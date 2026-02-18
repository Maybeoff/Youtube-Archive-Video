from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import database
import models
import parser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Монтируем статические файлы
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

class ChannelRequest(BaseModel):
    channel_url: str | None = None
    max_videos: int = 10

class VideoResponse(BaseModel):
    id: int
    video_id: str
    title: str
    thumbnail_path: str
    video_path: str

@app.get("/")
async def root():
    """Главная страница"""
    html_file = Path("static/index.html")
    if html_file.exists():
        content = html_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content, media_type="text/html; charset=utf-8")
    return HTMLResponse(content="<h1>Video Parser</h1><p>Файл index.html не найден</p>", media_type="text/html; charset=utf-8")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket для статуса в реальном времени"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/parse-channel")
async def parse_channel(
    request: ChannelRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(database.get_db)
):
    """Парсить видео с канала"""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    channel_url = request.channel_url or os.getenv("CHANNEL_URL")
    if not channel_url:
        raise HTTPException(status_code=400, detail="Укажите channel_url или установите CHANNEL_URL в .env")
    
    await manager.broadcast(f"🔍 Начинаем парсинг канала: {channel_url}")
    videos = parser.get_channel_videos(channel_url, request.max_videos)
    await manager.broadcast(f"✅ Найдено {len(videos)} видео")
    
    for i, video in enumerate(videos, 1):
        video_url = f"https://www.youtube.com/watch?v={video['id']}"
        title = video.get('title', video['id'])
        await manager.broadcast(f"📥 Добавлено в очередь {i}/{len(videos)}: {title}")
        background_tasks.add_task(download_and_save, video_url, db, i, len(videos))
    
    return {"message": f"Начато скачивание {len(videos)} видео"}

async def download_and_save(video_url: str, db: AsyncSession, index: int, total: int):
    """Скачать видео и сохранить в БД"""
    try:
        await manager.broadcast(f"⬇️ Скачивание {index}/{total}: {video_url}")
        
        # Запускаем асинхронное скачивание
        video_data = await parser.download_video(video_url)
        
        # Проверяем, есть ли уже такое видео
        result = await db.execute(
            select(models.Video).where(models.Video.video_id == video_data['video_id'])
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Обновляем существующее
            existing.title = video_data['title']
            existing.video_path = video_data['video_path']
            existing.thumbnail_path = video_data['thumbnail_path']
            await manager.broadcast(f"🔄 Обновлено {index}/{total}: {video_data['title']}")
        else:
            # Добавляем новое
            video = models.Video(**video_data)
            db.add(video)
            await manager.broadcast(f"✅ Готово {index}/{total}: {video_data['title']}")
        
        await db.commit()
    except Exception as e:
        error_msg = f"❌ Ошибка {index}/{total}: {str(e)[:100]}"
        print(error_msg)
        await manager.broadcast(error_msg)

@app.get("/videos", response_model=list[VideoResponse])
async def get_videos(db: AsyncSession = Depends(database.get_db)):
    """Получить все видео из БД"""
    result = await db.execute(select(models.Video))
    videos = result.scalars().all()
    return videos

@app.get("/video/{video_id}")
async def get_video_file(video_id: str, db: AsyncSession = Depends(database.get_db)):
    """Получить видео файл"""
    result = await db.execute(
        select(models.Video).where(models.Video.video_id == video_id)
    )
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    
    video_path = Path(video.video_path)
    if not video_path.exists():
        # Попробовать найти файл с любым расширением
        downloads_dir = Path("downloads")
        for file in downloads_dir.glob(f"{video_id}.*"):
            if file.suffix not in ['.jpg', '.webp', '.png']:
                video_path = file
                break
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Файл видео не найден")
    
    return FileResponse(video_path)

@app.get("/thumbnail/{video_id}")
async def get_thumbnail(video_id: str, db: AsyncSession = Depends(database.get_db)):
    """Получить превью видео"""
    result = await db.execute(
        select(models.Video).where(models.Video.video_id == video_id)
    )
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    
    thumbnail_path = Path(video.thumbnail_path)
    if not thumbnail_path.exists():
        # Попробовать найти превью с разными расширениями
        downloads_dir = Path("downloads")
        for ext in ['.jpg', '.webp', '.png']:
            test_path = downloads_dir / f"{video_id}{ext}"
            if test_path.exists():
                thumbnail_path = test_path
                break
    
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Файл превью не найден")
    
    return FileResponse(thumbnail_path)

if __name__ == "__main__":
    import uvicorn
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    
    print(f"🚀 Запуск сервера на http://{host}:{port}")
    print(f"📹 Откройте в браузере: http://localhost:{port}")
    print("-" * 50)
    
    uvicorn.run(app, host=host, port=port, log_level="error")
