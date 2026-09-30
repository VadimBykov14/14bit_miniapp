"""Тесты bot-service.

MAX API подменён локальным стабом: проверяем не «код написан», а что бот
действительно отвечает в чат и что вебхук не пускает чужих.

Запуск:  /tmp/max26-venv/bin/python services/bot-service/test_bot.py
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SENT: list[dict] = []
RECEIVED_AUTH: list[str] = []
# Отвергать сообщения с клавиатурой — так MAX отвечает на кривую кнопку.
REJECT_KEYBOARD = {"on": False}
# Не принимать сообщения вовсе — так MAX отвечает тому, кто не открывал бота.
REJECT_ALL = {"on": False}
# Ответы на нажатия кнопок и то, что бот передал в API об отключении.
ANSWERS: list[dict] = []
MUTED: list[dict] = []
API_DOWN = {"on": False}


class FakeMax(BaseHTTPRequestHandler):
    """Минимальный стаб MAX Bot API."""

    def log_message(self, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        RECEIVED_AUTH.append(self.headers.get("Authorization", ""))
        if self.path.startswith("/me"):
            return self._json(200, {"user_id": 42, "username": "test_bot", "is_bot": True})
        if self.path.startswith("/subscriptions"):
            return self._json(200, {"subscriptions": []})
        return self._json(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/internal/invites/card"):
            # Текст приглашения знает API — здесь его подменяет стаб.
            return self._json(200, {
                "text": "Пекарня приглашает вас к витрине «Хлеб».",
                "button": {"text": "Принять приглашение", "payload": body.get("code")},
                "valid": True,
            })
        if self.path.startswith("/internal/notifications/mute"):
            if API_DOWN["on"]:
                return self._json(500, {})
            MUTED.append(body)
            return self._json(200, {"label": "напоминания об отсечке"})
        if self.path.startswith("/answers"):
            ANSWERS.append({"path": self.path, **body})
            return self._json(200, {"success": True})
        if self.path.startswith("/messages"):
            if REJECT_ALL["on"]:
                return self._json(404, {"code": "not.found"})
            attachments = body.get("attachments") or []
            if REJECT_KEYBOARD["on"] and any(a.get("type") == "inline_keyboard" for a in attachments):
                return self._json(400, {"code": "attachment.invalid"})
            SENT.append({"path": self.path, "text": body.get("text", ""), "attachments": attachments})
            return self._json(200, {"message": {"body": {"mid": "m1", "text": body.get("text")}}})
        return self._json(404, {})


stub = ThreadingHTTPServer(("127.0.0.1", 0), FakeMax)
threading.Thread(target=stub.serve_forever, daemon=True).start()
STUB_URL = f"http://127.0.0.1:{stub.server_address[1]}"

os.environ["MAX_BOT_TOKEN"] = "test-token"
os.environ["WEBHOOK_SECRET"] = "s3cr3t"
os.environ["MAX_API_BASE"] = STUB_URL
os.environ["API_INTERNAL_URL"] = STUB_URL
os.environ["BOT_DOMAIN"] = "example.test"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import httpx  # noqa: E402
from app import app  # noqa: E402


def call(path, payload=None, headers=None, method="POST"):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                if method == "GET":
                    return await client.get(path, headers=headers or {})
                return await client.post(path, json=payload, headers=headers or {})

    return asyncio.run(run())


def message_update(text, chat_id=777, name="Анна", is_bot=False):
    return {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 5, "first_name": name, "is_bot": is_bot},
            "recipient": {"chat_id": chat_id, "chat_type": "dialog"},
            "body": {"mid": "m", "seq": 1, "text": text},
        },
    }


GOOD = {"X-Max-Bot-Api-Secret": "s3cr3t"}


class BotTest(unittest.TestCase):
    def setUp(self):
        SENT.clear()
        RECEIVED_AUTH.clear()
        ANSWERS.clear()
        MUTED.clear()
        REJECT_KEYBOARD["on"] = False
        REJECT_ALL["on"] = False
        API_DOWN["on"] = False

    def test_invite_link_gets_invitation_with_accept_button(self):
        """Ссылка-приглашение открывает чат, и бот присылает приглашение с
        кнопкой, которая открывает приложение с тем же кодом."""
        update = {"update_type": "bot_started", "timestamp": 1, "chat_id": 999,
                  "user": {"user_id": 5, "first_name": "Анна"}, "payload": "inv_Ab3-x9"}
        call("/webhook", update, GOOD)
        self.assertEqual(len(SENT), 1)
        self.assertIn("Пекарня приглашает", SENT[0]["text"])
        button = SENT[0]["attachments"][0]["payload"]["buttons"][0][0]
        self.assertEqual(button["type"], "open_app")
        self.assertEqual(button["text"], "Принять приглашение")
        self.assertEqual(button["payload"], "inv_Ab3-x9")

    def test_start_command_with_invite_code(self):
        """Диалог с ботом уже был — код приходит командой «/start <код>»."""
        call("/webhook", message_update("/start wrk_Zz9yy1"), GOOD)
        self.assertEqual(len(SENT), 1)
        button = SENT[0]["attachments"][0]["payload"]["buttons"][0][0]
        self.assertEqual(button["payload"], "wrk_Zz9yy1")

    def test_notify_reports_whether_message_got_through(self):
        """«Доставлено» в ленте — только если MAX принял сообщение."""
        res = call("/internal/notify", {"user_id": 5, "text": "Заявка №9"})
        self.assertTrue(res.json()["sent"])
        REJECT_ALL["on"] = True
        res = call("/internal/notify", {"user_id": 5, "text": "Заявка №9"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["sent"])

    def test_notification_carries_open_app_button(self):
        """Кнопка под уведомлением открывает приложение сразу на заявке."""
        res = call("/internal/notify", {
            "user_id": 5, "text": "Новая заявка №7",
            "button": {"text": "Открыть заявку", "payload": "order_7"},
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(SENT), 1)
        keyboard = SENT[0]["attachments"][0]
        self.assertEqual(keyboard["type"], "inline_keyboard")
        button = keyboard["payload"]["buttons"][0][0]
        self.assertEqual(button["type"], "open_app")
        self.assertEqual(button["web_app"], "test_bot")
        self.assertEqual(button["contact_id"], 42)
        self.assertEqual(button["payload"], "order_7")

    def test_bad_payload_drops_button_not_message(self):
        res = call("/internal/notify", {
            "user_id": 5, "text": "Привет", "button": {"text": "Открыть", "payload": "a b/c"},
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(SENT[0]["attachments"], [])

    def test_rejected_button_falls_back_to_plain_message(self):
        """Кнопка — удобство, уведомление обязано дойти."""
        REJECT_KEYBOARD["on"] = True
        res = call("/internal/notify", {
            "user_id": 5, "text": "Заявка №8 подтверждена",
            "button": {"text": "Открыть заявку", "payload": "order_8"},
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(SENT), 1)
        self.assertEqual(SENT[0]["text"], "Заявка №8 подтверждена")
        self.assertEqual(SENT[0]["attachments"], [])

    def test_contact_card(self):
        """«Написать»: карточка контакта с id человека в MAX."""
        res = call("/internal/contact", {
            "user_id": 5, "contact_id": 77, "name": "Ирина", "text": "Ирина — нажмите на карточку",
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["sent"])
        card = SENT[0]["attachments"][0]
        self.assertEqual(card["type"], "contact")
        self.assertEqual(card["payload"]["contact_id"], 77)
        self.assertEqual(card["payload"]["name"], "Ирина")

    def test_replies_to_a_message(self):
        """На любой текст — короткий ответ и кнопка в приложение, без эха
        и без «ты»."""
        res = call("/webhook", message_update("почём хлеб"), GOOD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(SENT), 1, "бот обязан ответить")
        self.assertNotIn("почём хлеб", SENT[0]["text"])
        self.assertIsNone(re.search(r"\b(ты|тебя|написал)\b", SENT[0]["text"].lower()))
        self.assertIn("в приложении", SENT[0]["text"])
        self.assertIn("chat_id=777", SENT[0]["path"])
        button = SENT[0]["attachments"][0]["payload"]["buttons"][0][0]
        self.assertEqual(button["type"], "open_app")

    def test_notification_offers_to_mute_its_kind(self):
        """Под уведомлением — «Не присылать такие» с видом и стороной."""
        call("/internal/notify", {
            "user_id": 5, "text": "До отсечки 40 минут",
            "button": {"text": "Собрать заявку", "payload": "sf_3"},
            "mute": "mute:cutoff:",
        })
        rows = SENT[0]["attachments"][0]["payload"]["buttons"]
        self.assertEqual(rows[0][0]["type"], "open_app")
        self.assertEqual(rows[1][0], {"type": "callback", "text": "Не присылать такие",
                                      "payload": "mute:cutoff:"})

    def test_odd_mute_payload_drops_only_that_button(self):
        call("/internal/notify", {
            "user_id": 5, "text": "Заявка №9",
            "button": {"text": "Открыть заявку", "payload": "order_9"},
            "mute": "mute:../x:staff",
        })
        rows = SENT[0]["attachments"][0]["payload"]["buttons"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0]["type"], "open_app")

    def test_mute_press_is_passed_to_api_and_answered(self):
        """Нажатие «Не присылать такие»: API отключает вид, а человек сразу
        видит, что именно больше не придёт и где вернуть."""
        update = {
            "update_type": "message_callback", "timestamp": 1,
            "callback": {"timestamp": 1, "callback_id": "cb-1", "payload": "mute:cutoff:shop",
                         "user": {"user_id": 5, "first_name": "Анна", "is_bot": False}},
            "message": None,
        }
        res = call("/webhook", update, GOOD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(MUTED, [{"user_id": 5, "payload": "mute:cutoff:shop"}])
        self.assertEqual(len(ANSWERS), 1)
        self.assertIn("callback_id=cb-1", ANSWERS[0]["path"])
        self.assertIn("напоминания об отсечке", ANSWERS[0]["notification"])
        self.assertIn("«Аккаунте»", ANSWERS[0]["notification"])
        self.assertEqual(SENT, [], "в чат новых сообщений не надо")

    def test_mute_press_when_api_is_down_says_so(self):
        API_DOWN["on"] = True
        update = {
            "update_type": "message_callback", "timestamp": 1,
            "callback": {"timestamp": 1, "callback_id": "cb-2", "payload": "mute:order:staff",
                         "user": {"user_id": 5, "first_name": "Анна", "is_bot": False}},
        }
        call("/webhook", update, GOOD)
        self.assertIn("Не получилось", ANSWERS[0]["notification"])

    def test_unknown_button_is_still_answered(self):
        update = {
            "update_type": "message_callback", "timestamp": 1,
            "callback": {"timestamp": 1, "callback_id": "cb-3", "payload": "что-то старое",
                         "user": {"user_id": 5, "first_name": "Анна", "is_bot": False}},
        }
        call("/webhook", update, GOOD)
        self.assertEqual(MUTED, [])
        self.assertEqual(len(ANSWERS), 1)

    def test_greets_on_start_command(self):
        call("/webhook", message_update("/start"), GOOD)
        self.assertEqual(len(SENT), 1)
        self.assertIn("Привет, Анна", SENT[0]["text"])

    def test_greets_on_bot_started(self):
        update = {"update_type": "bot_started", "timestamp": 1, "chat_id": 999,
                  "user": {"user_id": 5, "first_name": "Анна"}}
        call("/webhook", update, GOOD)
        self.assertEqual(len(SENT), 1)
        self.assertIn("chat_id=999", SENT[0]["path"])

    def test_rejects_wrong_secret(self):
        res = call("/webhook", message_update("привет"), {"X-Max-Bot-Api-Secret": "wrong-secret"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(SENT, [], "на чужой запрос бот отвечать не должен")

    def test_rejects_missing_secret(self):
        res = call("/webhook", message_update("привет"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(SENT, [])

    def test_ignores_own_messages(self):
        """Иначе бот отвечает сам себе и уходит в петлю."""
        call("/webhook", message_update("эхо", is_bot=True), GOOD)
        self.assertEqual(SENT, [])

    def test_unknown_update_type_is_acknowledged(self):
        """Возврат не-200 заставил бы MAX ретраить событие, которое мы всё равно не обрабатываем."""
        res = call("/webhook", {"update_type": "dialog_muted", "timestamp": 1}, GOOD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(SENT, [])

    def test_sends_token_in_authorization_header(self):
        call("/webhook", message_update("привет"), GOOD)
        self.assertIn("test-token", RECEIVED_AUTH)

    def test_health_reports_bot_identity(self):
        res = call("/health", method="GET")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["bot"], "test_bot")
        self.assertEqual(res.json()["status"], "ok")



class SecretComparisonTest(unittest.TestCase):
    def test_non_ascii_secret_is_refused_not_crashed(self):
        """compare_digest на строке с кириллицей бросает TypeError, и
        подделанный секрет отвечал бы 500 вместо 403."""
        import secrets

        with self.assertRaises(TypeError):
            secrets.compare_digest("кириллица", "latin")

        self.assertFalse(
            secrets.compare_digest(
                "кириллица".encode("utf-8", "replace"), "latin".encode()
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
