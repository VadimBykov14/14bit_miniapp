"""Тесты API, не требующие базы.

Первый из них — на импорт: ошибка вроде «поле со значением по умолчанию
перед обязательным» валит контейнер на старте, и узнавать об этом из логов
на сервере дорого.

Запуск:  python3 services/api/test_api.py
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "services" / "api"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("MAX_BOT_TOKEN", "test-token")
os.environ.setdefault("APP_TIMEZONE", "Europe/Moscow")


class ImportTest(unittest.TestCase):
    def test_app_imports(self):
        """Ловит ошибки, которые иначе видно только в логах контейнера."""
        from app.main import app

        paths = set(app.openapi()["paths"])

        for expected in ("/api/me", "/api/storefronts", "/api/orders", "/api/health",
                         "/api/templates", "/api/owner/reminders/run",
                         "/api/owner/storefronts/{storefront_id}/price-import"):
            self.assertIn(expected, paths)


class CutoffTest(unittest.TestCase):
    def setUp(self):
        from app.models import Mode, Storefront

        self.tz = ZoneInfo("Europe/Moscow")
        self.storefront = Storefront(
            name="Пекарня", mode=Mode.preorder, cutoff_at=time(16, 0),
            delivery_days="пн,вт,ср,чт,пт,сб",
        )

    def at(self, day: int, hour: int, minute: int = 0) -> datetime:
        """Момент сентября 2026 по Москве: 21-е — понедельник."""
        return datetime(2026, 9, day, hour, minute, tzinfo=self.tz)

    def test_cutoff_is_in_local_time(self):
        """«До отсечки 40 минут» должно совпадать с часами на стене у менеджера,
        а не с UTC: 12:20 UTC — это 15:20 по Москве."""
        from datetime import timezone

        from app.schedule import cutoff_in_minutes

        now = datetime(2026, 9, 21, 12, 20, tzinfo=timezone.utc)
        self.assertEqual(cutoff_in_minutes(self.storefront, now), 40)

    def test_before_cutoff_order_goes_to_tomorrow(self):
        from datetime import date

        from app.schedule import cutoff_in_minutes, next_delivery_date

        now = self.at(21, 15)
        self.assertEqual(next_delivery_date(self.storefront, now), date(2026, 9, 22))
        self.assertEqual(cutoff_in_minutes(self.storefront, now), 60)

    def test_after_cutoff_order_goes_to_the_day_after(self):
        """В 17:30 при отсечке 16:00 завтрашняя дата закрыта: заявка уходит
        на послезавтра, и «до отсечки» считается до её отсечки — 22,5 ч."""
        from datetime import date

        from app.schedule import cutoff_in_minutes, delivery_dates, next_delivery_date, orderable

        now = self.at(21, 17, 30)
        self.assertFalse(orderable(self.storefront, date(2026, 9, 22), now))
        self.assertEqual(next_delivery_date(self.storefront, now), date(2026, 9, 23))
        self.assertEqual(delivery_dates(self.storefront, 2, now), [date(2026, 9, 23), date(2026, 9, 24)])
        self.assertEqual(cutoff_in_minutes(self.storefront, now), 22 * 60 + 30)

    def test_cutoff_belongs_to_the_day_before_delivery(self):
        """Возят по пн и чт: во вторник заявка на четверг принимается до
        отсечки в среду, а не до сегодняшней."""
        from datetime import date

        from app.schedule import cutoff_in_minutes, next_delivery_date

        self.storefront.delivery_days = "пн,чт"
        now = self.at(22, 10)
        self.assertEqual(next_delivery_date(self.storefront, now), date(2026, 9, 24))
        self.assertEqual(cutoff_in_minutes(self.storefront, now), 30 * 60)

    def test_production_starts_after_cutoff_of_that_date(self):
        from datetime import date

        from app.schedule import production_started

        tuesday = date(2026, 9, 22)
        self.assertFalse(production_started(self.storefront, tuesday, self.at(21, 15, 59)))
        self.assertTrue(production_started(self.storefront, tuesday, self.at(21, 16)))

    def test_stock_storefront_takes_orders_for_tomorrow_until_midnight(self):
        from datetime import date

        from app.models import Mode
        from app.schedule import next_delivery_date, production_started

        self.storefront.mode = Mode.stock
        now = self.at(21, 23, 50)
        self.assertEqual(next_delivery_date(self.storefront, now), date(2026, 9, 22))
        self.assertFalse(production_started(self.storefront, date(2026, 9, 22), now))

    def test_supplier_reschedules_from_today(self):
        from datetime import date

        from app.schedule import can_reschedule_to, reschedule_dates

        now = self.at(24, 9)
        self.assertEqual(reschedule_dates(2, now), [date(2026, 9, 24), date(2026, 9, 25)])
        self.assertTrue(can_reschedule_to(date(2026, 9, 24), now))
        self.assertFalse(can_reschedule_to(date(2026, 9, 23), now))

    def test_stock_storefront_has_no_cutoff(self):
        from app.models import Mode
        from app.schedule import cutoff_in_minutes

        self.storefront.mode = Mode.stock
        self.assertIsNone(cutoff_in_minutes(self.storefront))

    def test_next_delivery_respects_schedule(self):
        from app.schedule import WEEKDAYS, next_delivery_date

        self.storefront.delivery_days = "вт,чт,сб"
        result = next_delivery_date(self.storefront)
        self.assertIn(WEEKDAYS[result.weekday()], {"вт", "чт", "сб"})
        self.assertGreater(result, datetime.now(self.tz).date())


class RhythmTest(unittest.TestCase):
    """Ритм заявок: на нём держится подсказка «пора заказать»."""

    @staticmethod
    def _days(*offsets: int):
        from datetime import date, timedelta

        today = date(2026, 9, 22)
        return [today - timedelta(days=offset) for offset in offsets]

    def test_two_orders_are_not_a_habit(self):
        from app.reminders import rhythm

        self.assertIsNone(rhythm(self._days(7, 0)))

    def test_weekly_client(self):
        from app.reminders import rhythm

        self.assertEqual(rhythm(self._days(21, 14, 7, 0)), 7)

    def test_one_missed_week_does_not_stretch_the_habit(self):
        """Медиана, а не среднее: пропуск не должен переучивать подсказку."""
        from app.reminders import rhythm

        # 7, 7, 30, 7 — среднее дало бы 12, медиана оставляет 7
        self.assertEqual(rhythm(self._days(51, 44, 37, 7, 0)), 7)

    def test_hint_appears_only_when_overdue(self):
        from datetime import date

        from app.reminders import overdue_by

        weekly = self._days(21, 14, 7)
        self.assertIsNone(overdue_by(weekly, date(2026, 9, 18)))
        self.assertEqual(overdue_by(weekly, date(2026, 9, 22)), (7, 7))


class QuantityTest(unittest.TestCase):
    """Кратность до одной десятой. Проверяем ровно то, на чём ломается
    арифметика с плавающей точкой."""

    def test_three_tenths_is_a_multiple_of_one_tenth(self):
        """0.3 % 0.1 во float даёт 0.0999…, и заявка на 300 граммов
        при шаге 100 граммов была бы отвергнута."""
        from app.quantity import is_multiple

        self.assertTrue(is_multiple(0.3, 0.1))
        self.assertTrue(is_multiple(1.2, 0.4))
        self.assertFalse(is_multiple(1.0, 0.4))

    def test_finer_than_a_tenth_is_refused(self):
        from app.quantity import on_grid

        self.assertTrue(on_grid(0.4))
        self.assertTrue(on_grid(12))
        self.assertFalse(on_grid(0.35))

    def test_trimming_to_pack(self):
        from app.quantity import down_to_pack

        self.assertEqual(down_to_pack(1.0, 0.4), 0.8)
        self.assertEqual(down_to_pack(25, 12), 24)

    def test_rounding_up_to_pack(self):
        from app.quantity import up_to_pack

        self.assertEqual(up_to_pack(30, 12), 36)
        self.assertEqual(up_to_pack(24, 12), 24)
        self.assertEqual(up_to_pack(0.5, 0.4), 0.8)

    def test_order_minimum_is_whole_packs(self):
        """Минимум в заявке — целые упаковки: «от 24» после смены коробки
        на десяток — это 30, иначе минимум не набрать ни одним количеством."""
        from app.quantity import order_minimum

        self.assertIsNone(order_minimum(None, 12))
        self.assertIsNone(order_minimum(0, 12))
        self.assertEqual(order_minimum(24, 12), 24)
        self.assertEqual(order_minimum(24, 10), 30)

    def test_human_reading(self):
        from app.quantity import human

        self.assertEqual(human(0.5, "кг"), "0,5 кг")
        self.assertEqual(human(12, "шт"), "12 шт")
        self.assertEqual(human(1.0, "кг"), "1 кг")

    def test_decimal_for_storage_has_no_binary_tail(self):
        from app.quantity import to_decimal

        self.assertEqual(str(to_decimal(0.1 + 0.2)), "0.3")


class MinQtyTest(unittest.TestCase):
    """Минимум в заявке у позиции: ноль снимает его, некратный упаковке —
    отказ с понятной причиной."""

    def test_zero_or_empty_means_no_minimum(self):
        from app.routers.owner import _min_qty

        self.assertIsNone(_min_qty(None, 12, "шт"))
        self.assertIsNone(_min_qty(0, 12, "шт"))

    def test_minimum_is_whole_packs(self):
        from fastapi import HTTPException

        from app.routers.owner import _min_qty

        self.assertEqual(float(_min_qty(24, 12, "шт")), 24)
        self.assertEqual(float(_min_qty(1.2, 0.4, "кг")), 1.2)
        with self.assertRaises(HTTPException) as caught:
            _min_qty(30, 12, "шт")
        self.assertEqual(caught.exception.detail, "минимум должен быть кратен упаковке — 12 шт")
        with self.assertRaises(HTTPException):
            _min_qty(-12, 12, "шт")

    def test_supplier_cuts_down_to_minimum_not_zero(self):
        from app.quantity import edit_floor

        # Минимум 24 при упаковке 12 — ниже 24 при подтверждении не уменьшить
        self.assertEqual(edit_floor(48, 24, 12), 24)
        # Без минимума — одна упаковка
        self.assertEqual(edit_floor(48, None, 12), 12)
        self.assertEqual(edit_floor(3, None, 1), 1)
        # Минимум задали после заявки: заказано меньше — предел заказанное
        self.assertEqual(edit_floor(12, 24, 12), 12)
        # Весовая позиция
        self.assertEqual(edit_floor(2.4, 1.2, 0.4), 1.2)


class ProfileTest(unittest.IsolatedAsyncioTestCase):
    """Заполненность профиля поставщика: город, контакт, логотип. Описание
    витрины не считается — без него профиль заполнен целиком."""

    class Session:
        def __init__(self, fronts):
            self.fronts = fronts

        async def execute(self, _query):
            fronts = self.fronts

            class Result:
                def scalars(self):
                    return iter(fronts)

            return Result()

    @staticmethod
    def enterprise(**fields):
        from types import SimpleNamespace

        return SimpleNamespace(**{
            "id": 1, "city": "Казань", "contact_phone": "+7 (900) 123-45-67",
            "max_chat": False, "contact_max": "", **fields,
        })

    async def test_description_is_not_counted(self):
        from types import SimpleNamespace

        from app.routers.owner import _profile

        front = SimpleNamespace(logo_key="logo.png", about="")
        self.assertEqual(await _profile(self.Session([front]), self.enterprise()), (100, []))

    async def test_missing_items_are_named(self):
        from types import SimpleNamespace

        from app.routers.owner import _profile

        front = SimpleNamespace(logo_key=None, about="Печём с 1998 года")
        self.assertEqual(
            await _profile(self.Session([front]), self.enterprise(city=" ")),
            (33, ["город", "логотип"]),
        )


class VolumePromoTest(unittest.TestCase):
    """Скидка «от количества»: на свою позицию и «на любую позицию» — у
    каждой позиции свой порог, штуки разных позиций не складываются."""

    @staticmethod
    def promo(item_id, min_qty=24, percent=10):
        from app.models import Promo, PromoKind

        return Promo(
            kind=PromoKind.volume_qty, title="Опт", item_id=item_id,
            min_qty=min_qty, discount_percent=percent,
        )

    def test_own_item_only(self):
        from app.promos import apply_volume

        prices, applied = apply_volume([self.promo(1)], [(1, 24, 100.0), (2, 30, 50.0)])
        self.assertEqual(prices, {1: 90.0})
        self.assertEqual([row.title for row in applied], ["Опт"])

    def test_any_item_counts_each_item_apart(self):
        from app.promos import apply_volume

        prices, applied = apply_volume(
            [self.promo(None)], [(1, 24, 100.0), (2, 12, 50.0), (3, 12, 40.0)]
        )
        self.assertEqual(prices, {1: 90.0})
        self.assertEqual(len(applied), 1)

    def test_any_item_below_threshold_gives_nothing(self):
        from app.promos import apply_volume

        prices, applied = apply_volume([self.promo(None)], [(1, 23, 100.0)])
        self.assertEqual((prices, applied), ({}, []))

    def test_condition_names_the_target(self):
        from app.promos import condition

        self.assertEqual(
            condition(self.promo(1), "Зефир"), "−10 % на «Зефир» при заказе от 24"
        )
        self.assertEqual(
            condition(self.promo(None)), "−10 % на любую позицию при заказе от 24"
        )


class LinkChatSqlTest(unittest.TestCase):
    def test_chat_comparison_compiles_for_postgres(self):
        """`IS NOT $1` — синтаксическая ошибка Postgres, а ошибку связывания
        чата глотает бот: без этой проверки она не видна вообще нигде."""
        from sqlalchemy import update
        from sqlalchemy.dialects import postgresql

        from app.models import Client

        statement = (
            update(Client)
            .where(Client.max_user_id == 1, Client.max_chat_id.is_distinct_from(2))
            .values(max_chat_id=2)
        )
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertNotIn("IS NOT %", sql)


class PriceListTest(unittest.TestCase):
    """Разбор прайса. Файл приходит от человека, а не от системы, поэтому
    проверяем именно то, чем такие файлы обычно и ломают импорт."""

    HEADER = "Артикул;Наименование;Единица;Кратность;Цена;Остаток"

    def _parse(self, body: str, name: str = "price.csv"):
        from app.pricelist import parse

        return parse(body.encode("utf-8-sig"), name)

    def test_reads_russian_csv(self):
        parsed = self._parse(f"{self.HEADER}\r\nА-1;Батон;шт;10;38,50;240\r\n")
        self.assertEqual(len(parsed.rows), 1)
        row = parsed.rows[0]
        self.assertEqual((row.external_id, row.name, row.price), ("А-1", "Батон", 38.5))
        self.assertEqual((row.pack_size, row.stock, row.unit), (10, 240, "шт"))

    def test_number_with_spaces_and_comma(self):
        from app.pricelist import _number

        self.assertEqual(_number("1 234,50"), 1234.5)
        self.assertEqual(_number("1\u00a0234.5"), 1234.5)
        self.assertIsNone(_number("—"))

    def test_columns_may_be_in_any_order_and_named_differently(self):
        parsed = self._parse("Цена;Название;Код\r\n38,5;Батон;А-1\r\n")
        self.assertEqual(parsed.rows[0].name, "Батон")
        self.assertEqual(parsed.rows[0].external_id, "А-1")

    def test_section_rows_are_not_errors(self):
        """«Хлебобулочные изделия» без цены — это раздел прайса,
        а не сломанная строка."""
        parsed = self._parse(f"{self.HEADER}\r\n;Хлебобулочные;;;;\r\n;Батон;шт;10;38,5;0\r\n")
        self.assertEqual(len(parsed.rows), 1)
        self.assertFalse(parsed.problems)

    def test_bad_price_is_reported_with_line_number(self):
        parsed = self._parse(f"{self.HEADER}\r\n;Батон;шт;10;-5;0\r\n;Булка;шт;12;22;0\r\n")
        self.assertEqual(len(parsed.rows), 1)
        self.assertIn("строка 2", parsed.problems[0])

    def test_file_without_header_is_refused_whole(self):
        from app.pricelist import PriceListError

        with self.assertRaises(PriceListError):
            self._parse("что-то;совсем;другое\r\n1;2;3\r\n")

    def test_xlsx_round_trip(self):
        import io

        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Наименование", "Цена", "Остаток"])
        sheet.append(["Багет французский", 54, 60])
        buffer = io.BytesIO()
        workbook.save(buffer)

        from app.pricelist import parse

        parsed = parse(buffer.getvalue(), "прайс.xlsx")
        self.assertEqual(parsed.rows[0].name, "Багет французский")
        self.assertEqual(parsed.rows[0].price, 54.0)
        self.assertEqual(parsed.rows[0].stock, 60)


class DurationTest(unittest.TestCase):
    def test_reads_like_a_clock(self):
        from app.reminders import human_duration

        self.assertEqual(human_duration(40), "40 мин")
        self.assertEqual(human_duration(125), "2 ч 5 мин")
        self.assertEqual(human_duration(288), "4 ч")


class MigrationsTest(unittest.TestCase):
    def test_revisions_form_one_chain(self):
        """Две ревизии с одним down_revision дают ветку, и upgrade head
        падает уже на сервере. Дешевле поймать здесь."""
        import re

        versions = pathlib.Path(__file__).resolve().parent / "migrations" / "versions"
        heads, parents = set(), {}
        for path in versions.glob("*.py"):
            text = path.read_text()
            revision = re.search(r"^revision = '([^']+)'", text, re.M).group(1)
            down = re.search(r"^down_revision = (?:'([^']+)'|None)", text, re.M).group(1)
            heads.add(revision)
            self.assertNotIn(down, parents, f"ветка: {down} имеет двух потомков")
            parents[down] = revision

        self.assertEqual(len(heads - set(parents)), 1, "должна быть одна голова")
        self.assertIn(None, parents, "должна быть ровно одна начальная ревизия")


class DocumentTest(unittest.TestCase):
    def test_document_number_format(self):
        from app.onec import document_number

        self.assertEqual(document_number(3), "ЗК-000003")

    def test_simulated_number_comes_from_the_order_id(self):
        """Внешний ключ — «max26-order-7». Сбор всех цифр строки дал бы
        267 вместо 7, и номер документа разошёлся бы с заявкой."""
        from app.onec.simulated import _tail

        self.assertEqual(_tail("max26-order-7"), "000007")
        self.assertEqual(_tail("max26-correction-123"), "000123")

    def test_document_key_survives_database_reset(self):
        """Базу приложения пересоздают, и заявка №7 появляется снова, а база
        1С помнит вчерашнюю №7. С ключом по одному номеру 1С возвращала
        старый документ: новый заказ не создавался, остаток не менялся."""
        from app.models import Order
        from app.onec import document_key
        from app.onec.simulated import _tail
        from datetime import timezone

        yesterday = Order(id=7, created_at=datetime(2026, 9, 22, 19, 33, 2, tzinfo=timezone.utc))
        today = Order(id=7, created_at=datetime(2026, 9, 23, 1, 53, 37, tzinfo=timezone.utc))
        self.assertNotEqual(document_key("order", yesterday), document_key("order", today))
        self.assertNotEqual(document_key("order", today), document_key("correction", today))
        # Номер документа в эмуляции по-прежнему берётся из номера заявки.
        self.assertEqual(_tail(document_key("order", today)), "000007")
        self.assertLessEqual(len(document_key("correction", today)), 80)

    def test_correction_has_its_own_number(self):
        """Корректировка — отдельный документ, а не правка заказа:
        номера не должны совпадать."""
        from app.onec import correction_number, document_number

        self.assertEqual(correction_number(3), "КР-000003")
        self.assertNotEqual(correction_number(3), document_number(3))



class ExtraLimitTest(unittest.TestCase):
    """Сверх заказанного менеджер добавляет не больше 5 %."""

    def test_five_percent_rounded_down_to_pack(self):
        from app.quantity import ceiling

        # 67 шт + 5 % = 70,35 → 70: скриншот с 67 → 81 такого не пропустит
        self.assertEqual(ceiling(67, 1), 70)
        self.assertEqual(ceiling(100, 1), 105)

    def test_no_room_for_a_whole_pack_means_no_increase(self):
        """60 при упаковке 12: 5 % — это 3 штуки, коробку не добавить."""
        from app.quantity import ceiling

        self.assertEqual(ceiling(60, 12), 60)
        self.assertEqual(ceiling(240, 12), 252)

    def test_fractional_units(self):
        from app.quantity import ceiling

        self.assertEqual(ceiling(10, 0.1), 10.5)
        self.assertEqual(ceiling(2, 0.5), 2)


class ContactTest(unittest.TestCase):
    """Кнопка «Связаться» ведёт в MAX или на телефон — и только туда."""

    def test_max_profile_link_and_nick(self):
        from app.contact import href, normalize

        self.assertEqual(normalize("max", "https://max.ru/u/f9LHodD0cOL"),
                         ("max", "https://max.ru/u/f9LHodD0cOL"))
        self.assertEqual(normalize("max", "max.ru/sweet_home"), ("max", "https://max.ru/sweet_home"))
        self.assertEqual(normalize("max", "@sweet_home"), ("max", "https://max.ru/sweet_home"))
        self.assertEqual(href("max", "@sweet_home"), "https://max.ru/sweet_home")

    def test_foreign_link_is_refused(self):
        """Чужой сайт под видом контакта поставщика — это фишинг, а не контакт."""
        from app.contact import ContactError, normalize

        with self.assertRaises(ContactError):
            normalize("max", "https://evil.example/max.ru/u/x")

    def test_phone_becomes_tel_with_country_code(self):
        from app.contact import href

        self.assertEqual(href("phone", "8 (900) 123-45-67"), "tel:+79001234567")
        self.assertEqual(href("phone", "+7 900 123-45-67"), "tel:+79001234567")

    def test_phone_is_stored_by_the_mask(self):
        """Ровно 11 цифр, восьмёрка становится семёркой, иностранные — отказ."""
        from app.contact import ContactError, normalize_phone, phone_href

        self.assertEqual(normalize_phone("89001234567"), "+7 (900) 123-45-67")
        self.assertEqual(normalize_phone("+7 900 123-45-67"), "+7 (900) 123-45-67")
        for value in ("9001234567", "+44 20 7946 0958", "+7 900 123-45-678"):
            with self.assertRaises(ContactError):
                normalize_phone(value)
        # Старый номер без кода страны звонком не станет.
        self.assertEqual(phone_href("+44 20 7946 0958"), "")

    def test_short_phone_is_refused(self):
        from app.contact import ContactError, normalize

        with self.assertRaises(ContactError):
            normalize("phone", "12-34")

    def test_empty_contact_is_allowed(self):
        from app.contact import href, normalize

        self.assertEqual(normalize("phone", "  "), ("", ""))
        self.assertEqual(href("", ""), "")

    def test_link_is_taken_out_of_pasted_text(self):
        """«Поделиться» в MAX кладёт в буфер фразу — адрес достаём из неё."""
        from app.contact import normalize_max

        self.assertEqual(normalize_max("Мой профиль в MAX: https://max.ru/u/f9LHodD0cOL"),
                         "https://max.ru/u/f9LHodD0cOL")
        self.assertEqual(normalize_max("https://max.ru/u/abc?utm=1"), "https://max.ru/u/abc")

    def test_phone_in_the_max_field_is_named_a_phone(self):
        """«89001234567» раньше становился ссылкой max.ru/89001234567."""
        from app.contact import ContactError, normalize_max

        for value in ("89001234567", "+7 900 123-45-67"):
            with self.assertRaisesRegex(ContactError, "номер телефона"):
                normalize_max(value)

    def test_button_falls_back_to_the_filled_way(self):
        from app.contact import effective

        self.assertEqual(effective("max", "+7 900 123-45-67", ""), ("phone", "+7 900 123-45-67"))
        self.assertEqual(effective("phone", "", "https://max.ru/x_y"), ("max", "https://max.ru/x_y"))
        self.assertEqual(effective("phone", "+7 900", "https://max.ru/x_y"), ("phone", "+7 900"))
        self.assertEqual(effective("", "", ""), ("", ""))

    def test_too_long_is_refused_not_truncated(self):
        """Обрезанная ссылка никуда не ведёт — лучше честный отказ."""
        from app.contact import ContactError, normalize_max, normalize_phone

        with self.assertRaises(ContactError):
            normalize_max("https://max.ru/u/" + "a" * 300)
        with self.assertRaises(ContactError):
            normalize_phone("8" + " " * 40 + "9001234567")

    def test_client_chat_needs_a_public_nick(self):
        from app.contact import user_chat

        self.assertEqual(user_chat("ivan_petrov"), "https://max.ru/ivan_petrov")
        self.assertEqual(user_chat(None), "")
        self.assertEqual(user_chat("12345"), "")


class LinksTest(unittest.TestCase):
    """Подписанная ссылка открывает ровно свой путь, своим человеком и недолго."""

    def test_round_trip(self):
        from app import links

        token = links.token("/api/photos/receipts/k1", 42, "client", links.PHOTO_TTL)
        self.assertEqual(links.verify("/api/photos/receipts/k1", token), (42, "client"))

    def test_bound_to_path(self):
        from app import links

        token = links.token("/api/photos/receipts/k1", 42, "client", links.PHOTO_TTL)
        self.assertIsNone(links.verify("/api/photos/receipts/k2", token))

    def test_tampered_user_or_role_is_refused(self):
        from app import links

        user, role, expires, mac = links.token("/api/x", 42, "client", 60).split(".")
        self.assertIsNone(links.verify("/api/x", f"43.{role}.{expires}.{mac}"))
        self.assertIsNone(links.verify("/api/x", f"{user}.owner.{expires}.{mac}"))
        self.assertIsNone(links.verify("/api/x", "мусор"))

    def test_expired_is_refused(self):
        from app import links

        user, role, _, _ = links.token("/api/x", 42, None, 60).split(".")
        stale = f"{user}.{role}.1000"
        self.assertIsNone(links.verify("/api/x", f"{stale}.{links._mac('/api/x', stale)}"))

    def test_stable_within_window_for_caching(self):
        from app import links

        first = links.token("/api/x", 42, "client", links.PHOTO_TTL)
        second = links.token("/api/x", 42, "client", links.PHOTO_TTL)
        self.assertEqual(first, second)


class TeamScheduleTest(unittest.TestCase):
    """График сотрудника: кто на связи и когда ответит."""

    def employee(self, days="пн,вт,ср,чт,пт", start=time(9, 0), end=time(18, 0)):
        from app.models import Employee, Role

        return Employee(max_user_id=1, enterprise_id=1, role=Role.manager, name="Иван",
                        work_days=days, work_from=start, work_to=end)

    def at(self, text):
        from app.schedule import TZ

        return datetime.fromisoformat(text).replace(tzinfo=TZ)

    def test_days_are_shown_as_range_or_list(self):
        from app import team

        self.assertEqual(team.days_text([0, 1, 2, 3, 4]), "пн–пт")
        self.assertEqual(team.days_text([0, 2, 4]), "пн, ср, пт")
        self.assertEqual(team.days_text([5, 6]), "сб, вс")
        self.assertEqual(team.days_text(list(range(7))), "ежедневно")
        self.assertEqual(team.hours_text(self.employee()), "пн–пт 9:00–18:00")

    def test_on_shift_by_day_and_hour(self):
        from app import team

        worker = self.employee()
        # 2026-09-21 — понедельник
        self.assertTrue(team.on_shift(worker, self.at("2026-09-21T10:30")))
        self.assertFalse(team.on_shift(worker, self.at("2026-09-21T18:00")))
        self.assertFalse(team.on_shift(worker, self.at("2026-09-26T10:30")))  # суббота
        self.assertIsNone(team.on_shift(self.employee(days="")))

    def test_night_shift_belongs_to_its_start_day(self):
        from app import team

        night = self.employee(days="пт", start=time(22, 0), end=time(6, 0))
        self.assertTrue(team.on_shift(night, self.at("2026-09-25T23:00")))  # пятница
        self.assertTrue(team.on_shift(night, self.at("2026-09-26T03:00")))  # ночь на субботу
        self.assertFalse(team.on_shift(night, self.at("2026-09-27T03:00")))  # ночь на воскресенье

    def test_next_shift_is_named(self):
        from app import team

        worker = self.employee()
        self.assertEqual(team.next_shift_text(worker, self.at("2026-09-21T07:00")), "сегодня с 9:00")
        self.assertEqual(team.next_shift_text(worker, self.at("2026-09-21T19:00")), "завтра с 9:00")
        self.assertEqual(team.next_shift_text(worker, self.at("2026-09-25T19:00")), "пн с 9:00")

    def test_schedule_is_validated(self):
        from app import team

        self.assertEqual(team.normalize_schedule([], "", ""), ("", None, None))
        days, start, end = team.normalize_schedule(["пт", "пн"], "9:00", "18:30")
        self.assertEqual((days, start, end), ("пн,пт", time(9, 0), time(18, 30)))
        with self.assertRaises(team.ScheduleError):
            team.normalize_schedule(["пн"], "25:99", "18:00")
        with self.assertRaises(team.ScheduleError):
            team.normalize_schedule(["пн"], "9:00", "9:00")


class MessageButtonTest(unittest.TestCase):
    """Кнопка под сообщением ведёт туда, где дело."""

    def test_buttons_lead_to_the_right_screen(self):
        from app.messaging import button_for

        self.assertEqual(button_for("confirmed", 57, None)["payload"], "order_57")
        self.assertEqual(button_for("order", 57, None, "owner")["payload"], "order_57_owner")
        self.assertEqual(button_for("confirmed", 57, None, "worker")["payload"], "order_57_worker")
        self.assertEqual(button_for("staff_cutoff", None, 3)["payload"], "orders_staff")
        self.assertEqual(button_for("join_request", None, 3)["payload"], "connections")
        self.assertEqual(button_for("cutoff", None, 3)["payload"], "sf_3")
        self.assertEqual(button_for("connection", None, 3)["text"], "Открыть витрину")
        self.assertEqual(button_for("info", None, None)["payload"], "")
        # Приглашение приняли — тому, кто звал: клиенты или сотрудники.
        self.assertEqual(button_for("joined", None, None)["payload"], "clients")
        self.assertEqual(button_for("joined_staff", None, None)["payload"], "staff")
        # Клиент отменил — поставщику в его роли.
        self.assertEqual(button_for("cancelled", 9, None, "manager")["payload"], "order_9_manager")

    def test_payload_fits_max_rules(self):
        """MAX пропускает в ярлык только буквы, цифры, «_» и «-»."""
        import re

        from app.messaging import button_for

        for args in (("order", 1, None), ("staff_cutoff", None, 2), ("connection", None, None)):
            self.assertRegex(button_for(*args)["payload"], re.compile(r"^[\w-]*$"))




class CityTest(unittest.TestCase):
    """Город выбирают из справочника: области, страны и дубли в список
    не попадают, область в скобках уходит в подпись."""

    def test_parse_keeps_russian_cities_only(self):
        from app.routers.cities import parse

        russia = {"id": "113", "text": "Россия"}
        moscow_region = {"id": "2019", "text": "Московская область", "parent": russia}
        payload = {"items": [
            {"id": "1", "text": "Москва", "parent": russia},
            {"id": "2019", "text": "Московская область", "parent": russia},
            {"id": "2061", "text": "Подольск (Московская область)", "parent": moscow_region},
            {"id": "40", "text": "Казахстан"},
            {"id": "150", "text": "Аксай (Казахстан)",
             "parent": {"id": "1", "text": "Западно-Казахстанская область",
                        "parent": {"id": "40", "text": "Казахстан"}}},
            {"id": "88", "text": "Казань",
             "parent": {"id": "1624", "text": "Республика Татарстан", "parent": russia}},
        ]}
        cities = [(row.name, row.region) for row in parse(payload)]
        self.assertEqual(
            cities,
            [("Москва", ""), ("Подольск", "Московская область"), ("Казань", "Республика Татарстан")],
        )

    def test_places_matched_only_by_region_are_dropped(self):
        from app.routers.cities import parse

        region = {"id": "1754", "text": "Ивановская область", "parent": {"id": "113", "text": "Россия"}}
        payload = {"items": [
            {"id": "1", "text": "Родники (Ивановская область)", "parent": region},
            {"id": "2", "text": "Катав-Ивановск", "parent": region},
            {"id": "3", "text": "Иваново", "parent": region},
        ]}
        self.assertEqual([row.name for row in parse(payload, "Иван")], ["Иваново", "Катав-Ивановск"])

    def test_fallback_when_directory_is_down(self):
        from app.routers.cities import _fallback

        self.assertEqual([row.name for row in _fallback("кин")], ["Кинешма"])
        self.assertTrue(_fallback("Мос"))

    def test_city_is_one_not_a_list(self):
        from app.routers.cities import CityError, one_city

        self.assertEqual(one_city("  Нижний   Новгород "), "Нижний Новгород")
        self.assertEqual(one_city(""), "")
        for wrong in ("Кинешма, Заволжск", "Город-на-реке" * 10):
            with self.assertRaises(CityError):
                one_city(wrong)


class InviteCardTest(unittest.TestCase):
    """Ссылка-приглашение открывает чат с ботом, и бот присылает приглашение
    с кнопкой. Подключения до нажатия нет; чужое и использованное — отказ."""

    class Session:
        def __init__(self, rows, supplier=None, shop=None):
            self.rows = rows
            # Предприятие, где приглашённый владелец или менеджер, и магазин,
            # где он владелец точки или работник
            self.supplier = supplier
            self.shop = shop

        async def get(self, model, key):
            return self.rows.get((model.__name__, key))

        async def execute(self, query):
            answer = self.supplier if "employees" in str(query) else self.shop

            class Result:
                def scalars(self):
                    return self

                def first(self):
                    return answer

            return Result()

    def card(self, invite, user_id, rows=None, supplier=None, shop=None):
        import asyncio

        from app.invites import card

        return asyncio.run(card(self.Session(rows or {}, supplier, shop), invite, user_id))

    def invite(self, **fields):
        from app.models import Invite

        base = dict(code="inv_Abc123", kind="client", enterprise_id=1, storefront_id=3,
                    client_id=None, used_by=None, for_user=None)
        base.update(fields)
        return Invite(**base)

    def rows(self):
        from app.models import Client, Enterprise, Storefront

        return {
            ("Enterprise", 1): Enterprise(id=1, name="Пекарня «Колос»", city="Кинешма"),
            ("Storefront", 3): Storefront(id=3, name="Хлеб", enterprise_id=1),
            ("Client", 5): Client(id=5, name="Магазин «У дома»", max_user_id=10),
        }

    def test_client_invitation_has_accept_button_with_same_code(self):
        card = self.card(self.invite(), 77, self.rows())
        self.assertTrue(card.valid)
        self.assertIn("Пекарня «Колос» (Кинешма) приглашает вас к витрине «Хлеб»", card.text)
        self.assertEqual(card.button, {"text": "Принять приглашение", "payload": "inv_Abc123"})

    def test_worker_and_manager_invitations(self):
        worker = self.card(self.invite(code="wrk_x1y2z3", kind="worker", client_id=5,
                                       enterprise_id=None), 77, self.rows())
        self.assertIn("Магазин «У дома» приглашает вас работником", worker.text)
        manager = self.card(self.invite(code="emp_q1w2e3", kind="manager"), 77, self.rows())
        self.assertIn("менеджером", manager.text)
        self.assertEqual(manager.button["payload"], "emp_q1w2e3")

    def test_used_foreign_and_missing_are_refused(self):
        self.assertFalse(self.card(self.invite(used_by=55), 77, self.rows()).valid)
        self.assertIn("уже приняли", self.card(self.invite(used_by=77), 77, self.rows()).text)
        foreign = self.card(self.invite(for_user=55), 77, self.rows())
        self.assertFalse(foreign.valid)
        self.assertIn("другому человеку", foreign.text)
        self.assertFalse(self.card(None, 77).valid)
        self.assertEqual(self.card(None, 77).button["payload"], "")

    def test_supplier_gets_no_accept_button_for_shop_invites(self):
        # Аккаунт поставщика магазином не становится: ни клиентом, ни работником
        client = self.card(self.invite(), 77, self.rows(), supplier="Молочный двор")
        self.assertFalse(client.valid)
        self.assertEqual(client.button["payload"], "")
        self.assertIn("на стороне поставщика — «Молочный двор»", client.text)
        self.assertTrue(client.text[0].isupper() and client.text.endswith("."))
        worker = self.card(self.invite(code="wrk_x1y2z3", kind="worker", client_id=5,
                                       enterprise_id=None), 77, self.rows(), supplier="Молочный двор")
        self.assertFalse(worker.valid)
        # В команду другого поставщика звать можно — это не магазин
        manager = self.card(self.invite(code="emp_q1w2e3", kind="manager"), 77, self.rows(),
                            supplier="Молочный двор")
        self.assertTrue(manager.valid)

    def test_shop_gets_no_accept_button_for_team_invite(self):
        # И наоборот: магазин — владелец точки или работник — в команду поставщика не входит
        manager = self.card(self.invite(code="emp_q1w2e3", kind="manager"), 77, self.rows(),
                            shop="Магазин «У дома»")
        self.assertFalse(manager.valid)
        self.assertEqual(manager.button["payload"], "")
        self.assertIn("на стороне магазина — «Магазин «У дома»»", manager.text)
        # Приглашение магазина магазину — как раньше
        self.assertTrue(self.card(self.invite(), 77, self.rows(), shop="Магазин «У дома»").valid)


class ApproveCounterpartyTest(unittest.IsolatedAsyncioTestCase):
    """Контрагент 1С выбирают сразу при подключении клиента. У витрины без 1С
    и с испорченной ссылкой — отказ до первой записи: клиент не подключается
    наполовину."""

    class Session:
        def __init__(self, connection, storefront):
            self.rows = {"Connection": connection, "Storefront": storefront}

        async def get(self, model, _key):
            return self.rows.get(model.__name__)

        async def commit(self):
            raise AssertionError("отказ не должен ничего сохранять")

    async def test_refused_before_anything_is_written(self):
        from types import SimpleNamespace

        from fastapi import HTTPException

        from app.auth import Identity
        from app.models import Role, Source
        from app.routers.owner import decide_connection
        from app.schemas import ConnectionDecisionIn

        owner = Identity(max_user_id=1, first_name="Ольга", role=Role.owner, enterprise_id=7)
        connection = SimpleNamespace(id=5, client_id=9, storefront_id=3, status="pending")
        guid = "4f1c2b3a-0000-4000-8000-00000000abcd"

        manual = SimpleNamespace(id=3, enterprise_id=7, source=Source.manual, name="Склад")
        with self.assertRaises(HTTPException) as caught:
            await decide_connection(
                5, "approve", ConnectionDecisionIn(contractor_key=guid), owner,
                self.Session(connection, manual),
            )
        self.assertEqual(caught.exception.status_code, 422)

        on_onec = SimpleNamespace(id=3, enterprise_id=7, source=Source.onec, name="Склад")
        with self.assertRaises(HTTPException) as caught:
            await decide_connection(
                5, "approve", ConnectionDecisionIn(contractor_key="ООО Ромашка"), owner,
                self.Session(connection, on_onec),
            )
        self.assertEqual(caught.exception.detail, "значение из 1С испорчено — выберите заново")
        self.assertEqual(connection.status, "pending")


class SupplierAcceptTest(unittest.IsolatedAsyncioTestCase):
    """«Принять приглашение» из старого сообщения бота или ссылка ?startapp=inv_…
    Аккаунту поставщика — отказ, и в базе ничего не появляется."""

    class Session:
        def __init__(self, invite):
            self.invite = invite
            self.added = []

        async def execute(self, _query):
            invite = self.invite

            class Result:
                def scalar_one_or_none(self):
                    return invite

            return Result()

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            raise AssertionError("отказ не должен ничего заводить")

        async def commit(self):
            raise AssertionError("отказ не должен ничего сохранять")

    async def test_owner_and_manager_cannot_become_shop(self):
        from fastapi import HTTPException

        from app.auth import Identity, Membership
        from app.models import Invite, Role
        from app.routers.public import accept_invite

        for role in (Role.owner, Role.manager):
            person = Identity(
                max_user_id=77, first_name="Пётр", role=role, enterprise_id=1,
                memberships=(Membership(role=role, enterprise_id=1, enterprise_name="Пекарня «Колос»"),),
            )
            for kind, code in (("client", "inv_Abc123"), ("worker", "wrk_x1y2z3")):
                invite = Invite(code=code, kind=kind, enterprise_id=2, storefront_id=3, client_id=5,
                                used_by=None, for_user=None)
                session = self.Session(invite)
                with self.assertRaises(HTTPException) as caught:
                    await accept_invite(code, person, session)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("на стороне поставщика — «Пекарня «Колос»»", caught.exception.detail)
                self.assertEqual(session.added, [])

    async def test_shop_owner_and_worker_cannot_join_supplier_team(self):
        from fastapi import HTTPException

        from app.auth import Identity, Membership
        from app.models import Invite, Role
        from app.routers.public import accept_invite

        for role in (Role.client, Role.worker):
            person = Identity(
                max_user_id=77, first_name="Анна", role=role, client_id=5,
                memberships=(Membership(role=role, client_id=5, client_name="Магазин «У дома»"),),
            )
            invite = Invite(code="emp_q1w2e3", kind="manager", enterprise_id=2, storefront_id=None,
                            client_id=None, used_by=None, for_user=None)
            session = self.Session(invite)
            with self.assertRaises(HTTPException) as caught:
                await accept_invite("emp_q1w2e3", person, session)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("на стороне магазина — «Магазин «У дома»»", caught.exception.detail)
            self.assertEqual(session.added, [])


class OrderHoldTest(unittest.TestCase):
    """Сколько заявка держит на складе: подтверждённое, до подтверждения —
    заказанное. От этого считается, что вернуть при отмене и правке."""

    def test_held_prefers_confirmed(self):
        from app.models import Order, OrderItem
        from app.onec import held

        order = Order(id=1)
        order.items = [
            OrderItem(item_id=1, qty_ordered=24, qty_confirmed=None, price=10),
            OrderItem(item_id=2, qty_ordered=10, qty_confirmed=6, price=10),
        ]
        self.assertEqual(held(order), {1: 24.0, 2: 6.0})


class OneCAddressTest(unittest.TestCase):
    """Адрес базы 1С вписывает владелец, а ходит по нему сервер: только
    https и только публичная сеть. Иначе через витрину читали бы внутренние
    сервисы стенда и служебные адреса облака."""

    def test_only_https_and_public_network(self):
        from app.onec.address import BadAddress, check

        self.assertEqual(check(" https://1c.example.ru/trade/ "), "https://1c.example.ru/trade")
        self.assertEqual(check(""), "")
        for bad in (
            "http://1c.example.ru/trade",
            "https://user:secret@1c.example.ru/trade",
            "https://1c.example.ru/trade?x=1",
            "https://1c.example.ru/trade#x",
            "https://127.0.0.1/trade",
            "https://10.0.0.7/trade",
            "https://169.254.169.254/latest/meta-data",
            "https://[::1]/trade",
            "https://[::ffff:10.0.0.1]/trade",
            "https://mock-1c:8080/demo",
            "https://localhost/trade",
            "https://srv.local/trade",
            "https://2130706433/trade",
            "https://0x7f.1/trade",
            "not a url",
        ):
            with self.subTest(bad), self.assertRaises(BadAddress):
                check(bad)

    def test_ipv4_inside_ipv6_is_checked_as_ipv4(self):
        from ipaddress import ip_address

        from app.onec.address import is_public

        self.assertTrue(is_public(ip_address("8.8.8.8")))
        self.assertTrue(is_public(ip_address("2a00:1450:4010:c05::64")))
        for internal in ("100.64.0.1", "224.0.0.1", "0.0.0.0", "::ffff:127.0.0.1",
                         "64:ff9b::a9fe:a9fe", "2002:7f00:1::1", "fd00::1", "fe80::1"):
            with self.subTest(internal):
                self.assertFalse(is_public(ip_address(internal)))

    def test_key_without_base_does_not_fall_back_to_stand(self):
        """Раньше ключ, из которого не выводилась база, отправлял витрину в
        базу стенда из окружения — с паролем стенда."""
        from app.models import Source, Storefront
        from app.onec import OneCUnavailable, backend, base_from_key

        self.assertTrue(base_from_key("demo.secret").endswith("/demo"))
        for bad in ("secret", ".secret", "demo.", "../x.secret", "a?b.secret", "a/b.secret"):
            with self.subTest(bad):
                self.assertEqual(base_from_key(bad), "")
        with self.assertRaises(OneCUnavailable):
            backend(Storefront(source=Source.onec, onec_key="../x.secret", onec_url=""))

    def test_owner_address_is_checked_on_every_exchange(self):
        """Адрес мог сохраниться раньше этих правил — проверяется и при обмене."""
        from app.models import Source, Storefront
        from app.onec import OneCUnavailable, backend

        with self.assertRaises(OneCUnavailable):
            backend(Storefront(source=Source.onec, onec_key="k", onec_url="http://10.0.0.7/base"))
        own = backend(
            Storefront(source=Source.onec, onec_key="k", onec_url="https://1c.example.ru/trade")
        )
        self.assertTrue(own._public_only)
        stand = backend(Storefront(source=Source.onec, onec_key="demo.secret", onec_url=""))
        self.assertFalse(stand._public_only)


class OneCConnectTest(unittest.IsolatedAsyncioTestCase):
    """Имя, прошедшее проверку при сохранении, DNS может разрешить во
    внутреннюю сеть. Поэтому сервер проверяет адреса перед соединением и
    соединяется с проверенным."""

    def resolve_to(self, *addresses):
        import asyncio
        import socket
        from unittest import mock

        async def resolve(host, port, **kwargs):
            family = {4: socket.AF_INET, 6: socket.AF_INET6}
            return [
                (family[6 if ":" in address else 4], socket.SOCK_STREAM, 6, "", (address, port))
                for address in addresses
            ]

        return mock.patch.object(asyncio.get_running_loop(), "getaddrinfo", new=resolve)

    async def catalog_error(self) -> str:
        from app.onec import OneCUnavailable
        from app.onec.odata import ODataOneC

        client = ODataOneC(base_url="https://1c.example.ru/trade", password="k", public_only=True)
        with self.assertRaises(OneCUnavailable) as caught:
            await client.catalog()
        return str(caught.exception)

    async def test_name_resolving_inside_is_refused(self):
        with self.resolve_to("10.0.0.7"):
            self.assertIn("внутреннюю сеть", await self.catalog_error())

    async def test_one_internal_answer_refuses_the_whole_name(self):
        with self.resolve_to("93.184.216.34", "127.0.0.1"):
            self.assertIn("внутреннюю сеть", await self.catalog_error())

    async def test_connects_to_the_checked_address(self):
        """Соединение — с тем адресом, что проверили, а не с именем: второй
        запрос к DNS мог бы вернуть другой."""
        from unittest import mock

        import httpcore

        seen = []

        async def connect(self, host, port, **kwargs):
            seen.append(host)
            raise httpcore.ConnectError("стоп: в тестах сеть не нужна")

        with self.resolve_to("93.184.216.34"), \
                mock.patch.object(httpcore.AnyIOBackend, "connect_tcp", new=connect):
            message = await self.catalog_error()
        self.assertEqual(seen, ["93.184.216.34"])
        self.assertIn("не удалось соединиться", message)
        self.assertNotIn("93.184", message)


class OneCAnswerTest(unittest.IsolatedAsyncioTestCase):
    """Что сервер 1С ответил — по-человечески, без сырых ошибок: редирект
    не выполняется, не-OData и огромный ответ — отказ, а не падение."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/moved/"):
                    self.send_response(302)
                    self.send_header("Location", "http://10.0.0.7/")
                    self.end_headers()
                    return
                body = b"<html>login</html>" if self.path.startswith("/html/") else b"x" * 4096
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        from unittest import mock

        # Прокси из окружения песочницы не должен перехватывать localhost.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(name, None)

    async def error(self, base: str) -> str:
        from app.onec import OneCUnavailable
        from app.onec.odata import ODataOneC

        with self.assertRaises(OneCUnavailable) as caught:
            await ODataOneC(base_url=base, password="k").catalog()
        return str(caught.exception)

    async def test_redirect_is_not_followed(self):
        self.assertIn("перенаправляет", await self.error(f"{self.base}/moved"))

    async def test_not_odata_is_a_refusal(self):
        self.assertIn("не в формате OData", await self.error(f"{self.base}/html"))

    async def test_huge_answer_is_cut(self):
        from unittest import mock

        with mock.patch("app.onec.odata.MAX_RESPONSE_BYTES", 1024):
            self.assertIn("слишком большой", await self.error(f"{self.base}/big"))

    async def test_connection_error_names_no_address(self):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        message = await self.error(f"http://127.0.0.1:{port}/base")
        self.assertIn("не удалось соединиться", message)
        self.assertNotIn("127.0.0.1", message)


class SpreadsheetTest(unittest.TestCase):
    """Выгрузку открывают в Excel: ячейка, похожая на формулу, должна
    остаться текстом, а точка с запятой в названии — не рвать строку."""

    def test_formula_becomes_text(self):
        from app.spreadsheet import text

        self.assertEqual(text('=HYPERLINK("http://x";"click")'), '\'=HYPERLINK("http://x";"click")')
        for start in ("+7 999", "-2+3", "@SUM(A1)", " =1+1"):
            with self.subTest(start):
                self.assertTrue(text(start).startswith("'"))
        self.assertEqual(text("Пекарня «Утро»"), "Пекарня «Утро»")
        self.assertEqual(text("две\nстроки"), "две строки")

    def test_table_is_read_back_whole(self):
        import csv
        import io

        from app.spreadsheet import table, text, untext

        body = table(("Наименование", "Цена"), [[text('=cmd|"/c calc"!A1'), "10,00"],
                                                [text('Хлеб; "Дарницкий"'), "45,50"]])
        self.assertTrue(body.startswith("\ufeff"))
        rows = list(csv.reader(io.StringIO(body.lstrip("\ufeff")), delimiter=";"))
        self.assertEqual(rows[1], ['\'=cmd|"/c calc"!A1', "10,00"])
        self.assertEqual(rows[2], ['Хлеб; "Дарницкий"', "45,50"])
        self.assertEqual(untext(rows[1][0]), '=cmd|"/c calc"!A1')
        self.assertEqual(untext("'просто апостроф"), "'просто апостроф")

    def test_price_list_round_trip_drops_the_apostrophe(self):
        from app.pricelist import parse
        from app.spreadsheet import table, text

        body = table(("Артикул", "Наименование", "Единица", "Кратность", "Цена", "Остаток"),
                     [[text("-15"), text("=Батон"), "шт", "1", "40,00", "5"]])
        row = parse(body.encode("utf-8"), "price.csv").rows[0]
        self.assertEqual((row.external_id, row.name, row.price), ("-15", "=Батон", 40.0))


class BodyLimitTest(unittest.IsolatedAsyncioTestCase):
    """Тело больше предела — отказ 413 до того, как сервер его дочитает:
    FastAPI читает тело ещё до проверки подписи, и гигабайтный запрос мог
    прислать кто угодно."""

    async def asyncSetUp(self):
        import httpx
        from fastapi import FastAPI, File, UploadFile

        from app.body_limit import BodyLimit

        app = FastAPI()
        app.add_middleware(BodyLimit, limit=1024)

        @app.post("/echo")
        async def echo(payload: dict) -> dict:
            return {"size": len(str(payload))}

        @app.post("/upload")
        async def upload(file: UploadFile = File(...)) -> dict:
            return {"size": len(await file.read())}

        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_small_request_passes(self):
        response = await self.client.post("/echo", json={"a": "b"})
        self.assertEqual(response.status_code, 200)

    async def test_declared_length_over_limit_is_refused(self):
        response = await self.client.post("/echo", json={"a": "x" * 2048})
        self.assertEqual(response.status_code, 413)
        self.assertIn("слишком большой", response.json()["detail"])

    async def test_undeclared_length_is_cut_while_reading(self):
        async def chunks():
            yield (b'--zzz\r\nContent-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
                   b"Content-Type: image/jpeg\r\n\r\n")
            for _ in range(8):
                yield b"x" * 512
            yield b"\r\n--zzz--\r\n"

        response = await self.client.post(
            "/upload", content=chunks(),
            headers={"Content-Type": "multipart/form-data; boundary=zzz"},
        )
        self.assertEqual(response.status_code, 413)


class MuteTest(unittest.TestCase):
    """«Не присылать такие» отключает вид уведомлений на своей стороне:
    клиент, отключивший «ваша заявка отправлена», продолжает как владелец
    получать «новая заявка»."""

    def test_order_is_split_by_side(self):
        from app import mutes

        self.assertEqual(mutes.side("owner"), "staff")
        self.assertEqual(mutes.side("manager"), "staff")
        self.assertEqual(mutes.side("worker"), "shop")
        self.assertEqual(mutes.side(None), "")
        self.assertEqual(mutes.label("order", "staff"), "новые заявки")
        self.assertEqual(mutes.label("order", "shop"), "ваши отправленные заявки")
        self.assertIsNone(mutes.label("order", ""))

    def test_payload_round_trip_matches_bot_contract(self):
        """Бот пропускает только «mute:<вид>:<сторона>» — см. MUTE в bot-service."""
        import re

        from app import mutes

        contract = re.compile(r"^mute:[a-z_]{1,30}:(staff|shop)?$")
        for kind in [*mutes.LABELS, "order"]:
            for side in ("staff", "shop", ""):
                payload = mutes.payload(kind, side)
                if payload is None:
                    continue
                with self.subTest(payload=payload):
                    self.assertRegex(payload, contract)
                    self.assertEqual(mutes.parse(payload), (kind, side))

    def test_unknown_kinds_are_not_mutable(self):
        from app import mutes

        self.assertIsNone(mutes.payload("promo_spam", "shop"))
        for bad in ("mute:promo_spam:shop", "mute:cutoff:admin", "cutoff", "mute:../x:", ""):
            with self.subTest(bad):
                self.assertIsNone(mutes.parse(bad))


class FavoritesTest(unittest.TestCase):
    """Звёздочки — по ролям: магазин отмечает витрины, товары и сотрудников
    поставщика, поставщик — клиентов. Остальное — 404, а не молчаливая запись."""

    def test_kinds_follow_role(self):
        from app.auth import Identity
        from app.models import Role
        from app.routers.favorites import BUYER_KINDS, STAFF_KINDS, _kinds

        shop = Identity(max_user_id=1, first_name="", role=Role.worker, client_id=5)
        owner = Identity(max_user_id=2, first_name="", role=Role.owner, enterprise_id=7)
        lost = Identity(max_user_id=3, first_name="", role=None)
        self.assertEqual(_kinds(shop), BUYER_KINDS)
        self.assertEqual(_kinds(owner), STAFF_KINDS)
        self.assertEqual(_kinds(lost), ())
        self.assertNotIn("client", BUYER_KINDS)
        self.assertNotIn("storefront", STAFF_KINDS)

    def test_routes_are_published(self):
        from app.main import app

        paths = set(app.openapi()["paths"])
        for expected in ("/api/favorites", "/api/favorites/ids",
                         "/api/favorites/{kind}/{target_id}",
                         "/api/notifications/mutes", "/api/notifications/mutes/{kind}",
                         "/internal/notifications/mute"):
            self.assertIn(expected, paths)


class ShelfTest(unittest.TestCase):
    """Разделы полки: популярные — по числу магазинов, новые — последние
    открытые. Витрина попадает только в один раздел."""

    def test_sections(self):
        from app.shelf import sections

        placed = sections([1, 2, 3, 4], {1: 5, 3: 2})
        self.assertEqual(placed, {1: "popular", 3: "popular", 4: "new", 2: "new"})

    def test_limits(self):
        from app.shelf import NEW_LIMIT, POPULAR_LIMIT, sections

        ids = list(range(1, 21))
        placed = sections(ids, {sid: sid for sid in ids})
        popular = [sid for sid, section in placed.items() if section == "popular"]
        fresh = [sid for sid, section in placed.items() if section == "new"]
        self.assertEqual(sorted(popular), list(range(15, 21)))
        self.assertEqual(len(popular), POPULAR_LIMIT)
        # Новые — свежие из тех, что не попали в популярные
        self.assertEqual(sorted(fresh), list(range(9, 15)))
        self.assertEqual(len(fresh), NEW_LIMIT)
        self.assertEqual(sum(1 for section in placed.values() if section == "all"), 8)

    def test_rank_orders_sections(self):
        from app.shelf import rank, sections

        clients = {2: 1, 5: 9}
        ids = [3, 1, 2, 5, 4]
        placed = sections(ids, clients)
        ordered = sorted(ids, key=lambda sid: rank(placed[sid], sid, clients))
        self.assertEqual(ordered[:2], [5, 2])
        self.assertEqual(ordered[2:], [4, 3, 1])


class PlainTextTest(unittest.TestCase):
    """Описание с двадцатью пустыми строками растягивало карточку товара на
    весь экран, а внизу оставался одинокий дефис."""

    def test_blank_lines_collapse(self):
        from app.plaintext import description

        self.assertEqual(description("Энергичный донельзя\n\n\n\n\n\n-"), "Энергичный донельзя\n\n-")
        self.assertEqual(description("  \r\n\n  "), "")

    def test_extra_lines_join_the_last_one(self):
        """Строк не больше восьми, но текст не теряется."""
        from app.plaintext import DESCRIPTION_LINES, description

        text = description("\n".join(str(n) for n in range(12)))
        self.assertEqual(len(text.split("\n")), DESCRIPTION_LINES)
        self.assertTrue(text.endswith("7 8 9 10 11"))

    def test_limit_is_kept(self):
        from app.plaintext import COMMENT_LIMIT, comment

        self.assertEqual(len(comment("я" * 1000)), COMMENT_LIMIT)


class StrictOneCTest(unittest.IsolatedAsyncioTestCase):
    """Клиент OData против строгого эмулятора: те же правила, что у
    настоящей базы, — скобки, GUID, «На согласовании» без резерва."""

    async def asyncSetUp(self):
        import importlib.util
        import tempfile

        import httpx

        # Модуль эмулятора называется app.py, как и пакет API: грузим его
        # под своим именем, иначе импорт app.onec сломался бы.
        mock_dir = pathlib.Path(__file__).resolve().parent.parent / "mock-1c"
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ONEC_STATE"] = f"{self.tmp.name}/bases.json"
        os.environ["ONEC_SEED"] = str(mock_dir / "data.json")
        os.environ["ONEC_NOTIFY_URL"] = ""
        os.environ["ONEC_DEMO_KEY"] = "demo.test-key"
        sys.modules.pop("store", None)
        sys.path.insert(0, str(mock_dir))
        try:
            spec = importlib.util.spec_from_file_location("mock_onec", mock_dir / "app.py")
            self.mock = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mock)
        finally:
            sys.path.remove(str(mock_dir))
            sys.modules.pop("store", None)
        self.transport = httpx.ASGITransport(app=self.mock.app)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def client(self, settings=None, user="exchange", password="demo.test-key"):
        from app.onec.odata import ODataOneC

        return ODataOneC(
            base_url="http://mock/demo", user=user, password=password,
            settings=settings, transport=self.transport,
        )

    async def configured(self):
        from app.onec.settings import OneCSettings

        lists = await self.client().lists()
        pick = lambda key, name=None: next(  # noqa: E731
            row for row in lists[key] if name is None or row["name"] == name
        )
        contractor = pick("contractors", "Магазин «У дома» (тест)")
        return OneCSettings(
            organization=pick("organizations")["key"],
            warehouse=pick("warehouses", "Основной склад")["key"],
            price_kind=pick("price_kinds", "Розничная")["key"],
            currency=pick("currencies")["key"],
            contractor=contractor["key"], partner=contractor["partner"],
        )

    def stock(self, name):
        base = self.mock.store.base("demo")
        return next(float(item["Остаток"]) for item in base["items"] if item["Description"] == name)

    async def test_catalog_skips_folders_and_reads_prices_by_kind(self):
        settings = await self.configured()
        items = await self.client(settings).catalog()
        names = {item.name for item in items}
        self.assertEqual(len(items), 7)
        self.assertNotIn("Кондитерские изделия (группа)", names)
        zefir = next(item for item in items if item.name.startswith("Зефир"))
        self.assertRegex(zefir.ref, r"^[0-9a-f-]{36}$")
        self.assertEqual(zefir.external_id, "00-0001")
        self.assertEqual(zefir.price, 120.0)  # розничная = оптовая × 1,25
        self.assertEqual(zefir.stock, 144)
        self.assertIsNone(zefir.pack_size)  # кратности в типовой УТ нет
        caramel = next(item for item in items if item.name.startswith("Карамель"))
        self.assertEqual(caramel.unit, "кг")

    async def test_empty_warehouse_has_no_stock(self):
        settings = await self.configured()
        lists = await self.client().lists()
        settings.warehouse = next(r["key"] for r in lists["warehouses"] if "№2" in r["name"])
        items = await self.client(settings).catalog()
        self.assertTrue(all(item.stock == 0 for item in items))

    async def test_virtual_table_without_brackets_is_refused(self):
        from app.onec.contract import OneCUnavailable

        with self.assertRaisesRegex(OneCUnavailable, "не опубликован"):
            await self.client()._request("GET", "AccumulationRegister_СвободныеОстатки/Balance")

    async def test_wrong_user_is_refused(self):
        from app.onec.contract import OneCUnavailable

        with self.assertRaisesRegex(OneCUnavailable, "имя или пароль"):
            await self.client(user="admin").lists()

    async def cabinet(self, method, path, body=None):
        import httpx

        async with httpx.AsyncClient(transport=self.transport, base_url="http://mock") as client:
            return await client.request(method, "/1c/api" + path, json=body)

    async def test_contractors_are_per_base_and_reach_the_app(self):
        from app.onec.contract import Document, DocumentLine

        name = "ИП Смирнова (магазин «Ромашка»)"
        added = await self.cabinet("POST", "/bases/demo/contractors", {"name": f"  {name} "})
        self.assertEqual(added.status_code, 201)
        self.assertIn(name, [row["Description"] for row in added.json()["contractors"]])
        # Тот же контрагент ещё раз, пустое название, чужая база — отказы.
        again = await self.cabinet("POST", "/bases/demo/contractors", {"name": name.upper()})
        self.assertEqual(again.status_code, 409)
        self.assertIn("уже есть", again.json()["detail"])
        self.assertEqual((await self.cabinet("POST", "/bases/demo/contractors", {"name": " "})).status_code, 422)
        self.assertEqual((await self.cabinet("POST", "/bases/nope/contractors", {"name": name})).status_code, 404)

        # Приложение видит его в справочнике — с партнёром, как в УТ.
        lists = await self.client().lists()
        mine = next(row for row in lists["contractors"] if row["name"] == name)
        self.assertRegex(mine["key"], r"^[0-9a-f-]{36}$")
        self.assertRegex(mine["partner"], r"^[0-9a-f-]{36}$")

        # Заказ на нового контрагента проводится.
        settings = await self.configured()
        settings.contractor, settings.partner = mine["key"], mine["partner"]
        zefir = next(item for item in await self.client(settings).catalog() if item.name.startswith("Зефир"))
        refs = {
            "organization": settings.organization, "warehouse": settings.warehouse,
            "currency": settings.currency, "partner": settings.partner, "contractor": settings.contractor,
        }
        order = Document(external_key="max26-1-order-romashka", client="",
                         lines=[DocumentLine(ref=zefir.ref, name=zefir.name, qty=12, price=96)],
                         status="КВыполнению", post=True, refs=refs)
        await self.client(settings).push_order(order)
        self.assertEqual(self.mock.store.base("demo")["documents"][0]["Контрагент"], name)

        # У другой базы список свой: только исходные тестовые контрагенты.
        other = (await self.cabinet("POST", "/bases", {"name": "Вторая база"})).json()
        detail = (await self.cabinet("GET", f"/bases/{other['slug']}")).json()
        self.assertNotIn(name, [row["Description"] for row in detail["contractors"]])
        self.assertIn("Магазин «У дома» (тест)", [row["Description"] for row in detail["contractors"]])

    def test_old_base_gets_the_former_contractors(self):
        # База, сохранённая до своих контрагентов, получает прежние три:
        # на них уже выгружены заказы. Модуль store эмулятора снят с
        # sys.modules после загрузки — функцию берём из его пространства имён.
        upgrade = self.mock.Store.__init__.__globals__["upgrade"]
        base = {"slug": "old", "items": [], "documents": [], "user": "exchange"}
        self.assertTrue(upgrade(base))
        self.assertIn("Магазин «У дома» (тест)", base["contractors"])
        self.assertFalse(upgrade(base))

    async def test_order_waits_without_reserve_then_reserves_on_confirm(self):
        from app.onec.contract import Document, DocumentLine

        settings = await self.configured()
        items = await self.client(settings).catalog()
        zefir = next(item for item in items if item.name.startswith("Зефир"))
        refs = {
            "organization": settings.organization, "warehouse": settings.warehouse,
            "currency": settings.currency, "partner": settings.partner,
            "contractor": settings.contractor,
        }
        # Кавычка в ключе: отбор экранирует её удвоением.
        key = "max26-1-order-o'7"
        line = DocumentLine(ref=zefir.ref, name=zefir.name, qty=24, price=96)
        new = Document(external_key=key, client="", lines=[line], status="НеСогласован", refs=refs)
        number = await self.client(settings).push_order(new)
        self.assertTrue(number.startswith("ЗК-"))
        self.assertEqual(self.stock(zefir.name), 144)  # «На согласовании» не резервирует
        # Повторная выгрузка находит тот же документ.
        self.assertEqual(await self.client(settings).push_order(new), number)

        confirmed = Document(
            external_key=key, client="", lines=[DocumentLine(zefir.ref, zefir.name, 12, 96)],
            status="КВыполнению", post=True, refs=refs,
        )
        await self.client(settings).update_order(confirmed)
        self.assertEqual(self.stock(zefir.name), 132)

        await self.client(settings).note_order(key, "Расхождения приёмки: недовоз")
        doc = self.mock.store.base("demo")["documents"][0]
        self.assertIn("недовоз", doc["Комментарий"])
        self.assertEqual(doc["Контрагент"], "Магазин «У дома» (тест)")

        await self.client(settings).cancel_order(key, "отменена")
        self.assertEqual(self.stock(zefir.name), 144)
        self.assertTrue(doc["DeletionMark"])

    async def test_order_without_requisites_is_not_sent(self):
        from app.onec.contract import Document, DocumentLine, OneCUnavailable

        document = Document(
            external_key="k", client="", lines=[DocumentLine("x", "позиция", 1, 1)], refs={},
        )
        with self.assertRaisesRegex(OneCUnavailable, "не выбраны: организация, склад"):
            await self.client().push_order(document)

    async def test_mock_checks_required_fields_on_posting(self):
        """Эмулятор, как 1С, не проводит заказ без склада."""
        from app.onec.contract import OneCUnavailable

        settings = await self.configured()
        items = await self.client(settings).catalog()
        client = self.client(settings)
        created = await client._request("POST", "Document_ЗаказКлиента", body={
            "Организация_Key": settings.organization, "Статус": "КВыполнению",
            "Товары": [{"Номенклатура_Key": items[0].ref, "Количество": 1, "Цена": 1}],
        })
        with self.assertRaisesRegex(OneCUnavailable, "Не заполнено поле"):
            await client._post(client._target(created))

    def test_filter_literal_doubles_quotes(self):
        from app.onec.odata import literal

        self.assertEqual(literal("o'7"), "'o''7'")


class OwnBaseTest(unittest.TestCase):
    """Своя база владельца: адрес, пользователь и пароль, который в базе
    приложения лежит только зашифрованным."""

    def setUp(self):
        os.environ.setdefault("MAX_BOT_TOKEN", "test-token")

    def storefront(self, password):
        from app import secret_box
        from app.models import Mode, Source, Storefront

        return Storefront(
            name="Склад", mode=Mode.stock, source=Source.onec,
            onec_url="https://1c.example.ru/trade", onec_user="Обмен_MAX",
            onec_password=secret_box.seal(password) if password else "",
            onec_settings={"preset": "ut11_5", "warehouse": "", "names": {}},
        )

    def test_password_is_sealed_and_used(self):
        from app import onec, secret_box

        front = self.storefront("длинный-пароль")
        self.assertNotIn("длинный-пароль", front.onec_password)
        self.assertEqual(secret_box.open_sealed(front.onec_password), "длинный-пароль")
        client = onec.backend(front)
        self.assertEqual(client._auth, ("Обмен_MAX", "длинный-пароль"))
        self.assertTrue(client._public_only)
        self.assertEqual(client.settings.object("prices"), "InformationRegister_ЦеныНоменклатуры25")

    def test_foreign_seal_asks_to_reenter(self):
        from app import onec

        front = self.storefront("")
        front.onec_password = "gAAAAA-чужой"
        with self.assertRaisesRegex(onec.OneCUnavailable, "введите его заново"):
            onec.backend(front)

    def test_reserve_choice_decides_status(self):
        """По умолчанию «На согласовании» без проведения; «резерв сразу» —
        рабочий статус и проведение."""
        from app import onec
        from app.models import Order, OrderStatus

        front = self.storefront("p")
        order = Order(status=OrderStatus.sent)
        self.assertEqual(onec._state(order, front), ("НеСогласован", False))
        front.onec_reserve_now = True
        self.assertEqual(onec._state(order, front), ("КВыполнению", True))
        front.onec_reserve_now = False
        order.status = OrderStatus.confirmed
        self.assertEqual(onec._state(order, front), ("КВыполнению", True))


class TestBotsTest(unittest.IsolatedAsyncioTestCase):
    """Тестовые боты — вторая сторона сценария для проверяющих."""

    @staticmethod
    def item(item_id: int, available: float, pack: float = 1, min_qty: float | None = None,
             price: float = 100) -> dict:
        return {"id": item_id, "available": available, "pack_size": pack,
                "min_qty": min_qty, "price": price}

    def test_order_takes_two_roomiest_items_at_minimum(self):
        """Остатки никто не пополняет: берём по минимуму и там, где запаса
        больше всего. Позицию, где и минимум не набрать, пропускаем."""
        from app.testbots import compose

        lines = compose(
            [self.item(1, 24, pack=12), self.item(2, 500, pack=10, min_qty=20),
             self.item(3, 5, pack=6), self.item(4, 240, pack=12)],
            None,
        )
        self.assertEqual(lines, [{"item_id": 2, "qty": 20.0}, {"item_id": 4, "qty": 12.0}])

    def test_order_reaches_minimum_sum_with_margin(self):
        """Минимальная сумма — с запасом в пятую часть: скидка «от суммы» не
        должна опустить итог ниже порога. Добираем по упаковке."""
        from app.testbots import compose

        lines = compose([self.item(1, 100, pack=0.5, price=300)], 1000)
        self.assertEqual(lines, [{"item_id": 1, "qty": 4.0}])

    def test_order_gives_up_when_nothing_fits(self):
        from app.testbots import compose

        self.assertIsNone(compose([self.item(1, 3, pack=6)], None))
        self.assertIsNone(compose([self.item(1, 12, pack=12, price=10)], 5000))

    def test_shop_bot_comes_only_to_listed_test_bases(self):
        """На стенде — только база со служебного слайда; без списка — любая
        тестовая, кроме демо. Своя база и витрина без 1С — никогда."""
        from app import testbots
        from app.models import Source, Storefront

        def front(key: str, url: str = "", user: str = "", source=Source.onec) -> Storefront:
            return Storefront(name="В", source=source, onec_key=key, onec_url=url, onec_user=user)

        saved = testbots.BASES
        try:
            testbots.BASES = {"base-c117db"}
            self.assertTrue(testbots.on_test_base(front("base-c117db.secret")))
            self.assertFalse(testbots.on_test_base(front("base-other.secret")))
            testbots.BASES = set()
            self.assertTrue(testbots.on_test_base(front("base-other.secret")))
            self.assertFalse(testbots.on_test_base(front("demo.stand-demo-key")))
            self.assertFalse(testbots.on_test_base(front("", "https://1c.example.ru/ut", "exchange")))
            self.assertFalse(testbots.on_test_base(front("base-other.secret", source=Source.manual)))
        finally:
            testbots.BASES = saved

    def test_bot_signature_passes_the_same_check(self):
        """Бот ходит в API как человек: подпись сервера проходит ту же
        проверку, id у бота отрицательный."""
        from webapp_auth import sign, verify

        ctx = verify(sign(-1002, "Бот-магазин", "test-token"), "test-token")
        self.assertEqual((ctx.user_id, ctx.first_name), (-1002, "Бот-магазин"))

    async def test_bots_get_no_messages(self):
        """Чата в MAX у бота нет: уведомление ему не уходит и в ленту не ложится."""
        from app.messaging import tell

        class Untouchable:
            def __getattr__(self, name):
                raise AssertionError(f"сессия тронута: {name}")

        self.assertFalse(await tell(Untouchable(), -1001, "Новая заявка"))

    async def test_writing_to_a_bot_reaches_the_demo_account(self):
        """В MAX ботов нет: «Написать» боту присылает карточку аккаунта
        демо-стенда — человека из команды, — и без его телефона."""
        from types import SimpleNamespace
        from unittest import mock

        from app.auth import Identity
        from app.models import Role
        from app.routers import reach
        from app.schemas import ReachIn

        human = SimpleNamespace(first_name="Ольга", last_name="Смирнова", title="Ольга Смирнова",
                                max_reachable=True, username="", phone="+7 (900) 111-22-33")

        class Found:
            def scalar_one_or_none(self):
                return human

        class Session:
            async def execute(self, _query):
                return Found()

        async def bot(*_args):
            return -1001, "Бот-поставщик"

        async def people(_session, ids):
            return {user_id: human for user_id in ids}

        async def chat(*_args):
            return 42

        async def name():
            return "test_bot"

        sent = {}

        async def send_contact(to, chat_id, **card):
            sent.update(card, to=to)
            return True

        shop = Identity(max_user_id=7001, first_name="Анна", role=Role.client, client_id=9)
        with mock.patch.object(reach, "_target", bot), mock.patch.object(reach.team, "people", people), \
                mock.patch.object(reach, "known_chat", chat), \
                mock.patch.object(reach.botinfo, "username", name), \
                mock.patch.object(reach, "send_contact", send_contact):
            answer = await reach.reach(ReachIn(employee_id=1), shop, Session())
        self.assertTrue(answer.sent)
        self.assertEqual(sent["contact_id"], reach.DEMO_USER_ID)
        self.assertEqual(sent["name"], "Ольга Смирнова")
        self.assertEqual(sent["phone"], "")
        self.assertIn("За тестового бота «Бот-поставщик» отвечает Ольга Смирнова", sent["text"])

    async def test_failed_action_waits_before_retry(self):
        """Не вышло — повтор через минуту, а не каждым проходом."""
        from app import testbots

        worker = testbots.Worker.__new__(testbots.Worker)
        worker.later = {}
        calls = []

        async def refused(*args, **_kwargs):
            calls.append(args)
            return None

        worker.call = refused
        for _ in range(3):
            await worker.act("confirm", 7, testbots.SUPPLIER_ID, "owner", "POST", "/orders/7/confirm")
        self.assertEqual(len(calls), 1)
        worker.later[("confirm", 7)] = 0
        await worker.act("confirm", 7, testbots.SUPPLIER_ID, "owner", "POST", "/orders/7/confirm")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
