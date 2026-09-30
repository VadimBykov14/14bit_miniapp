"""Сводка на завтра и листы сборки.

Смысл экрана: после отсечки менеджер должен одним взглядом понять,
сколько чего печь или собирать — агрегат по всем заявкам сразу.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Identity, require_staff
from ..db import get_session
from ..models import Client, Order, OrderItem, OrderStatus, Storefront, StorefrontItem
from ..schemas import AssemblyOrderOut, ProductionSummaryOut, SummaryLineOut
from ..schedule import TZ

router = APIRouter()

# В сводку идут заявки, которые поставщик обязался отгрузить.
PLANNED = (OrderStatus.confirmed, OrderStatus.assembling)


async def _planned_dates(session: AsyncSession, enterprise_id: int) -> list[date_type]:
    """Даты, на которые у предприятия есть что собирать или подтверждать:
    без неподтверждённых сводка открывалась на пустой день, а заявки на
    понедельник ждали решения незамеченными."""
    today = datetime.now(TZ).date()
    rows = await session.execute(
        select(Order.delivery_date)
        .join(Storefront, Storefront.id == Order.storefront_id)
        .where(
            Storefront.enterprise_id == enterprise_id,
            Order.status.in_((*PLANNED, OrderStatus.sent)),
            Order.delivery_date >= today,
        )
        .group_by(Order.delivery_date)
        .order_by(Order.delivery_date)
    )
    return [row[0] for row in rows]


@router.get("/production-summary", response_model=ProductionSummaryOut)
async def production_summary(
    date: date_type | None = None,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> ProductionSummaryOut:
    planned = await _planned_dates(session, identity.enterprise_id)

    # «Завтра» у склада с доставкой по вторникам и четвергам почти всегда
    # пусто, поэтому по умолчанию открываем ближайший день, на который
    # действительно есть что собирать.
    target = date or (planned[0] if planned else datetime.now(TZ).date() + timedelta(days=1))

    orders = list(
        (
            await session.execute(
                select(Order)
                .join(Storefront, Storefront.id == Order.storefront_id)
                .where(
                    Storefront.enterprise_id == identity.enterprise_id,
                    Order.delivery_date == target,
                    Order.status.in_(PLANNED),
                )
                .order_by(Order.id)
            )
        ).scalars()
    )

    item_ids = {line.item_id for order in orders for line in order.items}
    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(StorefrontItem.id.in_(item_ids or {0}))
            )
        ).scalars()
    }
    clients = {
        client.id: client
        for client in (
            await session.execute(
                select(Client).where(Client.id.in_({o.client_id for o in orders} or {0}))
            )
        ).scalars()
    }

    totals: dict[int, float] = {}
    assembly: list[AssemblyOrderOut] = []

    for order in orders:
        lines: list[SummaryLineOut] = []
        for line in order.items:
            qty = float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
            if qty <= 0:
                continue
            totals[line.item_id] = totals.get(line.item_id, 0.0) + qty
            item = catalog.get(line.item_id)
            lines.append(
                SummaryLineOut(
                    item_id=line.item_id,
                    name=item.name if item else "",
                    unit=item.unit if item else "шт",
                    qty=qty,
                )
            )
        if lines:
            assembly.append(
                AssemblyOrderOut(
                    order_id=order.id,
                    number=order.label,
                    client_name=clients[order.client_id].name if order.client_id in clients else "",
                    lines=lines,
                )
            )

    pending = await session.scalar(
        select(func.count(Order.id))
        .join(Storefront, Storefront.id == Order.storefront_id)
        .where(
            Storefront.enterprise_id == identity.enterprise_id,
            Order.delivery_date == target,
            Order.status == OrderStatus.sent,
        )
    )

    return ProductionSummaryOut(
        date=target,
        dates=planned,
        orders=len(assembly),
        pending=pending or 0,
        totals=sorted(
            (
                SummaryLineOut(
                    item_id=item_id,
                    name=catalog[item_id].name if item_id in catalog else "",
                    unit=catalog[item_id].unit if item_id in catalog else "шт",
                    qty=qty,
                )
                for item_id, qty in totals.items()
            ),
            key=lambda line: -line.qty,
        ),
        assembly=assembly,
    )
