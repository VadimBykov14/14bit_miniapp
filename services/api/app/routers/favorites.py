"""Избранное: звёздочка на витрине, товаре и контакте, раздел в «Аккаунте».

У магазина — витрины, товары и сотрудники поставщиков, к которым он
подключён. У поставщика — клиенты. Отметить можно только то, что человеку
и так видно: звёздочка не должна стать обходом прав — например, телефон
сотрудника по-прежнему достаётся только подключённому клиенту.

Список собирается по текущим правам, а не по тому, что было при отметке:
отключили от витрины — её товары и сотрудники из избранного пропадают сами.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import contact, live, team
from ..auth import Identity, current_identity
from ..db import get_session
from ..models import (
    BotUser, Client, Connection, Employee, Enterprise, Favorite, Storefront, StorefrontItem,
)
from ..schemas import (
    FavoriteIdsOut, FavoriteItemOut, FavoritePersonOut, FavoritesOut, FavoriteStorefrontOut,
)

router = APIRouter()

BUYER_KINDS = ("storefront", "item", "employee")
STAFF_KINDS = ("client",)


def _kinds(identity: Identity) -> tuple[str, ...]:
    if identity.buyer:
        return BUYER_KINDS
    if identity.staff and identity.enterprise_id is not None:
        return STAFF_KINDS
    return ()


async def _connected_storefronts(session: AsyncSession, client_id: int) -> dict[int, Storefront]:
    """Витрины, к которым магазин подключён сейчас."""
    rows = (
        await session.execute(
            select(Storefront)
            .join(Connection, Connection.storefront_id == Storefront.id)
            .where(Connection.client_id == client_id, Connection.status == "active")
        )
    ).scalars()
    return {row.id: row for row in rows}


async def _enterprise_clients(session: AsyncSession, enterprise_id: int) -> set[int]:
    """Клиенты предприятия: подключённые или просящиеся — как у «Написать»."""
    return set(
        (
            await session.execute(
                select(Connection.client_id)
                .join(Storefront, Storefront.id == Connection.storefront_id)
                .where(Storefront.enterprise_id == enterprise_id)
            )
        ).scalars()
    )


async def _allowed(session: AsyncSession, identity: Identity, kind: str, target_id: int) -> bool:
    # Номер вне int4 до базы не доходит: asyncpg ответил бы ошибкой, а не «нет».
    if kind not in _kinds(identity) or not 0 < target_id < 2**31:
        return False
    if kind == "client":
        return target_id in await _enterprise_clients(session, identity.enterprise_id)
    fronts = await _connected_storefronts(session, identity.client_id)
    if kind == "storefront":
        return target_id in fronts
    if kind == "item":
        item = await session.get(StorefrontItem, target_id)
        return item is not None and not item.hidden and item.storefront_id in fronts
    employee = await session.get(Employee, target_id)
    return employee is not None and any(
        front.enterprise_id == employee.enterprise_id for front in fronts.values()
    )


async def _ids(session: AsyncSession, identity: Identity) -> FavoriteIdsOut:
    kinds = _kinds(identity)
    out = FavoriteIdsOut()
    if not kinds:
        return out
    rows = (
        await session.execute(
            select(Favorite.kind, Favorite.target_id)
            .where(Favorite.max_user_id == identity.max_user_id, Favorite.kind.in_(kinds))
            .order_by(Favorite.id)
        )
    ).all()
    for kind, target_id in rows:
        getattr(out, kind).append(target_id)
    return out


@router.get("/favorites/ids", response_model=FavoriteIdsOut)
async def favorite_ids(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> FavoriteIdsOut:
    return await _ids(session, identity)


@router.put("/favorites/{kind}/{target_id}", response_model=FavoriteIdsOut)
async def add_favorite(
    kind: str,
    target_id: int,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> FavoriteIdsOut:
    if not await _allowed(session, identity, kind, target_id):
        raise HTTPException(status_code=404, detail="нечего добавить в избранное")
    await session.execute(
        insert(Favorite)
        .values(max_user_id=identity.max_user_id, kind=kind, target_id=target_id)
        .on_conflict_do_nothing()
    )
    await session.commit()
    # Звёздочка загорается и на другом устройстве человека.
    await live.publish([identity.max_user_id], "favorites")
    return await _ids(session, identity)


@router.delete("/favorites/{kind}/{target_id}", response_model=FavoriteIdsOut)
async def remove_favorite(
    kind: str,
    target_id: int,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> FavoriteIdsOut:
    """Убрать — всегда можно, даже то, к чему доступа уже нет."""
    await session.execute(
        delete(Favorite).where(
            Favorite.max_user_id == identity.max_user_id,
            Favorite.kind == kind,
            Favorite.target_id == target_id,
        )
    )
    await session.commit()
    await live.publish([identity.max_user_id], "favorites")
    return await _ids(session, identity)


def _person(row_id: int, name: str, note: str, person: BotUser | None) -> FavoritePersonOut:
    """Контакт так же, как в «Связаться»: телефон, ник для «Написать» и
    разрешил ли человек писать себе в MAX."""
    phone = person.phone if person else ""
    return FavoritePersonOut(
        id=row_id,
        name=name,
        note=note,
        phone=phone,
        phone_href=contact.phone_href(phone),
        chat_href=contact.user_chat(person.username if person else ""),
        reachable=person.max_reachable if person else True,
    )


@router.get("/favorites", response_model=FavoritesOut)
async def favorites(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> FavoritesOut:
    """Раздел «Избранное»: то, что отмечено и что человеку сейчас доступно."""
    ids = await _ids(session, identity)
    out = FavoritesOut()

    if identity.buyer:
        fronts = await _connected_storefronts(session, identity.client_id)
        suppliers = {
            row.id: row.name
            for row in (
                await session.execute(
                    select(Enterprise).where(
                        Enterprise.id.in_({front.enterprise_id for front in fronts.values()} or {0})
                    )
                )
            ).scalars()
        }
        out.storefronts = [
            FavoriteStorefrontOut(
                id=front.id,
                name=front.name,
                supplier=suppliers.get(front.enterprise_id, ""),
                logo_url=f"/api/photos/{front.logo_key}" if front.logo_key else None,
                color=front.color,
            )
            for front in (fronts.get(target) for target in ids.storefront)
            if front is not None
        ]
        items = {
            row.id: row
            for row in (
                await session.execute(
                    select(StorefrontItem).where(
                        StorefrontItem.id.in_(ids.item or [0]), StorefrontItem.hidden.is_(False)
                    )
                )
            ).scalars()
        }
        out.items = [
            FavoriteItemOut(
                id=item.id,
                name=item.name,
                unit=item.unit,
                storefront_id=item.storefront_id,
                storefront_name=fronts[item.storefront_id].name,
                photo_url=f"/api/photos/{item.photo_key}" if item.photo_key else None,
            )
            for item in (items.get(target) for target in ids.item)
            if item is not None and item.storefront_id in fronts
        ]
        linked = {front.enterprise_id for front in fronts.values()}
        staff = {
            row.id: row
            for row in (
                await session.execute(select(Employee).where(Employee.id.in_(ids.employee or [0])))
            ).scalars()
            if row.enterprise_id in linked
        }
        known = await team.people(session, {row.max_user_id for row in staff.values()})
        out.contacts = [
            _person(
                employee.id,
                team.display_name(employee, known.get(employee.max_user_id)),
                suppliers.get(employee.enterprise_id, ""),
                known.get(employee.max_user_id),
            )
            for employee in (staff.get(target) for target in ids.employee)
            if employee is not None
        ]

    elif identity.staff and identity.enterprise_id is not None:
        mine = await _enterprise_clients(session, identity.enterprise_id)
        clients = {
            row.id: row
            for row in (
                await session.execute(
                    select(Client).where(Client.id.in_([c for c in ids.client if c in mine] or [0]))
                )
            ).scalars()
        }
        known = await team.people(session, {row.max_user_id for row in clients.values()})
        out.clients = [
            _person(client.id, client.name, client.address, known.get(client.max_user_id))
            for client in (clients.get(target) for target in ids.client)
            if client is not None
        ]

    return out
