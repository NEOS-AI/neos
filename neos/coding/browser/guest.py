"""샌드박스 안에서 도는 브라우저 guest -- 트랙 Q14c (docs/Q14_AGENT_BROWSER_DESIGN_261001.md §8).

`python -m neos.coding.browser.guest` 가 stdin/stdout 의 프레임(`wire.py`)으로 호스트와 말한다.
guest 는 **판정하지 않는다**: Chromium 은 여기서도 네트워크 없이 뜨고(`playwright_driver` 그대로),
페이지가 내는 모든 요청을 route 프레임으로 호스트에 넘겨 답을 기다린다. 호스트가 답하지
않거나 채널이 끊기면 그 요청은 `route.abort()` 다(fail closed).

guest 는 호스트의 실행기·세션·금고를 모른다. 받는 것은 드라이버 계약(`driver.py`)의
메서드 호출뿐이고, 돌려주는 것은 그 결과와 지금 페이지의 URL, 실패는 코드(`timeout`·`failed`)뿐이다.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import sys
from typing import Any

from neos.coding.browser.driver import (
    BrowserActionError,
    BrowserContext,
    BrowserDriver,
    BrowserPage,
    InterceptedRequest,
    ServedResponse,
)
from neos.coding.browser.wire import (
    PROTOCOL_VERSION,
    ByteChannel,
    FrameError,
    FrameStream,
    WireInvalid,
    guest_bundle_digest,
    request_to_wire,
    response_from_wire,
)

#: 호스트가 route 에 답하는 시간의 상한. 호스트의 한 홉 timeout 보다 넉넉하다 -- 넘으면 abort.
DEFAULT_ROUTE_TIMEOUT_SEC = 120.0


def _ms(args: dict[str, Any]) -> float:
    value = args.get("timeout_ms")
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 < value <= 600_000:
        raise WireInvalid("timeout_ms")
    return float(value)


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise WireInvalid(key)
    return value


class BrowserGuest:
    """채널 하나 = 컨텍스트 하나 = 페이지 하나. `close` 를 받거나 채널이 끊기면 끝난다."""

    def __init__(
        self,
        driver: BrowserDriver,
        channel: ByteChannel,
        *,
        digest: str | None = None,
        route_timeout_sec: float = DEFAULT_ROUTE_TIMEOUT_SEC,
    ) -> None:
        self._driver = driver
        self._stream = FrameStream(channel)
        self._digest = digest or guest_bundle_digest()
        self._route_timeout_sec = route_timeout_sec
        self._route_ids = itertools.count(1)
        self._routes: dict[int, asyncio.Future] = {}
        self._context: BrowserContext | None = None
        self._page: BrowserPage | None = None
        self._calls: set[asyncio.Task] = set()
        self._done = asyncio.Event()

    # -- 호스트에게 묻는다 ------------------------------------------------------------

    async def _serve(self, request: InterceptedRequest) -> ServedResponse | None:
        if self._done.is_set():
            return None
        route_id = next(self._route_ids)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._routes[route_id] = future
        try:
            await self._stream.write({"route": route_id, "request": request_to_wire(request)})
            answer = await asyncio.wait_for(future, self._route_timeout_sec)
        except Exception:  # noqa: BLE001 -- 답을 못 받은 요청은 내보내지 않는다
            return None
        finally:
            self._routes.pop(route_id, None)
        if not isinstance(answer, dict) or answer.get("abort") is True:
            return None
        try:
            return response_from_wire(answer.get("response"))
        except WireInvalid:
            return None

    # -- 호스트의 호출 ----------------------------------------------------------------

    async def _op(self, op: str, args: dict[str, Any]) -> Any:
        if op == "open":
            if self._context is not None:
                raise WireInvalid("open")
            self._context = await self._driver.new_context(self._serve, task_id="")
            self._page = await self._context.open_page()
            return None
        page = self._page
        if page is None:
            raise WireInvalid("no_page")
        if op == "close":
            context, self._context, self._page = self._context, None, None
            if context is not None:
                await context.close()
            self._done.set()
            return None
        if op == "title":
            return await page.title()
        if op == "goto":
            return await page.goto(_str(args, "url"), timeout_ms=_ms(args))
        if op == "snapshot":
            return await page.snapshot(timeout_ms=_ms(args))
        if op == "password_values":
            return list(await page.password_values())
        if op == "element_origin":
            return await page.element_origin(_str(args, "ref"), timeout_ms=_ms(args))
        if op == "click":
            return await page.click(_str(args, "ref"), timeout_ms=_ms(args))
        if op == "fill":
            return await page.fill(_str(args, "ref"), _str(args, "value"), timeout_ms=_ms(args))
        if op == "press_enter":
            return await page.press_enter(_str(args, "ref"), timeout_ms=_ms(args))
        raise WireInvalid("op")

    async def _call(self, message: dict) -> None:
        call_id = message.get("call")
        op = message.get("op")
        args = message.get("args") or {}
        try:
            if not isinstance(op, str) or not isinstance(args, dict):
                raise WireInvalid("call")
            result = await self._op(op, args)
            reply: dict[str, Any] = {"reply": call_id, "ok": True, "result": result}
        except BrowserActionError as error:
            reply = {"reply": call_id, "ok": False, "error": error.kind}
        except Exception:  # noqa: BLE001 -- 문구를 싣지 않는다(W9)
            reply = {"reply": call_id, "ok": False, "error": "failed"}
        if self._page is not None:
            reply["url"] = self._page.url()
        try:
            await self._stream.write(reply)
        except Exception:  # noqa: BLE001
            self._done.set()

    # -- 한 연결 ---------------------------------------------------------------------

    async def run(self) -> None:
        await self._stream.write(
            {"hello": {"protocol": PROTOCOL_VERSION, "bundle_digest": self._digest}}
        )
        reader = asyncio.create_task(self._read())
        done = asyncio.create_task(self._done.wait())
        try:
            await asyncio.wait({reader, done}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (reader, done):
                task.cancel()
            if self._calls:
                await asyncio.gather(*self._calls, return_exceptions=True)
            for future in self._routes.values():
                if not future.done():
                    future.cancel()
            context, self._context, self._page = self._context, None, None
            if context is not None:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                await self._driver.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _read(self) -> None:
        while True:
            try:
                message = await self._stream.read()
            except (FrameError, Exception):  # noqa: BLE001 -- 끊기거나 깨진 채널은 끝이다
                return
            if "route" in message:
                future = self._routes.get(message.get("route"))  # type: ignore[arg-type]
                if future is not None and not future.done():
                    future.set_result(message)
                continue
            if "call" in message:
                task = asyncio.create_task(self._call(message))
                self._calls.add(task)
                task.add_done_callback(self._calls.discard)


class _StdioChannel:
    """guest 프로세스의 stdin/stdout. 벤더 exec 가 이 둘을 호스트에 잇는다."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def read_exactly(self, size: int) -> bytes:
        return await self._reader.readexactly(size)

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()


async def _stdio() -> _StdioChannel:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=1 << 20)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    transport, protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout.buffer
    )
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return _StdioChannel(reader, writer)


async def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="neos-browser-guest")
    parser.add_argument("--executable-path", default=None)
    parser.add_argument(
        "--no-chromium-sandbox",
        action="store_true",
        help="Chromium 자신의 샌드박스를 끈다 -- 스모크 전용, 운영에서 쓰지 않는다",
    )
    options = parser.parse_args(argv)
    from neos.coding.browser.playwright_driver import PlaywrightDriver

    driver = PlaywrightDriver(
        chromium_sandbox=not options.no_chromium_sandbox,
        executable_path=options.executable_path,
    )
    await BrowserGuest(driver, await _stdio()).run()


if __name__ == "__main__":  # pragma: no cover -- 실제 Chromium 스모크가 이 길로 띄운다
    asyncio.run(_main())
