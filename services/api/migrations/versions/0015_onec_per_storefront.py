"""подключение к 1С переезжает с предприятия на витрину

Revision ID: c9e04b72d158
Revises: b7d13ac48f02
Create Date: 2026-09-22 22:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c9e04b72d158'
down_revision = 'b7d13ac48f02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'storefronts', sa.Column('onec_key', sa.String(length=200), server_default='', nullable=False)
    )
    op.add_column(
        'storefronts', sa.Column('onec_url', sa.String(length=300), server_default='', nullable=False)
    )
    # Настройку, заведённую на предприятии, переносим на его витрины:
    # терять уже подключённую базу при обновлении нельзя.
    op.execute(
        """
        UPDATE storefronts SET
            onec_key = enterprises.onec_key,
            onec_url = enterprises.onec_url
        FROM enterprises
        WHERE enterprises.id = storefronts.enterprise_id
          AND enterprises.onec_key <> ''
        """
    )
    op.drop_column('enterprises', 'onec_key')
    op.drop_column('enterprises', 'onec_url')


def downgrade() -> None:
    op.add_column(
        'enterprises', sa.Column('onec_url', sa.String(length=300), server_default='', nullable=False)
    )
    op.add_column(
        'enterprises', sa.Column('onec_key', sa.String(length=200), server_default='', nullable=False)
    )
    op.drop_column('storefronts', 'onec_url')
    op.drop_column('storefronts', 'onec_key')
