"""Кабинет владельца: сводка, клиенты, сотрудники, витрины, обмен с 1С.

Четыре права сверх менеджера из концепта: видеть предприятие цифрами,
управлять сотрудниками, ценами и витринами, подключать клиентов.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import date as date_type
from datetime import datetime, timedelta
from datetime import time as time_type
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import (
    contact, exporting, invites, live, metrics, onec, plaintext, pricelist, promos, reminders,
    secret_box, shop, spreadsheet, stock, storage, team,
)
from ..audience import known_chat, remember_chat
from ..messaging import tell
from ..notify import send
from ..quantity import human, is_multiple, on_grid, tenths, to_decimal
from ..schedule import TZ
from ..auth import Identity, require_owner, require_staff
from ..db import get_session
from ..models import (
    BotUser, Client, ClientManager, Connection, Employee, Enterprise, ExchangeEvent,
    ExchangeStatus, Invite, Mode, Notification, OneCCounterparty, Order, OrderItem, OrderStatus,
    OrderTemplateLine, PriceChange, Promo, PromoKind, Reminder, Role, Source, Storefront,
    StorefrontItem,
)
from ..schemas import (
    AudienceInviteIn, AudienceRowOut, ClientDetailOut, ClientManagerIn, ClientOrderOut,
    ClientRowOut, ClientStorefrontOut, ConnectionDecisionIn, ConnectionRowOut, EmployeeRowOut,
    EnterpriseIn,
    EnterpriseOut, ExchangeRowOut, ImportReportOut, ItemCreateIn, ItemEditIn, ItemRowOut,
    OneCCounterpartyIn, OneCCounterpartyOut, OneCListsIn,
    OwnerSummaryOut, PriceChangeOut, PromoIn, PromoOut, ShopPersonOut, StaffOptionOut,
    StorefrontCreateIn, StorefrontSettingsIn, StorefrontSettingsOut, TopItemOut,
)
from .cities import CityError, one_city

router = APIRouter()


def _item_row(item: StorefrontItem) -> ItemRowOut:
    """Одна сборка строки позиции: количества дробные, и три независимых
    преобразования Decimal → float неизбежно разошлись бы."""
    return ItemRowOut(
        id=item.id,
        name=item.name,
        unit=item.unit,
        pack_size=float(item.pack_size),
        price=float(item.price),
        stock=float(item.stock),
        daily_limit=None if item.daily_limit is None else float(item.daily_limit),
        min_qty=None if item.min_qty is None else float(item.min_qty),
        photo_url=f"/api/photos/{item.photo_key}" if item.photo_key else None,
        description=plaintext.description(item.description),
        hidden=bool(item.hidden),
        onec_missing=bool(item.onec_missing),
    )


def _min_qty(value: float | None, pack: object, unit: str) -> Decimal | None:
    """Минимум в одной заявке. Ноль или пусто — минимума нет. Кратен
    упаковке: «от 30 шт» при коробке по 12 клиент всё равно не наберёт —
    ближайшее, что получится, 36."""
    if not value:
        return None
    if value < 0:
        raise HTTPException(status_code=422, detail="минимум не может быть меньше нуля")
    if not on_grid(value):
        raise HTTPException(
            status_code=422, detail=f"минимум задаётся с точностью до 0,1 {unit}"
        )
    if not is_multiple(value, pack):
        raise HTTPException(
            status_code=422, detail=f"минимум должен быть кратен упаковке — {human(pack, unit)}"
        )
    return to_decimal(value)


async def _profile(session: AsyncSession, enterprise: Enterprise) -> tuple[int, list[str]]:
    """Насколько заполнено то, что клиент видит о поставщике.

    Три пункта, и каждый работает на клиента: по городу витрину находят
    на полке, по контакту работает «Связаться», логотип отличает плитку от
    соседней. Название не считаем — без него предприятия не бывает, и
    процент от него только врал бы. Описание витрины тоже не считаем: оно
    необязательно, и без него профиль не хуже.
    """
    fronts = list(
        (
            await session.execute(
                select(Storefront).where(Storefront.enterprise_id == enterprise.id)
            )
        ).scalars()
    )
    checks = [
        ("город", bool(enterprise.city.strip())),
        ("контакт", bool(enterprise.contact_phone or enterprise.max_chat or enterprise.contact_max)),
        ("логотип", bool(fronts) and all(front.logo_key for front in fronts)),
    ]
    done = sum(1 for _, ok in checks if ok)
    return round(100 * done / len(checks)), [label for label, ok in checks if not ok]


# Клиент считается «спящим», если не заказывал столько дней. Владелец должен
# узнавать об уходе клиента раньше, чем через полгода.
SLEEPING_AFTER_DAYS = 21

SETTLED = (
    OrderStatus.confirmed, OrderStatus.assembling, OrderStatus.shipped,
    OrderStatus.accepted, OrderStatus.closed,
)


async def _enterprise_orders(session: AsyncSession, enterprise_id: int):
    return (
        select(Order)
        .join(Storefront, Storefront.id == Order.storefront_id)
        .where(Storefront.enterprise_id == enterprise_id)
    )


@router.get("/owner/summary", response_model=OwnerSummaryOut)
async def owner_summary(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerSummaryOut:
    since = datetime.now().date() - timedelta(days=7)

    every = list(
        (
            await session.execute(
                (await _enterprise_orders(session, identity.enterprise_id)).where(
                    Order.status.notin_((OrderStatus.draft, OrderStatus.cancelled))
                )
            )
        ).scalars()
    )
    # Деньги считаем только по тем, что поставщик подтвердил: неподтверждённая
    # заявка — ещё не оборот.
    orders = [order for order in every if order.status in SETTLED]
    waiting = [order for order in every if order.status is OrderStatus.sent]

    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem)
                .join(Storefront, Storefront.id == StorefrontItem.storefront_id)
                .where(Storefront.enterprise_id == identity.enterprise_id)
            )
        ).scalars()
    }

    revenue_week = 0.0
    revenue_total = 0.0
    tops: dict[int, float] = {}

    for order in orders:
        amount = sum(
            float(line.price)
            * float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
            for line in order.items
        )
        revenue_total += amount
        if order.created_at.date() >= since:
            revenue_week += amount
        for line in order.items:
            qty = float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
            tops[line.item_id] = tops.get(line.item_id, 0.0) + qty

    # Точность отгрузки считается там же, где её видит клиент на полке:
    # владелец и покупатель должны смотреть на одно число.
    own = list(
        (
            await session.execute(
                select(Storefront.id).where(Storefront.enterprise_id == identity.enterprise_id)
            )
        ).scalars()
    )
    accuracy = metrics.combine(
        list((await metrics.by_storefront(session, own)).values())
    ).percent

    rows = (
        await session.execute(
            select(Client, func.min(Connection.at))
            .join(Connection, Connection.client_id == Client.id)
            .join(Storefront, Storefront.id == Connection.storefront_id)
            .where(Storefront.enterprise_id == identity.enterprise_id)
            .group_by(Client.id)
        )
    ).all()
    clients = [client for client, _ in rows]
    connected_at = {client.id: at for client, at in rows}

    last_order_at: dict[int, datetime] = {}
    for order in every:
        current = last_order_at.get(order.client_id)
        if current is None or order.created_at > current:
            last_order_at[order.client_id] = order.created_at

    sleeping: list[ClientRowOut] = []
    threshold = datetime.now(tz=None).date() - timedelta(days=SLEEPING_AFTER_DAYS)
    for client in clients:
        last = last_order_at.get(client.id)
        joined = connected_at.get(client.id)
        # Тот, кто подключился на этой неделе, не мог «перестать заказывать»:
        # ему ещё нечего было прекращать.
        if joined is not None and joined.date() > threshold:
            continue
        if last is None or last.date() <= threshold:
            sleeping.append(
                ClientRowOut(
                    id=client.id,
                    name=client.name,
                    address=client.address,
                    connected_at=joined,
                    orders=sum(1 for o in every if o.client_id == client.id),
                    last_order_at=last,
                )
            )

    enterprise = await session.get(Enterprise, identity.enterprise_id)
    percent, missing = await _profile(session, enterprise) if enterprise else (0, [])

    pending = (
        await session.execute(
            select(func.count(Connection.id))
            .join(Storefront, Storefront.id == Connection.storefront_id)
            .where(
                Storefront.enterprise_id == identity.enterprise_id,
                Connection.status == "request",
            )
        )
    ).scalar_one()
    staff = (
        await session.execute(
            select(func.count(Employee.id)).where(Employee.enterprise_id == identity.enterprise_id)
        )
    ).scalar_one()
    queued = (
        await session.execute(
            select(func.count(ExchangeEvent.id)).where(
                ExchangeEvent.enterprise_id == identity.enterprise_id,
                ExchangeEvent.status == ExchangeStatus.queued,
            )
        )
    ).scalar_one()
    linked = (
        await session.execute(
            select(func.count(Storefront.id)).where(
                Storefront.enterprise_id == identity.enterprise_id,
                Storefront.source == Source.onec,
            )
        )
    ).scalar_one()
    # Ближайшая отгрузка — та же дата, которую откроет «Сводка на завтра».
    today = datetime.now(TZ).date()
    planned = [
        order for order in every
        if order.status in (OrderStatus.confirmed, OrderStatus.assembling)
        and order.delivery_date >= today
    ]
    nearest = min((order.delivery_date for order in planned), default=None)

    return OwnerSummaryOut(
        enterprise=enterprise.name if enterprise else "",
        city=enterprise.city if enterprise else "",
        storefronts_total=len(own),
        revenue_week=round(revenue_week, 2),
        revenue_total=round(revenue_total, 2),
        orders_total=len(every),
        orders_new=len(waiting),
        clients_total=len(clients),
        shipping_accuracy=accuracy,
        top_items=[
            TopItemOut(
                item_id=item_id,
                name=catalog[item_id].name if item_id in catalog else "",
                unit=catalog[item_id].unit if item_id in catalog else "шт",
                qty=qty,
            )
            for item_id, qty in sorted(tops.items(), key=lambda pair: -pair[1])[:5]
        ],
        sleeping_clients=sleeping,
        connections_pending=int(pending),
        staff_total=int(staff),
        profile_percent=percent,
        profile_missing=missing,
        exchange_queued=int(queued),
        onec_linked=int(linked),
        planned_orders=sum(1 for order in planned if order.delivery_date == nearest),
        planned_date=nearest,
    )


@router.get("/owner/clients", response_model=list[ClientRowOut])
async def owner_clients(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[ClientRowOut]:
    rows = await session.execute(
        select(
            Client,
            # Отменённые и отклонённые — не заказы: как и в карточке клиента.
            func.count(Order.id).filter(
                Order.status.notin_([OrderStatus.cancelled, OrderStatus.rejected])
            ),
            func.max(Order.created_at),
            func.min(Connection.at),
        )
        .join(Connection, Connection.client_id == Client.id)
        .join(Storefront, Storefront.id == Connection.storefront_id)
        # Только заявки в витрины этого предприятия: у кафе бывают и другие
        # поставщики, и их заявки в чужой список не входят.
        .outerjoin(
            Order, (Order.client_id == Client.id) & (Order.storefront_id == Storefront.id)
        )
        .where(Storefront.enterprise_id == identity.enterprise_id)
        .group_by(Client.id)
        .order_by(Client.name)
    )
    rows = list(rows)
    managers = await _managers_by_client(session, identity.enterprise_id)
    return [
        ClientRowOut(
            id=client.id,
            name=client.name,
            address=client.address,
            orders=int(orders or 0),
            last_order_at=last,
            connected_at=joined,
            manager=managers.get(client.id, ""),
        )
        for client, orders, last, joined in rows
    ]


async def _managers_by_client(session: AsyncSession, enterprise_id: int) -> dict[int, str]:
    """Имя закреплённого менеджера по клиенту — для списка клиентов."""
    rows = list(
        (
            await session.execute(
                select(ClientManager.client_id, Employee)
                .join(Employee, Employee.id == ClientManager.employee_id)
                .where(ClientManager.enterprise_id == enterprise_id)
            )
        ).all()
    )
    known = await team.people(session, {employee.max_user_id for _, employee in rows})
    return {
        client_id: team.display_name(employee, known.get(employee.max_user_id))
        for client_id, employee in rows
    }


async def _own_client(session: AsyncSession, enterprise_id: int, client_id: int) -> Client:
    """Клиент этого предприятия: подключён или просится хотя бы к одной витрине.
    Чужого клиента по угаданному номеру не показываем."""
    client = await session.get(Client, client_id)
    linked = (
        await session.execute(
            select(Connection.id)
            .join(Storefront, Storefront.id == Connection.storefront_id)
            .where(Connection.client_id == client_id, Storefront.enterprise_id == enterprise_id)
            .limit(1)
        )
    ).first()
    if client is None or linked is None:
        raise HTTPException(status_code=404, detail="клиент не найден")
    return client


async def _client_detail(session: AsyncSession, enterprise_id: int, client: Client) -> ClientDetailOut:
    person = (
        await session.execute(select(BotUser).where(BotUser.max_user_id == client.max_user_id))
    ).scalar_one_or_none()
    storefronts = [
        ClientStorefrontOut(
            id=storefront.id, name=storefront.name, status=connection.status,
            connection_id=connection.id,
        )
        for connection, storefront in (
            await session.execute(
                select(Connection, Storefront)
                .join(Storefront, Storefront.id == Connection.storefront_id)
                .where(Connection.client_id == client.id, Storefront.enterprise_id == enterprise_id)
                .order_by(Storefront.id)
            )
        ).all()
    ]
    orders = list(
        (
            await session.execute(
                select(Order)
                .join(Storefront, Storefront.id == Order.storefront_id)
                .where(Order.client_id == client.id, Storefront.enterprise_id == enterprise_id)
                .order_by(Order.created_at.desc())
            )
        ).scalars()
    )
    names = {row.id: row.name for row in storefronts}

    def total(order: Order) -> float:
        return round(
            sum(
                float(line.price)
                * float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
                for line in order.items
            ),
            2,
        )

    done = [
        order for order in orders
        if order.status not in (OrderStatus.rejected, OrderStatus.cancelled, OrderStatus.draft)
    ]
    staff = list(
        (
            await session.execute(
                select(Employee).where(Employee.enterprise_id == enterprise_id).order_by(Employee.id)
            )
        ).scalars()
    )
    known = await team.people(session, {row.max_user_id for row in staff})
    manager = await team.personal_manager(session, enterprise_id, client.id)
    phone = person.phone if person else ""
    return ClientDetailOut(
        id=client.id,
        name=client.name,
        address=client.address,
        person=person.title if person and (person.first_name or person.last_name) else "",
        phone=phone,
        phone_href=contact.phone_href(phone),
        chat_href=contact.user_chat(person.username if person else ""),
        storefronts=storefronts,
        orders=len(done),
        revenue=round(sum(total(order) for order in done), 2),
        last_order_at=orders[0].created_at if orders else None,
        recent=[
            ClientOrderOut(
                id=order.id,
                number=order.label,
                storefront=names.get(order.storefront_id, ""),
                status=order.status.value,
                delivery_date=order.delivery_date,
                total=total(order),
            )
            for order in orders[:5]
        ],
        manager_id=manager.id if manager else None,
        staff=[
            StaffOptionOut(
                id=row.id,
                name=team.display_name(row, known.get(row.max_user_id)),
                role=row.role.value,
                hours=team.hours_text(row),
            )
            for row in staff
        ],
        # Кто в магазине сейчас на месте: работнику, оформившему заявку, и
        # звонят, а не владельцу точки.
        people=[ShopPersonOut(**asdict(row)) for row in await shop.people(session, client)],
    )


@router.get("/owner/clients/{client_id}", response_model=ClientDetailOut)
async def owner_client(
    client_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ClientDetailOut:
    """Карточка клиента: кто это, как связаться, что заказывал и кто его ведёт."""
    client = await _own_client(session, identity.enterprise_id, client_id)
    return await _client_detail(session, identity.enterprise_id, client)


@router.put("/owner/clients/{client_id}/manager", response_model=ClientDetailOut)
async def assign_manager(
    client_id: int,
    payload: ClientManagerIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ClientDetailOut:
    """Закрепить менеджера за клиентом или снять закрепление (null).

    Один менеджер на клиента: так проще и клиенту — «мой менеджер Иван», —
    и сотрудникам, которым не нужно выяснять, чей это клиент.
    """
    client = await _own_client(session, identity.enterprise_id, client_id)
    current = (
        await session.execute(
            select(ClientManager).where(
                ClientManager.enterprise_id == identity.enterprise_id,
                ClientManager.client_id == client.id,
            )
        )
    ).scalar_one_or_none()

    if payload.employee_id is None:
        if current is not None:
            await session.delete(current)
    else:
        employee = await session.get(Employee, payload.employee_id)
        if employee is None or employee.enterprise_id != identity.enterprise_id:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        if current is None:
            session.add(
                ClientManager(
                    enterprise_id=identity.enterprise_id,
                    client_id=client.id,
                    employee_id=employee.id,
                )
            )
        else:
            current.employee_id = employee.id
    await session.commit()
    await live.publish([client.max_user_id], "contacts")
    return await _client_detail(session, identity.enterprise_id, client)


@router.get("/owner/staff", response_model=list[EmployeeRowOut])
async def owner_staff(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[EmployeeRowOut]:
    employees = list(
        (
            await session.execute(
                select(Employee)
                .where(Employee.enterprise_id == identity.enterprise_id)
                .order_by(Employee.id)
            )
        ).scalars()
    )
    known = await team.people(session, {row.max_user_id for row in employees})
    clients = dict(
        (
            await session.execute(
                select(ClientManager.employee_id, func.count(ClientManager.id))
                .where(ClientManager.enterprise_id == identity.enterprise_id)
                .group_by(ClientManager.employee_id)
            )
        ).all()
    )
    return [
        EmployeeRowOut(
            id=employee.id,
            name=team.display_name(employee, known.get(employee.max_user_id)),
            role=employee.role.value,
            notifications=True,  # пишем по user_id, диалог с ботом не нужен
            hours=team.hours_text(employee),
            on_shift=team.on_shift(employee),
            phone=(known.get(employee.max_user_id).phone if known.get(employee.max_user_id) else ""),
            clients=int(clients.get(employee.id, 0)),
        )
        for employee in employees
    ]


@router.get("/owner/exchange", response_model=list[ExchangeRowOut])
async def owner_exchange(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[ExchangeRowOut]:
    """Журнал обмена: что ушло, что не ушло и почему."""
    rows = (
        await session.execute(
            select(ExchangeEvent)
            .where(ExchangeEvent.enterprise_id == identity.enterprise_id)
            .order_by(ExchangeEvent.at.desc())
            .limit(50)
        )
    ).scalars()
    return [
        ExchangeRowOut(
            id=event.id,
            direction=event.direction,
            object_kind=event.object_kind,
            order_id=event.order_id,
            status=event.status.value,
            external_key=event.external_key,
            message=event.message,
            at=event.at,
        )
        for event in rows
    ]


@router.get("/owner/storefronts", response_model=list[StorefrontSettingsOut])
async def owner_storefronts(
    # Менеджер работает с каталогом каждый день: список витрин ему нужен.
    # Все правки ниже остаются за владельцем.
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> list[StorefrontSettingsOut]:
    storefronts = list(
        (
            await session.execute(
                select(Storefront)
                .where(Storefront.enterprise_id == identity.enterprise_id)
                .order_by(Storefront.id)
            )
        ).scalars()
    )
    return [await _settings_out(session, storefront) for storefront in storefronts]


@router.patch("/owner/storefronts/{storefront_id}", response_model=StorefrontSettingsOut)
async def update_storefront(
    storefront_id: int,
    payload: StorefrontSettingsIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)

    if payload.name is not None:
        name = payload.name.strip()[:200]
        if not name:
            raise HTTPException(status_code=422, detail="название не может быть пустым")
        storefront.name = name
        storefront.initials = _initials(name)
    if payload.mode is not None:
        try:
            storefront.mode = Mode(payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="режим — stock или preorder") from exc
    onec_before = (storefront.onec_key, storefront.onec_url, storefront.onec_user)
    if payload.onec_key is not None:
        storefront.onec_key = payload.onec_key.strip()[:200]
        # Ключ и источник — одно решение: витрина с ключом ведётся из 1С,
        # без ключа — вручную.
        storefront.source = Source.onec if storefront.onec_key else Source.manual
        if storefront.onec_key:
            # Тестовая база по ключу вместо своей: своя больше не нужна.
            storefront.onec_user = ""
            storefront.onec_password = ""
    if payload.onec_user is not None:
        _own_base(storefront, payload)
    elif payload.onec_url is not None:
        storefront.onec_url = _onec_url(payload.onec_url)
    _onec_options(storefront, payload)
    if payload.source is not None:
        try:
            storefront.source = Source(payload.source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="источник — onec или manual") from exc
    if payload.onec_key is not None or payload.onec_url is not None or payload.source is not None:
        await _check_onec(session, storefront, identity.enterprise_id)
    if storefront.source is Source.manual:
        # Без 1С сверки больше нет: скрытое ею «нет в 1С» возвращается в
        # витрину, иначе висело бы скрытым навсегда.
        await session.execute(
            update(StorefrontItem)
            .where(StorefrontItem.storefront_id == storefront.id, StorefrontItem.onec_missing.is_(True))
            .values(onec_missing=False, hidden=False)
        )
    # Сменили базу — прежние ссылки на организацию и склад к ней не относятся.
    if (storefront.onec_key, storefront.onec_url, storefront.onec_user) != onec_before and (
        payload.onec_refs is None
    ):
        storefront.onec_settings = {
            **onec.settings_of(storefront).stored(),
            **{key: "" for key in (*onec.onec_settings.REFS, "partner")},
            "names": {},
        }
    if payload.cutoff_at is not None:
        storefront.cutoff_at = _parse_cutoff(payload.cutoff_at) if payload.cutoff_at else None
    if storefront.mode is Mode.preorder and storefront.cutoff_at is None:
        raise HTTPException(status_code=422, detail="для витрины «под заказ» нужна отсечка")
    if payload.delivery_days is not None:
        storefront.delivery_days = payload.delivery_days.strip()[:40]
    if payload.min_amount is not None:
        storefront.min_amount = payload.min_amount or None
    if payload.is_public is not None:
        storefront.is_public = payload.is_public
    if payload.show_prices_public is not None:
        storefront.show_prices_public = payload.show_prices_public
    if payload.color is not None:
        color = payload.color.strip()
        if color and not _is_color(color):
            raise HTTPException(status_code=422, detail="цвет в формате #RRGGBB")
        storefront.color = color or None
    if payload.about is not None:
        storefront.about = payload.about.strip()[:160]
    if payload.remind_before_minutes is not None:
        # Сутки — верхняя граница: отсечка суточная, напоминать раньше
        # предыдущей отсечки бессмысленно.
        storefront.remind_before_minutes = max(0, min(payload.remind_before_minutes, 1440))

    await session.commit()
    if storefront.source is Source.onec and (
        payload.onec_key is not None or payload.onec_user is not None or payload.onec_refs is not None
        or payload.onec_preset is not None
    ):
        # Позиции, цены и остатки — по новым настройкам, не дожидаясь фона.
        stock.later(storefront.id)
    return await _settings_out(session, storefront)


def _own_base(storefront: Storefront, payload: StorefrontSettingsIn) -> None:
    """Своя база 1С: адрес публикации, служебный пользователь и пароль.

    Пароль хранится зашифрованным и обратно не отдаётся; пустое поле при
    сохранении — «оставить прежний». Пустой адрес — своя база отключена.
    """
    url = (payload.onec_url if payload.onec_url is not None else storefront.onec_url).strip()
    user = (payload.onec_user or "").strip()[:100]
    if not url:
        storefront.onec_url = ""
        storefront.onec_user = ""
        storefront.onec_password = ""
        if not storefront.onec_key:
            storefront.source = Source.manual
        return
    if not user:
        raise HTTPException(status_code=422, detail="укажите пользователя 1С для обмена")
    password = payload.onec_password or ""
    if not password and not storefront.onec_password:
        raise HTTPException(status_code=422, detail="укажите пароль пользователя 1С")
    storefront.onec_url = _onec_url(url)
    storefront.onec_user = user
    if password:
        storefront.onec_password = secret_box.seal(password[:200])
    # Своя база вместо тестовой: ключ стенда больше не нужен.
    storefront.onec_key = ""
    storefront.source = Source.onec


def _onec_options(storefront: Storefront, payload: StorefrontSettingsIn) -> None:
    """Версия конфигурации, реквизиты заказа и резерв."""
    if payload.onec_reserve_now is not None:
        storefront.onec_reserve_now = payload.onec_reserve_now
    if payload.onec_preset is None and payload.onec_refs is None:
        return
    current = onec.settings_of(storefront)
    if payload.onec_preset is not None:
        if payload.onec_preset not in onec.onec_settings.PRESETS:
            raise HTTPException(status_code=422, detail="такой версии конфигурации 1С нет в списке")
        current.preset = payload.onec_preset
    if payload.onec_refs is not None:
        names = dict(current.names)
        for key in onec.onec_settings.REFS:
            chosen = payload.onec_refs.get(key)
            if chosen is None:
                continue
            ref = str(chosen.get("key") or "")
            if ref and not onec.odata.GUID.match(ref):
                raise HTTPException(status_code=422, detail="значение из 1С испорчено — выберите заново")
            setattr(current, key, ref)
            names[key] = str(chosen.get("name") or "")[:200] if ref else ""
            if key == "contractor":
                partner = str(chosen.get("partner") or "")
                current.partner = partner if onec.odata.GUID.match(partner) else ""
        current.names = names
    storefront.onec_settings = current.stored()


@router.post("/owner/storefronts/{storefront_id}/onec/lists")
async def onec_lists(
    storefront_id: int,
    payload: OneCListsIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Проверка подключения и списки для выбора: организации, склады, виды
    цен, валюты, контрагенты, соглашения — из самой базы.

    Работает и до сохранения: владелец видит, что база отвечает, прежде
    чем витрина перейдёт на неё."""
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    probe = Storefront(
        enterprise_id=storefront.enterprise_id,
        name=storefront.name,
        mode=storefront.mode,
        source=Source.onec,
        onec_key=storefront.onec_key,
        onec_url=storefront.onec_url,
        onec_user=storefront.onec_user,
        onec_password=storefront.onec_password,
        onec_settings=dict(storefront.onec_settings or {}),
    )
    if payload.onec_key is not None and payload.onec_key.strip():
        probe.onec_key = payload.onec_key.strip()[:200]
        probe.onec_url = probe.onec_user = probe.onec_password = ""
    if payload.onec_user is not None and (payload.onec_url or "").strip():
        probe.onec_key = ""
        probe.onec_url = _onec_url(payload.onec_url or "")
        probe.onec_user = payload.onec_user.strip()[:100]
        if payload.onec_password:
            probe.onec_password = secret_box.seal(payload.onec_password[:200])
        elif not storefront.onec_password or storefront.onec_url != probe.onec_url:
            raise HTTPException(status_code=422, detail="укажите пароль пользователя 1С")
    if payload.onec_preset:
        probe.onec_settings = {**probe.onec_settings, "preset": payload.onec_preset}
    if not probe.onec_key and not onec.own_base(probe):
        enterprise = await session.get(Enterprise, identity.enterprise_id)
        if enterprise is None or not enterprise.is_demo:
            raise HTTPException(status_code=422, detail="укажите ключ тестовой базы или адрес своей")
    client = onec.backend(probe)
    if not isinstance(client, onec.odata.ODataOneC):
        raise HTTPException(status_code=409, detail="на стенде обмен с 1С выключен")
    try:
        return await client.lists()
    except onec.OneCUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/owner/clients/{client_id}/onec", response_model=list[OneCCounterpartyOut])
async def client_counterparties(
    client_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[OneCCounterpartyOut]:
    """Каким контрагентом 1С магазин оформляется на витринах предприятия,
    которые ведутся в 1С и к которым он подключён."""
    fronts = list(
        (
            await session.execute(
                select(Storefront)
                .join(Connection, Connection.storefront_id == Storefront.id)
                .where(
                    Storefront.enterprise_id == identity.enterprise_id,
                    Storefront.source == Source.onec,
                    Connection.client_id == client_id,
                    Connection.status == "active",
                )
                .order_by(Storefront.id)
            )
        ).scalars()
    )
    mapped = {
        row.storefront_id: row
        for row in (
            await session.execute(
                select(OneCCounterparty).where(
                    OneCCounterparty.client_id == client_id,
                    OneCCounterparty.storefront_id.in_([front.id for front in fronts] or [0]),
                )
            )
        ).scalars()
    }
    return [
        OneCCounterpartyOut(
            storefront_id=front.id,
            storefront=front.name,
            contractor_key=mapped[front.id].contractor_key if front.id in mapped else "",
            name=mapped[front.id].name if front.id in mapped else "",
            default_name=onec.settings_of(front).names.get("contractor", ""),
        )
        for front in fronts
    ]


def _check_refs(*refs: str) -> None:
    """Ссылки 1С приходят из списка базы — только GUID. Иное — испорченный
    запрос, и в заказ такое не уйдёт."""
    for ref in refs:
        if ref and not onec.odata.GUID.match(ref):
            raise HTTPException(status_code=422, detail="значение из 1С испорчено — выберите заново")


async def _map_counterparty(
    session: AsyncSession, storefront_id: int, client_id: int,
    contractor_key: str, partner_key: str, name: str,
) -> None:
    """Каким контрагентом 1С магазин идёт в заказы витрины. Пустой ключ —
    снова контрагент по умолчанию из настроек витрины."""
    row = (
        await session.execute(
            select(OneCCounterparty).where(
                OneCCounterparty.client_id == client_id,
                OneCCounterparty.storefront_id == storefront_id,
            )
        )
    ).scalar_one_or_none()
    if not contractor_key:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(
            OneCCounterparty(
                storefront_id=storefront_id, client_id=client_id,
                contractor_key=contractor_key, partner_key=partner_key,
                name=name.strip()[:200],
            )
        )
    else:
        row.contractor_key = contractor_key
        row.partner_key = partner_key
        row.name = name.strip()[:200]


@router.put("/owner/clients/{client_id}/onec/{storefront_id}", response_model=OneCCounterpartyOut)
async def set_client_counterparty(
    client_id: int,
    storefront_id: int,
    payload: OneCCounterpartyIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OneCCounterpartyOut:
    """Сопоставить магазин с контрагентом 1С. Пустой ключ — снова по умолчанию."""
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    connected = (
        await session.execute(
            select(Connection.id).where(
                Connection.client_id == client_id,
                Connection.storefront_id == storefront.id,
                Connection.status == "active",
            )
        )
    ).first()
    if not connected:
        raise HTTPException(status_code=404, detail="клиент не подключён к этой витрине")
    _check_refs(payload.contractor_key, payload.partner_key)
    await _map_counterparty(
        session, storefront.id, client_id, payload.contractor_key, payload.partner_key, payload.name
    )
    await session.commit()
    return OneCCounterpartyOut(
        storefront_id=storefront.id,
        storefront=storefront.name,
        contractor_key=payload.contractor_key,
        name=payload.name.strip()[:200] if payload.contractor_key else "",
        default_name=onec.settings_of(storefront).names.get("contractor", ""),
    )


@router.post("/owner/reminders/run")
async def run_reminders(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ручной прогон напоминаний по своему предприятию.

    В фоне они идут сами раз в несколько минут, но на демо ждать нечего:
    владелец нажимает кнопку и видит, что именно ушло клиентам.
    """
    return await reminders.run(session, identity.enterprise_id)


@router.get("/integrations/1c")
async def integration_status(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Что настроено и что для боевого подключения ещё нужно."""
    storefronts = list(
        (
            await session.execute(
                select(Storefront).where(Storefront.enterprise_id == identity.enterprise_id)
            )
        ).scalars()
    )
    linked = [row for row in storefronts if row.source is Source.onec]
    own = [row for row in storefronts if row.onec_key or onec.own_base(row)]
    last = (
        await session.execute(
            select(ExchangeEvent)
            .where(ExchangeEvent.enterprise_id == identity.enterprise_id)
            .order_by(ExchangeEvent.at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    queued = (
        await session.execute(
            select(func.count(ExchangeEvent.id)).where(
                ExchangeEvent.enterprise_id == identity.enterprise_id,
                ExchangeEvent.status == ExchangeStatus.queued,
            )
        )
    ).scalar_one()

    return {
        "mode": onec.MODE,
        "title": onec.mode_title(own[0] if own else None),
        "live": bool(own) or onec.MODE == "odata",
        "own_base": bool(own),
        "bases": sorted({onec.connection(row)[0].rsplit("/", 1)[-1] for row in own}),
        "storefronts": len(storefronts),
        "linked": len(linked),
        "queued": int(queued),
        "last_exchange_at": last.at.isoformat() if last else None,
        "needs": [
            "опубликованная база 1С по HTTPS с включённым OData",
            "служебный пользователь с правами на чтение номенклатуры, цен и остатков",
            "право создавать, изменять и проводить «Заказ клиента»",
            "организация, склад, вид цен, валюта и контрагент — выбираются в настройках витрины",
        ],
    }


@router.post("/integrations/1c/sync", status_code=202)
async def sync_1c(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Синхронизация номенклатуры, цен и остатков по всем витринам на 1С.

    Витрины на ручном ведении пропускаются, но в журнале это видно: владелец
    должен понимать, почему позиция не обновилась, а не гадать.
    """
    storefronts = list(
        (
            await session.execute(
                select(Storefront).where(Storefront.enterprise_id == identity.enterprise_id)
            )
        ).scalars()
    )

    linked = [row for row in storefronts if row.source is Source.onec]
    skipped = len(storefronts) - len(linked)
    for storefront in storefronts:
        if storefront.source is not Source.onec:
            session.add(
                ExchangeEvent(
                    direction="in",
                    object_kind="Номенклатура, цены, остатки",
                    enterprise_id=identity.enterprise_id,
                    status=ExchangeStatus.done,
                    message=f"витрина «{storefront.name}» ведётся вручную, обмен не требуется",
                )
            )

    if not linked:
        await session.commit()
        return {"accepted": True, "storefronts": 0, "skipped": skipped, "created": 0, "updated": 0}

    created = updated = 0
    for storefront in linked:
        try:
            pulled = await stock.pull(session, storefront, identity.max_user_id)
        except onec.OneCUnavailable as exc:
            # Неудачная синхронизация не ломает витрину: клиент продолжает
            # видеть прежние остатки с прежней меткой актуальности.
            session.add(
                ExchangeEvent(
                    direction="in",
                    object_kind="Номенклатура, цены, остатки",
                    enterprise_id=identity.enterprise_id,
                    status=ExchangeStatus.failed,
                    message=f"витрина «{storefront.name}»: обмен не удался — {exc}",
                )
            )
            await session.commit()
            raise HTTPException(status_code=502, detail=f"1С недоступна: {exc}") from exc
        created += pulled.created
        updated += pulled.updated

    await session.commit()
    # Открытые каталоги и корзины узнают о новых остатках сразу.
    for storefront in linked:
        await live.stock_changed(session, storefront.id)
    return {
        "accepted": True,
        "storefronts": len(linked),
        "skipped": skipped,
        "created": created,
        "updated": updated,
    }


@router.post("/integrations/1c/retry", status_code=202)
async def retry_exchange(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Повторная выгрузка того, что застряло в очереди."""
    return await onec.retry_queued(session)


# --- подключения клиентов ---


def _connection_row(
    connection: Connection, client: Client | None, storefront: Storefront
) -> ConnectionRowOut:
    on_onec = storefront.source is Source.onec
    return ConnectionRowOut(
        id=connection.id,
        client_id=connection.client_id,
        client_name=client.name if client else "",
        storefront_id=storefront.id,
        storefront_name=storefront.name,
        status=connection.status,
        onec=on_onec,
        onec_default=onec.settings_of(storefront).names.get("contractor", "") if on_onec else "",
    )


@router.get("/owner/connections", response_model=list[ConnectionRowOut])
async def owner_connections(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[ConnectionRowOut]:
    rows = await session.execute(
        select(Connection, Client, Storefront)
        .join(Client, Client.id == Connection.client_id)
        .join(Storefront, Storefront.id == Connection.storefront_id)
        .where(Storefront.enterprise_id == identity.enterprise_id)
        .order_by(Connection.status, Client.name)
    )
    rows = list(rows)
    # Просьба о подключении горит в «Аккаунте», пока владелец не придёт сюда:
    # открыл список — увидел, значок больше не нужен.
    seen = await session.execute(
        update(Notification)
        .where(
            Notification.max_user_id == identity.max_user_id,
            Notification.kind == "join_request",
            Notification.read_at.is_(None),
        )
        .values(read_at=func.now())
    )
    if seen.rowcount:
        await session.commit()
        await live.publish([identity.max_user_id], "badges", "feed")
    return [_connection_row(connection, client, storefront) for connection, client, storefront in rows]


@router.post("/owner/connections/{connection_id}/{decision}", response_model=ConnectionRowOut)
async def decide_connection(
    connection_id: int,
    decision: str,
    payload: ConnectionDecisionIn | None = None,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ConnectionRowOut:
    """Решение по подключению: одобрить просьбу или отказать в ней, отключить
    клиента от витрины или подключить снова. При одобрении владелец сразу
    называет менеджера, который будет вести клиента: клиент без менеджера —
    это заявки, о которых узнают все и не отвечает никто.

    Отключение не отменяет заявок, которые уже в работе: их поставщик ведёт
    до конца, а новую в эту витрину клиент уже не оформит."""
    if decision not in ("approve", "block"):
        raise HTTPException(status_code=422, detail="решение — approve или block")

    connection = await session.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="подключение не найдено")
    storefront = await session.get(Storefront, connection.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="подключение не найдено")

    manager = None
    if decision == "approve" and payload and payload.employee_id:
        manager = await session.get(Employee, payload.employee_id)
        if manager is None or manager.enterprise_id != identity.enterprise_id:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
    # Контрагент 1С выбирают сразу при подключении (просьба пользователя):
    # первая же заявка клиента уйдёт в 1С на него, а не на контрагента по
    # умолчанию. Проверяем до первой записи.
    counterparty = decision == "approve" and payload is not None and bool(payload.contractor_key)
    if counterparty:
        if storefront.source is not Source.onec:
            raise HTTPException(status_code=422, detail="витрина не ведётся в 1С — контрагент ей не нужен")
        _check_refs(payload.contractor_key, payload.partner_key)

    # Отключают подключённого: без сообщения витрина просто пропала бы у
    # него из списка, и он искал бы ошибку.
    disconnected = decision == "block" and connection.status == "active"
    connection.status = "active" if decision == "approve" else "blocked"
    if manager is not None:
        current = (
            await session.execute(
                select(ClientManager).where(
                    ClientManager.enterprise_id == identity.enterprise_id,
                    ClientManager.client_id == connection.client_id,
                )
            )
        ).scalar_one_or_none()
        if current is None:
            session.add(
                ClientManager(
                    enterprise_id=identity.enterprise_id,
                    client_id=connection.client_id,
                    employee_id=manager.id,
                )
            )
        else:
            current.employee_id = manager.id
    if counterparty:
        await _map_counterparty(
            session, storefront.id, connection.client_id,
            payload.contractor_key, payload.partner_key, payload.contractor_name,
        )
    await session.commit()

    client = await session.get(Client, connection.client_id)
    await live.connections_changed(session, storefront.enterprise_id)
    if client:
        await live.shop_connection_changed(session, client, storefront.id)
    if decision == "approve" and client:
        await tell(
            session,
            client.max_user_id,
            f"Поставщик подключил вас к витрине «{storefront.name}». Можно собирать заявку.",
            kind="connection",
            storefront_id=storefront.id,
        )
    elif disconnected and client:
        await tell(
            session,
            client.max_user_id,
            f"Поставщик отключил вас от витрины «{storefront.name}». Новые заявки в неё "
            "не оформить, а те, что уже в работе, остаются в силе.",
            kind="connection",
        )

    return _connection_row(connection, client, storefront)


# --- позиции и цены ---


@router.get("/owner/storefronts/{storefront_id}/items", response_model=list[ItemRowOut])
async def owner_items(
    storefront_id: int,
    identity: Identity = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> list[ItemRowOut]:
    storefront = await session.get(Storefront, storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="витрина не найдена")
    items = (
        await session.execute(
            select(StorefrontItem)
            .where(StorefrontItem.storefront_id == storefront_id)
            .order_by(StorefrontItem.id)
        )
    ).scalars()
    return [
        _item_row(item)
        for item in items
    ]


@router.patch("/owner/items/{item_id}", response_model=ItemRowOut)
async def edit_item(
    item_id: int,
    payload: ItemEditIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ItemRowOut:
    item = await session.get(StorefrontItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    storefront = await session.get(Storefront, item.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="позиция не найдена")

    if payload.price is not None and float(payload.price) != float(item.price):
        if payload.price <= 0:
            raise HTTPException(status_code=422, detail="цена должна быть больше нуля")
        # История цен копится сама: поставщик должен уметь показать клиенту,
        # когда и на сколько менялась цена.
        session.add(
            PriceChange(
                item_id=item.id,
                old_price=item.price,
                new_price=payload.price,
                changed_by=identity.max_user_id,
            )
        )
        item.price = payload.price

    if payload.stock is not None:
        item.stock = to_decimal(max(0.0, payload.stock))
    if payload.daily_limit is not None:
        item.daily_limit = to_decimal(payload.daily_limit) if payload.daily_limit else None
    # Название и единица у витрины на 1С приходят из 1С: правка здесь
    # прожила бы до ближайшей сверки. Кратности в типовой УТ нет — её
    # задаёт поставщик и у витрины на 1С.
    name = (payload.name or "").strip()[:300]
    unit = (payload.unit or "").strip()[:20]
    name_changed = payload.name is not None and name != item.name
    unit_changed = payload.unit is not None and unit != item.unit
    pack_changed = payload.pack_size is not None and tenths(payload.pack_size) != tenths(
        item.pack_size
    )
    if storefront.source is Source.onec and (name_changed or unit_changed):
        raise HTTPException(
            status_code=409,
            detail="у витрины на 1С название и единицу задаёт 1С — поправьте их там",
        )
    if name_changed:
        if not name:
            raise HTTPException(status_code=422, detail="назовите позицию")
        duplicate = (
            await session.execute(
                select(StorefrontItem.id).where(
                    StorefrontItem.storefront_id == storefront.id,
                    StorefrontItem.id != item.id,
                    func.lower(StorefrontItem.name) == name.lower(),
                )
            )
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="позиция с таким названием уже есть")
        item.name = name
    if unit_changed:
        if not unit:
            raise HTTPException(status_code=422, detail="укажите единицу: шт, кг, л")
        item.unit = unit
    if pack_changed:
        if tenths(payload.pack_size) < 1:
            raise HTTPException(status_code=422, detail="кратность не меньше 0,1")
        item.pack_size = to_decimal(payload.pack_size)
    # После кратности: минимум проверяется по той упаковке, что будет.
    if payload.min_qty is not None:
        item.min_qty = _min_qty(payload.min_qty, item.pack_size, item.unit)
    if payload.description is not None:
        item.description = plaintext.description(payload.description)
    if payload.hidden is not None:
        item.hidden = payload.hidden

    await session.commit()
    await live.stock_changed(session, storefront.id)
    return _item_row(item)


@router.delete("/owner/items/{item_id}", status_code=204, response_class=Response)
async def delete_item(
    item_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаление позиции — только пока её никто не заказывал.

    Нужно ровно для одного случая: в витрину заехал не тот прайс. Позицию
    с историей заказов удалять нельзя — вместе с ней исчезли бы строки
    чужих заявок, и прошлая заявка перестала бы сходиться по сумме.
    """
    item = await session.get(StorefrontItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    storefront = await session.get(Storefront, item.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="позиция не найдена")

    ordered = (
        await session.execute(
            select(func.count(OrderItem.id)).where(OrderItem.item_id == item.id)
        )
    ).scalar_one()
    if ordered:
        raise HTTPException(
            status_code=409,
            detail=f"позицию заказывали {ordered} раз — её нельзя удалить, "
                   f"скройте её из витрины",
        )

    await session.execute(delete(PriceChange).where(PriceChange.item_id == item.id))
    await session.execute(
        delete(OrderTemplateLine).where(OrderTemplateLine.item_id == item.id)
    )
    await session.delete(item)
    await session.commit()
    await live.stock_changed(session, storefront.id)
    return Response(status_code=204)


@router.get("/owner/items/{item_id}/price-history", response_model=list[PriceChangeOut])
async def price_history(
    item_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[PriceChangeOut]:
    item = await session.get(StorefrontItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    storefront = await session.get(Storefront, item.storefront_id)
    if not storefront or storefront.enterprise_id != identity.enterprise_id:
        raise HTTPException(status_code=404, detail="позиция не найдена")

    rows = (
        await session.execute(
            select(PriceChange)
            .where(PriceChange.item_id == item_id)
            .order_by(PriceChange.at.desc())
            .limit(30)
        )
    ).scalars()
    return [
        PriceChangeOut(
            id=row.id, old_price=float(row.old_price), new_price=float(row.new_price), at=row.at
        )
        for row in rows
    ]


# --- прайс-лист: выгрузка и загрузка ---

PRICE_HEADER = ("Артикул", "Наименование", "Единица", "Кратность", "Цена", "Остаток")

# Файл летит целиком в память, поэтому предел явный. Прайс на пять тысяч
# позиций весит меньше мегабайта даже в xlsx.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024


async def _owned_storefront(session: AsyncSession, storefront_id: int, enterprise_id: int) -> Storefront:
    storefront = await session.get(Storefront, storefront_id)
    if not storefront or storefront.enterprise_id != enterprise_id:
        raise HTTPException(status_code=404, detail="витрина не найдена")
    return storefront


@router.get("/owner/storefronts/{storefront_id}/price-list.csv")
async def price_list_csv(
    storefront_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Текущий прайс в том же формате, в каком принимается загрузка.

    Это и выгрузка, и шаблон: владелец скачивает, правит в Excel и грузит
    обратно — без отдельного «примера файла», который всегда расходится
    с тем, что ждёт разбор.
    """
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    items = (
        await session.execute(
            select(StorefrontItem)
            .where(StorefrontItem.storefront_id == storefront.id)
            .order_by(StorefrontItem.id)
        )
    ).scalars()

    body = spreadsheet.table(PRICE_HEADER, [
        [
            spreadsheet.text(item.external_id or ""),
            spreadsheet.text(item.name),
            spreadsheet.text(item.unit),
            f"{float(item.pack_size):g}".replace(".", ","),
            f"{float(item.price):.2f}".replace(".", ","),
            f"{float(item.stock):g}".replace(".", ","),
        ]
        for item in items
    ])
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="price-{storefront.id}.csv"'
        },
    )


@router.post("/owner/storefronts/{storefront_id}/price-import", response_model=ImportReportOut)
async def import_price_list(
    storefront_id: int,
    preview: bool = False,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ImportReportOut:
    """Загрузка прайса: обновляет цены и остатки, заводит новые позиции.

    `preview=1` показывает, что произойдёт, ничего не меняя: цену всей
    витрины страшно менять вслепую.
    """
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="файл больше 4 МБ")
    try:
        parsed = pricelist.parse(data, file.filename or "")
    except pricelist.PriceListError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = list(
        (
            await session.execute(
                select(StorefrontItem).where(StorefrontItem.storefront_id == storefront.id)
            )
        ).scalars()
    )
    by_external = {item.external_id: item for item in existing if item.external_id}
    by_name = {item.name.strip().lower(): item for item in existing}

    created = updated = unchanged = 0
    changes: list[str] = []

    for row in parsed.rows:
        item = by_external.get(row.external_id) if row.external_id else None
        if item is None:
            item = by_name.get(row.name.strip().lower())

        if item is None:
            created += 1
            changes.append(f"новая позиция «{row.name}» по {row.price:.2f} ₽")
            if not preview:
                item = StorefrontItem(
                    storefront_id=storefront.id,
                    external_id=row.external_id,
                    name=row.name,
                    unit=row.unit or "шт",
                    pack_size=to_decimal(row.pack_size or 1),
                    price=row.price,
                    stock=to_decimal(row.stock or 0),
                )
                session.add(item)
                by_name[row.name.strip().lower()] = item
                if row.external_id:
                    by_external[row.external_id] = item
            continue

        touched = False
        if float(item.price) != row.price:
            changes.append(f"«{item.name}»: {float(item.price):.2f} → {row.price:.2f} ₽")
            if not preview:
                # История цен копится и при импорте: иначе массовая
                # переоценка прошла бы мимо журнала.
                session.add(
                    PriceChange(
                        item_id=item.id,
                        old_price=item.price,
                        new_price=row.price,
                        changed_by=identity.max_user_id,
                    )
                )
                item.price = row.price
            touched = True
        if row.stock is not None and float(item.stock) != row.stock:
            if not preview:
                item.stock = to_decimal(row.stock)
            touched = True
        if row.pack_size and float(item.pack_size) != row.pack_size:
            if not preview:
                item.pack_size = to_decimal(row.pack_size)
            touched = True
        if row.unit and item.unit != row.unit:
            if not preview:
                item.unit = row.unit
            touched = True

        if touched:
            updated += 1
        else:
            unchanged += 1

    if not preview:
        session.add(
            ExchangeEvent(
                direction="in",
                object_kind="Прайс-лист",
                enterprise_id=identity.enterprise_id,
                status=ExchangeStatus.done,
                message=(
                    f"витрина «{storefront.name}»: загружен файл {file.filename}, "
                    f"новых {created}, обновлено {updated}, без изменений {unchanged}"
                ),
            )
        )
        await session.commit()
        await live.stock_changed(session, storefront.id)

    return ImportReportOut(
        preview=preview,
        rows=len(parsed.rows),
        created=created,
        updated=updated,
        unchanged=unchanged,
        changes=changes[:50],
        problems=parsed.problems[:50],
    )


@router.get("/owner/export/orders.csv")
async def export_orders(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Вся история предприятия одной таблицей.

    Продукт не заменяет учётную систему и не должен: владельцу время от
    времени нужно посчитать что-то своё, и выгрузка дешевле любого отчёта,
    который мы могли бы придумать за него.
    """
    orders = list(
        (
            await session.execute(
                (await _enterprise_orders(session, identity.enterprise_id))
                .order_by(Order.created_at)
            )
        ).scalars()
    )
    body = await exporting.orders_csv(session, orders)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


# --- своё предприятие и свои витрины ---


def _initials(name: str) -> str:
    """Две буквы для аватара витрины. Кавычки и служебные слова в аватаре
    читаются как мусор, поэтому берём начала значимых слов."""
    skip = {"и", "в", "на", "по", "оптом", "опт", "ооо", "ип", "тд"}
    words = [
        word.strip("«»\"'()-—,.")
        for word in name.split()
        if word.strip("«»\"'()-—,.").lower() not in skip
    ]
    letters = [word[0] for word in words if word and word[0].isalpha()]
    return "".join(letters[:2]).upper() or name[:2].upper()


def _is_color(value: str) -> bool:
    """#RRGGBB. Чужую строку нельзя пускать в style: это прямая дорога
    к подстановке произвольного CSS в чужой браузер."""
    return (
        len(value) == 7
        and value[0] == "#"
        and all(ch in "0123456789abcdefABCDEF" for ch in value[1:])
    )


def _parse_cutoff(value: str | None) -> time_type | None:
    if not value:
        return None
    try:
        hours, minutes = value.strip().split(":")
        return time_type(int(hours), int(minutes))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="время отсечки в формате ЧЧ:ММ") from exc


def _onec_url(value: str) -> str:
    try:
        url = onec.address.check(value)
    except onec.address.BadAddress as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Обрезанный адрес вёл бы уже не туда — отказ, а не молчаливая обрезка.
    if len(url) > 300:
        raise HTTPException(status_code=422, detail="адрес базы 1С длиннее 300 знаков")
    return url


async def _check_onec(session: AsyncSession, storefront: Storefront, enterprise_id: int) -> None:
    """Ключ и источник витрины согласованы до того, как по ним пойдёт обмен.

    Витрина «из 1С» без своего ключа берёт базу стенда из окружения — так
    работает демо. Чужому предприятию туда нельзя: его заказы с названиями
    магазинов ложились бы в общую тестовую базу, открытую в кабинете.
    """
    if storefront.onec_key and not onec.connection(storefront)[0]:
        raise HTTPException(
            status_code=422,
            detail="ключ базы 1С выглядит иначе — скопируйте его из кабинета базы целиком",
        )
    if storefront.source is Source.onec and not storefront.onec_key and not onec.own_base(storefront):
        enterprise = await session.get(Enterprise, enterprise_id)
        if enterprise is None or not enterprise.is_demo:
            raise HTTPException(
                status_code=422,
                detail="чтобы вести витрину из 1С, вставьте ключ тестовой базы или укажите свою",
            )


async def _settings_out(session: AsyncSession, storefront: Storefront) -> StorefrontSettingsOut:
    count = (
        await session.execute(
            select(func.count(StorefrontItem.id)).where(
                StorefrontItem.storefront_id == storefront.id
            )
        )
    ).scalar_one()
    accuracy = await metrics.by_storefront(session, [storefront.id])
    settings = onec.settings_of(storefront)
    return StorefrontSettingsOut(
        id=storefront.id,
        name=storefront.name,
        mode=storefront.mode.value,
        source=storefront.source.value,
        is_public=storefront.is_public,
        show_prices_public=storefront.show_prices_public,
        delivery_days=storefront.delivery_days,
        cutoff_at=storefront.cutoff_at.strftime("%H:%M") if storefront.cutoff_at else None,
        min_amount=float(storefront.min_amount) if storefront.min_amount is not None else None,
        remind_before_minutes=storefront.remind_before_minutes,
        shipping_accuracy=accuracy.get(storefront.id, metrics.Accuracy()).percent,
        logo_url=f"/api/photos/{storefront.logo_key}" if storefront.logo_key else None,
        cover_url=f"/api/photos/{storefront.cover_key}" if storefront.cover_key else None,
        color=storefront.color,
        about=storefront.about,
        onec_base=onec.connection(storefront)[0].rsplit("/", 1)[-1] if storefront.onec_key else "",
        onec_mode=(
            "own" if onec.own_base(storefront)
            else "key" if storefront.onec_key
            else "stand" if storefront.source is Source.onec
            else ""
        ),
        onec_url=storefront.onec_url if onec.own_base(storefront) else "",
        onec_user=storefront.onec_user,
        onec_has_password=bool(storefront.onec_password),
        onec_preset=settings.preset,
        onec_refs={
            key: {"key": getattr(settings, key), "name": settings.names.get(key, "")}
            for key in onec.onec_settings.REFS
            if getattr(settings, key)
        },
        onec_missing=settings.missing() if storefront.source is Source.onec else [],
        onec_reserve_now=bool(storefront.onec_reserve_now),
        items=int(count),
    )


@router.get("/owner/enterprise", response_model=EnterpriseOut)
async def get_enterprise(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> EnterpriseOut:
    enterprise = await session.get(Enterprise, identity.enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="предприятие не найдено")
    count = (
        await session.execute(
            select(func.count(Storefront.id)).where(Storefront.enterprise_id == enterprise.id)
        )
    ).scalar_one()
    kind, reach = contact.effective(
        enterprise.contact_kind, enterprise.contact_phone, enterprise.contact_max
    )
    percent, missing = await _profile(session, enterprise)
    return EnterpriseOut(
        id=enterprise.id, name=enterprise.name, city=enterprise.city,
        contact_kind=kind or enterprise.contact_kind, contact=reach,
        contact_phone=enterprise.contact_phone, contact_max=enterprise.contact_max,
        max_chat=enterprise.max_chat,
        is_demo=enterprise.is_demo, storefronts=int(count),
        profile_percent=percent, profile_missing=missing,
    )


@router.patch("/owner/enterprise", response_model=EnterpriseOut)
async def update_enterprise(
    payload: EnterpriseIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> EnterpriseOut:
    enterprise = await session.get(Enterprise, identity.enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="предприятие не найдено")
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=422, detail="название не может быть пустым")
        enterprise.name = payload.name.strip()[:200]
    if payload.city is not None:
        # Город — не украшение: по нему витрина попадает на полку своего города.
        try:
            enterprise.city = one_city(payload.city)
        except CityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Проверяем здесь, а не у клиента: кнопка «Связаться» с битой ссылкой
    # хуже, чем её честное отсутствие.
    kind = payload.contact_kind if payload.contact_kind is not None else enterprise.contact_kind
    if kind not in ("", *contact.KINDS):
        raise HTTPException(status_code=422, detail="способ связи — max или phone")
    phone = payload.contact_phone
    link = payload.contact_max
    if payload.contact is not None:
        # Прежний вызов: одно значение для выбранного способа.
        if kind == "phone":
            phone = payload.contact
        else:
            link = payload.contact
    try:
        if phone is not None:
            enterprise.contact_phone = contact.normalize_phone(phone)
        if link is not None:
            enterprise.contact_max = contact.normalize_max(link)
    except contact.ContactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.max_chat is not None:
        # Ссылку на профиль больше не вписывают: «Написать в MAX» присылает
        # клиенту карточку владельца. Поставщик решает только, можно ли.
        enterprise.max_chat = payload.max_chat
        if payload.contact_kind is None:
            kind = "phone" if enterprise.contact_phone else ("max" if payload.max_chat else "")
    enterprise.contact_kind = kind
    await session.commit()
    return await get_enterprise(identity, session)


@router.post("/owner/storefronts", response_model=StorefrontSettingsOut, status_code=201)
async def create_storefront(
    payload: StorefrontCreateIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    name = payload.name.strip()[:200]
    if not name:
        raise HTTPException(status_code=422, detail="назовите витрину")
    try:
        mode = Mode(payload.mode)
        source = Source(payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="режим витрины — stock или preorder") from exc

    key = payload.onec_key.strip()[:200]
    if key:
        # Ключ указан — значит витрина ведётся из 1С. Отдельно выбирать
        # источник не нужно: это одно и то же решение, а два переключателя
        # на одно решение неизбежно разойдутся.
        source = Source.onec
    cutoff = _parse_cutoff(payload.cutoff_at)
    if mode is Mode.preorder and cutoff is None:
        # Витрина «под заказ» без отсечки не работает: непонятно, на какую
        # дату уедет заявка и когда закрывается приём.
        raise HTTPException(status_code=422, detail="для витрины «под заказ» нужна отсечка")

    storefront = Storefront(
        enterprise_id=identity.enterprise_id,
        name=name,
        initials=_initials(name),
        mode=mode,
        source=source,
        delivery_days=payload.delivery_days.strip()[:40],
        cutoff_at=cutoff,
        min_amount=payload.min_amount or None,
        onec_key=key,
        onec_url=_onec_url(payload.onec_url),
        stock_synced_at=onec.stock_synced_now() if source is Source.onec else None,
        # Открытая витрина видна на полке города, и клиент сам просит
        # подключения; закрытая — только по приглашению владельца.
        is_public=payload.is_public,
    )
    await _check_onec(session, storefront, identity.enterprise_id)
    session.add(storefront)
    await session.commit()
    await session.refresh(storefront)

    # Наполняем сразу: витрина, созданная с ключом и оставшаяся пустой,
    # выглядит как сломанная интеграция.
    if key:
        try:
            await stock.pull(session, storefront, identity.max_user_id)
            await session.commit()
        except onec.OneCUnavailable as exc:
            session.add(
                ExchangeEvent(
                    direction="in",
                    object_kind="Номенклатура, цены, остатки",
                    enterprise_id=identity.enterprise_id,
                    status=ExchangeStatus.failed,
                    message=f"витрина «{storefront.name}» создана, но обмен не удался: {exc}",
                )
            )
            await session.commit()

    return await _settings_out(session, storefront)


@router.delete("/owner/storefronts/{storefront_id}", status_code=204, response_class=Response)
async def delete_storefront(
    storefront_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаление витрины — только пока по ней не было заявок.

    Нужно ровно для одного случая: витрину завели не с тем ключом или
    не с тем режимом. Витрину с историей удалять нельзя: вместе с ней
    исчезли бы чужие заявки.
    """
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)

    orders = (
        await session.execute(
            select(func.count(Order.id)).where(Order.storefront_id == storefront.id)
        )
    ).scalar_one()
    if orders:
        raise HTTPException(
            status_code=409,
            detail=f"по витрине было заявок: {orders}. Её можно скрыть от магазинов города, но не удалить",
        )

    items = list(
        (
            await session.execute(
                select(StorefrontItem.id).where(StorefrontItem.storefront_id == storefront.id)
            )
        ).scalars()
    )
    if items:
        await session.execute(delete(PriceChange).where(PriceChange.item_id.in_(items)))
        await session.execute(
            delete(OrderTemplateLine).where(OrderTemplateLine.item_id.in_(items))
        )
    await session.execute(delete(Promo).where(Promo.storefront_id == storefront.id))
    await session.execute(delete(StorefrontItem).where(StorefrontItem.storefront_id == storefront.id))
    await session.execute(delete(Connection).where(Connection.storefront_id == storefront.id))
    await session.execute(delete(Reminder).where(Reminder.storefront_id == storefront.id))
    await session.execute(
        update(Notification)
        .where(Notification.storefront_id == storefront.id)
        .values(storefront_id=None)
    )
    await session.delete(storefront)
    await session.commit()
    return Response(status_code=204)


@router.post("/owner/storefronts/{storefront_id}/items", response_model=ItemRowOut, status_code=201)
async def create_item(
    storefront_id: int,
    payload: ItemCreateIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ItemRowOut:
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)

    name = payload.name.strip()[:300]
    if not name:
        raise HTTPException(status_code=422, detail="назовите позицию")
    if payload.price <= 0:
        raise HTTPException(status_code=422, detail="цена должна быть больше нуля")
    if tenths(payload.pack_size) < 1:
        raise HTTPException(status_code=422, detail="кратность не меньше 0,1")
    unit = payload.unit.strip()[:20] or "шт"
    min_qty = _min_qty(payload.min_qty, payload.pack_size, unit)

    duplicate = (
        await session.execute(
            select(StorefrontItem).where(
                StorefrontItem.storefront_id == storefront.id,
                func.lower(StorefrontItem.name) == name.lower(),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="позиция с таким названием уже есть")

    item = StorefrontItem(
        storefront_id=storefront.id,
        external_id=payload.external_id.strip()[:80],
        name=name,
        unit=unit,
        pack_size=to_decimal(payload.pack_size),
        price=payload.price,
        stock=to_decimal(max(0.0, payload.stock)),
        daily_limit=to_decimal(payload.daily_limit) if payload.daily_limit else None,
        min_qty=min_qty,
        description=plaintext.description(payload.description),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await live.stock_changed(session, item.storefront_id)
    return _item_row(item)


# --- аудитория бота и приглашение клиентов ---


@router.get("/owner/audience", response_model=list[AudienceRowOut])
async def audience(
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[AudienceRowOut]:
    """Все, кто запускал бота, кроме поставщиков.

    Это и есть список, из которого поставщик набирает клиентов: пригласить
    можно только того, с кем у бота есть диалог, иначе приглашение некуда
    доставить. Владельцев и менеджеров — и своих, и чужих — здесь нет:
    магазином аккаунт поставщика не становится.
    """
    suppliers = select(Employee.max_user_id)
    people = list(
        (
            await session.execute(
                select(BotUser)
                .where(BotUser.max_user_id.not_in(suppliers))
                .order_by(BotUser.last_seen_at.desc().nullslast(), BotUser.id.desc())
            )
        ).scalars()
    )
    if not people:
        return []

    ids = [person.max_user_id for person in people]
    clients = {
        client.max_user_id: client
        for client in (
            await session.execute(select(Client).where(Client.max_user_id.in_(ids)))
        ).scalars()
    }
    # К каким моим витринам этот человек уже подключён
    rows = await session.execute(
        select(Client.max_user_id, Storefront.name)
        .join(Connection, Connection.client_id == Client.id)
        .join(Storefront, Storefront.id == Connection.storefront_id)
        .where(
            Storefront.enterprise_id == identity.enterprise_id,
            Connection.status == "active",
            Client.max_user_id.in_(ids),
        )
    )
    connected: dict[int, list[str]] = {}
    for user_id, storefront_name in rows:
        connected.setdefault(user_id, []).append(storefront_name)

    # Позвали, но человек ещё не ответил: приглашение ждёт в чате с ботом.
    names = {
        storefront.id: storefront.name
        for storefront in (
            await session.execute(
                select(Storefront).where(Storefront.enterprise_id == identity.enterprise_id)
            )
        ).scalars()
    }
    waiting: dict[int, list[str]] = {}
    for invite in (
        await session.execute(
            select(Invite).where(
                Invite.enterprise_id == identity.enterprise_id,
                Invite.kind == "client",
                Invite.for_user.in_(ids),
                Invite.used_by.is_(None),
            )
        )
    ).scalars():
        label = names.get(invite.storefront_id, "") if invite.storefront_id else "все витрины"
        if label and label not in connected.get(invite.for_user, []):
            waiting.setdefault(invite.for_user, [])
            if label not in waiting[invite.for_user]:
                waiting[invite.for_user].append(label)

    return [
        AudienceRowOut(
            max_user_id=person.max_user_id,
            name=clients[person.max_user_id].name if person.max_user_id in clients else person.title,
            username=person.username,
            started_at=person.started_at,
            last_seen_at=person.last_seen_at,
            has_dialog=person.max_chat_id is not None,
            is_client=person.max_user_id in clients,
            storefronts=sorted(connected.get(person.max_user_id, [])),
            invited=sorted(waiting.get(person.max_user_id, [])),
        )
        for person in people
    ]


@router.post("/owner/audience/invite", response_model=AudienceRowOut)
async def invite_from_audience(
    payload: AudienceInviteIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> AudienceRowOut:
    """Зовёт человека из аудитории бота к витрине — но не подключает.

    Раньше нажатие «Пригласить» сразу открывало доступ: человек оказывался
    клиентом, ещё ничего не ответив. Теперь бот присылает ему приглашение с
    кнопкой «Принять приглашение», а подключение случается, только когда он
    сам её нажмёт. Приглашение личное: принять его может только он. Если
    MAX не доставил сообщение, приглашение ждёт человека в приложении.
    """
    person = (
        await session.execute(
            select(BotUser).where(BotUser.max_user_id == payload.max_user_id)
        )
    ).scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="этого человека нет среди пришедших")
    # Список мог устареть: человек успел завести своё предприятие.
    if await invites.supplier_of(session, person.max_user_id):
        raise HTTPException(status_code=409, detail="это аккаунт поставщика — магазином его не пригласить")

    targets = list(
        (
            await session.execute(
                select(Storefront).where(
                    Storefront.enterprise_id == identity.enterprise_id,
                    *([Storefront.id == payload.storefront_id] if payload.storefront_id else []),
                )
            )
        ).scalars()
    )
    if not targets:
        raise HTTPException(status_code=404, detail="витрина не найдена")

    client = (
        await session.execute(select(Client).where(Client.max_user_id == person.max_user_id))
    ).scalar_one_or_none()
    connected: set[int] = set()
    if client is not None:
        connected = set(
            (
                await session.execute(
                    select(Connection.storefront_id).where(
                        Connection.client_id == client.id,
                        Connection.status == "active",
                    )
                )
            ).scalars()
        )
    if all(storefront.id in connected for storefront in targets):
        raise HTTPException(status_code=409, detail="уже подключён к этой витрине")

    # Уже звали и он не ответил — не плодим второе приглашение, а
    # напоминаем тем же: кнопка в старом сообщении продолжает работать.
    invite = (
        await session.execute(
            select(Invite).where(
                Invite.for_user == person.max_user_id,
                Invite.enterprise_id == identity.enterprise_id,
                Invite.kind == "client",
                Invite.used_by.is_(None),
                Invite.storefront_id.is_(None)
                if payload.storefront_id is None
                else Invite.storefront_id == payload.storefront_id,
            )
        )
    ).scalars().first()
    # Каждое сообщение бота — в счёт дневного лимита, и повторное тоже:
    # иначе одного человека можно было бы засыпать приглашениями.
    try:
        await invites.count_send(session, identity.max_user_id, person.max_user_id)
    except invites.DailyLimit as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if invite is None:
        invite = Invite(
            code=f"inv_{secrets.token_urlsafe(6)}",
            kind="client",
            enterprise_id=identity.enterprise_id,
            storefront_id=payload.storefront_id,
            created_by=identity.max_user_id,
            for_user=person.max_user_id,
        )
        session.add(invite)
    await session.commit()

    card = await invites.card(session, invite, person.max_user_id)
    delivered = await send(
        person.max_user_id, card.text, chat_id=person.max_chat_id, button=card.button
    )
    # Открытое приложение приглашённого показывает приглашение сразу — и
    # тогда, когда в чат с ботом его доставить не вышло.
    await live.publish([person.max_user_id], "invites")

    rows = await audience(identity, session)
    row = next(row for row in rows if row.max_user_id == person.max_user_id)
    return row.model_copy(update={"delivered": delivered})


# --- акции ---


def _promo_out(promo: Promo, item_name: str, today: date_type) -> PromoOut:
    return PromoOut(
        id=promo.id,
        kind=promo.kind.value,
        title=promo.title,
        description=promo.description,
        discount_percent=float(promo.discount_percent),
        item_id=promo.item_id,
        item_name=item_name,
        min_amount=None if promo.min_amount is None else float(promo.min_amount),
        min_qty=None if promo.min_qty is None else float(promo.min_qty),
        starts_on=promo.starts_on,
        ends_on=promo.ends_on,
        is_active=promo.is_active,
        is_live=promos.is_live(promo, today),
        condition=promos.condition(promo, item_name),
    )


async def _promo_names(session: AsyncSession, rows: list[Promo]) -> dict[int, str]:
    ids = {promo.item_id for promo in rows if promo.item_id}
    if not ids:
        return {}
    return {
        item.id: item.name
        for item in (
            await session.execute(select(StorefrontItem).where(StorefrontItem.id.in_(ids)))
        ).scalars()
    }


@router.get("/owner/storefronts/{storefront_id}/promos", response_model=list[PromoOut])
async def list_promos(
    storefront_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[PromoOut]:
    await _owned_storefront(session, storefront_id, identity.enterprise_id)
    rows = list(
        (
            await session.execute(
                select(Promo).where(Promo.storefront_id == storefront_id).order_by(Promo.id.desc())
            )
        ).scalars()
    )
    names = await _promo_names(session, rows)
    today = datetime.now(TZ).date()
    return [_promo_out(promo, names.get(promo.item_id or 0, ""), today) for promo in rows]


async def _validate_promo(
    session: AsyncSession, storefront_id: int, payload: PromoIn
) -> tuple[str, float, PromoKind]:
    title = payload.title.strip()[:120]
    if not title:
        raise HTTPException(status_code=422, detail="у акции должно быть название")
    try:
        kind = PromoKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="неизвестный тип акции") from exc

    percent = round(float(payload.discount_percent or 0), 1)
    if not 0 < percent < 100:
        # Скидка в ноль процентов — это не акция, а сто — раздача товара.
        raise HTTPException(status_code=422, detail="скидка от 0,1 до 99,9 %")
    if payload.starts_on and payload.ends_on and payload.ends_on < payload.starts_on:
        raise HTTPException(status_code=422, detail="акция заканчивается раньше, чем начинается")

    # «От количества» без позиции — «на любую позицию» (app/promos.py),
    # а скидка «на позицию» без позиции ничего бы не значила.
    if kind is PromoKind.item and payload.item_id is None:
        raise HTTPException(status_code=422, detail="для этого типа акции нужна позиция")
    if payload.item_id is not None:
        item = await session.get(StorefrontItem, payload.item_id)
        if not item or item.storefront_id != storefront_id:
            raise HTTPException(status_code=404, detail="позиции нет в этой витрине")

    if kind is PromoKind.volume_amount and not payload.min_amount:
        raise HTTPException(status_code=422, detail="укажите сумму, от которой действует скидка")
    if kind is PromoKind.volume_qty and not payload.min_qty:
        raise HTTPException(
            status_code=422, detail="укажите количество, от которого действует скидка"
        )
    return title, percent, kind


@router.post("/owner/storefronts/{storefront_id}/promos", response_model=PromoOut, status_code=201)
async def create_promo(
    storefront_id: int,
    payload: PromoIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> PromoOut:
    await _owned_storefront(session, storefront_id, identity.enterprise_id)
    title, percent, kind = await _validate_promo(session, storefront_id, payload)

    promo = Promo(
        storefront_id=storefront_id,
        item_id=payload.item_id if kind in (PromoKind.item, PromoKind.volume_qty) else None,
        kind=kind,
        title=title,
        description=payload.description.strip()[:2000],
        discount_percent=percent,
        min_amount=payload.min_amount,
        min_qty=to_decimal(payload.min_qty) if payload.min_qty else None,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        is_active=payload.is_active,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    names = await _promo_names(session, [promo])
    return _promo_out(promo, names.get(promo.item_id or 0, ""), datetime.now(TZ).date())


@router.patch("/owner/promos/{promo_id}", response_model=PromoOut)
async def update_promo(
    promo_id: int,
    payload: PromoIn,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> PromoOut:
    promo = await session.get(Promo, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="акция не найдена")
    await _owned_storefront(session, promo.storefront_id, identity.enterprise_id)
    title, percent, kind = await _validate_promo(session, promo.storefront_id, payload)

    promo.title = title
    promo.kind = kind
    promo.description = payload.description.strip()[:2000]
    promo.discount_percent = percent
    promo.item_id = payload.item_id if kind in (PromoKind.item, PromoKind.volume_qty) else None
    promo.min_amount = payload.min_amount
    promo.min_qty = to_decimal(payload.min_qty) if payload.min_qty else None
    promo.starts_on = payload.starts_on
    promo.ends_on = payload.ends_on
    promo.is_active = payload.is_active
    await session.commit()

    names = await _promo_names(session, [promo])
    return _promo_out(promo, names.get(promo.item_id or 0, ""), datetime.now(TZ).date())


@router.delete("/owner/promos/{promo_id}", status_code=204, response_class=Response)
async def delete_promo(
    promo_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    promo = await session.get(Promo, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="акция не найдена")
    await _owned_storefront(session, promo.storefront_id, identity.enterprise_id)
    await session.delete(promo)
    await session.commit()
    return Response(status_code=204)


# --- фотография позиции ---


@router.post("/owner/items/{item_id}/photo", response_model=ItemRowOut)
async def upload_item_photo(
    item_id: int,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ItemRowOut:
    """Снимок товара. Заменяет предыдущий: витрине нужна одна карточка,
    а не галерея."""
    item = await session.get(StorefrontItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    await _owned_storefront(session, item.storefront_id, identity.enterprise_id)

    data = await file.read(storage.MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="пустой файл")
    if len(data) > storage.MAX_BYTES:
        raise HTTPException(
            status_code=413, detail=f"снимок больше {storage.MAX_BYTES // (1024 * 1024)} МБ"
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in storage.ALLOWED:
        raise HTTPException(status_code=422, detail="поддерживаются только изображения")

    item.photo_key = storage.put(data, content_type, prefix="items")
    await session.commit()
    return _item_row(item)


@router.delete("/owner/items/{item_id}/photo", response_model=ItemRowOut)
async def drop_item_photo(
    item_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ItemRowOut:
    item = await session.get(StorefrontItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    await _owned_storefront(session, item.storefront_id, identity.enterprise_id)
    item.photo_key = None
    await session.commit()
    return _item_row(item)


@router.post("/owner/storefronts/{storefront_id}/logo", response_model=StorefrontSettingsOut)
async def upload_logo(
    storefront_id: int,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    """Логотип витрины. Заменяет предыдущий: на полке места под один."""
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    storefront.logo_key = await _store_image(file, "logos")
    await session.commit()
    return await _settings_out(session, storefront)


async def _store_image(file: UploadFile, prefix: str) -> str:
    """Картинка витрины в хранилище: размер и тип проверяем до записи."""
    data = await file.read(storage.MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="пустой файл")
    if len(data) > storage.MAX_BYTES:
        raise HTTPException(
            status_code=413, detail=f"файл больше {storage.MAX_BYTES // (1024 * 1024)} МБ"
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in storage.ALLOWED:
        raise HTTPException(status_code=422, detail="поддерживаются только изображения")
    return storage.put(data, content_type, prefix=prefix)


@router.post("/owner/storefronts/{storefront_id}/cover", response_model=StorefrontSettingsOut)
async def upload_cover(
    storefront_id: int,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    """Фото витрины — большая картинка в карточке и в шапке каталога."""
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    storefront.cover_key = await _store_image(file, "covers")
    await session.commit()
    return await _settings_out(session, storefront)


@router.delete("/owner/storefronts/{storefront_id}/cover", response_model=StorefrontSettingsOut)
async def drop_cover(
    storefront_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    storefront.cover_key = None
    await session.commit()
    return await _settings_out(session, storefront)


@router.delete("/owner/storefronts/{storefront_id}/logo", response_model=StorefrontSettingsOut)
async def drop_logo(
    storefront_id: int,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StorefrontSettingsOut:
    storefront = await _owned_storefront(session, storefront_id, identity.enterprise_id)
    storefront.logo_key = None
    await session.commit()
    return await _settings_out(session, storefront)
