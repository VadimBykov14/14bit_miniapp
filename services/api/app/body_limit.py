"""Предел размера запроса.

API читает тело целиком — JSON в память, загрузку во временный файл — и
только потом проверяет размер снимка. Запрос в гигабайт успевал съесть
память и диск сервера раньше проверки, а тело FastAPI читает ещё до того,
как проверит подпись MAX: такой запрос мог прислать кто угодно.

Снаружи тело режет Caddy (`request_body` в Caddyfile). Здесь тот же предел
для запросов мимо него — из внутренней сети и при локальном запуске.
"""

from __future__ import annotations

from fastapi import HTTPException

# Самое большое, что принимаем, — снимок до 8 МБ; остальное — запас на
# обёртку multipart.
MAX_BODY_BYTES = 10 * 1024 * 1024

DETAIL = "файл слишком большой — принимаем до 8 МБ"


class BodyLimit:
    """ASGI-обёртка: считает прочитанное и отказывает, как только тело
    перевалило за предел.

    По заявленной длине заранее не отказываем: за Caddy такой ответ приходит,
    пока он ещё отправляет тело, — соединение рвётся, и человек видит «502»
    вместо понятной причины. Дочитать до предела дешевле.
    """

    def __init__(self, app, limit: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        received = 0

        async def limited():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    # HTTPException, а не своё исключение: FastAPI превращает
                    # любую другую ошибку чтения тела в «400 не разобрал тело».
                    raise HTTPException(status_code=413, detail=DETAIL)
            return message

        await self.app(scope, limited, send)
