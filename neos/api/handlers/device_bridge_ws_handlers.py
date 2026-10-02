"""기기 브리지 소켓 -- 트랙 Q16a (docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md).

```
WS /api/v1/coding/device-bridge/ws      subprotocol neos.device-bridge.v1
```

브리지가 **밖으로** 연다(기기에 열린 포트가 없다). 자격증명은 코딩 소켓과 같은 자리에서
읽는다(`ticket_from_websocket`: `x-neos-ticket` · `Authorization: Bearer` · `neos.ticket.*`
subprotocol) -- 쿼리 문자열은 받지 않는다(접근 로그에 남는다). 접속 뒤 첫 메시지는 도구
선언(hello)이고, 받는 등급 밖이 하나라도 있으면 전부 거절한다(B3). 쓰기 도구는 자격증명의
`allow_writes` 가 참일 때만 받는다 -- 아니면 역시 전부 거절(`device_writes_not_enabled`, Q16b BW2).

`coding_model.device_bridge.enabled` 가 꺼져 있으면 `main.py` 가 마운트하지 않는다.
nginx 는 이 경로를 업그레이드 location 으로 받는다(`config/nginx/nginx.conf`).
"""

from __future__ import annotations

import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from neos.api.handlers.coding_ws_handlers import ticket_from_websocket
from neos.api.handlers.device_bridge_handlers import (
    get_bridge_credential_store,
    get_device_bridge_config,
    get_device_bridge_relay,
)
from neos.coding.bridge.catalog import DeviceDeclarationRefused, parse_declaration
from neos.coding.bridge.credentials import BridgeCredentialStore
from neos.coding.bridge.relay import BridgeView, DeviceBridgeRelay
from neos.coding.bridge.session import BridgeSocketSession

router = APIRouter(prefix="/coding/device-bridge", tags=["Coding Device Bridge"])

PROTOCOL = "neos.device-bridge.v1"
CLOSE_UNSUPPORTED = 4406
CLOSE_UNAUTHENTICATED = 4401
CLOSE_REFUSED = 4403
CLOSE_HELLO_TIMEOUT = 4408
CLOSE_UNAVAILABLE = 1013


@router.websocket("/ws")
async def device_bridge_websocket(
    websocket: WebSocket,
    credentials: BridgeCredentialStore = Depends(get_bridge_credential_store),
    relay: DeviceBridgeRelay | None = Depends(get_device_bridge_relay),
    config=Depends(get_device_bridge_config),
) -> None:
    offered = websocket.headers.get("sec-websocket-protocol", "")
    if PROTOCOL not in {item.strip() for item in offered.split(",")}:
        await websocket.close(code=CLOSE_UNSUPPORTED, reason="Unsupported protocol")
        return
    token = ticket_from_websocket(websocket)
    info = await credentials.authenticate(token) if token else None
    if info is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="Authentication required")
        return
    if relay is None:
        await websocket.close(code=CLOSE_UNAVAILABLE, reason="Relay unavailable")
        return

    await websocket.accept(subprotocol=PROTOCOL)
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=float(config.hello_timeout_seconds)
        )
    except TimeoutError:
        await websocket.close(code=CLOSE_HELLO_TIMEOUT, reason="hello expected")
        return
    except WebSocketDisconnect:
        return
    try:
        hello = json.loads(raw) if len(raw) <= 65_536 else None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            raise DeviceDeclarationRefused("device_declaration_invalid")
        tools = parse_declaration(hello.get("tools"), allow_writes=info.allow_writes)
    except (ValueError, DeviceDeclarationRefused) as error:
        code = error.code if isinstance(error, DeviceDeclarationRefused) else "device_declaration_invalid"
        await websocket.send_json({"v": 1, "type": "refused", "code": code})
        await websocket.close(code=CLOSE_REFUSED, reason=code)
        return

    view = BridgeView(
        user_id=info.user_id,
        bridge_id=info.bridge_id,
        conn_id="dbc_" + secrets.token_hex(16),
        tools=tools,
        allow_unattended=info.allow_unattended,
    )

    async def recheck():
        return await credentials.get(info.user_id, info.bridge_id)

    session = BridgeSocketSession(websocket, view, relay, config=config, recheck=recheck)
    try:
        await session.run()
    except WebSocketDisconnect:
        return
