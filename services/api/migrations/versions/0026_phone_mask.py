"""телефоны по маске +7 (900) 123-45-67: 10 цифр дополняются семёркой, иностранные стираются

Revision ID: 5c1f8e3a7b20
Revises: 2d7e4b9a1c56
Create Date: 2026-09-26 12:00:00.000000
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = '5c1f8e3a7b20'
down_revision = '2d7e4b9a1c56'
branch_labels = None
depends_on = None

# Колонки с телефоном: номер человека и общий номер предприятия.
COLUMNS = (('bot_users', 'phone'), ('enterprises', 'contact_phone'))


def masked(value: str) -> str:
    """Своя копия правила из app/contact.py: миграция не должна меняться
    вместе с кодом приложения. Номер, который к +7 не привести, стираем —
    человек введёт его заново, а битый номер в заявке хуже пустого."""
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 10:
        digits = '7' + digits
    if len(digits) != 11 or digits[0] not in '78':
        return ''
    return f'+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}'


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in COLUMNS:
        rows = bind.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} <> ''")
        ).all()
        for row_id, value in rows:
            fixed = masked(value)
            if fixed != value:
                bind.execute(
                    sa.text(f'UPDATE {table} SET {column} = :value WHERE id = :id'),
                    {'value': fixed, 'id': row_id},
                )


def downgrade() -> None:
    # Прежний вид номера не сохранился, а маска его и так читает.
    pass
