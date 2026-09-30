"""работники магазина, автор заявки, «можно писать в MAX» вместо ссылки

Revision ID: 9d4b2f7e1a63
Revises: 7c1f4a9e2b58
Create Date: 2026-09-23 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '9d4b2f7e1a63'
down_revision = '7c1f4a9e2b58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Роль нужна только в перечислении: сотрудники поставщика и работники
    # магазина живут в разных таблицах. В одной транзакции значение не
    # используется, поэтому ADD VALUE здесь допустим (PostgreSQL 12+).
    op.execute("ALTER TYPE role ADD VALUE IF NOT EXISTS 'worker'")

    # Работник магазина — как менеджер у поставщика, только у точки: график
    # нужен, чтобы поставщик видел, кто сейчас на месте.
    op.create_table(
        'client_workers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'client_id', sa.Integer(),
            sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('max_user_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=200), server_default='', nullable=False),
        sa.Column('max_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('work_days', sa.String(length=40), server_default='', nullable=False),
        sa.Column('work_from', sa.Time(), nullable=True),
        sa.Column('work_to', sa.Time(), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ux_client_workers_pair', 'client_workers', ['client_id', 'max_user_id'],
                    unique=True)
    op.create_index('ix_client_workers_max_user_id', 'client_workers', ['max_user_id'])

    # Приглашение работника ведёт в точку, а не в предприятие.
    op.alter_column('invites', 'enterprise_id', existing_type=sa.Integer(), nullable=True)
    op.add_column(
        'invites',
        sa.Column(
            'client_id', sa.Integer(),
            sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=True,
        ),
    )

    # Автор заявки: уведомления — ему, его имя и телефон видит поставщик.
    # У старых заявок автор — владелец точки, другого тогда не бывало.
    op.add_column('orders', sa.Column('created_by', sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE orders SET created_by = clients.max_user_id "
        "FROM clients WHERE clients.id = orders.client_id"
    )

    op.add_column(
        'bot_users',
        sa.Column('max_reachable', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'enterprises',
        sa.Column('max_chat', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Кто раньше вписал профиль MAX или выбрал «чат в MAX», тот писать
    # разрешал — решение сохраняется.
    op.execute(
        "UPDATE enterprises SET max_chat = true "
        "WHERE contact_max <> '' OR contact_kind = 'max'"
    )


def downgrade() -> None:
    op.drop_column('enterprises', 'max_chat')
    op.drop_column('bot_users', 'max_reachable')
    op.drop_column('orders', 'created_by')
    op.drop_column('invites', 'client_id')
    op.alter_column('invites', 'enterprise_id', existing_type=sa.Integer(), nullable=False)
    op.drop_index('ix_client_workers_max_user_id', table_name='client_workers')
    op.drop_index('ux_client_workers_pair', table_name='client_workers')
    op.drop_table('client_workers')
    # Значение перечисления PostgreSQL удалить не умеет — оно остаётся.
