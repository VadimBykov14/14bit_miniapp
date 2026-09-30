"""Разделы полки города: популярные, новые и все остальные.

Одним списком по алфавиту полка перестаёт читаться, как только витрин
больше десятка: к витрине, у которой двадцать магазинов, и к открытой
вчера — одинаковый путь. Популярность — число подключённых магазинов: её
нельзя накрутить без клиентов. Новые — последние открытые витрины: номер
растёт с каждой новой, отдельная дата для этого не нужна.
"""

from __future__ import annotations

POPULAR_LIMIT = 6
NEW_LIMIT = 6

# Порядок разделов на экране
ORDER = {"popular": 0, "new": 1, "all": 2}


def sections(ids: list[int], clients: dict[int, int]) -> dict[int, str]:
    """Раздел каждой витрины: popular, new или all. Витрина — только в одном:
    популярная не повторяется среди новых."""
    popular = sorted(
        (sid for sid in ids if clients.get(sid, 0) > 0),
        key=lambda sid: (-clients[sid], sid),
    )[:POPULAR_LIMIT]
    fresh = sorted((sid for sid in ids if sid not in popular), reverse=True)[:NEW_LIMIT]
    result = {sid: "all" for sid in ids}
    result.update({sid: "popular" for sid in popular})
    result.update({sid: "new" for sid in fresh})
    return result


def rank(section: str, storefront_id: int, clients: dict[int, int]) -> tuple:
    """Место на полке: популярные — по числу магазинов, новые — свежие
    первыми. Остальные сохраняют порядок запроса (город, название)."""
    if section == "popular":
        return (ORDER[section], -clients.get(storefront_id, 0), storefront_id)
    if section == "new":
        return (ORDER[section], -storefront_id)
    return (ORDER[section],)
