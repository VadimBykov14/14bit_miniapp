"""номер заявки — свой у каждого поставщика, а не сквозной по стенду

Revision ID: 7c2e9a4b1d68
Revises: 3e8b1c7d5a90
Create Date: 2026-09-26 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7c2e9a4b1d68'
down_revision = '3e8b1c7d5a90'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('number', sa.Integer(), nullable=True))
    # Прежние заявки нумеруются у каждого поставщика по порядку создания.
    op.execute(
        """
        UPDATE orders SET number = numbered.n
        FROM (
            SELECT orders.id,
                   row_number() OVER (PARTITION BY storefronts.enterprise_id ORDER BY orders.id) AS n
            FROM orders JOIN storefronts ON storefronts.id = orders.storefront_id
        ) AS numbered
        WHERE numbered.id = orders.id
        """
    )


def downgrade() -> None:
    op.drop_column('orders', 'number')
