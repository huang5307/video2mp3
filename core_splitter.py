import asyncio
import os
import re
import json
import subprocess
import aiohttp
import tempfile
import shutil
from typing import List, Dict, Any, Callable, Optional, Tuple
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from shazamio import Shazam

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.wma', '.aiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.ts', '.m4v'}

def is_audio_file(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext in AUDIO_EXTENSIONS

def clean_filename(s: str) -> str:
    """清理 Windows / Linux 不允許的檔名特殊字元，保留各國文字"""
    s = re.sub(r'^[a-f0-9]{8}_', '', s)  # 移除上傳時生成的 8 位 UUID 前綴
    s = re.sub(r'[\\/*?:"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else "Untitled"

def get_media_duration(file_path: str) -> float:
    """使用 ffprobe 獲取媒體總時長（秒）"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def detect_silence_candidates(media_path: str, noise_db: int = -24, min_duration: float = 0.35) -> List[float]:
    """使用 FFmpeg 偵測所有潛在靜音切分點"""
    cmd = [
        'ffmpeg', '-i', media_path,
        '-af', f'silencedetect=noise={noise_db}dB:d={min_duration}',
        '-f', 'null', '-'
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
    
    silences = []
    current_start = None
    for line in res.stderr.splitlines():
        if 'silence_start:' in line:
            m = re.search(r'silence_start:\s*([0-9.]+)', line)
            if m:
                current_start = float(m.group(1))
        elif 'silence_end:' in line:
            m = re.search(r'silence_end:\s*([0-9.]+)', line)
            if m and current_start is not None:
                end_time = float(m.group(1))
                mid = (current_start + end_time) / 2.0
                silences.append(mid)
                current_start = None
    return silences

class VideoMusicSplitter:
    def __init__(self, output_dir: str = "outputs", language: str = "zh-TW", endpoint_country: str = "TW"):
        self.output_dir = output_dir
        self.language = language
        self.endpoint_country = endpoint_country
        os.makedirs(self.output_dir, exist_ok=True)

    def get_shazam_instance(self) -> Shazam:
        return Shazam(language=self.language, endpoint_country=self.endpoint_country)

    async def identify_audio_file(self, audio_path: str) -> Optional[Dict[str, Any]]:
        """直接對音訊檔案進行 Shazam 全曲指紋特徵比對"""
        try:
            shazam = self.get_shazam_instance()
            res = await asyncio.wait_for(shazam.recognize(audio_path), timeout=10.0)
            track = res.get('track') if res else None
            if not track:
                return None
            
            title = track.get('title')
            artist = track.get('subtitle')
            images = track.get('images', {})
            cover_url = images.get('coverarthq') or images.get('coverart')
            
            album = None
            for section in track.get('sections', []):
                if section.get('type') == 'SONG':
                    for meta in section.get('metadata', []):
                        if meta.get('title') == 'Album':
                            album = meta.get('text')
            
            return {
                'title': title,
                'artist': artist,
                'album': album or "Single",
                'cover_url': cover_url,
                'track_id': f"{artist} - {title}".lower().strip()
            }
        except Exception:
            return None

    async def identify_clip(self, media_path: str, start_sec: float, duration_sec: float = 14.0) -> Optional[Dict[str, Any]]:
        """在指定時間截取一小段音訊，交由 Shazam 辨識"""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            temp_path = tf.name
        
        try:
            cmd = [
                'ffmpeg', '-ss', f"{max(0, start_sec):.2f}",
                '-t', f"{duration_sec:.2f}",
                '-i', media_path,
                '-vn', '-ac', '2', '-ar', '44100',
                '-b:a', '128k',
                temp_path, '-y'
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            return await self.identify_audio_file(temp_path)
        except Exception:
            return None
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    async def identify_segment_robust(self, media_path: str, start: float, end: float) -> Optional[Dict[str, Any]]:
        """多點自適應抽樣辨識：在 50%、25%、75% 三個關鍵位置依次嘗試"""
        dur = end - start
        sample_offsets = [0.5 * dur, 0.25 * dur, 0.75 * dur]
        for offset in sample_offsets:
            probe_time = start + offset
            info = await self.identify_clip(media_path, probe_time - 7.0, duration_sec=14.0)
            if info and info.get('title') and info.get('artist'):
                return info
        return None

    async def process_single_audio(
        self,
        audio_path: str,
        custom_output_dir: str,
        parent_name: str,
        report_cb: Callable[[str, float, str], None]
    ) -> List[Dict[str, Any]]:
        """處理單曲音訊檔：直接辨識並輸出至 Output 根目錄（無子目錄）"""
        report_cb("identifying", 30, f"正在識別單曲音訊元數據...")
        info = await self.identify_audio_file(audio_path)
        
        title = info['title'] if info and info.get('title') else parent_name
        artist = info['artist'] if info and info.get('artist') else ""
        album = info.get('album', '') if info else ""
        cover_url = info.get('cover_url') if info else None

        if artist:
            safe_base = clean_filename(f"{artist} - {title}")
        else:
            safe_base = clean_filename(title)
        
        out_mp3_name = f"{safe_base}.mp3"
        out_mp3_path = os.path.join(custom_output_dir, out_mp3_name)

        report_cb("converting", 60, f"正在匯出標準 MP3 檔案至 Output 根目錄: {out_mp3_name}...")
        
        # 轉碼為 320k mp3
        cmd = [
            'ffmpeg', '-i', audio_path,
            '-vn', '-c:a', 'libmp3lame', '-b:a', '320k',
            out_mp3_path, '-y'
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        # 寫入 ID3 標籤
        try:
            try:
                audio = EasyID3(out_mp3_path)
            except Exception:
                audio = MP3(out_mp3_path, ID3=EasyID3)
                audio.add_tags()
            audio['title'] = title
            if artist:
                audio['artist'] = artist
            if album:
                audio['album'] = album
            audio.save()

            if cover_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(cover_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                mp3_tags = ID3(out_mp3_path)
                                mp3_tags.add(APIC(
                                    encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data
                                ))
                                mp3_tags.save()
                except Exception:
                    pass
        except Exception:
            pass

        dur = get_media_duration(out_mp3_path)
        report_cb("completed", 100, f"單曲處理完成！已儲存至根目錄：{out_mp3_name}")
        return [{
            'index': 1,
            'title': title,
            'artist': artist or "Unknown Artist",
            'album': album,
            'duration': round(dur, 1),
            'start_time': 0.0,
            'end_time': round(dur, 1),
            'file_name': out_mp3_name,
            'file_path': out_mp3_path,
            'cover_url': cover_url
        }]

    async def split_and_process(
        self,
        media_path: str,
        custom_output_dir: Optional[str] = None,
        custom_folder_name: Optional[str] = None,
        language: Optional[str] = None,
        endpoint_country: Optional[str] = None,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
        min_song_duration: float = 90.0
    ) -> List[Dict[str, Any]]:
        """
        支援影片與音訊的切分與處理
        規則：
        - 影片檔：在 custom_output_dir 建立子目錄儲存。
        - 音訊檔（單曲或多曲）：直接放在 custom_output_dir 根目錄，不建立子目錄。
        - 歌曲命名規則：
          識別成功：{Artist} .{序號} - {Title}.mp3（讓同一位歌手在排序時聚合在一起）
          未識別：{母檔名}_Track{序號}.mp3
        """
        if custom_output_dir:
            self.output_dir = custom_output_dir
            os.makedirs(self.output_dir, exist_ok=True)
        if language:
            self.language = language
        if endpoint_country:
            self.endpoint_country = endpoint_country

        def report(status: str, progress: float, details: str = ""):
            if progress_cb:
                progress_cb({
                    'status': status,
                    'progress': round(progress, 1),
                    'details': details
                })

        report("analyzing", 5, "正在讀取媒體檔案資訊與時長...")
        total_duration = get_media_duration(media_path)
        if total_duration <= 0:
            raise ValueError("無法讀取檔案長度或檔案無效")

        is_audio = is_audio_file(media_path)
        parent_name = clean_filename(custom_folder_name or os.path.splitext(os.path.basename(media_path))[0])

        # 若是音訊檔，檢查是否為單曲
        if is_audio:
            report("analyzing", 10, f"偵測到輸入為音訊檔案（{int(total_duration)} 秒），正在判定是否為單曲...")
            silences = detect_silence_candidates(media_path, noise_db=-24, min_duration=0.5)
            valid_cuts = [p for p in silences if 60.0 <= p <= total_duration - 45.0]
            
            if total_duration <= 390.0 and len(valid_cuts) == 0:
                report("analyzing", 15, "判定為單曲音訊檔，免切分直接分析元數據...")
                return await self.process_single_audio(media_path, self.output_dir, parent_name, report)

        report("detecting_silence", 15, f"長度 {int(total_duration//60)} 分 {int(total_duration%60)} 秒，正在偵測歌曲轉折點...")
        raw_silences = detect_silence_candidates(media_path, noise_db=-24, min_duration=0.35)

        candidate_points = [0.0]
        for p in raw_silences:
            if p - candidate_points[-1] >= min_song_duration and (total_duration - p) >= 30.0:
                candidate_points.append(p)
        candidate_points.append(total_duration)

        report("identifying", 30, f"劃分出 {len(candidate_points)-1} 個候選音樂區塊，正在以 {self.language} 進行多點指紋識別...")

        sub_tracks = []
        for i in range(len(candidate_points) - 1):
            s_start = candidate_points[i]
            s_end = candidate_points[i + 1]
            cur_pct = 30 + ((i + 1) / (len(candidate_points) - 1)) * 35
            report("identifying", cur_pct, f"正在識別區塊 {i+1}/{len(candidate_points)-1}...")

            info = await self.identify_segment_robust(media_path, s_start, s_end)
            sub_tracks.append({
                'start': s_start,
                'end': s_end,
                'info': info
            })

        # 智慧合併相鄰同曲段落 (Merge Adjacent Same Tracks)
        merged_tracks = []
        for st in sub_tracks:
            if not merged_tracks:
                merged_tracks.append(st)
                continue

            last = merged_tracks[-1]
            last_id = last['info']['track_id'] if last['info'] else None
            curr_id = st['info']['track_id'] if st['info'] else None

            if last_id and curr_id and (last_id == curr_id):
                last['end'] = st['end']
            elif not curr_id and (st['end'] - st['start'] < 120.0):
                last['end'] = st['end']
            else:
                merged_tracks.append(st)

        final_songs_count = len(merged_tracks)
        
        # 音訊檔如果是多曲合輯，若最後只合併成 1 段且長度正常，走單曲流程
        if is_audio and final_songs_count == 1:
            report("analyzing", 60, "經分析全曲為單一完整曲目，直接匯出至 Output 根目錄...")
            return await self.process_single_audio(media_path, self.output_dir, parent_name, report)

        report("converting", 70, f"共確認 {final_songs_count} 首獨立歌曲，開始切片並匯出高品質 MP3...")

        # 決定儲存資料夾：
        # 音訊檔（多曲）：直接放在 Output 根目錄，不建立子目錄！
        # 影片檔：建立獨立子目錄儲存
        if is_audio:
            save_folder = self.output_dir
        else:
            save_folder = os.path.join(self.output_dir, parent_name)
            os.makedirs(save_folder, exist_ok=True)

        results = []
        for idx, trk in enumerate(merged_tracks):
            cur_pct = 70 + ((idx + 1) / final_songs_count) * 28
            info = trk['info']
            start_sec = trk['start']
            end_sec = trk['end']
            duration = end_sec - start_sec

            # 命名規則修改：
            # 若能識別出歌名與演唱者：{Artist} .{序號} - {Title}.mp3（讓同一位歌手在排序時聚合在一起）
            # 若無演唱者但有歌名：{Title} .{序號}.mp3
            # 若無法識別歌名：{母檔名}_Track{序號}.mp3
            track_num = f"{idx+1:02d}"
            
            if info and info.get('title') and info.get('title').strip():
                title = info['title'].strip()
                artist = info.get('artist', '').strip()
                if artist and artist != "Unknown Artist":
                    base_name = f"{artist} .{track_num} - {title}"
                else:
                    base_name = f"{title} .{track_num}"
                out_mp3_name = f"{clean_filename(base_name)}.mp3"
            else:
                title = f"{parent_name}_Track{track_num}"
                artist = ""
                out_mp3_name = f"{parent_name}_Track{track_num}.mp3"

            album = info.get('album', '') if info else ""
            cover_url = info.get('cover_url') if info else None

            out_mp3_path = os.path.join(save_folder, out_mp3_name)

            report("converting", cur_pct, f"正在匯出 MP3: {out_mp3_name}...")

            # FFmpeg 匯出 320kbps MP3
            cmd = [
                'ffmpeg',
                '-ss', f"{start_sec:.3f}",
                '-to', f"{end_sec:.3f}",
                '-i', media_path,
                '-vn',
                '-c:a', 'libmp3lame',
                '-b:a', '320k',
                out_mp3_path,
                '-y'
            ]
            subprocess.run(cmd, capture_output=True, check=True)

            # 【雙重保障機制】：若原本未識別成功，直接對剛生成的 MP3 實體檔案進行全曲深度指紋辨識
            if (not info or not info.get('title')) and os.path.exists(out_mp3_path):
                report("converting", cur_pct, f"正在為第 {idx+1} 首進行全曲深度特徵二次校準...")
                sec_info = await self.identify_audio_file(out_mp3_path)
                if sec_info and sec_info.get('title') and sec_info.get('title').strip():
                    info = sec_info
                    title = info['title'].strip()
                    artist = info.get('artist', '').strip()
                    album = info.get('album', '')
                    cover_url = info.get('cover_url')
                    
                    if artist and artist != "Unknown Artist":
                        new_base = f"{artist} .{track_num} - {title}"
                    else:
                        new_base = f"{title} .{track_num}"
                    new_safe = clean_filename(new_base)
                    new_mp3_name = f"{new_safe}.mp3"
                    new_mp3_path = os.path.join(save_folder, new_mp3_name)
                    try:
                        if os.path.exists(new_mp3_path):
                            os.remove(new_mp3_path)
                        os.rename(out_mp3_path, new_mp3_path)
                        out_mp3_path = new_mp3_path
                        out_mp3_name = new_mp3_name
                    except Exception:
                        pass

            # 寫入 ID3 標籤
            try:
                try:
                    audio = EasyID3(out_mp3_path)
                except Exception:
                    audio = MP3(out_mp3_path, ID3=EasyID3)
                    audio.add_tags()
                
                audio['title'] = title
                if artist:
                    audio['artist'] = artist
                if album:
                    audio['album'] = album
                audio['tracknumber'] = f"{idx+1}/{final_songs_count}"
                audio.save()

                # 下載並寫入封面圖片
                if cover_url:
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(cover_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                                if resp.status == 200:
                                    img_data = await resp.read()
                                    mp3_tags = ID3(out_mp3_path)
                                    mp3_tags.add(APIC(
                                        encoding=3,
                                        mime='image/jpeg',
                                        type=3,
                                        desc='Cover',
                                        data=img_data
                                    ))
                                    mp3_tags.save()
                    except Exception:
                        pass
            except Exception:
                pass

            results.append({
                'index': idx + 1,
                'title': title,
                'artist': artist or "Unknown Artist",
                'album': album,
                'duration': round(duration, 1),
                'start_time': round(start_sec, 1),
                'end_time': round(end_sec, 1),
                'file_name': out_mp3_name,
                'file_path': out_mp3_path,
                'cover_url': cover_url
            })

        dest_desc = "Output 根目錄" if is_audio else f"「{save_folder}」"
        report("completed", 100, f"處理完成！已成功匯出 {len(results)} 首歌曲至 {dest_desc}。")
        return results
