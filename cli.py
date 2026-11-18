#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Video2MP3 - Command Line Interface (CLI)
支援影片與音訊檔案的自動歌曲切分、Shazam 聲學指紋辨識與標準 MP3 匯出。
便於被其他自動化腳本、AI Agent 或第三方程式透過命令列調用。
"""

import sys
import os
import argparse
import asyncio
import json
import glob
import warnings
from pathlib import Path
from typing import List, Dict, Any, Optional

warnings.filterwarnings("ignore")

from core_splitter import (
    VideoMusicSplitter,
    clean_filename,
    is_audio_file,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS
)

SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)
DEFAULT_OUTPUT_DIR = str(Path.home() / "Music" / "Video2MP3")

def print_progress(status: str, progress: float, details: str, quiet: bool = False):
    """進度回報回呼"""
    if not quiet:
        bar_len = 25
        filled = int(bar_len * progress / 100)
        bar = '=' * filled + '-' * (bar_len - filled)
        sys.stderr.write(f"\r[{bar}] {progress:5.1f}% | {details:<50}")
        sys.stderr.flush()
        if progress >= 100:
            sys.stderr.write("\n")
            sys.stderr.flush()

async def process_file(
    splitter: VideoMusicSplitter,
    file_path: str,
    output_dir: str,
    language: str,
    endpoint_country: str,
    quiet: bool = False
) -> Dict[str, Any]:
    """處理單一檔案（影片或音訊）"""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return {
            "file": file_path,
            "status": "error",
            "error": f"找不到指定檔案: {file_path}",
            "results": []
        }

    file_name = os.path.basename(abs_path)
    is_audio = is_audio_file(abs_path)
    parent_name = clean_filename(os.path.splitext(file_name)[0])

    if not quiet:
        print(f"\n[Video2MP3 CLI] 正在處理: {file_name} ({'音訊' if is_audio else '影片'})", file=sys.stderr)

    def on_progress(p: Dict[str, Any]):
        print_progress(p.get("status", ""), p.get("progress", 0.0), p.get("details", ""), quiet=quiet)

    try:
        results = await splitter.split_and_process(
            media_path=abs_path,
            custom_output_dir=output_dir,
            custom_folder_name=parent_name,
            language=language,
            endpoint_country=endpoint_country,
            progress_cb=on_progress
        )

        dest_folder = output_dir if is_audio else os.path.join(output_dir, parent_name)
        return {
            "file": abs_path,
            "file_name": file_name,
            "is_audio": is_audio,
            "status": "success",
            "output_directory": dest_folder,
            "song_count": len(results),
            "results": results
        }
    except Exception as e:
        if not quiet:
            sys.stderr.write(f"\n[錯誤] 處理失敗 {file_name}: {e}\n")
        return {
            "file": abs_path,
            "file_name": file_name,
            "status": "failed",
            "error": str(e),
            "results": []
        }

def collect_files(inputs: List[str], recursive_dir: Optional[str] = None) -> List[str]:
    """收集所有符合副檔名的輸入檔案（支援萬用字元與目錄遍歷）"""
    target_files = []

    # 處理輸入檔案清單
    if inputs:
        for item in inputs:
            # 支援 glob 通配符（如 *.mp4）
            matched = glob.glob(item)
            if matched:
                for m in matched:
                    if os.path.isfile(m):
                        ext = os.path.splitext(m)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            target_files.append(os.path.abspath(m))
                    elif os.path.isdir(m):
                        # 如果輸入的是目錄，收集目錄內檔案
                        for root, _, files in os.walk(m):
                            for f in files:
                                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                                    target_files.append(os.path.abspath(os.path.join(root, f)))
            elif os.path.isfile(item):
                target_files.append(os.path.abspath(item))

    # 處理 --dir 目錄參數
    if recursive_dir and os.path.isdir(recursive_dir):
        for root, _, files in os.walk(recursive_dir):
            for f in files:
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                    target_files.append(os.path.abspath(os.path.join(root, f)))

    # 去重並維持排序
    seen = set()
    unique_files = []
    for f in target_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files

async def main_async(args):
    # 如果指定啟動 Web 伺服器
    if getattr(args, "web", False):
        import uvicorn
        print(f"[Video2MP3] 正在啟動 Web 圖形介面服務：http://{args.host}:{args.port} ...", file=sys.stderr)
        uvicorn.run("app:app", host=args.host, port=args.port, reload=False)
        return

    # 收集待處理檔案
    files_to_process = collect_files(args.input, args.dir)
    if not files_to_process:
        print("[錯誤] 未指定有效或存在的影片/音訊檔案。請使用 -i/--input 指定檔案或使用 -d/--dir 指定資料夾。", file=sys.stderr)
        print("使用 python cli.py --help 查看說明。", file=sys.stderr)
        sys.exit(1)

    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)

    # 語言與地區匹配
    lang_map = {
        "zh-tw": ("zh-TW", "TW"),
        "ja-jp": ("ja-JP", "JP"),
        "zh-cn": ("zh-CN", "CN"),
        "en-us": ("en-US", "US")
    }
    lang_key = args.lang.lower()
    default_lang, default_country = lang_map.get(lang_key, (args.lang, args.country or "TW"))
    if args.country:
        default_country = args.country

    splitter = VideoMusicSplitter(
        output_dir=output_dir,
        language=default_lang,
        endpoint_country=default_country
    )

    if not args.quiet and not args.json:
        print("=" * 60, file=sys.stderr)
        print(" Video2MP3 CLI 音樂切分與辨識工具", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"待處理檔案數量 : {len(files_to_process)}", file=sys.stderr)
        print(f"Output 輸出目錄: {output_dir}", file=sys.stderr)
        print(f"識別偏好語言   : {default_lang} ({default_country})", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    all_results = []
    for idx, f_path in enumerate(files_to_process, 1):
        if not args.quiet and not args.json:
            print(f"\n>> 處理隊列 [{idx}/{len(files_to_process)}]", file=sys.stderr)

        res = await process_file(
            splitter=splitter,
            file_path=f_path,
            output_dir=output_dir,
            language=default_lang,
            endpoint_country=default_country,
            quiet=args.quiet or args.json
        )
        all_results.append(res)

    # 輸出結構化結果
    if args.json:
        # 機器可讀 JSON 格式輸出到 stdout
        print(json.dumps({
            "status": "success",
            "total_files": len(files_to_process),
            "output_directory": output_dir,
            "tasks": all_results
        }, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print("\n" + "=" * 60, file=sys.stderr)
        print(" 全部處理完成！匯出成果總結：", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for r in all_results:
            status_icon = "✅" if r.get("status") == "success" else "❌"
            print(f"{status_icon} {r.get('file_name')} -> 共匯出 {r.get('song_count', 0)} 首 (存放於: {r.get('output_directory')})", file=sys.stderr)
            for s in r.get("results", []):
                print(f"    - #{s.get('index')} {s.get('file_name')} ({s.get('duration')}s)", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(
        description="Video2MP3 CLI - 支援影片與音訊的自動歌曲切分、Shazam 聽歌辨識與 MP3 匯出工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
調用範例:
  # 處理單一影片
  python cli.py -i "concert.mp4"

  # 批次處理多個音訊/影片並輸出到指定資料夾
  python cli.py -i "video1.mp4" "song2.mp3" -o "D:\\Music"

  # 批次處理整個資料夾內的所有音樂影片
  python cli.py -d "C:\\Users\\Downloads\\Videos" -o "D:\\Music"

  # 指定日文原名優先並輸出 JSON 格式 (便於 AI Agent 或管線程式解析)
  python cli.py -i "jpop.mp4" --lang ja-JP --json

  # 一鍵啟動 Web UI 圖形介面
  python cli.py --web
        """
    )

    parser.add_argument("-i", "--input", nargs="*", default=[], help="輸入的影片或音訊檔案路徑（支援多個檔案或 *.mp4 萬用字元）")
    parser.add_argument("-d", "--dir", default=None, help="批次掃描並處理指定資料夾內的所有媒體檔案")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR, help=f"自訂 Output 輸出根目錄 (預設: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("-l", "--lang", default="zh-TW", help="歌曲名稱辨識偏好語言: zh-TW(預設), ja-JP, zh-CN, en-US")
    parser.add_argument("-c", "--country", default=None, help="地區代碼 (例如: TW, JP, CN, US)")
    parser.add_argument("--json", action="store_true", help="以標準 JSON 格式將結果輸出至 stdout (便於 AI Agent 或其他程式串接)")
    parser.add_argument("-q", "--quiet", action="store_true", help="安靜模式，不印出即時進度條")
    
    # Web UI 控制參數
    parser.add_argument("--web", action="store_true", help="啟動 Web 圖形介面伺服器")
    parser.add_argument("--host", default="127.0.0.1", help="Web 伺服器 Host (預設 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Web 伺服器 Port (預設 8000)")

    args = parser.parse_args()
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()
