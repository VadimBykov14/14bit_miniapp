"""Регистрация вебхука в MAX.

Запускать на сервере, где уже лежит .env:
    docker compose run --rm bot python set_webhook.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from max_client import DEFAULT_BASE, MaxClient


async def main() -> int:
    token = os.environ["MAX_BOT_TOKEN"]
    domain = os.environ.get("BOT_DOMAIN", "").strip()
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not domain:
        print("BOT_DOMAIN пуст — некуда регистрировать вебхук", file=sys.stderr)
        return 2

    url = f"https://{domain}/webhook"
    client = MaxClient(token, base_url=os.environ.get("MAX_API_BASE", DEFAULT_BASE))
    try:
        me = await client.get_me()
        print(f"бот: {me.get('username')} (id {me.get('user_id')})")

        existing = (await client.get_subscriptions()).get("subscriptions", [])
        for sub in existing:
            if sub.get("url") == url:
                print(f"подписка на {url} уже есть — пересоздаю, чтобы обновить секрет")
                await client.unsubscribe(url)

        # message_callback — нажатия кнопок под сообщениями: «Не присылать такие».
        await client.subscribe(
            url, secret=secret,
            update_types=["message_created", "bot_started", "message_callback"],
        )
        print(f"вебхук зарегистрирован: {url}")

        for sub in (await client.get_subscriptions()).get("subscriptions", []):
            print(f"  подписка: {sub.get('url')}")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
