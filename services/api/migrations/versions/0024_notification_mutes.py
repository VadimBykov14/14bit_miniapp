"""уведомления в MAX отключаются по видам кнопкой под сообщением

Revision ID: 8f3a6d2c9e41
Revises: 5c2e8a0f3b17
Create Date: 2026-09-25 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8f3a6d2c9e41'
down_revision = '5c2e8a0f3b17'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Под каждым сообщением бота — «Не присылать такие»: отключается вид
    # уведомления на своей стороне, лента в приложении пишет всё по-прежнему.
    op.create_table(
        'notification_mutes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('max_user_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('side', sa.String(length=10), server_default='', nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ux_notification_mutes_once', 'notification_mutes',
        ['max_user_id', 'kind', 'side'], unique=True,
    )
    op.add_column(
        'notifications',
        sa.Column('muted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('notifications', 'muted')
    op.drop_index('ux_notification_mutes_once', table_name='notification_mutes')
    op.drop_table('notification_mutes')
