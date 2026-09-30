"""Снимки: фотографии товаров, логотипы и снимки расхождений при приёмке."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import links, storage
from ..auth import Identity, current_identity, require_client
from ..db import get_session
from ..models import AcceptancePhoto, Order, Role, Storefront, StorefrontItem

router = APIRouter()


@router.post("/orders/{order_id}/photos", status_code=201)
async def upload_photo(
    order_id: int,
    file: UploadFile = File(...),
    item_id: int | None = Form(default=None),
    identity: Identity = Depends(require_client),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Снимок уходит в хранилище сразу после съёмки, а к заявке крепится
    только при приёмке — см. `accept_order`."""
    order = await session.get(Order, order_id)
    if not order or order.client_id != identity.client_id:
        raise HTTPException(status_code=404, detail="заявка не найдена")

    data = await file.read(storage.MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="пустой файл")
    if len(data) > storage.MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"снимок больше {storage.MAX_BYTES // (1024 * 1024)} МБ",
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in storage.ALLOWED:
        raise HTTPException(status_code=422, detail="поддерживаются только изображения")

    key = storage.put(data, content_type)
    photo = AcceptancePhoto(
        order_id=order.id, item_id=item_id, object_key=key, content_type=content_type,
        attached=False,
    )
    session.add(photo)
    await session.commit()
    return {
        "key": key,
        "url": links.signed(
            f"/api/photos/{key}", identity.max_user_id,
            identity.role.value if identity.role else "client", links.PHOTO_TTL,
        ),
    }


async def _public(session: AsyncSession, key: str) -> Response:
    """Фотография товара, логотип и фото витрины — часть витрины, их видит любой клиент.

    Тег <img> не передаёт заголовок с подписью MAX, поэтому раньше каждая
    картинка получала 401 и не показывалась. Ключ — случайные 128 бит, и
    отдаём только тот, что сейчас стоит в карточке: перебором не найти, а
    заменённый снимок по старой ссылке больше не открывается.
    """
    known = (
        await session.execute(select(StorefrontItem.id).where(StorefrontItem.photo_key == key))
    ).first() or (
        await session.execute(
            select(Storefront.id).where((Storefront.logo_key == key) | (Storefront.cover_key == key))
        )
    ).first()
    if not known:
        raise HTTPException(status_code=404, detail="снимок не найден")
    data, content_type = storage.get(key)
    # Ключ меняется при каждой замене снимка, поэтому кэшировать можно надолго.
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/photos/{key:path}")
async def fetch_photo(
    key: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Отдаёт снимок.

    Два вида снимков живут по разным правилам. Фотография товара — часть
    витрины, она открыта. Снимок расхождения — доказательство в споре: он
    открыт только участникам заявки, по подписи MAX или по подписанной
    ссылке, которую сервер выдал вместе с заявкой.
    """
    if key.startswith(("items/", "logos/", "covers/")):
        return await _public(session, key)

    identity = await current_identity(
        request,
        x_max_init_data=request.headers.get("x-max-init-data", ""),
        x_active_role=request.headers.get("x-active-role", ""),
        session=session,
    )

    photo = (
        await session.execute(select(AcceptancePhoto).where(AcceptancePhoto.object_key == key))
    ).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="снимок не найден")

    order = await session.get(Order, photo.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="снимок не найден")

    allowed = False
    if identity.buyer and order.client_id == identity.client_id:
        allowed = True
    elif identity.role in (Role.manager, Role.owner):
        storefront = await session.get(Storefront, order.storefront_id)
        allowed = bool(storefront and storefront.enterprise_id == identity.enterprise_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="чужая заявка")

    data, content_type = storage.get(key)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
