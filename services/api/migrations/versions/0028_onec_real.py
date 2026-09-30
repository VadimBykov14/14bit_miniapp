"""настоящая 1С: своя база с логином и паролем, реквизиты заказа, резерв по выбору, ссылки позиций, контрагенты клиентов

Revision ID: 3e8b1c7d5a90
Revises: 9a4d2f6b8c13
Create Date: 2026-09-26 16:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '3e8b1c7d5a90'
down_revision = '9a4d2f6b8c13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('storefronts', sa.Column('onec_user', sa.String(length=100), server_default='', nullable=False))
    op.add_column('storefronts', sa.Column('onec_password', sa.Text(), server_default='', nullable=False))
    op.add_column(
        'storefronts',
        sa.Column('onec_settings', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        'storefronts',
        sa.Column('onec_reserve_now', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column('storefront_items', sa.Column('onec_ref', sa.String(length=40), server_default='', nullable=False))
    op.add_column(
        'storefront_items',
        sa.Column('onec_missing', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        'onec_counterparties',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('storefront_id', sa.Integer(), sa.ForeignKey('storefronts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contractor_key', sa.String(length=40), nullable=False),
        sa.Column('partner_key', sa.String(length=40), server_default='', nullable=False),
        sa.Column('name', sa.String(length=200), server_default='', nullable=False),
    )
    op.create_index(
        'ux_onec_counterparties_pair', 'onec_counterparties', ['storefront_id', 'client_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ux_onec_counterparties_pair', table_name='onec_counterparties')
    op.drop_table('onec_counterparties')
    op.drop_column('storefront_items', 'onec_missing')
    op.drop_column('storefront_items', 'onec_ref')
    op.drop_column('storefronts', 'onec_reserve_now')
    op.drop_column('storefronts', 'onec_settings')
    op.drop_column('storefronts', 'onec_password')
    op.drop_column('storefronts', 'onec_user')
