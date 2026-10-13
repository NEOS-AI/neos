"""네이티브 러너 -- 배선 표를 해석해 노드를 차례로 돌린다 (spec 2026-10-13 §4.2).

- 한 걸음: 핸들러 → 갱신을 `apply_update`(리듀서 의미론)로 접기 → `{node: update}` chunk →
  `Edge` 또는 `Branch` 라우터로 다음 노드. `END` 면 멈춘다
- chunk 모양은 LangGraph updates 모드와 같다 -- `execute_workflow` 의 진행 추적이 그대로 읽는다
- `interrupt_before` 노드에 닿으면 **실행 전에** 멈춘다. 예외가 아니라 결과(`Interrupted`)이고,
  LangGraph 와 같은 `{"__interrupt__": (next_node,)}` chunk 를 마지막으로 낸다
- `start_at` 은 승인 재개용이다 -- 그 노드가 게이트여도 첫 걸음은 실행한다(사람이 이미 결정했다)
- 순차만 돈다(spec §4.10). 한 노드에서 무조건 출구가 둘이면 만들 때 거절한다
- 저장하지 않는다 -- 저장은 턴 경계(`runtime/turns.py`)가 한다
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neos.workflow.runtime.node_updates import apply_update
from neos.workflow.topology import END, START
from neos.workflow.wiring import Wiring, WiringError, resolve_ref

INTERRUPT_KEY = "__interrupt__"


@dataclass(frozen=True)
class Completed:
    state: dict[str, Any]


@dataclass(frozen=True)
class Interrupted:
    next_node: str
    state: dict[str, Any]


class StepLimitExceeded(RuntimeError):
    pass


class WorkflowRunner:
    def __init__(
        self,
        wiring: Wiring,
        owner: Any,
        *,
        step_limit: int,
        interrupt_before: Sequence[str] = (),
        wrap: Callable[[str, Callable], Callable] | None = None,
    ) -> None:
        self._step_limit = step_limit
        self._interrupt_before = frozenset(interrupt_before)
        self._handlers: dict[str, Callable] = {}
        for spec in wiring.nodes:
            handler = resolve_ref(owner, spec.handler)
            self._handlers[spec.name] = wrap(spec.name, handler) if wrap and spec.wrapped else handler
        self._edges: dict[str, str] = {}
        for edge in wiring.edges:
            if edge.source in self._edges:
                raise WiringError(
                    f"{edge.source}: 무조건 출구가 둘 이상이다(parallel) -- 네이티브 러너는 순차만 돈다"
                )
            self._edges[edge.source] = edge.target
        self._branches: dict[str, tuple[Callable, dict[str, str]]] = {}
        for branch in wiring.branches:
            if branch.source in self._edges:
                raise WiringError(f"{branch.source}: 무조건 출구와 분기가 함께 있다(parallel)")
            self._branches[branch.source] = (
                resolve_ref(owner, branch.router),
                wiring.path_map(branch),
            )
        if START not in self._edges:
            raise WiringError("START 에서 나가는 엣지가 없다")
        self._entry = self._edges[START]
        self._outcome: Completed | Interrupted | None = None

    @property
    def outcome(self) -> Completed | Interrupted | None:
        return self._outcome

    async def stream(
        self, state: Mapping[str, Any], *, start_at: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        self._outcome = None
        current = dict(state)
        node = start_at or self._entry
        steps = 0
        while node != END:
            resuming_here = start_at is not None and steps == 0
            if node in self._interrupt_before and not resuming_here:
                self._outcome = Interrupted(next_node=node, state=current)
                yield {INTERRUPT_KEY: (node,)}
                return
            steps += 1
            if steps > self._step_limit:
                raise StepLimitExceeded(f"걸음 상한 {self._step_limit} 을 넘었다 (마지막 노드 {node})")
            handler = self._handlers.get(node)
            if handler is None:
                raise WiringError(f"켜지지 않은 노드로 갔다: {node}")
            result = handler(current)
            if inspect.isawaitable(result):
                result = await result
            update = dict(result or {})
            current = apply_update(current, update)
            yield {node: update}
            node = self._next(node, current)
        self._outcome = Completed(state=current)

    def _next(self, node: str, state: Mapping[str, Any]) -> str:
        if node in self._branches:
            router, path_map = self._branches[node]
            label = router(state)
            if label not in path_map:
                raise WiringError(f"{node}: 라우터가 경로 표에 없는 라벨을 냈다: {label!r}")
            return path_map[label]
        if node in self._edges:
            return self._edges[node]
        raise WiringError(f"{node}: 출구가 없다")
