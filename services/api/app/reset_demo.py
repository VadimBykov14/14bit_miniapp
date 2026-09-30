"""Сброс демо-данных стенда без потери чужих данных.

Прогоны сценариев тратят остатки и копят заявки, и перед показом демо
возвращают к исходному. Раньше для этого стенд очищался целиком — и вместе
с демо пропадали предприятия и магазины, которые люди завели сами. Теперь
стирается только демо: два демо-предприятия и точка демо-аккаунта, — и
заводится заново. Свои предприятия и магазины остаются; их подключения к
демо-витринам переносятся на новые витрины с теми же названиями.

Заодно убираются предприятия без единого сотрудника: ими никто не
управляет, а их витрины висели на полке города.

Запуск в контейнере api:  python -m app.reset_demo
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from . import purge
from .db import Session
from .models import Client, Connection, Employee, Enterprise, Storefront
from .seed import DEMO_USER_ID, seed


async def run() -> None:
    async with Session() as session:
        demo = list(
            (await session.execute(select(Enterprise.id).where(Enterprise.is_demo.is_(True)))).scalars()
        )
        staffed = select(Employee.enterprise_id)
        orphans = list(
            (
                await session.execute(
                    select(Enterprise.id).where(
                        Enterprise.is_demo.is_(False), Enterprise.id.not_in(staffed)
                    )
                )
            ).scalars()
        )
        demo_clients = list(
            (await session.execute(select(Client.id).where(Client.max_user_id == DEMO_USER_ID))).scalars()
        )

        # Подключения чужих точек к демо-витринам — чтобы вернуть их на новые.
        kept = list(
            (
                await session.execute(
                    select(Connection.client_id, Connection.status, Storefront.name)
                    .join(Storefront, Storefront.id == Connection.storefront_id)
                    .where(
                        Storefront.enterprise_id.in_(demo or [0]),
                        Connection.client_id.not_in(demo_clients or [0]),
                    )
                )
            ).all()
        )

        for client_id in demo_clients:
            await purge.delete_client(session, client_id)
        for enterprise_id in [*demo, *orphans]:
            await purge.delete_enterprise(session, enterprise_id)
        await session.commit()

    async with Session() as session:
        await seed(session)

    async with Session() as session:
        fresh = {
            row.name: row.id
            for row in (
                await session.execute(
                    select(Storefront)
                    .join(Enterprise, Enterprise.id == Storefront.enterprise_id)
                    .where(Enterprise.is_demo.is_(True))
                )
            ).scalars()
        }
        restored = 0
        for client_id, status, name in kept:
            if name in fresh:
                session.add(Connection(client_id=client_id, storefront_id=fresh[name], status=status))
                restored += 1
        await session.commit()

    print(
        f"демо сброшено: демо-предприятий {len(demo)}, пустых предприятий убрано {len(orphans)}, "
        f"подключений чужих точек перенесено {restored}"
    )


if __name__ == "__main__":
    asyncio.run(run())
