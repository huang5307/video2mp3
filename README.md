# Video2MP3 - 智慧音樂切分與辨識工具

專為「音樂合輯影片、演唱會、音樂檔案、BGM 合輯」設計的全自動歌曲切分與標籤辨識工具。
**提供現代化 Web 圖形介面（雙擊即用）與強大的 CLI 命令列介面（方便 AI Agent、自動化腳本或第三方程序調用）。**

---

## ✨ 核心特色與命名規則

1. **支援批次多檔案佇列（影片 / 音訊雙支援）**：
   - 支援同時拖曳多個影片（MP4, MKV, AVI, MOV 等）與音訊（MP3, WAV, FLAC, M4A, OGG 等）。
   - 視覺化待處理隊列清單，支援一鍵批次連續處理。
2. **音訊檔案（Audio）專屬智慧處理規則**：
   - **單曲音訊**：免去繁瑣切分，自動識別歌名與演唱者，重命名為標準 `{Artist} - {Title}.mp3`，**直接輸出於 Output 根目錄，不建立子資料夾**。
   - **多曲長音訊合輯**：自動尋找歌曲邊界進行切分與聽歌識別，**同樣直接輸出至 Output 根目錄，不建立子資料夾**。
3. **已識別歌曲全新命名（歌手聚合排序）**：
   - 命名格式：**`{Artist} .{序號} - {Title}.mp3`**
   - **範例**：
     * `Chicago .04 - Hard to Say I'm Sorry.mp3`
     * `Richard Marx .01 - Right Here Waiting.mp3`
   - **核心優勢**：當所有歌曲放在 Output 根目錄按檔名排序時，**同一位歌手的所有歌曲會完美集中排列在一起**，不再被開頭的序號打散！
4. **未識別歌曲命名（母檔聚合排序）**：
   - 命名格式：**`{母檔名}_Track{序號}.mp3`**
   - **範例**：
     * `那些经典的日语歌_Track01.mp3`
     * `那些经典的日语歌_Track02.mp3`
   - 徹底移除無助可讀性的時間軸括號，同一個母檔切出的歌曲自然緊貼排列在一起。
5. **影片檔案（Video）處理規則**：
   - 保持資料庫整齊，在 Output 目錄下建立以原始影片名稱命名的專屬子資料夾進行分類存放。
6. **專案 100% 零殘留**：
   - Output 輸出目錄與 Uploads 暫存目錄皆完全獨立於專案目錄。
   - 支援轉碼完成後自動清理上傳的大暫存檔案，釋放硬碟空間。

---

## 🤖 CLI 命令列模式（AI Agent / 自動化串接專用）

在 AI 時代，Video2MP3 提供完整的命令列介面 `cli.py`，所有功能皆可透過參數調用，並支援將結果輸出為標準 JSON 格式至 `stdout`，方便 AI Agent、Shell 腳本或後台服務無縫整合。

### 1. 基本用法

```bash
python cli.py [選項]
```

### 2. 常用命令範例

#### ① 處理單一影片或音訊檔案
```bash
python cli.py -i "concert.mp4"
python cli.py -i "song_collection.mp3"
```

#### ② 批次處理多個檔案並指定輸出資料夾
```bash
python cli.py -i "video1.mp4" "video2.mkv" "album.mp3" -o "D:\MyMusic\Output"
```

#### ③ 批次掃描並處理整個資料夾內的音樂或影片
```bash
python cli.py -d "C:\Users\Downloads\MusicVideos" -o "D:\Music"
```

#### ④ 指定語言偏好（例如：日文歌曲保留日文原生字符）
```bash
python cli.py -i "jpop_live.mp4" --lang ja-JP
```
> 支援語言選項：`zh-TW`（繁體中文，預設）、`ja-JP`（日文）、`zh-CN`（簡體中文）、`en-US`（英文）。

#### ⑤ AI Agent / 腳本串接模式（輸出結構化 JSON）
使用 `--json` 參數時，即時進度會導向 `stderr`，而最終結構化分析結果會輸出為乾淨的 JSON 字串至 `stdout`：
```bash
python cli.py -i "concert.mp4" --output "D:\Music" --json
```

**JSON 輸出結構範例：**
```json
{
  "status": "success",
  "total_files": 1,
  "output_directory": "C:\\Users\\kangl\\Music\\Video2MP3",
  "tasks": [
    {
      "file": "C:\\Users\\kangl\\Downloads\\陳昇【最後一次溫柔】.mp4",
      "file_name": "陳昇【最後一次溫柔】.mp4",
      "is_audio": false,
      "status": "success",
      "output_directory": "C:\\Users\\kangl\\Music\\Video2MP3\\陳昇【最後一次溫柔】",
      "song_count": 1,
      "results": [
        {
          "index": 1,
          "title": "最后一次温柔(Rough Road)",
          "artist": "陈升",
          "album": "Single",
          "duration": 288.3,
          "start_time": 0.0,
          "end_time": 288.3,
          "file_name": "陈升 .01 - 最后一次温柔(Rough Road).mp3",
          "file_path": "C:\\Users\\kangl\\Music\\Video2MP3\\陳昇【最後一次溫柔】\\陈升 .01 - 最后一次温柔(Rough Road).mp3",
          "cover_url": "https://is1-ssl.mzstatic.com/image/thumb/Music/6b/e3/7d/mzi.wjjenmpu.jpg/400x400cc.jpg"
        }
      ]
    }
  ]
}
```

#### ⑥ 透過 CLI 啟動 Web UI 服務
```bash
python cli.py --web
# 或自訂連接埠與主機位址
python cli.py --web --host 0.0.0.0 --port 8080
```

---

### 3. CLI 完整參數清單

| 參數 | 完整名稱 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- |
| `-i` | `--input` | 輸入的影片或音訊檔案路徑（支援傳入多個路徑或萬用字元 `*.mp4`） | 無 |
| `-d` | `--dir` | 遞迴掃描並處理指定資料夾內的所有支援媒體檔案 | 無 |
| `-o` | `--output` | 自訂 Output 匯出根目錄 | `~/Music/Video2MP3` |
| `-l` | `--lang` | 歌曲名稱辨識偏好語言：`zh-TW`, `ja-JP`, `zh-CN`, `en-US` | `zh-TW` |
| `-c` | `--country` | Shazam API 地區代碼（如 `TW`, `JP`, `US`, `CN`） | 自動對應語言 |
| `--json` | `--json` | 以標準 JSON 格式將切分與辨識結果輸出至 `stdout` | 關閉 |
| `-q` | `--quiet` | 安靜模式，不印出動態進度條 | 關閉 |
| `--web` | `--web` | 一鍵啟動 Web 圖形介面服務 | 關閉 |
| `--host` | `--host` | Web 伺服器綁定 IP | `127.0.0.1` |
| `--port` | `--port` | Web 伺服器連接埠 | `8000` |

---

## 🚀 Web 圖形介面啟動方式

若偏好使用瀏覽器圖形操作：
1. **滑鼠雙擊 [`start_app.bat`](file:///c:/Users/kangl/OneDrive/Projects/video2mp3/start_app.bat)** 或在終端機輸入 `python cli.py --web`。
2. 瀏覽器自動開啟操作介面：[http://127.0.0.1:8000](http://127.0.0.1:8000)。
3. 支援拖曳多個影片或音訊檔案進入佇列，自訂輸出與暫存資料夾，即時預覽切分進度與專輯封面。
