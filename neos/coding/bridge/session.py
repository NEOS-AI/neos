"""브리지 소켓 하나의 세션 -- 트랙 Q16a.

인증과 도구 선언(hello)이 끝난 소켓을 받아, 중계에 연결을 걸고, 들어온 호출을 브리지로
보내고, 브리지의 답을 그 호출을 건 쪽에만 돌려준다. 이 세션은 **자기 연결의 것만** 안다:

- 요청의 `user_id` 가 이 연결의 사용자와 다르면 보내지 않는다(`device_bridge_owner_mismatch`)
- 답은 이 연결이 보낸 요청 id 에만 붙는다 -- 모르는 id 의 답은 버린다
- 무인 규칙은 연결이 쥔 **지금의** `allow_unattended` 로 한 번 더 본다(`device_unattended_refused`)
- 걸린 호출 수 상한 · 메시지 크기 상한 · 갱신마다 자격증명을 다시 읽는다(폐기·설정 변경 감지)

닫는 코드: 4401 폐기 · 4409 다른 연결에 밀림(브리지는 다시 붙지 않는다) ·
4001 설정이 바뀜/연결 표시를 잃음(다시 붙는다) · 1009 메시지가 너무 크다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from neos.coding.bridge.catalog import DEVICE_TOOLS, device_unattended_refused
from neos.coding.bridge.relay import DISPLACED, KICKED, BridgeView, DeviceBridgeRelay

logger = logging.getLogger(__name__)

CLOSE_REVOKED = 4401
CLOSE_DISPLACED = 4409
CLOSE_RECONNECT = 4001
CLOSE_TOO_LARGE = 1009

Recheck = Callable[[], Awaitable[Any]]


class BridgeSocketSession:
    def __init__(
        self,
        websocket: Any,
        view: BridgeView,
        relay: DeviceBridgeRelay,
        *,
        config: Any,
        recheck: Recheck,
    ) -> None:
        self._ws = websocket
        self.view = view
        self._relay = relay
        self._config = config
        self._recheck = recheck
        self._inflight: set[str] = set()
        self._send_lock = asyncio.Lock()

    async def _send(self, message: dict) -> None:
        async with self._send_lock:
            await self._ws.send_json(message)

    async def _answer(self, request_id: str, **body: Any) -> None:
        await self._relay.respond(
            request_id, {"id": request_id, "user_id": self.view.user_id, **body}
        )

    async def deliver(self, request: Any) -> None:
        """중계가 부른다. 이 연결로 보낼 수 없는 요청은 이름 붙은 오류로 곧바로 답한다."""
        request_id = request.get("id") if isinstance(request, dict) else None
        if not isinstance(request_id, str) or not request_id:
            return
        if request.get("user_id") != self.view.user_id:
            logger.warning("device bridge request for another user refused")
            await self._answer(request_id, ok=False, error="device_bridge_owner_mismatch")
            return
        tool = request.get("tool")
        spec = DEVICE_TOOLS.get(tool) if isinstance(tool, str) else None
        if spec is None or tool not in self.view.tools:
            await self._answer(request_id, ok=False, error="device_tool_not_offered")
            return
        if device_unattended_refused(
            spec.tool.name,
            unattended=request.get("unattended") is not False,
            allowed=self.view.allow_unattended,
        ):
            await self._answer(request_id, ok=False, error="policy_device_unattended")
            return
        if len(self._inflight) >= int(self._config.max_inflight_per_bridge):
            await self._answer(request_id, ok=False, error="device_bridge_busy")
            return
        args = request.get("args")
        self._inflight.add(request_id)
        try:
            await self._send(
                {
                    "v": 1,
                    "type": "call",
                    "id": request_id,
                    "tool": tool,
                    "args": args if isinstance(args, dict) else {},
                }
            )
        except Exception:  # noqa: BLE001 -- 보내지 못했으면 기다리게 두지 않는다
            self._inflight.discard(request_id)
            await self._answer(request_id, ok=False, error="device_bridge_disconnected")

    async def _on_message(self, raw: str) -> int | None:
        """닫아야 하면 닫는 코드를 돌려준다."""
        if len(raw.encode("utf-8")) > int(self._config.max_message_bytes):
            return CLOSE_TOO_LARGE
        try:
            message = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(message, dict):
            return None
        kind = message.get("type")
        if kind == "ping":
            await self._send({"v": 1, "type": "pong"})
            return None
        if kind != "result":
            return None
        request_id = message.get("id")
        if not isinstance(request_id, str) or request_id not in self._inflight:
            return None  # 이 연결이 보낸 요청이 아니다
        self._inflight.discard(request_id)
        if message.get("ok") is True:
            await self._answer(request_id, ok=True, result=message.get("result"))
        else:
            error = message.get("error")
            await self._answer(
                request_id, ok=False, error=error if isinstance(error, str) else "device_error"
            )
        return None

    async def _closing_code_for(self, reason: str) -> int:
        if reason == DISPLACED:
            return CLOSE_DISPLACED
        if reason == KICKED:
            current = await self._recheck_safely()
            return CLOSE_REVOKED if current is None else CLOSE_RECONNECT
        return CLOSE_RECONNECT

    async def _recheck_safely(self) -> Any:
        try:
            return await self._recheck()
        except Exception:  # noqa: BLE001 -- 못 읽으면 폐기된 것으로 닫는다
            logger.warning("device bridge credential recheck failed", exc_info=True)
            return None

    async def _tick(self, attachment: Any) -> int | None:
        current = await self._recheck_safely()
        if current is None:
            return CLOSE_REVOKED
        if bool(getattr(current, "allow_unattended", False)) != self.view.allow_unattended:
            return CLOSE_RECONNECT
        if not await attachment.refresh():
            return await self._closing_code_for(attachment.reason)
        return None

    async def run(self) -> int:
        """세션이 끝날 때까지 돈다. 닫은 코드를 돌려준다(브리지가 먼저 끊었으면 1000)."""
        attachment = await self._relay.attach(self.view, self.deliver)
        code = 1000
        receive: asyncio.Task | None = None
        closed = asyncio.create_task(attachment.closed.wait())
        interval = max(float(self._config.presence_ttl_seconds) / 3.0, 0.05)
        try:
            await self._send(
                {
                    "v": 1,
                    "type": "ready",
                    "bridge_id": self.view.bridge_id,
                    "tools": sorted(self.view.tools),
                    "allow_unattended": self.view.allow_unattended,
                    "max_message_bytes": int(self._config.max_message_bytes),
                }
            )
            while True:
                if receive is None:
                    receive = asyncio.create_task(self._ws.receive_text())
                done, _pending = await asyncio.wait(
                    {receive, closed}, timeout=interval, return_when=asyncio.FIRST_COMPLETED
                )
                if closed in done:
                    code = await self._closing_code_for(attachment.reason)
                    break
                if receive in done:
                    try:
                        raw = receive.result()
                    except Exception:  # noqa: BLE001 -- 브리지가 끊었다
                        code = 1000
                        break
                    receive = None
                    closing = await self._on_message(raw)
                    if closing == CLOSE_TOO_LARGE:
                        # 어느 요청의 답인지 읽지 않는다 -- 걸린 것 전부가 같은 이유로 끝난다.
                        for request_id in tuple(self._inflight):
                            await self._answer(
                                request_id, ok=False, error="device_result_too_large"
                            )
                        self._inflight.clear()
                    if closing is not None:
                        code = closing
                        break
                    continue
                closing = await self._tick(attachment)
                if closing is not None:
                    code = closing
                    break
        finally:
            for task in (receive, closed):
                if task is not None and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
            await attachment.detach()
            for request_id in tuple(self._inflight):
                with contextlib.suppress(Exception):
                    await self._answer(request_id, ok=False, error="device_bridge_disconnected")
            self._inflight.clear()
        if code != 1000:
            with contextlib.suppress(Exception):
                await self._ws.close(code=code)
        return code


__all__ = [
    "BridgeSocketSession",
    "CLOSE_DISPLACED",
    "CLOSE_RECONNECT",
    "CLOSE_REVOKED",
    "CLOSE_TOO_LARGE",
]
