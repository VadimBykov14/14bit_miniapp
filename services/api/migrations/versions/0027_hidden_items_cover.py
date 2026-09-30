"""витрина: позицию можно скрыть, у витрины появляется фото

Revision ID: 9a4d2f6b8c13
Revises: 5c1f8e3a7b20
Create Date: 2026-09-26 13:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '9a4d2f6b8c13'
down_revision = '5c1f8e3a7b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'storefront_items',
        sa.Column('hidden', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column('storefronts', sa.Column('cover_key', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('storefronts', 'cover_key')
    op.drop_column('storefront_items', 'hidden')
