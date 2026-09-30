"""аудитория бота

Revision ID: f3a81d60c2e9
Revises: e7c2f0a93d61
Create Date: 2026-09-22 14:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3a81d60c2e9'
down_revision = 'e7c2f0a93d61'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bot_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('max_user_id', sa.BigInteger(), nullable=False),
        sa.Column('max_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('first_name', sa.String(length=120), nullable=False),
        sa.Column('last_name', sa.String(length=120), nullable=False),
        sa.Column('username', sa.String(length=120), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bot_users_max_user_id'), 'bot_users', ['max_user_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_bot_users_max_user_id'), table_name='bot_users')
    op.drop_table('bot_users')
