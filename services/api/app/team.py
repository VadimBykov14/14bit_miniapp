"""Люди поставщика: график, закреплённый менеджер, кому писать о заявке.

Живёт отдельно от роутеров, потому что этим пользуются трое: заявки
(кому уведомление и кто ведёт), «Связаться» у клиента (кто сейчас на
связи) и карточка клиента у владельца (кого закрепить).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import contact
from .models import BotUser, ClientManager, Employee, Role
from .schedule import TZ, WEEKDAYS


class ScheduleError(ValueError):
    """График не годится — объяснение для сотрудника."""


def parse_days(text: str) -> list[int]:
    """«пн,ср,пт» → [0, 2, 4]. Незнакомое молча пропускаем: хранится то,
    что прислала наша же форма."""
    return sorted({WEEKDAYS.index(day) for day in (text or "").split(",") if day in WEEKDAYS})


def parse_time(value: str) -> time:
    """«9:00» или «09:00» → time. Иначе — понятная ошибка."""
    raw = (value or "").strip()
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ScheduleError("время в формате ЧЧ:ММ, например 9:00") from exc


def normalize_schedule(days: list[str], start: str, end: str) -> tuple[str, time | None, time | None]:
    """Проверяет график из формы. Пустые дни — «график не указан»."""
    picked = [day for day in WEEKDAYS if day in set(days)]
    if not picked:
        return "", None, None
    begin, finish = parse_time(start), parse_time(end)
    if begin == finish:
        raise ScheduleError("начало и конец смены совпадают")
    return ",".join(picked), begin, finish


def clock(value: time | None) -> str:
    return f"{value.hour}:{value.minute:02d}" if value else ""


def days_text(days: list[int]) -> str:
    """Подряд идущие дни — диапазоном: «пн–пт», вразброс — списком."""
    if len(days) == 7:
        return "ежедневно"
    parts: list[str] = []
    run: list[int] = []
    for day in days + [99]:
        if run and day == run[-1] + 1:
            run.append(day)
            continue
        if run:
            parts.append(
                f"{WEEKDAYS[run[0]]}–{WEEKDAYS[run[-1]]}" if len(run) > 2
                else ", ".join(WEEKDAYS[d] for d in run)
            )
        run = [day] if day != 99 else []
    return ", ".join(parts)


def hours_text(employee: Employee) -> str:
    days = parse_days(employee.work_days)
    if not days or not employee.work_from or not employee.work_to:
        return ""
    return f"{days_text(days)} {clock(employee.work_from)}–{clock(employee.work_to)}"


def has_schedule(employee: Employee) -> bool:
    return bool(parse_days(employee.work_days) and employee.work_from and employee.work_to)


def on_shift(employee: Employee, now: datetime | None = None) -> bool | None:
    """На смене ли сейчас. None — график не указан.

    Ночная смена (22:00–06:00) принадлежит дню, в который началась: в
    субботу в 3 часа ночи на связи тот, у кого в графике пятница.
    """
    if not has_schedule(employee):
        return None
    now = (now or datetime.now(TZ)).astimezone(TZ)
    days = parse_days(employee.work_days)
    start, end = employee.work_from, employee.work_to
    moment = now.time()
    if start < end:
        return now.weekday() in days and start <= moment < end
    yesterday = (now.weekday() - 1) % 7
    return (now.weekday() in days and moment >= start) or (yesterday in days and moment < end)


def next_shift_text(employee: Employee, now: datetime | None = None) -> str:
    """Когда ответит: «сегодня с 9:00», «завтра с 9:00», «пн с 9:00»."""
    if not has_schedule(employee):
        return ""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    days = parse_days(employee.work_days)
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() not in days:
            continue
        begins = datetime.combine(day, employee.work_from, tzinfo=TZ)
        if begins <= now:
            continue
        when = "сегодня" if offset == 0 else "завтра" if offset == 1 else WEEKDAYS[day.weekday()]
        return f"{when} с {clock(employee.work_from)}"
    return ""


async def people(session: AsyncSession, user_ids: set[int]) -> dict[int, BotUser]:
    if not user_ids:
        return {}
    rows = (
        await session.execute(select(BotUser).where(BotUser.max_user_id.in_(user_ids)))
    ).scalars()
    return {row.max_user_id: row for row in rows}


def display_name(employee: Employee, person: BotUser | None) -> str:
    """Имя, которое человек видит у себя в «Аккаунте»: он мог его поправить,
    а снимок в сотрудниках сделан в день приглашения."""
    if person is not None and (person.first_name or person.last_name):
        return person.title
    return employee.name or "Сотрудник"


async def personal_manager(
    session: AsyncSession, enterprise_id: int, client_id: int
) -> Employee | None:
    return (
        await session.execute(
            select(Employee)
            .join(ClientManager, ClientManager.employee_id == Employee.id)
            .where(
                ClientManager.enterprise_id == enterprise_id,
                ClientManager.client_id == client_id,
            )
        )
    ).scalar_one_or_none()


async def employee_of(session: AsyncSession, enterprise_id: int, max_user_id: int) -> Employee | None:
    return (
        await session.execute(
            select(Employee).where(
                Employee.enterprise_id == enterprise_id, Employee.max_user_id == max_user_id
            )
        )
    ).scalars().first()


async def order_recipients(
    session: AsyncSession, enterprise_id: int, client_id: int | None
) -> dict[int, str]:
    """Кому писать о заявке клиента — и в какой роли: {user_id: роль}.

    Есть закреплённый менеджер — ему и владельцу: остальные видят заявку
    в общем списке, но сообщение о чужом клиенте для них шум. Нет — всем
    сотрудникам, как раньше: заявка не должна повиснуть без внимания.
    """
    staff = list(
        (
            await session.execute(select(Employee).where(Employee.enterprise_id == enterprise_id))
        ).scalars()
    )
    manager = (
        await personal_manager(session, enterprise_id, client_id) if client_id else None
    )
    chosen = (
        staff
        if manager is None
        else [row for row in staff if row.role is Role.owner or row.id == manager.id]
    )
    return {row.max_user_id: row.role.value for row in chosen}


@dataclass(frozen=True)
class Contact:
    """Сотрудник в окне «Связаться» у клиента."""
    id: int
    name: str
    role: str
    personal: bool
    on_shift: bool | None
    hours: str
    next: str
    phone: str
    phone_href: str
    chat_href: str
    # Ведёт заявку, из которой открыли «Связаться»
    handles_order: bool = False
    # Разрешил писать себе в MAX
    reachable: bool = True


async def contacts_for_client(
    session: AsyncSession,
    enterprise_id: int,
    client_id: int | None,
    order_manager_id: int | None = None,
) -> list[Contact]:
    """Кого показать клиенту: закреплённого менеджера и всех, кто указал
    график. Сверху — кто ведёт заявку (если окно открыли из неё), затем
    закреплённый, затем кто на смене, затем остальные.

    Без графика сотрудник в список не попадает: «позвоните Ивану» в его
    выходной — это обещание, которое продукт не выполнит. Исключение —
    закреплённый и ведущий заявку: их клиент уже знает по имени.
    """
    staff = list(
        (
            await session.execute(
                select(Employee)
                .where(Employee.enterprise_id == enterprise_id)
                .order_by(Employee.id)
            )
        ).scalars()
    )
    manager = (
        await personal_manager(session, enterprise_id, client_id) if client_id else None
    )
    known = await people(session, {row.max_user_id for row in staff})
    now = datetime.now(TZ)

    result: list[Contact] = []
    for employee in staff:
        personal = manager is not None and employee.id == manager.id
        handles = order_manager_id is not None and employee.id == order_manager_id
        if not personal and not handles and not has_schedule(employee):
            continue
        person = known.get(employee.max_user_id)
        phone = person.phone if person else ""
        shift = on_shift(employee, now)
        result.append(
            Contact(
                id=employee.id,
                name=display_name(employee, person),
                role=employee.role.value,
                personal=personal,
                on_shift=shift,
                hours=hours_text(employee),
                next="" if shift else next_shift_text(employee, now),
                phone=phone,
                phone_href=contact.phone_href(phone),
                chat_href=contact.user_chat(person.username if person else ""),
                handles_order=handles,
                reachable=person.max_reachable if person else True,
            )
        )

    # Ведущий заявку и закреплённый — первыми, затем кто на связи сейчас.
    result.sort(
        key=lambda row: (not row.handles_order, not row.personal, row.on_shift is not True)
    )
    return result


def parse_days_names(text: str) -> set[str]:
    return {WEEKDAYS[day] for day in parse_days(text)}
