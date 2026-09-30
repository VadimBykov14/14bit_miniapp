"""Удаление предприятия или точки со всем, что на них ссылается.

Нужно в двух местах: «Начать заново» в «Аккаунте» и сброс демо-данных
стенда. Порядок удаления задают внешние ключи: сначала то, что ссылается,
потом то, на что ссылаются. Уведомления не удаляем — запись «была заявка
№…» остаётся в ленте человека, только без ссылки.
"""

from __future__ import annotations

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AcceptancePhoto, Client, ClientManager, ClientWorker, Connection, Employee, Enterprise,
    ExchangeEvent, Invite, Notification, Order, OrderItem, OrderTemplate, OrderTemplateLine,
    PriceChange, Promo, Reminder, Storefront, StorefrontItem,
)


async def _ids(session: AsyncSession, query) -> list[int]:
    return list((await session.execute(query)).scalars())


async def delete_orders(session: AsyncSession, order_ids: list[int]) -> None:
    if not order_ids:
        return
    await session.execute(delete(ExchangeEvent).where(ExchangeEvent.order_id.in_(order_ids)))
    await session.execute(delete(AcceptancePhoto).where(AcceptancePhoto.order_id.in_(order_ids)))
    await session.execute(
        update(Notification).where(Notification.order_id.in_(order_ids)).values(order_id=None)
    )
    await session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await session.execute(delete(Order).where(Order.id.in_(order_ids)))


async def _delete_templates(session: AsyncSession, template_ids: list[int]) -> None:
    if not template_ids:
        return
    await session.execute(
        delete(OrderTemplateLine).where(OrderTemplateLine.template_id.in_(template_ids))
    )
    await session.execute(delete(OrderTemplate).where(OrderTemplate.id.in_(template_ids)))


async def delete_client(session: AsyncSession, client_id: int) -> None:
    """Точка со своими заявками, подключениями, шаблонами и работниками."""
    await delete_orders(
        session, await _ids(session, select(Order.id).where(Order.client_id == client_id))
    )
    await session.execute(delete(Connection).where(Connection.client_id == client_id))
    await session.execute(delete(Reminder).where(Reminder.client_id == client_id))
    await _delete_templates(
        session,
        await _ids(session, select(OrderTemplate.id).where(OrderTemplate.client_id == client_id)),
    )
    await session.execute(delete(ClientManager).where(ClientManager.client_id == client_id))
    await session.execute(delete(ClientWorker).where(ClientWorker.client_id == client_id))
    await session.execute(delete(Invite).where(Invite.client_id == client_id))
    await session.execute(delete(Client).where(Client.id == client_id))


async def delete_enterprise(session: AsyncSession, enterprise_id: int) -> None:
    """Предприятие с витринами, позициями, заявками к ним и сотрудниками."""
    storefronts = await _ids(
        session, select(Storefront.id).where(Storefront.enterprise_id == enterprise_id)
    )
    items = await _ids(
        session,
        select(StorefrontItem.id).where(StorefrontItem.storefront_id.in_(storefronts or [0])),
    )
    await delete_orders(
        session,
        await _ids(session, select(Order.id).where(Order.storefront_id.in_(storefronts or [0]))),
    )
    await _delete_templates(
        session,
        await _ids(
            session,
            select(OrderTemplate.id).where(
                or_(
                    OrderTemplate.storefront_id.in_(storefronts or [0]),
                    OrderTemplate.id.in_(
                        select(OrderTemplateLine.template_id).where(
                            OrderTemplateLine.item_id.in_(items or [0])
                        )
                    ),
                )
            ),
        ),
    )
    await session.execute(
        delete(Promo).where(
            or_(Promo.storefront_id.in_(storefronts or [0]), Promo.item_id.in_(items or [0]))
        )
    )
    await session.execute(delete(PriceChange).where(PriceChange.item_id.in_(items or [0])))
    await session.execute(delete(AcceptancePhoto).where(AcceptancePhoto.item_id.in_(items or [0])))
    await session.execute(delete(Connection).where(Connection.storefront_id.in_(storefronts or [0])))
    await session.execute(
        delete(Reminder).where(
            or_(
                Reminder.storefront_id.in_(storefronts or [0]),
                Reminder.enterprise_id == enterprise_id,
            )
        )
    )
    await session.execute(
        delete(Invite).where(
            or_(Invite.storefront_id.in_(storefronts or [0]), Invite.enterprise_id == enterprise_id)
        )
    )
    await session.execute(
        update(Notification)
        .where(Notification.storefront_id.in_(storefronts or [0]))
        .values(storefront_id=None)
    )
    await session.execute(
        delete(StorefrontItem).where(StorefrontItem.storefront_id.in_(storefronts or [0]))
    )
    await session.execute(delete(Storefront).where(Storefront.id.in_(storefronts or [0])))
    await session.execute(delete(ExchangeEvent).where(ExchangeEvent.enterprise_id == enterprise_id))
    await session.execute(delete(ClientManager).where(ClientManager.enterprise_id == enterprise_id))
    await session.execute(delete(Employee).where(Employee.enterprise_id == enterprise_id))
    await session.execute(delete(Enterprise).where(Enterprise.id == enterprise_id))
