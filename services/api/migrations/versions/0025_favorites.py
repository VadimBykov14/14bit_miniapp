"""избранное: витрины, товары и контакты у магазина, клиенты у поставщика

Revision ID: 2d7e4b9a1c56
Revises: 8f3a6d2c9e41
Create Date: 2026-09-25 20:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '2d7e4b9a1c56'
down_revision = '8f3a6d2c9e41'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'favorites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('max_user_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ux_favorites_once', 'favorites', ['max_user_id', 'kind', 'target_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ux_favorites_once', table_name='favorites')
    op.drop_table('favorites')
