"""Люди магазина: владелец точки и работники.

То же, что team.py у поставщика, только со стороны клиента. Этим
пользуются заявки (кому писать о заявке), карточка клиента у поставщика
(кто в магазине сейчас на месте) и «Написать» (кому слать карточку).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import contact, team
from .models import BotUser, Client, ClientWorker, Order
from .schedule import TZ


async def workers(session: AsyncSession, client_id: int) -> list[ClientWorker]:
    return list(
        (
            await session.execute(
                select(ClientWorker)
                .where(ClientWorker.client_id == client_id)
                .order_by(ClientWorker.id)
            )
        ).scalars()
    )


async def worker_of(session: AsyncSession, client_id: int, max_user_id: int) -> ClientWorker | None:
    return (
        await session.execute(
            select(ClientWorker).where(
                ClientWorker.client_id == client_id, ClientWorker.max_user_id == max_user_id
            )
        )
    ).scalar_one_or_none()


async def order_recipients(session: AsyncSession, order: Order) -> dict[int, str]:
    """Кому со стороны магазина писать о заявке — и в какой роли.

    Владельцу точки — всегда: это его деньги и его поставщики. Работнику —
    если заявку оформил он: подтверждение и отгрузка — продолжение его дела,
    а о чужих заявках коллег ему знать незачем.
    """
    client = await session.get(Client, order.client_id)
    if client is None:
        return {}
    result = {client.max_user_id: "client"}
    author = order.created_by
    if author and author != client.max_user_id:
        if await worker_of(session, client.id, author) is not None:
            result[author] = "worker"
    return result


@dataclass(frozen=True)
class Person:
    """Человек магазина в карточке клиента у поставщика."""
    # Номер работника; у владельца точки — None
    worker_id: int | None
    name: str
    role: str
    on_shift: bool | None
    hours: str
    next: str
    phone: str
    phone_href: str
    chat_href: str
    # Разрешил ли писать себе в MAX
    reachable: bool


async def people(session: AsyncSession, client: Client) -> list[Person]:
    """Владелец точки и работники: у кого какой график и кто сейчас на месте.

    Первым — владелец, дальше работники: сначала те, кто сейчас на смене.
    """
    staff = await workers(session, client.id)
    known = await team.people(
        session, {client.max_user_id, *(row.max_user_id for row in staff)}
    )
    now = datetime.now(TZ)

    def card(person: BotUser | None, fallback: str) -> tuple[str, str, str, str, bool]:
        phone = person.phone if person else ""
        name = person.title if person and (person.first_name or person.last_name) else fallback
        return (
            name,
            phone,
            contact.phone_href(phone),
            contact.user_chat(person.username if person else ""),
            person.max_reachable if person else True,
        )

    owner = known.get(client.max_user_id)
    name, phone, phone_href, chat_href, reachable = card(owner, "Владелец")
    result = [
        Person(
            worker_id=None, name=name, role="client", on_shift=None, hours="", next="",
            phone=phone, phone_href=phone_href, chat_href=chat_href, reachable=reachable,
        )
    ]
    rows: list[Person] = []
    for worker in staff:
        name, phone, phone_href, chat_href, reachable = card(
            known.get(worker.max_user_id), worker.name or "Работник"
        )
        shift = team.on_shift(worker, now)
        rows.append(
            Person(
                worker_id=worker.id,
                name=name,
                role="worker",
                on_shift=shift,
                hours=team.hours_text(worker),
                next="" if shift else team.next_shift_text(worker, now),
                phone=phone,
                phone_href=phone_href,
                chat_href=chat_href,
                reachable=reachable,
            )
        )
    rows.sort(key=lambda row: row.on_shift is not True)
    return result + rows
