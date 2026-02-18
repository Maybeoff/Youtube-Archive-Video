import yt_dlp
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

def get_channel_videos(channel_url: str, max_videos: int = 10):
    """Получить список видео с канала или одиночное видео"""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'playlistend': max_videos,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)
        if 'entries' in result:
            # Это плейлист или канал
            return result['entries']
        elif 'id' in result:
            # Это одиночное видео
            return [{'id': result['id'], 'title': result.get('title', result['id'])}]
        return []

async def download_video(video_url: str):
    """Скачать видео и превью асинхронно"""
    import asyncio
    import json
    
    # Сначала получаем информацию о видео через API
    info_cmd = [
        'yt-dlp',
        '--dump-json',
        '--no-warnings',
        video_url
    ]
    
    info_process = await asyncio.create_subprocess_exec(
        *info_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    info_stdout, _ = await info_process.communicate()
    
    if info_process.returncode != 0:
        video_id = video_url.split('v=')[-1] if 'v=' in video_url else video_url.split('/')[-1]
        title = video_id
    else:
        info = json.loads(info_stdout.decode('utf-8'))
        video_id = info['id']
        title = info['title']
    
    # Формат: лучшее видео до 1440p + лучшее аудио
    format_str = 'bestvideo[height<=1440]+bestaudio/best[height<=1440]'
    
    # Создаем команду для скачивания
    cmd = [
        'yt-dlp',
        '--format', format_str,
        '-o', str(DOWNLOAD_DIR / '%(id)s.%(ext)s'),
        '--write-thumbnail',
        '--remux-video', 'webm',  # Перепаковать в webm с аудио
        video_url
    ]
    
    try:
        # Запускаем процесс скачивания
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Читаем вывод построчно
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            line_str = line.decode('utf-8', errors='ignore').strip()
            if any(x in line_str for x in ['[download]', '[info]', 'ERROR', 'WARNING']):
                print(line_str)
        
        await process.wait()
        
        if process.returncode != 0:
            raise Exception(f"Ошибка скачивания, код: {process.returncode}")
        
        # Найти файлы
        video_path = None
        thumbnail_path = None
        
        # Искать превью
        for ext in ['jpg', 'webp', 'png']:
            test_path = DOWNLOAD_DIR / f"{video_id}.{ext}"
            if test_path.exists():
                thumbnail_path = str(test_path)
                break
        
        # Искать видео файл
        for file in DOWNLOAD_DIR.glob(f"{video_id}.*"):
            if file.suffix.lower() in ['.webm', '.mp4', '.mkv']:
                video_path = str(file)
                break
        
        if not video_path:
            video_path = str(DOWNLOAD_DIR / f"{video_id}.webm")
        
        if not thumbnail_path:
            thumbnail_path = str(DOWNLOAD_DIR / f"{video_id}.jpg")
        
        return {
            'video_id': video_id,
            'title': title,
            'video_path': video_path,
            'thumbnail_path': thumbnail_path
        }
        
    except Exception as e:
        raise Exception(f"Ошибка: {str(e)}")