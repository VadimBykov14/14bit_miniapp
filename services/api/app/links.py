"""Подписанные ссылки для запросов без заголовка.

Личность приходит заголовком с подписью MAX, но есть запросы, которые
заголовок передать не могут: <img src> снимка расхождения и скачивание
файла средствами MAX — `WebApp.downloadFile` получает только адрес. Для них
сервер выдаёт ссылку с подписью: она привязана к пути, к человеку и к роли
и живёт недолго, поэтому чужой адрес с ней не открыть, а утёкшая ссылка
скоро перестаёт работать.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

_SECRET = hmac.new(
    b"max26-links", os.environ.get("MAX_BOT_TOKEN", "").encode(), hashlib.sha256
).digest()

# Снимок висит на экране заявки, файл скачивается сразу после нажатия.
PHOTO_TTL = 3600
FILE_TTL = 300


def _mac(path: str, payload: str) -> str:
    return hmac.new(_SECRET, f"{path}|{payload}".encode(), hashlib.sha256).hexdigest()[:40]


def token(path: str, user_id: int, role: str | None, ttl: int) -> str:
    """Срок округляется вверх до следующего окна: подпись не меняется
    внутри окна, и браузер берёт снимок из кэша, а не качает заново."""
    expires = (int(time.time()) // ttl + 2) * ttl
    payload = f"{user_id}.{role or '-'}.{expires}"
    return f"{payload}.{_mac(path, payload)}"


def signed(path: str, user_id: int, role: str | None, ttl: int) -> str:
    return f"{path}?t={token(path, user_id, role, ttl)}"


def verify(path: str, value: str) -> tuple[int, str | None] | None:
    """(user_id, роль) или None, если подпись чужая или срок вышел."""
    try:
        user, role, expires, mac = value.split(".")
        user_id, expires_at = int(user), int(expires)
    except ValueError:
        return None
    if expires_at < time.time():
        return None
    if not hmac.compare_digest(mac, _mac(path, f"{user}.{role}.{expires}")):
        return None
    return user_id, None if role == "-" else role
