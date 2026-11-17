@echo off
title Video2MP3 - 智慧音樂切分工具
chcp 65001 >nul
cd /d "%~dp0"

echo 正在啟動 Video2MP3 智慧音樂切分服務...
echo 請稍候，系統將自動為您開啟瀏覽器圖形介面...

:: 在背景或延遲 2 秒後開啟瀏覽器
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8000"

:: 啟動 Python Web 伺服器
python -m uvicorn app:app --host 127.0.0.1 --port 8000

pause
