"""노드 반환값을 "이번 노드의 갱신" 하나로 만든다 (spec 2026-10-13 §4.2, R5).

응답 생성기·하네스·오케스트레이터 등 여러 노드가 갱신분이 아니라 **전체 상태**를
돌려준다. LangGraph 는 그것을 갱신으로 받아 `operator.add` 필드에 리스트 전체를
다시 붙인다 -- 노드 셋짜리 프로브에서 `search_results` 가 네 배가 됐다. 서른 개
노드를 하나씩 고치는 대신 노드 경계 한 곳에서 정규화한다. LangGraph 어댑터와
Plan 2 의 네이티브 러너가 같은 함수를 쓴다.

규칙
- `_` 로 시작하는 런타임 주입 키는 갱신이 아니다
- 누적(`append`) 필드: 반환 리스트가 이전 값으로 시작하면 그 뒤만 새 항목이다.
  접두가 다르면(재정렬·중복 제거) 무엇이 새 것인지 모르므로 전부 새 항목으로 본다
  -- 지금 동작과 같고 나빠지지 않는다
- 그 밖의 필드: 이전 값과 같으면(동일 객체이거나 `==`) 갱신이 아니다. 비교가 예외를
  던지면 바뀐 것으로 본다
- 노드에는 상태의 **작업 사본**을 넘긴다 -- 제자리 변경(`append`)이 이전 값을 바꾸면
  변경이 보이지 않는다
- 계약의 `writes` 밖 키: `report` 는 기록만, `drop` 은 버림, `raise` 는 거절
"""

from __future__ import annotations

import functools
import inspect
import logging
import operator
import typing
from collections.abc import Callable, Mapping
from typing import Any, Literal

logger = logging.getLogger(__name__)

UpdatePolicy = Literal["report", "drop", "raise"]
_MISSING = object()


class NodeUpdateRejected(ValueError):
    def __init__(self, node: str, keys: tuple[str, ...]) -> None:
        super().__init__(f"노드 {node!r} 가 계약의 writes 밖 키를 썼다: {list(keys)}")
        self.node = node
        self.keys = keys


@functools.lru_cache(maxsize=1)
def reducer_kinds() -> dict[str, Literal["append", "merge"]]:
    """`AgentState` 의 `Annotated` 메타데이터에서 리듀서 종류를 읽는다 -- 표에 다시 적지 않는다."""
    from neos.workflow.state import AgentState

    kinds: dict[str, Literal["append", "merge"]] = {}
    for key, hint in typing.get_type_hints(AgentState, include_extras=True).items():
        while typing.get_origin(hint) in (typing.NotRequired, typing.Required):
            hint = typing.get_args(hint)[0]
        if typing.get_origin(hint) is not typing.Annotated:
            continue
        metadata = typing.get_args(hint)[1:]
        if operator.add in metadata:
            kinds[key] = "append"
        elif any(callable(item) for item in metadata):
            kinds[key] = "merge"
    return kinds


def working_copy(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.copy() if isinstance(value, (list, dict, set)) else value
        for key, value in state.items()
    }


def _same(left: Any, right: Any) -> bool:
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:  # noqa: BLE001 -- numpy 배열처럼 진릿값이 모호한 비교
        return False


def apply_update(state: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """갱신 하나를 상태에 병합한다 -- LangGraph 리듀서와 같은 의미론(spec 2026-10-13 §4.2).
    누적(append) 필드는 이어 붙이고, 병합(merge) 필드는 dict 를 합치고, 나머지는 교체한다."""
    kinds = reducer_kinds()
    merged = dict(state)
    for key, value in update.items():
        kind = kinds.get(key)
        if kind == "append":
            merged[key] = list(state.get(key) or []) + list(value or [])
        elif kind == "merge":
            merged[key] = {**(state.get(key) or {}), **(value or {})}
        else:
            merged[key] = value
    return merged


def _new_items(prior: Any, returned: Any) -> list:
    items = list(returned or [])
    old = list(prior or []) if prior is not _MISSING else []
    if old and len(items) >= len(old) and all(_same(a, b) for a, b in zip(items, old)):
        return items[len(old):]
    return items


def _count_rejected(node: str, key: str) -> None:
    try:
        from neos.observability.metrics import metrics

        metrics.workflow_update_rejected_total.labels(node=node, key=key).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 노드를 막지 않는다
        logger.debug("workflow_update_rejected_total unavailable", exc_info=True)


def normalize_update(
    node: str,
    before: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    *,
    writes: frozenset[str] | None,
    policy: UpdatePolicy,
) -> dict[str, Any]:
    if not result:
        return {}
    kinds = reducer_kinds()
    update: dict[str, Any] = {}
    for key, value in result.items():
        if key.startswith("_"):
            continue
        prior = before.get(key, _MISSING)
        if kinds.get(key) == "append":
            items = _new_items(prior, value)
            if items:
                update[key] = items
        elif prior is not _MISSING and _same(value, prior):
            continue
        else:
            update[key] = value

    if writes is None:
        return update
    outside = tuple(sorted(set(update) - writes))
    if not outside:
        return update
    if policy == "raise":
        raise NodeUpdateRejected(node, outside)
    for key in outside:
        _count_rejected(node, key)
    logger.warning("node %s wrote keys outside its contract: %s (policy=%s)", node, list(outside), policy)
    if policy == "drop":
        for key in outside:
            del update[key]
    return update


def wrap_node(node: str, handler: Callable, *, policy: UpdatePolicy) -> Callable:
    """계약이 있는 노드는 `writes` 로 검사하고, 없는 노드(서브에이전트 템플릿)는 정규화만 한다."""
    from neos.workflow.contracts import NODE_CONTRACTS

    contract = NODE_CONTRACTS.get(node)
    writes = frozenset(contract.writes) if contract is not None else None

    @functools.wraps(handler)
    async def run(state):
        result = handler(working_copy(state))
        if inspect.isawaitable(result):
            result = await result
        return normalize_update(node, state, result, writes=writes, policy=policy)

    return run
