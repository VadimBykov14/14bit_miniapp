"""Хранилище фотографий приёмки.

Фото — доказательство расхождения в разговоре с поставщиком, поэтому оно
должно пережить перезапуск контейнера: файлы уходят в объектное хранилище,
а не в файловую систему приложения.

Клиент никогда не ходит в S3 напрямую: бакет закрыт, отдаёт API по ссылке,
проверив, что этот пользователь имеет отношение к заявке.
"""

from __future__ import annotations

import io
import logging
import os
import time
import uuid

from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

ENDPOINT = os.environ.get("S3_ENDPOINT", "s3:9000")
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "max26")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "max26secret")
BUCKET = os.environ.get("S3_BUCKET", "max26")

MAX_BYTES = 8 * 1024 * 1024
ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/heic"}

log = logging.getLogger("api")

_client: Minio | None = None


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=False)
    return _client


def ensure_bucket(attempts: int = 10, delay: float = 1.5) -> bool:
    """Хранилище может подняться позже API, поэтому пробуем несколько раз.

    Неудача не валит сервис: приёмка без фото работает, а снимок вернётся,
    когда хранилище появится.
    """
    for attempt in range(1, attempts + 1):
        try:
            if not client().bucket_exists(BUCKET):
                client().make_bucket(BUCKET)
            return True
        except Exception as exc:  # noqa: BLE001 — сеть, DNS, ещё не поднялся
            if attempt == attempts:
                log.warning("не смог подготовить бакет за %s попыток: %s", attempts, exc)
                return False
            time.sleep(delay)
    return False


def put(data: bytes, content_type: str, prefix: str = "receipts") -> str:
    """Кладёт файл и возвращает ключ. Имя генерируем сами: имя из телефона
    может содержать что угодно, включая пути."""
    key = f"{prefix}/{uuid.uuid4().hex}"
    client().put_object(BUCKET, key, io.BytesIO(data), length=len(data), content_type=content_type)
    return key


def copy(key: str, prefix: str) -> str | None:
    """Копия файла под новым ключом — на стороне хранилища, без скачивания.
    Нет исходного или хранилище недоступно — None: картинка не обязательна."""
    target = f"{prefix}/{uuid.uuid4().hex}"
    try:
        client().copy_object(BUCKET, target, CopySource(BUCKET, key))
    except Exception as exc:  # noqa: BLE001 — сеть, хранилище, исходного нет
        log.warning("не смог скопировать %s: %s", key, exc)
        return None
    return target


def get(key: str) -> tuple[bytes, str]:
    response = client().get_object(BUCKET, key)
    try:
        return response.read(), response.headers.get("Content-Type", "application/octet-stream")
    finally:
        response.close()
        response.release_conn()


def remove(key: str) -> None:
    """Стирает объект. Неудача не страшна: ссылки на него в базе уже нет,
    и найти его по заявке больше нельзя."""
    try:
        client().remove_object(BUCKET, key)
    except Exception as exc:  # noqa: BLE001 — сеть, хранилище недоступно
        log.warning("не смог удалить %s: %s", key, exc)
