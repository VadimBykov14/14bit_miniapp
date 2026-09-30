"""Внутренние ручки. Наружу не проксируются: Caddy отдаёт только /api/*."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import invites, live, mutes, stock
from ..db import get_session
from ..models import BotUser, Client, Employee, Invite

router = APIRouter()


class OnecChangedIn(BaseModel):
    # Имя базы — первая часть ключа «база.секрет»
    base: str


@router.post("/internal/onec/changed", status_code=202)
async def onec_changed(payload: OnecChangedIn) -> dict:
    """1С сообщила: в базе что-то поменялось — списание, правка позиции,
    новый заказ. Перечитываем остатки подключённых витрин сразу, не ждём
    фонового прохода: клиент в каталоге должен увидеть это сейчас."""
    linked = await stock.refresh_base(payload.base.strip())
    return {"storefronts": linked}


class InviteCardIn(BaseModel):
    code: str
    user_id: int | None = None


@router.post("/internal/invites/card")
async def invite_card(payload: InviteCardIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Что ответить боту, когда человек пришёл по ссылке-приглашению:
    текст приглашения и кнопка «Принять приглашение» с тем же кодом."""
    invite = (
        await session.execute(select(Invite).where(Invite.code == payload.code.strip()[:24]))
    ).scalar_one_or_none()
    card = await invites.card(session, invite, payload.user_id)
    return {"text": card.text, "button": card.button, "valid": card.valid}


class MuteIn(BaseModel):
    user_id: int
    # То, что лежало в кнопке «Не присылать такие»: «mute:<вид>:<сторона>»
    payload: str


@router.post("/internal/notifications/mute")
async def mute_notifications(payload: MuteIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Человек нажал «Не присылать такие» под сообщением бота. Отвечаем
    подписью вида — бот скажет, что именно больше не придёт."""
    parsed = mutes.parse(payload.payload)
    if parsed is None:
        raise HTTPException(status_code=422, detail="такие уведомления не отключаются")
    kind, side = parsed
    await mutes.mute(session, payload.user_id, kind, side)
    await session.commit()
    # Открытый «Аккаунт» сразу покажет отключённое.
    await live.publish([payload.user_id], "mutes")
    return {"label": mutes.label(kind, side)}


class LinkChatIn(BaseModel):
    user_id: int
    chat_id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""


@router.post("/internal/chat")
async def link_chat(payload: LinkChatIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Запоминает диалог пользователя с ботом и самого пользователя.

    Без chat_id уведомлять некуда: он приходит только в апдейтах бота,
    а мини-приложение его не знает. Заодно это единственный источник
    списка людей, которых поставщик может пригласить в витрину: пригласить
    того, с кем у бота нет диалога, значит отправить письмо в никуда.
    """
    linked = 0
    for model in (Client, Employee):
        result = await session.execute(
            update(model)
            .where(
                model.max_user_id == payload.user_id,
                # is_not() разворачивается в «IS NOT $1», а это в Postgres
                # синтаксическая ошибка: IS NOT работает только с NULL и
                # булевыми. Нужно IS DISTINCT FROM — оно ещё и корректно
                # сравнивает с NULL, а именно такие строки и надо обновить.
                model.max_chat_id.is_distinct_from(payload.chat_id),
            )
            .values(max_chat_id=payload.chat_id)
        )
        linked += result.rowcount or 0

    now = datetime.now(timezone.utc)
    person = (
        await session.execute(select(BotUser).where(BotUser.max_user_id == payload.user_id))
    ).scalar_one_or_none()
    if person is None:
        session.add(
            BotUser(
                max_user_id=payload.user_id,
                max_chat_id=payload.chat_id,
                first_name=payload.first_name[:120],
                last_name=payload.last_name[:120],
                username=payload.username[:120],
                last_seen_at=now,
            )
        )
    else:
        person.max_chat_id = payload.chat_id
        person.last_seen_at = now
        # Имя могло смениться в профиле MAX — берём свежее, но не затираем
        # известное пустым: в некоторых апдейтах имени просто нет.
        if payload.first_name:
            person.first_name = payload.first_name[:120]
        if payload.last_name:
            person.last_name = payload.last_name[:120]
        if payload.username:
            person.username = payload.username[:120]

    await session.commit()

    known = bool(
        (
            await session.execute(select(Client.id).where(Client.max_user_id == payload.user_id))
        ).first()
        or (
            await session.execute(select(Employee.id).where(Employee.max_user_id == payload.user_id))
        ).first()
    )
    return {"linked": linked, "known": known}
