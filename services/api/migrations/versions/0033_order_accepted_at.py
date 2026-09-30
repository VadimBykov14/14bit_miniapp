"""заявка: когда клиент принял товар — приёмку раньше срока видно в заявке

Revision ID: b7eef71b8f60
Revises: d6a39f139b20
Create Date: 2026-09-29 23:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7eef71b8f60'
down_revision = 'd6a39f139b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'orders', sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True)
    )
    # Уже принятым заявкам — время уведомления о приёмке: поставщику оно
    # уходит в ту же минуту. Где его нет (заявки из сида, стёртая лента),
    # поле остаётся пустым, и заявка пишет «Доставка …», как раньше.
    op.execute(
        """
        UPDATE orders SET accepted_at = told.at
          FROM (SELECT order_id, min(at) AS at
                  FROM notifications
                 WHERE kind = 'accepted' AND order_id IS NOT NULL
                 GROUP BY order_id) AS told
         WHERE orders.id = told.order_id
           AND orders.status IN ('accepted', 'closed')
        """
    )


def downgrade() -> None:
    op.drop_column('orders', 'accepted_at')
