"""типы акций и публичность

Revision ID: f8b02e5d4931
Revises: e4a9c17b60d8
Create Date: 2026-09-22 19:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f8b02e5d4931'
down_revision = 'e4a9c17b60d8'
branch_labels = None
depends_on = None

KIND = sa.Enum("item", "storefront", "volume_amount", "volume_qty", name="promo_kind")


def upgrade() -> None:
    KIND.create(op.get_bind(), checkfirst=True)
    op.add_column('promos', sa.Column('kind', KIND, server_default='item', nullable=False))
    op.add_column('promos', sa.Column('min_amount', sa.Numeric(12, 2), nullable=True))
    op.add_column('promos', sa.Column('min_qty', sa.Numeric(12, 1), nullable=True))
    op.add_column(
        'promos', sa.Column('is_public', sa.Boolean(), server_default='false', nullable=False)
    )
    # Акции, заведённые до появления типов, были именно позиционными.
    op.execute("UPDATE promos SET kind = 'storefront' WHERE item_id IS NULL")


def downgrade() -> None:
    op.drop_column('promos', 'is_public')
    op.drop_column('promos', 'min_qty')
    op.drop_column('promos', 'min_amount')
    op.drop_column('promos', 'kind')
    KIND.drop(op.get_bind(), checkfirst=True)
