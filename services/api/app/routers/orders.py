"""Заявки: от корзины клиента до документа в 1С."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import contact, exporting, links, live, onec, plaintext, shop, stock, storage, team
from ..auth import Identity, current_identity, require_client, require_staff
from ..db import get_session
from ..inventory import booked_for_date, left_for_day, reserved_by_item
from ..numbering import next_number
from ..models import (
    AcceptancePhoto, BotUser, Client, ClientWorker, Connection, Employee, Enterprise, ExchangeEvent,
    ExchangeStatus, Mode, Order, OrderItem, OrderStatus, Role, Source, Storefront, StorefrontItem,
)

# Заявка ещё в работе — и уже в истории. Отказ и отмена тоже история:
# по ним больше ничего не произойдёт.
ACTIVE = (OrderStatus.sent, OrderStatus.confirmed, OrderStatus.assembling, OrderStatus.shipped)
FINISHED = (OrderStatus.accepted, OrderStatus.closed, OrderStatus.rejected, OrderStatus.cancelled)
# История не бесконечна на экране: за полгода набегают сотни заявок, а
# вся она целиком есть в выгрузке в Excel.
HISTORY_LIMIT = 200
from ..messaging import tell
from ..promos import active as active_promos, apply_volume, best, discounts
from ..quantity import (
    EXTRA_PERCENT, ceiling, edit_floor, human, is_multiple, on_grid, order_minimum, tenths,
    to_decimal,
)
from ..schemas import (
    AcceptIn, AcceptLineIn, ConfirmIn, OrderIn, OrderLineOut, OrderOut, PhotoOut, RejectIn,
    RescheduleIn,
)
from ..schedule import (
    TZ, WEEKDAYS, can_reschedule_to, next_delivery_date, production_started, why_not_orderable,
)

router = APIRouter()


async def _notify_staff(
    session: AsyncSession,
    enterprise_id: int,
    text: str,
    kind: str = "order",
    order_id: int | None = None,
    quiet: bool = False,
    client_id: int | None = None,
) -> None:
    # По user_id, а не по chat_id: сотрудник мог ни разу не написать боту,
    # но уведомление о новой заявке обязано до него дойти. У клиента с
    # закреплённым менеджером пишем ему и владельцу — см. team.order_recipients.
    recipients = await team.order_recipients(session, enterprise_id, client_id)
    for user_id in sorted(recipients):
        await tell(
            session, user_id, text, kind=kind, order_id=order_id, quiet=quiet,
            role=recipients[user_id],
        )


async def _notify_shop(
    session: AsyncSession, order: Order, text: str, kind: str, quiet: bool = False
) -> None:
    """Магазину о заявке: владельцу точки и работнику, который её оформил."""
    recipients = await shop.order_recipients(session, order)
    for user_id in sorted(recipients):
        await tell(
            session, user_id, text, kind=kind, order_id=order.id, quiet=quiet,
            role=recipients[user_id],
        )


async def _take(session: AsyncSession, order: Order, identity: Identity, enterprise_id: int) -> None:
    """Кто ведёт заявку: если никто не закреплён, её берёт первый, кто
    обработал. Клиент видит имя рядом с номером и знает, кому звонить."""
    if order.manager_id is not None:
        return
    employee = await team.employee_of(session, enterprise_id, identity.max_user_id)
    if employee is not None:
        order.manager_id = employee.id


# Из каких статусов заявку ещё можно отгрузить. Отсюда же — «отгрузку не
# отметили»: доставка прошла, а заявка всё ещё в одном из них.
SHIPPABLE = (OrderStatus.confirmed, OrderStatus.assembling)


def _state(order: Order) -> str:
    """Что сейчас с заявкой — словами для человека. Раньше в отказе стояло
    «заявка уже в статусе «confirmed»», и клиент не понимал ни слова."""
    if order.status is OrderStatus.sent:
        return "заявка ещё ждёт подтверждения"
    if order.status is OrderStatus.confirmed:
        return "заявку уже подтвердили"
    if order.status is OrderStatus.assembling:
        return "заявку уже готовят к отгрузке"
    if order.status is OrderStatus.shipped:
        return "заявку уже отгрузили"
    if order.status in (OrderStatus.accepted, OrderStatus.closed):
        return "заявка уже завершена"
    if order.status is OrderStatus.rejected:
        return "поставщик отменил заявку" if order.confirmed_at else "поставщик отклонил заявку"
    if order.status is OrderStatus.cancelled:
        return "клиент отменил заявку"
    return "заявка ещё не отправлена"


def _day(value: date) -> str:
    """«пт, 26.09» — дата доставки в уведомлении."""
    return f"{WEEKDAYS[value.weekday()]}, {value.strftime('%d.%m')}"


async def _locked_items(
    session: AsyncSession, storefront_id: int, item_ids: list[int]
) -> dict[int, StorefrontItem]:
    """Позиции витрины под замком до конца транзакции. Две заявки на
    «последний ящик» без замка обе видели его свободным. Порядок по id —
    чтобы встречные заявки не заперли друг друга."""
    return {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem)
                .where(
                    StorefrontItem.storefront_id == storefront_id,
                    StorefrontItem.id.in_(item_ids or [0]),
                )
                .order_by(StorefrontItem.id)
                .with_for_update()
            )
        ).scalars()
    }


async def _locked_order(session: AsyncSession, order_id: int) -> Order | None:
    """Заявка под замком: повтор запроса или вторая вкладка иначе провели бы
    отгрузку или приёмку дважды — две корректировки и двойной возврат."""
    return (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()


def _pool(
    item: StorefrontItem, order: Order, reserved: dict[int, float], own: float
) -> float:
    """Сколько этой позиции может получить заявка: остаток витрины за
    вычетом того, что держат другие заявки, плюс её собственное, если оно
    уже списано."""
    others = reserved.get(item.id, 0.0) - (0.0 if order.stock_taken else own)
    return float(item.stock) + (own if order.stock_taken else 0.0) - max(0.0, others)


def _photo_url(key: str, viewer: Identity | None) -> str:
    """Снимок расхождения закрыт: <img> заголовок с подписью MAX не
    передаёт, поэтому адрес подписан для того, кто смотрит заявку."""
    path = f"/api/photos/{key}"
    if viewer is None:
        return path
    role = viewer.role.value if viewer.role else None
    return links.signed(path, viewer.max_user_id, role, links.PHOTO_TTL)


@dataclass
class _Batch:
    """Всё, что нужно списку заявок, — одним запросом на вид данных.

    Раньше каждая строка списка ходила в базу за автором, позициями,
    журналом обмена, снимками и резервом отдельно: у поставщика с сотней
    заявок это были сотни запросов на одно открытие вкладки."""
    people: dict[int, BotUser] = field(default_factory=dict)
    workers: dict[tuple[int, int], ClientWorker] = field(default_factory=dict)
    items: dict[int, StorefrontItem] = field(default_factory=dict)
    events: dict[int, ExchangeEvent] = field(default_factory=dict)
    photos: dict[int, list[AcceptancePhoto]] = field(default_factory=dict)
    reserved: dict[int, dict[int, float]] = field(default_factory=dict)


async def _batch(session: AsyncSession, orders: list[Order]) -> _Batch:
    batch = _Batch()
    if not orders:
        return batch
    ids = [order.id for order in orders]
    # Витрины, предприятия и точки — в карту сессии: дальше session.get
    # берёт их оттуда без запроса.
    fronts = {
        row.id: row
        for row in (
            await session.execute(
                select(Storefront).where(Storefront.id.in_({o.storefront_id for o in orders}))
            )
        ).scalars()
    }
    await session.execute(
        select(Enterprise).where(Enterprise.id.in_({f.enterprise_id for f in fronts.values()}))
    )
    clients = {
        row.id: row
        for row in (
            await session.execute(
                select(Client).where(Client.id.in_({o.client_id for o in orders}))
            )
        ).scalars()
    }
    authors = {
        order.created_by
        or (clients[order.client_id].max_user_id if order.client_id in clients else 0)
        for order in orders
    }
    managers = {
        row.id: row
        for row in (
            await session.execute(
                select(Employee).where(
                    Employee.id.in_({o.manager_id for o in orders if o.manager_id} or {0})
                )
            )
        ).scalars()
    }
    batch.people = await team.people(
        session, {a for a in authors if a} | {m.max_user_id for m in managers.values()}
    )
    batch.workers = {
        (row.client_id, row.max_user_id): row
        for row in (
            await session.execute(select(ClientWorker).where(ClientWorker.client_id.in_(clients)))
        ).scalars()
    }
    batch.items = {
        row.id: row
        for row in (
            await session.execute(
                select(StorefrontItem).where(
                    StorefrontItem.id.in_({line.item_id for o in orders for line in o.items} or {0})
                )
            )
        ).scalars()
    }
    for event in (
        await session.execute(
            select(ExchangeEvent).where(ExchangeEvent.order_id.in_(ids)).order_by(ExchangeEvent.at)
        )
    ).scalars():
        batch.events[event.order_id] = event  # по возрастанию: остаётся последнее
    for photo in (
        await session.execute(
            select(AcceptancePhoto)
            .where(AcceptancePhoto.order_id.in_(ids), AcceptancePhoto.attached.is_(True))
            .order_by(AcceptancePhoto.id)
        )
    ).scalars():
        batch.photos.setdefault(photo.order_id, []).append(photo)
    for storefront_id in {o.storefront_id for o in orders if o.status is OrderStatus.sent}:
        batch.reserved[storefront_id] = await reserved_by_item(session, storefront_id)
    return batch


async def _as_out(
    session: AsyncSession,
    order: Order,
    viewer: Identity | None = None,
    batch: _Batch | None = None,
) -> OrderOut:
    storefront = await session.get(Storefront, order.storefront_id)
    enterprise = (
        await session.get(Enterprise, storefront.enterprise_id) if storefront else None
    )
    client = await session.get(Client, order.client_id)
    # Кто оформил: владелец точки или работник магазина. Звонить по заявке —
    # ему, поэтому и телефон в заявке его, а не владельца.
    author_id = order.created_by or (client.max_user_id if client else None)
    if batch is not None:
        person = batch.people.get(author_id) if author_id else None
        author_worker = (
            batch.workers.get((client.id, author_id))
            if client and author_id and author_id != client.max_user_id
            else None
        )
        items = {
            line.item_id: batch.items[line.item_id]
            for line in order.items
            if line.item_id in batch.items
        }
        event = batch.events.get(order.id)
        reserved = (
            batch.reserved.get(order.storefront_id, {})
            if order.status is OrderStatus.sent
            else {}
        )
    else:
        person = (
            await session.execute(select(BotUser).where(BotUser.max_user_id == author_id))
        ).scalar_one_or_none() if author_id else None
        author_worker = (
            await shop.worker_of(session, client.id, author_id)
            if client and author_id and author_id != client.max_user_id
            else None
        )
        items = {
            item.id: item
            for item in (
                await session.execute(
                    select(StorefrontItem).where(
                        StorefrontItem.id.in_([line.item_id for line in order.items] or [0])
                    )
                )
            ).scalars()
        }
        event = (
            await session.execute(
                select(ExchangeEvent)
                .where(ExchangeEvent.order_id == order.id)
                .order_by(ExchangeEvent.at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        # Поставщику, который подтверждает, нужен остаток для этой заявки: с
        # её собственным товаром, если он уже списан, и за вычетом того, что
        # держат другие. Столько же проверит сервер при подтверждении.
        reserved = (
            await reserved_by_item(session, order.storefront_id)
            if order.status is OrderStatus.sent
            else {}
        )
    lines = [
        OrderLineOut(
            item_id=line.item_id,
            name=items[line.item_id].name if line.item_id in items else "",
            unit=items[line.item_id].unit if line.item_id in items else "шт",
            pack_size=float(items[line.item_id].pack_size) if line.item_id in items else 1,
            min_qty=(
                order_minimum(items[line.item_id].min_qty, items[line.item_id].pack_size)
                if line.item_id in items
                else None
            ),
            stock=(
                max(0.0, _pool(items[line.item_id], order, reserved, float(line.qty_ordered)))
                if line.item_id in items
                else 0
            ),
            price=float(line.price),
            qty_ordered=float(line.qty_ordered),
            qty_confirmed=None if line.qty_confirmed is None else float(line.qty_confirmed),
            qty_accepted=None if line.qty_accepted is None else float(line.qty_accepted),
            change_reason=line.change_reason,
            acceptance_issue=line.acceptance_issue,
            photo_url=(
                f"/api/photos/{items[line.item_id].photo_key}"
                if line.item_id in items and items[line.item_id].photo_key
                else None
            ),
        )
        for line in order.items
    ]
    # В заявке только снимки, прикреплённые при приёмке: снятое и отменённое
    # вместе с расхождением не должно всплывать в закрытой заявке.
    attached = (
        batch.photos.get(order.id, [])
        if batch is not None
        else (
            await session.execute(
                select(AcceptancePhoto)
                .where(AcceptancePhoto.order_id == order.id, AcceptancePhoto.attached.is_(True))
                .order_by(AcceptancePhoto.id)
            )
        ).scalars()
    )
    photos = [
        PhotoOut(
            key=photo.object_key, url=_photo_url(photo.object_key, viewer), item_id=photo.item_id
        )
        for photo in attached
    ]
    kind, reach = (
        contact.effective(enterprise.contact_kind, enterprise.contact_phone, enterprise.contact_max)
        if enterprise
        else ("", "")
    )
    client_phone = person.phone if person else ""
    manager = await session.get(Employee, order.manager_id) if order.manager_id else None
    manager_person = (
        (
            batch.people if batch is not None
            else await team.people(session, {manager.max_user_id})
        ).get(manager.max_user_id)
        if manager
        else None
    )

    total_ordered = sum(line.price * line.qty_ordered for line in lines)
    confirmed = [line for line in lines if line.qty_confirmed is not None]
    total_confirmed = (
        sum(line.price * (line.qty_confirmed or 0) for line in confirmed) if confirmed else None
    )
    # lines уже пересчитаны во float выше, поэтому здесь чистая арифметика

    return OrderOut(
        id=order.id,
        number=order.label,
        storefront_id=order.storefront_id,
        storefront_name=storefront.name if storefront else "",
        storefront_mode=storefront.mode.value if storefront else "stock",
        storefront_source=storefront.source.value if storefront else "manual",
        stock_synced_at=storefront.stock_synced_at if storefront else None,
        client_name=client.name if client else "",
        status=order.status.value,
        delivery_date=order.delivery_date,
        created_at=order.created_at,
        comment=order.comment,
        onec_document=order.onec_document,
        onec_correction=order.onec_correction,
        supplier=enterprise.name if enterprise else "",
        supplier_contact=reach,
        contact_kind=kind,
        contact_href=contact.href(kind, reach),
        supplier_comment=order.supplier_comment,
        accepted_early=order.accepted_early,
        accepted_at=order.accepted_at,
        client_address=client.address if client else "",
        client_phone=client_phone,
        client_phone_href=contact.phone_href(client_phone),
        client_chat_href=contact.user_chat(person.username if person else ""),
        client_id=order.client_id,
        author=person.title if person and (person.first_name or person.last_name) else "",
        author_worker_id=author_worker.id if author_worker else None,
        client_reachable=person.max_reachable if person else True,
        manager_id=order.manager_id,
        manager=team.display_name(manager, manager_person) if manager else "",
        onec_status=event.status.value if event else None,
        confirmed_at=order.confirmed_at,
        ship_overdue=(
            order.status in SHIPPABLE and order.delivery_date < datetime.now(TZ).date()
        ),
        total_ordered=round(float(total_ordered), 2),
        total_confirmed=round(float(total_confirmed), 2) if total_confirmed is not None else None,
        photos=photos,
        lines=lines,
    )


@router.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(
    payload: OrderIn,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    connection = (
        await session.execute(
            select(Connection).where(
                Connection.client_id == identity.client_id,
                Connection.storefront_id == payload.storefront_id,
                Connection.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=403, detail="витрина не подключена")

    storefront = await session.get(Storefront, payload.storefront_id)
    if not storefront:
        raise HTTPException(status_code=404, detail="витрина не найдена")

    lines = [line for line in payload.lines if line.qty > 0]
    if not lines:
        raise HTTPException(status_code=400, detail="в заявке нет позиций")
    ids = [line.item_id for line in lines]
    if len(ids) != len(set(ids)):
        # Интерфейс так не присылает, но запрос в обход него проверил бы
        # остаток по каждой строке отдельно и взял бы товар дважды.
        raise HTTPException(
            status_code=422, detail="одна позиция указана в заявке дважды — сложите количество"
        )
    if payload.delivery_date is not None:
        problem = why_not_orderable(storefront, payload.delivery_date)
        if problem:
            raise HTTPException(status_code=422, detail=problem)

    # Остаток читаем уже под замком: иначе две одновременные заявки видят
    # «последний ящик» свободным и забирают его обе.
    catalog = await _locked_items(session, storefront.id, ids)
    reserved = await reserved_by_item(session, storefront.id)
    # Цена фиксируется в заявке, поэтому скидку надо учесть здесь же:
    # акция, которая видна только в каталоге, превращается в обман.
    today = datetime.now(TZ).date()
    by_item, overall = await discounts(session, storefront.id, today)

    order = Order(
        storefront_id=storefront.id,
        client_id=identity.client_id,
        delivery_date=payload.delivery_date or next_delivery_date(storefront),
        status=OrderStatus.sent,
        # Комментарий уезжает в документ 1С и в сообщение поставщику —
        # длину режем здесь, а не надеемся на форму.
        comment=plaintext.comment(payload.comment),
        created_by=identity.max_user_id,
    )
    # Закреплённый менеджер ведёт заявку с первой минуты: клиент сразу
    # видит, кто ею занимается.
    personal = await team.personal_manager(session, storefront.enterprise_id, identity.client_id)
    if personal is not None:
        order.manager_id = personal.id
    order.number = await next_number(session, storefront.enterprise_id)

    # Под заказ проверяем дневной лимит на выбранную дату: без этого пекарне
    # с лимитом 240 батонов приходили заявки на 1000, а «доступно» в каталоге
    # не менялось сколько ни заказывай.
    booked = (
        await booked_for_date(session, storefront.id, order.delivery_date)
        if storefront.mode is Mode.preorder
        else {}
    )

    for line in lines:
        item = catalog.get(line.item_id)
        if not item:
            raise HTTPException(status_code=400, detail=f"позиции {line.item_id} нет в витрине")
        if item.hidden:
            raise HTTPException(
                status_code=409, detail=f"«{item.name}» поставщик убрал из витрины"
            )
        # Оптовая торговля идёт коробками: произвольное количество приводит
        # к ручной правке на стороне поставщика.
        if not on_grid(line.qty):
            raise HTTPException(
                status_code=422,
                detail=f"«{item.name}»: количество задаётся с точностью до 0,1 {item.unit}",
            )
        if not is_multiple(line.qty, item.pack_size):
            raise HTTPException(
                status_code=422,
                detail=f"«{item.name}»: количество кратно {human(item.pack_size, item.unit)}",
            )
        # Меньше минимума поставщик не возит: такую заявку он отклонил бы
        # всё равно, только позже и уже после сборки остальных.
        need = order_minimum(item.min_qty, item.pack_size)
        if need is not None and float(line.qty) < need - 1e-9:
            raise HTTPException(
                status_code=422,
                detail=f"«{item.name}»: минимум в заказе — {human(need, item.unit)}",
            )
        if storefront.mode is Mode.stock:
            available = max(0.0, float(item.stock) - reserved.get(item.id, 0.0))
            if float(line.qty) > available + 1e-9:
                raise HTTPException(
                    status_code=409,
                    detail=f"«{item.name}»: доступно {human(available, item.unit)}",
                )
        elif item.daily_limit is not None:
            left = left_for_day(item.daily_limit, booked.get(item.id, 0.0))
            if float(line.qty) > left + 1e-9:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"«{item.name}»: на {order.delivery_date.strftime('%d.%m')} можно "
                        f"заказать ещё {human(left, item.unit)}"
                    ),
                )
        discount = best(item.id, by_item, overall)
        price = discount.apply(float(item.price)) if discount else float(item.price)
        order.items.append(
            OrderItem(item_id=item.id, qty_ordered=to_decimal(line.qty), price=price)
        )

    # Объёмные акции считаются по набранной заявке, а не по позиции:
    # «−10 % от 5 000 ₽» нельзя показать ценой в каталоге, но в заявке
    # она обязана сработать, иначе обещание остаётся баннером.
    volume, applied = apply_volume(
        await active_promos(session, storefront.id, today),
        [
            (line.item_id, float(line.qty_ordered), float(line.price))
            for line in order.items
        ],
    )
    for line in order.items:
        if line.item_id in volume:
            line.price = volume[line.item_id]

    # Минимальная сумма — свойство витрины: «от 3 000 ₽» у оптовика
    # означает, что заявку меньше этой суммы он не повезёт.
    if storefront.min_amount:
        total = sum(float(line.price) * float(line.qty_ordered) for line in order.items)
        if total < float(storefront.min_amount):
            raise HTTPException(
                status_code=422,
                detail=f"минимальная сумма заявки — {float(storefront.min_amount):.0f} ₽, "
                       f"набрано {total:.0f} ₽",
            )

    session.add(order)
    await session.commit()
    await session.refresh(order)
    # Заявка зарезервировала остаток: у других клиентов «доступно» меньше,
    # и корзина того, кто выбирал ту же позицию, должна узнать об этом сразу.
    await live.stock_changed(session, storefront.id)
    await live.order_changed(session, order)
    # Заказ уходит в 1С сразу, не дожидаясь поставщика: резерв в учёте
    # появляется в ту же минуту. Фоном — клиент не ждёт ответа 1С.
    onec.later(order.id)

    total = sum(float(line.price) * float(line.qty_ordered) for line in order.items)
    # Про сработавшую акцию говорим в том же сообщении: отдельное
    # уведомление «вам дали скидку» читается как реклама.
    bonus = (
        " Сработало: " + "; ".join(row.title for row in applied) + "."
        if applied
        else ""
    )
    await tell(
        session,
        identity.max_user_id,
        f"Заявка №{order.label} отправлена в «{storefront.name}»: "
        f"{len(order.items)} поз. на {total:.0f} ₽, доставка "
        f"{order.delivery_date.strftime('%d.%m')}.{bonus} Ждём подтверждения поставщика.",
        kind="order",
        order_id=order.id,
        # Заявку клиент только что отправил сам — значок об этом лишний.
        quiet=True,
        role=identity.role.value if identity.role else "client",
    )
    if identity.role is Role.worker:
        # Владелец точки узнаёт, что заказал работник: это его деньги.
        client = await session.get(Client, identity.client_id)
        if client and client.max_user_id != identity.max_user_id:
            author = (
                await session.execute(
                    select(BotUser).where(BotUser.max_user_id == identity.max_user_id)
                )
            ).scalar_one_or_none()
            who = author.title if author else "Работник"
            await tell(
                session,
                client.max_user_id,
                f"{who} оформил заявку №{order.label} в «{storefront.name}»: "
                f"{len(order.items)} поз. на {total:.0f} ₽, доставка "
                f"{order.delivery_date.strftime('%d.%m')}.",
                kind="order",
                order_id=order.id,
                quiet=True,
                role="client",
            )

    # Уведомления идут обеим сторонам: заявка, о которой менеджер узнаёт
    # только зайдя в приложение, — это тот же телефонный разговор, только хуже.
    await _notify_staff(
        session,
        storefront.enterprise_id,
        f"Новая заявка №{order.label} в «{storefront.name}»: "
        f"{len(order.items)} поз. на {total:.0f} ₽, доставка {order.delivery_date.strftime('%d.%m')}.",
        kind="order",
        order_id=order.id,
        # Новая заявка горит на «Заявках»; второй значок на «Аккаунте» — дубль.
        quiet=True,
        client_id=order.client_id,
    )

    return await _as_out(session, order, identity)


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    scope: str | None = None,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> list[OrderOut]:
    """Заявки. scope=active — в работе, scope=history — завершённые,
    отменённые и отклонённые; без scope — все подряд."""
    query = select(Order).order_by(Order.created_at.desc())
    if scope == "active":
        query = query.where(Order.status.in_(ACTIVE))
    elif scope == "history":
        query = query.where(Order.status.in_(FINISHED)).limit(HISTORY_LIMIT)
    if identity.buyer:
        query = query.where(Order.client_id == identity.client_id)
    elif identity.role in (Role.manager, Role.owner):
        query = query.join(Storefront, Storefront.id == Order.storefront_id).where(
            Storefront.enterprise_id == identity.enterprise_id
        )
    else:
        raise HTTPException(status_code=403, detail="нет доступа к заявкам")

    orders = list((await session.execute(query)).scalars())
    batch = await _batch(session, orders)
    return [await _as_out(session, order, identity, batch) for order in orders]


@router.get("/orders/export.csv")
async def export_my_orders(
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """История закупок клиента таблицей: сверить с накладными за месяц
    проще в Excel, чем листая экраны."""
    orders = list(
        (
            await session.execute(
                select(Order).where(Order.client_id == identity.client_id).order_by(Order.created_at)
            )
        ).scalars()
    )
    body = await exporting.orders_csv(session, orders)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="my-orders.csv"'},
    )


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="заявка не найдена")

    if identity.buyer:
        if order.client_id != identity.client_id:
            raise HTTPException(status_code=404, detail="заявка не найдена")
    elif identity.staff:
        storefront = await session.get(Storefront, order.storefront_id)
        if not storefront or storefront.enterprise_id != identity.enterprise_id:
            raise HTTPException(status_code=404, detail="заявка не найдена")
    else:
        # Без роли в продукте чужую заявку не открыть даже по номеру.
        raise HTTPException(status_code=404, detail="заявка не найдена")

    return await _as_out(session, order, identity)


@router.post("/orders/{order_id}/confirm", response_model=OrderOut)
async def confirm_order(
    order_id: int,
    payload: ConfirmIn,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    # Под замком: выгрузка новой заявки в 1С идёт фоном и может совпасть с
    # подтверждением.
    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="заявка не найдена")

    storefront = await session.get(Storefront, order.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status is not OrderStatus.sent:
        raise HTTPException(status_code=409, detail=_state(order))

    # Сколько заявка держала до подтверждения — от этого считается, что
    # вернуть на склад или добрать.
    before = onec.held(order)
    corrections = {line.item_id: line for line in payload.lines}
    changed: list[str] = []
    # Под замком, как при оформлении: пока менеджер подтверждает, другая
    # заявка не должна забрать тот же остаток.
    catalog = await _locked_items(
        session, storefront.id, [line.item_id for line in order.items]
    )
    reserved = (
        await reserved_by_item(session, storefront.id) if storefront.mode is Mode.stock else {}
    )

    # Проверяем всё до первой записи: половина подтверждённой заявки хуже,
    # чем понятный отказ с перечнем того, что поправить.
    for line in order.items:
        correction = corrections.get(line.item_id)
        if not correction:
            continue
        item = catalog.get(line.item_id)
        name = item.name if item else "позиция"
        unit = item.unit if item else "шт"
        pack = item.pack_size if item else 1
        if correction.qty < 0 or not on_grid(correction.qty):
            raise HTTPException(status_code=422, detail=f"«{name}»: количество с шагом 0,1")
        if not is_multiple(correction.qty, pack):
            raise HTTPException(
                status_code=422, detail=f"«{name}»: количество кратно упаковке — {human(pack, unit)}"
            )
        top = ceiling(line.qty_ordered, pack)
        if tenths(correction.qty) > tenths(top):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"«{name}»: добавить можно не больше {EXTRA_PERCENT} % от заказанного — "
                    f"до {human(top, unit)}"
                ),
            )
        # Уменьшить можно до минимума позиции, а не до нуля: меньше клиент и
        # сам заказать не смог бы. Ноль остаётся только позиции, которой на
        # складе меньше этого предела: её не набрать, и она уходит из заявки,
        # а не держит всю заявку неподтверждённой.
        least = edit_floor(line.qty_ordered, item.min_qty, pack) if item else 0.0
        if tenths(correction.qty) < tenths(least):
            short = (
                storefront.mode is Mode.stock
                and _pool(item, order, reserved, before.get(line.item_id, 0.0)) + 1e-9 < least
            )
            if not (short and tenths(correction.qty) == 0):
                raise HTTPException(
                    status_code=422,
                    detail=f"«{name}»: уменьшить можно только до {human(least, unit)}",
                )

    # Остаток мог уменьшиться, пока заявка ждала: списание в 1С, продажа
    # мимо приложения. Подтвердить больше, чем есть, значит обещать клиенту
    # товар, которого нет, — поэтому сервер проверяет сам, а не верит экрану.
    if storefront.mode is Mode.stock:
        for line in order.items:
            item = catalog.get(line.item_id)
            if item is None:
                continue
            correction = corrections.get(line.item_id)
            wanted = float(correction.qty) if correction else float(line.qty_ordered)
            pool = _pool(item, order, reserved, before.get(line.item_id, 0.0))
            # Ноль со склада ничего не берёт: позиция, которую не набрать,
            # уходит из заявки, даже если чужие резервы увели остаток в минус.
            if wanted > 1e-9 and wanted > pool + 1e-9:
                raise HTTPException(
                    status_code=409,
                    detail=f"«{item.name}»: на складе {human(max(0.0, pool), item.unit)} — уменьшите количество",
                )

    for line in order.items:
        correction = corrections.get(line.item_id)
        line.qty_confirmed = (
            to_decimal(correction.qty) if correction else line.qty_ordered
        )
        if correction and tenths(correction.qty) != tenths(line.qty_ordered):
            # Причину знает только менеджер. Подставлять «остаток меньше»
            # за него — значит врать клиенту, когда количество выросло.
            line.change_reason = (correction.reason or "").strip()[:200] or None
            item = catalog.get(line.item_id)
            name = item.name if item else "позиция"
            unit = item.unit if item else "шт"
            changed.append(
                f"{name}: {human(line.qty_ordered, unit)} → {human(correction.qty, unit)}"
            )

    order.supplier_comment = plaintext.comment(payload.comment)

    # Отсечка этой даты уже прошла — витрина «под заказ» готовит её сразу.
    order.status = (
        OrderStatus.assembling
        if production_started(storefront, order.delivery_date)
        else OrderStatus.confirmed
    )
    order.confirmed_at = onec.stock_synced_now()
    await _take(session, order, identity, storefront.enterprise_id)

    # Заказ уже в 1С с оформления — правим количества и согласуем; нет —
    # выгружаем сейчас. Остаток витрины меняется вместе с учётом. Если 1С
    # недоступна, заявка всё равно подтверждается, выгрузка уходит в
    # очередь: внешняя система не имеет права уронить основной сценарий.
    await onec.confirm_order(session, order, storefront.enterprise_id, before)
    await session.commit()
    await session.refresh(order)
    await live.order_changed(session, order)
    await live.stock_changed(session, storefront.id)
    if storefront.source is Source.onec:
        # Сверяемся с 1С: там заказ тоже списал товар, и источник правды —
        # она. Фоном, чтобы не задерживать ответ менеджеру.
        stock.later(storefront.id)

    # Изменения — первыми словами: уведомление читают по началу, а «Заявка
    # подтверждена» звучит так, будто всё осталось как заказали.
    text = (
        f"Заявка №{order.label} подтверждена с изменениями: " + "; ".join(changed) + "."
        if changed
        else f"Заявка №{order.label} подтверждена."
    )
    if order.supplier_comment:
        text += f" Комментарий поставщика: {order.supplier_comment}"
    await _notify_shop(session, order, text, kind="confirmed")

    return await _as_out(session, order, identity)


@router.post("/orders/{order_id}/reject", response_model=OrderOut)
async def reject_order(
    order_id: int,
    payload: RejectIn,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Отказ поставщика: до подтверждения — отклонить заявку, после —
    отменить поставку, которую не смогли выполнить. Резерв снимается,
    позиции возвращаются в витрину."""
    order = await _locked_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="заявка не найдена")

    storefront = await session.get(Storefront, order.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status is not OrderStatus.sent and order.status not in SHIPPABLE:
        raise HTTPException(status_code=409, detail=_state(order))
    # О подтверждённой поставке клиент уже договорился и ждёт машину:
    # отменить её молча нельзя, нужна причина.
    agreed = order.status in SHIPPABLE
    if agreed and not payload.reason.strip():
        raise HTTPException(status_code=422, detail="напишите клиенту, почему поставка отменяется")

    before = onec.held(order)
    order.status = OrderStatus.rejected
    order.supplier_comment = plaintext.comment(payload.reason)
    reason = order.supplier_comment or "поставщик отклонил заявку"
    for line in order.items:
        line.qty_confirmed = to_decimal(0)
    await _take(session, order, identity, storefront.enterprise_id)
    # Заказ в 1С снимается с проведения: товар возвращается на склад.
    await onec.cancel_order(session, order, storefront.enterprise_id, before)

    await session.commit()
    await session.refresh(order)
    # Отказ снимает резерв — позиции снова доступны другим.
    await live.order_changed(session, order)
    await live.stock_changed(session, order.storefront_id)
    if storefront.source is Source.onec:
        stock.later(storefront.id)

    text = (
        f"Поставщик отменил заявку №{order.label}: {reason}"
        if agreed
        else f"Заявка №{order.label} отклонена: {reason}"
    )
    await _notify_shop(session, order, text, kind="rejected")

    return await _as_out(session, order, identity)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: int,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Клиент может отменить заявку, пока её не подтвердили."""
    order = await _locked_order(session, order_id)
    if not order or order.client_id != identity.client_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status in SHIPPABLE:
        raise HTTPException(
            status_code=409,
            detail="заявку уже подтвердили — отменить её может поставщик, свяжитесь с ним",
        )
    if order.status is not OrderStatus.sent:
        raise HTTPException(status_code=409, detail=_state(order))

    before = onec.held(order)
    order.status = OrderStatus.cancelled
    storefront = await session.get(Storefront, order.storefront_id)
    await onec.cancel_order(
        session, order, storefront.enterprise_id if storefront else None, before
    )
    await session.commit()
    await session.refresh(order)
    await live.order_changed(session, order)
    await live.stock_changed(session, order.storefront_id)
    if storefront and storefront.source is Source.onec:
        stock.later(storefront.id)

    # Раньше отмена проходила молча: поставщик узнавал о ней, только открыв
    # заявку, которую уже собирался подтверждать.
    if storefront:
        client = await session.get(Client, order.client_id)
        await _notify_staff(
            session,
            storefront.enterprise_id,
            f"Заявка №{order.label} отменена клиентом"
            f"{f' ({client.name})' if client else ''}. Резерв снят, подтверждать её не нужно.",
            kind="cancelled",
            order_id=order.id,
            client_id=order.client_id,
        )
    return await _as_out(session, order, identity)


async def _attach_photos(
    session: AsyncSession, order_id: int, keep: list[str] | None
) -> list[str]:
    """Прикрепляет к заявке снимки, оставшиеся в приёмке, остальные снимает.

    Снимок загружается сразу после съёмки: держать его до отправки в памяти
    телефона — значит потерять при первом сбое сети. Но расхождение можно
    отменить, и тогда его снимок заявке не принадлежит. Возвращает ключи,
    которые можно стереть из хранилища, когда приёмка сохранится.
    """
    pending = list(
        (
            await session.execute(
                select(AcceptancePhoto).where(
                    AcceptancePhoto.order_id == order_id, AcceptancePhoto.attached.is_(False)
                )
            )
        ).scalars()
    )
    dropped: list[str] = []
    for photo in pending:
        if keep is None or photo.object_key in keep:
            photo.attached = True
        else:
            dropped.append(photo.object_key)
            await session.delete(photo)
    return dropped


# Из каких статусов клиент может принять заявку. «В сборке» и
# «подтверждена» — досрочная приёмка: товар приехал раньше отметки.
ACCEPTABLE = (OrderStatus.confirmed, OrderStatus.assembling, OrderStatus.shipped)

ISSUE_LABELS = {
    "short": "недовоз",
    "mismatch": "пересорт",
    "damaged": "брак",
    "expiry": "срок годности",
}


@router.post("/orders/{order_id}/ship", response_model=OrderOut)
async def ship_order(
    order_id: int,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    order = await _locked_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    storefront = await session.get(Storefront, order.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status not in SHIPPABLE:
        raise HTTPException(status_code=409, detail=_state(order))

    order.status = OrderStatus.shipped
    await _take(session, order, identity, storefront.enterprise_id)
    await session.commit()
    await session.refresh(order)
    await live.order_changed(session, order)

    await _notify_shop(
        session,
        order,
        f"Заявка №{order.label} отгружена. Примите товар в приложении и отметьте расхождения, если они есть.",
        kind="shipped",
        # Ждущая приёмки заявка горит на «Заказах» — там и дело.
        quiet=True,
    )
    return await _as_out(session, order, identity)


@router.post("/orders/{order_id}/reschedule", response_model=OrderOut)
async def reschedule_order(
    order_id: int,
    payload: RescheduleIn,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Перенос доставки. Чаще всего — из вопроса «отгрузку не отметили»:
    машина не ушла, и клиенту нужна новая дата, а не тишина. Дату выбирает
    поставщик — хоть вне графика: везти ли в неурочный день, решает он."""
    order = await _locked_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    storefront = await session.get(Storefront, order.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status not in SHIPPABLE:
        raise HTTPException(status_code=409, detail=_state(order))
    day = payload.delivery_date
    if not can_reschedule_to(day):
        raise HTTPException(
            status_code=422, detail="перенести можно на сегодня или позже — не дальше двух месяцев"
        )
    if day == order.delivery_date:
        raise HTTPException(status_code=422, detail="доставка уже назначена на этот день")

    previous = order.delivery_date
    order.delivery_date = day
    # Перенесли на дату, отсечка которой ещё впереди, — производство по
    # ней не началось, и заявка снова просто подтверждена.
    order.status = (
        OrderStatus.assembling if production_started(storefront, day) else OrderStatus.confirmed
    )
    comment = plaintext.comment(payload.comment)
    if comment:
        order.supplier_comment = comment
    await _take(session, order, identity, storefront.enterprise_id)
    await onec.reschedule_order(session, order, storefront.enterprise_id)
    await session.commit()
    await session.refresh(order)
    await live.order_changed(session, order)

    text = f"Поставщик перенёс доставку по заявке №{order.label}: {_day(previous)} → {_day(day)}."
    if comment:
        text += f" Комментарий: {comment}"
    await _notify_shop(session, order, text, kind="rescheduled")
    return await _as_out(session, order, identity)


@router.post("/orders/{order_id}/accept", response_model=OrderOut)
async def accept_order(
    order_id: int,
    payload: AcceptIn,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Приёмка. Пустой список позиций означает «принято полностью».

    Принять можно и до отметки об отгрузке: машина приезжает раньше, чем
    менеджер доходит до кнопки, и держать клиента без приёмки из-за этого
    нельзя. До подтверждения — нельзя: состав заявки ещё не согласован.
    """
    order = await _locked_order(session, order_id)
    if not order or order.client_id != identity.client_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if order.status is OrderStatus.sent:
        raise HTTPException(
            status_code=409, detail="заявку ещё не подтвердили — принимать пока нечего"
        )
    if order.status not in ACCEPTABLE:
        raise HTTPException(status_code=409, detail=_state(order))

    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(
                    StorefrontItem.id.in_([line.item_id for line in order.items] or [0])
                )
            )
        ).scalars()
    }
    # Проверяем всё до первой записи. Интерфейс ограничивает количество, но
    # запрос в обход него с отрицательным числом превращал «возврат на
    # склад» в прибавку остатка, а с чужой позицией — в мусор в 1С.
    facts: dict[int, AcceptLineIn] = {}
    lines_by_item = {line.item_id: line for line in order.items}
    for fact in payload.lines:
        line = lines_by_item.get(fact.item_id)
        if line is None:
            raise HTTPException(status_code=422, detail="в приёмке позиция, которой нет в заявке")
        if fact.item_id in facts:
            raise HTTPException(status_code=422, detail="одна позиция указана в приёмке дважды")
        item = catalog.get(fact.item_id)
        name = item.name if item else "позиция"
        unit = item.unit if item else "шт"
        expected = float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
        if fact.qty < 0 or not on_grid(fact.qty):
            raise HTTPException(status_code=422, detail=f"«{name}»: количество от нуля, с шагом 0,1")
        if fact.qty > expected + 1e-9:
            raise HTTPException(
                status_code=422,
                detail=f"«{name}»: принять можно не больше, чем везли, — {human(expected, unit)}",
            )
        if fact.issue is not None and fact.issue not in ISSUE_LABELS:
            raise HTTPException(status_code=422, detail=f"«{name}»: такого вида расхождения нет")
        facts[fact.item_id] = fact
    order.accepted_early = order.status is not OrderStatus.shipped
    order.accepted_at = datetime.now(TZ)

    problems: list[str] = []
    for line in order.items:
        expected = float(
            line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered
        )
        fact = facts.get(line.item_id)
        line.qty_accepted = to_decimal(fact.qty) if fact else to_decimal(expected)
        line.acceptance_issue = fact.issue if fact else None
        if float(line.qty_accepted) != expected or line.acceptance_issue:
            item = catalog.get(line.item_id)
            name = item.name if item else "позиция"
            unit = item.unit if item else "шт"
            label = ISSUE_LABELS.get(line.acceptance_issue or "", line.acceptance_issue or "расхождение")
            problems.append(
                f"{name}: {human(line.qty_accepted, unit)} из {human(expected, unit)} ({label})"
            )

    order.status = OrderStatus.accepted
    dropped = await _attach_photos(session, order.id, payload.photos)

    storefront = await session.get(Storefront, order.storefront_id)
    # Расхождения уходят в 1С отдельным документом. Как и с заказом,
    # недоступность 1С не мешает клиенту закрыть приёмку: выгрузка встаёт
    # в очередь, а факт уже зафиксирован.
    await onec.export_acceptance(
        session, order, problems, storefront.enterprise_id if storefront else None
    )

    # Непринятое возвращается на склад: при подтверждении мы списали всё
    # подтверждённое, а доехала часть. Раньше остаток после приёмки «по
    # факту» не менялся, и недовезённый товар из витрины пропадал. Витрину
    # из 1С правит сама 1С по корректировке — остаток заберём оттуда.
    returned = {
        line.item_id: float(
            line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered
        ) - float(line.qty_accepted or 0)
        for line in order.items
    }
    if (
        storefront
        and storefront.mode is Mode.stock
        and storefront.source is not Source.onec
        and order.stock_taken
    ):
        for item_id, qty in returned.items():
            item = catalog.get(item_id)
            if item and qty > 0:
                item.stock = to_decimal(float(item.stock) + qty)

    await session.commit()
    await session.refresh(order)
    await live.order_changed(session, order)
    if storefront and any(qty > 0 for qty in returned.values()):
        await live.stock_changed(session, storefront.id)
        if storefront.source is Source.onec:
            stock.later(storefront.id)
    for key in dropped:
        storage.remove(key)

    if storefront:
        early = " досрочно, до отметки об отгрузке" if order.accepted_early else ""
        if problems:
            await _notify_staff(
                session,
                storefront.enterprise_id,
                f"Заявка №{order.label} завершена: клиент принял товар{early}, есть расхождения. "
                + "; ".join(problems),
                kind="accepted",
                order_id=order.id,
                client_id=order.client_id,
            )
        else:
            await _notify_staff(
                session, storefront.enterprise_id,
                f"Заявка №{order.label} завершена: клиент принял товар полностью{early}.",
                kind="accepted",
                order_id=order.id, client_id=order.client_id,
            )

    return await _as_out(session, order, identity)
