"""Доступное количество.

Клиент видит `доступно = остаток − резерв`, но не меньше нуля. Резерв —
это позиции отправленных и подтверждённых заявок, которые ещё не списаны
с остатка витрины (`Order.stock_taken`): у витрины из 1С списание — когда
заказ встал в учёт, у витрины без 1С — при подтверждении. Держать резерв
по уже списанному значило бы вычесть его дважды.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Order, OrderItem, OrderStatus

RESERVING_STATUSES = (OrderStatus.sent, OrderStatus.confirmed)

# Витрина «под заказ» остатка не держит: пекарня печёт по заявкам, и её
# дневной лимит («больше 240 батонов в день не испечём») тратит каждая
# заявка на эту дату — от отправки до приёмки. Отменённая и отклонённая
# лимит возвращают.
BOOKING_STATUSES = (
    OrderStatus.sent, OrderStatus.confirmed, OrderStatus.assembling,
    OrderStatus.shipped, OrderStatus.accepted, OrderStatus.closed,
)

# «Лимита нет» — позиция под заказ без дневного предела. Число, а не None:
# степпер в каталоге ограничивает количество доступным.
UNLIMITED = 99999.0


async def booked_for_date(session: AsyncSession, storefront_id: int, day: date) -> dict[int, float]:
    """Сколько каждой позиции уже заказано на дату — для дневного лимита."""
    rows = await session.execute(
        select(
            OrderItem.item_id,
            func.sum(func.coalesce(OrderItem.qty_confirmed, OrderItem.qty_ordered)),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.storefront_id == storefront_id,
            Order.delivery_date == day,
            Order.status.in_(BOOKING_STATUSES),
        )
        .group_by(OrderItem.item_id)
    )
    return {item_id: float(qty or 0) for item_id, qty in rows}


def left_for_day(daily_limit: object, booked: float) -> float:
    """Сколько ещё можно заказать на дату. Без лимита — сколько угодно."""
    if daily_limit is None:
        return UNLIMITED
    return max(0.0, float(daily_limit) - booked)


async def reserved_by_item(session: AsyncSession, storefront_id: int) -> dict[int, float]:
    rows = await session.execute(
        select(
            OrderItem.item_id,
            func.sum(func.coalesce(OrderItem.qty_confirmed, OrderItem.qty_ordered)),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.storefront_id == storefront_id,
            Order.status.in_(RESERVING_STATUSES),
            Order.stock_taken.is_(False),
        )
        .group_by(OrderItem.item_id)
    )
    return {item_id: float(qty or 0) for item_id, qty in rows}
