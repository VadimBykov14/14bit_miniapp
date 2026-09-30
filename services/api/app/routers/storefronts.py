"""Витрины клиента и их каталог."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import contact, plaintext, team
from ..auth import Identity, require_client
from ..db import get_session
from ..inventory import booked_for_date, left_for_day, reserved_by_item
from ..metrics import Accuracy, by_storefront
from ..models import (
    Connection, Employee, Enterprise, Mode, Order, OrderStatus, Role, Storefront, StorefrontItem,
)
from ..promos import active as active_promos, best, condition, discounts, volume_conditions
from ..quantity import normalize, order_minimum
from ..reminders import reorder_hint
from ..schedule import HORIZON_DAYS, TZ, cutoff_in_minutes, delivery_dates, next_delivery_date
from ..schemas import (
    ContactsOut, ItemOut, LastOrderOut, PromoOut, StorefrontDetailOut, StorefrontOut,
    TeamContactOut,
)

router = APIRouter()


async def _client_storefronts(session: AsyncSession, client_id: int) -> list[Storefront]:
    return list(
        (
            await session.execute(
                select(Storefront)
                .join(Connection, Connection.storefront_id == Storefront.id)
                .where(Connection.client_id == client_id, Connection.status == "active")
                .order_by(Storefront.id)
            )
        ).scalars()
    )


# «Повторить прошлый заказ» — это последняя заявка, которая состоялась.
# Отклонённая повторялась бы пустой (подтверждено 0), а отменённую клиент
# отменил сам: предлагать её сумму «0,00 ₽» — ошибка, а не подсказка.
NOT_REPEATED = (OrderStatus.draft, OrderStatus.rejected, OrderStatus.cancelled)


async def _last_order(session: AsyncSession, client_id: int, storefront_id: int) -> LastOrderOut | None:
    order = (
        await session.execute(
            select(Order)
            .where(
                Order.client_id == client_id,
                Order.storefront_id == storefront_id,
                Order.status.notin_(NOT_REPEATED),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not order:
        return None
    total = sum(
        float(line.price) * float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
        for line in order.items
    )
    return LastOrderOut(id=order.id, date=order.created_at.date(), total=round(total, 2))


def _base(storefront: Storefront) -> dict:
    return {
        "id": storefront.id,
        "name": storefront.name,
        "initials": storefront.initials,
        "logo_url": f"/api/photos/{storefront.logo_key}" if storefront.logo_key else None,
        "cover_url": f"/api/photos/{storefront.cover_key}" if storefront.cover_key else None,
        "color": storefront.color,
        "about": storefront.about,
        "mode": storefront.mode.value,
        "source": storefront.source.value,
        "delivery_days": storefront.delivery_days,
        "stock_synced_at": storefront.stock_synced_at,
        "cutoff_at": storefront.cutoff_at.strftime("%H:%M") if storefront.cutoff_at else None,
        "cutoff_in_minutes": cutoff_in_minutes(storefront),
        "next_delivery_date": next_delivery_date(storefront),
    }


@router.get("/storefronts", response_model=list[StorefrontOut])
async def list_storefronts(
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> list[StorefrontOut]:
    storefronts = await _client_storefronts(session, identity.client_id)
    accuracy = await by_storefront(session, [front.id for front in storefronts])

    result = []
    for storefront in storefronts:
        result.append(
            StorefrontOut(
                **_base(storefront),
                last_order=await _last_order(session, identity.client_id, storefront.id),
                hint=await reorder_hint(session, identity.client_id, storefront.id),
                shipping_accuracy=accuracy.get(storefront.id, Accuracy()).public,
            )
        )
    return result


@router.get("/storefronts/{storefront_id}", response_model=StorefrontDetailOut)
async def storefront_detail(
    storefront_id: int,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> StorefrontDetailOut:
    allowed = {s.id: s for s in await _client_storefronts(session, identity.client_id)}
    storefront = allowed.get(storefront_id)
    if not storefront:
        raise HTTPException(status_code=404, detail="витрина не подключена")

    # Ленивая связь в асинхронной сессии не подгружается — берём явно.
    enterprise = await session.get(Enterprise, storefront.enterprise_id)
    reserved = await reserved_by_item(session, storefront_id)
    # Под заказ «доступно» — остаток дневного лимита на ближайшую дату
    # доставки: каждая заявка на эту дату его тратит.
    booked = (
        await booked_for_date(session, storefront_id, next_delivery_date(storefront))
        if storefront.mode is Mode.preorder
        else {}
    )
    items = (
        await session.execute(
            select(StorefrontItem)
            .where(
                StorefrontItem.storefront_id == storefront_id,
                StorefrontItem.hidden.is_(False),
            )
            .order_by(StorefrontItem.id)
        )
    ).scalars()

    today = datetime.now(TZ).date()
    by_item, overall = await discounts(session, storefront_id, today)
    live = await active_promos(session, storefront_id, today)
    names = {
        row.id: row.name
        for row in (
            await session.execute(
                select(StorefrontItem).where(
                    StorefrontItem.id.in_({p.item_id for p in live if p.item_id} or {0})
                )
            )
        ).scalars()
    }

    out: list[ItemOut] = []
    for item in items:
        pack = float(item.pack_size or 1)
        if storefront.mode is Mode.preorder:
            available = left_for_day(item.daily_limit, booked.get(item.id, 0.0))
        else:
            available = max(0.0, float(item.stock) - reserved.get(item.id, 0.0))
        discount = best(item.id, by_item, overall)
        price = float(item.price)
        out.append(
            ItemOut(
                id=item.id,
                name=item.name,
                unit=item.unit,
                pack_size=pack,
                price=discount.apply(price) if discount else price,
                price_before=price if discount else None,
                promo=discount.title if discount else None,
                photo_url=f"/api/photos/{item.photo_key}" if item.photo_key else None,
                available=normalize(available),
                # «Весь остаток» — предупреждение, что позиция заканчивается
                is_low=storefront.mode is Mode.stock and 0 < available <= pack * 3,
                daily_limit=None if item.daily_limit is None else float(item.daily_limit),
                min_qty=order_minimum(item.min_qty, pack),
                description=plaintext.description(item.description),
            )
        )

    kind, reach = (
        contact.effective(enterprise.contact_kind, enterprise.contact_phone, enterprise.contact_max)
        if enterprise
        else ("", "")
    )
    return StorefrontDetailOut(
        **_base(storefront),
        is_demo=(enterprise.is_demo or enterprise.is_bot) if enterprise else True,
        supplier=enterprise.name if enterprise else "",
        city=enterprise.city if enterprise else "",
        supplier_contact=reach,
        contact_kind=kind,
        contact_href=contact.href(kind, reach),
        min_amount=float(storefront.min_amount) if storefront.min_amount is not None else None,
        # Все даты, на которые примут заявку, а не ближайшие восемь: клиент
        # выбирает их календарём (экран 10), и день графика за восьмым не
        # должен выглядеть там недоступным.
        delivery_dates=delivery_dates(storefront, HORIZON_DAYS),
        volume_promos=[
            PromoOut(
                id=promo.id,
                kind=promo.kind.value,
                title=promo.title,
                description=promo.description,
                discount_percent=float(promo.discount_percent),
                item_id=promo.item_id,
                item_name=names.get(promo.item_id or 0, ""),
                min_amount=None if promo.min_amount is None else float(promo.min_amount),
                min_qty=None if promo.min_qty is None else float(promo.min_qty),
                is_live=True,
                condition=condition(promo, names.get(promo.item_id or 0, "")),
            )
            for promo in volume_conditions(live)
        ],
        promos=[
            PromoOut(
                id=promo.id,
                kind=promo.kind.value,
                title=promo.title,
                description=promo.description,
                discount_percent=float(promo.discount_percent),
                item_id=promo.item_id,
                item_name=names.get(promo.item_id or 0, ""),
                starts_on=promo.starts_on,
                ends_on=promo.ends_on,
                is_active=promo.is_active,
                is_live=True,
                condition=condition(promo, names.get(promo.item_id or 0, "")),
            )
            for promo in live
            if promo.kind.value in ("item", "storefront")
        ],
        last_order=await _last_order(session, identity.client_id, storefront_id),
        hint=await reorder_hint(session, identity.client_id, storefront_id),
        shipping_accuracy=(
            await by_storefront(session, [storefront_id])
        ).get(storefront_id, Accuracy()).public,
        items=out,
    )


@router.get("/storefronts/{storefront_id}/last-order-lines")
async def last_order_lines(
    storefront_id: int,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Позиции прошлой заявки — для «Повторить прошлый заказ»."""
    order = (
        await session.execute(
            select(Order)
            .where(
                Order.client_id == identity.client_id,
                Order.storefront_id == storefront_id,
                Order.status.notin_(NOT_REPEATED),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not order:
        return []
    # Название — чтобы сказать «не вошло: …» и про позицию, которой в витрине
    # уже нет: по одному номеру клиент её не узнает.
    names = dict(
        (
            await session.execute(
                select(StorefrontItem.id, StorefrontItem.name).where(
                    StorefrontItem.id.in_([line.item_id for line in order.items])
                )
            )
        ).all()
    )
    return [
        {
            "item_id": line.item_id,
            "name": names.get(line.item_id, ""),
            "qty": float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered),
        }
        for line in order.items
    ]


@router.get("/storefronts/{storefront_id}/contacts", response_model=ContactsOut)
async def storefront_contacts(
    storefront_id: int,
    order_id: int | None = None,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> ContactsOut:
    """Окно «Связаться»: закреплённый менеджер, кто сейчас на смене, и общий
    контакт предприятия. Раньше кнопка вела в один номер — и в выходной
    менеджера клиент звонил в пустоту."""
    allowed = {s.id: s for s in await _client_storefronts(session, identity.client_id)}
    storefront = allowed.get(storefront_id)
    if not storefront:
        raise HTTPException(status_code=404, detail="витрина не подключена")
    enterprise = await session.get(Enterprise, storefront.enterprise_id)
    kind, reach = (
        contact.effective(enterprise.contact_kind, enterprise.contact_phone, enterprise.contact_max)
        if enterprise
        else ("", "")
    )
    # Из заявки «Связаться» первым показывает того, кто её ведёт.
    order = await session.get(Order, order_id) if order_id else None
    handler = (
        order.manager_id
        if order and order.client_id == identity.client_id and order.storefront_id == storefront_id
        else None
    )
    people = await team.contacts_for_client(
        session, storefront.enterprise_id, identity.client_id, handler
    )
    # «Написать в MAX» от имени предприятия ведёт к владельцу: ссылку на
    # профиль больше не вписывают, бот присылает его карточку.
    owner = (
        (
            await session.execute(
                select(Employee)
                .where(
                    Employee.enterprise_id == storefront.enterprise_id,
                    Employee.role == Role.owner,
                )
                .order_by(Employee.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if enterprise and enterprise.max_chat
        else None
    )
    if owner is not None:
        # Владелец выключил сообщения у себя в «Аккаунте» — кнопку не даём,
        # иначе она отвечала бы отказом.
        person = (await team.people(session, {owner.max_user_id})).get(owner.max_user_id)
        if person is not None and not person.max_reachable:
            owner = None
    phone = enterprise.contact_phone if enterprise else ""
    return ContactsOut(
        supplier=enterprise.name if enterprise else "",
        people=[TeamContactOut(**asdict(row)) for row in people],
        general_kind=kind,
        general=reach,
        general_href=contact.href(kind, reach),
        general_phone=phone,
        general_phone_href=contact.phone_href(phone),
        general_employee_id=owner.id if owner else None,
    )
