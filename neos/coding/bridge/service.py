"""루프가 쥐는 것 -- 소유자의 브리지를 보고, 호출하고, 결과를 감싼다 (트랙 Q16a · Q16b · Q16c).

어떤 실패도 예외로 루프에 올리지 않는다: 연결이 없거나, 늦거나, 답이 어긋나면 이름 붙은
`ToolResult` 하나가 된다. 연결 표시를 읽지 못하면 **브리지가 없는 것**으로 본다 --
도구가 사라지는 쪽은 좁히는 쪽이다(Q2 규칙 읽기 실패와 반대 방향이라 재시도로 만들지 않는다).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from neos.coding.bridge.catalog import (
    COMMAND_TOOLS,
    WRITE_TOOLS,
    bridge_tool_name,
    device_unattended_refusal,
    failure_result,
    shape_reply,
)
from neos.coding.bridge.relay import BridgeView, DeviceBridgeRelay, DeviceRelayError

logger = logging.getLogger(__name__)


class DeviceBridgeService:
    def __init__(self, relay: DeviceBridgeRelay, config: Any) -> None:
        self._relay = relay
        self._config = config

    @property
    def command_claim_seconds(self) -> float:
        """기기 명령 하나가 걸릴 수 있는 가장 긴 시간 + 여유 -- 루프가 claim 을 그만큼 쥔다(BC10)."""
        return (
            float(self._config.command_timeout_seconds)
            + float(self._config.call_timeout_seconds)
            + 30.0
        )

    async def view(self, owner_id: str | None) -> BridgeView | None:
        if not owner_id:
            return None
        try:
            view = await self._relay.view(owner_id)
        except Exception:  # noqa: BLE001 -- 못 읽으면 없는 것이다(좁히는 쪽)
            logger.warning("device bridge presence unreadable", exc_info=True)
            return None
        if view is None or view.user_id != owner_id:
            return None
        return view

    async def execute(self, owner_id: str | None, call, *, unattended: bool, revision: str = "unknown"):
        bridge_name = bridge_tool_name(call.name)
        if bridge_name is None:
            return failure_result("device_tool_not_offered", revision=revision)
        view = await self.view(owner_id)
        if view is None:
            return failure_result("device_bridge_unavailable", revision=revision)
        if bridge_name not in view.tools:
            return failure_result("device_tool_not_offered", revision=revision)
        # 게이트가 이미 봤다. 단계 시작과 호출 사이에 설정이 바뀌었을 수 있어 한 번 더 -- 같은 함수로.
        refusal = device_unattended_refusal(
            call.name, unattended=unattended, allowed=view.allow_unattended
        )
        if refusal is not None:
            return failure_result(refusal, revision=revision)
        args = dict(call.input)
        timeout = float(self._config.call_timeout_seconds)
        if bridge_name in COMMAND_TOOLS:
            # Q16c. 실행 파일은 이 연결이 선언하고 서버 상한이 받은 것이어야 한다(BC3) -- 검증기는
            # 서버 상한만 안다. 시간·출력 상한은 서버가 정해 넘기고, 기기도 자기 상한과 함께 본다.
            argv = args.get("argv")
            if not (isinstance(argv, list) and argv and argv[0] in view.executables):
                return failure_result("device_command_not_offered", revision=revision)
            cap = float(self._config.command_timeout_seconds)
            requested = args.get("timeout_sec")
            limit = min(float(requested), cap) if isinstance(requested, (int, float)) else cap
            args["timeout_sec"] = limit
            args["max_output_bytes"] = int(self._config.max_command_output_bytes)
            # 기기는 시간 제한까지 돌고 그 뒤에 답한다 -- 기다리는 쪽은 그만큼 더 기다린다.
            timeout = limit + float(self._config.call_timeout_seconds)
        elif bridge_name in WRITE_TOOLS:
            # 운영 상한(BW11). 기기도 같은 값을 받아 한 번 더 본다.
            cap = int(self._config.max_write_bytes)
            if len(str(args.get("content", "")).encode("utf-8")) > cap:
                return failure_result("device_write_too_large", revision=revision)
            args["max_bytes"] = cap
        elif bridge_name == "read_file":
            args["max_bytes"] = int(self._config.max_read_bytes)
        elif bridge_name == "list_dir":
            args["max_entries"] = int(self._config.max_list_entries)
        message = {
            "id": uuid.uuid4().hex,
            "user_id": owner_id,
            "tool": bridge_name,
            "args": args,
            "unattended": bool(unattended),
        }
        try:
            reply = await self._relay.request(view, message, timeout=timeout)
        except DeviceRelayError as error:
            return failure_result(error.code, revision=revision)
        except Exception:  # noqa: BLE001 -- 중계가 깨져도 이름 붙은 실패 하나다
            logger.warning("device bridge relay failed", exc_info=True)
            return failure_result("device_bridge_unavailable", revision=revision)
        if reply.get("id") != message["id"] or reply.get("user_id") != owner_id:
            return failure_result("device_bridge_owner_mismatch", revision=revision)
        return shape_reply(
            bridge_name,
            reply,
            revision=revision,
            max_read_bytes=int(self._config.max_read_bytes),
            max_list_entries=int(self._config.max_list_entries),
            digests=bool(view.tools & WRITE_TOOLS),
            max_output_bytes=int(self._config.max_command_output_bytes),
        )


def build_device_bridge_service(coding: Any) -> DeviceBridgeService | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다.

    루프는 Celery 워커에서 돈다 -- 태스크마다 이벤트 루프가 새로 서므로 Redis 클라이언트를
    연산마다 연다(`client_factory`).
    """
    config = getattr(coding, "device_bridge", None)
    if config is None or not getattr(config, "enabled", False):
        return None
    from neos.coding.bridge.relay import RedisDeviceBridgeRelay

    def open_client():
        import redis.asyncio as redis

        from neos.config.settings import settings

        return redis.Redis.from_url(settings.REDIS_URL)

    return DeviceBridgeService(
        RedisDeviceBridgeRelay(
            client_factory=open_client, ttl_seconds=config.presence_ttl_seconds
        ),
        config,
    )


__all__ = ["DeviceBridgeService", "build_device_bridge_service"]
