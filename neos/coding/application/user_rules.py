"""사용자 승인 규칙 저장소 -- 트랙 Q2 (docs/Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md §2).

규칙은 **사용자**의 것이다(키는 `user_id`). 상시 에이전트가 연 태스크도 소유자의
규칙을 쓴다(Q13 설계 §5 -- 에이전트 권한은 소유자의 부분집합).

- 루프는 매 단계 소유자의 규칙을 **새로 읽는다**(`DurableCodingLoop` 의
  `user_rules` 원천). 체크포인트에 싣지 않는다 -- 실행 중에 더한 block 이 다음
  단계부터 바로 걸린다.
- 읽을 수 없으면 그 단계는 재시도 가능한 실패다. 규칙 없이 판정하면 block 이
  조용히 빠진다(fail-open).
- 메모리·Postgres 가 **같은 계약**을 지킨다(`tests/coding/test_user_rules.py`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neos.coding.domain.approvals import UserApprovalRule, UserRuleEffect

#: 도구 이름의 모양(`execute.v1`, `write_file.v1`, `mcp__x__y` …). 모르는 도구 이름도
#: 받는다 -- 규칙을 미리 걸어 둘 수 있게. 맞는 호출이 없으면 아무 일도 안 한다.
_TOOL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
#: argv 접두를 받는 도구. 기기 명령(트랙 Q16c)은 argv 접두가 있는 allow 만 승인을 대신한다(BC5).
_ARGV_TOOLS = frozenset({"execute.v1", "device_run_command.v1"})
MAX_ARGV_PREFIX = 8
MAX_ARGV_TOKEN = 128


class UserRuleConflict(Exception):
    """같은 규칙(효과·도구·argv 접두)이 이미 있다."""


class UserRuleLimit(Exception):
    """사용자당 규칙 수 상한(`coding_model.approval_user_rules_max`)에 닿았다."""


def parse_rule_fields(effect: str, tool: str, argv_prefix: Sequence[Any] = ()) -> tuple[
    UserRuleEffect, str, tuple[str, ...]
]:
    """API·DB 의 값을 읽는다. 모양이 틀리면 ValueError."""
    resolved = UserRuleEffect(effect)
    name = (tool or "").strip()
    if not _TOOL_RE.fullmatch(name):
        raise ValueError("tool must be a tool name such as execute.v1")
    prefix = tuple(argv_prefix or ())
    if prefix and name not in _ARGV_TOOLS:
        raise ValueError("argv_prefix applies to execute.v1 and device_run_command.v1 only")
    if len(prefix) > MAX_ARGV_PREFIX:
        raise ValueError(f"argv_prefix has at most {MAX_ARGV_PREFIX} tokens")
    for token in prefix:
        if (
            not isinstance(token, str)
            or not token.strip()
            or token != token.strip()
            or token.startswith("-")
            or len(token) > MAX_ARGV_TOKEN
        ):
            # 플래그는 접두에 둘 수 없다 -- 매칭이 플래그를 건너뛰므로 영영 맞지 않는다.
            raise ValueError("argv_prefix tokens are non-empty words, not flags")
    return resolved, name, prefix


class UserRuleStore(Protocol):
    async def list_for_user(self, user_id: str) -> list[UserApprovalRule]: ...

    async def create(
        self, user_id: str, *, effect: str, tool: str, argv_prefix: Sequence[str] = ()
    ) -> UserApprovalRule: ...

    async def delete(self, user_id: str, rule_id: str) -> bool: ...


def new_rule_id() -> str:
    return f"ur_{uuid4().hex}"


class InMemoryUserRuleStore:
    def __init__(self, *, max_rules: int = 100) -> None:
        self._rules: dict[str, tuple[str, UserApprovalRule, datetime]] = {}
        self._max = max_rules

    async def list_for_user(self, user_id):
        mine = [(at, rule) for owner, rule, at in self._rules.values() if owner == user_id]
        return [rule for _at, rule in sorted(mine, key=lambda pair: pair[0])]

    async def create(self, user_id, *, effect, tool, argv_prefix=()):
        resolved, name, prefix = parse_rule_fields(effect, tool, argv_prefix)
        mine = await self.list_for_user(user_id)
        if any((r.effect, r.tool, r.argv_prefix) == (resolved, name, prefix) for r in mine):
            raise UserRuleConflict()
        if len(mine) >= self._max:
            raise UserRuleLimit()
        rule = UserApprovalRule(new_rule_id(), resolved, name, prefix)
        self._rules[rule.rule_id] = (user_id, rule, datetime.now(UTC))
        return rule

    async def delete(self, user_id, rule_id):
        found = self._rules.get(rule_id)
        if found is None or found[0] != user_id:
            return False
        del self._rules[rule_id]
        return True


class PostgresUserRuleStore:
    def __init__(
        self, session_factory: Callable[[], Awaitable[Any]], *, max_rules: int = 100
    ) -> None:
        self._session_factory = session_factory
        self._max = max_rules

    async def list_for_user(self, user_id):
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT rule_id, effect, tool, argv_prefix FROM user_approval_rules "
                    "WHERE user_id = :user_id ORDER BY created_at, rule_id"
                ),
                {"user_id": user_id},
            )
            return [
                UserApprovalRule(
                    row.rule_id,
                    UserRuleEffect(row.effect),
                    row.tool,
                    tuple(str(token) for token in row.argv_prefix),
                )
                for row in result
            ]

    async def create(self, user_id, *, effect, tool, argv_prefix=()):
        resolved, name, prefix = parse_rule_fields(effect, tool, argv_prefix)
        rule = UserApprovalRule(new_rule_id(), resolved, name, prefix)
        try:
            async with await self._session_factory() as session:
                async with session.begin():
                    # 상한 검사와 삽입이 한 문장이다 -- 동시에 둘이 넣어도 상한을 넘지 않게
                    # 사용자 행을 잠근다.
                    await session.execute(
                        text("SELECT 1 FROM users WHERE user_id = :user_id FOR UPDATE"),
                        {"user_id": user_id},
                    )
                    result = await session.execute(
                        text(
                            """
                            INSERT INTO user_approval_rules
                                (rule_id, user_id, effect, tool, argv_prefix, created_at)
                            SELECT CAST(:rule_id AS VARCHAR), CAST(:user_id AS VARCHAR),
                                   CAST(:effect AS VARCHAR), CAST(:tool AS VARCHAR),
                                   CAST(:argv_prefix AS JSONB), :now
                            WHERE (SELECT count(*) FROM user_approval_rules
                                   WHERE user_id = CAST(:user_id AS VARCHAR))
                                  < CAST(:max AS INTEGER)
                            RETURNING rule_id
                            """
                        ),
                        {
                            "rule_id": rule.rule_id,
                            "user_id": user_id,
                            "effect": resolved.value,
                            "tool": name,
                            "argv_prefix": json.dumps(list(prefix)),
                            "now": datetime.now(UTC),
                            "max": self._max,
                        },
                    )
                    if result.first() is None:
                        raise UserRuleLimit()
        except IntegrityError as error:
            if "uq_user_approval_rules_rule" in str(error):
                raise UserRuleConflict() from error
            raise
        return rule

    async def delete(self, user_id, rule_id):
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "DELETE FROM user_approval_rules "
                        "WHERE user_id = :user_id AND rule_id = :rule_id"
                    ),
                    {"user_id": user_id, "rule_id": rule_id},
                )
        return bool(result.rowcount)


def build_user_rule_source(
    coding: Any, session_factory: Callable[[], Awaitable[Any]]
) -> PostgresUserRuleStore | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다."""
    if not getattr(coding, "approval_user_rules", False):
        return None
    return PostgresUserRuleStore(session_factory, max_rules=coding.approval_user_rules_max)
