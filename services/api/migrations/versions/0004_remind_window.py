"""окно напоминания об отсечке — настройка витрины

Revision ID: d5b9e3c14a08
Revises: c8e1a6f24b57
Create Date: 2026-09-22 12:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd5b9e3c14a08'
down_revision = 'c8e1a6f24b57'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'storefronts',
        sa.Column('remind_before_minutes', sa.Integer(), server_default='60', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('storefronts', 'remind_before_minutes')
