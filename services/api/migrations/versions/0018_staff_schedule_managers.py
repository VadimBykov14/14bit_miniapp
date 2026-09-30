"""график сотрудников, закреплённый менеджер клиента, менеджер заявки

Revision ID: 5b7d2e9a4c31
Revises: 3e8a5c1d7b92
Create Date: 2026-09-23 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5b7d2e9a4c31'
down_revision = '3e8a5c1d7b92'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # График нужен клиенту, а не отделу кадров: кто сейчас на связи.
    # Пустые дни — «график не указан», такой сотрудник в «Связаться» не
    # попадает, если он не закреплён за клиентом.
    op.add_column(
        'employees',
        sa.Column('work_days', sa.String(length=40), server_default='', nullable=False),
    )
    op.add_column('employees', sa.Column('work_from', sa.Time(), nullable=True))
    op.add_column('employees', sa.Column('work_to', sa.Time(), nullable=True))

    # Закрепление живёт у пары «предприятие ↔ клиент», а не у клиента:
    # кафе покупает у нескольких поставщиков, и у каждого свой менеджер.
    op.create_table(
        'client_managers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'enterprise_id', sa.Integer(),
            sa.ForeignKey('enterprises.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'client_id', sa.Integer(),
            sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'employee_id', sa.Integer(),
            sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('enterprise_id', 'client_id', name='ux_client_managers_pair'),
    )

    # Кто ведёт заявку со стороны поставщика: закреплённый менеджер или тот,
    # кто первым её обработал. Сотрудника удалили — заявка остаётся.
    op.add_column(
        'orders',
        sa.Column(
            'manager_id', sa.Integer(),
            sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('orders', 'manager_id')
    op.drop_table('client_managers')
    op.drop_column('employees', 'work_to')
    op.drop_column('employees', 'work_from')
    op.drop_column('employees', 'work_days')
