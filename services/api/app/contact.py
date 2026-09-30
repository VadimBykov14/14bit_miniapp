"""Куда ведёт кнопка «Связаться».

У поставщика два способа — профиль в MAX и телефон, оба можно заполнить,
а кнопка у клиента ведёт туда, куда он выбрал. Кнопка только перенаправляет:
сообщений от имени клиента она не отправляет, иначе каждое нажатие будило бы
сотрудников уведомлением «перезвоните».
"""

from __future__ import annotations

import re

KINDS = ("max", "phone")

# Длины колонок в базе: длиннее — честный отказ, а не ошибка записи.
PHONE_LIMIT = 40
LINK_LIMIT = 200

_PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{5,}$")
# Ник в MAX начинается с буквы: «89001234567» ником не бывает, и такой ввод —
# телефон, попавший не в то поле.
_NICK = re.compile(r"^@?([A-Za-z][A-Za-z0-9_.]{2,63})$")
# Личный профиль — https://max.ru/u/<код>, ник, канал или бот — https://max.ru/<ник>
_MAX_LINK = re.compile(r"^(?:https?://)?(?:www\.)?max\.ru/([^\s?#]+)", re.IGNORECASE)
# Ссылка посреди текста: «Поделиться» в MAX кладёт в буфер фразу вместе с
# адресом. Перед адресом — начало строки или пробел, иначе
# «https://evil.example/max.ru/u/x» сошла бы за профиль.
_MAX_IN_TEXT = re.compile(r"(?:^|\s)((?:https?://)?(?:www\.)?max\.ru/[^\s?#]+)", re.IGNORECASE)


class ContactError(ValueError):
    """Значение не годится для перехода — объяснение для поставщика."""


def phone_digits(value: str) -> str:
    """Одиннадцать цифр российского номера, начиная с 7; пусто — не номер.

    Восьмёрку в начале меняем на семёрку: так номер набирается с любой
    сим-карты. Иностранные номера не принимаем — поставщики и магазины
    здесь российские, а лишний формат — лишняя ошибка при звонке.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    return ""


def format_phone(digits: str) -> str:
    """79001234567 → «+7 (900) 123-45-67» — так номер видят везде."""
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def normalize_phone(value: str) -> str:
    """Номер по маске «+7 (900) 123-45-67». Пусто — «не указан»."""
    value = (value or "").strip()
    if not value:
        return ""
    digits = phone_digits(value) if len(value) <= PHONE_LIMIT and _PHONE.match(value) else ""
    if not digits:
        raise ContactError("телефон: российский номер из 11 цифр, например +7 (900) 123-45-67")
    return format_phone(digits)


def normalize_max(value: str) -> str:
    """Ссылка на профиль MAX в полном виде. Пусто — «не указан»."""
    value = (value or "").strip()
    if not value:
        return ""
    found = _MAX_IN_TEXT.search(value)
    link = _MAX_LINK.match(found.group(1) if found else value)
    if link:
        result = f"https://max.ru/{link.group(1)}"
        if len(result) > LINK_LIMIT:
            raise ContactError("ссылка слишком длинная — скопируйте её из MAX заново")
        return result
    nick = _NICK.match(value)
    if nick:
        return f"https://max.ru/{nick.group(1)}"
    if _PHONE.match(value):
        raise ContactError("это номер телефона — впишите его в поле «Телефон»")
    raise ContactError("нужна ссылка на профиль MAX вида https://max.ru/u/… или ник")


def normalize(kind: str, value: str) -> tuple[str, str]:
    """Проверяет контакт выбранного вида. Пустое значение — законный выбор
    «не указывать»: у клиента кнопка остаётся на месте, но неактивна."""
    value = (value or "").strip()
    if not value:
        return "", ""
    if kind == "phone":
        return "phone", normalize_phone(value)
    if kind == "max":
        return "max", normalize_max(value)
    raise ContactError("способ связи — max или phone")


def phone_href(value: str) -> str:
    """tel: с кодом страны: набор с сим-карты другой страны без него не пройдёт."""
    digits = phone_digits(value)
    return f"tel:+{digits}" if digits else ""


def href(kind: str, value: str) -> str:
    """Адрес для кнопки. Пустая строка — контакт не указан или битый."""
    try:
        kind, value = normalize(kind, value)
    except ContactError:
        return ""
    if kind == "max":
        return value
    if kind == "phone":
        return phone_href(value)
    return ""


def effective(kind: str, phone: str, max_link: str) -> tuple[str, str]:
    """Куда кнопка ведёт на самом деле: выбранный способ, а если его поле
    пустое — заполненный второй. Кнопка без адреса хуже кнопки «не туда»."""
    options = {"phone": phone or "", "max": max_link or ""}
    if options.get(kind):
        return kind, options[kind]
    for other in ("max", "phone"):
        if options[other]:
            return other, options[other]
    return "", ""


def user_chat(username: str | None) -> str:
    """Профиль человека в MAX по его публичному нику. Без ника ссылки нет:
    код вида /u/… из user_id не вычисляется."""
    nick = _NICK.match((username or "").strip())
    return f"https://max.ru/{nick.group(1)}" if nick else ""
