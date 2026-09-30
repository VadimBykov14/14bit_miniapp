"""Имя бота для диплинков.

Ник бота задаётся один раз при создании и не меняется, но зашивать его
в код нельзя: на другом стенде бот другой, а ссылка-приглашение с чужим
ником просто не откроется. Спрашиваем у bot-service — он единственный,
кто знает это наверняка, — и запоминаем на время жизни процесса.
"""

from __future__ import annotations

import logging
import os

import httpx

BOT_INTERNAL_URL = os.environ.get("BOT_INTERNAL_URL", "http://bot:8080")
FALLBACK = os.environ.get("BOT_USERNAME", "")

log = logging.getLogger("botinfo")

_cached: str | None = None


async def username() -> str:
    global _cached
    if _cached:
        return _cached
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{BOT_INTERNAL_URL}/health")
            response.raise_for_status()
            name = (response.json() or {}).get("bot")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("не спросил имя бота: %s", exc)
        name = None

    _cached = name or FALLBACK
    return _cached
