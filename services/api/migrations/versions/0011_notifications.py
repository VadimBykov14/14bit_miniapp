"""лента уведомлений

Revision ID: e4a9c17b60d8
Revises: d6f2b73c85a9
Create Date: 2026-09-22 19:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4a9c17b60d8'
down_revision = 'd6f2b73c85a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('max_user_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('storefront_id', sa.Integer(), nullable=True),
        sa.Column('delivered', sa.Boolean(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
        sa.ForeignKeyConstraint(['storefront_id'], ['storefronts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_max_user_id'), 'notifications', ['max_user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_max_user_id'), table_name='notifications')
    op.drop_table('notifications')
