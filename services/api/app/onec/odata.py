"""Клиент стандартного OData-интерфейса «1С:Предприятие 8».

Транспорт выбран потому, что включается в конфигураторе галочкой и не
требует доработки конфигурации: внедрение не упирается в программиста 1С
у каждого поставщика. Правила — как у настоящей базы, а не как удобно
эмулятору (см. docs/1c-connection.md):

* виртуальные таблицы вызываются со скобками — `SliceLast()`, `Balance()`,
  отбор по виду цен и складу передаётся в их параметре `Condition`;
* ссылки — только GUID в полях `<Имя>_Key`, строкой 1С ссылку не примет;
* справочник читается с `$select` и `$filter`: без групп (`IsFolder`) и
  помеченных на удаление (`DeletionMark`), а не весь целиком;
* строки в `$filter` экранируются удвоением кавычки — так требует OData;
* заказ ищется по стандартному реквизиту «Номер по данным клиента» —
  конфигурацию дорабатывать не нужно;
* запись документа его не проводит: проведение — отдельный вызов `/Post`.

Имена объектов, организация, склад и вид цен — настройка витрины
(settings.py). Базу стенда из окружения по-прежнему можно задать
переменными `ONEC_URL`, `ONEC_USER`, `ONEC_PASSWORD`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from .address import PublicTransport
from .contract import CatalogItem, Document, OneCUnavailable
from .settings import OneCSettings

log = logging.getLogger("onec")

BASE_URL = os.environ.get("ONEC_URL", "")
USER = os.environ.get("ONEC_USER", "")
PASSWORD = os.environ.get("ONEC_PASSWORD", "")
TIMEOUT = float(os.environ.get("ONEC_TIMEOUT", "15"))
# Вид цен базы стенда, пока витрина не выбрала свой.
PRICE_KIND = os.environ.get("ONEC_PRICE_KIND", "Оптовая")

# Потолок ответа. Номенклатура на пять тысяч позиций — пара мегабайт; сервер,
# который шлёт гигабайты, иначе съел бы память стенда.
MAX_RESPONSE_BYTES = 20 * 1024 * 1024

GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
# Скобки, кавычки и «=» в пути — синтаксис 1С (`Balance(Condition='…')`).
PATH_SAFE = "/()'=,$_-"


def configured() -> bool:
    return bool(BASE_URL)


def literal(value: str) -> str:
    """Строка для `$filter`: кавычка внутри удваивается, как требует OData.
    Раньше строка кодировалась quote(), и 1С искала «max26%2D…» вместо ключа."""
    return "'" + value.replace("'", "''") + "'"


def guid(value: str) -> str:
    """Ссылка для отбора. Не GUID — отказ до запроса: подставлять в отбор
    произвольную строку нельзя."""
    if not GUID.match(value or ""):
        raise OneCUnavailable("в настройках витрины ссылка 1С испорчена — выберите значение заново")
    return f"guid'{value}'"


class ODataOneC:
    name = "OData 1С:Предприятие"

    def __init__(
        self,
        base_url: str = "",
        user: str = "",
        password: str = "",
        settings: OneCSettings | None = None,
        timeout: float = TIMEOUT,
        public_only: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = (base_url or BASE_URL).rstrip("/")
        self._auth = (user or USER, password or PASSWORD)
        self._timeout = timeout
        self.settings = settings or OneCSettings()
        # Адрес вписал владелец: соединяться только с публичной сетью,
        # см. address.py. Адрес стенда задаём мы сами — он внутренний.
        self._public_only = public_only
        # Для проверок: эмулятор в том же процессе.
        self._transport = transport
        if not self._base:
            raise OneCUnavailable("адрес базы 1С не задан (ONEC_URL)")

    # --- транспорт ---

    async def _request(
        self, method: str, path: str, params: dict | None = None, body: Any = None
    ) -> Any:
        # Кириллица и пробелы уходят в процентной записи.
        url = f"{self._base}/odata/standard.odata/{quote(path, safe=PATH_SAFE)}"
        transport = self._transport or (PublicTransport() if self._public_only else None)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, auth=self._auth, follow_redirects=False, transport=transport
            ) as client:
                async with client.stream(
                    method, url, params={"$format": "json", **(params or {})},
                    json=body if body is not None else None,
                ) as response:
                    if not response.is_success:
                        detail = (await response.aread())[:2000]
                        raise OneCUnavailable(self._refusal(response.status_code, path, detail))
                    content = await self._read(response)
        except OneCUnavailable:
            raise
        except httpx.HTTPError as exc:
            # Владельцу — причина словами, в лог — как есть. Сырой текст
            # ошибки называл внутренние адреса и попадал в журнал обмена.
            log.warning("1С: %s %s не удался: %r", method, path, exc)
            raise OneCUnavailable(self._failure(exc)) from exc
        if not content:
            return {}
        try:
            return json.loads(content)
        except ValueError as exc:
            raise OneCUnavailable("1С ответила не в формате OData — проверьте адрес базы") from exc

    @staticmethod
    def _refusal(status: int, path: str, detail: bytes = b"") -> str:
        # 401 и 403 — это не «база лежит», а неверно выданные права:
        # сообщение должно называть причину, иначе искать будут сеть.
        if 300 <= status < 400:
            return "1С перенаправляет запрос — укажите конечный адрес публикации базы"
        if status == 400:
            # 1С объясняет отказ записи: «Не заполнено поле „Склад“» и т. п.
            reason = ODataOneC._odata_message(detail)
            return f"1С не приняла документ: {reason}" if reason else "1С не приняла запрос"
        name = path.split("(", 1)[0].split("/", 1)[0]
        return {
            401: "1С отклонила имя или пароль служебного пользователя",
            403: "у служебного пользователя нет прав на этот объект",
            404: f"объект {name} не опубликован в OData — включите его в составе интерфейса",
        }.get(status, f"1С ответила ошибкой {status}")

    @staticmethod
    def _odata_message(detail: bytes) -> str:
        try:
            error = json.loads(detail).get("odata.error", {})
            return str(error.get("message", {}).get("value") or "")[:300]
        except (ValueError, AttributeError):
            return ""

    def _failure(self, exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return f"1С не ответила за {self._timeout:g} с"
        if isinstance(exc, httpx.ConnectError):
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                return "сертификат сервера 1С не прошёл проверку"
            return "не удалось соединиться с 1С — проверьте адрес и что база опубликована"
        return "связь с 1С прервалась"

    @staticmethod
    async def _read(response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise OneCUnavailable("1С прислала слишком большой ответ — проверьте адрес базы")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _rows(payload: Any) -> list[dict]:
        rows = payload.get("value") if isinstance(payload, dict) else payload
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    async def _list(self, name: str, fields: str, where: str = "") -> list[dict]:
        params = {"$select": fields}
        if where:
            params["$filter"] = where
        return self._rows(await self._request("GET", self.settings.object(name), params))

    # --- справочники для настройки витрины ---

    async def lists(self) -> dict[str, list[dict]]:
        """Из чего владелец выбирает реквизиты заказа. Соглашения ведут не
        все — их отсутствие не ошибка."""
        # Только пометка удаления: она есть у любого справочника, а отбор по
        # несуществующему полю (IsFolder у неиерархического) 1С отклонит.
        live = "DeletionMark eq false"
        result: dict[str, list[dict]] = {}
        for key, name, fields in (
            ("organizations", "organizations", "Ref_Key,Description"),
            ("warehouses", "warehouses", "Ref_Key,Description"),
            ("price_kinds", "price_kinds", "Ref_Key,Description"),
            ("currencies", "currencies", "Ref_Key,Description"),
            ("contractors", "contractors", "Ref_Key,Description,Партнер_Key"),
        ):
            result[key] = [
                {
                    "key": str(row.get("Ref_Key") or ""),
                    "name": str(row.get("Description") or "").strip(),
                    **({"partner": str(row.get("Партнер_Key") or "")} if key == "contractors" else {}),
                }
                for row in await self._list(name, fields, live)
                if GUID.match(str(row.get("Ref_Key") or ""))
            ]
        try:
            agreements = await self._list("agreements", "Ref_Key,Description", live)
        except OneCUnavailable:
            agreements = []
        result["agreements"] = [
            {"key": str(row.get("Ref_Key") or ""), "name": str(row.get("Description") or "")}
            for row in agreements
            if GUID.match(str(row.get("Ref_Key") or ""))
        ]
        return result

    # --- чтение ---

    async def catalog(self) -> list[CatalogItem]:
        """Номенклатура, цены выбранного вида и свободные остатки выбранного
        склада — четырьмя запросами, ровно так, как они лежат в базе."""
        s = self.settings
        nomenclature = await self._list(
            "catalog",
            "Ref_Key,Code,Description,ЕдиницаИзмерения_Key",
            "IsFolder eq false and DeletionMark eq false",
        )
        units = {
            str(row.get("Ref_Key")): str(row.get("Description") or "").strip()
            for row in await self._list("units", "Ref_Key,Description")
        }
        price_condition = f"(Condition='ВидЦены_Key eq {guid(s.price_kind)}')" if s.price_kind else "()"
        prices = self._rows(
            await self._request("GET", f"{s.object('prices')}/SliceLast{price_condition}")
        )
        stock_field = s.object("stock_field")
        if s.object("balance_kind") == "rows":
            where = f"Склад_Key eq {guid(s.warehouse)}" if s.warehouse else ""
            balance = self._rows(
                await self._request(
                    "GET", s.object("balance"), {"$filter": where} if where else None
                )
            )
        else:
            stock_field = f"{stock_field}Balance"
            condition = f"(Condition='Склад_Key eq {guid(s.warehouse)}')" if s.warehouse else "()"
            balance = self._rows(
                await self._request("GET", f"{s.object('balance')}/Balance{condition}")
            )
        try:
            return self._catalog(nomenclature, units, prices, balance, stock_field)
        except (TypeError, ValueError) as exc:
            # Цена «abc» или список вместо числа — неудачный обмен с записью
            # в журнале, а не ошибка сервера посреди создания витрины.
            raise OneCUnavailable("1С прислала номенклатуру, которую не разобрать") from exc

    @staticmethod
    def _catalog(
        nomenclature: list[dict],
        units: dict[str, str],
        prices: list[dict],
        balance: list[dict],
        stock_field: str,
    ) -> list[CatalogItem]:
        # Срез последних по виду цен даёт одну строку на позицию; если в
        # ответе несколько — берём самую свежую.
        price_by_key: dict[str, tuple[str, float]] = {}
        for row in prices:
            key = str(row.get("Номенклатура_Key") or "")
            period = str(row.get("Period") or "")
            if key not in price_by_key or period >= price_by_key[key][0]:
                price_by_key[key] = (period, float(row.get("Цена") or 0))

        stock_by_key: dict[str, float] = {}
        for row in balance:
            key = str(row.get("Номенклатура_Key") or "")
            stock_by_key[key] = stock_by_key.get(key, 0.0) + float(row.get(stock_field) or 0)

        items: list[CatalogItem] = []
        for row in nomenclature:
            # Отбор уже на стороне 1С; проверка здесь — на случай базы,
            # которая $filter не выполнила.
            if row.get("IsFolder") or row.get("DeletionMark"):
                continue
            key = str(row.get("Ref_Key") or "")
            name = str(row.get("Description") or "").strip()
            if not name or not GUID.match(key):
                continue
            unit = units.get(str(row.get("ЕдиницаИзмерения_Key") or ""), "") or "шт"
            items.append(
                CatalogItem(
                    ref=key,
                    external_id=str(row.get("Code") or "").strip(),
                    name=name,
                    unit=unit[:20],
                    price=price_by_key.get(key, ("", 0.0))[1],
                    stock=max(0.0, stock_by_key.get(key, 0.0)),
                )
            )
        return items

    # --- запись ---

    @staticmethod
    def _lines(document: Document) -> list[dict]:
        lines = []
        for number, line in enumerate(document.lines, start=1):
            if not GUID.match(line.ref or ""):
                raise OneCUnavailable(
                    f"позиция «{line.name}» ещё не сверена с 1С — заказ уйдёт после сверки"
                )
            lines.append(
                {
                    "LineNumber": str(number),
                    "Номенклатура_Key": line.ref,
                    "Количество": line.qty,
                    "КоличествоУпаковок": line.qty,
                    "Цена": line.price,
                    "Сумма": round(line.qty * line.price, 2),
                }
            )
        return lines

    def _header(self, document: Document) -> dict:
        """Реквизиты шапки: без них УТ документ не проведёт."""
        refs = document.refs
        missing = [title for key, title in (
            ("organization", "организация"), ("warehouse", "склад"), ("currency", "валюта"),
            ("partner", "партнёр"), ("contractor", "контрагент"),
        ) if not GUID.match(refs.get(key) or "")]
        if missing:
            raise OneCUnavailable(
                "в настройках 1С у витрины не выбраны: " + ", ".join(missing)
            )
        header = {
            "Организация_Key": refs["organization"],
            "Склад_Key": refs["warehouse"],
            "Валюта_Key": refs["currency"],
            "Партнер_Key": refs["partner"],
            "Контрагент_Key": refs["contractor"],
            "ХозяйственнаяОперация": self.settings.object("operation"),
            "Комментарий": document.comment,
        }
        if GUID.match(refs.get("agreement") or ""):
            header["Соглашение_Key"] = refs["agreement"]
        if document.status:
            header["Статус"] = document.status
        if document.ship_date:
            header["ДатаОтгрузки"] = f"{document.ship_date}T00:00:00"
        return header

    async def _find_row(self, external_key: str) -> dict | None:
        """Заказ по нашему ключу — чтобы не завести второй и править свой."""
        if not external_key:
            return None
        field = self.settings.object("external_key")
        rows = await self._list(
            "order",
            f"Ref_Key,Number,Posted,DeletionMark,Комментарий,{field}",
            f"{field} eq {literal(external_key)}",
        )
        return next((row for row in rows if str(row.get(field) or "") == external_key), None)

    def _target(self, row: dict) -> str:
        return f"{self.settings.object('order')}(guid'{row.get('Ref_Key')}')"

    async def _post(self, target: str) -> None:
        await self._request("POST", f"{target}/Post", {"PostingModeOperational": "false"})

    async def push_order(self, document: Document) -> str:
        """Создаёт «Заказ клиента». Повторный вызов с тем же ключом находит
        уже созданный документ, а не заводит второй."""
        existing = await self._find_row(document.external_key)
        if existing:
            log.info("заказ %s уже есть: %s", document.external_key, existing.get("Number"))
            return str(existing.get("Number") or "")
        body = {
            **self._header(document),
            "Date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            self.settings.object("external_key"): document.external_key,
            "Товары": self._lines(document),
        }
        created = await self._request("POST", self.settings.object("order"), body=body)
        number = str(created.get("Number") or "").strip() if isinstance(created, dict) else ""
        if not number or not GUID.match(str(created.get("Ref_Key") or "")):
            raise OneCUnavailable("1С создала документ без номера")
        if document.post:
            await self._post(self._target(created))
        return number

    async def update_order(self, document: Document) -> str:
        """Правка — PATCH шапки и табличной части, затем проведение, если
        заказ в рабочем статусе: так 1С пересчитывает резерв, как если бы
        менеджер сохранил заказ."""
        row = await self._find_row(document.external_key)
        if row is None:
            return await self.push_order(document)
        target = self._target(row)
        await self._request(
            "PATCH", target, body={**self._header(document), "Товары": self._lines(document)}
        )
        if document.post:
            await self._post(target)
        return str(row.get("Number") or "")

    async def cancel_order(self, external_key: str, comment: str) -> str | None:
        """Отмена проведения снимает резерв, пометка удаления — сам заказ."""
        row = await self._find_row(external_key)
        if row is None:
            return None
        target = self._target(row)
        if row.get("Posted"):
            await self._request("POST", f"{target}/Unpost")
        await self._request("PATCH", target, body={"DeletionMark": True, "Комментарий": comment})
        return str(row.get("Number") or "") or None

    async def note_order(self, external_key: str, text: str) -> str | None:
        row = await self._find_row(external_key)
        if row is None:
            return None
        before = str(row.get("Комментарий") or "").strip()
        comment = f"{before}\n{text}" if before and text not in before else (before or text)
        await self._request("PATCH", self._target(row), body={"Комментарий": comment[:1000]})
        return str(row.get("Number") or "") or None
