"""Количества с точностью до одной десятой.

Оптовая торговля не только штучная: колбаса идёт по 0,4 кг, сыр — по 0,5,
и кратность упаковки у таких позиций дробная. Поэтому количество везде
хранится как `Numeric(12, 1)`.

Кратность проверяется в десятых долях целыми числами, а не остатком от
деления float: `0.3 % 0.1` в двоичной арифметике даёт 0.0999…, и заявка
на 300 граммов при шаге 100 граммов была бы отвергнута как некратная.
"""

from __future__ import annotations

from decimal import Decimal

# Шаг сетки: одна десятая. Всё, что мельче, округляется.
SCALE = 10


def tenths(value: object) -> int:
    """Количество в десятых долях единицы. 0.4 → 4, 12 → 120."""
    return int(round(float(value or 0) * SCALE))


def normalize(value: object) -> float:
    """Приводит к сетке в одну десятую."""
    return tenths(value) / SCALE


def on_grid(value: object) -> bool:
    """Лежит ли значение на сетке в одну десятую. 0,35 кг не лежит —
    и лучше сказать об этом, чем молча округлить чужой заказ."""
    return abs(float(value or 0) * SCALE - tenths(value)) < 1e-6


def is_multiple(qty: object, pack: object) -> bool:
    """Кратно ли количество упаковке."""
    step = tenths(pack)
    if step <= 0:
        return True
    return tenths(qty) % step == 0


def down_to_pack(qty: object, pack: object) -> float:
    """Ближайшее сверху-вниз кратное значение. Нужно, когда прошлое
    количество уже не помещается в остаток."""
    step = tenths(pack)
    if step <= 0:
        return normalize(qty)
    return (tenths(qty) // step) * step / SCALE


def up_to_pack(qty: object, pack: object) -> float:
    """Ближайшее снизу-вверх кратное: 30 шт при упаковке по 12 — это 36."""
    step = tenths(pack)
    if step <= 0:
        return normalize(qty)
    return -(-tenths(qty) // step) * step / SCALE


def order_minimum(min_qty: object, pack: object) -> float | None:
    """Меньше этого в одной заявке не заказать: минимум поставщика, поднятый
    до целой упаковки — после смены кратности он мог перестать ей кратным
    быть. None — минимума нет, хватает одной упаковки."""
    if min_qty is None or tenths(min_qty) <= 0:
        return None
    return up_to_pack(min_qty, pack)


def edit_floor(ordered: object, min_qty: object, pack: object) -> float:
    """Ниже этого поставщик не уменьшает строку при подтверждении
    (просьба пользователя): минимум позиции, без минимума — упаковка, а
    если заказано меньше минимума (его задали позже) — заказанное."""
    return min(float(ordered), order_minimum(min_qty, pack) or float(pack))


# Сколько менеджер может добавить сверх заказанного, в процентах. Клиент
# соглашался на своё количество: чуть больше — добрать до целой партии —
# нормально, а «на пятую часть больше» — уже другой заказ и другие деньги.
EXTRA_PERCENT = 5


def ceiling(ordered: object, pack: object) -> float:
    """Больше этого подтвердить нельзя: заказанное плюс 5 %, вниз до
    упаковки, но не меньше самого заказа."""
    limit = tenths(ordered) * (100 + EXTRA_PERCENT) // 100
    step = tenths(pack)
    if step > 0:
        limit = (limit // step) * step
    return max(limit, tenths(ordered)) / SCALE


def to_decimal(value: object) -> Decimal:
    """Для записи в базу: без промежуточного float, чтобы не таскать
    двоичную погрешность в Numeric."""
    return Decimal(tenths(value)) / SCALE


def human(value: object, unit: str = "шт") -> str:
    """«0,5 кг», «12 шт» — без хвостового нуля у целых."""
    amount = normalize(value)
    text = f"{amount:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} {unit}"
