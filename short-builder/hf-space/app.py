"""Short Builder — Gradio 網頁版(HuggingFace Spaces)。

貼一個 YouTube/影片網址(或上傳檔案),按一下就自動產出 9:16 直式短影音。
"""

import tempfile
import traceback
from pathlib import Path

import gradio as gr

from pipeline import build

VOICES = {
    "不配音(保留原音)": "",
    "台灣中文・女 (HsiaoChen)": "zh-TW-HsiaoChenNeural",
    "台灣中文・男 (YunJhe)": "zh-TW-YunJheNeural",
    "簡體中文・女 (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",
    "英文・女 (Aria)": "en-US-AriaNeural",
    "日文・女 (Nanami)": "ja-JP-NanamiNeural",
}


def make_shorts(url, upload, duration, clips, lang, model, voice_label,
                keep_audio, subs, crop, manual_start, manual_end,
                progress=gr.Progress()):
    source = (upload or "").strip() or (url or "").strip()
    if not source:
        raise gr.Error("請貼上影片網址,或上傳一個影片檔。")

    logs = []

    def log(msg):
        logs.append(str(msg))
        progress(min(0.95, 0.05 * len(logs)), desc=str(msg)[:60])

    out_dir = Path(tempfile.mkdtemp(prefix="shortbuilder_"))
    start = manual_start if manual_start and manual_start >= 0 else None
    end = manual_end if manual_end and manual_end >= 0 else None

    try:
        results = build(
            source,
            duration=int(duration),
            clips=int(clips),
            start=start,
            end=end,
            lang=lang,
            model=model,
            voice=VOICES.get(voice_label, ""),
            keep_audio=keep_audio,
            subs=subs,
            crop=crop,
            out=str(out_dir),
            log=log,
        )
    except Exception as e:
        logs.append(f"\n❌ 發生錯誤:{e}")
        logs.append(traceback.format_exc())
        return None, [], "\n".join(logs)

    preview = results[0] if results else None
    return preview, results, "\n".join(logs)


with gr.Blocks(title="Short Builder", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# 🎬 Short Builder — 自動短影音製作\n"
        "貼一個 **YouTube / 影片網址**(或上傳檔案),自動下載 → 語音辨識 → "
        "挑精華 → 剪成 9:16 直式 → 加字幕 →(可選)AI 配音。完全免費。"
    )

    with gr.Row():
        with gr.Column(scale=1):
            url = gr.Textbox(label="影片網址", placeholder="https://www.youtube.com/watch?v=...")
            upload = gr.Video(label="或上傳影片檔(可選)")

            with gr.Accordion("短片設定", open=True):
                duration = gr.Slider(15, 90, value=45, step=5, label="每支秒數")
                clips = gr.Slider(1, 5, value=1, step=1, label="產生幾支")
                with gr.Row():
                    crop = gr.Checkbox(value=True, label="裁成 9:16 直式")
                    subs = gr.Checkbox(value=True, label="加字幕")

            with gr.Accordion("語音辨識", open=False):
                lang = gr.Dropdown(
                    ["auto", "zh", "en", "ja", "ko"], value="auto", label="語言"
                )
                model = gr.Dropdown(
                    ["tiny", "base", "small", "medium", "large-v3"],
                    value="small",
                    label="模型(越大越準但越慢)",
                )

            with gr.Accordion("AI 配音", open=False):
                voice_label = gr.Dropdown(
                    list(VOICES.keys()), value="不配音(保留原音)", label="配音聲音"
                )
                keep_audio = gr.Checkbox(value=False, label="配音時保留原音當背景")

            with gr.Accordion("手動指定片段(進階)", open=False):
                manual_start = gr.Number(value=-1, label="起點秒(-1 = 自動挑選)")
                manual_end = gr.Number(value=-1, label="終點秒(-1 = 自動)")

            run = gr.Button("🚀 開始製作", variant="primary")

        with gr.Column(scale=1):
            preview = gr.Video(label="預覽(第一支)")
            files = gr.File(label="下載全部短影音", file_count="multiple")
            log_box = gr.Textbox(label="進度紀錄", lines=14, max_lines=20)

    run.click(
        make_shorts,
        inputs=[url, upload, duration, clips, lang, model, voice_label,
                keep_audio, subs, crop, manual_start, manual_end],
        outputs=[preview, files, log_box],
    )

    gr.Markdown(
        "> 第一次製作會下載 whisper 模型(small 約 460MB),請稍候。"
        "請只下載與剪輯你擁有權利或已獲授權的內容。"
    )


if __name__ == "__main__":
    demo.queue().launch()
