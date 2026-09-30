"""Эмуляция обмена внутри процесса.

Режим по умолчанию: стенд поднимается без внешних зависимостей, а номера
документов выглядят так же, как из 1С. Используется, когда `mock-1c`
не поднят или боевая база ещё не подключена.
"""

from __future__ import annotations

import asyncio
import os
import random

from .contract import CatalogItem, Document, OneCUnavailable

# Вероятность имитировать недоступность 1С. По умолчанию ноль:
# на демо сбой показывается кнопкой, а не случайностью.
FAILURE_RATE = float(os.environ.get("ONEC_FAILURE_RATE", "0"))


class SimulatedOneC:
    name = "эмуляция в процессе"

    async def catalog(self) -> list[CatalogItem]:
        # Номенклатуру эмуляция не выдумывает: позиции витрины ведутся
        # вручную, и подменять их случайным списком было бы враньём.
        await self._pause()
        return []

    async def push_order(self, document: Document) -> str:
        await self._pause()
        return f"ЗК-{_tail(document.external_key)}"

    async def note_order(self, external_key: str, text: str) -> str | None:
        await self._pause()
        return f"ЗК-{_tail(external_key)}"

    async def update_order(self, document: Document) -> str:
        await self._pause()
        return f"ЗК-{_tail(document.external_key)}"

    async def cancel_order(self, external_key: str, comment: str) -> str | None:
        await self._pause()
        return f"ЗК-{_tail(external_key)}"

    async def _pause(self) -> None:
        await asyncio.sleep(0.15)
        if FAILURE_RATE and random.random() < FAILURE_RATE:
            raise OneCUnavailable("таймаут соединения")


def _tail(external_key: str) -> str:
    """Номер заявки — хвост внешнего ключа `max26-230923101500-order-7`.

    Собирать цифры со всей строки нельзя: «max26» дало бы 267 вместо 7.
    """
    tail = external_key.rsplit("-", 1)[-1]
    return f"{int(tail) if tail.isdigit() else 0:06d}"
