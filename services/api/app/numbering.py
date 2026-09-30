"""Номер заявки — свой у каждого поставщика.

Раньше номером был сквозной id по всему стенду: у нового поставщика первая
заявка выходила №146, и по номеру читался объём чужих продаж. Внутри
по-прежнему живёт id — на нём ссылки из уведомлений и ключ документа в 1С.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Enterprise, Order, Storefront


async def next_number(session: AsyncSession, enterprise_id: int) -> int:
    """Следующий номер у предприятия. Строка предприятия — под замком до
    конца транзакции: две заявки в одну секунду не получат один номер."""
    await session.execute(
        select(Enterprise.id).where(Enterprise.id == enterprise_id).with_for_update()
    )
    last = await session.scalar(
        select(func.max(Order.number))
        .join(Storefront, Storefront.id == Order.storefront_id)
        .where(Storefront.enterprise_id == enterprise_id)
    )
    return int(last or 0) + 1
