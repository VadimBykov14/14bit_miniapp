"""Напоминания клиенту и менеджеру.

Два повода, оба из концепта:

* **«завтра отсечка, вы ещё не заказали»** — витрина под заказ, до отсечки
  меньше часа, а заявки на ближайшую дату от клиента нет;
* **«пора заказать»** — клиент берёт раз в неделю, а прошло девять дней.

Ритм считается медианой интервалов, а не средним: одна пропущенная неделя
не должна растягивать привычку. Отправленное помечается в `reminders`,
иначе планировщик, просыпающийся каждые пять минут, повторил бы сообщение
дюжину раз.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Client, Connection, Employee, Mode, Order, OrderStatus, Reminder, Storefront,
)
from .messaging import tell
from .schedule import TZ, cutoff_in_minutes, next_delivery_date

log = logging.getLogger("reminders")

# Запасное окно для витрин, у которых настройка не заполнена.
DEFAULT_REMIND_BEFORE = int(os.environ.get("REMIND_BEFORE_MINUTES", "60"))

# Заявки в этих статусах считаются «клиент уже заказал».
PLACED = (
    OrderStatus.sent, OrderStatus.confirmed, OrderStatus.assembling,
    OrderStatus.shipped, OrderStatus.accepted, OrderStatus.closed,
)


def human_duration(minutes: int) -> str:
    """«288 мин» читается плохо. Вблизи важны минуты, вдали — часы."""
    if minutes < 60:
        return f"{minutes} мин"
    hours, rest = divmod(minutes, 60)
    if hours >= 3 or not rest:
        return f"{hours} ч"
    return f"{hours} ч {rest} мин"


@dataclass(frozen=True)
class Nudge:
    kind: str
    user_id: int | None
    text: str
    key: str
    client_id: int | None = None
    enterprise_id: int | None = None
    storefront_id: int | None = None


def rhythm(dates: list[date_type]) -> int | None:
    """Медианный интервал между заявками в днях.

    Меньше трёх заявок — это ещё не привычка, и подсказывать нечего.
    """
    if len(dates) < 3:
        return None
    ordered = sorted(dates)
    gaps = sorted((b - a).days for a, b in zip(ordered, ordered[1:]) if (b - a).days > 0)
    if not gaps:
        return None
    middle = len(gaps) // 2
    median = gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) // 2
    return median or None


def overdue_by(dates: list[date_type], today: date_type) -> tuple[int, int] | None:
    """(ритм, дней с последней заявки), если пора заказывать."""
    days = rhythm(dates)
    if days is None:
        return None
    since = (today - max(dates)).days
    return (days, since) if since >= days else None


async def _order_dates(session: AsyncSession, client_id: int, storefront_id: int) -> list[date_type]:
    rows = await session.execute(
        select(func.date(Order.created_at))
        .where(
            Order.client_id == client_id,
            Order.storefront_id == storefront_id,
            Order.status.in_(PLACED),
        )
        .order_by(func.date(Order.created_at))
    )
    return [row[0] for row in rows]


async def reorder_hint(session: AsyncSession, client_id: int, storefront_id: int) -> str | None:
    """Строка подсказки для карточки витрины. Пусто — значит рано."""
    today = datetime.now(TZ).date()
    result = overdue_by(await _order_dates(session, client_id, storefront_id), today)
    if not result:
        return None
    days, since = result
    return f"Обычно раз в {days} дн., прошло {since} — пора заказывать"


async def _clients_of(session: AsyncSession, storefront_id: int) -> list[Client]:
    return list(
        (
            await session.execute(
                select(Client)
                .join(Connection, Connection.client_id == Client.id)
                .where(
                    Connection.storefront_id == storefront_id,
                    Connection.status == "active",
                )
            )
        ).scalars()
    )


async def collect(session: AsyncSession, enterprise_id: int | None = None) -> list[Nudge]:
    """Что нужно отправить прямо сейчас. Ничего не шлёт и не пишет в базу."""
    today = datetime.now(TZ).date()
    query = select(Storefront)
    if enterprise_id is not None:
        query = query.where(Storefront.enterprise_id == enterprise_id)
    storefronts = list((await session.execute(query)).scalars())

    nudges: list[Nudge] = []
    for storefront in storefronts:
        clients = await _clients_of(session, storefront.id)

        # Ноль — это «не напоминать», а не «настройка пустая»: отличаем
        # явно, иначе выключенное напоминание вернулось бы значением по умолчанию.
        window = (
            DEFAULT_REMIND_BEFORE
            if storefront.remind_before_minutes is None
            else storefront.remind_before_minutes
        )
        minutes = cutoff_in_minutes(storefront)
        if storefront.mode is Mode.preorder and minutes is not None and 0 < minutes <= window:
            target = next_delivery_date(storefront)
            ordered = {
                row
                for row in (
                    await session.execute(
                        select(Order.client_id).where(
                            Order.storefront_id == storefront.id,
                            Order.delivery_date == target,
                            Order.status.in_(PLACED),
                        )
                    )
                ).scalars()
            }
            silent = [client for client in clients if client.id not in ordered]
            cutoff = storefront.cutoff_at.strftime("%H:%M") if storefront.cutoff_at else "—"
            for client in silent:
                nudges.append(
                    Nudge(
                        kind="cutoff",
                        user_id=client.max_user_id,
                        text=(
                            f"До отсечки в {cutoff} — {human_duration(minutes)}. "
                            f"Витрина «{storefront.name}»: заявки на "
                            f"{target.strftime('%d.%m')} от вас ещё нет."
                        ),
                        key=target.isoformat(),
                        client_id=client.id,
                        storefront_id=storefront.id,
                    )
                )
            # Менеджеру — не про каждого клиента, а одной строкой: сколько
            # заявок ещё не подтверждено перед отсечкой.
            pending = (
                await session.execute(
                    select(func.count(Order.id)).where(
                        Order.storefront_id == storefront.id,
                        Order.delivery_date == target,
                        Order.status == OrderStatus.sent,
                    )
                )
            ).scalar_one()
            if pending:
                for user_id in await _staff(session, storefront.enterprise_id):
                    nudges.append(
                        Nudge(
                            kind="staff_cutoff",
                            user_id=user_id,
                            text=(
                                f"До отсечки в {cutoff} — {human_duration(minutes)}. "
                                f"В витрине «{storefront.name}» не подтверждено заявок: {pending}."
                            ),
                            key=f"{target.isoformat()}:{user_id}",
                            enterprise_id=storefront.enterprise_id,
                            storefront_id=storefront.id,
                        )
                    )

        for client in clients:
            result = overdue_by(await _order_dates(session, client.id, storefront.id), today)
            if not result:
                continue
            days, since = result
            nudges.append(
                Nudge(
                    kind="reorder",
                    user_id=client.max_user_id,
                    text=(
                        f"Витрина «{storefront.name}»: вы обычно заказываете раз в {days} дн., "
                        f"а прошло {since}. Повторить прошлую заявку — два тапа."
                    ),
                    key=today.isoformat(),
                    client_id=client.id,
                    storefront_id=storefront.id,
                )
            )

    return nudges


async def _staff(session: AsyncSession, enterprise_id: int) -> list[int]:
    rows = (
        await session.execute(
            select(Employee.max_user_id).where(Employee.enterprise_id == enterprise_id)
        )
    ).scalars()
    return sorted(set(rows))


async def run(session: AsyncSession, enterprise_id: int | None = None) -> dict:
    """Отправляет всё, что назрело, и помечает отправленное."""
    sent: list[str] = []
    skipped = 0

    for nudge in await collect(session, enterprise_id):
        mark = Reminder(
            kind=nudge.kind,
            client_id=nudge.client_id,
            enterprise_id=nudge.enterprise_id,
            storefront_id=nudge.storefront_id,
            key=nudge.key,
        )
        session.add(mark)
        try:
            # Уникальный индекс — единственная защита от дубля: проверка
            # «а не отправляли ли мы уже» разошлась бы в гонке двух процессов.
            await session.flush()
        except IntegrityError:
            await session.rollback()
            skipped += 1
            continue

        await tell(
            session, nudge.user_id, nudge.text,
            kind=nudge.kind, storefront_id=nudge.storefront_id,
        )
        sent.append(nudge.text)

    await session.commit()
    if sent:
        log.info("напоминаний отправлено %s, пропущено как дубли %s", len(sent), skipped)
    return {"sent": sent, "skipped": skipped}
