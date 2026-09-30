"""Публичная полка города и подключение к витринам.

Полка — не маркетплейс, а механизм распространения: клиентская база первого
поставщика делает полку города непустой для второго.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import invites, live
from ..audience import known_chat
from ..auth import Identity, current_identity, require_client, require_owner, require_shop_owner
from ..db import get_session
from ..messaging import tell
from ..metrics import Accuracy, by_storefront
from ..models import (
    Client, ClientWorker, Connection, Employee, Enterprise, Invite, Role, Storefront,
    StorefrontItem,
)
from ..schemas import PendingInviteOut
from ..shelf import rank, sections

router = APIRouter()


class ShelfItemOut(BaseModel):
    id: int
    name: str
    logo_url: str | None = None
    cover_url: str | None = None
    color: str | None = None
    about: str = ""
    enterprise: str
    city: str
    mode: str
    items: int
    connected: bool
    pending: bool
    price_from: float | None = None
    # Точность отгрузки — единственная репутация поставщика на полке:
    # отзывов тут нет, а «довозит 98 %» проверяемо и берётся из приёмок.
    shipping_accuracy: float | None = None
    # «Заказ до 16:00» на плитке витрины под заказ; у складской — пусто
    cutoff_at: str | None = None
    # Дни доставки «пн,ср,пт»; пусто — график не задан, возят каждый день
    delivery_days: str = ""
    # Демо-витрина стенда: пометка «Тестовые данные» — требование брифа
    is_demo: bool = False
    # Раздел полки: popular, new или all — см. app/shelf.py
    section: str = "all"


class JoinResultOut(BaseModel):
    status: str
    storefront_id: int


class InviteOut(BaseModel):
    code: str
    kind: str
    link: str
    storefront_id: int | None = None


@router.get("/public/shelf", response_model=list[ShelfItemOut])
async def shelf(
    city: str | None = None,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> list[ShelfItemOut]:
    query = (
        # Цена «от» — тем же запросом: раньше за ней ходили отдельно для
        # каждой витрины на полке.
        select(
            Storefront, Enterprise, func.count(StorefrontItem.id), func.min(StorefrontItem.price)
        )
        .join(Enterprise, Enterprise.id == Storefront.enterprise_id)
        .outerjoin(
            StorefrontItem,
            (StorefrontItem.storefront_id == Storefront.id) & StorefrontItem.hidden.is_(False),
        )
        .where(Storefront.is_public.is_(True))
        .group_by(Storefront.id, Enterprise.id)
        .order_by(Enterprise.city, Storefront.name)
    )
    if city:
        # Витрина бота-поставщика (app/testbots.py) — в любом городе:
        # проверяющий регистрирует магазин в своём городе, а подключиться к
        # «Тестовой» ему нужно всё равно.
        query = query.where(or_(Enterprise.city == city, Enterprise.is_bot.is_(True)))

    existing: dict[int, str] = {}
    if identity.client_id:
        rows = await session.execute(
            select(Connection.storefront_id, Connection.status).where(
                Connection.client_id == identity.client_id
            )
        )
        existing = {storefront_id: status for storefront_id, status in rows}

    rows = list(await session.execute(query))
    ids = [row[0].id for row in rows]
    accuracy = await by_storefront(session, ids)
    clients = dict(
        (
            await session.execute(
                select(Connection.storefront_id, func.count(Connection.id))
                .where(Connection.storefront_id.in_(ids or [0]), Connection.status == "active")
                .group_by(Connection.storefront_id)
            )
        ).all()
    )
    placed = sections(ids, clients)

    result: list[ShelfItemOut] = []
    for storefront, enterprise, count, cheapest in rows:
        price_from = cheapest if storefront.show_prices_public else None
        status = existing.get(storefront.id)
        result.append(
            ShelfItemOut(
                id=storefront.id,
                name=storefront.name,
                logo_url=f"/api/photos/{storefront.logo_key}" if storefront.logo_key else None,
                cover_url=f"/api/photos/{storefront.cover_key}" if storefront.cover_key else None,
                color=storefront.color,
                about=storefront.about,
                enterprise=enterprise.name,
                city=enterprise.city,
                mode=storefront.mode.value,
                items=int(count or 0),
                connected=status == "active",
                pending=status == "request",
                price_from=float(price_from) if price_from is not None else None,
                shipping_accuracy=accuracy.get(storefront.id, Accuracy()).public,
                cutoff_at=storefront.cutoff_at.strftime("%H:%M") if storefront.cutoff_at else None,
                delivery_days=storefront.delivery_days,
                is_demo=enterprise.is_demo or enterprise.is_bot,
                section=placed[storefront.id],
            )
        )
    # Сортировка устойчивая: внутри «всех» остаётся порядок запроса.
    result.sort(key=lambda row: rank(row.section, row.id, clients))
    return result


class HomeOut(BaseModel):
    """«Витрины города»: открытые поставщики по разделам, см. app/shelf.py."""
    city: str = ""
    # Ленты акций больше нет (решение пользователя): акции видят только
    # подключённые, в каталоге. Пустой список — для версии приложения,
    # открытой до выкатки: она читает поле без проверки.
    promos: list[dict] = []
    storefronts: list[ShelfItemOut] = []


@router.get("/public/home", response_model=HomeOut)
async def home(
    city: str | None = None,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> HomeOut:
    """Витрина продукта для клиента: к кому можно подключиться. Никаких
    категорий — их некому наполнять, а пустая категория хуже её отсутствия."""
    return HomeOut(city=city or "", storefronts=await shelf(city, identity, session))


@router.post("/public/storefronts/{storefront_id}/join-request", status_code=202,
             response_model=JoinResultOut)
async def join_request(
    storefront_id: int,
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> JoinResultOut:
    """Заявка на подключение с полки. Решение за владельцем."""
    storefront = await session.get(Storefront, storefront_id)
    if not storefront or not storefront.is_public:
        raise HTTPException(status_code=404, detail="витрина не найдена")
    status = await ask_to_join(session, identity.client_id, storefront)
    return JoinResultOut(status=status, storefront_id=storefront_id)


async def ask_to_join(session: AsyncSession, client_id: int, storefront: Storefront) -> str:
    """Просьба магазина подключить его к витрине — или состояние той, что
    уже есть. Бот-магазин (app/testbots.py) просится так же, но и в витрину
    «по приглашению»: иначе проверяющему не с кем пройти сценарий."""
    existing = (
        await session.execute(
            select(Connection).where(
                Connection.client_id == client_id,
                Connection.storefront_id == storefront.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing.status

    session.add(Connection(client_id=client_id, storefront_id=storefront.id, status="request"))
    await session.commit()

    # Раньше просьба ложилась в базу молча, и владелец узнавал о ней, только
    # случайно открыв «Подключения». Решает владелец — ему и сообщение. В
    # ленте оно непрочитанное: просьба горит значком на «Аккаунте» и гаснет,
    # когда владелец открывает «Подключения».
    client = await session.get(Client, client_id)
    await live.connections_changed(session, storefront.enterprise_id)
    owners = (
        await session.execute(
            select(Employee.max_user_id).where(
                Employee.enterprise_id == storefront.enterprise_id,
                Employee.role == Role.owner,
            )
        )
    ).scalars()
    for user_id in set(owners):
        await tell(
            session,
            user_id,
            f"{client.name if client else 'Новый клиент'} просит подключить к витрине "
            f"«{storefront.name}». Решение — в разделе «Подключения».",
            kind="join_request",
            storefront_id=storefront.id,
        )
    return "request"


# --- приглашения по диплинку ---


@router.post("/owner/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    kind: str = "client",
    storefront_id: int | None = None,
    identity: Identity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    if kind not in ("client", "manager"):
        raise HTTPException(status_code=422, detail="приглашение бывает client или manager")
    if storefront_id is not None:
        storefront = await session.get(Storefront, storefront_id)
        if not storefront or storefront.enterprise_id != identity.enterprise_id:
            raise HTTPException(status_code=404, detail="витрина не найдена")

    code = f"{'inv' if kind == 'client' else 'emp'}_{secrets.token_urlsafe(6)}"
    session.add(
        Invite(
            code=code,
            kind=kind,
            enterprise_id=identity.enterprise_id,
            storefront_id=storefront_id,
            created_by=identity.max_user_id,
        )
    )
    await session.commit()
    return InviteOut(
        code=code,
        kind=kind,
        storefront_id=storefront_id,
        link=await invites.link(code),
    )


@router.post("/shop/invites", response_model=InviteOut, status_code=201)
async def create_worker_invite(
    identity: Identity = Depends(require_shop_owner),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    """Ссылка для работника магазина. Как с менеджером у поставщика: человек
    сам открывает её в MAX, и его личность подтверждает мессенджер."""
    code = f"wrk_{secrets.token_urlsafe(6)}"
    session.add(
        Invite(
            code=code,
            kind="worker",
            client_id=identity.client_id,
            created_by=identity.max_user_id,
        )
    )
    await session.commit()
    return InviteOut(
        code=code,
        kind="worker",
        link=await invites.link(code),
    )


@router.get("/invites/mine", response_model=list[PendingInviteOut])
async def my_invites(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> list[PendingInviteOut]:
    """Личные приглашения, которые ждут ответа.

    Главный путь — кнопка в сообщении бота. Но MAX не пишет тому, кто ни
    разу не открывал бота, и тогда приглашение ждёт человека здесь: на
    главной и на первом входе, с теми же «Принять» и «Отклонить».
    """
    rows = (
        await session.execute(
            select(Invite)
            .where(Invite.for_user == identity.max_user_id, Invite.used_by.is_(None))
            .order_by(Invite.at.desc())
            .limit(10)
        )
    ).scalars()
    result: list[PendingInviteOut] = []
    for invite in rows:
        card = await invites.card(session, invite, identity.max_user_id)
        if card.valid:
            result.append(
                PendingInviteOut(code=invite.code, kind=invite.kind, text=card.text, at=invite.at)
            )
    return result


@router.post("/invites/{code}/decline", status_code=204, response_class=Response)
async def decline_invite(
    code: str,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Отказ от личного приглашения: оно гаснет, а тот, кто звал, узнаёт
    ответ — иначе он так и ждал бы «принятия»."""
    invite = (
        await session.execute(select(Invite).where(Invite.code == code))
    ).scalar_one_or_none()
    if not invite or invite.for_user != identity.max_user_id:
        raise HTTPException(status_code=404, detail="приглашение не найдено")
    if invite.used_by is not None:
        return Response(status_code=204)
    invite.used_by = identity.max_user_id
    invite.used_at = datetime.now(timezone.utc)
    await session.commit()
    if invite.enterprise_id:
        await live.connections_changed(session, invite.enterprise_id)
    if invite.created_by:
        who = " ".join(filter(None, [identity.first_name, identity.last_name])) or "Человек"
        await tell(
            session, invite.created_by, f"{who}: приглашение к вашим витринам отклонено.",
            kind="info",
        )
    return Response(status_code=204)


@router.post("/invites/{code}/accept")
async def accept_invite(
    code: str,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Приглашение подключает клиента к витрине или заводит менеджера.

    Регистрации и паролей нет: пользователь уже авторизован в MAX.
    """
    invite = (
        await session.execute(select(Invite).where(Invite.code == code))
    ).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="приглашение не найдено")
    if invite.used_by is not None:
        # «Принять приглашение» нажали второй раз — это не чужое приглашение,
        # и отвечаем так же, как бот в чате.
        raise HTTPException(
            status_code=409,
            detail="это приглашение вы уже приняли"
            if invite.used_by == identity.max_user_id
            else "приглашение уже использовано",
        )
    # Личное приглашение из списка «Кто запускал бота» — только тому, кого
    # позвали: кнопку в пересланном сообщении нажмёт и кто-то другой.
    if invite.for_user and invite.for_user != identity.max_user_id:
        raise HTTPException(status_code=403, detail="приглашение адресовано другому человеку")
    # Аккаунт — либо поставщик, либо магазин: магазином (клиентом или
    # работником) поставщик не становится, в команду поставщика магазин не
    # входит. Кнопки «Принять» бот таким уже не показывает, но старые
    # сообщения с ней и ссылки ?startapp=… остаются.
    if invite.kind == "manager":
        shop = next(
            (
                membership.client_name
                for membership in identity.memberships
                if membership.role in (Role.client, Role.worker)
            ),
            None,
        )
        if shop is not None:
            raise HTTPException(status_code=409, detail=invites.shop_refusal(shop))
    else:
        supplier = next(
            (
                membership.enterprise_name
                for membership in identity.memberships
                if membership.role in (Role.owner, Role.manager)
            ),
            None,
        )
        if supplier is not None:
            raise HTTPException(status_code=409, detail=invites.supplier_refusal(supplier))

    if invite.kind == "worker":
        client = await session.get(Client, invite.client_id) if invite.client_id else None
        if client is None:
            raise HTTPException(status_code=404, detail="магазин больше не работает в приложении")
        if client.max_user_id == identity.max_user_id:
            raise HTTPException(status_code=409, detail="это ваш собственный магазин")
        already = (
            await session.execute(
                select(ClientWorker).where(
                    ClientWorker.client_id == client.id,
                    ClientWorker.max_user_id == identity.max_user_id,
                )
            )
        ).scalar_one_or_none()
        # Работник — одного магазина: роль в приложении одна на человека, и со
        # вторым магазином переключатель ролей открывал бы всегда первый.
        elsewhere = (
            await session.execute(
                select(Client.name)
                .join(ClientWorker, ClientWorker.client_id == Client.id)
                .where(
                    ClientWorker.max_user_id == identity.max_user_id,
                    ClientWorker.client_id != client.id,
                )
            )
        ).scalars().first()
        if elsewhere is not None:
            raise HTTPException(
                status_code=409,
                detail=f"вы уже работник магазина {elsewhere} — сначала выйдите из него в «Аккаунте»",
            )
        if not already:
            session.add(
                ClientWorker(
                    client_id=client.id,
                    max_user_id=identity.max_user_id,
                    max_chat_id=await known_chat(session, identity.max_user_id),
                    name=" ".join(filter(None, [identity.first_name, identity.last_name]))
                    or "Работник",
                )
            )
        invite.used_by = identity.max_user_id
        invite.used_at = datetime.now(timezone.utc)
        await session.commit()
        # Владелец видит нового работника, не обновляя экран.
        await live.publish([client.max_user_id], "workers")
        await tell(
            session,
            client.max_user_id,
            f"{' '.join(filter(None, [identity.first_name, identity.last_name])) or 'Новый работник'} "
            f"теперь в команде магазина «{client.name}» — по вашей ссылке.",
            kind="info",
        )
        return {"role": "worker", "client_id": client.id}

    if invite.kind == "manager":
        already = (
            await session.execute(
                select(Employee).where(
                    Employee.max_user_id == identity.max_user_id,
                    Employee.enterprise_id == invite.enterprise_id,
                )
            )
        ).scalar_one_or_none()
        if not already:
            session.add(
                Employee(
                    max_user_id=identity.max_user_id,
                    max_chat_id=await known_chat(session, identity.max_user_id),
                    enterprise_id=invite.enterprise_id,
                    role=Role.manager,
                    name=" ".join(filter(None, [identity.first_name, identity.last_name])) or "Менеджер",
                )
            )
        result = {"role": "manager", "enterprise_id": invite.enterprise_id}
        shop = ""
    else:
        client = (
            await session.execute(
                select(Client).where(Client.max_user_id == identity.max_user_id)
            )
        ).scalar_one_or_none()
        if not client:
            name = " ".join(filter(None, [identity.first_name, identity.last_name])) or "Клиент"
            client = Client(
                max_user_id=identity.max_user_id,
                max_chat_id=await known_chat(session, identity.max_user_id),
                name=f"Магазин «{name}»",
            )
            session.add(client)
            await session.flush()

        targets = (
            [invite.storefront_id]
            if invite.storefront_id
            else [
                row
                for row in (
                    await session.execute(
                        select(Storefront.id).where(Storefront.enterprise_id == invite.enterprise_id)
                    )
                ).scalars()
            ]
        )
        for storefront_id in targets:
            existing = (
                await session.execute(
                    select(Connection).where(
                        Connection.client_id == client.id,
                        Connection.storefront_id == storefront_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.status = "active"
            else:
                session.add(
                    Connection(client_id=client.id, storefront_id=storefront_id, status="active")
                )
        shop = client.name
        # Одна витрина — приложение откроет сразу её.
        result = {
            "role": "client",
            "storefronts": len(targets),
            "storefront_id": targets[0] if len(targets) == 1 else None,
        }

    invite.used_by = identity.max_user_id
    invite.used_at = datetime.now(timezone.utc)
    await session.commit()
    # Владелец видит нового клиента или сотрудника, не обновляя экран.
    await live.connections_changed(session, invite.enterprise_id)
    if invite.created_by and invite.created_by != identity.max_user_id:
        # Тот, кто звал, узнаёт, что приглашение приняли: раньше человек
        # просто появлялся в списке, и ждать ответа было нечем.
        # Без глаголов прошедшего времени: имя из MAX пол не сообщает, а
        # «принял(а) … подключён(а)» читается как анкета.
        who = " ".join(filter(None, [identity.first_name, identity.last_name])) or "Новый человек"
        kind = "joined"
        if invite.kind == "manager":
            kind = "joined_staff"
            text = f"{who} теперь в команде менеджером — приглашение принято."
        else:
            storefront = (
                await session.get(Storefront, invite.storefront_id) if invite.storefront_id else None
            )
            where = f"к витрине «{storefront.name}»" if storefront else "к вашим витринам"
            # Поставщик ищет в списке магазин, а не человека за ним.
            text = f"{shop or who} теперь в списке подключённых {where}."
        await tell(session, invite.created_by, text, kind=kind, role="owner")
    return result
