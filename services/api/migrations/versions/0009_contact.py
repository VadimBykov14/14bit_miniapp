"""контакт поставщика

Revision ID: c1e8a95d3742
Revises: b9d34e7fa051
Create Date: 2026-09-22 17:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c1e8a95d3742'
down_revision = 'b9d34e7fa051'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'enterprises',
        sa.Column('contact', sa.String(length=120), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('enterprises', 'contact')
