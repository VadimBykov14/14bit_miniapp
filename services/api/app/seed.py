"""Демо-данные стенда.

Два синтетических предприятия из концепта: кондитерская база со складской
витриной и пекарня под заказ. Весь контент помечен как тестовый — прямое
требование брифа (стр. 7 п. 10).

Сидирование идемпотентно: повторный запуск ничего не дублирует.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Client, Connection, Employee, Enterprise, Mode, Order, OrderItem, OrderStatus,
    Promo, PromoKind, Role, Source, Storefront, StorefrontItem,
)
from .numbering import next_number
from .onec import stock_synced_now

# Аккаунт MAX, под которым проходит демо. У него сразу три роли — это не
# упрощение, а случай из концепта: владелец пекарни одновременно клиент базы.
DEMO_USER_ID = int(os.environ.get("DEMO_MAX_USER_ID", "491411422"))

CONFECTIONERY_ITEMS = [
    ("Зефир ванильный, 250 г", "шт", 12, 96.00, 144),
    ("Пряники с начинкой, 400 г", "шт", 10, 112.00, 30),
    ("Вафли сливочные, 200 г", "шт", 20, 78.50, 260),
    ("Мармелад дольки, 350 г", "шт", 6, 134.00, 72),
    ("Печенье овсяное, 500 г", "шт", 8, 156.00, 96),
    ("Карамель «Барбарис», развес", "кг", 0.5, 289.00, 20),
]

BAKERY_ITEMS = [
    ("Батон нарезной, 400 г", "шт", 10, 38.00, 240),
    ("Булка сдобная, 100 г", "шт", 12, 22.00, 120),
    ("Багет французский, 250 г", "шт", 6, 54.00, 60),
]


async def seed(session: AsyncSession) -> None:
    # Демо заводится, пока на стенде нет демо-предприятий. Свои предприятия
    # людей этому не мешают: сброс демо стирает только демо и заводит заново.
    demo = select(func.count(Enterprise.id)).where(Enterprise.is_demo.is_(True))
    if (await session.execute(demo)).scalar_one():
        return

    base = Enterprise(name="Кондитерская база «Сладкий дом»", city="Кинешма")
    bakery = Enterprise(name="Пекарня «Хлебный двор»", city="Кинешма")
    session.add_all([base, bakery])
    await session.flush()

    confectionery = Storefront(
        enterprise_id=base.id,
        name="Кондитерский опт",
        initials="КО",
        mode=Mode.stock,
        source=Source.onec,
        delivery_days="вт,чт,сб",
        min_amount=3000,
        is_public=True,
        show_prices_public=False,
        color="#7a3fb8",
        about="Кондитерка мелким оптом, доставка своим транспортом",
        stock_synced_at=stock_synced_now(),
    )
    bread = Storefront(
        enterprise_id=bakery.id,
        name="Пекарня",
        initials="П",
        mode=Mode.preorder,
        source=Source.manual,
        delivery_days="пн,вт,ср,чт,пт,сб",
        cutoff_at=time(16, 0),
        is_public=True,
        show_prices_public=True,
        color="#c2622a",
        about="Печём ночью, привозим к открытию",
    )
    session.add_all([confectionery, bread])
    await session.flush()

    # Коды — те же, что у позиций в тестовой базе 1С: заказ и корректировка
    # находят в ней строку по коду, и остаток меняется с первой заявки, а не
    # после первой синхронизации.
    for code, (name, unit, pack, price, stock) in enumerate(CONFECTIONERY_ITEMS, start=1):
        session.add(
            StorefrontItem(
                storefront_id=confectionery.id,
                external_id=f"00-{code:04d}",
                name=name, unit=unit, pack_size=pack, price=price, stock=stock,
            )
        )
    for name, unit, pack, price, limit in BAKERY_ITEMS:
        session.add(
            StorefrontItem(
                storefront_id=bread.id,
                name=name, unit=unit, pack_size=pack, price=price,
                stock=0, daily_limit=limit,
            )
        )

    shop = Client(
        max_user_id=DEMO_USER_ID,
        max_chat_id=DEMO_USER_ID,
        name="Магазин «У дома»",
        address="Кинешма, ул. Советская, 12",
    )
    session.add(shop)
    await session.flush()

    session.add_all([
        Connection(client_id=shop.id, storefront_id=confectionery.id),
        Connection(client_id=shop.id, storefront_id=bread.id),
        # С графиком: в «Связаться» у клиента базы сразу есть к кому обратиться.
        Employee(max_user_id=DEMO_USER_ID, max_chat_id=DEMO_USER_ID,
                 enterprise_id=base.id, role=Role.manager, name="Менеджер базы",
                 work_days="пн,вт,ср,чт,пт,сб", work_from=time(8, 0), work_to=time(20, 0)),
        Employee(max_user_id=DEMO_USER_ID, max_chat_id=DEMO_USER_ID,
                 enterprise_id=bakery.id, role=Role.owner, name="Владелец пекарни"),
    ])
    await session.flush()

    # История не для красоты: по ней считается ритм заявок («обычно раз в
    # неделю, а прошло девять дней») и точность отгрузки витрины. Одной
    # заявки для этого мало — нужен ряд.
    for days_ago in (21, 14, 7):
        await _past_order(
            session, shop.id, confectionery.id, {0: 24, 1: 30, 2: 40, 3: 12, 4: 16}, days_ago
        )
    for days_ago in (5, 3, 1):
        await _past_order(session, shop.id, bread.id, {0: 30, 1: 24, 2: 12}, days_ago)
    # Акция на витрине — с настоящей скидкой: она меняет цену в каталоге.
    session.add(
        Promo(
            storefront_id=bread.id,
            kind=PromoKind.volume_amount,
            title="Опт от 3 000 ₽",
            description="Скидка на всю заявку",
            discount_percent=7,
            min_amount=3000,
        )
    )

    await session.commit()


async def _past_order(
    session: AsyncSession,
    client_id: int,
    storefront_id: int,
    lines: dict[int, int],
    days_ago: int = 5,
) -> None:
    """История нужна, чтобы «Повторить прошлый заказ» было чем наполнить."""
    items = list(
        (
            await session.execute(
                select(StorefrontItem)
                .where(StorefrontItem.storefront_id == storefront_id)
                .order_by(StorefrontItem.id)
            )
        ).scalars()
    )
    # created_at проставляем руками: по умолчанию его ставит база значением
    # now(), и вся «история» оказалась бы сегодняшней.
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    order = Order(
        storefront_id=storefront_id,
        client_id=client_id,
        delivery_date=created.date() + timedelta(days=1),
        status=OrderStatus.closed,
        created_at=created,
        confirmed_at=created,
        onec_document=None,
    )
    storefront = await session.get(Storefront, storefront_id)
    order.number = await next_number(session, storefront.enterprise_id)
    for index, qty in lines.items():
        if index < len(items):
            order.items.append(
                OrderItem(
                    item_id=items[index].id,
                    qty_ordered=qty,
                    qty_confirmed=qty,
                    qty_accepted=qty,
                    price=items[index].price,
                )
            )
    session.add(order)
