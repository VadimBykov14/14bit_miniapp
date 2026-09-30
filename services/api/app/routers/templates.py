"""Шаблоны регулярных заявок.

«Повторить прошлый заказ» закрывает вчерашний день. Но у магазина недельный
ритм: пятничная заявка вдвое больше среды, а перед праздниками своя. Шаблон
именованный и не затирается следующей заявкой — клиент собирает привычный
набор в два тапа, не пересчитывая коробки заново.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Identity, require_client
from ..db import get_session
from ..models import (
    Connection, Order, OrderTemplate, OrderTemplateLine, StorefrontItem,
)
from ..quantity import to_decimal
from ..schemas import TemplateIn, TemplateLineOut, TemplateOut

router = APIRouter()

# Больше десятка шаблонов на витрину никто не разбирает глазами, а список
# превращается в свалку. Предел явный, с понятной ошибкой.
MAX_TEMPLATES = 10


async def _assert_connected(session: AsyncSession, client_id: int, storefront_id: int) -> None:
    connection = (
        await session.execute(
            select(Connection).where(
                Connection.client_id == client_id,
                Connection.storefront_id == storefront_id,
                Connection.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=403, detail="витрина не подключена")


async def _as_out(session: AsyncSession, template: OrderTemplate) -> TemplateOut:
    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(
                    StorefrontItem.id.in_([line.item_id for line in template.lines] or [0])
                )
            )
        ).scalars()
    }
    lines = [
        TemplateLineOut(
            item_id=line.item_id,
            name=catalog[line.item_id].name if line.item_id in catalog else "позиция удалена",
            unit=catalog[line.item_id].unit if line.item_id in catalog else "шт",
            qty=float(line.qty),
        )
        for line in template.lines
    ]
    total = sum(
        float(catalog[line.item_id].price) * float(line.qty)
        for line in template.lines
        if line.item_id in catalog
    )
    return TemplateOut(
        id=template.id,
        storefront_id=template.storefront_id,
        name=template.name,
        total=round(total, 2),
        lines=lines,
    )


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    storefront_id: int | None = None,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> list[TemplateOut]:
    query = (
        select(OrderTemplate)
        .where(OrderTemplate.client_id == identity.client_id)
        .order_by(OrderTemplate.id)
    )
    if storefront_id is not None:
        query = query.where(OrderTemplate.storefront_id == storefront_id)
    return [await _as_out(session, row) for row in (await session.execute(query)).scalars()]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    payload: TemplateIn,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    """Шаблон собирается либо из текущей корзины, либо из готовой заявки."""
    await _assert_connected(session, identity.client_id, payload.storefront_id)

    lines = {line.item_id: float(line.qty) for line in payload.lines if line.qty > 0}
    if payload.order_id is not None:
        order = await session.get(Order, payload.order_id)
        if not order or order.client_id != identity.client_id:
            raise HTTPException(status_code=404, detail="заявка не найдена")
        if order.storefront_id != payload.storefront_id:
            raise HTTPException(status_code=422, detail="заявка из другой витрины")
        # Подтверждённое количество ближе к правде, чем заказанное: именно
        # столько поставщик реально возит.
        lines = {
            line.item_id: float(
                line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered
            )
            for line in order.items
            if float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered) > 0
        }
    if not lines:
        raise HTTPException(status_code=422, detail="в шаблоне нет позиций")

    known = {
        item_id
        for item_id in (
            await session.execute(
                select(StorefrontItem.id).where(
                    StorefrontItem.storefront_id == payload.storefront_id,
                    StorefrontItem.id.in_(lines),
                )
            )
        ).scalars()
    }
    lines = {item_id: qty for item_id, qty in lines.items() if item_id in known}
    if not lines:
        raise HTTPException(status_code=422, detail="позиций этой витрины в шаблоне нет")

    name = payload.name.strip()[:80] or "Шаблон"
    existing = list(
        (
            await session.execute(
                select(OrderTemplate).where(
                    OrderTemplate.client_id == identity.client_id,
                    OrderTemplate.storefront_id == payload.storefront_id,
                )
            )
        ).scalars()
    )
    # Одноимённый шаблон перезаписываем: клиент, который жмёт «Сохранить»
    # второй раз с тем же названием, хочет обновить набор, а не завести дубль.
    template = next((row for row in existing if row.name == name), None)
    if template is None and len(existing) >= MAX_TEMPLATES:
        raise HTTPException(
            status_code=409, detail=f"шаблонов на витрину не больше {MAX_TEMPLATES}"
        )

    if template is None:
        template = OrderTemplate(
            client_id=identity.client_id, storefront_id=payload.storefront_id, name=name
        )
        session.add(template)
        await session.flush()
    else:
        await session.execute(
            delete(OrderTemplateLine).where(OrderTemplateLine.template_id == template.id)
        )

    for item_id, qty in lines.items():
        session.add(
            OrderTemplateLine(template_id=template.id, item_id=item_id, qty=to_decimal(qty))
        )

    await session.commit()
    await session.refresh(template)
    return await _as_out(session, template)


@router.delete("/templates/{template_id}", status_code=204, response_class=Response)
async def delete_template(
    template_id: int,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    template = await session.get(OrderTemplate, template_id)
    if not template or template.client_id != identity.client_id:
        raise HTTPException(status_code=404, detail="шаблон не найден")
    await session.execute(
        delete(OrderTemplateLine).where(OrderTemplateLine.template_id == template.id)
    )
    await session.delete(template)
    await session.commit()
    return Response(status_code=204)
