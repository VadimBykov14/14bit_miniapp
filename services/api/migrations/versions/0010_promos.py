"""акции и фотографии позиций

Revision ID: d6f2b73c85a9
Revises: c1e8a95d3742
Create Date: 2026-09-22 17:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd6f2b73c85a9'
down_revision = 'c1e8a95d3742'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('storefront_items', sa.Column('photo_key', sa.String(length=120), nullable=True))
    op.create_table(
        'promos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('storefront_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('discount_percent', sa.Numeric(5, 1), nullable=False),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['storefront_items.id'], ),
        sa.ForeignKeyConstraint(['storefront_id'], ['storefronts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_promos_storefront_id'), 'promos', ['storefront_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_promos_storefront_id'), table_name='promos')
    op.drop_table('promos')
    op.drop_column('storefront_items', 'photo_key')
