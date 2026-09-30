"""шаблоны регулярных заявок

Revision ID: b2d4f1a7c930
Revises: 9505bad0b9e2
Create Date: 2026-09-22 10:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2d4f1a7c930'
down_revision = '9505bad0b9e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'order_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('storefront_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
        sa.ForeignKeyConstraint(['storefront_id'], ['storefronts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_order_templates_client_id'), 'order_templates', ['client_id'])
    op.create_index(op.f('ix_order_templates_storefront_id'), 'order_templates', ['storefront_id'])

    op.create_table(
        'order_template_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['storefront_items.id'], ),
        sa.ForeignKeyConstraint(['template_id'], ['order_templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_order_template_lines_template_id'), 'order_template_lines', ['template_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_order_template_lines_template_id'), table_name='order_template_lines')
    op.drop_table('order_template_lines')
    op.drop_index(op.f('ix_order_templates_storefront_id'), table_name='order_templates')
    op.drop_index(op.f('ix_order_templates_client_id'), table_name='order_templates')
    op.drop_table('order_templates')
