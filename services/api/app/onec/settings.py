"""Настройки обмена витрины с её базой 1С.

Имена объектов OData зависят от конфигурации и её версии: цены в УТ 11.5 —
уже «ЦеныНоменклатуры25», свободный остаток с 11.5.7 — другой регистр.
Раньше имена задавались переменными окружения на весь стенд, а у разных
поставщиков разные УТ и ERP. Теперь это настройка витрины: шаблон под
версию и, если нужно, свои имена поверх него.

Реквизиты заказа — организация, склад, вид цен, валюта, контрагент — в
1С ссылки (GUID). Без них «Заказ клиента» не проведётся, поэтому их
выбирают из списков, прочитанных из самой базы.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Общие для типовых УТ 11, КА 2 и ERP 2 имена.
COMMON = {
    "catalog": "Catalog_Номенклатура",
    "units": "Catalog_УпаковкиЕдиницыИзмерения",
    "order": "Document_ЗаказКлиента",
    "organizations": "Catalog_Организации",
    "warehouses": "Catalog_Склады",
    "price_kinds": "Catalog_ВидыЦен",
    "currencies": "Catalog_Валюты",
    "contractors": "Catalog_Контрагенты",
    "agreements": "Catalog_СоглашенияСКлиентами",
    "prices": "InformationRegister_ЦеныНоменклатуры",
    "balance": "AccumulationRegister_СвободныеОстатки",
    # accumulation — регистр накопления с таблицей Balance(); rows —
    # регистр сведений, строки которого складываются по складу.
    "balance_kind": "accumulation",
    # Свободный остаток — ресурс «В наличии», а не «Количество».
    "stock_field": "ВНаличии",
    # Стандартный реквизит заказа: по нему повторная выгрузка находит уже
    # созданный документ, и дорабатывать конфигурацию не нужно.
    "external_key": "НомерПоДаннымКлиента",
    "operation": "РеализацияКлиенту",
    # В УТ 11 нет статуса «Согласован»: «На согласовании» движений не
    # делает, рабочий статус резервирует.
    "status_new": "НеСогласован",
    "status_work": "КВыполнению",
}

PRESETS: dict[str, dict] = {
    "ut11_4": {"title": "УТ 11.4, КА 2.4, ERP 2.4"},
    "ut11_5": {
        "title": "УТ 11.5, КА 2.5, ERP 2.5 — до 11.5.7",
        "prices": "InformationRegister_ЦеныНоменклатуры25",
    },
    "ut11_5_7": {
        "title": "УТ 11.5.7 и новее, ERP 2.5.7 и новее",
        "prices": "InformationRegister_ЦеныНоменклатуры25",
        # «Свободные остатки» заменил регистр сведений «Распределение
        # запасов»: таблицы Balance() у него нет. Имя ресурса проверьте по
        # $metadata своей базы и при необходимости задайте своё.
        "balance": "InformationRegister_РаспределениеЗапасов",
        "balance_kind": "rows",
        "stock_field": "Количество",
    },
}
DEFAULT_PRESET = "ut11_4"

# Реквизиты заказа, которые выбирают из списков базы.
REFS = ("organization", "warehouse", "price_kind", "currency", "contractor", "agreement")
# Без этих заказ в УТ не проведётся. Соглашение — только если их ведут.
REQUIRED = {
    "organization": "организация",
    "warehouse": "склад",
    "currency": "валюта",
    "contractor": "контрагент",
}


@dataclass
class OneCSettings:
    preset: str = DEFAULT_PRESET
    objects: dict[str, str] = field(default_factory=dict)
    organization: str = ""
    warehouse: str = ""
    price_kind: str = ""
    currency: str = ""
    contractor: str = ""
    # Партнёр — владелец контрагента в УТ: берётся из карточки контрагента.
    partner: str = ""
    agreement: str = ""
    # Названия выбранного — чтобы показать владельцу, не спрашивая 1С.
    names: dict[str, str] = field(default_factory=dict)
    reserve_now: bool = False

    def object(self, name: str) -> str:
        """Имя объекта: своё поверх шаблона версии поверх общего."""
        preset = PRESETS.get(self.preset, PRESETS[DEFAULT_PRESET])
        return str(self.objects.get(name) or preset.get(name) or COMMON[name])

    def missing(self) -> list[str]:
        return [title for key, title in REQUIRED.items() if not getattr(self, key)]

    def stored(self) -> dict:
        """Что лежит в Storefront.onec_settings."""
        return {
            "preset": self.preset,
            "objects": {k: v for k, v in self.objects.items() if k in COMMON and v},
            **{key: getattr(self, key) for key in (*REFS, "partner")},
            "names": self.names,
        }


def load(stored: dict | None, reserve_now: bool = False) -> OneCSettings:
    data = stored if isinstance(stored, dict) else {}
    preset = str(data.get("preset") or DEFAULT_PRESET)
    return OneCSettings(
        preset=preset if preset in PRESETS else DEFAULT_PRESET,
        objects={k: str(v) for k, v in (data.get("objects") or {}).items() if k in COMMON and v},
        **{key: str(data.get(key) or "") for key in (*REFS, "partner")},
        names={k: str(v) for k, v in (data.get("names") or {}).items()},
        reserve_now=reserve_now,
    )
