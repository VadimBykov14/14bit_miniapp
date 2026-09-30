"""Работники магазина: кто в команде точки и как их убрать.

Смотреть команду может любой её участник — работнику полезно знать, кто
ещё заказывает от имени магазина. Приглашать и убирать — только владелец
точки: это его магазин и его закупки.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import live, shop
from ..auth import Identity, require_client, require_shop_owner
from ..db import get_session
from ..messaging import tell
from ..models import Client, ClientWorker
from ..schemas import ShopPersonOut

router = APIRouter()


@router.get("/shop/workers", response_model=list[ShopPersonOut])
async def shop_workers(
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> list[ShopPersonOut]:
    client = await session.get(Client, identity.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="магазин не найден")
    return [ShopPersonOut(**asdict(row)) for row in await shop.people(session, client)]


@router.delete("/shop/workers/{worker_id}", status_code=204, response_class=Response)
async def remove_worker(
    worker_id: int,
    identity: Identity = Depends(require_shop_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    worker = await session.get(ClientWorker, worker_id)
    if worker is None or worker.client_id != identity.client_id:
        raise HTTPException(status_code=404, detail="работник не найден")
    client = await session.get(Client, identity.client_id)
    user_id = worker.max_user_id
    await session.delete(worker)
    await session.commit()
    await live.publish([identity.max_user_id], "workers")
    # Человек должен понять, почему магазин пропал из приложения, а не
    # искать ошибку.
    await tell(
        session,
        user_id,
        f"Владелец магазина «{client.name if client else ''}» убрал вас из работников. "
        "Заказывать от имени магазина больше нельзя.",
        kind="info",
    )
    return Response(status_code=204)
