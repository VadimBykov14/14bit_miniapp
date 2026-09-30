"""заявка помнит, списан ли её товар со склада витрины

Revision ID: 7b1d9c4e2a85
Revises: 3e8a5c1d7f20
Create Date: 2026-09-24 22:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7b1d9c4e2a85'
down_revision = '3e8a5c1d7f20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Раньше признаком «товар уже списан» был номер документа 1С: остаток
    # уменьшался, когда заказ вставал в учёт. Витрина без 1С теперь в 1С
    # не выгружается и списывает при подтверждении, поэтому признак свой.
    op.add_column(
        'orders',
        sa.Column('stock_taken', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Всё, что уже встало в 1С и не отменено, списано — так было до этой
    # миграции, и остаток витрины это уже учитывает.
    op.execute(
        "UPDATE orders SET stock_taken = true "
        "WHERE onec_document IS NOT NULL AND status NOT IN ('rejected', 'cancelled')"
    )


def downgrade() -> None:
    op.drop_column('orders', 'stock_taken')
