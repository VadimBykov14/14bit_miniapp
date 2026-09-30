"""Живые обновления по веб-сокету.

Раньше приложение узнавало о новой заявке, отгрузке или остатке только
опросом раз в 20 секунд, а экраны без опроса — только после перехода.
Теперь сервер сам говорит «это изменилось», и открытый экран перечитывает
своё сразу.

По сокету идут только названия тем, а не данные: `orders`, `order:57`,
`storefront:3`, `badges`, `feed`, `connections`. Данные экран берёт тем
же запросом, что и раньше, — с проверкой прав. Так через сокет нельзя
ничего увидеть, даже подписавшись чужим именем.

Хаб живёт в процессе: api запущен одним процессом uvicorn. Если процессов
станет несколько, публикацию нужно будет пустить через LISTEN/NOTIFY
Postgres — интерфейс `publish` для этого менять не придётся.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from collections import defaultdict
from typing import Iterable

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Client, ClientWorker, Connection, Employee, Order, Role, Storefront

log = logging.getLogger("live")


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[int, set[WebSocket]] = defaultdict(set)

    def join(self, user_id: int, socket: WebSocket) -> None:
        self._sockets[user_id].add(socket)

    def leave(self, user_id: int, socket: WebSocket) -> None:
        sockets = self._sockets.get(user_id)
        if sockets is None:
            return
        sockets.discard(socket)
        if not sockets:
            self._sockets.pop(user_id, None)

    def online(self, user_ids: Iterable[int]) -> set[int]:
        return {user_id for user_id in user_ids if user_id in self._sockets}

    async def publish(self, user_ids: Iterable[int], topics: Iterable[str]) -> None:
        """Шлёт «изменилось» тем, кто сейчас в приложении. Ошибка одного
        сокета не мешает остальным: мёртвый просто выбывает."""
        message = json.dumps({"type": "changed", "topics": sorted(set(topics))})
        targets = [
            (user_id, socket)
            for user_id in set(user_ids)
            for socket in list(self._sockets.get(user_id, ()))
        ]
        if not targets:
            return
        results = await asyncio.gather(
            *(socket.send_text(message) for _, socket in targets), return_exceptions=True
        )
        for (user_id, socket), result in zip(targets, results):
            if isinstance(result, Exception):
                self.leave(user_id, socket)


hub = Hub()


async def publish(user_ids: Iterable[int | None], *topics: str) -> None:
    """Публикация не имеет права уронить обработчик: заявка уже сохранена,
    а экран в худшем случае обновится по опросу."""
    try:
        await hub.publish([user_id for user_id in user_ids if user_id], topics)
    except Exception as exc:  # noqa: BLE001
        log.warning("не смог разослать %s: %s", topics, exc)


def _safe(func):
    """Рассылка идёт после коммита: действие уже случилось, и сбой рассылки
    не должен превращать успешный ответ в 500."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            await func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("рассылка %s не удалась: %s", func.__name__, exc)

    return wrapper


async def _shop(session: AsyncSession, client_ids: list[int]) -> list[int]:
    """Работники магазинов: их экраны заявок и каталога живые так же, как у
    владельца точки."""
    if not client_ids:
        return []
    return list(
        (
            await session.execute(
                select(ClientWorker.max_user_id).where(ClientWorker.client_id.in_(client_ids))
            )
        ).scalars()
    )


async def _staff(session: AsyncSession, enterprise_id: int) -> list[int]:
    return list(
        (
            await session.execute(
                select(Employee.max_user_id).where(Employee.enterprise_id == enterprise_id)
            )
        ).scalars()
    )


@_safe
async def order_changed(session: AsyncSession, order: Order) -> None:
    """Заявка поменялась: клиенту и всем сотрудникам — списки, сама заявка
    и значки. Уведомление получают не все, а экран обновляется у всех:
    коллега должен видеть, что заявку уже подтвердили."""
    storefront = await session.get(Storefront, order.storefront_id)
    client = await session.get(Client, order.client_id)
    users = await _staff(session, storefront.enterprise_id) if storefront else []
    if client:
        users.append(client.max_user_id)
        users += await _shop(session, [client.id])
    await publish(users, "orders", f"order:{order.id}", "badges")


@_safe
async def stock_changed(session: AsyncSession, storefront_id: int) -> None:
    """Остаток или резерв изменился: каталог и корзина у подключённых
    клиентов, позиции у сотрудников. На этом держится «уже нет в наличии»:
    пока клиент выбирал, позицию выкупил другой."""
    storefront = await session.get(Storefront, storefront_id)
    if storefront is None:
        return
    rows = (
        await session.execute(
            select(Client.id, Client.max_user_id)
            .join(Connection, Connection.client_id == Client.id)
            .where(Connection.storefront_id == storefront_id, Connection.status == "active")
        )
    ).all()
    clients = [user_id for _, user_id in rows]
    workers = await _shop(session, [client_id for client_id, _ in rows])
    staff = await _staff(session, storefront.enterprise_id)
    await publish([*clients, *workers, *staff], f"storefront:{storefront_id}")


@_safe
async def shop_connection_changed(
    session: AsyncSession, client: Client, storefront_id: int
) -> None:
    """Магазин подключили к витрине или отключили от неё: у владельца точки
    и у работников — «Мои витрины», полка и открытый каталог. Каталог
    отключённой витрины перечитается и скажет, что она не подключена, а не
    откажет уже на отправке заявки."""
    users = [client.max_user_id, *await _shop(session, [client.id])]
    await publish(users, "storefronts", "badges", f"storefront:{storefront_id}")


@_safe
async def connections_changed(session: AsyncSession, enterprise_id: int) -> None:
    """Просьба о подключении или решение по ней: владельцу — список и
    значки. Магазину о решении говорит shop_connection_changed."""
    owners = list(
        (
            await session.execute(
                select(Employee.max_user_id).where(
                    Employee.enterprise_id == enterprise_id, Employee.role == Role.owner
                )
            )
        ).scalars()
    )
    await publish(owners, "connections", "badges", "clients", "staff")
