"""Пароль своей базы 1С — в базе приложения только зашифрованным.

Ключ шифрования выводится из секрета, который на сервере уже есть: из
`ONEC_SECRET`, а если его не задали — из токена бота. Отдельный ключ в
`.env` стенда не нужен, а утечка одной таблицы не отдаёт паролей от баз
поставщиков. Сменили токен без `ONEC_SECRET` — старые пароли не
расшифруются, и владелец введёт пароль заново: обмен скажет об этом
словами, а не упадёт.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    secret = os.environ.get("ONEC_SECRET") or os.environ.get("MAX_BOT_TOKEN", "")
    if not secret:
        raise RuntimeError("нет секрета для шифрования паролей 1С")
    digest = hashlib.sha256(f"max26:onec-password:{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode() if password else ""


def open_sealed(value: str) -> str | None:
    """Расшифрованный пароль; None — зашифрован другим ключом."""
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None
