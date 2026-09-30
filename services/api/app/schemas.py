"""Формы ответов API. Совпадают с тем, что рисует фронт."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class MembershipOut(BaseModel):
    role: str
    title: str


class ScheduleOut(BaseModel):
    days: list[str] = []
    start: str = ""
    end: str = ""
    # «пн–пт 9:00–18:00» — как увидит клиент
    text: str = ""
    on_shift: bool | None = None


class ScheduleIn(BaseModel):
    """Пустые дни — «график не указан»: в «Связаться» сотрудник не попадёт."""
    days: list[str] = []
    start: str = ""
    end: str = ""


class MeOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str = ""
    role: str | None
    title: str
    needs_onboarding: bool = False
    start_param: str | None = None
    # Счётчик для значка на вкладке «Аккаунт»
    unread: int = 0
    # Правится в «Аккаунте». Телефон нужен поставщику, чтобы перезвонить
    phone: str = ""
    # Адрес доставки активной точки клиента; у сотрудника пусто
    address: str = ""
    # Город активной точки: по нему полка показывает поставщиков рядом
    city: str = ""
    # График сотрудника: по нему клиент видит, кто сейчас на связи
    schedule: ScheduleOut | None = None
    # Можно ли писать человеку в MAX — тумблер в «Аккаунте»
    max_reachable: bool = True
    # У покупателя есть подключённые витрины — приложение открывается на
    # «Моих витринах», где «Повторить», а не на поиске поставщиков
    has_storefronts: bool = False
    # Активная точка — демо-магазин стенда: в шапке пометка «Тестовые данные»
    demo_shop: bool = False
    memberships: list[MembershipOut]


class ProfileIn(BaseModel):
    """Что человек может поправить о себе сам. Поле не передано — не трогаем."""
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    max_reachable: bool | None = None
    # Только для владельца точки: название, адрес доставки и город
    client_name: str | None = None
    address: str | None = None
    city: str | None = None


class BadgesOut(BaseModel):
    """Счётчики на вкладках. Отдельно от /me: их опрашивают часто."""
    unread: int = 0
    # Сотруднику — новые заявки, ждущие решения; клиенту — отгруженные,
    # которые пора принять
    orders: int = 0
    # Владельцу — просьбы о подключении, ждущие решения: число у пункта
    # «Подключения» на главной. Значок на вкладке — в «Аккаунте», по ленте.
    connections: int = 0
    # Номер последнего уведомления: приложение, вернувшееся из чата, видит,
    # что пришло, пока его не было, и открывает нужный экран.
    last_notification: int = 0


class LastOrderOut(BaseModel):
    id: int
    date: date
    total: float


class StorefrontOut(BaseModel):
    id: int
    name: str
    initials: str
    # Оформление: логотип, фото и цвет карточки задаёт поставщик
    logo_url: str | None = None
    cover_url: str | None = None
    color: str | None = None
    about: str = ""
    mode: str
    # «onec» — остаток из 1С, «manual» — ведёт сам поставщик
    source: str = "manual"
    delivery_days: str
    stock_synced_at: datetime | None = None
    # «Заказ до 16:00» на плитке; у складской витрины пусто
    cutoff_at: str | None = None
    cutoff_in_minutes: int | None = None
    next_delivery_date: date | None = None
    last_order: LastOrderOut | None = None
    # «Обычно раз в 7 дн., прошло 9» — подсказка по ритму клиента
    hint: str | None = None
    # Сколько из обещанного доезжает. None — заявок ещё слишком мало
    shipping_accuracy: float | None = None


class ItemOut(BaseModel):
    id: int
    name: str
    unit: str
    pack_size: float
    price: float
    available: float
    is_low: bool
    daily_limit: float | None = None
    # Меньше этого в заявку не положить — минимум поставщика, уже кратный
    # упаковке. None — хватает одной упаковки
    min_qty: float | None = None
    photo_url: str | None = None
    # Цена до скидки и название акции — чтобы клиент видел, откуда она взялась
    price_before: float | None = None
    promo: str | None = None
    # Пишет поставщик в приложении; в карточке товара, пусто — не показываем
    description: str = ""


class PromoOut(BaseModel):
    id: int
    kind: str = "item"
    title: str
    description: str = ""
    discount_percent: float = 0
    item_id: int | None = None
    item_name: str = ""
    min_amount: float | None = None
    min_qty: float | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True
    # Человекочитаемое условие: «−10 % при заказе от 5 000 ₽»
    condition: str = ""
    # Действует ли прямо сейчас: выключенная или просроченная акция
    # остаётся в списке у владельца, но в каталог не попадает
    is_live: bool = False


class PromoIn(BaseModel):
    kind: str = "item"
    title: str
    description: str = ""
    discount_percent: float = 0
    item_id: int | None = None
    min_amount: float | None = None
    min_qty: float | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True


class StorefrontDetailOut(StorefrontOut):
    is_demo: bool
    # «Связаться» на странице витрины: вопрос к поставщику бывает до заявки
    supplier: str = ""
    # Город поставщика — в карточке витрины, как на полке
    city: str = ""
    supplier_contact: str = ""
    contact_kind: str = ""
    contact_href: str = ""
    # Объёмные акции: их показываем условием, цена меняется в заявке
    volume_promos: list[PromoOut] = []
    min_amount: float | None = None
    delivery_dates: list[date]
    promos: list[PromoOut] = []
    items: list[ItemOut]


class OrderLineIn(BaseModel):
    item_id: int
    qty: float


class OrderIn(BaseModel):
    storefront_id: int
    delivery_date: date | None = None
    comment: str = ""
    lines: list[OrderLineIn]


class PhotoOut(BaseModel):
    key: str
    url: str
    item_id: int | None = None


class OrderLineOut(BaseModel):
    item_id: int
    name: str
    unit: str
    price: float
    pack_size: float = 1
    # Минимум позиции, уже кратный упаковке: ниже него поставщик при
    # подтверждении не уменьшает. None — минимума нет, предел — упаковка.
    min_qty: float | None = None
    acceptance_issue: str | None = None
    # Остаток 1С на момент просмотра: менеджеру нужен, чтобы увидеть расхождение
    stock: float = 0
    qty_ordered: float
    qty_confirmed: float | None = None
    qty_accepted: float | None = None
    change_reason: str | None = None
    photo_url: str | None = None


class OrderOut(BaseModel):
    id: int
    # Номер у поставщика — его и показываем людям; id — для ссылок
    number: int
    storefront_id: int
    storefront_name: str
    storefront_mode: str = "stock"
    # «onec» — остаток из 1С; иначе его ведёт сам поставщик
    storefront_source: str = "manual"
    stock_synced_at: datetime | None = None
    client_name: str
    status: str
    delivery_date: date
    created_at: datetime
    comment: str = ""
    onec_document: str | None = None
    onec_correction: str | None = None
    # Чтобы «связаться с поставщиком» вело к человеку, а не в пустоту.
    # contact_href — готовый адрес: https://max.ru/… или tel:+7…
    supplier: str = ""
    supplier_contact: str = ""
    contact_kind: str = ""
    contact_href: str = ""
    # Комментарий менеджера к изменениям или к отказу
    supplier_comment: str = ""
    accepted_early: bool = False
    # У заявок, принятых до появления этого поля, его может не быть
    accepted_at: datetime | None = None
    # Куда везти и кому звонить — менеджеру, собирающему заявку.
    # client_chat_href — профиль клиента в MAX по его публичному нику.
    client_address: str = ""
    client_phone: str = ""
    client_phone_href: str = ""
    client_chat_href: str = ""
    client_id: int = 0
    # Кто оформил заявку со стороны клиента — имя человека, не точки
    author: str = ""
    # Оформил работник магазина — его номер: «Написать» шлёт его карточку
    author_worker_id: int | None = None
    # Разрешил ли автор писать себе в MAX
    client_reachable: bool = True
    # Кто ведёт заявку у поставщика: закреплённый или первым обработавший
    manager_id: int | None = None
    manager: str = ""
    onec_status: str | None = None
    # Когда поставщик подтвердил. Отказ после подтверждения — это отменённая
    # поставка, а не отклонённая заявка, и клиент видит это по-разному.
    confirmed_at: datetime | None = None
    # Доставка прошла, а отгрузку не отметили: поставщику — вопрос
    # «всё в порядке?» и три действия прямо в заявке.
    ship_overdue: bool = False
    total_ordered: float
    total_confirmed: float | None = None
    photos: list[PhotoOut] = []
    lines: list[OrderLineOut]


class ConfirmLineIn(BaseModel):
    item_id: int
    qty: float
    reason: str | None = None


class ConfirmIn(BaseModel):
    lines: list[ConfirmLineIn] = []
    # Клиент видит его рядом с изменениями: почему стало не так, как заказывал
    comment: str = ""


class RejectIn(BaseModel):
    reason: str = ""


class RescheduleIn(BaseModel):
    delivery_date: date
    # Что сказать клиенту: «машина сломалась, привезём в пятницу»
    comment: str = ""


class AcceptLineIn(BaseModel):
    item_id: int
    qty: float
    issue: str | None = None


class AcceptIn(BaseModel):
    lines: list[AcceptLineIn] = []
    # Ключи снимков, которые остаются в заявке. Снимки, снятые и потом
    # отменённые вместе с расхождением, сюда не попадают и удаляются.
    # None — старый клиент: прикрепляем всё загруженное.
    photos: list[str] | None = None


class SummaryLineOut(BaseModel):
    item_id: int
    name: str
    unit: str
    qty: float


class AssemblyOrderOut(BaseModel):
    order_id: int
    number: int = 0
    client_name: str
    lines: list[SummaryLineOut]


class ProductionSummaryOut(BaseModel):
    date: date
    dates: list[date] = []
    orders: int
    # Заявки на эту дату, которые ещё не подтвердили: в сводку они не
    # попали, и без этой строки менеджер печёт меньше, чем закажут
    pending: int = 0
    totals: list[SummaryLineOut]
    assembly: list[AssemblyOrderOut]


class TopItemOut(BaseModel):
    item_id: int
    name: str
    unit: str
    qty: float


class ClientRowOut(BaseModel):
    id: int
    name: str
    address: str = ""
    orders: int = 0
    last_order_at: datetime | None = None
    connected_at: datetime | None = None
    # Закреплённый менеджер — имя, пусто — не закреплён
    manager: str = ""


class ClientStorefrontOut(BaseModel):
    id: int
    name: str
    # active | request | blocked
    status: str
    # Подключение — чтобы отключить клиента от витрины прямо из карточки
    connection_id: int


class ClientOrderOut(BaseModel):
    id: int
    number: int = 0
    storefront: str
    status: str
    delivery_date: date
    total: float


class StaffOptionOut(BaseModel):
    id: int
    name: str
    role: str
    hours: str = ""


class ShopPersonOut(BaseModel):
    """Человек магазина: владелец точки или работник."""
    # Номер работника; у владельца точки — null
    worker_id: int | None = None
    name: str
    # client — владелец точки, worker — работник
    role: str
    on_shift: bool | None = None
    hours: str = ""
    next: str = ""
    phone: str = ""
    phone_href: str = ""
    chat_href: str = ""
    # Разрешил ли писать себе в MAX
    reachable: bool = True


class ClientDetailOut(BaseModel):
    """Карточка клиента у владельца: кто, как связаться, что заказывал и
    кто его ведёт."""
    id: int
    name: str
    address: str = ""
    # Человек за точкой — как его зовут в MAX
    person: str = ""
    phone: str = ""
    phone_href: str = ""
    chat_href: str = ""
    storefronts: list[ClientStorefrontOut] = []
    orders: int = 0
    revenue: float = 0
    last_order_at: datetime | None = None
    recent: list[ClientOrderOut] = []
    manager_id: int | None = None
    staff: list[StaffOptionOut] = []
    # Люди магазина: владелец и работники — кто сейчас на месте
    people: list[ShopPersonOut] = []


class ClientManagerIn(BaseModel):
    """null — снять закрепление."""
    employee_id: int | None = None


class EmployeeRowOut(BaseModel):
    id: int
    name: str
    role: str
    notifications: bool
    # График и телефон — то, что видит клиент в «Связаться»
    hours: str = ""
    on_shift: bool | None = None
    phone: str = ""
    # Скольких клиентов ведёт
    clients: int = 0


class TeamContactOut(BaseModel):
    """Сотрудник в окне «Связаться» у клиента."""
    id: int
    name: str
    role: str
    # Закреплён за этим клиентом
    personal: bool = False
    # None — график не указан (так бывает только у закреплённого)
    on_shift: bool | None = None
    hours: str = ""
    # Когда снова на связи: «завтра с 9:00»
    next: str = ""
    phone: str = ""
    phone_href: str = ""
    # Прямая ссылка на профиль по публичному нику; пусто — «Написать»
    # присылает карточку контакта в чат с ботом
    chat_href: str = ""
    # Ведёт заявку, из которой открыли окно
    handles_order: bool = False
    # Разрешил писать себе в MAX: без этого «Написать» у него нет
    reachable: bool = True


class ContactsOut(BaseModel):
    supplier: str = ""
    people: list[TeamContactOut] = []
    # Общий контакт предприятия — телефон или профиль из «Предприятия»
    general_kind: str = ""
    general: str = ""
    general_href: str = ""
    # Телефон предприятия и «Написать в MAX» — оба сразу, если есть
    general_phone: str = ""
    general_phone_href: str = ""
    # Кому «Написать в MAX» от имени предприятия — сотрудник-владелец
    general_employee_id: int | None = None


class ReachIn(BaseModel):
    """С кем связаться: сотрудник поставщика (для клиента), клиент или
    работник магазина (для сотрудника)."""
    employee_id: int | None = None
    client_id: int | None = None
    worker_id: int | None = None


class CityOut(BaseModel):
    name: str
    # Область — чтобы отличить Троицк московский от челябинского
    region: str = ""


class ReachOut(BaseModel):
    # Карточка ушла в чат с ботом
    sent: bool = False
    # Прямая ссылка, если у человека есть публичный ник
    chat_href: str = ""
    # Чат с ботом, куда пришла карточка
    bot_href: str = ""


class ExchangeRowOut(BaseModel):
    id: int
    direction: str
    object_kind: str
    order_id: int | None
    status: str
    external_key: str | None
    message: str
    at: datetime


class OwnerSummaryOut(BaseModel):
    enterprise: str
    city: str = ""
    storefronts_total: int = 0
    revenue_week: float
    revenue_total: float
    orders_total: int
    orders_new: int = 0
    clients_total: int
    shipping_accuracy: float | None
    top_items: list[TopItemOut]
    sleeping_clients: list[ClientRowOut]
    # Цифры у пунктов меню: что внутри, не открывая
    connections_pending: int = 0
    staff_total: int = 0
    profile_percent: int = 0
    profile_missing: list[str] = []
    exchange_queued: int = 0
    onec_linked: int = 0
    planned_orders: int = 0
    planned_date: date | None = None


class StorefrontSettingsOut(BaseModel):
    id: int
    name: str
    mode: str
    source: str
    is_public: bool = False
    show_prices_public: bool = False
    delivery_days: str
    cutoff_at: str | None
    min_amount: float | None
    remind_before_minutes: int = 60
    shipping_accuracy: float | None = None
    logo_url: str | None = None
    cover_url: str | None = None
    color: str | None = None
    about: str = ""
    # Имя базы 1С, к которой подключена витрина. Пусто — ведётся вручную
    onec_base: str = ""
    # Как подключена 1С: key — тестовая база по ключу, own — своя база по
    # адресу и паролю, stand — база стенда (демо), пусто — без 1С
    onec_mode: str = ""
    onec_url: str = ""
    onec_user: str = ""
    # Пароль сохранён. Сам пароль наружу не отдаётся никогда
    onec_has_password: bool = False
    onec_preset: str = ""
    # Выбранные реквизиты заказа: {организация: {key, name}, …}
    onec_refs: dict[str, dict[str, str]] = {}
    # Каких обязательных реквизитов не хватает, чтобы заказ провёлся
    onec_missing: list[str] = []
    onec_reserve_now: bool = False
    items: int


class StorefrontSettingsIn(BaseModel):
    name: str | None = None
    mode: str | None = None
    source: str | None = None
    color: str | None = None
    about: str | None = None
    onec_key: str | None = None
    onec_url: str | None = None
    onec_user: str | None = None
    # Пусто или не передан — оставить сохранённый
    onec_password: str | None = None
    onec_preset: str | None = None
    # Реквизиты заказа: {organization: {key, name}, contractor: {key, name, partner}}
    onec_refs: dict[str, dict[str, str]] | None = None
    onec_reserve_now: bool | None = None
    cutoff_at: str | None = None
    delivery_days: str | None = None
    min_amount: float | None = None
    remind_before_minutes: int | None = None
    is_public: bool | None = None
    show_prices_public: bool | None = None


class ConnectionRowOut(BaseModel):
    id: int
    client_id: int
    client_name: str
    storefront_id: int
    storefront_name: str
    status: str
    # Витрина ведётся в 1С: подключая клиента, владелец сразу выбирает, каким
    # контрагентом он пойдёт в заказы. onec_default — контрагент по
    # умолчанию из настроек витрины: на него уйдёт заявка без выбора.
    onec: bool = False
    onec_default: str = ""


class ConnectionDecisionIn(BaseModel):
    """Решение по подключению. При одобрении — кто ведёт клиента и, у витрины
    на 1С, каким контрагентом он пойдёт в заказы; пусто — по умолчанию."""
    employee_id: int | None = None
    contractor_key: str = ""
    partner_key: str = ""
    contractor_name: str = ""


class ItemRowOut(BaseModel):
    id: int
    name: str
    unit: str
    pack_size: float
    price: float
    stock: float
    daily_limit: float | None = None
    # Минимум в одной заявке; None — без минимума
    min_qty: float | None = None
    photo_url: str | None = None
    description: str = ""
    # Скрыта из витрины: клиент её не видит
    hidden: bool = False
    # Скрыла сверка: позиции больше нет в 1С
    onec_missing: bool = False


class ItemEditIn(BaseModel):
    name: str | None = None
    unit: str | None = None
    price: float | None = None
    stock: float | None = None
    pack_size: float | None = None
    daily_limit: float | None = None
    # Ноль снимает минимум, как у дневного лимита
    min_qty: float | None = None
    description: str | None = None
    hidden: bool | None = None


class PriceChangeOut(BaseModel):
    id: int
    old_price: float
    new_price: float
    at: datetime


class TemplateLineIn(BaseModel):
    item_id: int
    qty: float


class TemplateIn(BaseModel):
    storefront_id: int
    name: str = ""
    # Либо явные позиции из корзины, либо «сохранить вот эту заявку».
    lines: list[TemplateLineIn] = []
    order_id: int | None = None


class TemplateLineOut(BaseModel):
    item_id: int
    name: str
    unit: str
    qty: float


class TemplateOut(BaseModel):
    id: int
    storefront_id: int
    name: str
    total: float
    lines: list[TemplateLineOut]


class ImportReportOut(BaseModel):
    """Отчёт о загрузке прайса. Показывается и при предпросмотре, и после."""
    preview: bool = False
    rows: int
    created: int
    updated: int
    unchanged: int
    changes: list[str] = []
    problems: list[str] = []


class EnterpriseOut(BaseModel):
    id: int
    name: str
    city: str = ""
    # Выбранный способ и значения обоих; contact — куда кнопка ведёт сейчас
    contact_kind: str = ""
    contact: str = ""
    contact_phone: str = ""
    contact_max: str = ""
    # Клиенты могут написать в MAX — бот пришлёт им карточку владельца
    max_chat: bool = False
    is_demo: bool = False
    storefronts: int = 0
    # Насколько заполнен профиль, который видит клиент, и чего не хватает
    profile_percent: int = 0
    profile_missing: list[str] = []


class EnterpriseIn(BaseModel):
    name: str | None = None
    city: str | None = None
    # «max» или «phone» — куда ведёт кнопка «Связаться»
    contact_kind: str | None = None
    contact_phone: str | None = None
    contact_max: str | None = None
    max_chat: bool | None = None
    # Прежний способ: одно значение для выбранного contact_kind
    contact: str | None = None


class StorefrontCreateIn(BaseModel):
    name: str
    mode: str = "stock"
    source: str = "manual"
    delivery_days: str = ""
    cutoff_at: str | None = None
    min_amount: float | None = None
    # Ключ базы 1С вида «база.секрет». Указан — витрина ведётся из 1С
    onec_key: str = ""
    onec_url: str = ""
    # Открытая — на полке города, клиенты сами просят подключения
    is_public: bool = False


class ItemCreateIn(BaseModel):
    name: str
    unit: str = "шт"
    pack_size: float = 1
    price: float
    stock: float = 0
    daily_limit: float | None = None
    min_qty: float | None = None
    external_id: str = ""
    description: str = ""


class AudienceRowOut(BaseModel):
    """Человек, с которым у бота есть диалог. Пригласить можно только его:
    приглашение тому, кто бота не запускал, доставить некуда."""
    max_user_id: int
    name: str
    username: str = ""
    started_at: datetime
    last_seen_at: datetime | None = None
    # Диалог с ботом заведён. Для уведомлений не обязателен — пишем по user_id,
    # — но поставщику полезно видеть, с кем бот уже знаком.
    has_dialog: bool = False
    # Что у него уже есть в этом предприятии
    is_client: bool = False
    storefronts: list[str] = []
    # Куда позвали, а он ещё не ответил: приглашение ждёт в чате с ботом
    invited: list[str] = []
    # Ответ на «Пригласить»: дошло ли приглашение в чат. Не дошло — оно всё
    # равно ждёт человека в приложении.
    delivered: bool = True


class PendingInviteOut(BaseModel):
    """Личное приглашение, которое человек ещё не принял и не отклонил."""
    code: str
    kind: str
    text: str
    at: datetime


class AudienceInviteIn(BaseModel):
    max_user_id: int
    storefront_id: int | None = None


class NotificationOut(BaseModel):
    id: int
    kind: str
    text: str
    order_id: int | None = None
    # Дошло ли в MAX. «Не читал» и «не получил» — разные истории
    delivered: bool = False
    # В MAX не отправляли: такие человек отключил сам
    muted: bool = False
    at: datetime
    unread: bool = True
    # Куда ведёт запись: «order_57», «connections», «sf_3». Пусто — никуда
    link: str = ""


class MuteOut(BaseModel):
    """Отключённый вид уведомлений: «напоминания об отсечке»."""
    kind: str
    side: str = ""
    label: str


class NotificationsOut(BaseModel):
    unread: int = 0
    items: list[NotificationOut] = []


class NotificationsReadIn(BaseModel):
    """Что отметить прочитанным. Пусто — всё: «Прочитать все»."""
    ids: list[int] = Field(default_factory=list, max_length=100)
    # Всё о заявке: человек открыл её, значит, видел, что с ней стало
    order_id: int | None = None
    # Всё, что ведёт на тот же экран, — ярлык из NotificationOut.link
    link: str | None = Field(default=None, max_length=64)


# --- избранное ---


class FavoriteIdsOut(BaseModel):
    """Что отмечено звёздочкой — чтобы нарисовать её на месте."""
    storefront: list[int] = []
    item: list[int] = []
    employee: list[int] = []
    client: list[int] = []


class FavoriteStorefrontOut(BaseModel):
    id: int
    name: str
    supplier: str = ""
    logo_url: str | None = None
    color: str | None = None


class FavoriteItemOut(BaseModel):
    id: int
    name: str
    unit: str
    storefront_id: int
    storefront_name: str
    photo_url: str | None = None


class FavoritePersonOut(BaseModel):
    """Контакт: сотрудник поставщика у магазина или клиент у поставщика."""
    id: int
    name: str
    # Чей: поставщик сотрудника или адрес клиента
    note: str = ""
    phone: str = ""
    phone_href: str = ""
    chat_href: str = ""
    # Разрешил ли писать себе в MAX
    reachable: bool = True


class FavoritesOut(BaseModel):
    storefronts: list[FavoriteStorefrontOut] = []
    items: list[FavoriteItemOut] = []
    contacts: list[FavoritePersonOut] = []
    clients: list[FavoritePersonOut] = []


class OneCListsIn(BaseModel):
    """Проверка подключения до сохранения: не переданное берётся из витрины."""
    onec_key: str | None = None
    onec_url: str | None = None
    onec_user: str | None = None
    onec_password: str | None = None
    onec_preset: str | None = None


class OneCCounterpartyIn(BaseModel):
    contractor_key: str = ""
    partner_key: str = ""
    name: str = ""


class OneCCounterpartyOut(BaseModel):
    storefront_id: int
    storefront: str
    contractor_key: str = ""
    name: str = ""
    # Кем оформится без сопоставления
    default_name: str = ""
