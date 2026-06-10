# Short Builder — 自動短影音製作工具

給一個 YouTube(或任何 yt-dlp 支援的)網址或本機影片檔,自動完成整條短影音製作流程:

1. **下載影片**(yt-dlp)
2. **語音辨識**(faster-whisper)取得逐字稿與字詞時間軸
3. **自動挑精華**:用說話密度 + 驚嘆/疑問/數字加分的演算法,滑動視窗找出最有內容的片段
4. **剪輯成 9:16 直式**(ffmpeg,1080×1920,自動置中裁切)
5. **燒錄字幕**(大字、黑邊白字,適合手機觀看)
6. **配音**(可選,edge-tts 微軟語音,可取代原音或疊在原音上)

## 安裝

需要 Python 3.9+ 與 ffmpeg:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg
# macOS
brew install ffmpeg

pip install -r requirements.txt
```

第一次執行會自動下載 whisper 模型(small 約 460MB)。

## 使用

```bash
# 最簡單:自動挑 45 秒精華、加字幕、輸出到 ./output
python short_builder.py "https://www.youtube.com/watch?v=XXXX"

# 產生 3 支 30 秒短片
python short_builder.py "https://www.youtube.com/watch?v=XXXX" --clips 3 --duration 30

# 加上台灣中文女聲配音(取代原音)
python short_builder.py URL --voice zh-TW-HsiaoChenNeural

# 配音但保留原音當背景(降到 15% 音量)
python short_builder.py URL --voice zh-TW-HsiaoChenNeural --keep-audio

# 手動指定片段(120 秒到 165 秒),不靠自動挑選
python short_builder.py URL --start 120 --end 165

# 本機檔案也可以
python short_builder.py my_video.mp4 --duration 60
```

### 常用參數

| 參數 | 說明 | 預設 |
|---|---|---|
| `--duration` | 每支短片目標秒數 | 45 |
| `--clips` | 產生幾支短片 | 1 |
| `--start` / `--end` | 手動指定片段(秒),略過自動挑選 | — |
| `--lang` | 語音辨識語言(`zh`、`en`…) | 自動偵測 |
| `--model` | whisper 模型:`tiny`/`base`/`small`/`medium`/`large-v3` | `small` |
| `--voice` | edge-tts 配音聲音,不給就保留原音 | — |
| `--keep-audio` | 配音時保留原音當背景 | 關 |
| `--no-subs` | 不燒錄字幕 | 關 |
| `--no-crop` | 保留原始比例(不裁 9:16) | 關 |
| `--out` | 輸出資料夾 | `./output` |

### 配音聲音

常用 edge-tts 聲音(完整列表:`edge-tts --list-voices`):

- `zh-TW-HsiaoChenNeural` — 台灣中文・女
- `zh-TW-YunJheNeural` — 台灣中文・男
- `zh-CN-XiaoxiaoNeural` — 簡中・女
- `en-US-AriaNeural` — 英文・女

## 注意事項

- 中文影片建議至少用 `--model small`,`medium` 更準但較慢。
- 使用 `--voice` 取代原音時,字幕時間軸仍對應**原始語音**,配音語速若差很多會有些微不同步;`--keep-audio` 模式較不明顯。
- 自動挑選依賴語音內容,純音樂或無人聲影片請改用 `--start`/`--end`。
- 請只下載與剪輯你擁有權利或獲得授權的內容。
