"""Адрес базы 1С, который вписал владелец, — чужой сервер.

Владельцем на стенде может стать любой, а по адресу базы ходит сам сервер.
Раньше адрес сохранялся как есть, и через него можно было достучаться до
внутренних сервисов стенда — базы, бота, хранилища — и до служебных адресов
облака, а ошибки с внутренними адресами оседали в журнале обмена. Поэтому:

* только `https://` — по адресу уходит ключ базы, открытым текстом нельзя;
* только публичная сеть. Имя сервера разрешаем сами, проверяем каждый
  адрес и соединяемся с уже проверенным: иначе DNS мог бы ответить на
  проверку публичным адресом, а на соединение — внутренним;
* без переходов по редиректам — ими адрес увёл бы запрос во внутреннюю сеть.

Адрес тестового стенда (эмулятор 1С, база из ключа) задаём мы сами, поэтому
эти правила его не касаются.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import typing

import httpcore
import httpx

from .contract import OneCUnavailable

INTERNAL = "это адрес внутренней сети — укажите публичный адрес базы 1С"

# Зоны, которые наружу не разрешаются: сервер с таким именем живёт в чьей-то
# локальной сети, а не в интернете.
LOCAL_ZONES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")

# NAT64 (RFC 6052): за таким IPv6 прячется любой IPv4, в том числе внутренний.
NAT64 = ipaddress.ip_network("64:ff9b::/96")

# «127.1», «0x7f.1», «2130706433» — тот же 127.0.0.1, записанный иначе:
# системный резолвер такие имена понимает как адрес.
NUMERIC_LABEL = re.compile(r"0x[0-9a-f]*|[0-9]+")


class BadAddress(ValueError):
    """Адрес не годится для базы 1С. Текст — для владельца."""


class InternalAddress(OneCUnavailable):
    """Имя сервера разрешилось во внутреннюю сеть — соединения не будет."""


def is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Адрес из интернета, а не из внутренней, служебной или особой сети."""
    if isinstance(address, ipaddress.IPv6Address):
        # IPv4 внутри IPv6 проверяем как IPv4: ::ffff:127.0.0.1 — это localhost.
        embedded = address.ipv4_mapped or address.sixtofour
        if embedded is None and address in NAT64:
            embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if embedded is not None:
            return is_public(embedded)
    return address.is_global and not address.is_multicast


def check(url: str) -> str:
    """Проверяет адрес при сохранении и перед обменом. Возвращает его без
    хвостового «/»; пустой — пустым: своей базы у витрины нет."""
    text = (url or "").strip()
    if not text:
        return ""
    try:
        parsed = httpx.URL(text)
    except (httpx.InvalidURL, ValueError, TypeError) as exc:
        raise BadAddress("не похоже на адрес — нужен вид https://сервер/база") from exc
    if parsed.scheme != "https":
        raise BadAddress("адрес базы 1С должен начинаться с https://")
    if parsed.userinfo:
        raise BadAddress("логин и пароль в адрес не вписывайте — для них есть свои поля")
    if parsed.query or parsed.fragment:
        raise BadAddress("в адресе базы не должно быть «?» и «#»")
    host = (parsed.host or "").lower().rstrip(".")
    if not host:
        raise BadAddress("не похоже на адрес — нужен вид https://сервер/база")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public(literal):
            raise BadAddress(INTERNAL)
    elif (
        # Имя без точки — сервис внутренней сети вроде «db» или «bot».
        "." not in host
        or host.endswith(LOCAL_ZONES)
        or all(NUMERIC_LABEL.fullmatch(label) for label in host.split("."))
    ):
        raise BadAddress(INTERNAL)
    return text.rstrip("/")


class PublicOnly(httpcore.AsyncNetworkBackend):
    """Сетевой слой, который соединяется только с публичными адресами."""

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        loop = asyncio.get_running_loop()
        try:
            found = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise OneCUnavailable("сервер базы 1С не найден — проверьте адрес") from exc
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in found]
        # Хоть один внутренний адрес среди ответов — отказ целиком: иначе
        # выбор адреса решал бы, куда уйдёт запрос.
        if not addresses or not all(is_public(address) for address in addresses):
            raise InternalAddress("адрес базы 1С ведёт во внутреннюю сеть — укажите публичный адрес")
        return await self._inner.connect_tcp(
            str(addresses[0]), port,
            timeout=timeout, local_address=local_address, socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise InternalAddress("адрес базы 1С ведёт во внутреннюю сеть — укажите публичный адрес")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PublicTransport(httpx.AsyncHTTPTransport):
    """Транспорт httpx поверх `PublicOnly`.

    Свой сетевой слой httpx параметром не принимает, поэтому пул соединений
    собираем сами. Сертификат по-прежнему проверяется по имени из адреса:
    httpcore передаёт его в TLS отдельно от адреса, с которым соединился.
    Прокси из окружения при своём транспорте httpx не применяет.
    """

    def __init__(self) -> None:
        ssl_context = httpx.create_ssl_context()
        super().__init__(verify=ssl_context)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context, network_backend=PublicOnly()
        )
