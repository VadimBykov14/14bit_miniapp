"""Обмен с 1С.

Наружу торчит ровно то, чем пользуются заявки: выгрузка заказа, выгрузка
корректировки по приёмке и метка актуальности остатков. Какая реализация
стоит за этим — эмуляция или боевой OData — решает `ONEC_MODE`.

Главное правило продукта живёт здесь: **недоступность 1С не роняет основной
сценарий**. Заявка подтверждается всегда, неудачная выгрузка превращается
в запись «в очереди», которую подхватит фоновый проход.

Заказ уходит в 1С сразу, как клиент оформил заявку. Резервировать ли в
1С сразу — решает поставщик настройкой витрины, как в «Моби-С»:

* по умолчанию заказ ждёт «На согласовании» и не проводится — в УТ такой
  заказ товар не резервирует, и резерв до подтверждения держит приложение;
* «резервировать сразу» — заказ в рабочем статусе и проведён, резерв в 1С.

Подтверждение правит количества, переводит заказ в рабочий статус и
проводит его; отказ и отмена снимают проведение и помечают на удаление.

В 1С уходят только витрины, у которых источник — 1С. Витрина без 1С
раньше выгружалась в общую тестовую базу стенда: у пекарни в заявках
стоял «1С: ЗК-…», хотя 1С у неё нет, а названия магазинов были видны в
открытом кабинете эмулятора. Её учёт — сам остаток витрины: товар
держится резервом до подтверждения и списывается при подтверждении.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import live
from ..db import Session
from .. import secret_box
from ..models import (
    ExchangeEvent, ExchangeStatus, Mode, OneCCounterparty, Order, OrderStatus, Source,
    Storefront, StorefrontItem,
)
from ..quantity import to_decimal
from . import address, settings as onec_settings
from .contract import CatalogItem, Document, DocumentLine, OneC, OneCUnavailable
from .odata import PRICE_KIND, ODataOneC, configured
from .settings import OneCSettings
from .simulated import SimulatedOneC

log = logging.getLogger("onec")

MODE = os.environ.get("ONEC_MODE", "simulated")

__all__ = [
    "CatalogItem", "Document", "DocumentLine", "OneC", "OneCUnavailable",
    "backend", "mode_title", "document_number", "correction_number",
    "export_order", "export_acceptance", "stock_synced_now", "retry_queued",
    "export_new", "confirm_order", "cancel_order", "reschedule_order", "held",
    "enabled", "take_stock", "release_stock", "settings_of", "own_base", "complete_settings",
    "reserves_in_onec",
]

ORDER = "Заказ клиента"
# Правка и отмена уже выгруженного заказа — своими записями в журнале: их
# тоже догоняет повторная попытка, если 1С была недоступна.
ORDER_CONFIRM = "Заказ клиента: подтверждение"
ORDER_RESCHEDULE = "Заказ клиента: перенос доставки"
ORDER_CANCEL = "Заказ клиента: отмена"
ORDER_NOTE = "Заказ клиента: расхождения приёмки"


# Адрес стенда без базы: путь к конкретной базе выводится из ключа.
STAND_URL = os.environ.get("ONEC_STAND_URL", "http://mock-1c:8080")


# Имя базы в ключе: буквы, цифры, «-» и «_». Иначе «../» или «?» в ключе
# меняли бы путь запроса к стенду.
SLUG = re.compile(r"[A-Za-z0-9_-]{1,64}")


def base_from_key(key: str) -> str:
    """Адрес базы по ключу вида «база.секрет».

    Так при создании витрины хватает одного поля: адрес спрятан в ключе,
    и владельцу не нужно знать, как устроен путь публикации.
    """
    slug, dot, secret = key.strip().partition(".")
    if not dot or not secret or not SLUG.fullmatch(slug):
        return ""
    return f"{STAND_URL.rstrip('/')}/{slug}"


def connection(storefront: Storefront | None) -> tuple[str, str]:
    """(адрес, ключ) для этой витрины. Пусто — настройка стенда."""
    if storefront is None or not storefront.onec_key:
        return "", ""
    return storefront.onec_url or base_from_key(storefront.onec_key), storefront.onec_key


def enabled(storefront: Storefront | None) -> bool:
    """Витрина ведёт учёт в 1С. Демо-витрина без ключа — тоже: её база —
    база стенда из окружения."""
    return storefront is not None and storefront.source is Source.onec


def settings_of(storefront: Storefront | None) -> OneCSettings:
    if storefront is None:
        return OneCSettings()
    return onec_settings.load(storefront.onec_settings, bool(storefront.onec_reserve_now))


def own_base(storefront: Storefront | None) -> bool:
    """Своя база владельца — по адресу, логину и паролю, а не ключу стенда."""
    return bool(storefront is not None and storefront.onec_url and storefront.onec_user)


def backend(storefront: Storefront | None = None) -> OneC:
    """Реализация обмена для этой витрины.

    База принадлежит витрине, а не предприятию: склад и пекарня чаще
    живут в разных базах, чем в одной. Если витрина ничего не настроила,
    берётся база стенда из окружения — иначе демо пришлось бы настраивать
    руками перед каждым показом.
    """
    settings = settings_of(storefront)
    if own_base(storefront):
        # Своя база: адрес — чужой сервер, проверяем при каждом обмене, а не
        # только при сохранении: адрес мог сохраниться раньше этих правил.
        try:
            url = address.check(storefront.onec_url)
        except address.BadAddress as exc:
            raise OneCUnavailable(str(exc)) from exc
        password = secret_box.open_sealed(storefront.onec_password)
        if password is None:
            raise OneCUnavailable("пароль 1С не расшифровать — введите его заново в настройках витрины")
        return ODataOneC(
            base_url=url, user=storefront.onec_user, password=password, settings=settings,
            public_only=True,
        )
    url, key = connection(storefront)
    if key and not url:
        # Ключ есть, а адреса из него не вывести. Раньше такая витрина
        # молча уходила в базу стенда из окружения — под паролем стенда.
        raise OneCUnavailable("ключ базы 1С не подходит — скопируйте его из кабинета базы заново")
    if url:
        # Адрес, вписанный владельцем, — чужой сервер: проверяем при каждом
        # обмене, а не только при сохранении, — адрес мог сохраниться раньше
        # этих правил.
        own = bool(storefront.onec_url)
        if own:
            try:
                url = address.check(url)
            except address.BadAddress as exc:
                raise OneCUnavailable(str(exc)) from exc
        return ODataOneC(
            base_url=url, user="exchange", password=key, settings=settings, public_only=own
        )
    if MODE == "odata":
        return ODataOneC(settings=settings)
    return SimulatedOneC()


async def complete_settings(storefront: Storefront, client: OneC) -> None:
    """Тестовая база: что не выбрано — берём первое из списков базы.

    Демо не должно требовать настройки перед каждым показом. Своя база так
    не угадывается: организацию и склад поставщик выбирает сам — ошибка
    здесь уводила бы заказы не на тот склад.
    """
    if own_base(storefront) or not isinstance(client, ODataOneC):
        return
    current = client.settings
    wanted = [key for key in onec_settings.REFS if key != "agreement" and not getattr(current, key)]
    if not wanted:
        return
    lists = await client.lists()
    names = dict(current.names)
    source = {
        "organization": lists["organizations"], "warehouse": lists["warehouses"],
        "price_kind": lists["price_kinds"], "currency": lists["currencies"],
        "contractor": lists["contractors"],
    }
    for key in wanted:
        options = source.get(key) or []
        if key == "price_kind":
            options = [row for row in options if row["name"] == PRICE_KIND] or options
        if options:
            setattr(current, key, options[0]["key"])
            names[key] = options[0]["name"]
            if key == "contractor":
                current.partner = options[0].get("partner", "")
    current.names = names
    storefront.onec_settings = current.stored()


def mode_title(storefront: Storefront | None = None) -> str:
    """Что написать владельцу в журнале и в кабинете.

    Тестовую базу называем тестовой прямо: демо-стенд отвечает по тому же
    OData, что и боевая 1С, и выдать одно за другое было бы враньём.
    """
    url, key = connection(storefront)
    if key and not url:
        return "ключ базы 1С не подходит"
    if not url:
        if MODE != "odata":
            return "эмуляция в процессе (боевая база не подключена)"
        url = os.environ.get("ONEC_URL", "")
    if not url:
        return "OData, адрес базы не задан"
    if "mock-1c" in url:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return f"OData, тестовая база «{slug}» (эмулятор)"
    return f"OData, база {url}"


def document_key(kind: str, order: Order) -> str:
    """Внешний ключ документа в 1С: номер заявки и момент её создания.

    Одного номера мало. Базу приложения пересоздают — на стенде перед
    каждым показом, — и нумерация заявок начинается заново, а база 1С свои
    документы помнит. Ключ «max26-order-7» совпадал со вчерашней заявкой
    №7, и 1С по правилу идемпотентности возвращала старый документ: новой
    заявки в учёте не появлялось, и остаток не менялся. Номер заявки
    остаётся в конце ключа — по нему эмуляция строит номер документа.
    """
    created = order.created_at
    stamp = created.strftime("%y%m%d%H%M%S") if created else "0"
    return f"max26-{stamp}-{kind}-{order.id}"


def document_number(order_id: int) -> str:
    """Номер документа «Заказ клиента», как его вернула бы 1С."""
    return f"ЗК-{order_id:06d}"


def correction_number(order_id: int) -> str:
    """Номер документа «Корректировка реализации»."""
    return f"КР-{order_id:06d}"


def stock_synced_now() -> datetime:
    """Метка «наличие актуально на …». В боевом режиме — время ответа 1С."""
    return datetime.now(timezone.utc)


async def _document(
    session: AsyncSession,
    order: Order,
    comment: str,
    storefront: Storefront | None,
    status: str = "",
    post: bool = False,
) -> Document:
    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(
                    StorefrontItem.id.in_([line.item_id for line in order.items] or [0])
                )
            )
        ).scalars()
    }
    lines = []
    for line in order.items:
        qty = float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
        if qty <= 0:
            continue
        item = catalog.get(line.item_id)
        lines.append(
            DocumentLine(
                ref=item.onec_ref if item else "",
                name=item.name if item else "позиция",
                qty=qty,
                price=float(line.price),
            )
        )
    settings = settings_of(storefront)
    refs = {
        "organization": settings.organization, "warehouse": settings.warehouse,
        "currency": settings.currency, "agreement": settings.agreement,
        "contractor": settings.contractor, "partner": settings.partner,
    }
    # Магазин, сопоставленный с контрагентом 1С, оформляется им; иначе —
    # контрагент витрины по умолчанию.
    mapped = (
        await session.execute(
            select(OneCCounterparty).where(
                OneCCounterparty.storefront_id == order.storefront_id,
                OneCCounterparty.client_id == order.client_id,
            )
        )
    ).scalar_one_or_none()
    if mapped is not None:
        refs["contractor"] = mapped.contractor_key
        refs["partner"] = mapped.partner_key or refs["partner"]
    return Document(
        external_key=document_key("order", order),
        client=mapped.name if mapped else settings.names.get("contractor", ""),
        comment=comment,
        lines=lines,
        status=status,
        post=post,
        refs=refs,
        ship_date=order.delivery_date.isoformat() if order.delivery_date else "",
    )


def _state(order: Order, storefront: Storefront | None) -> tuple[str, bool]:
    """Статус заказа в 1С и проводить ли его.

    Ждёт поставщика — «На согласовании» без проведения: в УТ такой заказ не
    резервирует, резерв держит приложение. Если поставщик выбрал «резерв
    сразу» или уже подтвердил — рабочий статус и проведение."""
    settings = settings_of(storefront)
    if order.status is OrderStatus.sent and not settings.reserve_now:
        return settings.object("status_new"), False
    return settings.object("status_work"), True


def reserves_in_onec(order: Order, storefront: Storefront | None) -> bool:
    """Заказ в 1С проведён в рабочем статусе — товар держит учёт, и резерв
    приложения больше не нужен."""
    return _state(order, storefront)[1]


def _comment(order: Order) -> str:
    base = f"Заявка №{order.label} из мини-приложения MAX"
    if order.status is OrderStatus.sent:
        return f"{base} — ждёт подтверждения поставщика"
    if order.status is OrderStatus.cancelled:
        return f"{base} — отменена клиентом"
    if order.status is OrderStatus.rejected:
        # Отказ после подтверждения — это отменённая поставка, а не
        # отклонённая заявка: в 1С видно, что о ней уже договорились.
        return f"{base} — {'отменена поставщиком' if order.confirmed_at else 'отклонена поставщиком'}"
    return f"{base} — подтверждена поставщиком"


async def export_order(
    session: AsyncSession, order: Order, enterprise_id: int | None = None
) -> ExchangeEvent | None:
    """Создаёт в 1С «Заказ клиента» по заявке и ставит в очередь, если 1С
    не ответила. Статус заказа — по заявке: ждёт поставщика или согласован.
    Витрина без 1С не выгружается — None.

    Идемпотентность двойная: не выгружаем повторно, если номер уже известен,
    а реализация ещё раз ищет документ по нашему ключу в самой базе.
    """
    if order.onec_document:
        return _event(
            session, order, enterprise_id, ORDER, ExchangeStatus.done,
            order.onec_document, "документ уже был создан, повторная выгрузка пропущена",
        )

    storefront = await session.get(Storefront, order.storefront_id)
    if not enabled(storefront):
        return None
    status, post = _state(order, storefront)
    document = await _document(session, order, _comment(order), storefront, status, post)
    try:
        number = await backend(storefront).push_order(document)
    except OneCUnavailable as exc:
        return _event(
            session, order, enterprise_id, ORDER, ExchangeStatus.queued, None,
            f"1С недоступна: {exc}. Заявка принята, заказ встанет в 1С, когда она ответит",
        )

    order.onec_document = number
    return _event(
        session, order, enterprise_id, ORDER, ExchangeStatus.done, number,
        ("заказ создан и проведён, товар в резерве 1С — ждёт подтверждения поставщика"
         if post else "заказ создан «На согласовании», резерв держит приложение до подтверждения")
        if order.status is OrderStatus.sent
        else "заказ создан и проведён",
    )


def held(order: Order) -> dict[int, float]:
    """Сколько заявка держит на складе по каждой позиции: подтверждённое,
    а до подтверждения — заказанное."""
    return {
        line.item_id: float(
            line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered
        )
        for line in order.items
    }


async def shift_stock(session: AsyncSession, order: Order, delta: dict[int, float]) -> None:
    """Меняет остаток витрины «со склада» на delta по позициям: минус —
    ушло в заказ, плюс — вернулось. Витрина «под заказ» остатка не держит."""
    storefront = await session.get(Storefront, order.storefront_id)
    if storefront is None or storefront.mode is not Mode.stock or not delta:
        return
    items = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(StorefrontItem.id.in_(list(delta) or [0]))
            )
        ).scalars()
    }
    for item_id, qty in delta.items():
        item = items.get(item_id)
        if item and qty:
            item.stock = to_decimal(max(0.0, float(item.stock) + qty))


async def take_stock(session: AsyncSession, order: Order) -> None:
    """Списывает со склада витрины то, что заявка держит сейчас: резерв
    заявки больше не нужен, её количество вычтено из остатка."""
    if order.stock_taken:
        return
    await shift_stock(session, order, {k: -v for k, v in held(order).items()})
    order.stock_taken = True


async def release_stock(session: AsyncSession, order: Order, amounts: dict[int, float]) -> None:
    """Возвращает на склад витрины то, что заявка держала: отказ, отмена.
    Не списанное возвращать не нужно — оно и так было лишь резервом."""
    if not order.stock_taken:
        return
    await shift_stock(session, order, amounts)
    order.stock_taken = False


async def _locked(session: AsyncSession, order_id: int) -> Order | None:
    """Заявка под замком строки: выгрузка при оформлении идёт фоном и может
    совпасть с подтверждением — без замка остаток списался бы дважды."""
    return (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()


async def export_new(order_id: int) -> None:
    """Только что оформленная заявка — в 1С, не задерживая ответ клиенту.

    Если заказ резервирует товар в учёте (поставщик выбрал «резерв сразу»),
    остаток витрины уменьшается сразу: резерв заявки больше не нужен. Иначе
    — и если 1С не ответила — заявка остаётся в резерве витрины.
    """
    storefront_id: int | None = None
    async with Session() as session:
        order = await _locked(session, order_id)
        if order is None or order.onec_document or order.status is not OrderStatus.sent:
            return
        storefront = await session.get(Storefront, order.storefront_id)
        if not enabled(storefront):
            return
        await export_order(session, order, storefront.enterprise_id if storefront else None)
        if order.onec_document:
            if reserves_in_onec(order, storefront):
                await take_stock(session, order)
            storefront_id = order.storefront_id
        await session.commit()
        if storefront_id is not None:
            await live.stock_changed(session, storefront_id)
            await live.order_changed(session, order)
    if storefront_id is not None and storefront is not None and storefront.source is Source.onec:
        from .. import stock  # иначе круговой импорт: stock сам зовёт onec

        stock.later(storefront_id)


def later(order_id: int) -> None:
    """Выгрузить новую заявку фоном."""
    task = asyncio.create_task(export_new(order_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


# Ссылки на фоновые задачи: без них сборщик мусора снял бы выгрузку на полпути.
_pending: set[asyncio.Task] = set()


async def confirm_order(
    session: AsyncSession, order: Order, enterprise_id: int | None, ordered: dict[int, float]
) -> ExchangeEvent | None:
    """Поставщик подтвердил заявку. Заказ уже в 1С — правим количества и
    согласуем, а в витрине возвращаем или добираем разницу. Не успел уйти —
    выгружаем сейчас, сразу согласованным, и списываем подтверждённое.
    Витрина без 1С списывает подтверждённое со своего остатка.

    `ordered` — сколько заявка держала до подтверждения: из этого и
    считается разница.
    """
    now = held(order)
    if order.stock_taken:
        await shift_stock(
            session, order, {item_id: ordered.get(item_id, 0.0) - qty for item_id, qty in now.items()}
        )
    storefront = await session.get(Storefront, order.storefront_id)
    if not enabled(storefront):
        await take_stock(session, order)
        return None

    if not order.onec_document:
        event = await export_order(session, order, enterprise_id)
        if order.onec_document:
            await take_stock(session, order)
        return event

    status, post = _state(order, storefront)
    document = await _document(session, order, _comment(order), storefront, status, post)
    try:
        await backend(storefront).update_order(document)
    except OneCUnavailable as exc:
        return _event(
            session, order, enterprise_id, ORDER_CONFIRM, ExchangeStatus.queued,
            order.onec_document, f"1С недоступна: {exc}. Подтверждение встанет в очередь",
        )
    # Заказ проведён в рабочем статусе — резерв теперь в 1С.
    await take_stock(session, order)
    changed = any(abs(ordered.get(item_id, 0.0) - qty) > 1e-9 for item_id, qty in now.items())
    return _event(
        session, order, enterprise_id, ORDER_CONFIRM, ExchangeStatus.done, order.onec_document,
        "заказ подтверждён и проведён, количества поправлены" if changed
        else "заказ подтверждён и проведён",
    )


async def reschedule_order(
    session: AsyncSession, order: Order, enterprise_id: int | None
) -> ExchangeEvent | None:
    """Поставщик перенёс доставку: в заказе 1С меняется дата отгрузки.
    Не ответила 1С — перенос встаёт в очередь, как и подтверждение."""
    storefront = await session.get(Storefront, order.storefront_id)
    if not order.onec_document or not enabled(storefront):
        return None
    status, post = _state(order, storefront)
    document = await _document(session, order, _comment(order), storefront, status, post)
    try:
        await backend(storefront).update_order(document)
    except OneCUnavailable as exc:
        return _event(
            session, order, enterprise_id, ORDER_RESCHEDULE, ExchangeStatus.queued,
            order.onec_document, f"1С недоступна: {exc}. Перенос даты встанет в очередь",
        )
    if post:
        # Перенос провёл заказ в рабочем статусе — резерв в 1С.
        await take_stock(session, order)
    return _event(
        session, order, enterprise_id, ORDER_RESCHEDULE, ExchangeStatus.done, order.onec_document,
        f"дата отгрузки — {order.delivery_date.strftime('%d.%m.%Y')}",
    )


async def cancel_order(
    session: AsyncSession, order: Order, enterprise_id: int | None, before: dict[int, float]
) -> ExchangeEvent | None:
    """Отказ поставщика или отмена клиента: заказ в 1С снимается с
    проведения и помечается на удаление, резерв возвращается на склад — и в
    учёте, и в витрине. Заказ в 1С не попал — отменять там нечего.

    `before` — сколько заявка держала до отмены.
    """
    await release_stock(session, order, before)
    storefront = await session.get(Storefront, order.storefront_id)
    if not order.onec_document or not enabled(storefront):
        return None
    try:
        await backend(storefront).cancel_order(document_key("order", order), _comment(order))
    except OneCUnavailable as exc:
        return _event(
            session, order, enterprise_id, ORDER_CANCEL, ExchangeStatus.queued,
            order.onec_document, f"1С недоступна: {exc}. Отмена заказа встанет в очередь",
        )
    return _event(
        session, order, enterprise_id, ORDER_CANCEL, ExchangeStatus.done, order.onec_document,
        "заказ отменён, резерв снят",
    )


async def export_acceptance(
    session: AsyncSession,
    order: Order,
    discrepancies: list[str],
    enterprise_id: int | None = None,
) -> ExchangeEvent | None:
    """Передаёт расхождения приёмки в 1С комментарием к заказу. Витрина без
    1С — None.

    Недовезённое и бракованное обязано дойти до учёта поставщика. Но
    «Корректировку реализации» в УТ оформляют по реализации, а не по
    заказу, и реализацию приложение не создаёт — поэтому расхождения
    уходят учётчику комментарием, а корректировку он делает сам.
    """
    kind = ORDER_NOTE
    storefront = await session.get(Storefront, order.storefront_id)
    if not enabled(storefront):
        return None
    if not discrepancies:
        return _event(
            session, order, enterprise_id, kind, ExchangeStatus.done, None,
            "приёмка без расхождений, передавать нечего",
        )
    if order.onec_correction:
        return _event(
            session, order, enterprise_id, kind, ExchangeStatus.done, order.onec_correction,
            "расхождения уже переданы, повтор пропущен",
        )
    summary = "; ".join(discrepancies)
    try:
        number = await backend(storefront).note_order(
            document_key("order", order), f"Расхождения приёмки: {summary}"
        )
    except OneCUnavailable as exc:
        return _event(
            session, order, enterprise_id, kind, ExchangeStatus.queued, None,
            f"1С недоступна: {exc}. Расхождения зафиксированы, передача в очереди: {summary}",
        )
    if number is None:
        return _event(
            session, order, enterprise_id, kind, ExchangeStatus.done, None,
            f"заказа в 1С нет — передать расхождения некуда: {summary}",
        )
    order.onec_correction = number
    return _event(
        session, order, enterprise_id, kind, ExchangeStatus.done, number,
        f"в комментарии к заказу — для корректировки учётчиком: {summary}",
    )


def _event(
    session: AsyncSession,
    order: Order,
    enterprise_id: int | None,
    kind: str,
    status: ExchangeStatus,
    external_key: str | None,
    message: str,
) -> ExchangeEvent:
    event = ExchangeEvent(
        direction="out",
        object_kind=kind,
        enterprise_id=enterprise_id,
        order_id=order.id,
        status=status,
        external_key=external_key,
        message=message,
    )
    session.add(event)
    return event


async def retry_queued(session: AsyncSession, limit: int = 20) -> dict:
    """Догоняет то, что не ушло, когда 1С была недоступна.

    Очередь — не украшение: без повторов «выгрузка в очереди» осталась бы
    вечным статусом, и владелец однажды обнаружил бы, что в 1С нет половины
    заказов. Каждая запись — своей транзакцией: заявка на время попытки под
    замком, и подтверждение менеджера не ждёт, пока пройдёт вся очередь.
    """
    stuck = [
        (event.id, event.order_id)
        for event in (
            await session.execute(
                select(ExchangeEvent)
                .where(ExchangeEvent.status == ExchangeStatus.queued)
                .order_by(ExchangeEvent.at)
                .limit(limit)
            )
        ).scalars()
    ]

    done = 0
    still = 0
    touched: set[int] = set()
    for event_id, order_id in stuck:
        if order_id is None:
            continue
        order = await _locked(session, order_id)
        event = await session.get(ExchangeEvent, event_id)
        if order is None or event is None or event.status is not ExchangeStatus.queued:
            await session.rollback()
            continue

        before = (order.onec_document, order.onec_correction)
        gone = order.status in (OrderStatus.rejected, OrderStatus.cancelled)
        storefront = await session.get(Storefront, order.storefront_id)
        if not enabled(storefront):
            # Витрину перевели на ручной учёт, пока запись ждала: выгружать
            # в 1С больше нечего и некуда.
            event.status = ExchangeStatus.done
            event.message += " → витрина работает без 1С, выгрузка не нужна"
            done += 1
        elif event.object_kind == ORDER and gone:
            # Заявку отменили раньше, чем 1С ответила: выгружать уже нечего.
            event.status = ExchangeStatus.done
            event.message += " → заявка отменена, выгрузка не нужна"
            done += 1
        elif event.object_kind in (ORDER_CONFIRM, ORDER_RESCHEDULE, ORDER_CANCEL):
            try:
                if event.object_kind == ORDER_CANCEL:
                    await backend(storefront).cancel_order(
                        document_key("order", order), _comment(order)
                    )
                else:
                    status, post = _state(order, storefront)
                    await backend(storefront).update_order(
                        await _document(session, order, _comment(order), storefront, status, post)
                    )
                    if post and not gone:
                        await take_stock(session, order)
                        touched.add(order.storefront_id)
            except OneCUnavailable:
                still += 1
                await session.rollback()
                continue
            event.status = ExchangeStatus.done
            event.message += " → выгружено повторной попыткой"
            done += 1
        else:
            if event.object_kind == ORDER:
                fresh = await export_order(session, order, event.enterprise_id)
            else:
                problems = [event.message.split(": ")[-1]] if event.message else ["расхождение"]
                fresh = await export_acceptance(session, order, problems, event.enterprise_id)

            if fresh is not None and fresh.status is ExchangeStatus.done and (
                order.onec_document, order.onec_correction
            ) != before:
                # Старую запись помечаем закрытой, чтобы очередь не росла вечно.
                event.status = ExchangeStatus.done
                event.message += " → выгружено повторной попыткой"
                done += 1
                if before[0] is None and order.onec_document and reserves_in_onec(
                    order, storefront
                ):
                    # Заказ дошёл до учёта только сейчас и проведён: пока он
                    # стоял в очереди, остаток держал его резерв, теперь —
                    # списываем.
                    await take_stock(session, order)
                    touched.add(order.storefront_id)
            else:
                # Новая запись «в очереди» — дубль той, что уже ждёт.
                if fresh is not None and fresh.status is ExchangeStatus.queued:
                    session.expunge(fresh)
                still += 1
                await session.rollback()
                continue
        await session.commit()

    if done or still:
        log.info("повторная выгрузка: ушло %s, осталось в очереди %s", done, still)
    for storefront_id in touched:
        await live.stock_changed(session, storefront_id)
    return {"sent": done, "queued": still}
