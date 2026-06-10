---
title: Short Builder
emoji: 🎬
colorFrom: red
colorTo: indigo
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
license: mit
---

# 🎬 Short Builder — 自動短影音製作

貼一個 YouTube / 影片網址(或上傳檔案),自動下載 → 語音辨識 → 挑精華 →
剪成 9:16 直式 → 燒錄字幕 →(可選)AI 配音。完全免費。

## 如何部署到 HuggingFace Spaces(免費)

1. 到 [huggingface.co/new-space](https://huggingface.co/new-space) 建立一個 Space:
   - **SDK** 選 **Gradio**
   - Hardware 用免費的 **CPU basic** 即可
2. 把這個 `hf-space/` 資料夾裡的四個檔案上傳到 Space:
   - `app.py`
   - `pipeline.py`
   - `requirements.txt`
   - `packages.txt`
   - `README.md`(就是這個檔,含最上方的設定區塊)
3. Space 會自動安裝並啟動。完成後你會得到一個固定網址,例如
   `https://huggingface.co/spaces/你的帳號/short-builder`,打開就能用,手機也行。

> 也可以用 `git` 直接 push:
> ```bash
> git clone https://huggingface.co/spaces/你的帳號/short-builder
> cp hf-space/* short-builder/ && cd short-builder
> git add . && git commit -m "init" && git push
> ```

## 注意

- 免費 Space 為 **CPU**,語音辨識較慢;長片建議用 `tiny`/`base`/`small` 模型,
  或在介面裡用「手動指定片段」只處理需要的一小段。
- 需要 GPU(更快)可在 Space 設定裡升級付費硬體,但**非必要**。
- 請只下載與剪輯你擁有權利或已獲授權的內容。
