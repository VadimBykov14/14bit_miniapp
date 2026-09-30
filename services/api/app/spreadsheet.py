"""Ячейки таблиц, которые мы отдаём и принимаем: CSV для русского Excel.

Выгрузка заявок и прайс уходят в Excel и «Google Таблицы», прайс ещё и
возвращается обратно загрузкой. Правила ячеек у них общие, поэтому живут
здесь, а не в каждой выгрузке.
"""

from __future__ import annotations

import csv
import io

# С этих знаков Excel и «Google Таблицы» начинают формулу.
FORMULA_START = ("=", "+", "-", "@")


def text(value: object) -> str:
    """Текст для ячейки: одной строкой и без формулы.

    Ячейку, которая начинается с «=», «+», «-» или «@», таблица исполняет
    как формулу. Магазин с названием «=HYPERLINK(…)» срабатывал бы у
    владельца при открытии выгрузки, поэтому такой текст выводим с
    апострофом: таблица показывает его текстом.
    """
    cell = str("" if value is None else value).replace("\r", " ").replace("\n", " ").strip()
    return f"'{cell}" if cell.startswith(FORMULA_START) else cell


def untext(value: str) -> str:
    """Обратное к `text`: прайс, скачанный и загруженный обратно, не должен
    обрасти апострофами."""
    return value[1:] if value.startswith("'") and value[1:].startswith(FORMULA_START) else value


def table(header: tuple[str, ...], rows: list[list[str]]) -> str:
    """CSV для русского Excel. Кавычки ставит модуль csv: точка с запятой
    или кавычка внутри значения больше не разрывают строку."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM обязателен: без него Excel открывает кириллицу кракозябрами.
    return "\ufeff" + buffer.getvalue()
