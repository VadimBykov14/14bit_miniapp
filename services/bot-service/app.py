"""bot-service — вебхук MAX и сообщения пользователю.

Бот не ведёт переписку, он ведёт в приложение: здоровается, присылает
приглашение по ссылке с кодом и уведомления с кнопкой «открыть там, где
дело». Под уведомлением — ещё «Не присылать такие»: нажатие отключает этот
вид уведомлений в MAX (см. services/api/app/mutes.py). На любой другой
текст бот коротко отвечает и даёт кнопку в приложение.

Живой бот — условие хакатона: если он не запускается или сценарий нельзя
пройти в MAX, работа получает ноль без дальнейшей оценки.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from max_client import DEFAULT_BASE, MaxClient

TOKEN = os.environ["MAX_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
API_BASE = os.environ.get("MAX_API_BASE", DEFAULT_BASE)
API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://api:8080")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

GREETING = (
    "Привет, {name}! Я бот витрины поставщика.\n"
    "Сюда приходят заявки, отгрузки и просьбы о подключении — под каждым "
    "сообщением кнопка, которая открывает нужный экран. Заявки собираются "
    "в приложении."
)

# На любой текст: бот не собеседник, всё делается в приложении. Раньше тут
# было эхо на «ты» — «Слышу тебя… Ты написал: …».
REPLY = (
    "Переписку здесь не веду — только присылаю уведомления. "
    "Заявки, отгрузки и контакты — в приложении, кнопка ниже."
)

# Кнопка под приветствием и ответами: бот не ведёт диалог, он ведёт в приложение.
HOME_BUTTON = {"text": "Открыть приложение", "payload": ""}

# «Не присылать такие» под уведомлением: вид и сторона — «mute:cutoff:shop».
# Что это значит и как подписать, знает API; бот только передаёт.
MUTE = re.compile(r"^mute:[a-z_]{1,30}:(staff|shop)?$")
MUTE_TEXT = "Не присылать такие"

# Код приглашения в ссылке `max.ru/<бот>?start=<код>`: клиент, менеджер
# поставщика или работник магазина.
INVITE = re.compile(r"^(inv|emp|wrk)_[\w-]{4,20}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.max = MaxClient(TOKEN, base_url=API_BASE)
    app.state.bot = {}
    try:
        app.state.bot = await app.state.max.get_me()
        log.info("бот %s (id %s) на связи", app.state.bot.get("username"), app.state.bot.get("user_id"))
    except httpx.HTTPError as exc:
        # Не валимся: пусть контейнер живёт и отдаёт /health с явной ошибкой,
        # иначе отладка на сервере превращается в гадание по логам рестартов.
        log.error("не смог представиться MAX: %s", exc)

    if not WEBHOOK_SECRET:
        log.warning("WEBHOOK_SECRET пуст — вебхук принимает запросы от кого угодно")

    try:
        yield
    finally:
        await app.state.max.aclose()


app = FastAPI(title="max26 bot-service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    bot = app.state.bot or {}
    return {
        "status": "ok" if bot else "degraded",
        "bot": bot.get("username"),
        "bot_id": bot.get("user_id"),
    }


@app.post("/webhook")
async def webhook(
    request: Request,
    x_max_bot_api_secret: str | None = Header(default=None),
) -> dict:
    # Байты, а не строки: compare_digest на не-ASCII заголовке бросает
    # TypeError, и подделанный секрет получил бы 500 вместо 403.
    if WEBHOOK_SECRET and not secrets.compare_digest(
        (x_max_bot_api_secret or "").encode("utf-8", "replace"), WEBHOOK_SECRET.encode()
    ):
        log.warning("вебхук с неверным секретом от %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="bad secret")

    update = await request.json()
    update_type = update.get("update_type")
    log.info("апдейт %s", update_type)

    # Подтверждаем приём любого события: MAX не должен ретраить из-за того,
    # что мы пока не умеем обрабатывать какой-то тип.
    if update_type == "message_callback":
        await _callback(update)
        return {"ok": True}
    if update_type not in ("message_created", "bot_started"):
        return {"ok": True}

    if update_type == "bot_started":
        chat_id = update.get("chat_id")
        user = update.get("user") or {}
        user_id = user.get("user_id") or user.get("id")
        await _link_chat(user_id, chat_id, user)
        if chat_id is not None:
            name = user.get("first_name") or "друг"
            code = str(update.get("payload") or "").strip()
            if INVITE.match(code):
                await _invite(code, user_id, chat_id, name)
            else:
                await _reply(
                    GREETING.format(name=name), chat_id=chat_id, keyboard=_app_button(HOME_BUTTON)
                )
        return {"ok": True}

    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("is_bot"):
        return {"ok": True}

    chat_id = (message.get("recipient") or {}).get("chat_id")
    if chat_id is None:
        return {"ok": True}

    await _link_chat(sender.get("user_id"), chat_id, sender)

    text = ((message.get("body") or {}).get("text") or "").strip()
    name = sender.get("first_name") or "друг"

    # «/start inv_…» — так приходит код, если диалог с ботом уже был.
    command, _, argument = text.partition(" ")
    if command == "/start" and INVITE.match(argument.strip()):
        await _invite(argument.strip(), sender.get("user_id"), chat_id, name)
    elif text in ("", "/start"):
        await _reply(GREETING.format(name=name), chat_id=chat_id, keyboard=_app_button(HOME_BUTTON))
    else:
        await _reply(REPLY, chat_id=chat_id, keyboard=_app_button(HOME_BUTTON))

    return {"ok": True}


@app.post("/internal/notify")
async def notify(payload: dict) -> dict:
    """Единственная точка исходящих уведомлений.

    Токен и ограничитель 30 rps живут здесь, поэтому api-сервис шлёт
    сообщения через бота, а не заводит второго клиента мимо лимита.
    Наружу этот путь не проксируется.

    `button` — кнопка под сообщением, которая открывает мини-приложение
    сразу на нужном экране: {"text": "Открыть заявку", "payload": "order_57"}.
    `mute` — что вернёт кнопка «Не присылать такие»; нет — кнопки нет.
    """
    chat_id = payload.get("chat_id")
    user_id = payload.get("user_id")
    text = str(payload.get("text") or "").strip()
    if not text or (not chat_id and not user_id):
        raise HTTPException(status_code=400, detail="нужен текст и адресат")

    sent = await _reply(
        text,
        chat_id=int(chat_id) if chat_id else None,
        user_id=int(user_id) if user_id else None,
        keyboard=_app_button(payload.get("button"), mute=payload.get("mute")),
    )
    # «Дошло ли» — честно: раньше ответ был «ok» и тогда, когда MAX отказал
    # (человек ни разу не открывал бота), и в ленте стояло «доставлено».
    return {"ok": True, "sent": sent}


# Ярлык экрана уходит в start_param мини-приложения. Схема MAX пропускает
# только буквы, цифры, подчёркивание и дефис — остальное не доедет.
_PAYLOAD = re.compile(r"^[\w-]{0,512}$")


def _open_app(button: dict | None) -> dict | None:
    """Кнопка «открыть приложение здесь». Без имени бота её не собрать."""
    if not isinstance(button, dict):
        return None
    bot = app.state.bot or {}
    name, bot_id = bot.get("username"), bot.get("user_id")
    text = str(button.get("text") or "").strip()[:128]
    payload = str(button.get("payload") or "")
    if not name or not text or not _PAYLOAD.match(payload):
        return None
    action: dict = {"type": "open_app", "text": text, "web_app": name}
    if bot_id:
        action["contact_id"] = bot_id
    if payload:
        action["payload"] = payload
    return action


def _app_button(button: dict | None, mute: str | None = None) -> list[dict] | None:
    """Клавиатура под сообщением: «открыть приложение здесь» и под ней —
    «Не присылать такие», если это уведомление.

    Кнопку, которую не собрать, пропускаем: сообщение уходит без неё —
    уведомление важнее кнопки.
    """
    rows = []
    action = _open_app(button)
    if action:
        rows.append([action])
    if isinstance(mute, str) and MUTE.match(mute):
        rows.append([{"type": "callback", "text": MUTE_TEXT, "payload": mute}])
    if not rows:
        return None
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


async def _callback(update: dict) -> None:
    """Нажата кнопка под сообщением. Такая у нас одна — «Не присылать такие».

    Ответить на нажатие нужно в любом случае: иначе MAX так и крутит
    ожидание на кнопке, и человек не понимает, сработало ли.
    """
    callback = update.get("callback") or {}
    callback_id = str(callback.get("callback_id") or "")
    payload = str(callback.get("payload") or "")
    user_id = (callback.get("user") or {}).get("user_id")
    if not callback_id:
        return
    answer = "Эта кнопка больше не работает — откройте приложение."
    if MUTE.match(payload) and user_id:
        answer = await _mute(int(user_id), payload)
    try:
        await app.state.max.answer(callback_id, notification=answer)
    except httpx.HTTPError as exc:
        log.warning("не ответил на нажатие %s: %s", payload, exc)


async def _mute(user_id: int, payload: str) -> str:
    """Отключает вид уведомлений через API и говорит, что именно отключено."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{API_INTERNAL_URL}/internal/notifications/mute",
                json={"user_id": user_id, "payload": payload},
            )
            response.raise_for_status()
            label = str((response.json() or {}).get("label") or "такие уведомления")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("не отключил уведомления %s для %s: %s", payload, user_id, exc)
        return "Не получилось отключить — попробуйте ещё раз чуть позже."
    return (
        f"Больше не пришлю: {label}. В приложении они останутся в ленте, "
        "а вернуть их можно в «Аккаунте»."
    )


@app.post("/internal/contact")
async def send_contact(payload: dict) -> dict:
    """Карточка контакта: нажатие открывает профиль человека в MAX, а там —
    «Написать». Личную ссылку на чат по id не построить, а карточку бот
    прислать может.

    Не вышло с карточкой — шлём текстом имя и телефон: человеку нужен
    способ связаться, а не красивое вложение.
    """
    chat_id = payload.get("chat_id")
    user_id = payload.get("user_id")
    contact_id = payload.get("contact_id")
    name = str(payload.get("name") or "").strip()[:120] or "Контакт"
    text = str(payload.get("text") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if not contact_id or (not chat_id and not user_id):
        raise HTTPException(status_code=400, detail="нужен контакт и адресат")

    card: dict = {"name": name, "contact_id": int(contact_id)}
    if phone:
        card["vcf_phone"] = phone
    sent = await _reply(
        text or name,
        chat_id=int(chat_id) if chat_id else None,
        user_id=int(user_id) if user_id else None,
        attachments=[{"type": "contact", "payload": card}],
    )
    if not sent:
        fallback = f"{text}\n{name}" + (f", тел. {phone}" if phone else "")
        await _reply(
            fallback.strip(),
            chat_id=int(chat_id) if chat_id else None,
            user_id=int(user_id) if user_id else None,
        )
    return {"ok": True, "sent": sent}


async def _invite(code: str, user_id: int | None, chat_id: int, name: str) -> None:
    """Пришли по ссылке-приглашению: присылаем само приглашение с кнопкой.

    Текст знает API — кто зовёт и куда. Кнопка открывает приложение с тем
    же кодом, и подключение происходит только по её нажатию. API не ответил
    — всё равно даём кнопку: код внутри, приложение примет его само.
    """
    text = "Вас пригласили в приложение витрины поставщика."
    button = {"text": "Принять приглашение", "payload": code}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{API_INTERNAL_URL}/internal/invites/card",
                json={"code": code, "user_id": int(user_id) if user_id else None},
            )
            response.raise_for_status()
            card = response.json() or {}
            text = str(card.get("text") or text)
            button = card.get("button") or button
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("не получил приглашение %s: %s", code, exc)
    await _reply(f"Привет, {name}! {text}", chat_id=chat_id, keyboard=_app_button(button))


async def _link_chat(user_id: int | None, chat_id: int | None, user: dict | None = None) -> None:
    """Сообщает API, в каком диалоге отвечать этому пользователю и кто это.

    Имя передаём здесь же: из мини-приложения оно приходит только в подписи
    запуска, а поставщику нужно видеть, кого он приглашает, до того как
    человек что-то откроет.

    Ошибку глотаем: связка чата — не причина ломать обработку апдейта.
    """
    if not user_id or not chat_id:
        return
    profile = user or {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{API_INTERNAL_URL}/internal/chat",
                json={
                    "user_id": int(user_id),
                    "chat_id": int(chat_id),
                    "first_name": profile.get("first_name") or "",
                    "last_name": profile.get("last_name") or "",
                    "username": profile.get("username") or "",
                },
            )
    except httpx.HTTPError as exc:
        log.warning("не смог связать чат %s с пользователем %s: %s", chat_id, user_id, exc)


async def _reply(
    text: str,
    chat_id: int | None = None,
    user_id: int | None = None,
    keyboard: list[dict] | None = None,
    attachments: list[dict] | None = None,
) -> bool:
    """Пробуем оба адреса по очереди.

    `?user_id=` отвечает 404, если такого пользователя в MAX нет; `?chat_id=`
    работает только для заведённого диалога. Один из двух обычно доезжает,
    и выбирать заранее не из чего.

    Если MAX отверг сообщение с кнопкой (400), шлём без неё: кнопка —
    удобство, а уведомление обязано дойти.
    """
    # Совпадение чисел ничего не значит: user_id и chat_id — разные
    # пространства идентификаторов, и один и тот же номер может быть
    # рабочим чатом и несуществующим пользователем одновременно.
    attempts: list[tuple[str, dict]] = []
    if user_id:
        attempts.append((f"user {user_id}", {"user_id": user_id}))
    if chat_id:
        attempts.append((f"chat {chat_id}", {"chat_id": chat_id}))

    extras = [*(attachments or []), *(keyboard or [])]
    last: Exception | None = None
    for label, target in attempts:
        try:
            await app.state.max.send_message(text, attachments=extras or None, **target)
            return True
        except httpx.HTTPStatusError as exc:
            last = exc
            if keyboard and not attachments and exc.response.status_code == 400:
                log.warning("MAX не принял кнопку (%s) — шлю без неё", exc.response.text[:200])
                try:
                    await app.state.max.send_message(text, **target)
                    return True
                except httpx.HTTPError as again:
                    last = again
            if attachments and exc.response.status_code == 400:
                log.warning("MAX не принял вложение: %s", exc.response.text[:200])
                break
            log.info("не прошло через %s, пробую дальше", label)
        except httpx.HTTPError as exc:
            last = exc
            log.info("не прошло через %s, пробую дальше", label)

    # Ошибку отправки глотаем: если вернуть 5xx, MAX будет ретраить апдейт,
    # и пользователь получит дубль, когда связь восстановится.
    if last is not None:
        log.error("не смог написать (%s): %s", ", ".join(l for l, _ in attempts), last)
    return False
