"""Веб-сокет живых обновлений: /api/live.

Заголовок с подписью MAX браузер в веб-сокет не передаёт, поэтому подпись
приходит первым сообщением. Пока она не проверена, сокет ничего не
получает, а через 10 секунд молчания закрывается.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from webapp_auth import InvalidInitData, verify

from ..auth import BOT_TOKEN
from ..live import hub

router = APIRouter()
log = logging.getLogger("live")

HELLO_TIMEOUT = 10
# Прокси и мобильные сети рвут молчащие соединения через минуту-другую.
# Пинг раз в 25 секунд держит сокет живым и заодно выявляет мёртвые.
PING_SECONDS = 25


@router.websocket("/live")
async def live(socket: WebSocket) -> None:
    await socket.accept()
    try:
        hello = json.loads(await asyncio.wait_for(socket.receive_text(), timeout=HELLO_TIMEOUT))
        ctx = verify(str(hello.get("init_data") or ""), BOT_TOKEN)
    except (asyncio.TimeoutError, InvalidInitData, ValueError, AttributeError, WebSocketDisconnect):
        # 4401 — «не авторизован» в пространстве кодов приложения: клиент
        # по нему понимает, что переподключаться с той же подписью незачем.
        try:
            await socket.close(code=4401)
        except RuntimeError:
            pass
        return

    hub.join(ctx.user_id, socket)
    try:
        await socket.send_text(json.dumps({"type": "ready"}))
        while True:
            try:
                message = await asyncio.wait_for(socket.receive_text(), timeout=PING_SECONDS)
            except asyncio.TimeoutError:
                await socket.send_text('{"type":"ping"}')
                continue
            if message == "ping":
                await socket.send_text('{"type":"pong"}')
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:  # noqa: BLE001 — сокет не должен валить процесс
        log.info("сокет %s закрыт: %s", ctx.user_id, exc)
    finally:
        hub.leave(ctx.user_id, socket)
