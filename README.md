# Video Parser

Приложение для парсинга видео с YouTube канала

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

## API Endpoints

- `POST /parse-channel` - Парсить канал
- `GET /videos` - Список всех видео
- `GET /video/{video_id}` - Скачать видео
- `GET /thumbnail/{video_id}` - Получить превью

## Пример использования

```bash
curl -X POST "http://localhost:8000/parse-channel" \
  -H "Content-Type: application/json" \
  -d '{"channel_url": "https://www.youtube.com/@channelname", "max_videos": 5}'
```
