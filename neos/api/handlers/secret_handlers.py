"""사용자 비밀 금고 API -- 트랙 Q6 (docs/Q6_CREDENTIAL_BROKER_DESIGN_261001.md).

```
GET    /api/v1/coding/secrets            # 이름·env_name·browser_origins·시각만
PUT    /api/v1/coding/secrets/{name}     # {env_name, value, browser_origins?} -- 만들거나 바꾼다
DELETE /api/v1/coding/secrets/{name}
```

값은 **어떤 응답에도 없다** -- 쓰기 전용이다. 자기 비밀만 보이고 지운다.
PUT 은 행을 통째로 바꾼다 -- `browser_origins` 를 빼면 브라우저 묶임이 비워진다(트랙 Q14b X2).
`coding_model.secret_broker` 가 꺼져 있으면 `main.py` 가 마운트하지 않는다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from neos.api.dependencies.auth import get_current_user
from neos.coding.secrets import (
    PostgresSecretStore,
    SecretInfo,
    SecretLimit,
    SecretStore,
    derive_secret_key,
)
from neos.database.connection import db_manager
from neos.database.models import User

router = APIRouter(prefix="/coding/secrets", tags=["Coding Secrets"])


def get_secret_store() -> SecretStore:
    from neos.config.settings import settings

    config = settings.config
    return PostgresSecretStore(
        db_manager.get_session,
        key=derive_secret_key(config.secrets.secret_broker_key or ""),
        max_secrets=config.coding_model.secret_broker_max,
    )


class SecretOut(BaseModel):
    name: str
    env_name: str
    browser_origins: list[str]
    created_at: datetime
    updated_at: datetime


class PutSecretIn(BaseModel):
    env_name: str
    # 길이 검사는 여기서 하지 않는다 -- pydantic 의 422 는 `input` 에 값을 되돌려
    # 싣는다. `parse_secret_fields` 가 값 없이 모양만 말한다.
    value: str = Field(repr=False)
    # 이 비밀을 입력해도 되는 https 출처(트랙 Q14b). 비면 브라우저 어디에도 입력되지 않는다.
    browser_origins: list[str] = Field(default_factory=list)


def _out(info: SecretInfo) -> SecretOut:
    return SecretOut(
        name=info.name,
        env_name=info.env_name,
        browser_origins=list(info.browser_origins),
        created_at=info.created_at,
        updated_at=info.updated_at,
    )


@router.get("", response_model=list[SecretOut])
async def list_secrets(
    current_user: User = Depends(get_current_user),
    store: SecretStore = Depends(get_secret_store),
) -> list[SecretOut]:
    return [_out(info) for info in await store.list_for_user(current_user.user_id)]


@router.put("/{name}", response_model=SecretOut)
async def put_secret(
    name: str,
    body: PutSecretIn,
    current_user: User = Depends(get_current_user),
    store: SecretStore = Depends(get_secret_store),
) -> SecretOut:
    try:
        info = await store.put(
            current_user.user_id,
            name,
            env_name=body.env_name,
            value=body.value,
            browser_origins=body.browser_origins,
        )
    except SecretLimit as error:
        raise HTTPException(status_code=409, detail={"code": "secret_limit"}) from error
    except ValueError as error:
        # 메시지는 모양만 말한다 -- 값을 싣지 않는다(parse_secret_fields).
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _out(info)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    name: str,
    current_user: User = Depends(get_current_user),
    store: SecretStore = Depends(get_secret_store),
) -> Response:
    if not await store.delete(current_user.user_id, name):
        raise HTTPException(status_code=404, detail="secret not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
