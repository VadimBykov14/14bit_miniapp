"""Аудитория бота: кто с ним разговаривал и куда ему писать.

Единственный источник chat_id. В MAX `user_id` и `chat_id` — разные числа,
и подстановка одного вместо другого не ломается громко: уведомление просто
уходит в никуда. Поэтому адрес берётся только отсюда.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BotUser, Client, Employee


async def known_chat(session: AsyncSession, max_user_id: int) -> int | None:
    """Диалог с ботом, если он где-нибудь известен.

    Смотрим три места: аудиторию бота и карточки клиента и сотрудника.
    Чат мог быть записан раньше, чем появилась таблица аудитории, — и
    терять рабочий адрес из-за того, что он лежит в другой строке, глупо.
    """
    for column, owner in (
        (BotUser.max_chat_id, BotUser),
        (Client.max_chat_id, Client),
        (Employee.max_chat_id, Employee),
    ):
        chat_id = (
            await session.execute(
                select(column).where(owner.max_user_id == max_user_id, column.is_not(None))
            )
        ).scalars().first()
        if chat_id:
            return chat_id
    return None


async def remember_chat(session: AsyncSession, max_user_id: int) -> int | None:
    """Проставляет найденный чат всем записям этого человека.

    Нужно после создания клиента или сотрудника: до этого момента строки
    ещё не существовало, и вебхук бота её не обновил.
    """
    chat_id = await known_chat(session, max_user_id)
    if chat_id is None:
        return None
    for model in (Client, Employee):
        for row in (
            await session.execute(select(model).where(model.max_user_id == max_user_id))
        ).scalars():
            row.max_chat_id = chat_id
    return chat_id


async def remember_visitor(
    session: AsyncSession,
    max_user_id: int,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
) -> None:
    """Запоминает того, кто открыл мини-приложение.

    Раньше в аудиторию попадали только написавшие боту, и поставщик не видел
    человека, который зашёл в витрину по ссылке и ничего не написал. Писать
    ему всё равно есть куда: `POST /messages` принимает user_id.

    Ник нужен для «Связаться» у поставщика: по нему открывается чат с
    клиентом в MAX. Ника у человека может и не быть — тогда только телефон.
    """
    person = (
        await session.execute(select(BotUser).where(BotUser.max_user_id == max_user_id))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if person is None:
        session.add(
            BotUser(
                max_user_id=max_user_id,
                first_name=first_name[:120],
                last_name=last_name[:120],
                username=username[:120],
                last_seen_at=now,
            )
        )
    else:
        person.last_seen_at = now
        if username:
            person.username = username[:120]
        # Имя из MAX освежаем, пока человек не поправил его сам в «Аккаунте».
        if not person.name_edited:
            if first_name:
                person.first_name = first_name[:120]
            if last_name:
                person.last_name = last_name[:120]
    await session.commit()
