"""Применение миграций при старте.

Раньше схема создавалась через create_all, а новые колонки доезжали списком
идемпотентных ALTER. Это работало, пока правок было три, и переставало бы
работать на первой же переименованной колонке.

Отдельный случай — база, созданная до появления Alembic: таблицы в ней уже
есть, но истории миграций нет. Такую базу помечаем текущей ревизией, а не
пытаемся создать таблицы заново.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("api")

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _state(connection) -> tuple[bool, bool]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    return "alembic_version" in tables, "enterprises" in tables


async def apply(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        versioned, populated = await connection.run_sync(_state)

    if versioned:
        action, message = "upgrade", "миграции применены"
    elif populated:
        action, message = "stamp", "существующая схема помечена текущей ревизией"
    else:
        action, message = "upgrade", "схема создана с нуля"

    def run() -> None:
        config = _config()
        if action == "stamp":
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")

    await asyncio.to_thread(run)
    log.info("%s", message)
