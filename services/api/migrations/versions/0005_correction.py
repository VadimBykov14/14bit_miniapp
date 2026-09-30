"""корректировка приёмки в 1С

Revision ID: e7c2f0a93d61
Revises: d5b9e3c14a08
Create Date: 2026-09-22 13:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e7c2f0a93d61'
down_revision = 'd5b9e3c14a08'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('onec_correction', sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'onec_correction')
