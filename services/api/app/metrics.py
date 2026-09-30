"""Точность отгрузки.

Один показатель, считаемый в одном месте. Он нужен трём экранам сразу —
полке города, витрине у клиента и сводке владельца, — и три независимых
подсчёта неизбежно разошлись бы на третьей правке.

Смысл: сколько из обещанного реально доехало. Обещанное — подтверждённое
количество (а если менеджер ничего не правил, то заказанное), доехавшее —
отмеченное при приёмке.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Order, OrderItem, OrderStatus

# Заявки, по которым приёмка уже прошла: только они говорят о точности.
DELIVERED_STATUSES = (OrderStatus.accepted, OrderStatus.closed)

# Публичный показатель по одной-двум заявкам — это не показатель, а случайность.
MIN_ORDERS_PUBLIC = 3


@dataclass(frozen=True)
class Accuracy:
    expected: float = 0.0
    delivered: float = 0.0
    orders: int = 0

    @property
    def percent(self) -> float | None:
        if not self.expected:
            return None
        return round(100 * self.delivered / self.expected, 1)

    @property
    def public(self) -> float | None:
        """То же число, но только когда за ним стоит достаточно заявок."""
        return self.percent if self.orders >= MIN_ORDERS_PUBLIC else None


def combine(values: list[Accuracy]) -> Accuracy:
    """Сумма по витринам, а не среднее процентов: витрина с тремя заявками
    не должна весить столько же, сколько витрина с тремястами."""
    return Accuracy(
        expected=sum(value.expected for value in values),
        delivered=sum(value.delivered for value in values),
        orders=sum(value.orders for value in values),
    )


async def by_storefront(
    session: AsyncSession, storefront_ids: list[int]
) -> dict[int, Accuracy]:
    if not storefront_ids:
        return {}

    promised = func.coalesce(OrderItem.qty_confirmed, OrderItem.qty_ordered)
    rows = await session.execute(
        select(
            Order.storefront_id,
            func.sum(promised),
            func.sum(func.coalesce(OrderItem.qty_accepted, promised)),
            func.count(func.distinct(Order.id)),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.storefront_id.in_(storefront_ids),
            Order.status.in_(DELIVERED_STATUSES),
        )
        .group_by(Order.storefront_id)
    )
    return {
        storefront_id: Accuracy(
            expected=float(expected or 0), delivered=float(delivered or 0), orders=int(orders or 0)
        )
        for storefront_id, expected, delivered, orders in rows
    }
