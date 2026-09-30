"""Эмулятор 1С:Предприятие 8 с интерфейсом OData и кабинетом настройки.

Это не «заглушка вместо интеграции», а вторая сторона того же контракта:
сервис отвечает по тем же адресам и теми же формами, что публикует
настоящая база через `/odata/standard.odata/`. Клиент в api не знает,
с кем говорит, и при переключении на боевую базу меняется только адрес
и учётные данные.

Баз несколько: у каждого предприятия своя, со своим ключом. Так на одном
стенде уживаются несколько поставщиков, и ключ одного не открывает
номенклатуру другого.

Что реализовано из стандартного интерфейса — так, как это устроено в
«Управлении торговлей 11.4»:

* справочники `Catalog_Номенклатура` (с группой и пометкой удаления),
  `Catalog_УпаковкиЕдиницыИзмерения`, `Catalog_Организации`,
  `Catalog_Склады`, `Catalog_ВидыЦен`, `Catalog_Валюты`, `Catalog_Партнеры`,
  `Catalog_Контрагенты`, `Catalog_СоглашенияСКлиентами`;
* `InformationRegister_ЦеныНоменклатуры/SliceLast()` — цены по видам;
* `AccumulationRegister_СвободныеОстатки/Balance()` — свободный остаток
  (ресурс «В наличии») по складу;
* `Document_ЗаказКлиента` — запись, поиск по «Номеру по данным клиента»,
  правка (`PATCH`), проведение (`/Post`) и отмена проведения (`/Unpost`).

Проведённый в рабочем статусе заказ резервирует товар: остаток
уменьшается на то, что удалось зарезервировать, и ровно это возвращается
при отмене проведения. «На согласовании» не резервирует — как в УТ.

Данные синтетические и помечены как тестовые — требование брифа.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import pathlib
import re
import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from store import USER, Refused, Store, now

app = FastAPI(title="mock-1c", docs_url=None, redoc_url=None)
store = Store()
log = logging.getLogger("mock-1c")

# Куда сообщать, что в базе что-то поменялось. Настоящая 1С делает это
# планом обмена или HTTP-сервисом; здесь — одним запросом. Пусто — молчим,
# и витрина узнает об изменении фоновым проходом.
NOTIFY_URL = os.environ.get("ONEC_NOTIFY_URL", "http://api:8080/internal/onec/changed")
_pending: set[asyncio.Task] = set()


async def _notify(slug: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(NOTIFY_URL, json={"base": slug})
    except httpx.HTTPError as exc:
        log.warning("не сообщил об изменении базы %s: %s", slug, exc)


def changed(slug: str) -> None:
    """Остатки или номенклатура базы изменились — сообщаем витрине, не
    задерживая ответ: она сама придёт за свежими данными по OData."""
    if not NOTIFY_URL:
        return
    task = asyncio.create_task(_notify(slug))
    _pending.add(task)
    task.add_done_callback(_pending.discard)

UI = pathlib.Path(__file__).with_name("ui.html")
UI_SCRIPT = pathlib.Path(__file__).with_name("ui.js")

# Кабинет открыт без входа и показывает названия магазинов и позиций, которые
# вписывают люди. Скрипты — только свой файл, без встроенных: разметка в
# названии ничего не запустит. Встроить кабинет в чужую страницу нельзя.
CABINET_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def odata(values: list[dict]) -> JSONResponse:
    """Обёртка ответа OData: 1С отдаёт коллекцию в поле `value`."""
    return JSONResponse({"odata.metadata": "mock", "value": values})


def refuse(status: int, message: str) -> HTTPException:
    """Отказ в той форме, в какой его отдаёт 1С: `odata.error` с текстом."""
    return HTTPException(
        status_code=status,
        detail={"odata.error": {"code": "-1", "message": {"lang": "ru", "value": message}}},
    )


@app.exception_handler(HTTPException)
async def odata_errors(request: Request, exc: HTTPException) -> JSONResponse:
    # Отказы OData — телом 1С, остальное — как у FastAPI.
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


def authorize(slug: str, authorization: str | None) -> dict:
    """Базовая аутентификация — ровно та, что включается в конфигураторе
    галочкой «Публиковать OData» и служебным пользователем. Проверяются и
    имя пользователя, и пароль: настоящая 1С чужое имя не пустит."""
    base = store.base(slug)
    if not base:
        raise HTTPException(status_code=404, detail="база не опубликована")
    if not authorization or not authorization.lower().startswith("basic "):
        raise HTTPException(
            status_code=401, detail="нужна базовая аутентификация",
            headers={"WWW-Authenticate": "Basic"},
        )
    try:
        raw = base64.b64decode(authorization.split(" ", 1)[1]).decode()
        user, _, password = raw.partition(":")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="не разобрал заголовок") from exc
    # Сравниваем байты: compare_digest на строке с кириллицей бросает
    # TypeError, и неверный ключ отвечал бы 500 вместо честного 401.
    right_user = secrets.compare_digest(user.encode(), str(base.get("user") or USER).encode())
    right_key = secrets.compare_digest(password.encode(), base["key"].encode())
    if not (right_user and right_key):
        raise HTTPException(status_code=401, detail="неверное имя пользователя или ключ подключения")
    return base


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "bases": len(store.bases)}


# --- OData ---
#
# Строгость — как у настоящей базы, а не как удобно клиенту: эмулятор,
# который принимает то, что 1С отклонит, прятал ошибки до первого
# подключения реальной базы.
#
# * виртуальные таблицы — только со скобками: SliceLast(), Balance();
# * ссылки — только GUID в полях <Имя>_Key, и объект по ссылке должен быть;
# * $select и $filter — по существующим полям, иначе 400;
# * запись документа его не проводит, проведение — /Post; при проведении
#   проверяются обязательные реквизиты;
# * «На согласовании» проведение движений не делает и не резервирует.

GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
REF_NS = uuid.UUID("6f1d1a4e-2b9c-4c55-9a51-4a2d6a1c0e11")


def ref(kind: str, name: str) -> str:
    """Постоянная ссылка справочника: одна и та же между перезапусками."""
    return str(uuid.uuid5(REF_NS, f"{kind}:{name}"))


# Справочники тестовой базы — синтетические, помечены тестовыми.
ORGANIZATIONS = ["ООО «Тестовая организация»"]
WAREHOUSES = ["Основной склад", "Склад №2 (пустой)"]
PRICE_KINDS = ["Оптовая", "Розничная"]
CURRENCIES = ["руб."]
AGREEMENTS = ["Основное соглашение (тест)"]
STATUSES = {"НеСогласован", "КОбеспечению", "КВыполнению", "КОтгрузке", "Закрыт"}
# Реквизиты, без которых «Заказ клиента» в УТ не проведётся.
REQUIRED = {
    "Организация_Key": "Организация", "Партнер_Key": "Партнер", "Контрагент_Key": "Контрагент",
    "Склад_Key": "Склад", "Валюта_Key": "Валюта", "ХозяйственнаяОперация": "Хозяйственная операция",
}
ORDER = "Document_ЗаказКлиента"
EXTERNAL = "НомерПоДаннымКлиента"


def _catalog(kind: str, names: list[str], **extra) -> list[dict]:
    return [
        {"Ref_Key": ref(kind, name), "Description": name, "DeletionMark": False,
         **{k: v(name) for k, v in extra.items()}}
        for name in names
    ]


def _units(base: dict) -> list[dict]:
    names = sorted({str(item.get("ЕдиницаИзмерения") or "шт") for item in base["items"]} | {"шт", "кг"})
    return _catalog("unit", names)


def catalogs(base: dict) -> dict[str, list[dict]]:
    """Все справочники базы в том виде, в каком их отдаёт OData."""
    unit_by_name = {row["Description"]: row["Ref_Key"] for row in _units(base)}
    nomenclature = [
        # Группа справочника: в витрину попасть не должна.
        {"Ref_Key": ref("folder", "Кондитерские изделия"), "Code": "", "IsFolder": True,
         "Description": "Кондитерские изделия (группа)", "DeletionMark": False,
         "ЕдиницаИзмерения_Key": "00000000-0000-0000-0000-000000000000"},
    ] + [
        {
            "Ref_Key": item["Ref_Key"],
            "Code": item["Code"],
            "Description": item["Description"],
            "IsFolder": False,
            "DeletionMark": bool(item.get("DeletionMark")),
            "ЕдиницаИзмерения_Key": unit_by_name.get(str(item.get("ЕдиницаИзмерения") or "шт")),
        }
        for item in base["items"]
    ]
    return {
        "Catalog_Номенклатура": nomenclature,
        "Catalog_УпаковкиЕдиницыИзмерения": _units(base),
        "Catalog_Организации": _catalog("org", ORGANIZATIONS),
        "Catalog_Склады": _catalog("warehouse", WAREHOUSES, IsFolder=lambda _: False),
        "Catalog_ВидыЦен": _catalog("price", PRICE_KINDS),
        "Catalog_Валюты": _catalog("currency", CURRENCIES),
        # Контрагенты у каждой базы свои, заводятся в кабинете. Партнёр — по
        # одному на контрагента, с тем же названием: так их заводят в УТ
        # для небольших магазинов.
        "Catalog_Партнеры": _catalog("partner", base["contractors"]),
        "Catalog_Контрагенты": _catalog(
            "contractor", base["contractors"], Партнер_Key=lambda name: ref("partner", name)
        ),
        "Catalog_СоглашенияСКлиентами": _catalog("agreement", AGREEMENTS),
    }


# Ссылочные поля заказа и справочник, где должен найтись объект.
REF_FIELDS = {
    "Организация_Key": "Catalog_Организации", "Партнер_Key": "Catalog_Партнеры",
    "Контрагент_Key": "Catalog_Контрагенты", "Склад_Key": "Catalog_Склады",
    "Валюта_Key": "Catalog_Валюты", "Соглашение_Key": "Catalog_СоглашенияСКлиентами",
}

_CONDITION = re.compile(r"""(\w+)\s+eq\s+(guid'[0-9A-Za-z-]+'|'(?:[^']|'')*'|true|false|-?\d+(?:\.\d+)?)""")


def _conditions(text: str) -> list[tuple[str, object]]:
    """Разбор отбора вида `Поле eq значение and …` — того, что шлёт клиент."""
    text = text.strip()
    if not text:
        return []
    parts = [part for part in re.split(r"\s+and\s+", text) if part]
    result = []
    for part in parts:
        match = _CONDITION.fullmatch(part.strip())
        if not match:
            raise refuse(400, f"Неверный формат отбора: {part}")
        field, raw = match.groups()
        if raw.startswith("guid'"):
            value: object = raw[5:-1]
            if not GUID.match(str(value)):
                raise refuse(400, f"Неверное значение ссылки: {raw}")
        elif raw.startswith("'"):
            value = raw[1:-1].replace("''", "'")
        elif raw in ("true", "false"):
            value = raw == "true"
        else:
            value = float(raw)
        result.append((field, value))
    return result


def _apply(rows: list[dict], where: list[tuple[str, object]], fields: set[str]) -> list[dict]:
    for field, _ in where:
        if field not in fields:
            raise refuse(400, f"Поле «{field}» не найдено")
    return [row for row in rows if all(row.get(field) == value for field, value in where)]


def _select(rows: list[dict], select: str, fields: set[str]) -> list[dict]:
    if not select:
        return rows
    wanted = [name.strip() for name in select.split(",") if name.strip()]
    for name in wanted:
        if name not in fields:
            raise refuse(400, f"Поле «{name}» не найдено")
    return [{name: row.get(name) for name in wanted} for row in rows]


def _query(rows: list[dict], request: Request, fields: set[str] | None = None) -> JSONResponse:
    known = fields or (set().union(*(row.keys() for row in rows)) if rows else set())
    where = _conditions(request.query_params.get("$filter", ""))
    return odata(_select(_apply(rows, where, known), request.query_params.get("$select", ""), known))


def _virtual(target: str, name: str) -> list[tuple[str, object]] | None:
    """`Регистр/Balance(Condition='…')` → условия отбора; не та таблица — None.
    Без скобок 1С такой объект не знает — и эмулятор тоже."""
    match = re.fullmatch(rf"{re.escape(name)}\((.*)\)", target, re.DOTALL)
    if not match:
        return None
    inside = match.group(1).strip()
    if not inside:
        return []
    condition = re.fullmatch(r"Condition='(.*)'", inside, re.DOTALL)
    if not condition:
        raise refuse(400, f"Неверные параметры виртуальной таблицы: {inside}")
    return _conditions(condition.group(1))


_ONE = re.compile(r"^" + ORDER + r"\(guid'([0-9A-Za-z-]+)'\)$")


def _order_by_ref(base: dict, target: str) -> dict:
    match = _ONE.match(target)
    if not match:
        raise refuse(404, f"Объект {target} не найден")
    doc = next((row for row in base["documents"] if row["Ref_Key"] == match.group(1)), None)
    if doc is None:
        raise refuse(404, "Документ не найден")
    return doc


def _order_view(doc: dict) -> dict:
    """Документ в выдаче: служебные поля эмулятора наружу не идут."""
    return {k: v for k, v in doc.items() if k not in ("Движения", "Проведён")} | {
        "Posted": bool(doc.get("Проведён")),
    }


@app.get("/{slug}/odata/standard.odata/{target:path}")
async def read(
    slug: str, target: str, request: Request, authorization: str | None = Header(default=None)
) -> JSONResponse:
    base = authorize(slug, authorization)
    known = catalogs(base)
    if target in known:
        return _query(known[target], request)

    prices = _virtual(target, "InformationRegister_ЦеныНоменклатуры/SliceLast")
    if prices is not None:
        rows = [
            {
                "Period": base["created_at"],
                "Номенклатура_Key": item["Ref_Key"],
                "ВидЦены_Key": ref("price", kind),
                "Цена": round(float(item["Цена"]) * (1.25 if kind == "Розничная" else 1), 2),
            }
            for item in base["items"]
            for kind in PRICE_KINDS
        ]
        return odata(_apply(rows, prices, {"Номенклатура_Key", "ВидЦены_Key"}))

    balance = _virtual(target, "AccumulationRegister_СвободныеОстатки/Balance")
    if balance is not None:
        rows = [
            {
                "Номенклатура_Key": item["Ref_Key"],
                "Склад_Key": ref("warehouse", WAREHOUSES[0]),
                "ВНаличииBalance": float(item["Остаток"]),
            }
            for item in base["items"]
        ]
        return odata(_apply(rows, balance, {"Номенклатура_Key", "Склад_Key"}))

    if target == ORDER:
        rows = [_order_view(doc) for doc in base["documents"]]
        fields = {"Ref_Key", "Number", "Date", "Posted", "DeletionMark", "Комментарий", EXTERNAL,
                  "Статус", "Контрагент_Key", "ДатаОтгрузки"}
        return _query(rows, request, fields)
    if _ONE.match(target):
        return JSONResponse(_order_view(_order_by_ref(base, target)))
    raise refuse(404, f"Объект {target} не найден")


def _check_refs(base: dict, payload: dict) -> None:
    """Ссылка — GUID существующего объекта, как проверяет 1С при записи."""
    known = catalogs(base)
    for field, catalog in REF_FIELDS.items():
        if field not in payload:
            continue
        value = str(payload[field] or "")
        if not GUID.match(value):
            raise refuse(400, f"Неверное значение ссылки в поле «{field}»: {value}")
        if not any(row["Ref_Key"] == value for row in known[catalog]):
            raise refuse(400, f"Объект не найден по ссылке в поле «{field}»")
    if "Статус" in payload and payload["Статус"] not in STATUSES:
        raise refuse(400, f"Недопустимое значение перечисления «Статус»: {payload['Статус']}")
    items = {item["Ref_Key"] for item in base["items"]}
    for line in payload.get("Товары") or []:
        value = str(line.get("Номенклатура_Key") or "")
        if not GUID.match(value) or value not in items:
            raise refuse(400, f"Номенклатура не найдена по ссылке: {value}")


def _contractor_name(base: dict, key: str) -> str:
    return next(
        (row["Description"] for row in catalogs(base)["Catalog_Контрагенты"] if row["Ref_Key"] == key),
        "",
    )


def _take(base: dict, lines: list[dict]) -> list[dict]:
    """Резерв по строкам заказа: сколько удалось взять с остатка. Запоминаем
    взятое, а не заказанное: отмена вернёт ровно то, что забрали."""
    items = {item["Ref_Key"]: item for item in base["items"]}
    moves = []
    for line in lines:
        item = items.get(str(line.get("Номенклатура_Key") or ""))
        if not item:
            continue
        want = float(line.get("Количество", 0) or 0)
        took = round(min(max(0.0, float(item["Остаток"])), max(0.0, want)), 3)
        item["Остаток"] = round(float(item["Остаток"]) - took, 3)
        moves.append({"ref": item["Ref_Key"], "qty": took})
    return moves


def _give_back(base: dict, moves: list[dict]) -> None:
    items = {row["Ref_Key"]: row for row in base["items"]}
    for move in moves:
        item = items.get(move["ref"])
        if item:
            item["Остаток"] = round(float(item["Остаток"]) + float(move["qty"]), 3)


def _unpost(base: dict, doc: dict) -> None:
    """Отмена проведения: резерв возвращается на склад."""
    if not doc.get("Проведён"):
        return
    _give_back(base, doc.get("Движения") or [])
    doc["Движения"] = []
    doc["Проведён"] = False


def _post(base: dict, doc: dict) -> None:
    """Проведение: обязательные реквизиты, затем резерв по строкам. Заказ
    «На согласовании» проводится без движений — товар не резервирует."""
    empty = [title for field, title in REQUIRED.items() if not doc.get(field)]
    if empty:
        raise refuse(400, f"Не заполнено поле «{empty[0]}»")
    if not doc.get("Товары"):
        raise refuse(400, "Не заполнена табличная часть «Товары»")
    _unpost(base, doc)
    doc["Движения"] = [] if doc.get("Статус") == "НеСогласован" else _take(base, doc["Товары"])
    doc["Проведён"] = True


WRITABLE = (
    "Организация_Key", "Партнер_Key", "Контрагент_Key", "Склад_Key", "Валюта_Key",
    "Соглашение_Key", "ХозяйственнаяОперация", "Статус", "Комментарий", "ДатаОтгрузки",
    "Товары", "DeletionMark", EXTERNAL,
)


@app.post("/{slug}/odata/standard.odata/{target:path}")
async def write(
    slug: str, target: str, request: Request, authorization: str | None = Header(default=None)
) -> JSONResponse:
    base = authorize(slug, authorization)
    action = re.fullmatch(r"(.+)/(Post|Unpost)", target)
    if action:
        doc = _order_by_ref(base, action.group(1))
        if action.group(2) == "Post":
            _post(base, doc)
        else:
            _unpost(base, doc)
        changed(slug)
        store.commit()
        return JSONResponse(_order_view(doc))
    if target != ORDER:
        raise refuse(404, f"Объект {target} не найден")

    payload = await request.json()
    _check_refs(base, payload)
    # Запись документа его не проводит: остаток не меняется до /Post.
    document = {
        "Ref_Key": str(uuid.uuid4()),
        "Number": f"ЗК-{len(base['documents']) + 1:06d}",
        "Date": now(),
        **{field: payload[field] for field in WRITABLE if field in payload},
        "Статус": str(payload.get("Статус") or "НеСогласован"),
        "Контрагент": _contractor_name(base, str(payload.get("Контрагент_Key") or "")),
        "Проведён": False,
        "Движения": [],
        "DeletionMark": False,
        "Товары": payload.get("Товары") or [],
    }
    base["documents"].insert(0, document)
    store.commit()
    return JSONResponse(_order_view(document), status_code=201)


@app.patch("/{slug}/odata/standard.odata/{target:path}")
async def patch(
    slug: str, target: str, request: Request, authorization: str | None = Header(default=None)
) -> JSONResponse:
    """Правка заказа. Как в 1С, остаток правка не трогает — его меняет
    перепроведение (`/Post`)."""
    base = authorize(slug, authorization)
    doc = _order_by_ref(base, target)
    payload = await request.json()
    _check_refs(base, payload)
    for field in WRITABLE:
        if field in payload:
            doc[field] = payload[field]
    if "Контрагент_Key" in payload:
        doc["Контрагент"] = _contractor_name(base, str(payload["Контрагент_Key"]))
    store.commit()
    return JSONResponse(_order_view(doc))


# --- кабинет ---


@app.get("/1c", response_class=HTMLResponse)
@app.get("/1c/", response_class=HTMLResponse)
async def cabinet() -> HTMLResponse:
    return HTMLResponse(
        UI.read_text(encoding="utf-8"), headers={"Content-Security-Policy": CABINET_CSP}
    )


@app.get("/1c/ui.js")
async def cabinet_script() -> Response:
    return Response(
        UI_SCRIPT.read_text(encoding="utf-8"),
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


def _public(base: dict, secret: bool = False) -> dict:
    """Что показываем в кабинете. Ключ отдаём только по прямому запросу."""
    return {
        "slug": base["slug"],
        "name": base["name"],
        "created_at": base["created_at"],
        "items": len(base["items"]),
        "contractors": len(base["contractors"]),
        "documents": len(base["documents"]),
        "corrections": len(base["corrections"]),
        **({"key": base["key"]} if secret else {}),
    }


@app.get("/1c/api/bases")
async def list_bases() -> dict:
    return {"bases": [_public(base) for base in store.bases]}


@app.post("/1c/api/bases")
async def add_base(payload: dict) -> dict:
    base = store.create_base(
        str(payload.get("name") or ""), bool(payload.get("copy_items", True))
    )
    return _public(base, secret=True)


@app.delete("/1c/api/bases/{slug}")
async def remove_base(slug: str) -> dict:
    if not store.drop_base(slug):
        raise HTTPException(status_code=409, detail="последнюю базу удалить нельзя")
    return {"deleted": True}


@app.get("/1c/api/bases/{slug}")
async def base_detail(slug: str, request: Request) -> dict:
    base = store.base(slug)
    if not base:
        raise HTTPException(status_code=404, detail="база не найдена")
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return {
        **_public(base, secret=True),
        # Адрес для подключения — тот же, по которому открыт кабинет:
        # из мини-приложения база видна по внутреннему имени, а человеку
        # нужен тот, что он видит в браузере.
        "url": f"{scheme}://{host}/1c/{base['slug']}",
        "internal_url": f"http://mock-1c:8080/{base['slug']}",
        "items": base["items"],
        "contractors": catalogs(base)["Catalog_Контрагенты"],
        "user": base.get("user") or USER,
        "documents": base["documents"][:20],
        "corrections": base["corrections"][:20],
        "writeoffs": base["writeoffs"][:20],
    }


@app.post("/1c/api/bases/{slug}/key")
async def new_key(slug: str) -> dict:
    key = store.rotate_key(slug)
    if key is None:
        raise HTTPException(status_code=404, detail="база не найдена")
    return {"key": key}


@app.post("/1c/api/bases/{slug}/items")
async def add_item(slug: str, payload: dict) -> dict:
    item = store.add_item(slug, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="база не найдена")
    changed(slug)
    return item


@app.post("/1c/api/bases/{slug}/contractors", status_code=201)
async def add_contractor(slug: str, payload: dict) -> dict:
    """Контрагент для заказов этой базы. В приложении он появится в списке
    выбора сам: справочник читается по OData при каждом открытии."""
    try:
        store.add_contractor(slug, str(payload.get("name") or ""))
    except Refused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"contractors": catalogs(store.base(slug))["Catalog_Контрагенты"]}


@app.patch("/1c/api/bases/{slug}/items/{ref}")
async def edit_item(slug: str, ref: str, payload: dict) -> dict:
    item = store.update_item(slug, ref, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    changed(slug)
    return item


@app.delete("/1c/api/bases/{slug}/items/{ref}")
async def remove_item(slug: str, ref: str) -> dict:
    if not store.drop_item(slug, ref):
        raise HTTPException(status_code=404, detail="позиция не найдена")
    changed(slug)
    return {"deleted": True}


@app.post("/1c/api/bases/{slug}/items/{ref}/write-off")
async def write_off(slug: str, ref: str, payload: dict) -> dict:
    record = store.write_off(
        slug, ref, float(payload.get("qty") or 0), str(payload.get("reason") or "")
    )
    if record is None:
        raise HTTPException(status_code=422, detail="нечего списывать")
    changed(slug)
    return record
