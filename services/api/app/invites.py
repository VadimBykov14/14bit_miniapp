"""Приглашения: ссылка ведёт в чат с ботом, а бот присылает приглашение.

Раньше ссылка сразу открывала мини-приложение. Человек, которого позвали,
попадал в приложение, так и не открыв бота, — и дальше уведомления до него
не доходили: MAX не пишет тому, у кого нет диалога с ботом. Теперь ссылка
вида `max.ru/<бот>?start=<код>` открывает чат, бот представляется и
присылает приглашение с кнопкой «Принять приглашение». Кнопка открывает
приложение с тем же кодом, и подключение происходит только тогда — когда
человек сам согласился.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import botinfo
from .models import Client, ClientWorker, Employee, Enterprise, Invite, InviteSend, Storefront
from .schedule import TZ

ACCEPT = "Принять приглашение"
# Кнопка под отказом — просто в приложение: пусть человек видит, куда пришёл.
HOME = {"text": "Открыть приложение", "payload": ""}


# Сколько приглашений в день владелец может разослать ботом из списка «Кто
# запускал бота». Список видит любой владелец, а пишет бот от имени всего
# сервиса: без предела один владелец разослал бы приглашение каждому.
AUDIENCE_PER_DAY = int(os.environ.get("AUDIENCE_INVITES_PER_DAY", "20"))


class DailyLimit(Exception):
    """Приглашений на сегодня больше нельзя. Текст — для владельца."""


async def count_send(session: AsyncSession, sender_id: int, recipient_id: int) -> None:
    """Засчитывает отправку приглашения или отказывает, если лимит на сегодня
    исчерпан. Не коммитит.

    Замок на отправителя держится до конца транзакции: десять одновременных
    нажатий иначе увидели бы один и тот же счётчик и прошли бы все.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"invite_sends:{sender_id}", 0)))
    )
    day_start = datetime.combine(datetime.now(TZ).date(), time.min, tzinfo=TZ)
    sent = (
        await session.execute(
            select(func.count(InviteSend.id)).where(
                InviteSend.sender_id == sender_id, InviteSend.at >= day_start
            )
        )
    ).scalar_one()
    if sent >= AUDIENCE_PER_DAY:
        raise DailyLimit(
            f"на сегодня приглашения закончились: ботом можно отправить не больше "
            f"{AUDIENCE_PER_DAY} в день. Завтра лимит обновится, а ссылку-приглашение "
            "из «Подключений» можно переслать и самому"
        )
    session.add(InviteSend(sender_id=sender_id, recipient_id=recipient_id))


async def link(code: str) -> str:
    """Ссылка-приглашение: открывает чат с ботом и передаёт ему код."""
    return f"https://max.ru/{await botinfo.username()}?start={code}"


@dataclass(frozen=True)
class Card:
    """Сообщение бота с приглашением и кнопка под ним."""
    text: str
    button: dict
    valid: bool = True


def _home(text: str) -> Card:
    return Card(text=text, button=HOME, valid=False)


async def supplier_of(session: AsyncSession, user_id: int) -> str | None:
    """Предприятие, где человек владелец или менеджер; None — не поставщик."""
    return (
        await session.execute(
            select(Enterprise.name)
            .join(Employee, Employee.enterprise_id == Enterprise.id)
            .where(Employee.max_user_id == user_id)
            .limit(1)
        )
    ).scalars().first()


def supplier_refusal(enterprise: str) -> str:
    """Почему аккаунт поставщика не становится магазином по ссылке.

    Аккаунт — либо поставщик, либо магазин (просьба пользователя). Магазин,
    заведённый поставщику приглашением, открывался по умолчанию — сервер
    выбирает роль клиента первой, — и приложение поставщика превращалось в
    магазинное."""
    return (
        f"вы в приложении на стороне поставщика — «{enterprise}». Заказывать как магазин с "
        "этого же аккаунта MAX нельзя: для магазина нужен другой аккаунт"
    )


async def shop_of(session: AsyncSession, user_id: int) -> str | None:
    """Магазин, где человек владелец точки или работник; None — не магазин."""
    return (
        await session.execute(
            select(Client.name)
            .outerjoin(ClientWorker, ClientWorker.client_id == Client.id)
            .where(or_(Client.max_user_id == user_id, ClientWorker.max_user_id == user_id))
            .limit(1)
        )
    ).scalars().first()


def shop_refusal(shop: str) -> str:
    """То же с другой стороны: магазин в команду поставщика не входит."""
    return (
        f"вы в приложении на стороне магазина — «{shop}». Работать у поставщика с этого же "
        "аккаунта MAX нельзя: для этого нужен другой аккаунт"
    )


def _sentence(text: str) -> str:
    return f"{text[0].upper()}{text[1:]}."


async def card(session: AsyncSession, invite: Invite | None, user_id: int | None) -> Card:
    """Что написать тому, кто пришёл по ссылке с кодом приглашения."""
    if invite is None:
        return _home(
            "Приглашение не нашлось — возможно, ссылку скопировали не полностью. "
            "Попросите прислать её ещё раз."
        )
    if invite.used_by is not None:
        if user_id and invite.used_by == user_id:
            return _home("Это приглашение вы уже приняли — всё открывается в приложении.")
        return _home("Это приглашение уже использовано. Если его прислали вам, попросите новое.")
    if invite.for_user and user_id and invite.for_user != user_id:
        return _home("Это приглашение адресовано другому человеку.")

    button = {"text": ACCEPT, "payload": invite.code}
    if invite.kind == "worker":
        shop = await session.get(Client, invite.client_id) if invite.client_id else None
        if shop is None:
            return _home("Магазин, который вас пригласил, больше не работает в приложении.")
        if user_id and (supplier := await supplier_of(session, user_id)):
            return _home(_sentence(supplier_refusal(supplier)))
        return Card(
            text=(
                f"{shop.name} приглашает вас работником магазина. После «Принять приглашение» "
                "вы сможете заказывать у поставщиков магазина и принимать товар."
            ),
            button=button,
        )

    enterprise = await session.get(Enterprise, invite.enterprise_id) if invite.enterprise_id else None
    if enterprise is None:
        return _home("Поставщик, который вас пригласил, больше не работает в приложении.")
    if invite.kind == "manager":
        if user_id and (shop := await shop_of(session, user_id)):
            return _home(_sentence(shop_refusal(shop)))
        return Card(
            text=(
                f"{enterprise.name} приглашает вас в команду менеджером. После «Принять "
                "приглашение» укажите телефон и график — клиенты увидят вас в разделе «Связаться»."
            ),
            button=button,
        )

    # Приглашение магазина: поставщику кнопку «Принять» не показываем.
    if user_id and (supplier := await supplier_of(session, user_id)):
        return _home(_sentence(supplier_refusal(supplier)))
    storefront = await session.get(Storefront, invite.storefront_id) if invite.storefront_id else None
    where = f"к витрине «{storefront.name}»" if storefront else "к своим витринам"
    city = f" ({enterprise.city})" if enterprise.city else ""
    return Card(
        text=(
            f"{enterprise.name}{city} приглашает вас {where}. Нажмите «Принять приглашение» — "
            "витрина откроется в приложении, и можно будет собирать заявки. Пока вы не "
            "приняли приглашение, вы ни к чему не подключены."
        ),
        button=button,
    )
