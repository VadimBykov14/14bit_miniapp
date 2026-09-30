"""Тестовые боты — вторая сторона сценария для проверяющих.

Жюри проверяет продукт в одиночку, а сценарий у него двусторонний: заявку
оформляет магазин, подтверждает поставщик. Поэтому на стенде живут два бота
и с небольшой задержкой делают то, что сделал бы человек с другой стороны:

- бот-поставщик с витриной «Тестовая»: одобряет просьбы о подключении и
  подтверждает оформленные заявки;
- бот-магазин: просится в новую витрину на тестовой базе 1С, после
  одобрения оформляет заявку, а подтверждённую через 30 секунд принимает
  досрочно.

Боты ходят в API как обычные пользователи: данные запуска подписывает сам
сервер (webapp_auth.sign), и запрос проходит те же проверки, уведомления и
обмен с 1С, что и запрос человека. id у ботов отрицательные — у настоящих
пользователей MAX они положительные, — поэтому писать ботам в MAX нечего:
messaging.tell их пропускает, а «Написать» боту ведёт на аккаунт демо-стенда
(routers/reach.py).

Картинки «Тестовой» — из витрины аккаунта демо-стенда, см. dress().

Остатки боты не пополняют (решение пользователя): бот-магазин берёт по
минимуму, а у «Тестовой» остаток с большим запасом.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from webapp_auth import sign

from . import onec, storage
from .auth import BOT_TOKEN
from .db import Session
from .models import (
    Client, Connection, Employee, Enterprise, Mode, Order, OrderStatus, Role, Source, Storefront,
    StorefrontItem,
)
from .quantity import tenths
from .routers.public import ask_to_join
from .seed import DEMO_USER_ID

log = logging.getLogger("api")

ENABLED = os.environ.get("TEST_BOTS", "1") == "1"
# Слаги тестовых баз («база» из ключа «база.секрет») через запятую: к
# витринам на них приходит бот-магазин. Пусто — любая тестовая база, кроме
# демо. На стенде — база со служебного слайда, чтобы бот не просился к
# живым тестировщикам.
BASES = {slug.strip() for slug in os.environ.get("TEST_BOTS_BASES", "").split(",") if slug.strip()}

SUPPLIER_ID = -1001
SHOP_ID = -1002
NAMES = {SUPPLIER_ID: "Бот-поставщик", SHOP_ID: "Бот-магазин"}

# Как часто просыпаться, сколько «думать» перед действием и через сколько
# после подтверждения принимать заказ — секунды. 30 — как на служебном слайде.
TICK = 5
DELAY = 15
ACCEPT_DELAY = 30
# Не вышло действие — следующая попытка через минуту, а не каждым проходом:
# иначе одна неудача забивала бы журнал.
RETRY = 60
# Пока у «Тестовой» нет картинок, раз в десять минут смотрим, не появились
# ли они у витрины-образца. Позиций с фото берём не больше двенадцати.
DRESS_EVERY = 600
PICTURED = 12

EVERY_DAY = "пн,вт,ср,чт,пт,сб,вс"
# Остаток с запасом: пополнять его боты не будут.
STOCK = 5000
ITEMS = [
    ("Печенье сахарное, 300 г", "шт", 12, 58.00),
    ("Вафли сливочные, 250 г", "шт", 10, 68.00),
    ("Сушки ванильные, 200 г", "шт", 20, 39.50),
    ("Пряники мятные, 350 г", "шт", 8, 74.00),
    ("Зефир бело-розовый, 250 г", "шт", 12, 96.00),
    ("Мармелад жевательный, развес", "кг", 0.5, 310.00),
]


@dataclass(frozen=True)
class Bots:
    enterprise_id: int
    employee_id: int
    storefront_ids: tuple[int, ...]
    client_id: int


async def ensure(session: AsyncSession) -> Bots:
    """Заводит ботов, если их ещё нет. Идемпотентно: вызывается каждым
    проходом, и бот, стёртый вместе с чем-то ещё, вернётся сам."""
    owner = (
        await session.execute(
            select(Employee).where(Employee.max_user_id == SUPPLIER_ID, Employee.role == Role.owner)
        )
    ).scalars().first()
    if owner is None:
        enterprise = Enterprise(name="Тестовый поставщик (бот)", city="", is_demo=False, is_bot=True)
        session.add(enterprise)
        await session.flush()
        owner = Employee(
            max_user_id=SUPPLIER_ID, enterprise_id=enterprise.id, role=Role.owner,
            name=NAMES[SUPPLIER_ID],
        )
        storefront = Storefront(
            enterprise_id=enterprise.id,
            name="Тестовая",
            initials="Т",
            mode=Mode.stock,
            source=Source.manual,
            delivery_days=EVERY_DAY,
            is_public=True,
            color="#2f7d6d",
            about="Подключение одобряет и заявки подтверждает бот — через несколько секунд",
        )
        session.add_all([owner, storefront])
        await session.flush()
        # Ассортимент с картинками — от витрины-образца; её нет — свой список.
        if not await dress(session, storefront):
            for name, unit, pack, price in ITEMS:
                session.add(
                    StorefrontItem(
                        storefront_id=storefront.id, name=name, unit=unit, pack_size=pack,
                        price=price, stock=STOCK,
                    )
                )
    shop = (
        await session.execute(select(Client).where(Client.max_user_id == SHOP_ID))
    ).scalars().first()
    if shop is None:
        shop = Client(max_user_id=SHOP_ID, name="Тестовый магазин (бот)", is_bot=True)
        session.add(shop)
    await session.commit()

    storefronts = tuple(
        (
            await session.execute(
                select(Storefront.id).where(Storefront.enterprise_id == owner.enterprise_id)
            )
        ).scalars()
    )
    return Bots(
        enterprise_id=owner.enterprise_id, employee_id=owner.id,
        storefront_ids=storefronts, client_id=shop.id,
    )


async def dress(session: AsyncSession, storefront: Storefront) -> bool:
    """Картинки «Тестовой» — из витрины аккаунта демо-стенда (DEMO_MAX_USER_ID),
    где их больше всего: логотип, обложка и позиции с фото.

    Позиции переносятся с названием, ценой и упаковкой — иначе фото не
    совпало бы с товаром. Файлы копируются: образец могут поменять или
    удалить, а у «Тестовой» картинка должна остаться. Прежние позиции без
    фото прячутся, а не удаляются: по ним могли быть заявки.

    Работает, только пока у «Тестовой» нет ни одной картинки. Возвращает,
    дал ли образец ассортимент.
    """
    if storefront.logo_key or storefront.cover_key:
        return False
    pictured = select(StorefrontItem.id).where(
        StorefrontItem.storefront_id == storefront.id, StorefrontItem.photo_key.is_not(None)
    )
    if (await session.execute(pictured.limit(1))).first():
        return False

    sample, sample_items, best = None, [], (0, 0)
    fronts = (
        await session.execute(
            select(Storefront)
            .join(Employee, Employee.enterprise_id == Storefront.enterprise_id)
            .join(Enterprise, Enterprise.id == Storefront.enterprise_id)
            .where(Employee.max_user_id == DEMO_USER_ID, Enterprise.is_bot.is_(False))
            .order_by(Storefront.id)
        )
    ).scalars().unique().all()
    for front in fronts:
        items = list(
            (
                await session.execute(
                    select(StorefrontItem)
                    .where(
                        StorefrontItem.storefront_id == front.id,
                        StorefrontItem.photo_key.is_not(None),
                        StorefrontItem.hidden.is_(False),
                        StorefrontItem.onec_missing.is_(False),
                    )
                    .order_by(StorefrontItem.id)
                    .limit(PICTURED)
                )
            ).scalars()
        )
        score = (len(items), bool(front.logo_key) + bool(front.cover_key))
        if score > best:
            sample, sample_items, best = front, items, score
    if sample is None:
        return False

    if sample.logo_key:
        storefront.logo_key = storage.copy(sample.logo_key, "logos")
    if sample.cover_key:
        storefront.cover_key = storage.copy(sample.cover_key, "covers")
    copies = []
    for item in sample_items:
        photo = storage.copy(item.photo_key, "items")
        if photo:
            copies.append(
                StorefrontItem(
                    storefront_id=storefront.id, name=item.name, unit=item.unit,
                    pack_size=item.pack_size, price=item.price, min_qty=item.min_qty,
                    description=item.description, photo_key=photo, stock=STOCK,
                )
            )
    if copies:
        await session.execute(
            update(StorefrontItem)
            .where(StorefrontItem.storefront_id == storefront.id)
            .values(hidden=True)
        )
        session.add_all(copies)
    log.info(
        "тестовые боты: картинки «%s» — из витрины «%s», позиций с фото %s",
        storefront.name, sample.name, len(copies),
    )
    return bool(copies)


def on_test_base(storefront: Storefront) -> bool:
    """Витрина ведётся из тестовой базы стенда, к которой ходит бот-магазин."""
    if storefront.source is not Source.onec or not storefront.onec_key or onec.own_base(storefront):
        return False
    slug = storefront.onec_key.partition(".")[0]
    return slug in BASES if BASES else slug != "demo"


def compose(items: list[dict], min_amount: float | None, lines: int = 2) -> list[dict] | None:
    """Строки заявки бота-магазина из каталога витрины.

    Две позиции, у которых запаса больше всего, — по минимуму: остатки
    никто не пополняет. Минимальную сумму заявки добираем по упаковке и с
    запасом в пятую часть: скидка «от суммы» опустила бы итог ниже порога.
    Не набирается — None.
    """
    picked = []
    for item in items:
        start = tenths(item.get("min_qty") or item["pack_size"])
        room = tenths(item["available"])
        if start <= 0 or start > room:
            continue
        picked.append({
            "id": item["id"], "qty": start, "pack": max(1, tenths(item["pack_size"])),
            "room": room, "price": float(item["price"]),
        })
    picked.sort(key=lambda row: row["room"] / row["qty"], reverse=True)
    picked = picked[:lines]
    if not picked:
        return None

    need = float(min_amount or 0) * 1.2
    while sum(row["qty"] / 10 * row["price"] for row in picked) < need:
        grow = [row for row in picked if row["qty"] + row["pack"] <= row["room"]]
        if not grow:
            return None
        row = min(grow, key=lambda candidate: candidate["qty"] / candidate["room"])
        row["qty"] += row["pack"]
    return [{"item_id": row["id"], "qty": row["qty"] / 10} for row in picked]


class Worker:
    """Проход ботов. Запросы идут в само приложение без сети — через
    ASGI, с теми же зависимостями и проверками, что у запросов людей."""

    def __init__(self, app: FastAPI) -> None:
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testbots", timeout=60
        )
        # Когда бот-магазин заметил, что его подключили: пауза перед заявкой
        # отсчитывается отсюда — время одобрения в базе не хранится.
        self.noticed: dict[int, float] = {}
        # Действия, которые не вышли, и когда их повторить.
        self.later: dict[tuple[str, int], float] = {}
        # Витрины, где заявку собрать не вышло: пишем в журнал один раз.
        self.warned: set[int] = set()
        # Когда снова поискать картинки для «Тестовой».
        self.dress_after = 0.0

    async def close(self) -> None:
        await self.http.aclose()

    async def call(
        self, user_id: int, role: str, method: str, path: str, body: dict | None = None
    ) -> dict | None:
        try:
            response = await self.http.request(
                method, f"/api{path}", json=body,
                headers={
                    "X-Max-Init-Data": sign(user_id, NAMES[user_id], BOT_TOKEN),
                    "X-Active-Role": role,
                },
            )
        except Exception as exc:  # noqa: BLE001 — сбой одного действия не держит остальные
            log.warning("тестовый бот: %s %s не удался: %s", method, path, exc)
            return None
        if response.status_code >= 400:
            log.warning(
                "тестовый бот: %s %s → %s %s", method, path, response.status_code,
                response.text[:200],
            )
            return None
        return response.json() if response.content else {}

    async def act(
        self, kind: str, target: int, user_id: int, role: str, method: str, path: str,
        body: dict | None = None,
    ) -> dict | None:
        """Действие бота. Не вышло — повтор через RETRY секунд."""
        if time.monotonic() < self.later.get((kind, target), 0):
            return None
        result = await self.call(user_id, role, method, path, body)
        if result is None:
            self.later[(kind, target)] = time.monotonic() + RETRY
        return result

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        due = now - timedelta(seconds=DELAY)
        async with Session() as session:
            bots = await ensure(session)
            if time.monotonic() >= self.dress_after:
                self.dress_after = time.monotonic() + DRESS_EVERY
                for storefront in (
                    await session.execute(
                        select(Storefront).where(Storefront.id.in_(bots.storefront_ids or (0,)))
                    )
                ).scalars().all():
                    await dress(session, storefront)
                await session.commit()
            requests = list(
                (
                    await session.execute(
                        select(Connection.id).where(
                            Connection.storefront_id.in_(bots.storefront_ids or (0,)),
                            Connection.status == "request",
                            Connection.at <= due,
                        )
                    )
                ).scalars()
            )
            incoming = list(
                (
                    await session.execute(
                        select(Order.id).where(
                            Order.storefront_id.in_(bots.storefront_ids or (0,)),
                            Order.status == OrderStatus.sent,
                            Order.created_at <= due,
                        )
                    )
                ).scalars()
            )
            asked = select(Connection.storefront_id).where(Connection.client_id == bots.client_id)
            fresh = [
                storefront
                for storefront in (
                    await session.execute(
                        select(Storefront).where(
                            Storefront.source == Source.onec,
                            Storefront.onec_key != "",
                            Storefront.created_at.is_not(None),
                            Storefront.created_at <= due,
                            Storefront.id.not_in(asked),
                        )
                    )
                ).scalars()
                if on_test_base(storefront)
            ]
            ordered = select(Order.storefront_id).where(Order.client_id == bots.client_id)
            approved = list(
                (
                    await session.execute(
                        select(Connection.storefront_id).where(
                            Connection.client_id == bots.client_id,
                            Connection.status == "active",
                            Connection.storefront_id.not_in(ordered),
                        )
                    )
                ).scalars()
            )
            to_accept = list(
                (
                    await session.execute(
                        select(Order.id).where(
                            Order.client_id == bots.client_id,
                            Order.status.in_(
                                (OrderStatus.confirmed, OrderStatus.assembling, OrderStatus.shipped)
                            ),
                            Order.confirmed_at <= now - timedelta(seconds=ACCEPT_DELAY),
                        )
                    )
                ).scalars()
            )
            # Просьба — тем же путём, что с полки, но и в витрину «по
            # приглашению»: поставщик увидит её в «Подключениях».
            for storefront in fresh:
                await ask_to_join(session, bots.client_id, storefront)

        moment = time.monotonic()
        self.later = {key: at for key, at in self.later.items() if at > moment}
        for connection_id in requests:
            await self.act(
                "approve", connection_id, SUPPLIER_ID, "owner", "POST",
                f"/owner/connections/{connection_id}/approve", {"employee_id": bots.employee_id},
            )
        for order_id in incoming:
            await self.act(
                "confirm", order_id, SUPPLIER_ID, "owner", "POST",
                f"/orders/{order_id}/confirm", {"lines": [], "comment": ""},
            )
        await self.order(approved)
        for order_id in to_accept:
            await self.act(
                "accept", order_id, SHOP_ID, "client", "POST",
                f"/orders/{order_id}/accept", {"lines": [], "photos": []},
            )

    async def order(self, storefront_ids: list[int]) -> None:
        """Заявка бота-магазина в витрину, где его подключили, — одна на
        витрину, после паузы с того прохода, где подключение заметили."""
        for gone in set(self.noticed) - set(storefront_ids):
            self.noticed.pop(gone)
        moment = time.monotonic()
        for storefront_id in storefront_ids:
            since = self.noticed.setdefault(storefront_id, moment)
            if moment - since < DELAY:
                continue
            detail = await self.act(
                "order", storefront_id, SHOP_ID, "client", "GET", f"/storefronts/{storefront_id}"
            )
            if detail is None:
                continue
            lines = compose(detail.get("items", []), detail.get("min_amount"))
            if not lines:
                # Позиции могут ещё не доехать из 1С, а остаток — появиться:
                # пробуем снова, но в журнал пишем один раз.
                self.later[("order", storefront_id)] = moment + RETRY
                if storefront_id not in self.warned:
                    self.warned.add(storefront_id)
                    log.warning("тестовый бот: в витрине %s не из чего собрать заявку", storefront_id)
                continue
            placed = await self.act(
                "order", storefront_id, SHOP_ID, "client", "POST", "/orders",
                {"storefront_id": storefront_id, "lines": lines, "comment": "Заявка тестового бота"},
            )
            if placed is not None:
                self.noticed.pop(storefront_id, None)


async def run(app: FastAPI) -> None:
    """Фоновый проход ботов, пока жив контейнер api."""
    if not BOT_TOKEN:
        log.warning("тестовые боты выключены: у сервера нет токена бота")
        return
    worker = Worker(app)
    try:
        while True:
            await asyncio.sleep(TICK)
            try:
                await worker.tick()
            except Exception as exc:  # noqa: BLE001 — цикл не имеет права умереть
                log.warning("тестовые боты: проход не удался: %s", exc)
    finally:
        await worker.close()
