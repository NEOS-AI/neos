"""브리지 소켓을 쥔 프로세스와 코딩 루프를 도는 프로세스 사이 -- 트랙 Q16a (B6).

브리지 소켓은 API 프로세스(uvicorn 워커 중 하나)에 붙고, 코딩 루프는 Celery 워커에서
돈다. 같은 프로세스라는 가정은 배포 어디에서도 참이 아니다 -- 그래서 중계가 필요하다.

- **연결 표시(presence)**: `presence:{user_id}` 에 그 사용자의 연결 하나(`BridgeView`)를
  TTL 과 함께 둔다. 소켓이 TTL 의 1/3 마다 **자기 값일 때만** 갱신한다(compare-and-refresh).
  새 연결이 값을 덮으면 옛 연결은 다음 갱신에서 자기가 밀려났음을 안다(B5 -- 동시에 하나).
- **호출**: 루프 쪽이 `conn:{conn_id}` 채널에 PUBLISH 하고 `reply:{request_id}` 를 BLPOP 한다.
  받는 구독자가 0 이면 즉시 `device_bridge_unavailable`. 요청 id 는 128비트 난수다.
- **소유자 격리**: presence 키가 소유자 `user_id` 이고, 소켓 쪽은 요청의 `user_id` 가 자기
  연결의 것과 다르면 거절하며, 루프 쪽은 답의 `user_id`·`id` 를 다시 맞춘다.

`InProcessDeviceBridgeRelay` 는 같은 계약의 테스트용 구현이다. 배포에는 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

Deliver = Callable[[Mapping[str, Any]], Awaitable[None]]


class DeviceRelayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BridgeView:
    """소유자의 **지금** 연결 하나. 체크포인트에 싣지 않는다 -- 단계마다 새로 읽는다."""

    user_id: str
    bridge_id: str
    conn_id: str
    tools: frozenset[str]
    allow_unattended: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_id": self.user_id,
                "bridge_id": self.bridge_id,
                "conn_id": self.conn_id,
                "tools": sorted(self.tools),
                "allow_unattended": self.allow_unattended,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: object, *, user_id: str) -> BridgeView | None:
        """모양이 어긋나거나 **다른 사용자의** 값이면 `None` 이다."""
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)  # type: ignore[arg-type]
        except (UnicodeDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("user_id") != user_id:
            return None
        bridge_id, conn_id, tools = data.get("bridge_id"), data.get("conn_id"), data.get("tools")
        if not (isinstance(bridge_id, str) and bridge_id and isinstance(conn_id, str) and conn_id):
            return None
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            return None
        return cls(
            user_id=user_id,
            bridge_id=bridge_id,
            conn_id=conn_id,
            tools=frozenset(tools),
            allow_unattended=data.get("allow_unattended") is True,
        )


class RelayAttachment(Protocol):
    closed: asyncio.Event
    reason: str

    async def refresh(self) -> bool: ...

    async def detach(self) -> None: ...


class DeviceBridgeRelay(Protocol):
    async def view(self, user_id: str) -> BridgeView | None: ...

    async def request(
        self, view: BridgeView, message: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]: ...

    async def attach(self, view: BridgeView, deliver: Deliver) -> RelayAttachment: ...

    async def respond(self, request_id: str, reply: Mapping[str, Any]) -> None: ...

    async def kick(self, user_id: str, bridge_id: str) -> None: ...


#: 연결이 닫힌 이유. 소켓 세션이 닫는 코드를 고른다.
DISPLACED = "displaced"
LOST = "presence_lost"
KICKED = "kicked"


# -- in-process (테스트) ----------------------------------------------------------------


class _InProcessAttachment:
    def __init__(self, relay: InProcessDeviceBridgeRelay, view: BridgeView, deliver: Deliver):
        self._relay = relay
        self.view = view
        self.deliver = deliver
        self.closed = asyncio.Event()
        self.reason = ""

    def _close(self, reason: str) -> None:
        if not self.closed.is_set():
            self.reason = reason
            self.closed.set()

    async def refresh(self) -> bool:
        current = self._relay._live.get(self.view.user_id)
        if current is self and not self.closed.is_set():
            return True
        self._close(LOST if current is None else DISPLACED)
        return False

    async def detach(self) -> None:
        if self._relay._live.get(self.view.user_id) is self:
            del self._relay._live[self.view.user_id]
        self._close(self.reason or LOST)


class InProcessDeviceBridgeRelay:
    """`RedisDeviceBridgeRelay` 와 같은 계약. 테스트에서만 쓴다."""

    def __init__(self) -> None:
        self._live: dict[str, _InProcessAttachment] = {}
        self._pending: dict[str, asyncio.Future] = {}

    async def view(self, user_id: str) -> BridgeView | None:
        live = self._live.get(user_id)
        if live is None or live.closed.is_set():
            return None
        return live.view

    async def attach(self, view: BridgeView, deliver: Deliver) -> _InProcessAttachment:
        old = self._live.get(view.user_id)
        if old is not None:
            old._close(DISPLACED)
        attachment = _InProcessAttachment(self, view, deliver)
        self._live[view.user_id] = attachment
        return attachment

    async def request(self, view, message, *, timeout):
        live = self._live.get(view.user_id)
        if live is None or live.closed.is_set() or live.view.conn_id != view.conn_id:
            raise DeviceRelayError("device_bridge_unavailable")
        request_id = str(message["id"])
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await live.deliver(dict(message))
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as error:
            raise DeviceRelayError("device_bridge_timeout") from error
        finally:
            self._pending.pop(request_id, None)

    async def respond(self, request_id, reply):
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(dict(reply))

    async def kick(self, user_id, bridge_id):
        live = self._live.get(user_id)
        if live is not None and live.view.bridge_id == bridge_id:
            del self._live[user_id]
            live._close(KICKED)


# -- Redis (배포) -----------------------------------------------------------------------

#: 1 = 내 값이라 갱신했다, 0 = 키가 없다, -1 = 다른 연결의 값이다.
_REFRESH = """
local current = redis.call('GET', KEYS[1])
if not current then return 0 end
if current == ARGV[1] then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  return 1
end
return -1
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
_REPLY_TTL_SECONDS = 60


def _decode(raw: object) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)  # type: ignore[arg-type]


class _RedisAttachment:
    def __init__(self, relay: RedisDeviceBridgeRelay, client: Any, view: BridgeView, deliver: Deliver):
        self._relay = relay
        self._redis = client
        self.view = view
        self._value = view.to_json()
        self._deliver = deliver
        self._pubsub: Any = None
        self._listener: asyncio.Task | None = None
        self.closed = asyncio.Event()
        self.reason = ""

    def _close(self, reason: str) -> None:
        if not self.closed.is_set():
            self.reason = reason
            self.closed.set()

    async def start(self) -> None:
        relay = self._relay
        await self._redis.set(relay._presence_key(self.view.user_id), self._value, px=relay._ttl_ms)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(relay._conn_channel(self.view.conn_id))
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            while not self.closed.is_set():
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None or message.get("type") != "message":
                    continue
                try:
                    data = _decode(message.get("data"))
                except (UnicodeDecodeError, TypeError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "kick":
                    self._close(KICKED)
                    return
                if data.get("type") == "call":
                    try:
                        await self._deliver(data)
                    except Exception:  # noqa: BLE001 -- 한 호출의 실패가 구독을 끊지 않는다
                        logger.warning("device bridge delivery failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- 구독이 죽으면 연결도 닫는다(닫힌 쪽으로)
            logger.warning("device bridge relay listener failed", exc_info=True)
            self._close(LOST)

    async def refresh(self) -> bool:
        if self.closed.is_set():
            return False
        relay = self._relay
        result = await self._redis.eval(
            _REFRESH, 1, relay._presence_key(self.view.user_id), self._value, relay._ttl_ms
        )
        if int(result) == 1:
            return True
        self._close(LOST if int(result) == 0 else DISPLACED)
        return False

    async def detach(self) -> None:
        self._close(self.reason or LOST)
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
        relay = self._relay
        with contextlib.suppress(Exception):
            await self._redis.eval(_RELEASE, 1, relay._presence_key(self.view.user_id), self._value)
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.unsubscribe(relay._conn_channel(self.view.conn_id))
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()


class RedisDeviceBridgeRelay:
    """`client` 는 소켓 쪽(API 프로세스)의 오래 사는 클라이언트, `client_factory` 는 루프 쪽
    (Celery 워커 -- 태스크마다 이벤트 루프가 새로 선다)이 연산마다 새로 여는 클라이언트다."""

    def __init__(
        self,
        *,
        client: Any = None,
        client_factory: Callable[[], Any] | None = None,
        ttl_seconds: int = 30,
        prefix: str = "neos:device-bridge",
    ) -> None:
        if client is None and client_factory is None:
            raise ValueError("a Redis client or a client factory is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._shared = client
        self._factory = client_factory
        self._ttl_ms = int(ttl_seconds * 1000)
        self._prefix = prefix.rstrip(":")

    def _presence_key(self, user_id: str) -> str:
        return f"{self._prefix}:presence:{user_id}"

    def _conn_channel(self, conn_id: str) -> str:
        return f"{self._prefix}:conn:{conn_id}"

    def _reply_key(self, request_id: str) -> str:
        return f"{self._prefix}:reply:{request_id}"

    @asynccontextmanager
    async def _client(self):
        if self._shared is not None:
            yield self._shared
            return
        client = self._factory()  # type: ignore[misc]
        try:
            yield client
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    async def view(self, user_id: str) -> BridgeView | None:
        async with self._client() as client:
            raw = await client.get(self._presence_key(user_id))
        return BridgeView.from_json(raw, user_id=user_id)

    async def request(self, view, message, *, timeout):
        request_id = str(message["id"])
        payload = json.dumps({**dict(message), "type": "call"}, separators=(",", ":"))
        async with self._client() as client:
            receivers = await client.publish(self._conn_channel(view.conn_id), payload)
            if not receivers:
                raise DeviceRelayError("device_bridge_unavailable")
            popped = await client.blpop([self._reply_key(request_id)], timeout=timeout)
        if popped is None:
            raise DeviceRelayError("device_bridge_timeout")
        try:
            reply = _decode(popped[1])
        except (UnicodeDecodeError, TypeError, ValueError, IndexError) as error:
            raise DeviceRelayError("device_result_invalid") from error
        if not isinstance(reply, dict):
            raise DeviceRelayError("device_result_invalid")
        return reply

    async def respond(self, request_id, reply):
        key = self._reply_key(request_id)
        async with self._client() as client:
            await client.rpush(key, json.dumps(dict(reply), separators=(",", ":")))
            await client.expire(key, _REPLY_TTL_SECONDS)

    async def attach(self, view, deliver):
        if self._shared is None:
            raise RuntimeError("attach needs a long-lived Redis client")
        attachment = _RedisAttachment(self, self._shared, view, deliver)
        await attachment.start()
        return attachment

    async def kick(self, user_id, bridge_id):
        key = self._presence_key(user_id)
        async with self._client() as client:
            raw = await client.get(key)
            current = BridgeView.from_json(raw, user_id=user_id)
            if current is None or current.bridge_id != bridge_id:
                return
            await client.eval(_RELEASE, 1, key, raw)
            await client.publish(
                self._conn_channel(current.conn_id), json.dumps({"type": "kick"})
            )


__all__ = [
    "BridgeView",
    "DISPLACED",
    "DeviceBridgeRelay",
    "DeviceRelayError",
    "InProcessDeviceBridgeRelay",
    "KICKED",
    "LOST",
    "RedisDeviceBridgeRelay",
    "RelayAttachment",
]
