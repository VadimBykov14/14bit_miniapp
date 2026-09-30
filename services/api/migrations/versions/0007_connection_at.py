"""дата подключения клиента

Revision ID: a4f70c2d8b13
Revises: f3a81d60c2e9
Create Date: 2026-09-22 16:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a4f70c2d8b13'
down_revision = 'f3a81d60c2e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'connections',
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('connections', 'at')
