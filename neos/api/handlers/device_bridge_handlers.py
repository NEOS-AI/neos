"""기기 브리지 페어링 API -- 트랙 Q16a (docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md).

```
GET    /api/v1/coding/device-bridges                # 내 브리지 목록 (+ 지금 붙어 있는가)
POST   /api/v1/coding/device-bridges                # {name, allow_unattended?, allow_writes?, allow_commands?} -- 토큰은 이 응답에만
PATCH  /api/v1/coding/device-bridges/{bridge_id}    # {allow_unattended?, allow_writes?, allow_commands?} -- 붙어 있으면 끊어 다시 붙게 한다
DELETE /api/v1/coding/device-bridges/{bridge_id}    # 폐기 -- 붙어 있으면 끊는다
```

토큰은 만들 때 **한 번만** 보인다. 자기 브리지만 보이고 바꾼다 -- 남의 id 는 404.
`coding_model.device_bridge.enabled` 가 꺼져 있으면 `main.py` 가 마운트하지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, model_validator

from neos.api.dependencies.auth import get_current_user
from neos.coding.bridge.credentials import (
    BridgeCredentialInfo,
    BridgeCredentialStore,
    BridgeLimit,
    BridgeNameTaken,
    PostgresBridgeCredentialStore,
)
from neos.coding.bridge.relay import DeviceBridgeRelay, RedisDeviceBridgeRelay
from neos.database.connection import db_manager
from neos.database.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding/device-bridges", tags=["Coding Device Bridges"])


def get_device_bridge_config():
    from neos.config.settings import settings

    return settings.config.coding_model.device_bridge


def get_bridge_credential_store() -> BridgeCredentialStore:
    return PostgresBridgeCredentialStore(
        db_manager.get_session,
        max_bridges=get_device_bridge_config().max_bridges_per_user,
    )


_relay_for: tuple[object, RedisDeviceBridgeRelay] | None = None


def get_device_bridge_relay() -> DeviceBridgeRelay | None:
    """API 프로세스의 Redis 클라이언트 위의 중계. Redis 가 없으면 `None` -- 소켓은 1013 으로 닫는다."""
    global _relay_for
    from neos.utils.cache import cache_manager

    client = cache_manager.redis_client
    if client is None:
        return None
    if _relay_for is None or _relay_for[0] is not client:
        _relay_for = (
            client,
            RedisDeviceBridgeRelay(
                client=client, ttl_seconds=get_device_bridge_config().presence_ttl_seconds
            ),
        )
    return _relay_for[1]


class BridgeOut(BaseModel):
    bridge_id: str
    name: str
    allow_unattended: bool
    created_at: datetime
    last_connected_at: datetime | None
    connected: bool = False
    #: 쓰기 도구를 선언해도 되는가(Q16b). 클라이언트의 `--allow-writes` 와 둘 다 있어야 한다.
    allow_writes: bool = False
    #: 명령 도구를 선언해도 되는가(Q16c). 클라이언트의 `--allow-commands` 와 서버 상한이 함께 있어야 한다.
    allow_commands: bool = False


class CreatedBridgeOut(BridgeOut):
    #: 이 응답에만 있다. 다시 볼 수 없다 -- 잃으면 폐기하고 새로 만든다.
    token: str


class CreateBridgeIn(BaseModel):
    name: str
    allow_unattended: bool = False
    allow_writes: bool = False
    allow_commands: bool = False


class UpdateBridgeIn(BaseModel):
    allow_unattended: bool | None = None
    allow_writes: bool | None = None
    allow_commands: bool | None = None

    @model_validator(mode="after")
    def _something(self) -> "UpdateBridgeIn":
        if self.allow_unattended is None and self.allow_writes is None and self.allow_commands is None:
            raise ValueError("set allow_unattended, allow_writes or allow_commands")
        return self


def _out(info: BridgeCredentialInfo, *, connected: bool = False) -> BridgeOut:
    return BridgeOut(
        bridge_id=info.bridge_id,
        name=info.name,
        allow_unattended=info.allow_unattended,
        created_at=info.created_at,
        last_connected_at=info.last_connected_at,
        connected=connected,
        allow_writes=info.allow_writes,
        allow_commands=info.allow_commands,
    )


async def _kick(relay: DeviceBridgeRelay | None, user_id: str, bridge_id: str) -> None:
    """붙어 있는 연결을 끊는다. 실패해도 소켓이 다음 갱신에서 자격증명을 다시 읽는다."""
    if relay is None:
        return
    try:
        await relay.kick(user_id, bridge_id)
    except Exception:  # noqa: BLE001
        logger.warning("device bridge kick failed; the socket recheck will close it", exc_info=True)


@router.get("", response_model=list[BridgeOut])
async def list_device_bridges(
    current_user: User = Depends(get_current_user),
    store: BridgeCredentialStore = Depends(get_bridge_credential_store),
    relay: DeviceBridgeRelay | None = Depends(get_device_bridge_relay),
) -> list[BridgeOut]:
    live = None
    if relay is not None:
        try:
            live = await relay.view(current_user.user_id)
        except Exception:  # noqa: BLE001 -- 목록은 연결 표시 없이도 보인다
            live = None
    return [
        _out(info, connected=live is not None and live.bridge_id == info.bridge_id)
        for info in await store.list_for_user(current_user.user_id)
    ]


@router.post("", response_model=CreatedBridgeOut, status_code=status.HTTP_201_CREATED)
async def create_device_bridge(
    body: CreateBridgeIn,
    current_user: User = Depends(get_current_user),
    store: BridgeCredentialStore = Depends(get_bridge_credential_store),
) -> CreatedBridgeOut:
    try:
        info, token = await store.create(
            current_user.user_id,
            body.name,
            allow_unattended=body.allow_unattended,
            allow_writes=body.allow_writes,
            allow_commands=body.allow_commands,
        )
    except BridgeLimit as error:
        raise HTTPException(status_code=409, detail={"code": "device_bridge_limit"}) from error
    except BridgeNameTaken as error:
        raise HTTPException(status_code=409, detail={"code": "device_bridge_name_taken"}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CreatedBridgeOut(**_out(info).model_dump(), token=token)


@router.patch("/{bridge_id}", response_model=BridgeOut)
async def update_device_bridge(
    bridge_id: str,
    body: UpdateBridgeIn,
    current_user: User = Depends(get_current_user),
    store: BridgeCredentialStore = Depends(get_bridge_credential_store),
    relay: DeviceBridgeRelay | None = Depends(get_device_bridge_relay),
) -> BridgeOut:
    info = await store.get(current_user.user_id, bridge_id)
    if info is not None and body.allow_unattended is not None:
        info = await store.set_unattended(current_user.user_id, bridge_id, body.allow_unattended)
    if info is not None and body.allow_writes is not None:
        info = await store.set_writes(current_user.user_id, bridge_id, body.allow_writes)
    if info is not None and body.allow_commands is not None:
        info = await store.set_commands(current_user.user_id, bridge_id, body.allow_commands)
    if info is None:
        raise HTTPException(status_code=404, detail="device bridge not found")
    # 붙어 있는 연결은 옛 설정을 쥐고 있다 -- 끊어서 새 설정으로 다시 붙게 한다.
    await _kick(relay, current_user.user_id, bridge_id)
    return _out(info)


@router.delete("/{bridge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_bridge(
    bridge_id: str,
    current_user: User = Depends(get_current_user),
    store: BridgeCredentialStore = Depends(get_bridge_credential_store),
    relay: DeviceBridgeRelay | None = Depends(get_device_bridge_relay),
) -> Response:
    if not await store.delete(current_user.user_id, bridge_id):
        raise HTTPException(status_code=404, detail="device bridge not found")
    await _kick(relay, current_user.user_id, bridge_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
