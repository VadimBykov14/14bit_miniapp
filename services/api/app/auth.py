"""Кто открыл мини-приложение.

Личность берётся только из подписанных данных запуска MAX. initDataUnsafe с
клиента не используется нигде: от того, кто это, зависит, какой прайс и какие
остатки человек увидит.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webapp_auth import InvalidInitData, LaunchContext, verify

from . import links
from .db import get_session
from .models import BotUser, Client, ClientWorker, Employee, Enterprise, Role

BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")


@dataclass(frozen=True)
class Membership:
    role: Role
    enterprise_id: int | None = None
    enterprise_name: str = ""
    client_id: int | None = None
    client_name: str = ""


@dataclass(frozen=True)
class Identity:
    max_user_id: int
    first_name: str
    role: Role | None
    last_name: str = ""
    enterprise_id: int | None = None
    client_id: int | None = None
    client_name: str = ""
    start_param: str | None = None
    memberships: tuple[Membership, ...] = ()
    # Публичный ник в MAX, если он задан: по нему поставщик пишет клиенту.
    username: str = ""

    @property
    def buyer(self) -> bool:
        """Покупает от имени точки: её владелец или работник магазина."""
        return self.role in (Role.client, Role.worker) and self.client_id is not None

    @property
    def staff(self) -> bool:
        return self.role in (Role.manager, Role.owner)


async def _from_link(session: AsyncSession, request: Request) -> tuple[LaunchContext, str]:
    """Личность по подписанной ссылке — для <img> и скачивания, которые не
    умеют передать заголовок. Подпись выдана этим же сервером и привязана
    к пути, поэтому ссылку на снимок нельзя переставить на чужую заявку."""
    signed_as = links.verify(request.url.path, request.query_params.get("t", ""))
    if signed_as is None:
        raise HTTPException(status_code=401, detail="ссылка устарела — откройте её заново")
    user_id, role = signed_as
    person = (
        await session.execute(select(BotUser).where(BotUser.max_user_id == user_id))
    ).scalar_one_or_none()
    ctx = LaunchContext(
        user_id=user_id,
        first_name=person.first_name if person else "",
        last_name=person.last_name if person else "",
        username=None,
        chat_id=None,
        start_param=None,
        auth_date=0,
    )
    return ctx, role or ""


async def current_identity(
    request: Request,
    x_max_init_data: str = Header(default=""),
    x_active_role: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> Identity:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="сервер без токена бота")

    if not x_max_init_data and "t" in request.query_params:
        ctx, x_active_role = await _from_link(session, request)
    else:
        try:
            ctx = verify(x_max_init_data, BOT_TOKEN)
        except InvalidInitData as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    memberships: list[Membership] = []

    rows = (
        await session.execute(
            select(Employee, Enterprise)
            .join(Enterprise, Enterprise.id == Employee.enterprise_id)
            .where(Employee.max_user_id == ctx.user_id)
        )
    ).all()
    for employee, enterprise in rows:
        memberships.append(
            Membership(
                role=employee.role,
                enterprise_id=employee.enterprise_id,
                enterprise_name=enterprise.name,
            )
        )

    for client in (
        await session.execute(select(Client).where(Client.max_user_id == ctx.user_id))
    ).scalars():
        memberships.append(
            Membership(role=Role.client, client_id=client.id, client_name=client.name)
        )

    # Работник магазина видит точку, в которую его пригласили.
    for worker, client in (
        await session.execute(
            select(ClientWorker, Client)
            .join(Client, Client.id == ClientWorker.client_id)
            .where(ClientWorker.max_user_id == ctx.user_id)
        )
    ).all():
        memberships.append(
            Membership(role=Role.worker, client_id=client.id, client_name=client.name)
        )

    if not memberships:
        # Человек в MAX есть, а в продукте его ещё нет — подключение по диплинку.
        return Identity(
            max_user_id=ctx.user_id,
            first_name=ctx.first_name,
            last_name=ctx.last_name,
            role=None,
            start_param=ctx.start_param,
            username=ctx.username or "",
        )

    # Выбирать можно только среди ролей, которые у человека действительно есть:
    # это экран «Смена роли» из макета, а не свободное переключение прав.
    # По умолчанию — клиент: стартовый экран приложения клиентский.
    active = next((m for m in memberships if m.role is Role.client), memberships[0])
    if x_active_role:
        for membership in memberships:
            if membership.role.value == x_active_role:
                active = membership
                break

    return Identity(
        max_user_id=ctx.user_id,
        first_name=ctx.first_name,
        last_name=ctx.last_name,
        role=active.role,
        enterprise_id=active.enterprise_id,
        client_id=active.client_id,
        client_name=active.client_name,
        start_param=ctx.start_param,
        memberships=tuple(memberships),
        username=ctx.username or "",
    )


async def require_client(identity: Identity = Depends(current_identity)) -> Identity:
    """Покупатель: владелец точки или работник магазина — заказывают,
    принимают товар и пишут поставщику одинаково."""
    if not identity.buyer:
        raise HTTPException(status_code=403, detail="доступно только клиенту витрины")
    return identity


async def require_shop_owner(identity: Identity = Depends(current_identity)) -> Identity:
    """Сверх работника: пригласить и убрать людей, поменять сведения о точке."""
    if identity.role is not Role.client or identity.client_id is None:
        raise HTTPException(status_code=403, detail="это может только владелец магазина")
    return identity


async def require_staff(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.role not in (Role.manager, Role.owner):
        raise HTTPException(status_code=403, detail="доступно только сотрудникам поставщика")
    return identity


async def require_owner(identity: Identity = Depends(current_identity)) -> Identity:
    """Четыре права сверх менеджера: сводка, сотрудники, цены и витрины,
    подключение клиентов."""
    if identity.role is not Role.owner:
        raise HTTPException(status_code=403, detail="доступно только владельцу предприятия")
    return identity
