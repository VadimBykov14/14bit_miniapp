"""позиция: минимальное количество в одной заявке

Revision ID: 26d91e33ab3e
Revises: 5033d4e6abd3
Create Date: 2026-09-29 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '26d91e33ab3e'
down_revision = '5033d4e6abd3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Пусто — минимума нет, как у всех позиций до сих пор.
    op.add_column(
        'storefront_items', sa.Column('min_qty', sa.Numeric(12, 1), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('storefront_items', 'min_qty')
