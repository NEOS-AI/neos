"""브리지 소켓 클라이언트 -- 트랙 Q16a.

기기에서 NEOS 로 **밖으로** 연결한다(기기에 열린 포트가 없다). 토큰은 헤더로만 보낸다.
첫 메시지는 도구 선언(hello)이고, 그 뒤로는 서버의 `call` 에 `result` 로 답한다.
도구는 스레드에서 돈다 -- 큰 파일 읽기가 핑을 막지 않게.

닫는 코드에 따라: 4401(폐기)·4403(선언 거절)·4409(다른 연결에 밀림)·4406 은 끝낸다.
그 밖(4001 설정 변경·연결 표시 잃음, 네트워크 끊김)은 물러섰다가 다시 붙는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

from neos.bridge.tools import BridgeToolError, LocalReadOnlyTools

logger = logging.getLogger(__name__)

PROTOCOL = "neos.device-bridge.v1"
FINAL_CLOSE_CODES = frozenset({4401, 4403, 4406, 4409})
PING_SECONDS = 20.0
_DEFAULT_MAX_MESSAGE = 2_097_152


class BridgeRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _encode_result(request_id: str, payload: dict[str, Any], limit: int) -> str:
    """상한을 넘는 답은 본문을 줄여 보낸다(서버는 넘으면 소켓을 닫는다)."""
    message = {"v": 1, "type": "result", "id": request_id, **payload}
    encoded = json.dumps(message, ensure_ascii=False)
    result = payload.get("result")
    while len(encoded.encode("utf-8")) > limit and isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str) and text:
            result = {**result, "text": text[: len(text) // 2], "truncated": True}
        else:
            entries = result.get("entries")
            if not isinstance(entries, list) or not entries:
                return json.dumps(
                    {"v": 1, "type": "result", "id": request_id, "ok": False, "error": "device_error"}
                )
            result = {**result, "entries": entries[: len(entries) // 2], "truncated": True}
        message["result"] = result
        encoded = json.dumps(message, ensure_ascii=False)
    return encoded


def _answer(tools: LocalReadOnlyTools, tool: object, args: object) -> dict[str, Any]:
    if not isinstance(tool, str):
        return {"ok": False, "error": "unknown_tool"}
    try:
        return {"ok": True, "result": tools.call(tool, args if isinstance(args, dict) else {})}
    except BridgeToolError as error:
        return {"ok": False, "error": error.code}
    except Exception:  # noqa: BLE001 -- 무엇이 깨졌는지는 기기 로그에만 남긴다
        logger.exception("bridge tool failed")
        return {"ok": False, "error": "device_error"}


async def serve(ws: Any, tools: LocalReadOnlyTools) -> None:
    """연결 하나를 끝까지 돈다. 거절되면 `BridgeRefused`."""
    await ws.send(json.dumps({"v": 1, "type": "hello", "tools": tools.declaration()}))
    first = json.loads(await ws.recv())
    if not isinstance(first, dict) or first.get("type") != "ready":
        code = first.get("code") if isinstance(first, dict) else None
        raise BridgeRefused(code if isinstance(code, str) else "device_declaration_invalid")
    limit = first.get("max_message_bytes")
    limit = limit if isinstance(limit, int) and limit > 0 else _DEFAULT_MAX_MESSAGE
    logger.info("bridge ready: %s tools=%s", first.get("bridge_id"), first.get("tools"))
    pending: set[asyncio.Task] = set()
    send_lock = asyncio.Lock()

    async def send(text: str) -> None:
        async with send_lock:
            await ws.send(text)

    async def handle(message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, str):
            return
        payload = await asyncio.to_thread(_answer, tools, message.get("tool"), message.get("args"))
        await send(_encode_result(request_id, payload, limit))

    async def ping() -> None:
        while True:
            await asyncio.sleep(PING_SECONDS)
            await send(json.dumps({"v": 1, "type": "ping"}))

    pinger = asyncio.create_task(ping())
    try:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "call":
                task = asyncio.create_task(handle(message))
                pending.add(task)
                task.add_done_callback(pending.discard)
    finally:
        pinger.cancel()
        for task in (pinger, *pending):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def _close_code(error: BaseException) -> int | None:
    received = getattr(error, "rcvd", None)
    code = getattr(received, "code", None)
    if code is not None:
        return code
    # 서버는 인증·subprotocol 을 accept **전에** 닫는다 -- ASGI 서버는 그것을 HTTP 403 으로
    # 보낸다(닫는 코드가 오지 않는다). 다시 붙어도 같으므로 끝낸다.
    status = getattr(getattr(error, "response", None), "status_code", None)
    return 4401 if status in {401, 403} else None


async def run_bridge(
    url: str,
    token: str,
    tools: LocalReadOnlyTools,
    *,
    connect: Callable[..., Any] | None = None,
    max_backoff: float = 60.0,
) -> int:
    """끝내야 할 때까지 붙어 있다. 끝낸 이유의 닫는 코드를 돌려준다."""
    if connect is None:
        from websockets.asyncio.client import connect as ws_connect

        connect = ws_connect
    backoff = 1.0
    while True:
        try:
            async with connect(
                url,
                subprotocols=[PROTOCOL],
                additional_headers={"Authorization": f"Bearer {token}"},
                max_size=None,
            ) as ws:
                backoff = 1.0
                await serve(ws, tools)
                code = getattr(ws, "close_code", None)
        except BridgeRefused as refused:
            logger.error("bridge refused by NEOS: %s", refused.code)
            return 4403
        except Exception as error:  # noqa: BLE001 -- 네트워크든 닫힘이든 코드로 가른다
            code = _close_code(error)
            logger.warning("bridge disconnected (%s): %s", code, type(error).__name__)
        if code in FINAL_CLOSE_CODES:
            logger.error("bridge stopped by NEOS (close %s)", code)
            return int(code)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


__all__ = ["BridgeRefused", "FINAL_CLOSE_CODES", "PROTOCOL", "run_bridge", "serve"]
