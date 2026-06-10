"""Short Builder 製作引擎 — 供 Gradio App 呼叫。

把長影片(網址或本機檔)做成 9:16 直式短影音:下載 → 語音辨識 →
自動挑精華 → 剪輯裁切 → 燒錄字幕 →(可選)edge-tts 配音。
"""

import asyncio
import re
import shutil
import subprocess
from pathlib import Path


def hms(t):
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{int((t - int(t)) * 1000):03d}"


def acquire_video(source, workdir, log):
    local = Path(source)
    if local.exists():
        log(f"[1/5] 使用上傳檔案:{local.name}")
        return local.resolve(), local.stem

    import yt_dlp

    log(f"[1/5] 下載影片:{source}")
    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": str(workdir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=True)
    path = next(workdir.glob("source.*"))
    log(f"      完成:{info.get('title', 'short')}")
    return path, info.get("title", "short")


def transcribe(path, model_size, lang, log):
    from faster_whisper import WhisperModel

    try:
        import torch

        dev = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        dev = "cpu"
    ct = "float16" if dev == "cuda" else "int8"
    log(f"[2/5] 語音辨識(whisper-{model_size} / {dev})…")
    model = WhisperModel(model_size, device=dev, compute_type=ct)
    raw, info = model.transcribe(
        str(path),
        language=None if lang == "auto" else lang,
        word_timestamps=True,
        vad_filter=True,
    )
    segs = []
    for s in raw:
        text = s.text.strip()
        if text:
            segs.append(
                {
                    "start": s.start,
                    "end": s.end,
                    "text": text,
                    "words": [
                        {"w": w.word, "s": w.start, "e": w.end} for w in (s.words or [])
                    ],
                }
            )
    log(f"      語言:{info.language},共 {len(segs)} 句")
    return segs


def _score(window):
    dur = window[-1]["end"] - window[0]["start"]
    if dur <= 0:
        return 0.0
    chars = sum(len(s["text"]) for s in window)
    bonus = 0.0
    for s in window:
        if re.search(r"[!?!?]", s["text"]):
            bonus += 2.0
        if re.search(r"\d", s["text"]):
            bonus += 0.5
    return chars / dur + bonus * 0.3


def pick_highlights(segs, duration, n_clips):
    if not segs:
        return []
    cand = []
    for i in range(len(segs)):
        j = i
        while j + 1 < len(segs) and segs[j + 1]["end"] - segs[i]["start"] <= duration * 1.1:
            j += 1
        w = segs[i : j + 1]
        if w[-1]["end"] - w[0]["start"] < min(duration * 0.5, 10):
            continue
        cand.append((_score(w), w[0]["start"], w[-1]["end"], w))
    if not cand:
        return [(segs[0]["start"], segs[-1]["end"], segs)]
    cand.sort(key=lambda c: -c[0])
    picked = []
    for sc, st, en, w in cand:
        if any(not (en <= ps or st >= pe) for _, ps, pe, _ in picked):
            continue
        picked.append((sc, st, en, w))
        if len(picked) >= n_clips:
            break
    picked.sort(key=lambda c: c[1])
    return [(s, e, w) for _, s, e, w in picked]


def build_srt(window, clip_start, srt_path, max_chars=14, max_dur=2.2):
    words = [w for s in window for w in s["words"]] or [
        {"w": s["text"], "s": s["start"], "e": s["end"]} for s in window
    ]
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        t = "".join(x["w"] for x in cur).strip()
        if len(t) >= max_chars or cur[-1]["e"] - cur[0]["s"] >= max_dur:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    lines = []
    for i, c in enumerate(chunks, 1):
        st = max(0.0, c[0]["s"] - clip_start)
        en = max(st + 0.3, c[-1]["e"] - clip_start)
        lines.append(f"{i}\n{hms(st)} --> {hms(en)}\n{''.join(x['w'] for x in c).strip()}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return len(chunks)


SUB_STYLE = (
    "FontName=Noto Sans CJK TC,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=60,Alignment=2"
)


async def _tts(text, voice, path):
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(path))


def add_voiceover(clip, text, voice, keep_audio, workdir, out_path, log):
    vo = workdir / "vo.mp3"
    log(f"  [tts] 配音({voice})…")
    asyncio.run(_tts(text, voice, vo))
    if keep_audio:
        f = "[0:a]volume=0.15[bg];[1:a]apad[vo];[bg][vo]amix=inputs=2:duration=first[a]"
        args = [
            "-i", str(clip), "-i", str(vo), "-filter_complex", f,
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(out_path),
        ]
    else:
        args = [
            "-i", str(clip), "-i", str(vo), "-map", "0:v", "-map", "1:a",
            "-af", "apad", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args, check=True)


def build(
    source,
    duration=45,
    clips=1,
    start=None,
    end=None,
    lang="auto",
    model="small",
    voice="",
    keep_audio=False,
    subs=True,
    crop=True,
    out="output",
    log=print,
):
    """執行完整管線,回傳產出的影片路徑清單。`log` 可傳入收集進度訊息的函式。"""
    out_dir = Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / ".work"
    workdir.mkdir(exist_ok=True)

    video, title = acquire_video(source, workdir, log)
    segs = transcribe(video, model, lang, log) if (subs or voice or start is None) else []

    if start is not None:
        e = end if end is not None else start + duration
        window = [s for s in segs if s["end"] > start and s["start"] < e]
        segments = [(start, e, window)]
        log(f"[3/5] 手動片段 {start:.1f}s – {e:.1f}s")
    else:
        segments = pick_highlights(segs, duration, clips)
        log(f"[3/5] 自動挑出 {len(segments)} 段精華:")
        for s, e, w in segments:
            log(f"      {s:7.1f}s – {e:7.1f}s  「{(w[0]['text'][:20] if w else '')}…」")

    safe = re.sub(r"[^\w一-鿿-]+", "_", title)[:40].strip("_") or "short"
    results = []
    for idx, (s, e, window) in enumerate(segments, 1):
        log(f"[4/5] 剪輯第 {idx}/{len(segments)} 支…")
        pad = max(0.0, s - 0.2)
        raw = workdir / f"clip_{idx}.mp4"
        vf = []
        if crop:
            vf.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
        if subs and window:
            srt = workdir / f"clip_{idx}.srt"
            build_srt(window, pad, srt)
            vf.append(f"subtitles={srt.name}:force_style='{SUB_STYLE}'")
        cmd = ["-ss", f"{pad:.2f}", "-to", f"{e + 0.3:.2f}", "-i", str(video)]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(raw),
        ]
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + cmd,
            check=True,
            cwd=workdir,
        )
        final = out_dir / f"{safe}_short{idx}.mp4"
        if voice and window:
            log(f"[5/5] 配音第 {idx} 支…")
            add_voiceover(
                raw, "".join(x["text"] for x in window), voice, keep_audio, workdir, final, log
            )
        else:
            shutil.move(str(raw), final)
        log(f"  ✓ 完成第 {idx} 支")
        results.append(str(final))

    log(f"🎉 全部完成!共 {len(results)} 支短影音。")
    return results
