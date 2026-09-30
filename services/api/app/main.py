"""API витрины поставщика."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .body_limit import BodyLimit
from .db import Session, engine
from .routers import (
    cities, downloads, favorites, internal, live, me, notifications, onboarding, orders, owner,
    photos, production, public, reach, storefronts, templates, workers,
)
from . import lifecycle, onec, reminders, stock, storage, testbots
from .migrate import apply as apply_migrations
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")

# Как часто будить планировщик напоминаний. Ноль выключает его совсем —
# удобно для локального запуска, где чат с ботом не заведён.
REMINDER_INTERVAL = int(os.environ.get("REMINDER_INTERVAL_SECONDS", "300"))
# Как часто перечитывать остатки витрин из 1С. Эмулятор сам сообщает об
# изменениях, а боевая 1С по OData — нет, и для неё это единственный способ
# узнать о списании или приходе. Ноль выключает фоновый проход.
STOCK_INTERVAL = int(os.environ.get("ONEC_SYNC_SECONDS", "60"))


async def _background_loop() -> None:
    """Фоновый проход: отсечка и забытая отгрузка, напоминания и повторная
    выгрузка в 1С.

    Отдельного планировщика в системе нет намеренно: один контейнер api,
    одна корутина и отметка об отправке в базе надёжнее второго сервиса,
    который нужно поднимать, мониторить и который в демо только мешает.
    Каждая часть — своей попыткой: сбой напоминаний не должен оставить
    заявки без статуса «в производстве».
    """
    # Повторная выгрузка — тем же проходом: «в очереди» не должно быть
    # вечным статусом.
    jobs = (("заявки", lifecycle.run), ("напоминания", reminders.run), ("1С", onec.retry_queued))
    while True:
        await asyncio.sleep(REMINDER_INTERVAL)
        for name, job in jobs:
            try:
                async with Session() as session:
                    await job(session)
            except Exception as exc:  # noqa: BLE001 — цикл не имеет права умереть
                log.warning("фоновый проход «%s» не удался: %s", name, exc)


async def _stock_loop() -> None:
    """Фоновое чтение остатков: то, что изменилось в 1С без нас, доезжает
    до каталога не позже чем через минуту. Первый проход — сразу после
    старта: за время простоя в 1С могло измениться что угодно."""
    delay = 5
    while True:
        await asyncio.sleep(delay)
        delay = STOCK_INTERVAL
        try:
            await stock.refresh_all()
        except Exception as exc:  # noqa: BLE001 — цикл не имеет права умереть
            log.warning("фоновое чтение остатков не удалось: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await apply_migrations(engine)
    storage.ensure_bucket()
    async with Session() as session:
        await seed(session)

    tasks = []
    if REMINDER_INTERVAL > 0:
        tasks.append(asyncio.create_task(_background_loop()))
    if STOCK_INTERVAL > 0:
        tasks.append(asyncio.create_task(_stock_loop()))
    # Вторая сторона сценария для проверяющих — см. app/testbots.py.
    if testbots.ENABLED:
        tasks.append(asyncio.create_task(testbots.run(app)))
    log.info("api готов")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await engine.dispose()


app = FastAPI(title="max26 api", lifespan=lifespan)
app.add_middleware(BodyLimit)

app.include_router(internal.router)
app.include_router(me.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(storefronts.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(production.router, prefix="/api")
app.include_router(owner.router, prefix="/api")
app.include_router(photos.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")
app.include_router(reach.router, prefix="/api")
app.include_router(live.router, prefix="/api")
app.include_router(workers.router, prefix="/api")
app.include_router(cities.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
