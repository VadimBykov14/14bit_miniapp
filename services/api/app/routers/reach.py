"""«Написать» — чат с человеком в MAX.

Ссылку на личный чат по номеру пользователя MAX не построить: адрес вида
max.ru/u/… выдаёт сам мессенджер, и из id он не вычисляется. Прямая ссылка
есть только у того, кто завёл публичный ник. Поэтому «Написать» работает
так: бот присылает в чат с ним карточку контакта, а нажатие на неё
открывает профиль человека с кнопкой «Написать». Два касания вместо
«спросите номер у коллеги».

Карточку можно получить только на того, с кем есть рабочая связь: клиент —
на сотрудника своего поставщика, сотрудник — на клиента своего
предприятия. Иначе ручка превратилась бы в справочник всех пользователей.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import botinfo, contact, team
from ..audience import known_chat
from ..auth import Identity, current_identity
from ..db import get_session
from ..models import BotUser, Client, ClientWorker, Connection, Employee, Role, Storefront
from ..notify import send_contact
from ..schemas import ReachIn, ReachOut
from ..seed import DEMO_USER_ID

router = APIRouter()

# Двойное нажатие не должно присылать две одинаковые карточки подряд.
REPEAT_SECONDS = 20
_recent: dict[tuple[int, int], float] = {}


async def _connected(
    session: AsyncSession, client_id: int, enterprise_id: int, active_only: bool = False
) -> bool:
    """Клиент подключён к витрине этого предприятия или просится в неё.

    `active_only` — только одобренное подключение. Карточка сотрудника
    несёт его телефон: раньше её получал и тот, кто лишь попросился в
    витрину, и заблокированный клиент, а номера сотрудников идут подряд.
    В обратную сторону поставщик пишет и тому, кто просится: ему нужно
    понять, кого он подключает.
    """
    return (
        await session.execute(
            select(Connection.id)
            .join(Storefront, Storefront.id == Connection.storefront_id)
            .where(
                Connection.client_id == client_id,
                Storefront.enterprise_id == enterprise_id,
                *([Connection.status == "active"] if active_only else []),
            )
            .limit(1)
        )
    ).first() is not None


async def _target(session: AsyncSession, identity: Identity, payload: ReachIn) -> tuple[int, str]:
    """(user_id, подпись) того, кому пишем, после проверки права."""
    if payload.employee_id:
        employee = await session.get(Employee, payload.employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        allowed = (
            identity.buyer
            and await _connected(
                session, identity.client_id, employee.enterprise_id, active_only=True
            )
        ) or (
            identity.role in (Role.manager, Role.owner)
            and identity.enterprise_id == employee.enterprise_id
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        person = (await team.people(session, {employee.max_user_id})).get(employee.max_user_id)
        return employee.max_user_id, team.display_name(employee, person)

    if payload.client_id:
        client = await session.get(Client, payload.client_id)
        allowed = (
            client is not None
            and identity.role in (Role.manager, Role.owner)
            and identity.enterprise_id is not None
            and await _connected(session, client.id, identity.enterprise_id)
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="клиент не найден")
        person = (await team.people(session, {client.max_user_id})).get(client.max_user_id)
        who = person.title if person and (person.first_name or person.last_name) else ""
        return client.max_user_id, " · ".join(filter(None, [who, client.name]))

    if payload.worker_id:
        # Работник магазина: ему звонят и пишут по заявке, которую он оформил.
        worker = await session.get(ClientWorker, payload.worker_id)
        allowed = (
            worker is not None
            and identity.staff
            and identity.enterprise_id is not None
            and await _connected(session, worker.client_id, identity.enterprise_id)
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="работник не найден")
        client = await session.get(Client, worker.client_id)
        person = (await team.people(session, {worker.max_user_id})).get(worker.max_user_id)
        who = person.title if person and (person.first_name or person.last_name) else worker.name
        return worker.max_user_id, " · ".join(filter(None, [who, client.name if client else ""]))

    raise HTTPException(status_code=422, detail="кому писать — сотрудник или клиент")


@router.post("/reach", response_model=ReachOut)
async def reach(
    payload: ReachIn,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> ReachOut:
    user_id, name = await _target(session, identity, payload)
    text = f"{name} — нажмите на карточку, чтобы открыть профиль и написать."
    share_phone = True
    if user_id < 0:
        # Тестового бота стенда (app/testbots.py) в MAX нет. Кнопка связи с
        # ним ведёт на аккаунт демо-стенда — к человеку из команды, которому
        # проверяющий может задать вопрос. Его телефон в карточку не кладём.
        user_id = DEMO_USER_ID
        human = (await team.people(session, {user_id})).get(user_id)
        who = human.title if human and (human.first_name or human.last_name) else "команда проекта"
        text = f"За тестового бота «{name}» отвечает {who} — нажмите на карточку, чтобы написать."
        name, share_phone = who, False
    if user_id == identity.max_user_id:
        raise HTTPException(status_code=422, detail="это вы")

    person = (
        await session.execute(select(BotUser).where(BotUser.max_user_id == user_id))
    ).scalar_one_or_none()
    if person is not None and not person.max_reachable:
        # Человек выключил «можно писать в MAX» — карточку не шлём.
        raise HTTPException(
            status_code=409, detail="этот человек не принимает сообщения в MAX — позвоните ему"
        )
    bot = await botinfo.username()
    direct = contact.user_chat(person.username if person else "")

    key = (identity.max_user_id, user_id)
    now = time.monotonic()
    if now - _recent.get(key, 0.0) < REPEAT_SECONDS:
        # Карточка уже в чате — просто ведём туда ещё раз.
        return ReachOut(sent=True, chat_href=direct, bot_href=f"https://max.ru/{bot}" if bot else "")

    sent = await send_contact(
        identity.max_user_id,
        await known_chat(session, identity.max_user_id),
        name=name,
        contact_id=user_id,
        text=text,
        phone=person.phone if person and share_phone else "",
    )
    if sent:
        _recent[key] = now
        # Словарь не должен расти вечно: старые отметки больше не нужны.
        for stale in [k for k, at in _recent.items() if now - at > REPEAT_SECONDS]:
            _recent.pop(stale, None)
    return ReachOut(sent=sent, chat_href=direct, bot_href=f"https://max.ru/{bot}" if bot else "")
