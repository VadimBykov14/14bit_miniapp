"""оформление витрины: логотип, цвет, описание

Revision ID: a2c95f1e7b40
Revises: f8b02e5d4931
Create Date: 2026-09-22 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a2c95f1e7b40'
down_revision = 'f8b02e5d4931'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('storefronts', sa.Column('logo_key', sa.String(length=120), nullable=True))
    op.add_column('storefronts', sa.Column('color', sa.String(length=9), nullable=True))
    op.add_column(
        'storefronts', sa.Column('about', sa.String(length=160), server_default='', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('storefronts', 'about')
    op.drop_column('storefronts', 'color')
    op.drop_column('storefronts', 'logo_key')
