"""Окружение Alembic.

Адрес базы берётся из DATABASE_URL, а не из alembic.ini: он один на всё
приложение, и дублировать его в двух местах — верный способ разойтись.
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import Base
from app import models  # noqa: F401 — импорт наполняет metadata

config = context.config
target_metadata = Base.metadata

DATABASE_URL = os.environ.get(
    "ALEMBIC_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://max26:max26@db:5432/max26"),
)


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
