"""Первый вход: выбор роли и сброс аккаунта.

Роль сохраняется записью в базе, а не в браузере: человек открывает
мини-приложение с разных устройств, и выбор должен переживать переустановку.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import contact, purge
from ..audience import known_chat, remember_visitor
from ..auth import Identity, current_identity
from ..db import get_session
from ..models import BotUser, Client, ClientWorker, Employee, Enterprise, Favorite, Invite, Role
from .cities import CityError, one_city

router = APIRouter()


class OnboardingIn(BaseModel):
    role: str
    # Клиент называет свою точку, владелец — своё предприятие.
    name: str = ""
    city: str = ""
    address: str = ""
    # Шаг «Контакты». Необязательный: без него поставщику некуда перезвонить,
    # но заставлять человека заполнять форму до первого взгляда на продукт
    # нельзя. Поменять можно в «Аккаунте» или в «Предприятии».
    phone: str = ""
    # Можно ли писать человеку в MAX. Ссылку на профиль не спрашиваем:
    # человек в MAX и так известен, бот пришлёт его карточку.
    max_reachable: bool = True
    # Прежняя форма присылала ссылку на профиль — её наличие значит «можно».
    contact_max: str = ""


class RoleOptionOut(BaseModel):
    role: str
    title: str
    description: str
    # Что спросить перед созданием. Пусто — значит ничего.
    name_label: str = ""
    name_placeholder: str = ""
    # Менеджера заводит владелец ссылкой, сам себя он назначить не может.
    self_serve: bool = True


OPTIONS = [
    RoleOptionOut(
        role="client",
        title="Клиент",
        description="Магазин или кафе: собирает заявки по витринам поставщиков",
        name_label="Название точки",
        name_placeholder="Магазин «У дома»",
    ),
    RoleOptionOut(
        role="owner",
        title="Поставщик",
        description="Своё предприятие: витрины, цены, заявки, сотрудники и обмен с 1С",
        name_label="Название предприятия",
        name_placeholder="Пекарня «Хлебный двор»",
    ),
    RoleOptionOut(
        role="manager",
        title="Менеджер поставщика",
        description="Добавляет владелец предприятия: попросите у него ссылку-приглашение",
        self_serve=False,
    ),
    RoleOptionOut(
        role="worker",
        title="Работник магазина",
        description="Добавляет владелец магазина: попросите у него ссылку-приглашение",
        self_serve=False,
    ),
]


@router.get("/onboarding/options", response_model=list[RoleOptionOut])
async def options() -> list[RoleOptionOut]:
    return OPTIONS


@router.post("/onboarding")
async def choose_role(
    payload: OnboardingIn,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if identity.memberships:
        raise HTTPException(status_code=409, detail="роль уже выбрана")

    try:
        role = Role(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="неизвестная роль") from exc

    person = " ".join(filter(None, [identity.first_name, identity.last_name])) or "Пользователь"
    title = payload.name.strip()[:200]

    if role is Role.manager:
        # Менеджер не может назначить себя сам: иначе любой открывший
        # приложение получил бы доступ к чужим заявкам и ценам.
        raise HTTPException(
            status_code=409,
            detail="менеджера добавляет владелец предприятия — попросите ссылку-приглашение",
        )
    if role is Role.worker:
        raise HTTPException(
            status_code=409,
            detail="работника добавляет владелец магазина — попросите ссылку-приглашение",
        )

    # Контакты и город проверяем до того, как что-то создать: ошибка в
    # номере не должна оставлять полузаведённое предприятие.
    try:
        phone = contact.normalize_phone(payload.phone)
    except contact.ContactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        city = one_city(payload.city)
    except CityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    reachable = payload.max_reachable or bool(payload.contact_max.strip())

    chat_id = await known_chat(session, identity.max_user_id)

    await remember_visitor(
        session, identity.max_user_id, identity.first_name, identity.last_name,
        identity.username,
    )
    visitor = (
        await session.execute(
            select(BotUser).where(BotUser.max_user_id == identity.max_user_id)
        )
    ).scalar_one_or_none()
    if visitor is not None:
        if phone:
            visitor.phone = phone
        visitor.max_reachable = reachable

    if role is Role.client:
        client = Client(
            max_user_id=identity.max_user_id,
            max_chat_id=chat_id,
            name=title or f"Магазин «{person}»",
            address=payload.address.strip()[:300],
            city=city,
        )
        session.add(client)
        await session.flush()

        # Подключений нет намеренно: клиент приходит по приглашению поставщика
        # или находит витрину на полке города. Пустой экран витрин ведёт на полку.
    else:
        if not title:
            raise HTTPException(status_code=422, detail="назовите предприятие")
        # Предприятие заводится своё, а не выбирается из существующих:
        # владелец, попавший в чужую базу, увидел бы чужие цены и заявки.
        enterprise = Enterprise(
            name=title,
            city=city,
            is_demo=False,
            # Номер со второго шага — и личный, и общий номер предприятия:
            # у небольшого поставщика это один и тот же телефон. «Писать в
            # MAX» — тоже его: общий контакт ведёт к владельцу.
            contact_phone=phone,
            max_chat=reachable,
            contact_kind="phone" if phone else ("max" if reachable else ""),
        )
        session.add(enterprise)
        await session.flush()
        session.add(
            Employee(
                max_user_id=identity.max_user_id,
                max_chat_id=chat_id,
                enterprise_id=enterprise.id,
                role=role,
                name=person,
            )
        )

    await session.commit()
    return {"role": role.value}



@router.delete("/me")
async def reset_account(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Удаляет аккаунт вместе с его заявками, чтобы можно было начать заново.

    Своя точка уходит целиком. Предприятие — если человек в нём единственный
    владелец: раньше оно оставалось без хозяина, и его витрины висели на
    полке города, куда клиенты слали просьбы, которые некому решать.
    Демо-предприятия стенда не трогаем — их восстанавливает сброс демо.
    """
    clients = list(
        (
            await session.execute(select(Client.id).where(Client.max_user_id == identity.max_user_id))
        ).scalars()
    )
    for client_id in clients:
        await purge.delete_client(session, client_id)

    owned = list(
        (
            await session.execute(
                select(Employee.enterprise_id).where(
                    Employee.max_user_id == identity.max_user_id, Employee.role == Role.owner
                )
            )
        ).scalars()
    )
    for enterprise_id in set(owned):
        enterprise = await session.get(Enterprise, enterprise_id)
        others = (
            await session.execute(
                select(Employee.id).where(
                    Employee.enterprise_id == enterprise_id,
                    Employee.role == Role.owner,
                    Employee.max_user_id != identity.max_user_id,
                )
            )
        ).first()
        if enterprise is not None and not enterprise.is_demo and others is None:
            await purge.delete_enterprise(session, enterprise_id)

    await session.execute(delete(Employee).where(Employee.max_user_id == identity.max_user_id))
    # Работник уходит из магазина — заявки, которые он оформил, остаются
    # магазину: это его закупки, а не личные.
    await session.execute(
        delete(ClientWorker).where(ClientWorker.max_user_id == identity.max_user_id)
    )
    # Неотвеченные приглашения ему — тоже: начавший заново не должен найти
    # на главной приглашение, которое ждало прежний аккаунт.
    await session.execute(
        delete(Invite).where(Invite.for_user == identity.max_user_id, Invite.used_by.is_(None))
    )
    # Избранное — про прежние витрины и клиентов. Отключённые в MAX виды
    # уведомлений остаются: человек сам просил бота такое не присылать.
    await session.execute(delete(Favorite).where(Favorite.max_user_id == identity.max_user_id))
    await session.commit()
    return {"reset": True}
