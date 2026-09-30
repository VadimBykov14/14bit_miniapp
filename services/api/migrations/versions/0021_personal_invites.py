"""личные приглашения: клиент подключается, только приняв приглашение

Revision ID: 3e8a5c1d7f20
Revises: 9d4b2f7e1a63
Create Date: 2026-09-23 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3e8a5c1d7f20'
down_revision = '9d4b2f7e1a63'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Приглашение из списка «Кто запускал бота» адресовано одному человеку:
    # раньше такой человек подключался сразу, ещё не ответив. Теперь бот
    # присылает ему приглашение с кнопкой, и принять его может только он.
    op.add_column('invites', sa.Column('for_user', sa.BigInteger(), nullable=True))
    op.create_index('ix_invites_for_user', 'invites', ['for_user'])


def downgrade() -> None:
    op.drop_index('ix_invites_for_user', table_name='invites')
    op.drop_column('invites', 'for_user')
