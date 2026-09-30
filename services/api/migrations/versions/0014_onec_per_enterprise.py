"""своя база 1С у каждого предприятия

Revision ID: b7d13ac48f02
Revises: a2c95f1e7b40
Create Date: 2026-09-22 21:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7d13ac48f02'
down_revision = 'a2c95f1e7b40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'enterprises', sa.Column('onec_url', sa.String(length=300), server_default='', nullable=False)
    )
    op.add_column(
        'enterprises', sa.Column('onec_key', sa.String(length=200), server_default='', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('enterprises', 'onec_key')
    op.drop_column('enterprises', 'onec_url')
