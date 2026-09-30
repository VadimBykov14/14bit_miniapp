"""Разбор прайс-листа из Excel или CSV.

Витрина без 1С ведётся вручную, и единственный формат, в котором у оптовика
уже лежит прайс, — это выгрузка в Excel. Поэтому разбор терпимый: колонки
ищутся по названию в любом порядке, лишние игнорируются, цена читается
и с запятой, и с пробелами внутри числа.

Файл разбирается целиком и отдельно от базы: сначала мы говорим, что
поняли и что не поняли, и только потом что-то меняем.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .spreadsheet import untext

# Синонимы колонок. Оптовик выгружает прайс из своей учётной системы и
# переименовывать шапку под нас не станет.
COLUMNS: dict[str, tuple[str, ...]] = {
    "external_id": ("артикул", "код", "код товара", "sku", "id"),
    "name": ("наименование", "название", "товар", "позиция", "номенклатура", "name"),
    "unit": ("единица", "ед", "ед. изм.", "ед.изм.", "единица измерения", "unit"),
    "pack_size": ("кратность", "упаковка", "уп", "в упаковке", "кратность упаковки", "pack"),
    "price": ("цена", "цена, руб", "стоимость", "price"),
    "stock": ("остаток", "количество", "кол-во", "наличие", "stock"),
}

MAX_ROWS = 5000


@dataclass
class Row:
    line: int
    name: str
    price: float
    external_id: str = ""
    unit: str | None = None
    pack_size: float | None = None
    stock: float | None = None


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


class PriceListError(Exception):
    """Файл не разобрать целиком: не та таблица или нет обязательных колонок."""


def _norm(value: object) -> str:
    return str(value if value is not None else "").strip().lower().rstrip(".")


def _map_header(cells: list[object]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(cells):
        key = _norm(cell)
        if not key:
            continue
        for field_name, synonyms in COLUMNS.items():
            if field_name in found:
                continue
            if key in synonyms or key.split(",")[0].strip() in synonyms:
                found[field_name] = index
                break
    return found


def _number(value: object) -> float | None:
    """«1 234,50» и «1234.5» — одно и то же число."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rows_from_xlsx(data: bytes) -> list[list[object]]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows = [list(row) for row in sheet.iter_rows(max_row=MAX_ROWS + 50, values_only=True)]
    workbook.close()
    return rows


def _rows_from_csv(data: bytes) -> list[list[object]]:
    # Excel в русской локали сохраняет CSV в cp1251 и с точкой с запятой.
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise PriceListError("не смог прочитать файл: неизвестная кодировка")

    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def parse(data: bytes, filename: str) -> Parsed:
    """Разбирает файл в строки прайса. Плохие строки не роняют хорошие."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        table = _rows_from_xlsx(data)
    elif lower.endswith((".csv", ".txt")):
        table = _rows_from_csv(data)
    elif lower.endswith(".xls"):
        raise PriceListError("старый формат .xls не читаем — сохраните как .xlsx или .csv")
    else:
        raise PriceListError("нужен файл .xlsx или .csv")

    header_at = None
    mapping: dict[str, int] = {}
    for index, cells in enumerate(table[:20]):
        candidate = _map_header(cells)
        if "name" in candidate and "price" in candidate:
            header_at, mapping = index, candidate
            break
    if header_at is None:
        raise PriceListError(
            "не нашёл шапку таблицы: нужны колонки «наименование» и «цена»"
        )

    parsed = Parsed()
    for offset, cells in enumerate(table[header_at + 1:], start=header_at + 2):
        if len(parsed.rows) >= MAX_ROWS:
            parsed.problems.append(f"строка {offset}: обрезано на {MAX_ROWS} позициях")
            break

        def cell(key: str) -> object:
            index = mapping.get(key)
            return cells[index] if index is not None and index < len(cells) else None

        # Выгрузка ставит апостроф перед «=», «+», «-» и «@», чтобы таблица не
        # приняла текст за формулу, — при загрузке его снимаем.
        name = untext(str(cell("name") or "").strip())
        if not name and not any(str(value or "").strip() for value in cells):
            continue  # пустая строка-разделитель
        if not name:
            parsed.problems.append(f"строка {offset}: нет наименования")
            continue

        price = _number(cell("price"))
        if price is None:
            # Строка-раздел вроде «Кондитерские изделия» — не ошибка, просто
            # не позиция. Ругаться на неё значит завалить отчёт шумом.
            continue
        if price <= 0:
            parsed.problems.append(f"строка {offset}: «{name[:40]}» — цена должна быть больше нуля")
            continue

        pack = _number(cell("pack_size"))
        stock = _number(cell("stock"))
        unit = untext(str(cell("unit") or "").strip()) or None

        parsed.rows.append(
            Row(
                line=offset,
                name=name[:300],
                price=round(price, 2),
                external_id=untext(str(cell("external_id") or "").strip())[:80],
                unit=unit[:20] if unit else None,
                pack_size=round(pack, 1) if pack and pack >= 0.1 else None,
                stock=round(stock, 1) if stock is not None and stock >= 0 else None,
            )
        )

    if not parsed.rows:
        raise PriceListError("в файле нет ни одной позиции с ценой")
    return parsed
