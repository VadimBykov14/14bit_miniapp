"""Выбор города из списка.

Город поставщика решает, на какой полке окажется его витрина: «Кинешма»,
«кинешма» и «Кинешма, Ивановская обл.» — три разные полки. Поэтому город
выбирают из справочника, а не вписывают.

Справочник — открытое API hh.ru: бесплатное, без ключа, с подсказками по
началу названия и с областью у каждого города. Запрос идёт через наш
сервер: так у мини-приложения один адрес, ответы кэшируются, а если
справочник недоступен, остаётся встроенный список крупных городов.
"""

from __future__ import annotations

import logging
import re
import time

import httpx
from fastapi import APIRouter, Depends

from ..auth import Identity, current_identity
from ..schemas import CityOut

router = APIRouter()
log = logging.getLogger("api")

SUGGEST_URL = "https://api.hh.ru/suggests/areas"
# hh.ru просит представляться: запросы без названия приложения он режет.
USER_AGENT = "max26-storefront/1.0"
TIMEOUT = 4.0
# Справочник городов не меняется за день — кэш на сутки, не больше 500 запросов.
TTL = 24 * 3600
CACHE_LIMIT = 500
_cache: dict[str, tuple[float, list[CityOut]]] = {}

RUSSIA = "Россия"
# Регион, а не город: «Московская область», «Пермский край», «Республика Татарстан».
_REGION = re.compile(
    r"(област|край$|округ|^республика|республика$|автономн)", re.IGNORECASE
)
# «Подольск (Московская область)» — область в скобках дублирует родителя.
_TAIL = re.compile(r"\s*\([^)]*\)\s*$")

# Если справочник недоступен: крупные города и город демо-стенда.
FALLBACK = [
    ("Москва", ""), ("Санкт-Петербург", ""), ("Новосибирск", "Новосибирская область"),
    ("Екатеринбург", "Свердловская область"), ("Казань", "Республика Татарстан"),
    ("Нижний Новгород", "Нижегородская область"), ("Челябинск", "Челябинская область"),
    ("Самара", "Самарская область"), ("Омск", "Омская область"),
    ("Ростов-на-Дону", "Ростовская область"), ("Уфа", "Республика Башкортостан"),
    ("Красноярск", "Красноярский край"), ("Воронеж", "Воронежская область"),
    ("Пермь", "Пермский край"), ("Волгоград", "Волгоградская область"),
    ("Краснодар", "Краснодарский край"), ("Саратов", "Саратовская область"),
    ("Тюмень", "Тюменская область"), ("Ижевск", "Удмуртская Республика"),
    ("Барнаул", "Алтайский край"), ("Ульяновск", "Ульяновская область"),
    ("Иркутск", "Иркутская область"), ("Хабаровск", "Хабаровский край"),
    ("Ярославль", "Ярославская область"), ("Владивосток", "Приморский край"),
    ("Томск", "Томская область"), ("Оренбург", "Оренбургская область"),
    ("Кемерово", "Кемеровская область"), ("Рязань", "Рязанская область"),
    ("Тверь", "Тверская область"), ("Тула", "Тульская область"),
    ("Иваново", "Ивановская область"), ("Кинешма", "Ивановская область"),
    ("Кострома", "Костромская область"), ("Владимир", "Владимирская область"),
    ("Калуга", "Калужская область"), ("Смоленск", "Смоленская область"),
    ("Сочи", "Краснодарский край"), ("Калининград", "Калининградская область"),
    ("Севастополь", ""),
]


# Столько знаков помещается в Enterprise.city.
CITY_LIMIT = 120


class CityError(ValueError):
    """Город не годится — объяснение для владельца."""


def one_city(value: str) -> str:
    """Город поставщика — один: по нему витрина стоит на полке.

    Список через запятую не принимаем: полка ищет по точному городу и не
    нашла бы витрину ни по одному из них. Обрезать длинное тоже нельзя —
    обрезанный город был бы уже другой полкой, поэтому отказ.
    """
    city = " ".join((value or "").split())
    if "," in city or len(city) > CITY_LIMIT:
        raise CityError("выберите один город из списка")
    return city


def _fallback(query: str) -> list[CityOut]:
    needle = query.strip().lower()
    return [
        CityOut(name=name, region=region)
        for name, region in FALLBACK
        if name.lower().startswith(needle)
    ][:10]


def _country(item: dict) -> str:
    node = item
    while node.get("parent"):
        node = node["parent"]
    return str(node.get("text") or "")


def parse(payload: dict, query: str = "") -> list[CityOut]:
    """Города России из ответа справочника, без областей и стран.

    Справочник находит и сёла, совпавшие только областью: на «Иван» —
    Родники Ивановской области. Такие уходят, если есть города с набранным
    в названии; сначала — те, что с него начинаются.
    """
    result: list[CityOut] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("items") or []:
        text = str(item.get("text") or "").strip()
        parent = item.get("parent") or {}
        if not text or _country(item) != RUSSIA or text == RUSSIA:
            continue
        name = _TAIL.sub("", text).strip()
        if _REGION.search(name):
            continue
        region = str(parent.get("text") or "")
        region = "" if region == RUSSIA else region
        key = (name, region)
        if key in seen:
            continue
        seen.add(key)
        result.append(CityOut(name=name, region=region))
    needle = query.strip().lower()
    if needle:
        named = [row for row in result if needle in row.name.lower()]
        if named:
            named.sort(key=lambda row: not row.name.lower().startswith(needle))
            result = named
    return result[:8]


@router.get("/cities", response_model=list[CityOut])
async def cities(
    q: str = "",
    identity: Identity = Depends(current_identity),
) -> list[CityOut]:
    query = q.strip()[:60]
    if len(query) < 2:
        return []
    key = query.lower()
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < TTL:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(SUGGEST_URL, params={"text": query})
            response.raise_for_status()
            found = parse(response.json(), query)
    except (httpx.HTTPError, ValueError) as exc:
        # Справочник лёг — не ломаем форму: крупные города есть и так.
        log.warning("справочник городов недоступен: %s", exc)
        return _fallback(query)

    if len(_cache) >= CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (now, found)
    return found
