"""след отправленных напоминаний

Revision ID: c8e1a6f24b57
Revises: b2d4f1a7c930
Create Date: 2026-09-22 11:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c8e1a6f24b57'
down_revision = 'b2d4f1a7c930'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('enterprise_id', sa.Integer(), nullable=True),
        sa.Column('storefront_id', sa.Integer(), nullable=True),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
        sa.ForeignKeyConstraint(['enterprise_id'], ['enterprises.id'], ),
        sa.ForeignKeyConstraint(['storefront_id'], ['storefronts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Повторную отправку ловим уникальным индексом, а не проверкой в коде:
    # два процесса api разошлись бы в гонке и отправили дубль.
    op.create_index(
        'ux_reminders_once', 'reminders',
        ['kind', 'client_id', 'enterprise_id', 'storefront_id', 'key'], unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index('ux_reminders_once', table_name='reminders')
    op.drop_table('reminders')
