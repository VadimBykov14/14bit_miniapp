"""Тонкий асинхронный клиент MAX Bot API.

Ограничитель скорости живёт здесь, а не в вызывающем коде: лимит в 30 rps общий
на бота, и удержать его можно только из одного места.

Контракт сверен с официальной схемой: github.com/max-messenger/api-schema
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

# Каноничный хост из схемы — platform-api2.max.ru, но его сертификат выпущен
# «Russian Trusted Sub CA» Минцифры: этого корня нет ни в certifi, ни в ca-certificates
# Debian, и контейнер к нему не подключится. botapi.max.ru отдаёт тот же API под
# сертификатом HARICA, который есть в любом стандартном наборе.
DEFAULT_BASE = "https://botapi.max.ru"
MAX_RPS = 30.0


class RateLimiter:
    """Token bucket на общий лимит бота."""

    def __init__(self, rate: float = MAX_RPS, burst: float = MAX_RPS) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = burst
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


class MaxClient:
    """Минимум методов, нужных боту. Растить по мере надобности."""

    def __init__(self, token: str, base_url: str = DEFAULT_BASE, timeout: float = 10.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": token},
            timeout=timeout,
        )
        self._limiter = RateLimiter()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        await self._limiter.acquire()
        response = await self._http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    # --- методы API ---

    async def get_me(self) -> dict:
        return await self._request("GET", "/me")

    async def send_message(
        self,
        text: str,
        chat_id: int | None = None,
        user_id: int | None = None,
        notify: bool = True,
        attachments: list[dict] | None = None,
    ) -> dict:
        """Схема допускает оба адреса: chat_id для диалога, который бот уже
        знает, и user_id — для того, кто боту ещё не писал. Второе важнее:
        человек может открыть мини-приложение, ни разу не написав в чат."""
        if chat_id is None and user_id is None:
            raise ValueError("нужен chat_id или user_id")
        params = {"chat_id": chat_id} if chat_id is not None else {"user_id": user_id}
        body: dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        return await self._request("POST", "/messages", params=params, json=body)

    async def answer(
        self, callback_id: str, notification: str | None = None, message: dict | None = None
    ) -> dict:
        """Ответ на нажатие кнопки-колбэка: короткое уведомление человеку
        и/или новое содержимое сообщения."""
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message:
            body["message"] = message
        return await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json=body
        )

    async def get_subscriptions(self) -> dict:
        return await self._request("GET", "/subscriptions")

    async def subscribe(self, url: str, secret: str = "", update_types: list[str] | None = None) -> dict:
        body: dict[str, Any] = {"url": url}
        if secret:
            body["secret"] = secret
        if update_types:
            body["update_types"] = update_types
        return await self._request("POST", "/subscriptions", json=body)

    async def unsubscribe(self, url: str) -> dict:
        return await self._request("DELETE", "/subscriptions", params={"url": url})
