"""Состояние тестовых баз 1С.

Базы живут в одном JSON-файле на диске: эмулятор перезапускается вместе
со стендом, а номенклатура, списания и созданные документы должны это
пережить — иначе после каждого деплоя поставщик заводил бы прайс заново.
"""

from __future__ import annotations

import json
import os
import pathlib
import secrets
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

PATH = pathlib.Path(os.environ.get("ONEC_STATE", "/data/bases.json"))
SEED = pathlib.Path(os.environ.get("ONEC_SEED", "/app/data.json"))

# Ключ демо-базы задаётся окружением: обе стороны стенда — эмулятор и api —
# должны знать его заранее, иначе после первого запуска демо пришлось бы
# вручную переносить сгенерированный ключ в настройки.
DEMO_KEY = os.environ.get("ONEC_DEMO_KEY", "demo.stand-demo-key")
# Служебный пользователь тестовых баз: 1С проверяет и имя, и пароль.
USER = os.environ.get("ONEC_USER", "exchange")

# С этими контрагентами база создаётся. Дальше список у каждой базы свой:
# поставщик заводит в кабинете контрагентов под своих магазинов и выбирает
# их в приложении при подключении клиента.
CONTRACTORS = ["Розничный покупатель (тест)", "Магазин «У дома» (тест)", "Кафе «Проверка» (тест)"]
CONTRACTOR_LIMIT = 150

# Ссылки в 1С — GUID. Прежние «a1f0-0001» переводятся в GUID один раз и
# всегда одинаково: заказы в базе ссылаются на них строками.
REF_NS = uuid.UUID("6f1d1a4e-2b9c-4c55-9a51-4a2d6a1c0e11")
GUID_LENGTH = 36


def as_guid(old: str) -> str:
    old = str(old or "")
    try:
        return str(uuid.UUID(old)) if len(old) == GUID_LENGTH else str(uuid.uuid5(REF_NS, f"item:{old}"))
    except ValueError:
        return str(uuid.uuid5(REF_NS, f"item:{old}"))


def upgrade(base: dict) -> bool:
    """Приводит базу, сохранённую прежним эмулятором, к нынешним правилам:
    GUID-ссылки, пользователь, «Номер по данным клиента». True — поменялось."""
    touched = False
    if not base.get("user"):
        base["user"] = USER
        touched = True
    # Прежде контрагенты были общими для всех баз — те же три остаются
    # у каждой, иначе заказы, выгруженные на них, не нашли бы ссылку.
    if "contractors" not in base:
        base["contractors"] = list(CONTRACTORS)
        touched = True
    moved: dict[str, str] = {}
    for item in base.get("items", []):
        new = as_guid(item["Ref_Key"])
        if new != item["Ref_Key"]:
            moved[item["Ref_Key"]] = new
            moved[str(item.get("Code") or "")] = new
            item["Ref_Key"] = new
            touched = True
    for doc in base.get("documents", []):
        if "ВнешнийКлюч" in doc and "НомерПоДаннымКлиента" not in doc:
            doc["НомерПоДаннымКлиента"] = doc["ВнешнийКлюч"]
            touched = True
        for line in doc.get("Товары") or []:
            key = str(line.get("Номенклатура_Key") or "")
            if key in moved:
                line["Номенклатура_Key"] = moved[key]
                touched = True
        for move in doc.get("Движения") or []:
            if move.get("ref") in moved:
                move["ref"] = moved[move["ref"]]
                touched = True
    return touched


def make_key(slug: str) -> str:
    """Ключ вида `база.секрет`.

    Адрес базы спрятан в самом ключе, поэтому при создании витрины
    достаточно одного поля: по префиксу находится база, остальное —
    пароль служебного пользователя.
    """
    return f"{slug}.{secrets.token_urlsafe(14)}"

_lock = threading.Lock()


class Refused(Exception):
    """Отказ кабинета: код ответа и текст для человека."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank(name: str, slug: str, items: list[dict] | None = None) -> dict:
    return {
        "slug": slug,
        "name": name,
        "key": DEMO_KEY if (slug == "demo" and DEMO_KEY) else make_key(slug),
        "user": USER,
        "created_at": now(),
        "items": items or [],
        "contractors": list(CONTRACTORS),
        "documents": [],
        "corrections": [],
        "writeoffs": [],
    }


def _seed_items() -> list[dict]:
    raw = json.loads(SEED.read_text(encoding="utf-8"))["Номенклатура"]
    return [{**row, "Ref_Key": as_guid(row["Ref_Key"])} for row in raw]


def load() -> dict:
    if PATH.exists():
        try:
            return json.loads(PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Первая база создаётся сразу: пустой экран без единой базы не объясняет,
    # что вообще делать дальше.
    state = {"bases": [_blank("Тестовая база «Демо»", "demo", _seed_items())]}
    save(state)
    return state


def save(state: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PATH)


class Store:
    """Тонкая обёртка: читает, меняет, сохраняет под замком."""

    def __init__(self) -> None:
        self._state = load()
        # База стенда всегда с ключом из окружения: том переживает деплой,
        # и старый случайный ключ иначе остался бы расходиться с настройкой api.
        demo = self.base("demo")
        touched = any([upgrade(base) for base in self.bases])
        if DEMO_KEY and demo and demo["key"] != DEMO_KEY:
            demo["key"] = DEMO_KEY
            touched = True
        if touched:
            self.commit()

    @property
    def bases(self) -> list[dict]:
        return self._state["bases"]

    def base(self, slug: str) -> dict | None:
        return next((row for row in self.bases if row["slug"] == slug), None)

    def by_key(self, key: str) -> dict | None:
        return next((row for row in self.bases if row["key"] == key), None)

    def commit(self) -> None:
        with _lock:
            save(self._state)

    # --- базы ---

    def create_base(self, name: str, copy_items: bool = True) -> dict:
        slug = f"base-{uuid.uuid4().hex[:6]}"
        base = _blank(name.strip()[:120] or "Без названия", slug,
                      _seed_items() if copy_items else [])
        self.bases.append(base)
        self.commit()
        return base

    def drop_base(self, slug: str) -> bool:
        base = self.base(slug)
        if not base or len(self.bases) <= 1:
            return False
        self.bases.remove(base)
        self.commit()
        return True

    def rotate_key(self, slug: str) -> str | None:
        base = self.base(slug)
        if not base:
            return None
        base["key"] = make_key(slug)
        self.commit()
        return base["key"]

    # --- контрагенты ---

    def add_contractor(self, slug: str, name: str) -> list[str]:
        """Новый контрагент базы; возвращает список контрагентов.

        Ссылка на контрагента выводится из названия, поэтому два одинаковых
        названия в одной базе были бы одним объектом — такое не заводим.
        """
        base = self.base(slug)
        if not base:
            raise Refused(404, "база не найдена")
        name = " ".join(str(name or "").split())
        if not name:
            raise Refused(422, "впишите название контрагента")
        if len(name) > CONTRACTOR_LIMIT:
            raise Refused(422, f"название длиннее {CONTRACTOR_LIMIT} знаков")
        same = next((row for row in base["contractors"] if row.casefold() == name.casefold()), None)
        if same is not None:
            raise Refused(409, f"контрагент «{same}» уже есть в этой базе")
        base["contractors"].append(name)
        self.commit()
        return base["contractors"]

    # --- номенклатура ---

    def add_item(self, slug: str, payload: dict) -> dict | None:
        base = self.base(slug)
        if not base:
            return None
        item = {
            "Ref_Key": str(uuid.uuid4()),
            "Code": str(payload.get("Code") or "").strip()[:40]
            or f"{len(base['items']) + 1:06d}",
            "Description": str(payload.get("Description") or "").strip()[:200],
            "ЕдиницаИзмерения": str(payload.get("ЕдиницаИзмерения") or "шт").strip()[:20],
            "Кратность": float(payload.get("Кратность") or 1),
            "Цена": float(payload.get("Цена") or 0),
            "Остаток": float(payload.get("Остаток") or 0),
        }
        base["items"].append(item)
        self.commit()
        return item

    def update_item(self, slug: str, ref: str, payload: dict) -> dict | None:
        base = self.base(slug)
        if not base:
            return None
        item = next((row for row in base["items"] if row["Ref_Key"] == ref), None)
        if not item:
            return None
        for field, cast in (
            ("Description", str), ("ЕдиницаИзмерения", str), ("Code", str),
            ("Кратность", float), ("Цена", float), ("Остаток", float),
        ):
            if field in payload and payload[field] is not None:
                item[field] = cast(payload[field])
        self.commit()
        return item

    def drop_item(self, slug: str, ref: str) -> bool:
        base = self.base(slug)
        if not base:
            return False
        before = len(base["items"])
        base["items"] = [row for row in base["items"] if row["Ref_Key"] != ref]
        self.commit()
        return len(base["items"]) < before

    def write_off(self, slug: str, ref: str, qty: float, reason: str) -> dict | None:
        """Списание: остаток уменьшается, факт остаётся в журнале.

        Списание — обычное дело на складе: бой, срок, пересорт. Без журнала
        остаток просто «сам меняется», и сверить его не с чем.
        """
        base = self.base(slug)
        if not base:
            return None
        item = next((row for row in base["items"] if row["Ref_Key"] == ref), None)
        if not item or qty <= 0:
            return None
        item["Остаток"] = round(max(0.0, float(item["Остаток"]) - qty), 3)
        record = {
            "at": now(),
            "Номенклатура": item["Description"],
            "Количество": qty,
            "Причина": reason.strip()[:120] or "без причины",
            "Остаток": item["Остаток"],
        }
        base["writeoffs"].insert(0, record)
        del base["writeoffs"][50:]
        self.commit()
        return record
