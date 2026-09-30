"""Свободный текст от человека: описание позиции, комментарий к заявке.

Описание показывается с переносами строк, и двадцать пустых строк подряд
растягивали карточку товара на весь экран — внизу оставался одинокий
дефис. Поэтому пустые строки схлопываются, число строк ограничено, а
лишнее не пропадает: хвост дописывается в последнюю строку через пробел.
"""

from __future__ import annotations

import re

# Пробелы, табуляции и неразрывные пробелы подряд — один пробел.
_SPACES = re.compile(r"[ \t\u00a0]+")

# Описание позиции — абзац о товаре, а не карточка маркетплейса.
DESCRIPTION_LIMIT = 500
DESCRIPTION_LINES = 8
# Комментарий уезжает в документ 1С и в сообщение в MAX.
COMMENT_LIMIT = 300
COMMENT_LINES = 4


def tidy(value: str | None, limit: int, max_lines: int) -> str:
    lines = [
        _SPACES.sub(" ", line).strip()
        for line in (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    kept: list[str] = []
    for line in lines:
        # Одна пустая строка — абзац, две и больше — просто пустое место.
        if not line and (not kept or not kept[-1]):
            continue
        kept.append(line)
    while kept and not kept[-1]:
        kept.pop()
    if len(kept) > max_lines:
        tail = " ".join(line for line in kept[max_lines - 1:] if line)
        kept = kept[: max_lines - 1] + [tail]
    return "\n".join(kept)[:limit].rstrip()


def description(value: str | None) -> str:
    return tidy(value, DESCRIPTION_LIMIT, DESCRIPTION_LINES)


def comment(value: str | None) -> str:
    return tidy(value, COMMENT_LIMIT, COMMENT_LINES)
