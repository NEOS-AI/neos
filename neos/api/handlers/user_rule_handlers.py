"""사용자 승인 규칙 API -- 트랙 Q2 (docs/Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md §2).

```
GET    /api/v1/coding/approval-rules             # 내 규칙 목록
POST   /api/v1/coding/approval-rules             # {effect, tool, argv_prefix?}
DELETE /api/v1/coding/approval-rules/{rule_id}
```

규칙은 자기 것만 보이고 지운다. 남의 규칙 id 는 없는 것과 같은 404 다.
`coding_model.approval_user_rules` 가 꺼져 있으면 `main.py` 가 마운트하지 않는다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.coding.application.user_rules import (
    PostgresUserRuleStore,
    UserRuleConflict,
    UserRuleLimit,
    UserRuleStore,
)
from neos.coding.domain.approvals import UserApprovalRule
from neos.database.connection import db_manager
from neos.database.models import User

router = APIRouter(prefix="/coding/approval-rules", tags=["Coding Approval Rules"])


def get_user_rule_store() -> UserRuleStore:
    from neos.config.settings import settings

    return PostgresUserRuleStore(
        db_manager.get_session,
        max_rules=settings.config.coding_model.approval_user_rules_max,
    )


class RuleOut(BaseModel):
    rule_id: str
    effect: str
    tool: str
    argv_prefix: list[str]


class CreateRuleIn(BaseModel):
    effect: Literal["allow", "require", "block"]
    tool: str
    argv_prefix: list[str] = []


def _out(rule: UserApprovalRule) -> RuleOut:
    return RuleOut(
        rule_id=rule.rule_id,
        effect=rule.effect.value,
        tool=rule.tool,
        argv_prefix=list(rule.argv_prefix),
    )


@router.get("", response_model=list[RuleOut])
async def list_rules(
    current_user: User = Depends(get_current_user),
    store: UserRuleStore = Depends(get_user_rule_store),
) -> list[RuleOut]:
    return [_out(rule) for rule in await store.list_for_user(current_user.user_id)]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: CreateRuleIn,
    current_user: User = Depends(get_current_user),
    store: UserRuleStore = Depends(get_user_rule_store),
) -> RuleOut:
    try:
        rule = await store.create(
            current_user.user_id, effect=body.effect, tool=body.tool, argv_prefix=body.argv_prefix
        )
    except UserRuleConflict as error:
        raise HTTPException(status_code=409, detail={"code": "rule_exists"}) from error
    except UserRuleLimit as error:
        raise HTTPException(status_code=409, detail={"code": "rule_limit"}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    store: UserRuleStore = Depends(get_user_rule_store),
) -> Response:
    if not await store.delete(current_user.user_id, rule_id):
        raise HTTPException(status_code=404, detail="rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
