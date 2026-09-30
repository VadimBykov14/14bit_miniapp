"""комментарий менеджера, досрочная приёмка, способ связи и профиль

Revision ID: 91f24166f0d1
Revises: c9e04b72d158
Create Date: 2026-09-23 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '91f24166f0d1'
down_revision = 'c9e04b72d158'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'orders', sa.Column('supplier_comment', sa.Text(), server_default='', nullable=False)
    )
    op.add_column(
        'orders',
        sa.Column('accepted_early', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'enterprises',
        sa.Column('contact_kind', sa.String(length=10), server_default='', nullable=False),
    )
    # Раньше контакт был одним полем «телефон или ник». Способ восстанавливаем
    # по виду значения, чтобы кнопка у клиентов не пропала после обновления.
    op.execute(
        """
        UPDATE enterprises SET contact_kind = CASE
            WHEN contact ~ '^[+0-9][0-9 ()-]{6,}$' THEN 'phone'
            WHEN contact <> '' THEN 'max'
            ELSE ''
        END
        """
    )
    op.add_column(
        'bot_users',
        sa.Column('name_edited', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'bot_users', sa.Column('phone', sa.String(length=40), server_default='', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('bot_users', 'phone')
    op.drop_column('bot_users', 'name_edited')
    op.drop_column('enterprises', 'contact_kind')
    op.drop_column('orders', 'accepted_early')
    op.drop_column('orders', 'supplier_comment')
