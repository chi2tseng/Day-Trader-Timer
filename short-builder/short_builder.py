#!/usr/bin/env python3
"""Short Builder — 自動短影音製作工具。

給一個 YouTube(或其他 yt-dlp 支援的)網址或本機影片檔,自動:
  1. 下載影片
  2. 語音辨識(faster-whisper)取得逐字稿與時間軸
  3. 自動挑選最精華的片段(也可手動指定 --start/--end)
  4. 剪輯並裁切成 9:16 直式短影音
  5. 燒錄字幕
  6. (可選)用 edge-tts 重新配音

用法範例:
  python short_builder.py "https://www.youtube.com/watch?v=XXXX"
  python short_builder.py video.mp4 --duration 30 --clips 3
  python short_builder.py URL --voice zh-TW-HsiaoChenNeural
  python short_builder.py URL --start 120 --end 165
"""

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- utilities

def run_ffmpeg(args, desc):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args
    print(f"  [ffmpeg] {desc}")
    subprocess.run(cmd, check=True)


def hms(t):
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------- 1. download

def acquire_video(source, workdir):
    """下載網址影片,或直接使用本機檔案。回傳 (path, title)。"""
    local = Path(source)
    if local.exists():
        local = local.resolve()
        print(f"[1/5] 使用本機檔案:{local}")
        return local, local.stem

    import yt_dlp
    print(f"[1/5] 下載影片:{source}")
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
    title = info.get("title", "short")
    print(f"      完成:{title}")
    return path, title


# ---------------------------------------------------------------- 2. transcribe

def transcribe(path, model_size, lang):
    """語音辨識,回傳 (segments, 偵測到的語言)。"""
    from faster_whisper import WhisperModel

    print(f"[2/5] 語音辨識(whisper-{model_size},第一次執行會下載模型)…")
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    raw, info = model.transcribe(
        str(path),
        language=None if lang == "auto" else lang,
        word_timestamps=True,
        vad_filter=True,
    )
    segs = []
    for s in raw:
        words = [
            {"w": w.word, "s": w.start, "e": w.end}
            for w in (s.words or [])
        ]
        text = s.text.strip()
        if text:
            segs.append({"start": s.start, "end": s.end, "text": text, "words": words})
    print(f"      語言:{info.language},共 {len(segs)} 句")
    return segs, info.language


# ---------------------------------------------------------------- 3. highlights

def window_score(window):
    """片段評分:說話密度高、含驚嘆/疑問/數字的句子加分。"""
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
    """滑動視窗找出 n 個互不重疊、評分最高的片段,回傳 [(start, end, segs)]。"""
    if not segs:
        return []
    candidates = []
    for i in range(len(segs)):
        j = i
        while (
            j + 1 < len(segs)
            and segs[j + 1]["end"] - segs[i]["start"] <= duration * 1.1
        ):
            j += 1
        window = segs[i : j + 1]
        dur = window[-1]["end"] - window[0]["start"]
        if dur < min(duration * 0.5, 10):
            continue  # 太短的視窗不收
        candidates.append(
            (window_score(window), window[0]["start"], window[-1]["end"], window)
        )
    if not candidates:  # 整部影片語音太少,退回整段
        return [(segs[0]["start"], segs[-1]["end"], segs)]
    candidates.sort(key=lambda c: -c[0])

    picked = []
    for score, start, end, window in candidates:
        if any(not (end <= ps or start >= pe) for _, ps, pe, _ in picked):
            continue  # 與已選片段重疊
        picked.append((score, start, end, window))
        if len(picked) >= n_clips:
            break
    picked.sort(key=lambda c: c[1])  # 依時間排序輸出
    return [(s, e, w) for _, s, e, w in picked]


# ---------------------------------------------------------------- 4. subtitles

def build_srt(window, clip_start, srt_path, max_chars=14, max_dur=2.2):
    """把字詞時間軸切成適合短影音的小段字幕(SRT,時間相對於剪輯起點)。"""
    words = [w for s in window for w in s["words"]]
    if not words:  # 沒有逐字時間軸就退回整句
        words = [
            {"w": s["text"], "s": s["start"], "e": s["end"]} for s in window
        ]

    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = "".join(x["w"] for x in cur).strip()
        if len(text) >= max_chars or cur[-1]["e"] - cur[0]["s"] >= max_dur:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    lines = []
    for i, chunk in enumerate(chunks, 1):
        start = max(0.0, chunk[0]["s"] - clip_start)
        end = max(start + 0.3, chunk[-1]["e"] - clip_start)
        text = "".join(x["w"] for x in chunk).strip()
        lines.append(f"{i}\n{hms(start)} --> {hms(end)}\n{text}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return len(chunks)


SUB_STYLE = (
    "FontName=Noto Sans TC,FontSize=15,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=1,MarginV=60,Alignment=2"
)


# ---------------------------------------------------------------- 5. voiceover

async def tts_save(text, voice, path):
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(path))


def add_voiceover(clip, text, voice, keep_audio, workdir, out_path):
    """用 edge-tts 產生配音,取代(或疊在)原始音軌。"""
    vo = workdir / "voiceover.mp3"
    print(f"  [tts] 產生配音({voice})…")
    asyncio.run(tts_save(text, voice, vo))

    if keep_audio:
        # 原音降到 15%,疊上配音
        run_ffmpeg(
            [
                "-i", str(clip), "-i", str(vo),
                "-filter_complex",
                "[0:a]volume=0.15[bg];[1:a]apad[vo];"
                "[bg][vo]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac",
                str(out_path),
            ],
            "混合原音與配音",
        )
    else:
        run_ffmpeg(
            [
                "-i", str(clip), "-i", str(vo),
                "-map", "0:v", "-map", "1:a",
                "-af", "apad",
                "-c:v", "copy", "-c:a", "aac",
                "-shortest",
                str(out_path),
            ],
            "以配音取代原始音軌",
        )


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Short Builder — 自動把長影片剪成直式短影音(字幕+配音)"
    )
    ap.add_argument("source", help="YouTube/其他網址,或本機影片檔路徑")
    ap.add_argument("--duration", type=float, default=45, help="每支短片目標秒數(預設 45)")
    ap.add_argument("--clips", type=int, default=1, help="要產生幾支短片(預設 1)")
    ap.add_argument("--start", type=float, help="手動指定片段起點(秒),會略過自動挑選")
    ap.add_argument("--end", type=float, help="手動指定片段終點(秒)")
    ap.add_argument("--lang", default="auto", help="語音辨識語言(預設自動偵測,如 zh、en)")
    ap.add_argument("--model", default="small", help="whisper 模型大小:tiny/base/small/medium/large-v3")
    ap.add_argument("--voice", help="edge-tts 配音聲音,如 zh-TW-HsiaoChenNeural(不給就保留原音)")
    ap.add_argument("--keep-audio", action="store_true", help="配音時保留原音(降至 15%% 當背景)")
    ap.add_argument("--no-subs", action="store_true", help="不燒錄字幕")
    ap.add_argument("--no-crop", action="store_true", help="保留原始畫面比例(不裁成 9:16)")
    ap.add_argument("--out", default="output", help="輸出資料夾(預設 ./output)")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("錯誤:找不到 ffmpeg,請先安裝(apt install ffmpeg / brew install ffmpeg)")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / ".work"
    workdir.mkdir(exist_ok=True)

    # 1. 取得影片
    video, title = acquire_video(args.source, workdir)

    # 2. 語音辨識(挑片段與字幕都需要)
    need_transcript = not args.no_subs or args.voice or args.start is None
    segs = []
    if need_transcript:
        segs, _ = transcribe(video, args.model, args.lang)

    # 3. 決定片段
    if args.start is not None:
        end = args.end if args.end is not None else args.start + args.duration
        window = [s for s in segs if s["end"] > args.start and s["start"] < end]
        clips = [(args.start, end, window)]
        print(f"[3/5] 使用手動片段 {args.start:.1f}s – {end:.1f}s")
    else:
        clips = pick_highlights(segs, args.duration, args.clips)
        if not clips:
            sys.exit("找不到可用片段(影片可能沒有語音)。可改用 --start/--end 手動指定。")
        print(f"[3/5] 自動挑出 {len(clips)} 個精華片段:")
        for s, e, w in clips:
            preview = w[0]["text"][:20] if w else ""
            print(f"      {s:7.1f}s – {e:7.1f}s  「{preview}…」")

    # 4. 逐支輸出
    safe_title = re.sub(r"[^\w一-鿿-]+", "_", title)[:40].strip("_")
    for idx, (start, end, window) in enumerate(clips, 1):
        print(f"[4/5] 剪輯第 {idx}/{len(clips)} 支({start:.1f}s – {end:.1f}s)…")
        pad_start = max(0.0, start - 0.2)
        clip_raw = workdir / f"clip_{idx}.mp4"

        vf = []
        if not args.no_crop:
            vf.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
        if not args.no_subs and window:
            srt = workdir / f"clip_{idx}.srt"
            n = build_srt(window, pad_start, srt)
            print(f"  [subs] 產生 {n} 段字幕")
            vf.append(f"subtitles={srt.name}:force_style='{SUB_STYLE}'")

        cmd = ["-ss", f"{pad_start:.2f}", "-to", f"{end + 0.3:.2f}", "-i", str(video)]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(clip_raw),
        ]
        # subtitles filter 用相對路徑,所以在 workdir 執行
        print("  [ffmpeg] 剪輯+裁切+字幕")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + cmd,
            check=True,
            cwd=workdir,
        )

        final = out_dir / f"{safe_title}_short{idx}.mp4"
        if args.voice and window:
            print(f"[5/5] 配音第 {idx} 支…")
            text = "".join(s["text"] for s in window)
            add_voiceover(clip_raw, text, args.voice, args.keep_audio, workdir, final)
        else:
            shutil.move(str(clip_raw), final)
        print(f"  ✓ 輸出:{final}")

    print(f"\n完成!{len(clips)} 支短影音已存到 {out_dir}/")


if __name__ == "__main__":
    main()
