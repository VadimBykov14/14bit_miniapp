"""Уведомление человеку: лента в приложении плюс сообщение в MAX.

Адрес у человека может быть двух видов, и ни один не работает всегда:

* `user_id` из подписи запуска есть у каждого, кто открыл мини-приложение,
  но `POST /messages?user_id=` отвечает 404, если такого пользователя в MAX
  нет — например, на синтетическом стенде;
* `chat_id` появляется только после первого сообщения боту, зато по нему
  доставка идёт наверняка.

Поэтому отправляем оба и даём bot-service выбрать. А запись в ленте кладём
в любом случае: сообщение может не дойти, но человек должен иметь
возможность увидеть, что произошло.

Один сигнал — одно место. Если у события есть свой значок — новая заявка
горит на «Заявках», отгрузка на «Заказах», — запись в ленте ложится сразу
прочитанной (`quiet`). Иначе одна заявка зажигала два значка, и второй гас
только после того, как человек сходит в «Аккаунт» и прочитает то, что уже
сделал. Просьба о подключении своего значка не имеет — она горит в
«Аккаунте» и гаснет, когда владелец открывает «Подключения».

У сообщения в MAX есть кнопка, которая открывает приложение сразу там, где
дело: заявку, «Подключения», витрину. Иначе из уведомления человек
попадал на главную и искал заявку по номеру сам. Вторая кнопка — «Не
присылать такие»: отключённый вид в MAX не уходит, но в ленту ложится.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from . import live, mutes
from .audience import known_chat
from .models import Notification
from .notify import send


def button_for(
    kind: str, order_id: int | None, storefront_id: int | None, role: str | None = None
) -> dict:
    """Куда ведёт кнопка под сообщением. Ярлык — адрес экрана внутри
    приложения: его разбирает мини-приложение при запуске. У заявки к ярлыку
    приписана роль получателя: у владельца пекарни, который ещё и клиент
    базы, заявка поставщика должна открыться в роли сотрудника."""
    if order_id:
        suffix = f"_{role}" if role in ("client", "worker", "manager", "owner") else ""
        return {"text": "Открыть заявку", "payload": f"order_{order_id}{suffix}"}
    if kind == "join_request":
        return {"text": "Рассмотреть просьбу", "payload": "connections"}
    if kind == "joined":
        return {"text": "Открыть клиентов", "payload": "clients"}
    if kind == "joined_staff":
        return {"text": "Открыть сотрудников", "payload": "staff"}
    if kind == "staff_cutoff":
        return {"text": "Открыть заявки", "payload": "orders_staff"}
    if storefront_id and kind == "connection":
        return {"text": "Открыть витрину", "payload": f"sf_{storefront_id}"}
    if storefront_id and kind in ("cutoff", "reorder"):
        return {"text": "Собрать заявку", "payload": f"sf_{storefront_id}"}
    if kind == "connection":
        return {"text": "Мои витрины", "payload": "storefronts"}
    return {"text": "Открыть приложение", "payload": ""}


async def tell(
    session: AsyncSession,
    user_id: int | None,
    text: str,
    kind: str = "info",
    order_id: int | None = None,
    storefront_id: int | None = None,
    quiet: bool = False,
    role: str | None = None,
) -> bool:
    # Отрицательный id — тестовый бот стенда (app/testbots.py): чата в MAX у
    # него нет, а лента ему не нужна.
    if not user_id or user_id < 0:
        return False

    side = mutes.side(role)
    muted = await mutes.is_muted(session, user_id, kind, side)
    delivered = False
    if not muted:
        delivered = await send(
            user_id,
            text,
            chat_id=await known_chat(session, user_id),
            button=button_for(kind, order_id, storefront_id, role),
            mute=mutes.payload(kind, side),
        )
    session.add(
        Notification(
            max_user_id=user_id,
            kind=kind,
            text=text,
            order_id=order_id,
            storefront_id=storefront_id,
            delivered=delivered,
            muted=muted,
            read_at=datetime.now(timezone.utc) if quiet else None,
            role=role or "",
        )
    )
    # Коммитим здесь же. Уведомление отправляется последним действием
    # обработчика, когда основная работа уже сохранена, и ждать чужого
    # коммита запись не может: его просто не будет.
    await session.commit()
    # Открытое приложение узнаёт о событии сразу: лента, значки и сама заявка.
    topics = ["feed", "badges"]
    if order_id:
        topics += ["orders", f"order:{order_id}"]
    await live.publish([user_id], *topics)
    return delivered
