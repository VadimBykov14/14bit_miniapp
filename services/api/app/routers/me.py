from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import contact, shop, team
from ..audience import remember_visitor
from ..auth import Identity, current_identity
from ..db import get_session
from ..models import (
    BotUser, Client, ClientWorker, Connection, Employee, Notification, Order, OrderStatus, Role,
    Storefront,
)
from ..schedule import WEEKDAYS
from ..schemas import BadgesOut, MeOut, MembershipOut, ProfileIn, ScheduleIn, ScheduleOut
from ..seed import DEMO_USER_ID
from .cities import CityError, one_city
from .notifications import unread_count

router = APIRouter()

# Пределы совпадают с полями формы: сервер не должен молча отрезать то,
# что форма разрешила ввести.
NAME_LIMIT = 60
ADDRESS_LIMIT = 120


def _title(role: str, enterprise: str, client: str) -> str:
    if role in ("client", "worker"):
        return client
    return enterprise


async def _employee(session: AsyncSession, identity: Identity) -> Employee | ClientWorker | None:
    """Чей график правит человек: сотрудника поставщика или работника
    магазина. У владельца точки графика нет — он и есть магазин."""
    if identity.role is Role.worker and identity.client_id:
        return await shop.worker_of(session, identity.client_id, identity.max_user_id)
    if identity.role not in (Role.manager, Role.owner) or not identity.enterprise_id:
        return None
    return await team.employee_of(session, identity.enterprise_id, identity.max_user_id)


def _schedule(employee: Employee | ClientWorker | None) -> ScheduleOut | None:
    if employee is None:
        return None
    return ScheduleOut(
        days=[day for day in WEEKDAYS if day in team.parse_days_names(employee.work_days)],
        start=team.clock(employee.work_from),
        end=team.clock(employee.work_to),
        text=team.hours_text(employee),
        on_shift=team.on_shift(employee),
    )


async def _person(session: AsyncSession, max_user_id: int) -> BotUser | None:
    return (
        await session.execute(select(BotUser).where(BotUser.max_user_id == max_user_id))
    ).scalar_one_or_none()


@router.get("/me", response_model=MeOut)
async def me(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    # Открытие приложения — это тоже «пришёл человек»: поставщик должен
    # видеть его в списке приглашаемых, даже если боту тот ничего не писал.
    await remember_visitor(
        session, identity.max_user_id, identity.first_name, identity.last_name, identity.username
    )

    person = await _person(session, identity.max_user_id)
    client = await session.get(Client, identity.client_id) if identity.client_id else None
    # Название точки читаем заново: после правки в «Аккаунте» identity
    # ещё помнит старое.
    client_name = client.name if client else identity.client_name
    has_storefronts = bool(
        identity.buyer
        and identity.client_id
        and await session.scalar(
            select(func.count())
            .select_from(Connection)
            .where(Connection.client_id == identity.client_id, Connection.status == "active")
        )
    )

    return MeOut(
        user_id=identity.max_user_id,
        first_name=person.first_name if person and person.name_edited else identity.first_name,
        last_name=person.last_name if person and person.name_edited else identity.last_name,
        role=identity.role.value if identity.role else None,
        needs_onboarding=not identity.memberships,
        start_param=identity.start_param,
        unread=await unread_count(session, identity.max_user_id),
        phone=person.phone if person else "",
        address=client.address if client else "",
        city=client.city if client else "",
        schedule=_schedule(await _employee(session, identity)),
        max_reachable=person.max_reachable if person else True,
        has_storefronts=has_storefronts,
        # Точки демо-аккаунта — демо: их же стирает и заводит заново reset_demo.
        demo_shop=bool(identity.buyer and client and client.max_user_id == DEMO_USER_ID),
        # Название — активной роли: у владельца пекарни, который ещё и
        # менеджер базы, в «Аккаунте» владельца должна стоять пекарня.
        title=client_name if identity.buyer else next(
            (
                m.enterprise_name
                for m in identity.memberships
                if m.enterprise_id and m.enterprise_id == identity.enterprise_id
            ),
            next((m.enterprise_name for m in identity.memberships if m.enterprise_id), ""),
        ),
        memberships=[
            MembershipOut(
                role=m.role.value,
                title=_title(
                    m.role.value,
                    m.enterprise_name,
                    client_name if m.client_id == identity.client_id else m.client_name,
                ),
            )
            for m in identity.memberships
        ],
    )


@router.patch("/me", response_model=MeOut)
async def update_me(
    payload: ProfileIn,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    """Личные данные и адрес доставки.

    Имя и телефон — человека: одни на все его роли. Название точки и адрес —
    клиента: у владельца пекарни, который закупается у кондитерской базы,
    адрес магазина свой, а предприятие настраивается в другом экране.
    """
    await remember_visitor(
        session, identity.max_user_id, identity.first_name, identity.last_name, identity.username
    )
    person = await _person(session, identity.max_user_id)
    if person is None:
        raise HTTPException(status_code=404, detail="профиль не найден")

    if payload.first_name is not None:
        first = payload.first_name.strip()
        if not first:
            raise HTTPException(status_code=422, detail="имя не может быть пустым")
        person.first_name = first[:NAME_LIMIT]
        person.name_edited = True
    if payload.last_name is not None:
        person.last_name = payload.last_name.strip()[:NAME_LIMIT]
        person.name_edited = True
    if payload.phone is not None:
        try:
            person.phone = contact.normalize_phone(payload.phone)
        except contact.ContactError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.max_reachable is not None:
        person.max_reachable = payload.max_reachable

    if payload.client_name is not None or payload.address is not None or payload.city is not None:
        if identity.role is Role.worker:
            raise HTTPException(
                status_code=403, detail="название, адрес и город магазина меняет его владелец"
            )
        if identity.role is not Role.client or identity.client_id is None:
            raise HTTPException(
                status_code=403, detail="название точки и адрес есть только у клиента"
            )
        client = await session.get(Client, identity.client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="точка не найдена")
        if payload.client_name is not None:
            name = payload.client_name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="название точки не может быть пустым")
            client.name = name[:NAME_LIMIT]
        if payload.address is not None:
            client.address = payload.address.strip()[:ADDRESS_LIMIT]
        if payload.city is not None:
            # Тот же справочник, что у поставщика: иначе «Кинешма» магазина
            # и «Кинешма » поставщика разошлись бы, и полка оказалась бы пустой.
            try:
                client.city = one_city(payload.city)
            except CityError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return await me(identity, session)


@router.put("/me/schedule", response_model=ScheduleOut)
async def update_schedule(
    payload: ScheduleIn,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> ScheduleOut:
    """График сотрудника или работника магазина. По нему другая сторона
    видит, кто сейчас на связи, а кто ответит завтра с утра."""
    employee = await _employee(session, identity)
    if employee is None:
        raise HTTPException(status_code=404, detail="график есть у сотрудников и работников")
    try:
        days, start, end = team.normalize_schedule(payload.days, payload.start, payload.end)
    except team.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    employee.work_days, employee.work_from, employee.work_to = days, start, end
    await session.commit()
    return _schedule(employee)


@router.get("/me/badges", response_model=BadgesOut)
async def badges(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> BadgesOut:
    """Счётчики на вкладках.

    Отдельно от /me, потому что их опрашивают раз в несколько секунд: /me
    записывает визит и собирает роли, а здесь два count по индексам.
    """
    orders = connections = 0
    if identity.buyer:
        orders = (
            await session.execute(
                select(func.count(Order.id)).where(
                    Order.client_id == identity.client_id,
                    Order.status == OrderStatus.shipped,
                )
            )
        ).scalar_one()
    elif identity.role in (Role.manager, Role.owner) and identity.enterprise_id:
        orders = (
            await session.execute(
                select(func.count(Order.id))
                .join(Storefront, Storefront.id == Order.storefront_id)
                .where(
                    Storefront.enterprise_id == identity.enterprise_id,
                    Order.status == OrderStatus.sent,
                )
            )
        ).scalar_one()
    if identity.role is Role.owner and identity.enterprise_id:
        # Подключение решает только владелец — менеджеру значок ни к чему.
        connections = (
            await session.execute(
                select(func.count(Connection.id))
                .join(Storefront, Storefront.id == Connection.storefront_id)
                .where(
                    Storefront.enterprise_id == identity.enterprise_id,
                    Connection.status == "request",
                )
            )
        ).scalar_one()

    last = (
        await session.execute(
            select(func.max(Notification.id)).where(
                Notification.max_user_id == identity.max_user_id
            )
        )
    ).scalar_one()
    return BadgesOut(
        unread=await unread_count(session, identity.max_user_id),
        orders=int(orders),
        connections=int(connections),
        last_notification=int(last or 0),
    )
