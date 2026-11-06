import socketio

from app.core.config import settings


def _client_manager():
    # Без Redis усе працює в межах одного процесу. З REDIS_URL події між копіями сервера
    # передаються через Redis (pub/sub), тож клієнт може бути підключений до будь-якої копії
    if settings.redis_url:
        return socketio.AsyncRedisManager(settings.redis_url)
    return None


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.cors_origins,
    client_manager=_client_manager(),
    logger=False,
    engineio_logger=False,
)
