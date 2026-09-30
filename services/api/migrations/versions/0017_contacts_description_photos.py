"""раздельные телефон и профиль MAX, описание позиции, прикреплённые снимки

Revision ID: 3e8a5c1d7b92
Revises: 91f24166f0d1
Create Date: 2026-09-24 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3e8a5c1d7b92'
down_revision = '91f24166f0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Одно поле на два способа связи путало поставщика: переключишь способ —
    # и номер телефона стоит в поле «профиль MAX». Теперь у каждого своё.
    op.add_column(
        'enterprises',
        sa.Column('contact_phone', sa.String(length=40), server_default='', nullable=False),
    )
    op.add_column(
        'enterprises',
        sa.Column('contact_max', sa.String(length=200), server_default='', nullable=False),
    )
    op.execute("UPDATE enterprises SET contact_phone = contact WHERE contact_kind = 'phone'")
    op.execute("UPDATE enterprises SET contact_max = contact WHERE contact_kind = 'max'")
    op.drop_column('enterprises', 'contact')

    op.add_column(
        'storefront_items',
        sa.Column('description', sa.Text(), server_default='', nullable=False),
    )

    # Снимок загружается сразу, а в заявку попадает только при приёмке.
    # Старые снимки уже были частью закрытых приёмок — они прикреплены.
    op.add_column(
        'acceptance_photos',
        sa.Column('attached', sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('acceptance_photos', 'attached')
    op.drop_column('storefront_items', 'description')
    op.add_column(
        'enterprises',
        sa.Column('contact', sa.String(length=120), server_default='', nullable=False),
    )
    op.execute(
        """
        UPDATE enterprises SET contact = CASE
            WHEN contact_kind = 'phone' THEN contact_phone
            ELSE contact_max
        END
        """
    )
    op.drop_column('enterprises', 'contact_max')
    op.drop_column('enterprises', 'contact_phone')
