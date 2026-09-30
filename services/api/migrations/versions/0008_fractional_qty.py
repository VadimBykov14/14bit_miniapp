"""дробные количества с точностью до одной десятой

Revision ID: b9d34e7fa051
Revises: a4f70c2d8b13
Create Date: 2026-09-22 16:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b9d34e7fa051'
down_revision = 'a4f70c2d8b13'
branch_labels = None
depends_on = None

# Целое → Numeric(_, 1) расширяет тип, данные переносятся без потерь.
COLUMNS = (
    ("storefront_items", "pack_size", sa.Numeric(10, 1), False),
    ("storefront_items", "stock", sa.Numeric(12, 1), False),
    ("storefront_items", "daily_limit", sa.Numeric(12, 1), True),
    ("order_items", "qty_ordered", sa.Numeric(12, 1), False),
    ("order_items", "qty_confirmed", sa.Numeric(12, 1), True),
    ("order_items", "qty_accepted", sa.Numeric(12, 1), True),
    ("order_template_lines", "qty", sa.Numeric(12, 1), False),
)


def upgrade() -> None:
    for table, column, kind, nullable in COLUMNS:
        op.alter_column(table, column, type_=kind, nullable=nullable,
                        existing_type=sa.Integer(), postgresql_using=f"{column}::numeric")


def downgrade() -> None:
    # Обратный переход округляет дробные количества до целых — иначе
    # 0,5 кг просто не поместится в колонку.
    for table, column, _, nullable in COLUMNS:
        op.alter_column(table, column, type_=sa.Integer(), nullable=nullable,
                        postgresql_using=f"round({column})::integer")
