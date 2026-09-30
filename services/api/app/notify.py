"""Уведомления в MAX идут через bot-service: токен и ограничитель 30 rps
живут там, и второй клиент API создал бы вторую очередь мимо лимита.

Адресуем по `user_id`, а не по `chat_id`. Так работает `POST /messages`
в схеме MAX, и это единственный способ написать тому, кто открыл
мини-приложение, но боту ничего не писал: chat_id появляется только
в апдейтах бота, а user_id известен из подписи запуска всегда.
"""

from __future__ import annotations

import logging
import os

import httpx

BOT_INTERNAL_URL = os.environ.get("BOT_INTERNAL_URL", "http://bot:8080")

log = logging.getLogger("notify")


async def send(
    user_id: int | None,
    text: str,
    chat_id: int | None = None,
    button: dict | None = None,
    mute: str | None = None,
) -> bool:
    """Молча не отправляет, если адресата нет: уведомление не должно
    ронять подтверждение заявки. `button` — кнопка «открыть приложение
    там, где дело»: {"text": …, "payload": …}. `mute` — что вернёт кнопка
    «Не присылать такие» (см. mutes.py); нет — кнопки нет."""
    if not user_id and not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{BOT_INTERNAL_URL}/internal/notify",
                json={
                    "user_id": user_id, "chat_id": chat_id, "text": text, "button": button,
                    "mute": mute,
                },
            )
            response.raise_for_status()
            # Бот отвечает, дошло ли сообщение: MAX не пишет тому, кто ни
            # разу не открывал бота, и такое уведомление живёт только в ленте.
            return bool((response.json() or {}).get("sent", True))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("не смог уведомить %s: %s", user_id or chat_id, exc)
        return False


async def send_contact(
    user_id: int,
    chat_id: int | None,
    name: str,
    contact_id: int,
    text: str,
    phone: str = "",
) -> bool:
    """Карточка контакта в чат с ботом.

    Ссылку на личный чат в MAX по номеру пользователя не построить: адрес
    вида max.ru/u/… выдаётся самим мессенджером и из id не вычисляется. А
    карточку с id бот прислать может — нажатие на неё открывает профиль с
    кнопкой «Написать». Так «Написать» работает у всех, а не только у тех,
    кто завёл публичный ник.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{BOT_INTERNAL_URL}/internal/contact",
                json={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "name": name,
                    "contact_id": contact_id,
                    "text": text,
                    "phone": phone,
                },
            )
            response.raise_for_status()
            return bool((response.json() or {}).get("sent"))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("не смог прислать контакт %s для %s: %s", contact_id, user_id, exc)
        return False
