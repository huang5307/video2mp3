import os
import sys
import uuid
import asyncio
import zipfile
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

from core_splitter import VideoMusicSplitter, clean_filename, is_audio_file, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_UPLOADS_DIR = os.path.join(tempfile.gettempdir(), "Video2MP3_Uploads")
DEFAULT_OUTPUTS_DIR = os.path.join(str(Path.home()), "Music", "Video2MP3")
STATIC_DIR = os.path.join(BASE_DIR, "static")
PS_PICKER_SCRIPT = os.path.join(BASE_DIR, "pick_folder.ps1")

os.makedirs(DEFAULT_UPLOADS_DIR, exist_ok=True)
os.makedirs(DEFAULT_OUTPUTS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Video2MP3 Music Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: Dict[str, Dict[str, Any]] = {}

@app.get("/api/default-config")
def get_default_config():
    """取得預設配置與常見快捷目錄"""
    user_home = str(Path.home())
    quick_presets = [
        {"name": "系統音樂", "path": os.path.join(user_home, "Music", "Video2MP3")},
        {"name": "下載目錄", "path": os.path.join(user_home, "Downloads")},
        {"name": "桌面", "path": os.path.join(user_home, "Desktop")},
    ]
    if os.path.exists("D:\\"):
        quick_presets.append({"name": "D槽音樂", "path": "D:\\Music"})
    else:
        quick_presets.append({"name": "C槽音樂", "path": "C:\\Music"})

    return {
        "default_output_dir": DEFAULT_OUTPUTS_DIR,
        "default_upload_dir": DEFAULT_UPLOADS_DIR,
        "default_language": "zh-TW:TW",
        "quick_presets": quick_presets,
        "languages": [
            {"code": "zh-TW", "country": "TW", "label": "繁體中文 (亞洲歌曲原名優先)"},
            {"code": "ja-JP", "country": "JP", "label": "日語原名優先 (保留日文假名/漢字)"},
            {"code": "zh-CN", "country": "CN", "label": "簡體中文"},
            {"code": "en-US", "country": "US", "label": "英文 (English / 羅馬拼音)"}
        ]
    }

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    custom_upload_dir: str = Form(DEFAULT_UPLOADS_DIR)
):
    """上傳單一影片或音訊檔至自訂或系統暫存目錄"""
    target_upload_dir = custom_upload_dir.strip() if custom_upload_dir.strip() else DEFAULT_UPLOADS_DIR
    os.makedirs(target_upload_dir, exist_ok=True)

    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}_{clean_filename(file.filename)}"
    save_path = os.path.join(target_upload_dir, safe_name)
    
    async with aiofiles.open(save_path, 'wb') as out_file:
        while content := await file.read(1024 * 1024):  # 1MB chunk
            await out_file.write(content)
            
    is_audio = is_audio_file(file.filename)
    return {
        "status": "success",
        "filename": safe_name,
        "original_name": file.filename,
        "path": save_path,
        "is_audio": is_audio
    }

@app.post("/api/upload-multiple")
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    custom_upload_dir: str = Form(DEFAULT_UPLOADS_DIR)
):
    """批次上傳多個影片或音訊檔案"""
    target_upload_dir = custom_upload_dir.strip() if custom_upload_dir.strip() else DEFAULT_UPLOADS_DIR
    os.makedirs(target_upload_dir, exist_ok=True)

    results = []
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        safe_name = f"{file_id}_{clean_filename(file.filename)}"
        save_path = os.path.join(target_upload_dir, safe_name)
        
        async with aiofiles.open(save_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):
                await out_file.write(content)
                
        is_audio = is_audio_file(file.filename)
        results.append({
            "status": "success",
            "filename": safe_name,
            "original_name": file.filename,
            "path": save_path,
            "is_audio": is_audio
        })
    return {"files": results}

@app.post("/api/select-folder")
def select_folder_dialog(current_path: str = Form(DEFAULT_OUTPUTS_DIR)):
    """呼叫獨立置頂 PowerShell 視窗選擇資料夾"""
    init_dir = current_path if os.path.exists(current_path) else DEFAULT_OUTPUTS_DIR
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy", "Bypass",
        "-File", PS_PICKER_SCRIPT,
        "-InitialDir", init_dir
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        selected = proc.stdout.strip()
        if selected and selected != "CANCELLED" and os.path.exists(selected):
            return {"status": "success", "path": os.path.normpath(selected)}
        return {"status": "cancelled", "path": current_path}
    except Exception as e:
        return {"status": "error", "message": str(e), "path": current_path}

@app.post("/api/open-folder")
def open_output_folder(folder_path: str = Form(...)):
    """在 Windows 檔案總管中開啟指定資料夾"""
    clean_p = folder_path.strip().strip('"')
    if not os.path.exists(clean_p):
        os.makedirs(clean_p, exist_ok=True)

    if sys.platform == "win32":
        try:
            norm_p = os.path.normpath(clean_p)
            subprocess.Popen(['explorer.exe', norm_p])
            return {"status": "success", "opened": norm_p}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "unsupported"}

async def run_splitting_task(
    task_id: str,
    media_path: str,
    original_name: str,
    output_dir: str,
    language: str,
    endpoint_country: str,
    auto_delete_temp: bool = True
):
    """非同步背景切割任務（支援影片與音訊）"""
    def on_progress(p: Dict[str, Any]):
        if task_id in TASKS:
            TASKS[task_id].update(p)

    splitter = VideoMusicSplitter(
        output_dir=output_dir,
        language=language,
        endpoint_country=endpoint_country
    )

    is_audio = is_audio_file(media_path)

    try:
        raw_name = os.path.splitext(original_name)[0]
        clean_folder = clean_filename(raw_name)

        results = await splitter.split_and_process(
            media_path=media_path,
            custom_output_dir=output_dir,
            custom_folder_name=clean_folder,
            language=language,
            endpoint_country=endpoint_country,
            progress_cb=on_progress
        )
        TASKS[task_id]["status"] = "completed"
        TASKS[task_id]["progress"] = 100
        TASKS[task_id]["results"] = results
        TASKS[task_id]["is_audio"] = is_audio
        
        # 音訊檔直接在 output_dir 根目錄，影片檔在 output_dir/clean_folder
        if is_audio:
            TASKS[task_id]["folder_name"] = "根目錄"
            TASKS[task_id]["folder_path"] = output_dir
        else:
            TASKS[task_id]["folder_name"] = clean_folder
            TASKS[task_id]["folder_path"] = os.path.join(output_dir, clean_folder)

        # 自動刪除暫存上傳檔
        if auto_delete_temp and os.path.exists(media_path):
            try:
                if "Temp" in media_path or "Video2MP3_Uploads" in media_path:
                    os.remove(media_path)
            except Exception:
                pass

    except Exception as e:
        TASKS[task_id]["status"] = "failed"
        TASKS[task_id]["error"] = str(e)
        TASKS[task_id]["details"] = f"處理失敗: {str(e)}"

@app.post("/api/process")
async def start_process(
    background_tasks: BackgroundTasks,
    video_path: str = Form(...),
    video_name: str = Form(...),
    output_dir: str = Form(DEFAULT_OUTPUTS_DIR),
    language: str = Form("zh-TW"),
    endpoint_country: str = Form("TW"),
    auto_delete_temp: bool = Form(True)
):
    """發起切割或音訊處理任務"""
    if not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail="找不到指定的檔案")

    if not output_dir.strip():
        output_dir = DEFAULT_OUTPUTS_DIR
    os.makedirs(output_dir, exist_ok=True)

    is_audio = is_audio_file(video_name)
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "task_id": task_id,
        "video_name": video_name,
        "is_audio": is_audio,
        "status": "started",
        "progress": 0,
        "details": f"任務已初始化，準備開始分析{'音訊' if is_audio else '影片'}...",
        "output_dir": output_dir,
        "results": []
    }

    background_tasks.add_task(
        run_splitting_task,
        task_id,
        video_path,
        video_name,
        output_dir,
        language,
        endpoint_country,
        auto_delete_temp
    )
    return {"status": "started", "task_id": task_id}

@app.get("/api/task/{task_id}")
def get_task_status(task_id: str):
    """查詢任務進度與結果"""
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="找不到該任務")
    return TASKS[task_id]

@app.get("/api/audio-by-path")
def stream_audio_by_path(path: str):
    """在線試聽自訂路徑的 MP3 音訊"""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="找不到音訊檔案")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))

@app.get("/api/download-zip-by-path")
def download_zip_by_path(folder_path: str):
    """打包為 ZIP 下載自訂資料夾內的歌曲"""
    if not os.path.exists(folder_path):
        raise HTTPException(status_code=404, detail="資料夾不存在")

    folder_name = os.path.basename(folder_path)
    zip_path = os.path.join(os.path.dirname(folder_path), f"{folder_name}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_full = os.path.join(root, file)
                zipf.write(file_full, arcname=file)

    return FileResponse(zip_path, media_type="application/zip", filename=f"{folder_name}.zip")

# 掛載靜態前端資源
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>前端介面加載中...</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
