"""Выгрузка истории заявок в таблицу.

CSV, а не xlsx, намеренно: его открывает и Excel, и «Google Таблицы», и 1С,
и он же читается глазами в любом текстовом редакторе. Разделитель — точка
с запятой, кодировка — UTF-8 с BOM: без BOM русский Excel показывает
кракозябры, и выгрузка становится бесполезной ровно для тех, кому нужна.

Строка = позиция заявки, а не заявка: в таком виде таблица сводится
сводной по любому разрезу — по клиенту, по позиции, по месяцу.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Client, Order, OrderItem, Storefront, StorefrontItem
from .quantity import normalize
from .spreadsheet import table, text

HEADER = (
    "Дата", "Заявка", "Статус", "Доставка", "Клиент", "Витрина",
    "Артикул", "Позиция", "Единица",
    "Заказано", "Подтверждено", "Принято",
    "Цена", "Сумма", "Расхождение", "Документ 1С", "Корректировка",
)

STATUS_LABELS = {
    "draft": "черновик",
    "sent": "отправлена",
    "confirmed": "подтверждена",
    "rejected": "отклонена",
    "assembling": "в сборке",
    "shipped": "отгружена",
    "accepted": "завершена",
    "closed": "завершена",
    "cancelled": "отменена",
}

ISSUE_LABELS = {
    "short": "недовоз",
    "mismatch": "пересорт",
    "damaged": "брак",
    "expiry": "срок годности",
}


def _qty(value: object) -> str:
    """Количество с одним знаком, запятой и без хвостового нуля."""
    if value is None:
        return ""
    return f"{normalize(value):.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _amount(value: float) -> str:
    # Русский Excel ждёт запятую: с точкой он прочитает число как текст,
    # и суммировать колонку придётся руками.
    return f"{value:.2f}".replace(".", ",")


async def orders_csv(session: AsyncSession, orders: list[Order]) -> str:
    item_ids = {line.item_id for order in orders for line in order.items}
    catalog = {
        item.id: item
        for item in (
            await session.execute(
                select(StorefrontItem).where(StorefrontItem.id.in_(item_ids or {0}))
            )
        ).scalars()
    }
    clients = {
        client.id: client
        for client in (
            await session.execute(
                select(Client).where(Client.id.in_({o.client_id for o in orders} or {0}))
            )
        ).scalars()
    }
    storefronts = {
        front.id: front
        for front in (
            await session.execute(
                select(Storefront).where(Storefront.id.in_({o.storefront_id for o in orders} or {0}))
            )
        ).scalars()
    }

    rows = []
    for order in sorted(orders, key=lambda o: o.created_at):
        for line in order.items:
            item = catalog.get(line.item_id)
            qty = float(line.qty_confirmed if line.qty_confirmed is not None else line.qty_ordered)
            rows.append([
                order.created_at.strftime("%d.%m.%Y"),
                str(order.id),
                STATUS_LABELS.get(order.status.value, order.status.value),
                order.delivery_date.strftime("%d.%m.%Y"),
                # Названия, артикулы и номера документов пишут люди и чужая
                # 1С — они идут через `text`.
                text(clients[order.client_id].name if order.client_id in clients else ""),
                text(storefronts[order.storefront_id].name if order.storefront_id in storefronts else ""),
                text(item.external_id if item else ""),
                text(item.name if item else ""),
                text(item.unit if item else ""),
                _qty(line.qty_ordered),
                _qty(line.qty_confirmed),
                _qty(line.qty_accepted),
                _amount(float(line.price)),
                _amount(float(line.price) * qty),
                text(ISSUE_LABELS.get(line.acceptance_issue or "", line.acceptance_issue or "")),
                text(order.onec_document or ""),
                text(order.onec_correction or ""),
            ])
    return table(HEADER, rows)
