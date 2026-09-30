"""Заявка движется и без нажатий: отсечка и забытая отгрузка.

Две вещи случаются по часам, а не по кнопке:

* **отсечка прошла** — у витрины «под заказ» состав заявок на эту дату
  больше не меняется, и подтверждённые уходят в производство: статус
  `assembling`. Раньше этот статус был в концепте, но не ставился никогда;
* **доставка была, а отгрузку не отметили** — утром следующего дня
  владельцу и тому, кто ведёт заявку, приходит вопрос «всё в порядке?», а в
  самой заявке — плашка с тремя действиями: отгрузка была, перенести,
  отменить. Иначе заявка висела «подтверждённой» неделями, и клиент не
  понимал, ждать ли машину.

Проход идёт вместе с напоминаниями раз в несколько минут. Отправленное
помечается в `reminders`: без отметки вопрос приходил бы каждые пять минут.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import live, team
from .messaging import tell
from .models import Client, Employee, Mode, Order, OrderStatus, Reminder, Storefront
from .schedule import TZ, production_started

log = logging.getLogger("lifecycle")

# С какого часа утра спрашивать о вчерашней отгрузке: ночью такой вопрос
# будит, а к девяти склад уже знает, что уехало.
OVERDUE_HOUR = int(os.environ.get("SHIP_OVERDUE_HOUR", "9"))
# Спрашиваем только о свежих: после выкатки первый проход иначе разослал бы
# вопросы по всем старым заявкам сразу. Давние видны плашкой в самой заявке.
OVERDUE_WINDOW_DAYS = 3

SHIPPABLE = (OrderStatus.confirmed, OrderStatus.assembling)


async def start_production(session: AsyncSession, now: datetime | None = None) -> int:
    """Подтверждённые заявки витрин «под заказ», чья отсечка прошла, —
    в производство. Возвращает, сколько заявок сменили статус."""
    moment = now or datetime.now(TZ)
    rows = (
        await session.execute(
            select(Order, Storefront)
            .join(Storefront, Storefront.id == Order.storefront_id)
            .where(
                Order.status == OrderStatus.confirmed,
                Storefront.mode == Mode.preorder,
                Storefront.cutoff_at.is_not(None),
                # Отсечка даты — накануне: у более поздних она ещё впереди.
                Order.delivery_date <= moment.date() + timedelta(days=1),
            )
            # Замок на заявку: отгрузка или отказ в ту же секунду не должны
            # быть перезаписаны статусом «в производстве».
            .with_for_update(of=Order)
        )
    ).all()
    started = [
        order
        for order, storefront in rows
        if production_started(storefront, order.delivery_date, moment)
    ]
    for order in started:
        order.status = OrderStatus.assembling
    await session.commit()
    for order in started:
        await live.order_changed(session, order)
    if started:
        log.info("в производство ушло заявок: %s", len(started))
    return len(started)


async def _claim(session: AsyncSession, key: str, enterprise_id: int, storefront_id: int) -> bool:
    """Отметка «уже спросили». Уникальный индекс — единственная защита от
    дубля: проверка перед отправкой разошлась бы в гонке двух проходов."""
    claimed = (
        await session.execute(
            insert(Reminder)
            .values(
                kind="ship_overdue",
                enterprise_id=enterprise_id,
                storefront_id=storefront_id,
                key=key,
            )
            .on_conflict_do_nothing()
            .returning(Reminder.id)
        )
    ).scalar_one_or_none()
    return claimed is not None


async def warn_overdue(session: AsyncSession, now: datetime | None = None) -> int:
    """Спрашивает поставщика о заявках, доставка которых прошла, а отгрузку
    не отметили. Один раз на заявку и дату. Возвращает число сообщений."""
    moment = now or datetime.now(TZ)
    if moment.hour < OVERDUE_HOUR:
        return 0
    rows = (
        await session.execute(
            select(
                Order.id, Order.number, Order.delivery_date, Order.client_id, Order.manager_id,
                Storefront.id, Storefront.enterprise_id, Client.name,
            )
            .join(Storefront, Storefront.id == Order.storefront_id)
            .join(Client, Client.id == Order.client_id)
            .where(
                Order.status.in_(SHIPPABLE),
                Order.delivery_date < moment.date(),
                Order.delivery_date >= moment.date() - timedelta(days=OVERDUE_WINDOW_DAYS),
            )
            .order_by(Order.id)
        )
    ).all()

    sent = 0
    for (
        order_id, number, day, client_id, manager_id, storefront_id, enterprise_id, client_name,
    ) in rows:
        # Владелец и закреплённый менеджер, а если заявку ведёт кто-то
        # другой — и он: вопрос к тому, кто должен был отметить отгрузку.
        recipients = await team.order_recipients(session, enterprise_id, client_id)
        if manager_id is not None:
            manager = await session.get(Employee, manager_id)
            if manager is not None:
                recipients.setdefault(manager.max_user_id, manager.role.value)
        text = (
            f"Заявка №{number or order_id} ({client_name}): доставка была {day.strftime('%d.%m')}, "
            "а отгрузку не отметили. Всё в порядке? В заявке можно отметить отгрузку, "
            "перенести доставку или отменить её."
        )
        for user_id, role in sorted(recipients.items()):
            key = f"{order_id}:{day.strftime('%Y%m%d')}:{user_id}"
            if not await _claim(session, key, enterprise_id, storefront_id):
                continue
            await tell(session, user_id, text, kind="ship_overdue", order_id=order_id, role=role)
            sent += 1
    await session.commit()
    if sent:
        log.info("вопросов о неотмеченной отгрузке: %s", sent)
    return sent


async def run(session: AsyncSession, now: datetime | None = None) -> dict:
    return {
        "production": await start_production(session, now),
        "overdue": await warn_overdue(session, now),
    }
