# app/services/media_service.py
"""
Media Engine: Handles downloading and processing of external URLs using yt-dlp.
"""
import yt_dlp
import os
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class MediaEngine:
    def __init__(self):
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)

    async def extract_metadata(self, url: str) -> Optional[Dict[str, Any]]:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False}
        
        def _sync_extract():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception as e:
                logger.error(f"Metadata extraction failed for {url}: {e}")
                return None

        return await asyncio.to_thread(_sync_extract)

    async def download_media(self, url: str, format_choice: str = "best_video") -> Optional[str]:
        unique_id = uuid.uuid4().hex[:8]
        output_template = str(self.download_dir / f"{unique_id}_%(ext)s")

        if format_choice == "mp3_audio":
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',
                }],
                'outtmpl': output_template, 'quiet': True,
            }
        elif format_choice == "720p_video":
            ydl_opts = {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
                'outtmpl': output_template, 'quiet': True, 'merge_output_format': 'mp4',
            }
        else:
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': output_template, 'quiet': True, 'merge_output_format': 'mp4',
            }

        def _sync_download():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    if format_choice == "mp3_audio":
                        filename = filename.rsplit('.', 1)[0] + '.mp3'
                    return filename
            except Exception as e:
                logger.error(f"Download failed for {url}: {e}")
                return None

        return await asyncio.to_thread(_sync_download)

    def cleanup_file(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup file {file_path}: {e}")

media_engine = MediaEngine()