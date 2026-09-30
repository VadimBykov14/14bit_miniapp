"""приглашения из аудитории бота считаются: не больше лимита в день

Revision ID: 5c2e8a0f3b17
Revises: 7b1d9c4e2a85
Create Date: 2026-09-25 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5c2e8a0f3b17'
down_revision = '7b1d9c4e2a85'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Список «Кто запускал бота» видит любой владелец, и раньше он мог
    # разослать приглашение каждому. Каждая отправка — строка здесь, по ним
    # считается дневной лимит.
    op.create_table(
        'invite_sends',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sender_id', sa.BigInteger(), nullable=False),
        sa.Column('recipient_id', sa.BigInteger(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_invite_sends_sender_at', 'invite_sends', ['sender_id', 'at'])


def downgrade() -> None:
    op.drop_index('ix_invite_sends_sender_at', table_name='invite_sends')
    op.drop_table('invite_sends')
