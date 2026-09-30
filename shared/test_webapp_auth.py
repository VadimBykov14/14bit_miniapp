"""Тесты проверки подписи данных запуска.

Здесь решается, кто именно открыл витрину, поэтому проверяем не только
счастливый путь, но и каждый способ подделки, который приходит в голову.

Запуск:  python3 shared/test_webapp_auth.py
"""

import hashlib
import hmac
import json
import pathlib
import sys
import time
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from webapp_auth import InvalidInitData, verify  # noqa: E402

TOKEN = "test-bot-token"
USER = {"id": 100500, "first_name": "Анна", "last_name": "Петрова", "username": "anna"}
CHAT = {"id": 100500, "type": "DIALOG"}


def sign(params: dict, token: str = TOKEN) -> str:
    """Собирает корректно подписанную строку initData."""
    payload = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": digest})


def fresh_params(**overrides) -> dict:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "q1",
        "user": json.dumps(USER, ensure_ascii=False),
        "chat": json.dumps(CHAT, ensure_ascii=False),
    }
    params.update(overrides)
    return params


class VerifyTest(unittest.TestCase):
    def test_accepts_valid_signature(self):
        ctx = verify(sign(fresh_params()), TOKEN)
        self.assertEqual(ctx.user_id, 100500)
        self.assertEqual(ctx.first_name, "Анна")
        self.assertEqual(ctx.last_name, "Петрова")
        self.assertEqual(ctx.chat_id, 100500)

    def test_reads_deeplink_payload(self):
        ctx = verify(sign(fresh_params(start_param="inv_ab12cd34")), TOKEN)
        self.assertEqual(ctx.start_param, "inv_ab12cd34")

    def test_rejects_tampered_user(self):
        """Главная атака: подменить себя на другого клиента и увидеть чужой прайс."""
        signed = sign(fresh_params())
        forged = signed.replace(
            urlencode({"user": json.dumps(USER, ensure_ascii=False)}).split("=", 1)[1],
            urlencode({"user": json.dumps({**USER, "id": 1}, ensure_ascii=False)}).split("=", 1)[1],
        )
        with self.assertRaises(InvalidInitData):
            verify(forged, TOKEN)

    def test_rejects_wrong_token(self):
        with self.assertRaises(InvalidInitData):
            verify(sign(fresh_params()), "другой-токен")

    def test_rejects_missing_hash(self):
        with self.assertRaises(InvalidInitData):
            verify(urlencode(fresh_params()), TOKEN)

    def test_rejects_empty(self):
        with self.assertRaises(InvalidInitData):
            verify("", TOKEN)

    def test_rejects_duplicate_parameter(self):
        """Дубль ключа позволил бы приложить второй user или второй hash."""
        signed = sign(fresh_params())
        with self.assertRaises(InvalidInitData):
            verify(signed + "&user=" + urlencode({"u": json.dumps({"id": 1})})[2:], TOKEN)

    def test_rejects_stale_data(self):
        """Подпись верна вечно — без срока годности перехваченную строку
        можно переиспользовать бесконечно."""
        old = fresh_params(auth_date=str(int(time.time()) - 48 * 3600))
        with self.assertRaises(InvalidInitData):
            verify(sign(old), TOKEN)

    def test_accepts_stale_data_when_age_check_disabled(self):
        old = fresh_params(auth_date=str(int(time.time()) - 48 * 3600))
        ctx = verify(sign(old), TOKEN, max_age_seconds=0)
        self.assertEqual(ctx.user_id, 100500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
