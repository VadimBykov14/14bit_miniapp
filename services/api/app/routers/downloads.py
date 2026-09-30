"""Скачивание файлов внутри MAX.

Вебвью мессенджера не сохраняет blob-ссылки, и «В Excel» молча не делал
ничего. MAX умеет скачать файл сам — `WebApp.downloadFile(url, name)`, — но
получает только адрес, без заголовка с подписью. Поэтому на выгрузку сервер
выдаёт короткоживущую подписанную ссылку. Прав она не добавляет: выгрузка
по-прежнему проверяет роль того, кому ссылка выдана.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import links
from ..auth import Identity, current_identity

router = APIRouter()

# Только выгрузки: подписать можно не любой адрес API, а то, что скачивают.
FILES = (
    (re.compile(r"^/api/orders/export\.csv$"), "my-orders.csv"),
    (re.compile(r"^/api/owner/export/orders\.csv$"), "orders.csv"),
    (re.compile(r"^/api/owner/storefronts/(\d+)/price-list\.csv$"), "price-{0}.csv"),
)


class DownloadIn(BaseModel):
    path: str


class DownloadOut(BaseModel):
    url: str
    file_name: str


@router.post("/downloads", response_model=DownloadOut)
async def download_link(
    payload: DownloadIn,
    identity: Identity = Depends(current_identity),
) -> DownloadOut:
    for pattern, name in FILES:
        match = pattern.match(payload.path)
        if match:
            role = identity.role.value if identity.role else None
            return DownloadOut(
                url=links.signed(payload.path, identity.max_user_id, role, links.FILE_TTL),
                file_name=name.format(*match.groups()),
            )
    raise HTTPException(status_code=404, detail="такой выгрузки нет")
