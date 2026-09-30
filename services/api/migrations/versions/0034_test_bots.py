"""тестовые боты: признак бота у предприятия и магазина, время создания витрины

Revision ID: 5c2e9a4d7b13
Revises: b7eef71b8f60
Create Date: 2026-09-30 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5c2e9a4d7b13'
down_revision = 'b7eef71b8f60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'enterprises',
        sa.Column('is_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'clients',
        sa.Column('is_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Время создания — только у новых витрин: колонку заводим пустой и лишь
    # потом ставим умолчание. Иначе все прежние витрины получили бы время
    # выкатки, и бот-магазин попросился бы к каждой разом.
    op.add_column(
        'storefronts', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column('storefronts', 'created_at', server_default=sa.text('now()'))


def downgrade() -> None:
    op.drop_column('storefronts', 'created_at')
    op.drop_column('clients', 'is_bot')
    op.drop_column('enterprises', 'is_bot')
