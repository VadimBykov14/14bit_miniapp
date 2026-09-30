"""точка: свой город — по нему полка показывает поставщиков рядом

Revision ID: d6a39f139b20
Revises: 26d91e33ab3e
Create Date: 2026-09-29 13:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd6a39f139b20'
down_revision = '26d91e33ab3e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Пусто у всех прежних точек: их полка остаётся полкой всех городов,
    # пока владелец не выберет город в «Аккаунте».
    op.add_column(
        'clients',
        sa.Column('city', sa.String(length=120), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('clients', 'city')
