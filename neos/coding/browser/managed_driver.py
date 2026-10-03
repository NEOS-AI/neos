"""관리형 샌드박스 안의 Chromium 을 부리는 드라이버 -- 트랙 Q14c (설계 §8).

`BrowserDriver` 계약을 그대로 구현한다. 세션(`session.py`)은 호스트 드라이버와 이것을
구별하지 않는다 -- 가드(출구 판정 · 비밀 출처 묶임 · 비밀번호 가리기 · 실패·취소 때 닫기 ·
자식 거절 · background 천장)는 전부 세션·실행기·게이트에 있고 드라이버 밑에 있지 않다.

달라지는 것은 둘이다:

1. **Chromium 이 호스트가 아니라 샌드박스에서 돈다.** 렌더러 탈출은 백엔드 호스트가 아니라
   벤더 VM 에 닿는다(W1 의 신뢰 경계를 옮긴다). 태스크마다 채널 하나 = 컨텍스트 하나.
2. **guest 는 페이지와 같은 신뢰 등급이다.** guest 가 보낸 요청은 페이지가 낸 요청과 똑같이
   세션의 `serve`(= web_fetch 판정 + IP 고정 한 홉)를 지난다. guest 가 말하는 URL·출처·
   비밀번호 값은 가리기의 재료일 뿐 권한의 근거가 아니다.

비밀은 이 채널로 보내지 않는다(MB4): `confidential_channel` 이 거짓으로 **고정**되어 있어
세션이 `browser_fill_secret.v1` 을 금고를 열기 전에 `browser_secret_channel_unavailable` 로
거절한다. 여는 것은 설정이 아니라 증거를 단 코드 변경이다(Q6b §4 와 같은 규칙).
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any, Protocol

from neos.coding.browser.driver import (
    BrowserActionError,
    InterceptedRequest,
    RequestServer,
    ServedResponse,
)
from neos.coding.browser.wire import (
    PROTOCOL_VERSION,
    ByteChannel,
    FrameStream,
    WireInvalid,
    guest_bundle_digest,
    request_from_wire,
    response_to_wire,
)

#: 드라이버 호출의 timeout 위에 얹는 여유 -- 선 위 왕복과 guest 의 스케줄링.
_CALL_MARGIN_SEC = 5.0
#: timeout_ms 를 받지 않는 호출(open · title · password_values · close)의 상한.
_PLAIN_CALL_SEC = 30.0
_MAX_URL_CHARS = 16 * 1024


class BrowserChannelOpener(Protocol):
    """태스크 하나의 관리형 샌드박스에 브라우저 guest 채널을 연다.

    B2 의 실제 구현은 할당 평면이 그 태스크에 붙인 살아 있는 allocation 을 찾아(소유권 검증 뒤)
    벤더 SDK 의 `open_stdio(ref, BROWSER_GUEST_ARGV)` 를 부른다 -- 아직 저장소에 없다(§8 남은 것).
    없거나 실패하면 예외를 올리고, 세션은 그것을 `browser_unavailable` 로 읽는다.
    """

    async def open(self, task_id: str) -> ByteChannel: ...


#: 샌드박스 이미지 안에서 guest 를 띄우는 argv(`neos-sandboxd connect` 와 같은 자리).
BROWSER_GUEST_ARGV = ("python3", "-m", "neos.coding.browser.guest")


class _Connection:
    def __init__(self, stream: FrameStream, serve: RequestServer) -> None:
        self._stream = stream
        self._serve = serve
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._routes: set[asyncio.Task] = set()
        self._reader: asyncio.Task | None = None
        self._lost = False
        self.url = "about:blank"

    async def handshake(self, *, digest: str, timeout_sec: float) -> None:
        message = await asyncio.wait_for(self._stream.read(), timeout_sec)
        hello = message.get("hello")
        if (
            not isinstance(hello, dict)
            or hello.get("protocol") != PROTOCOL_VERSION
            or hello.get("bundle_digest") != digest
        ):
            raise WireInvalid("hello")
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            while True:
                message = await self._stream.read()
                if "reply" in message:
                    future = self._pending.get(message.get("reply"))  # type: ignore[arg-type]
                    if future is not None and not future.done():
                        future.set_result(message)
                elif "route" in message:
                    task = asyncio.create_task(self._route(message))
                    self._routes.add(task)
                    task.add_done_callback(self._routes.discard)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- 끊기거나 깨진 채널: 기다리던 호출은 모두 실패
            pass
        finally:
            self._lost = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(BrowserActionError("failed"))

    async def _route(self, message: dict) -> None:
        """guest 가 페이지 대신 낸 요청 하나 -- 세션의 판정을 그대로 지난다(W2)."""
        route_id = message.get("route")
        served: ServedResponse | None
        try:
            request: InterceptedRequest = request_from_wire(message.get("request"))
            served = await self._serve(request)
        except Exception:  # noqa: BLE001 -- 모양이 틀린 요청은 내보내지 않는다
            served = None
        answer: dict[str, Any] = {"route": route_id}
        if served is None:
            answer["abort"] = True
        else:
            try:
                answer["response"] = response_to_wire(served)
            except Exception:  # noqa: BLE001
                answer = {"route": route_id, "abort": True}
        try:
            await self._stream.write(answer)
        except Exception:  # noqa: BLE001 -- 채널이 끊겼다: guest 쪽이 abort 한다
            pass

    async def call(self, op: str, args: dict[str, Any] | None = None, *, timeout_sec: float) -> Any:
        if self._lost:
            raise BrowserActionError("failed")
        call_id = next(self._ids)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        try:
            await self._stream.write({"call": call_id, "op": op, "args": args or {}})
            reply = await asyncio.wait_for(future, timeout_sec)
        except TimeoutError:
            raise BrowserActionError("timeout") from None
        except BrowserActionError:
            raise
        except Exception:  # noqa: BLE001
            raise BrowserActionError("failed") from None
        finally:
            self._pending.pop(call_id, None)
        url = reply.get("url")
        if isinstance(url, str) and len(url) <= _MAX_URL_CHARS:
            self.url = url
        if reply.get("ok") is not True:
            raise BrowserActionError("timeout" if reply.get("error") == "timeout" else "failed")
        return reply.get("result")

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        for task in list(self._routes):
            task.cancel()
        try:
            await self._stream.close()
        except Exception:  # noqa: BLE001
            pass


def _expect(value: Any, kind: type | tuple[type, ...]) -> Any:
    if not isinstance(value, kind) or isinstance(value, bool):
        raise BrowserActionError("failed")
    return value


class _RemotePage:
    def __init__(self, connection: _Connection) -> None:
        self._c = connection

    @staticmethod
    def _within(timeout_ms: float) -> float:
        return timeout_ms / 1000 + _CALL_MARGIN_SEC

    def url(self) -> str:
        # 계약의 `page.url` 은 동기다. guest 는 답마다 지금 URL 을 싣고, 이것은 마지막 값이다.
        return self._c.url

    async def title(self) -> str:
        return _expect(await self._c.call("title", timeout_sec=_PLAIN_CALL_SEC), str)

    async def goto(self, url: str, *, timeout_ms: float) -> int | None:
        status = await self._c.call(
            "goto", {"url": url, "timeout_ms": timeout_ms}, timeout_sec=self._within(timeout_ms)
        )
        return None if status is None else _expect(status, int)

    async def snapshot(self, *, timeout_ms: float) -> str:
        return _expect(
            await self._c.call(
                "snapshot", {"timeout_ms": timeout_ms}, timeout_sec=self._within(timeout_ms)
            ),
            str,
        )

    async def password_values(self) -> tuple[str, ...]:
        values = _expect(await self._c.call("password_values", timeout_sec=_PLAIN_CALL_SEC), list)
        return tuple(_expect(value, str) for value in values)

    async def element_origin(self, ref: str, *, timeout_ms: float) -> str:
        return _expect(
            await self._c.call(
                "element_origin",
                {"ref": ref, "timeout_ms": timeout_ms},
                timeout_sec=self._within(timeout_ms),
            ),
            str,
        )

    async def click(self, ref: str, *, timeout_ms: float) -> None:
        await self._c.call(
            "click", {"ref": ref, "timeout_ms": timeout_ms}, timeout_sec=self._within(timeout_ms)
        )

    async def fill(self, ref: str, value: str, *, timeout_ms: float) -> None:
        await self._c.call(
            "fill",
            {"ref": ref, "value": value, "timeout_ms": timeout_ms},
            timeout_sec=self._within(timeout_ms),
        )

    async def press_enter(self, ref: str, *, timeout_ms: float) -> None:
        await self._c.call(
            "press_enter",
            {"ref": ref, "timeout_ms": timeout_ms},
            timeout_sec=self._within(timeout_ms),
        )


class _RemoteContext:
    def __init__(self, connection: _Connection, owner: ManagedBrowserDriver) -> None:
        self._c = connection
        self._owner = owner

    async def open_page(self) -> _RemotePage:
        return _RemotePage(self._c)

    async def close(self) -> None:
        self._owner._live.discard(self)
        try:
            await self._c.call("close", timeout_sec=_PLAIN_CALL_SEC)
        except BrowserActionError:
            pass
        finally:
            await self._c.close()


class ManagedBrowserDriver:
    """태스크마다 관리형 샌드박스의 guest 에 채널 하나를 열어 컨텍스트로 쓴다."""

    #: 트랙 Q6b C1 과 같은 이유로 **고정**한다 -- 채널은 벤더 exec 의 stdio 중계이고 그 기밀성을
    #: 보일 바인딩이 저장소에 없다. 세션이 이것을 보고 `browser_fill_secret.v1` 을 거절한다(MB4).
    confidential_channel = False

    def __init__(
        self,
        channels: BrowserChannelOpener,
        *,
        digest: str | None = None,
        handshake_timeout_sec: float = 30.0,
    ) -> None:
        self._channels = channels
        self._digest = digest or guest_bundle_digest()
        self._handshake_timeout_sec = handshake_timeout_sec
        self._live: set[_RemoteContext] = set()

    def __repr__(self) -> str:
        return f"ManagedBrowserDriver(open={len(self._live)})"

    async def new_context(self, serve: RequestServer, *, task_id: str = "") -> _RemoteContext:
        if not task_id:
            raise BrowserActionError("failed")  # 샌드박스는 태스크의 것이다 -- 주인 없는 컨텍스트는 없다
        channel = await self._channels.open(task_id)
        connection = _Connection(FrameStream(channel), serve)
        try:
            await connection.handshake(
                digest=self._digest, timeout_sec=self._handshake_timeout_sec
            )
            await connection.call("open", timeout_sec=_PLAIN_CALL_SEC)
        except BaseException:
            await connection.close()
            raise
        context = _RemoteContext(connection, self)
        self._live.add(context)
        return context

    async def aclose(self) -> None:
        for context in list(self._live):
            await context.close()
