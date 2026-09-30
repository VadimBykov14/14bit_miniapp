"""Лента уведомлений и счётчик непрочитанного."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import live, mutes
from ..auth import Identity, current_identity
from ..messaging import button_for
from ..db import get_session
from ..models import Notification
from ..schemas import MuteOut, NotificationOut, NotificationsOut, NotificationsReadIn

router = APIRouter()

# Лента — не архив: двух экранов истории достаточно, остальное живёт
# в заявках и в журнале обмена.
LIMIT = 50


async def unread_count(session: AsyncSession, max_user_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count(Notification.id)).where(
                    Notification.max_user_id == max_user_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> NotificationsOut:
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.max_user_id == identity.max_user_id)
            .order_by(Notification.at.desc())
            .limit(LIMIT)
        )
    ).scalars()
    items = [
        NotificationOut(
            id=row.id,
            kind=row.kind,
            text=row.text,
            order_id=row.order_id,
            delivered=row.delivered,
            muted=row.muted,
            at=row.at,
            unread=row.read_at is None,
            # Тот же ярлык экрана, что у кнопки под сообщением в MAX: запись в
            # ленте и кнопка в чате ведут в одно место.
            link=_link(row),
        )
        for row in rows
    ]
    return NotificationsOut(
        unread=await unread_count(session, identity.max_user_id), items=items
    )


def _link(row: Notification) -> str:
    return button_for(row.kind, row.order_id, row.storefront_id, row.role)["payload"]


@router.post("/notifications/read", response_model=NotificationsOut)
async def mark_read(
    payload: NotificationsReadIn | None = Body(default=None),
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> NotificationsOut:
    """Отмечает прочитанным то, что человек открыл, — или всё сразу.

    Раньше уведомление гасло только по «Прочитать все»: нажал на запись,
    посмотрел заявку — а точка непрочитанного горит. Теперь прочитано то,
    на что нажали, и всё, что ведёт туда же: три уведомления об одной заявке
    гаснут вместе, когда её открыли — из ленты, из кнопки бота или из списка.
    """
    unread = [
        Notification.max_user_id == identity.max_user_id,
        Notification.read_at.is_(None),
    ]
    now = datetime.now(timezone.utc)
    if payload is None or not (payload.ids or payload.order_id or payload.link):
        await session.execute(update(Notification).where(*unread).values(read_at=now))
    else:
        rows = (await session.execute(select(Notification).where(*unread))).scalars()
        wanted = set(payload.ids)
        touched = 0
        for row in rows:
            if (
                row.id in wanted
                or (payload.order_id is not None and row.order_id == payload.order_id)
                or (payload.link and _link(row) == payload.link)
            ):
                row.read_at = now
                touched += 1
        if not touched:
            return NotificationsOut(unread=await unread_count(session, identity.max_user_id))
    await session.commit()
    # Значки на других устройствах человека гаснут тоже.
    await live.publish([identity.max_user_id], "badges")
    return await list_notifications(identity, session)


@router.delete("/notifications/{notification_id}", status_code=204, response_class=Response)
async def delete_notification(
    notification_id: int,
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Убирает запись из своей ленты — свайпом на экране «Все уведомления».

    Чужую запись не трогаем и о ней не сообщаем: ответ тот же, что на уже
    удалённую, — повторное нажатие после обрыва связи не должно пугать ошибкой.
    """
    await session.execute(
        delete(Notification).where(
            Notification.id == notification_id,
            Notification.max_user_id == identity.max_user_id,
        )
    )
    await session.commit()
    # Лента в «Аккаунте» и значок непрочитанного — на всех устройствах.
    await live.publish([identity.max_user_id], "feed", "badges")
    return Response(status_code=204)


@router.get("/notifications/mutes", response_model=list[MuteOut])
async def list_mutes(
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> list[MuteOut]:
    """Что человек отключил кнопкой «Не присылать такие» под сообщениями бота."""
    return [
        MuteOut(kind=kind, side=side, label=label)
        for kind, side, label in await mutes.listing(session, identity.max_user_id)
    ]


@router.delete("/notifications/mutes/{kind}", response_model=list[MuteOut])
async def unmute(
    kind: str,
    side: str = Query(default="", max_length=10),
    identity: Identity = Depends(current_identity),
    session: AsyncSession = Depends(get_session),
) -> list[MuteOut]:
    """Вернуть уведомления этого вида в MAX. Уже включённые — не ошибка."""
    await mutes.unmute(session, identity.max_user_id, kind[:30], side)
    await session.commit()
    await live.publish([identity.max_user_id], "mutes")
    return await list_mutes(identity, session)
