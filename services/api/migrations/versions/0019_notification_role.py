"""роль получателя у уведомления

Revision ID: 7c1f4a9e2b58
Revises: 5b7d2e9a4c31
Create Date: 2026-09-23 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7c1f4a9e2b58'
down_revision = '5b7d2e9a4c31'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # У человека бывает несколько ролей: владелец пекарни — ещё и клиент
    # базы. Кнопка «Открыть заявку» должна открыть её в той роли, в которой
    # пришло уведомление, иначе заявка поставщика откроется клиенту и не
    # найдётся.
    op.add_column(
        'notifications',
        sa.Column('role', sa.String(length=10), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('notifications', 'role')
