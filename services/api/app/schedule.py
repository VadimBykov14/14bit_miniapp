"""График витрины: отсечка, ближайшие даты доставки.

Живёт отдельно от роутеров, потому что этим пользуются трое: каталог,
создание заявки и напоминания. Импорт логики из роутера сводил бы их
в кольцо.

У каждой даты доставки своя отсечка — накануне, во время из настроек
витрины. Раньше отсечка считалась одна на «сегодня» и после наступления
переезжала на завтра, поэтому проверка «отсечка прошла» не срабатывала
никогда: в 17:30 при отсечке 16:00 заявка уходила на завтра. Теперь дата
доступна, пока не прошла её собственная отсечка, а «до отсечки» считается
до отсечки ближайшей доступной даты.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Mode, Storefront

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# Отсечка и график — местное время поставщика, не UTC: «до отсечки 40 минут»
# должно совпадать с часами на стене у менеджера.
TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Europe/Moscow"))

# Дальше этого заявку не оформить и доставку не перенести: за два месяца
# меняется и график, и прайс.
HORIZON_DAYS = 60


def _now(now: datetime | None) -> datetime:
    return now.astimezone(TZ) if now else datetime.now(TZ)


def _allowed(storefront: Storefront) -> set[int]:
    """Дни недели доставки. Пусто — график не задан, возим каждый день."""
    return {
        WEEKDAYS.index(day)
        for day in (storefront.delivery_days or "").split(",")
        if day in WEEKDAYS
    }


def in_schedule(storefront: Storefront, day: date) -> bool:
    allowed = _allowed(storefront)
    return not allowed or day.weekday() in allowed


def order_deadline(storefront: Storefront, day: date) -> datetime:
    """До какого момента принимаются заявки на эту дату доставки.

    Под заказ — отсечка накануне: пекарня печёт ночью то, что заказали до
    16:00. Со склада отсечки нет, но в день доставки заявку уже не собрать —
    принимаем до конца предыдущего дня.
    """
    if storefront.mode is Mode.preorder and storefront.cutoff_at is not None:
        return datetime.combine(day - timedelta(days=1), storefront.cutoff_at, tzinfo=TZ)
    return datetime.combine(day, time.min, tzinfo=TZ)


def orderable(storefront: Storefront, day: date, now: datetime | None = None) -> bool:
    """Можно ли прямо сейчас оформить заявку с доставкой в этот день."""
    moment = _now(now)
    if day <= moment.date() or day > moment.date() + timedelta(days=HORIZON_DAYS):
        return False
    return in_schedule(storefront, day) and moment < order_deadline(storefront, day)


def why_not_orderable(
    storefront: Storefront, day: date, now: datetime | None = None
) -> str | None:
    """Почему на эту дату заявку не оформить — словами для клиента. None —
    можно. Раньше дату проверял только интерфейс, и запрос в обход него
    ставил заявку на прошедший день или на воскресенье."""
    if orderable(storefront, day, now):
        return None
    moment = _now(now)
    nearest = next_delivery_date(storefront, moment)
    tail = f" — ближайшая доставка {nearest.strftime('%d.%m')}"
    if day > moment.date() + timedelta(days=HORIZON_DAYS):
        return f"заявки принимаются не дальше чем на {HORIZON_DAYS} дней вперёд{tail}"
    if day > moment.date() and not in_schedule(storefront, day):
        return f"{day.strftime('%d.%m')} поставщик не возит{tail}"
    return f"на {day.strftime('%d.%m')} заявки уже не принимаются{tail}"


def delivery_dates(
    storefront: Storefront, count: int = 8, now: datetime | None = None
) -> list[date]:
    """Только дни графика: календарь на весь год приводит к заказу
    на воскресенье и отказу постфактум."""
    moment = _now(now)
    today = moment.date()
    dates: list[date] = []
    for offset in range(1, HORIZON_DAYS + 1):
        candidate = today + timedelta(days=offset)
        if orderable(storefront, candidate, moment):
            dates.append(candidate)
        if len(dates) >= count:
            break
    return dates


def next_delivery_date(storefront: Storefront, now: datetime | None = None) -> date:
    """Ближайшая дата, на которую ещё принимают заявки."""
    dates = delivery_dates(storefront, 1, now)
    return dates[0] if dates else _now(now).date() + timedelta(days=1)


def cutoff_in_minutes(storefront: Storefront, now: datetime | None = None) -> int | None:
    """Сколько осталось до отсечки ближайшей даты. Клиент обязан видеть это
    ДО отправки: «до отсечки 40 минут» рядом с датой, на которую уйдёт заявка."""
    if storefront.mode is not Mode.preorder or storefront.cutoff_at is None:
        return None
    moment = _now(now)
    deadline = order_deadline(storefront, next_delivery_date(storefront, moment))
    return max(0, int((deadline - moment).total_seconds() // 60))


def production_started(
    storefront: Storefront, day: date, now: datetime | None = None
) -> bool:
    """Отсечка этой даты прошла: состав заявок на неё больше не меняется,
    и витрина «под заказ» начинает их готовить."""
    if storefront.mode is not Mode.preorder or storefront.cutoff_at is None:
        return False
    return _now(now) >= order_deadline(storefront, day)


def reschedule_dates(count: int = 7, now: datetime | None = None) -> list[date]:
    """Куда поставщик может перенести доставку: с сегодняшнего дня, любые
    дни. Везти ли вне графика — решает он сам, мы только подсказываем."""
    today = _now(now).date()
    return [today + timedelta(days=offset) for offset in range(count)]


def can_reschedule_to(day: date, now: datetime | None = None) -> bool:
    today = _now(now).date()
    return today <= day <= today + timedelta(days=HORIZON_DAYS)
