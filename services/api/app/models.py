"""Сущности продукта. Имена — из docs/product/concept.md, §«Ключевые сущности»."""

from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String,
    Text, Time, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Role(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    client = "client"
    # Работник магазина: заказывает от имени точки, как её владелец, но
    # не приглашает и не убирает людей и не меняет сведения о точке.
    worker = "worker"


class Mode(str, enum.Enum):
    """Режим витрины: со склада (есть остаток) или под заказ (есть отсечка)."""
    stock = "stock"
    preorder = "preorder"


class Source(str, enum.Enum):
    onec = "onec"
    manual = "manual"


class OrderStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    confirmed = "confirmed"
    rejected = "rejected"
    assembling = "assembling"
    shipped = "shipped"
    accepted = "accepted"
    closed = "closed"
    cancelled = "cancelled"


class ExchangeStatus(str, enum.Enum):
    queued = "queued"
    done = "done"
    failed = "failed"


class Enterprise(Base):
    __tablename__ = "enterprises"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120), default="")
    # Куда ведёт кнопка «Связаться» у клиента: продукт заменяет заявку по
    # телефону, а не сам разговор. Способ выбирает поставщик: «max» — профиль
    # в MAX, «phone» — номер телефона. Значения хранятся раздельно: в одном
    # поле телефон после переключения способа выдавал себя за профиль MAX.
    contact_kind: Mapped[str] = mapped_column(String(10), default="", server_default="")
    contact_phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    contact_max: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # «Написать в MAX» у общего контакта. Ссылку на профиль больше не
    # вписывают руками: человек в MAX и так известен, бот присылает клиенту
    # карточку владельца. Поставщик только решает, можно ли ему писать.
    max_chat: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Поставщик-бот для проверяющих (app/testbots.py): его витрину видят
    # магазины любого города, и она помечена как тестовая.
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    storefronts: Mapped[list["Storefront"]] = relationship(back_populates="enterprise")


class Employee(Base):
    """Роль привязана к паре «пользователь MAX ↔ предприятие»:
    владелец пекарни одновременно клиент кондитерской базы."""
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id"))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    name: Mapped[str] = mapped_column(String(200), default="")
    # Диалог с ботом. Заполняется при bot_started, без него уведомлять некуда.
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # График: дни через запятую («пн,вт,ср») и часы. Нужен клиенту — кто
    # сейчас на связи, — поэтому хранится по-человечески, а не битовой маской.
    work_days: Mapped[str] = mapped_column(String(40), default="", server_default="")
    work_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    work_to: Mapped[time | None] = mapped_column(Time, nullable=True)


class ClientManager(Base):
    """Закреплённый за клиентом менеджер — один на пару «предприятие ↔
    клиент»: кафе покупает у нескольких поставщиков, и у каждого свой.

    Закрепление меняет две вещи: в «Связаться» у клиента этот менеджер
    стоит первым, и о новых заявках клиента пишем ему и владельцу, а не
    всем сотрудникам подряд.
    """
    __tablename__ = "client_managers"
    __table_args__ = (
        Index("ux_client_managers_pair", "enterprise_id", "client_id", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Client(Base):
    """Точка — магазин, киоск, кафе. max_user_id — её владелец."""
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300), default="")
    # Один город из справочника, как у поставщика: по нему полка показывает
    # поставщиков рядом. Пусто — полка всех городов.
    city: Mapped[str] = mapped_column(String(120), default="", server_default="")
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Магазин-бот для проверяющих (app/testbots.py).
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class ClientWorker(Base):
    """Работник магазина — то же, что менеджер у поставщика, только у точки.

    Заказывает, принимает товар и пишет поставщику от имени магазина.
    График нужен той же цели, что у менеджера: поставщик видит, кто сейчас
    на месте и кому звонить по заявке.
    """
    __tablename__ = "client_workers"
    __table_args__ = (
        Index("ux_client_workers_pair", "client_id", "max_user_id", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    work_days: Mapped[str] = mapped_column(String(40), default="", server_default="")
    work_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    work_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Storefront(Base):
    __tablename__ = "storefronts"
    id: Mapped[int] = mapped_column(primary_key=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id"))
    name: Mapped[str] = mapped_column(String(200))
    initials: Mapped[str] = mapped_column(String(4), default="")
    mode: Mapped[Mode] = mapped_column(Enum(Mode, name="mode"))
    source: Mapped[Source] = mapped_column(Enum(Source, name="source"), default=Source.manual)
    # Видимость: публичная витрина попадает в полку города
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    # Оптовик не готов светить прайс конкурентам — по умолчанию выключено
    show_prices_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # Оформление витрины. Логотипа у оптовика чаще нет, чем есть, поэтому
    # оба поля необязательные: без них карточка рисуется цветом из названия.
    logo_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Фото витрины — большая картинка в карточке и в шапке каталога: по нему
    # витрину узнают быстрее, чем по логотипу.
    cover_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    about: Mapped[str] = mapped_column(String(160), default="", server_default="")

    # График доставки и отсечка
    delivery_days: Mapped[str] = mapped_column(String(40), default="")
    cutoff_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    min_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Своя база 1С у витрины, а не у предприятия: прайс со склада и прайс
    # пекарни живут в разных базах чаще, чем в одной. Ключ вида
    # «база.секрет» несёт в себе адрес, поэтому поле одно.
    onec_key: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Адрес боевой базы. Для стенда не нужен — он выводится из ключа.
    onec_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    # Служебный пользователь своей базы и его пароль — зашифрованным
    # (app/secret_box.py): наружу пароль не отдаётся никогда.
    onec_user: Mapped[str] = mapped_column(String(100), default="", server_default="")
    onec_password: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Конфигурация базы и реквизиты заказа: организация, склад, вид цен,
    # валюта, контрагент по умолчанию — см. app/onec/settings.py.
    onec_settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Решение поставщика, как в «Моби-С»: заказ сразу резервирует товар в 1С
    # или ждёт подтверждения «На согласовании», а до него резерв держит
    # приложение.
    onec_reserve_now: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # За сколько минут до отсечки напоминать молчащему клиенту. Это решение
    # поставщика, а не наша константа: пекарня будит за час, оптовая база —
    # с вечера, и обоим нужно своё.
    remind_before_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    stock_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Когда витрину завели. У витрин старше миграции 0034 пусто: по этому
    # полю бот-магазин приходит только к новым витринам.
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )

    enterprise: Mapped[Enterprise] = relationship(back_populates="storefronts")
    items: Mapped[list["StorefrontItem"]] = relationship(back_populates="storefront")


class Connection(Base):
    __tablename__ = "connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Когда клиент подключился. Без этого «перестал заказывать» срабатывает
    # на том, кто подключился вчера и просто не успел сделать первую заявку.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorefrontItem(Base):
    __tablename__ = "storefront_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id"))
    external_id: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(20), default="шт")
    # Дробная кратность — не экзотика: сыр и колбаса идут по 0,4 кг.
    # Точность до одной десятой, см. app/quantity.py.
    pack_size: Mapped[float] = mapped_column(Numeric(10, 1), default=1)
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    stock: Mapped[float] = mapped_column(Numeric(12, 1), default=0)
    daily_limit: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    # Меньше этого в одной заявке не заказать; None — хватает упаковки.
    # Задаёт поставщик и у витрины на 1С: в типовой УТ такого реквизита нет.
    min_qty: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    # Ключ снимка в объектном хранилище. У оптовика фотографий обычно нет,
    # поэтому поле необязательное, а без него рисуется плитка по названию.
    photo_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Из 1С описание не приходит: его пишет поставщик в приложении, и
    # синхронизация его не трогает.
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Скрыта из витрины: позицию с историей заказов удалить нельзя, а
    # нулевой остаток у витрины «под заказ» её не прячет — дневной лимит
    # остаётся. Клиент скрытую не видит и заказать не может, в прошлых
    # заявках она остаётся.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Ссылка на позицию в 1С (Ref_Key, GUID): документы 1С ссылаются на
    # номенклатуру только ею. Артикул остаётся в external_id.
    onec_ref: Mapped[str] = mapped_column(String(40), default="", server_default="")
    # Позиции больше нет в 1С — удалили или пометили на удаление. Такая
    # позиция скрыта (hidden), а эта отметка говорит, что скрыла её сверка:
    # вернётся в 1С — вернётся и в витрину.
    onec_missing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    storefront: Mapped[Storefront] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    delivery_date: Mapped[date] = mapped_column(Date)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="order_status"), default=OrderStatus.sent)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Номер у поставщика (app/numbering.py); id — внутренний, сквозной.
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def label(self) -> int:
        """Что показывать людям после «№»."""
        return self.number or self.id
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onec_document: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Товар заявки уже вычтен из остатка витрины. У витрины из 1С — когда
    # заказ встал в учёт, у витрины без 1С — при подтверждении. Пока нет,
    # заявка держит товар резервом, и «доступно» считается за её вычетом.
    stock_taken: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Документ корректировки по итогам приёмки: недовоз и брак должны
    # вернуться в учёт, иначе 1С останется с суммой, которую никто не привёз.
    onec_correction: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Что менеджер написал клиенту при подтверждении с изменениями или при
    # отказе. Причину знает только он — придумывать её за него нельзя.
    supplier_comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Клиент принял заявку до отметки об отгрузке: машина приехала раньше,
    # чем менеджер успел нажать кнопку.
    accepted_early: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Когда клиент принял товар. Принял раньше дня доставки — заявка так и
    # пишет, а не «Доставка» на день, до которого товар уже приехал.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Кто ведёт заявку у поставщика: закреплённый за клиентом менеджер, а без
    # него — тот, кто первым её обработал. Клиент видит имя рядом с номером.
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    # Кто оформил заявку со стороны магазина: владелец точки или работник.
    # Ему — уведомления о заявке, его имя и телефон видит поставщик.
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", lazy="selectin")


class OrderItem(Base):
    """Три количества: заказано, подтверждено, принято — их нельзя смешивать."""
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("storefront_items.id"))
    qty_ordered: Mapped[float] = mapped_column(Numeric(12, 1))
    qty_confirmed: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    qty_accepted: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    change_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Недовоз, пересорт, брак, срок годности — фиксация факта, не накладная
    acceptance_issue: Mapped[str | None] = mapped_column(String(40), nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")


class ExchangeEvent(Base):
    """Журнал обмена с 1С: что ушло, что не ушло и почему."""
    __tablename__ = "exchange_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[str] = mapped_column(String(10))
    object_kind: Mapped[str] = mapped_column(String(40))
    # Привязка к предприятию, а не только к заявке: входящая синхронизация
    # заявки не касается, но в журнале владельца обязана быть видна.
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    status: Mapped[ExchangeStatus] = mapped_column(Enum(ExchangeStatus, name="exchange_status"))
    external_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AcceptancePhoto(Base):
    """Снимок расхождения при приёмке.

    Ключ объекта, а не URL: бакет закрыт, ссылку выдаёт API после проверки
    прав, поэтому фото чужой заявки не открыть по угаданному адресу.
    """
    __tablename__ = "acceptance_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("storefront_items.id"), nullable=True)
    object_key: Mapped[str] = mapped_column(String(120), unique=True)
    content_type: Mapped[str] = mapped_column(String(60), default="image/jpeg")
    # Снимок загружается сразу после съёмки, а частью заявки становится только
    # при приёмке. Отменил расхождение — снимок в заявку не попадёт.
    attached: Mapped[bool] = mapped_column(Boolean, default=False, server_default="true")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceChange(Base):
    """История цен: копится сама, чтобы поставщик мог показать клиенту,
    когда и на сколько менялась цена."""
    __tablename__ = "price_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("storefront_items.id"), index=True)
    old_price: Mapped[float] = mapped_column(Numeric(12, 2))
    new_price: Mapped[float] = mapped_column(Numeric(12, 2))
    changed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(Base):
    """Приглашение по диплинку.

    Код короткий намеренно: диплинк MAX ограничен 128 символами для бота
    и 512 для мини-приложения, а UUID съедает их без пользы.
    """
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # client | manager | worker
    # Приглашение поставщика — в предприятие; приглашение работника — в точку.
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    storefront_id: Mapped[int | None] = mapped_column(ForeignKey("storefronts.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Личное приглашение — из списка «Кто запускал бота»: принять его может
    # только этот человек. Пусто — ссылка, которую передают кому угодно.
    for_user: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    used_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InviteSend(Base):
    """Приглашение, которое бот отправил из списка «Кто запускал бота».

    Этот список видит любой владелец, а пишет бот от имени всего сервиса —
    поэтому таких сообщений в день не больше лимита. Считаем по тому, кто
    отправил, а не по предприятию: «Начать заново» заводит новое
    предприятие, и счётчик по нему обнулялся бы.
    """
    __tablename__ = "invite_sends"
    __table_args__ = (Index("ix_invite_sends_sender_at", "sender_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(BigInteger)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderTemplate(Base):
    """Шаблон регулярной заявки.

    «Повторить прошлый заказ» закрывает один случай — вчерашний заказ. Но
    у магазина заказы разные по дням: в пятницу берут вдвое больше, чем в
    среду. Шаблон — это именованный набор количеств, который не затирается
    следующей заявкой.
    """
    __tablename__ = "order_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["OrderTemplateLine"]] = relationship(
        back_populates="template", lazy="selectin", cascade="all, delete-orphan"
    )


class OrderTemplateLine(Base):
    __tablename__ = "order_template_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("order_templates.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("storefront_items.id"))
    qty: Mapped[float] = mapped_column(Numeric(12, 1))

    template: Mapped[OrderTemplate] = relationship(back_populates="lines")


class Reminder(Base):
    """След отправленного напоминания.

    Нужен ради идемпотентности: планировщик просыпается раз в несколько
    минут, и без отметки клиент получил бы «завтра отсечка» двенадцать раз
    подряд. Ключ — то, про что напоминаем: дата отгрузки или день подсказки.
    """
    __tablename__ = "reminders"
    # NULLS NOT DISTINCT: у напоминания менеджеру client_id пустой, и без
    # этой оговорки Postgres считал бы такие строки разными.
    __table_args__ = (
        Index(
            "ux_reminders_once",
            "kind", "client_id", "enterprise_id", "storefront_id", "key",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), nullable=True)
    storefront_id: Mapped[int | None] = mapped_column(ForeignKey("storefronts.id"), nullable=True)
    key: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BotUser(Base):
    """Кто запускал бота.

    Список клиентов поставщика берётся отсюда: пригласить можно только того,
    с кем у бота есть диалог, — иначе приглашение некуда доставить. Запись
    появляется на `bot_started` и на любом сообщении боту.
    """
    __tablename__ = "bot_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    username: Mapped[str] = mapped_column(String(120), default="")
    # Правки из «Аккаунта». Имя из MAX приходит при каждом входе, и без
    # отметки оно затирало бы то, что человек исправил сам.
    name_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    # Можно ли писать человеку в MAX. Ссылку на профиль не спрашиваем: по
    # «Написать» бот присылает карточку контакта, а человек решает только,
    # готов ли он к сообщениям.
    max_reachable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def title(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name])) or f"id {self.max_user_id}"


class PromoKind(str, enum.Enum):
    """Четыре повода дать скидку — больше в опте и не встречается."""
    item = "item"            # на позицию
    storefront = "storefront"  # на всю витрину
    volume_amount = "volume_amount"  # при заказе от суммы
    volume_qty = "volume_qty"        # при заказе позиции от количества; без позиции — любой


class Promo(Base):
    """Акция витрины.

    Скидка настоящая: она меняет цену в каталоге и попадает в заявку —
    акция, о которой знает только баннер, клиента раздражает, а не
    привлекает.

    Акцию видят только подключённые — в каталоге витрины: так поставщик
    даёт цену своим, не показывая её конкурентам. Ленты акций в «Витринах
    города» больше нет (решение пользователя).
    """
    __tablename__ = "promos"
    id: Mapped[int] = mapped_column(primary_key=True)
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("storefront_items.id"), nullable=True)
    kind: Mapped[PromoKind] = mapped_column(
        Enum(PromoKind, name="promo_kind"), default=PromoKind.item, server_default="item"
    )
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    discount_percent: Mapped[float] = mapped_column(Numeric(5, 1), default=0)
    # Пороги для объёмных акций: от суммы заявки или от количества позиции
    min_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_qty: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    # Не используется: флажок ленты акций, которой больше нет. Колонку не
    # удаляли, чтобы не выкатывать миграцию ради пустого поля.
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Уведомление в приложении.

    Раньше уведомления существовали только как сообщения в MAX: не пришло —
    и следа нет. Своя лента нужна ради двух вещей: счётчик непрочитанного
    в аккаунте и возможность увидеть пропущенное, не листая чат с ботом.
    """
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="info")
    text: Mapped[str] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    storefront_id: Mapped[int | None] = mapped_column(ForeignKey("storefronts.id"), nullable=True)
    # В какой роли человек получил уведомление: заявку поставщика кнопка
    # открывает в роли сотрудника, свою заявку — в роли клиента.
    role: Mapped[str] = mapped_column(String(10), default="", server_default="")
    # Дошло ли сообщение в MAX. Владельцу полезно отличать «не читал»
    # от «не получил»: во втором случае дело не в клиенте.
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    # В MAX не отправляли: человек отключил такие кнопкой под сообщением.
    # Иначе лента писала бы «не доставлено», хотя дело не в доставке.
    muted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Favorite(Base):
    """Избранное человека: у магазина — витрины, товары и сотрудники
    поставщика, у поставщика — клиенты.

    Своё у каждого человека, а не у точки или предприятия: менеджеры одного
    склада держат под рукой разных клиентов. Ссылка — без внешнего ключа:
    удалённая витрина или отключённый клиент из списка просто пропадают,
    а не валят удаление.
    """
    __tablename__ = "favorites"
    __table_args__ = (
        Index("ux_favorites_once", "max_user_id", "kind", "target_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(12))  # storefront | item | employee | client
    target_id: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationMute(Base):
    """Вид уведомлений, который человек не хочет получать в MAX — см. mutes.py."""
    __tablename__ = "notification_mutes"
    __table_args__ = (
        Index("ux_notification_mutes_once", "max_user_id", "kind", "side", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(30))
    # «staff» — сотрудник поставщика, «shop» — магазин, пусто — без стороны
    side: Mapped[str] = mapped_column(String(10), default="", server_default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OneCCounterparty(Base):
    """Каким контрагентом 1С магазин оформляется в заказах этой витрины.

    Без сопоставления заказ уходит на контрагента по умолчанию из настроек
    витрины — удобно для «Розничного покупателя», но учёт по магазинам в
    1С тогда не сведёшь.
    """
    __tablename__ = "onec_counterparties"
    id: Mapped[int] = mapped_column(primary_key=True)
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    contractor_key: Mapped[str] = mapped_column(String(40))
    partner_key: Mapped[str] = mapped_column(String(40), default="", server_default="")
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
