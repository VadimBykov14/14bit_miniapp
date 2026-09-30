"""Номенклатура и остатки из 1С: забрать, сравнить, разослать.

Раньше остатки тянулись один раз — при создании витрины или по кнопке
владельца — и дальше жили своей жизнью: заявка проходила, списание в 1С
случалось, а «доступно» у клиента не менялось, пока владелец не нажмёт
«Синхронизировать».

Теперь остатки перечитываются каждый раз, когда о складе становится
что-то известно:

* 1С сообщила об изменении — списание, правка позиции, новый заказ;
* заявка выгружена в 1С — сразу после выгрузки;
* фоном раз в минуту — боевая 1С по OData сама ни о чём не сообщает.

Изменившийся остаток сразу уходит в открытые каталоги и корзины.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import live, onec
from .db import Session
from .models import ExchangeEvent, ExchangeStatus, PriceChange, Source, Storefront, StorefrontItem
from .onec.odata import BASE_URL as DEFAULT_URL
from .quantity import human, to_decimal

log = logging.getLogger("stock")

KIND = "Номенклатура, цены, остатки"

# Одна витрина — одна выгрузка за раз: фоновый проход и сигнал из 1С могут
# совпасть, и без замка история цен получила бы одно изменение дважды.
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass
class Pulled:
    received: int = 0
    created: int = 0
    updated: int = 0
    # Что изменилось по-человечески: «Батон: 12 → 8 шт»
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.changes)


async def pull(
    session: AsyncSession,
    storefront: Storefront,
    actor: int | None = None,
    journal: str = "always",
) -> Pulled:
    """Тянет номенклатуру, цены и остатки в одну витрину. Не коммитит.

    Позиции ищутся по ссылке 1С, затем по артикулу, а при его отсутствии —
    по названию: в 1С артикул заполнен не всегда, а заводить дубль «Батон
    нарезной» второй раз нельзя. Описание и кратность 1С не присылает, их
    задаёт поставщик — не трогаем.

    Позиции, которой в ответе больше нет (удалили, пометили на удаление,
    сделали группой), в витрине скрываются: раньше сверка только добавляла
    и обновляла, и клиент заказывал то, чего в учёте уже нет. Вернётся в
    1С — вернётся и в витрину.

    `journal`: «always» — запись в журнале обмена всегда (кнопка владельца,
    создание витрины); «changes» — только если что-то изменилось, иначе
    фоновый проход раз в минуту засыпал бы журнал одинаковыми строками.
    """
    client = onec.backend(storefront)
    await onec.complete_settings(storefront, client)
    catalog = await client.catalog()

    existing = list(
        (
            await session.execute(
                select(StorefrontItem).where(StorefrontItem.storefront_id == storefront.id)
            )
        ).scalars()
    )
    by_ref = {row.onec_ref: row for row in existing if row.onec_ref}
    by_external = {row.external_id: row for row in existing if row.external_id}
    by_name = {row.name.strip().lower(): row for row in existing}

    result = Pulled(received=len(catalog))
    seen: set[int] = set()
    for row in catalog:
        item = (
            (by_ref.get(row.ref) if row.ref else None)
            or (by_external.get(row.external_id) if row.external_id else None)
            or by_name.get(row.name.strip().lower())
        )
        if item is None:
            session.add(
                StorefrontItem(
                    storefront_id=storefront.id,
                    external_id=row.external_id,
                    onec_ref=row.ref,
                    name=row.name,
                    unit=row.unit,
                    pack_size=to_decimal(row.pack_size or 1),
                    price=row.price,
                    stock=to_decimal(row.stock),
                )
            )
            result.created += 1
            result.changes.append(f"{row.name}: новая позиция")
            continue

        if row.price and float(item.price) != row.price:
            session.add(
                PriceChange(
                    item_id=item.id, old_price=item.price, new_price=row.price, changed_by=actor
                )
            )
            result.changes.append(f"{item.name}: цена {float(item.price):g} → {row.price:g} ₽")
            item.price = row.price
        fresh = to_decimal(row.stock)
        if float(fresh) != float(item.stock):
            result.changes.append(
                f"{item.name}: {human(item.stock, item.unit)} → {human(fresh, item.unit)}"
            )
            item.stock = fresh
        seen.add(item.id)
        item.unit = row.unit or item.unit
        if row.pack_size:
            item.pack_size = to_decimal(row.pack_size)
        if row.external_id:
            item.external_id = row.external_id
        if row.ref:
            item.onec_ref = row.ref
        if item.onec_missing:
            item.onec_missing = False
            item.hidden = False
            result.changes.append(f"{item.name}: снова есть в 1С")
        result.updated += 1

    # Пропавшее из 1С прячем. Пустой ответ — не повод прятать всё: так
    # выглядит и база, у которой не опубликован справочник.
    if catalog:
        for item in existing:
            if item.id not in seen and not item.onec_missing and not item.hidden:
                item.onec_missing = True
                item.hidden = True
                result.changes.append(f"{item.name}: нет в 1С — скрыта из витрины")

    storefront.stock_synced_at = onec.stock_synced_now()
    if journal == "always" or result.changed:
        shown = "; ".join(result.changes[:6]) + (" …" if len(result.changes) > 6 else "")
        session.add(
            ExchangeEvent(
                direction="in",
                object_kind=KIND,
                enterprise_id=storefront.enterprise_id,
                status=ExchangeStatus.done,
                message=(
                    f"витрина «{storefront.name}»: получено позиций {len(catalog)}, "
                    f"источник — {onec.mode_title(storefront)}"
                    if journal == "always"
                    else f"витрина «{storefront.name}», изменилось в 1С: {shown}"
                ),
            )
        )
    return result


async def refresh(storefront_id: int) -> Pulled | None:
    """Перечитать остатки витрины в своей сессии и разослать, если что-то
    поменялось. Для фона и сигналов из 1С: ошибка здесь никого не роняет."""
    async with _locks[storefront_id]:
        async with Session() as session:
            storefront = await session.get(Storefront, storefront_id)
            if storefront is None or storefront.source is not Source.onec:
                return None
            try:
                result = await pull(session, storefront, journal="changes")
            except onec.OneCUnavailable as exc:
                log.info("остатки «%s» не обновились: %s", storefront.name, exc)
                return None
            await session.commit()
            if result.changed:
                await live.stock_changed(session, storefront_id)
            return result


def later(storefront_id: int) -> None:
    """Перечитать остатки в фоне, не задерживая ответ клиенту."""
    task = asyncio.create_task(refresh(storefront_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


# Ссылки на фоновые задачи: без них сборщик мусора может снять задачу
# посреди выгрузки.
_pending: set[asyncio.Task] = set()


def _slug(storefront: Storefront) -> str:
    """Имя базы витрины: из её ключа, а без ключа — база стенда из окружения
    (так работает демо-витрина, заведённая сидом)."""
    url, _ = onec.connection(storefront)
    if not url and onec.MODE == "odata":
        url = DEFAULT_URL
    return url.rstrip("/").rsplit("/", 1)[-1] if url else ""


async def refresh_base(slug: str) -> int:
    """1С сообщила: в базе `slug` что-то изменилось. Перечитываем все
    витрины, которые к ней подключены."""
    async with Session() as session:
        linked = [
            row.id
            for row in (
                await session.execute(select(Storefront).where(Storefront.source == Source.onec))
            ).scalars()
            if _slug(row) == slug
        ]
    for storefront_id in linked:
        await refresh(storefront_id)
    return len(linked)


# Сколько витрин читаем одновременно. По очереди медленная база одного
# владельца (до 15 с на запрос) задерживала остатки у всех остальных.
PARALLEL = 4


async def refresh_all() -> None:
    async with Session() as session:
        linked = list(
            (
                await session.execute(
                    select(Storefront.id).where(Storefront.source == Source.onec)
                )
            ).scalars()
        )
    gate = asyncio.Semaphore(PARALLEL)

    async def one(storefront_id: int) -> None:
        async with gate:
            await refresh(storefront_id)

    await asyncio.gather(*(one(storefront_id) for storefront_id in linked))
