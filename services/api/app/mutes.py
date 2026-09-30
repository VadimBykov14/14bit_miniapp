"""Какие уведомления человек не хочет получать в MAX.

Под каждым сообщением бота — кнопка «Не присылать такие». Отключается только
такой же вид и только на той же стороне: владелец пекарни, который ещё и
клиент базы, отключив «ваша заявка отправлена», не должен перестать узнавать
о новых заявках своих клиентов — у обоих сообщений вид «order». Поэтому ключ —
вид плюс сторона: сотрудник поставщика или магазин.

Лента в приложении по-прежнему пишет всё: отключается только сообщение в чат.
Вернуть — в «Аккаунте».
"""

from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NotificationMute

STAFF = "staff"
SHOP = "shop"

# Подписи — для «Аккаунта» и для ответа бота: «Больше не пришлю: …».
LABELS: dict[str, str] = {
    "confirmed": "подтверждение заявок",
    "rejected": "отказы и отмены поставщика",
    "cancelled": "отмены заявок клиентами",
    "shipped": "отгрузки",
    "rescheduled": "переносы доставки",
    "accepted": "приёмку товара клиентами",
    "ship_overdue": "вопросы о неотмеченной отгрузке",
    "cutoff": "напоминания об отсечке",
    "staff_cutoff": "неподтверждённые заявки перед отсечкой",
    "reorder": "подсказки повторить заказ",
    "join_request": "просьбы о подключении",
    "connection": "подключение к витринам",
    "joined": "принятые приглашения",
    "joined_staff": "новых сотрудников",
    "info": "прочие сообщения",
}
# «order» у сотрудника — новая заявка клиента, у магазина — его же заявка
# ушла поставщику: это разные сообщения, и отключаются они порознь.
ORDER_LABELS = {STAFF: "новые заявки", SHOP: "ваши отправленные заявки"}

PAYLOAD = re.compile(r"^mute:([a-z_]{1,30}):(staff|shop)?$")


def side(role: str | None) -> str:
    """Сторона получателя по роли, с которой пришло уведомление."""
    if role in ("owner", "manager"):
        return STAFF
    if role in ("client", "worker"):
        return SHOP
    return ""


def label(kind: str, where: str) -> str | None:
    """Как назвать этот вид человеку. None — вид не отключается."""
    if kind == "order":
        return ORDER_LABELS.get(where)
    return LABELS.get(kind)


def payload(kind: str, where: str) -> str | None:
    """Что положить в кнопку «Не присылать такие». Бот вернёт это при нажатии."""
    return f"mute:{kind}:{where}" if label(kind, where) else None


def parse(value: str) -> tuple[str, str] | None:
    match = PAYLOAD.match(value or "")
    if not match or not label(match.group(1), match.group(2) or ""):
        return None
    return match.group(1), match.group(2) or ""


async def is_muted(session: AsyncSession, user_id: int, kind: str, where: str) -> bool:
    return (
        await session.execute(
            select(NotificationMute.id).where(
                NotificationMute.max_user_id == user_id,
                NotificationMute.kind == kind,
                NotificationMute.side == where,
            )
        )
    ).first() is not None


async def mute(session: AsyncSession, user_id: int, kind: str, where: str) -> None:
    """Повторное нажатие — не ошибка: кнопка остаётся под старыми сообщениями."""
    await session.execute(
        insert(NotificationMute)
        .values(max_user_id=user_id, kind=kind, side=where)
        .on_conflict_do_nothing()
    )


async def unmute(session: AsyncSession, user_id: int, kind: str, where: str) -> None:
    await session.execute(
        delete(NotificationMute).where(
            NotificationMute.max_user_id == user_id,
            NotificationMute.kind == kind,
            NotificationMute.side == where,
        )
    )


async def listing(session: AsyncSession, user_id: int) -> list[tuple[str, str, str]]:
    """(вид, сторона, подпись) — что отключено, по порядку отключения."""
    rows = (
        await session.execute(
            select(NotificationMute)
            .where(NotificationMute.max_user_id == user_id)
            .order_by(NotificationMute.id)
        )
    ).scalars()
    return [
        (row.kind, row.side, label(row.kind, row.side) or row.kind)
        for row in rows
    ]
