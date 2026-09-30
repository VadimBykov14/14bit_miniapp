"""Акции и цена со скидкой.

Скидка настоящая: она меняет цену в каталоге и уезжает в заявку. Акция,
о которой знает только баннер, клиента раздражает — он пересчитывает сумму
и не находит обещанного.

Цена считается в одном месте, потому что её видят трое: каталог, черновик
заявки и создание заказа. Разойдись они на копейку — клиент увидит одну
сумму, а заплатит другую.

Четыре типа акций, и они делятся на два класса:

* **позиционные** (`item`, `storefront`) видны сразу: цена в каталоге уже
  со скидкой;
* **объёмные** (`volume_amount`, `volume_qty`) зависят от того, что клиент
  набрал, поэтому в каталоге они — условие («−10 % от 5 000 ₽»), а в
  заявке уже цена.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Promo, PromoKind

ITEM_KINDS = (PromoKind.item, PromoKind.storefront)
VOLUME_KINDS = (PromoKind.volume_amount, PromoKind.volume_qty)


@dataclass(frozen=True)
class Discount:
    percent: float
    title: str

    def apply(self, price: float) -> float:
        return round(price * (100 - self.percent) / 100, 2)


def is_live(promo: Promo, today: date) -> bool:
    if not promo.is_active:
        return False
    if promo.starts_on and promo.starts_on > today:
        return False
    if promo.ends_on and promo.ends_on < today:
        return False
    return float(promo.discount_percent or 0) > 0


async def active(session: AsyncSession, storefront_id: int, today: date) -> list[Promo]:
    rows = (
        await session.execute(
            select(Promo)
            .where(Promo.storefront_id == storefront_id)
            .order_by(Promo.id.desc())
        )
    ).scalars()
    return [promo for promo in rows if is_live(promo, today)]


async def discounts(
    session: AsyncSession, storefront_id: int, today: date
) -> tuple[dict[int, Discount], Discount | None]:
    """Скидки, которые видны в каталоге: по позициям и на всю витрину.

    Если позиция попала и под свою акцию, и под общую, берётся большая:
    клиент ожидает лучшую цену, а не первую попавшуюся.
    """
    by_item: dict[int, Discount] = {}
    overall: Discount | None = None

    for promo in await active(session, storefront_id, today):
        if promo.kind not in ITEM_KINDS:
            continue
        value = Discount(percent=float(promo.discount_percent), title=promo.title)
        if promo.kind is PromoKind.storefront or promo.item_id is None:
            if overall is None or value.percent > overall.percent:
                overall = value
        else:
            current = by_item.get(promo.item_id)
            if current is None or value.percent > current.percent:
                by_item[promo.item_id] = value

    return by_item, overall


def best(item_id: int, by_item: dict[int, Discount], overall: Discount | None) -> Discount | None:
    own = by_item.get(item_id)
    if own and overall:
        return own if own.percent >= overall.percent else overall
    return own or overall


@dataclass(frozen=True)
class VolumeApplied:
    """Сработавшая объёмная акция: что и насколько подешевело."""
    title: str
    percent: float
    item_id: int | None


def apply_volume(
    promos: list[Promo],
    lines: list[tuple[int, float, float]],
) -> tuple[dict[int, float], list[VolumeApplied]]:
    """Пересчитывает цены под объёмные акции.

    `lines` — тройки (item_id, количество, цена за единицу) уже со скидками
    каталога. Возвращает новые цены по позициям и список сработавшего.

    Скидка «от суммы» применяется ко всей заявке, «от количества» — только
    к своей позиции. Если позиция попадает под обе, берётся большая: две
    скидки подряд на один товар превратили бы акцию в подарок.

    «От количества» без позиции — «на любую позицию»: порог у каждой
    позиции свой, и скидку получает та, что его набрала. Складывать штуки
    разных позиций нельзя — у одной штуки, у другой килограммы.
    """
    total = sum(qty * price for _, qty, price in lines)
    qty_by_item: dict[int, float] = {}
    for item_id, qty, _ in lines:
        qty_by_item[item_id] = qty_by_item.get(item_id, 0.0) + qty

    percent_by_item: dict[int, float] = {}
    applied: dict[str, VolumeApplied] = {}

    for promo in promos:
        percent = float(promo.discount_percent)
        if promo.kind is PromoKind.volume_amount:
            if promo.min_amount is None or total + 1e-9 < float(promo.min_amount):
                continue
            targets = list(qty_by_item)
            item_id = None
        elif promo.kind is PromoKind.volume_qty:
            if promo.min_qty is None:
                continue
            need = float(promo.min_qty)
            candidates = [promo.item_id] if promo.item_id is not None else list(qty_by_item)
            targets = [
                target for target in candidates
                if qty_by_item.get(target, 0.0) + 1e-9 >= need
            ]
            if not targets:
                continue
            item_id = promo.item_id
        else:
            continue

        touched = False
        for target in targets:
            if percent > percent_by_item.get(target, 0.0):
                percent_by_item[target] = percent
                touched = True
        if touched:
            applied[promo.title] = VolumeApplied(
                title=promo.title, percent=percent, item_id=item_id
            )

    prices = {
        item_id: round(price * (100 - percent_by_item[item_id]) / 100, 2)
        for item_id, _, price in lines
        if item_id in percent_by_item
    }
    return prices, list(applied.values())


def condition(promo: Promo, item_name: str = "") -> str:
    """Одна строка, которую видят и владелец, и клиент. Пишется здесь,
    чтобы в каталоге и в кабинете акция называлась одинаково."""
    percent = f"−{float(promo.discount_percent):g} %"
    if promo.kind is PromoKind.volume_amount:
        return f"{percent} при заказе от {float(promo.min_amount or 0):.0f} ₽"
    if promo.kind is PromoKind.volume_qty:
        target = f"«{item_name or 'позицию'}»" if promo.item_id is not None else "любую позицию"
        return f"{percent} на {target} при заказе от {float(promo.min_qty or 0):g}"
    if promo.kind is PromoKind.storefront:
        return f"{percent} на всю витрину"
    return f"{percent} на «{item_name or 'позицию'}»"


def volume_conditions(promos: list[Promo]) -> list[Promo]:
    """Объёмные акции витрины — их показываем условием, а не ценой."""
    return [promo for promo in promos if promo.kind in VOLUME_KINDS]
