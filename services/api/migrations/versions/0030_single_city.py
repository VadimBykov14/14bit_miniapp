"""город поставщика — снова один: из списка через запятую остаётся первый

Revision ID: 5033d4e6abd3
Revises: 7c2e9a4b1d68
Create Date: 2026-09-28 15:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = '5033d4e6abd3'
down_revision = '7c2e9a4b1d68'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Какое-то время городов можно было выбрать несколько, и они легли в то
    # же поле через запятую. Полка ищет по точному городу и такую витрину
    # не нашла бы ни в одном из них. Остаётся первый: его выбрали раньше
    # остальных — обычно это свой город поставщика.
    op.execute(
        "UPDATE enterprises SET city = btrim(split_part(city, ',', 1)) WHERE city LIKE '%,%'"
    )


def downgrade() -> None:
    # Остальные города не сохранились, а один город прежний код и так читает.
    pass
