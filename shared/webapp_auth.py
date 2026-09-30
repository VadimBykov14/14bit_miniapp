"""Проверка подписи данных запуска мини-приложения.

MAX присылает initData вместе с подписью. Доверять initDataUnsafe нельзя —
он подделывается тривиально, а от того, кто открыл витрину, зависит,
какой прайс и какие остатки человек увидит. Поэтому личность пользователя
устанавливается только здесь.

Алгоритм — из документации MAX «Валидация данных».
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode


class InvalidInitData(Exception):
    """Подпись не сошлась или данные испорчены."""


@dataclass(frozen=True)
class LaunchContext:
    user_id: int
    first_name: str
    last_name: str
    username: str | None
    chat_id: int | None
    start_param: str | None
    auth_date: int


def _launch_params(pairs: list[tuple[str, str]]) -> str:
    """key=value через \\n, отсортированные по ключу. hash уже исключён."""
    return "\n".join(f"{key}={value}" for key, value in sorted(pairs, key=lambda p: p[0]))


def sign(user_id: int, first_name: str, bot_token: str) -> str:
    """Данные запуска, подписанные так же, как их подписывает MAX.

    Нужны тестовым ботам стенда (services/api/app/testbots.py): они ходят в
    API как обычные пользователи, и проверка подписи для них та же. Токен
    есть только у сервера, поэтому подписать чужое имя снаружи нельзя.
    """
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": first_name}, ensure_ascii=False),
    }
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(
        secret_key, _launch_params(list(params.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(params)


def verify(init_data: str, bot_token: str, max_age_seconds: int = 24 * 3600) -> LaunchContext:
    if not init_data:
        raise InvalidInitData("пустые данные запуска")

    # strict_parsing выключен намеренно: нам важнее явная проверка на дубли ниже.
    pairs = parse_qsl(init_data, keep_blank_values=True)

    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        # Дубль ключа позволил бы подсунуть второй hash или второго user.
        raise InvalidInitData("параметр встречается больше одного раза")

    data = dict(pairs)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise InvalidInitData("нет hash")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret_key, _launch_params(list(data.items())).encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise InvalidInitData("подпись не сошлась")

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError as exc:
        raise InvalidInitData("некорректный auth_date") from exc

    # Подпись верна вечно, поэтому перехваченную строку иначе можно было бы
    # переиспользовать сколько угодно.
    if max_age_seconds and time.time() - auth_date > max_age_seconds:
        raise InvalidInitData("Откройте приложение заново: с запуска прошли сутки")

    try:
        user = json.loads(data.get("user", "{}"))
        chat = json.loads(data.get("chat", "{}"))
    except json.JSONDecodeError as exc:
        raise InvalidInitData("не разобрал user или chat") from exc

    if not isinstance(user, dict) or "id" not in user:
        raise InvalidInitData("нет пользователя")

    return LaunchContext(
        user_id=int(user["id"]),
        first_name=str(user.get("first_name") or ""),
        last_name=str(user.get("last_name") or ""),
        username=user.get("username"),
        chat_id=int(chat["id"]) if isinstance(chat, dict) and "id" in chat else None,
        start_param=data.get("start_param"),
        auth_date=auth_date,
    )
