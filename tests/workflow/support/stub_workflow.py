"""스텁 노드로 **진짜** 정적 그래프를 돌리는 하네스 (spec 2026-10-13 §7.1).

노드 핸들러와 라우터만 인스턴스 속성으로 바꾸고, 배선·조립·`execute_workflow` 는
진짜를 쓴다. 그래서 같은 계약 테스트가 런타임을 갈아도 그대로 돈다(Plan 2 가
`runtime` 파라미터를 더한다).

라우터는 메서드 이름으로 고른다 -- `_should_continue_after_approval` 처럼 두 분기가
같은 라우터를 쓰기 때문이다. 계획에 없는 라우터가 불리면 실패한다: 기본 라벨을
추측하면 재생성 사이클 같은 루프로 조용히 빠진다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from neos.workflow import graph as graph_module
from neos.workflow.wiring import FLAG_ATTR_TO_KEY, resolve_wiring

NodeFn = Callable[[dict], Mapping[str, Any] | None]

FLAGS_OFF: dict[str, bool] = dict.fromkeys(FLAG_ATTR_TO_KEY.values(), False)

# 정제·맥락·셀렉터를 skip 으로 지나 직접 응답 → 응답 생성 → 하네스 → 끝.
SKIP_PATH_ROUTES: dict[str, str] = {
    "_should_refine_or_continue": "skip_refinement",
    "_should_process_context": "skip_context",
    "_route_after_skill_tool_selector": "skip_orchestrators",
    # 하네스 라우터는 end 로 고정한다: 이 스텁들은 게이트 복구에 들어가지 않는다.
    "_route_after_research_harness": "end",
}

_SIDE_EFFECTS = (
    "_check_cached_response",
    "_load_memory_context",
    "_apply_research_template",
    "_record_session_start",
    "_save_episode_memory",
    "_record_session_complete",
    "_record_session_harness_blocked",
    "_record_session_failed",
    "_cache_workflow_result",
    "_auto_save_dataset",
)


class _AsyncNoop:
    async def __call__(self, *args, **kwargs):
        return None


class UnplannedRoute(AssertionError):
    pass


@dataclass
class StubPlan:
    nodes: Mapping[str, NodeFn] = field(default_factory=dict)
    routes: Mapping[str, str] = field(default_factory=dict)


class RecordingHandler:
    def __init__(self) -> None:
        self.starts: list[tuple[str, int, int]] = []
        self.approvals: list[list] = []
        self.errors: list = []

    async def on_workflow_start(self, workflow_input): ...

    async def on_node_start(
        self, node_name, step, total_steps, step_name=None, estimated_remaining_s=None
    ):
        self.starts.append((node_name, step, total_steps))

    async def on_node_progress(self, node_name, message, progress=0): ...

    async def on_node_complete(self, node_name, result): ...

    async def on_workflow_complete(self, result): ...

    async def on_workflow_error(self, error, node_name=None):
        self.errors.append(error)

    async def on_approval_request(self, pending_approvals, session_id):
        self.approvals.append(list(pending_approvals))


def _as_node(fn: NodeFn | None):
    async def node(state):
        if fn is None:
            return {}
        result = fn(state)
        return dict(result) if result is not None else None

    return node


def _as_router(router: str, label: str | None):
    def route(state):
        if label is None:
            raise UnplannedRoute(f"계획에 없는 라우터가 불렸다: {router}")
        return label

    return route


def stub_workflow(
    monkeypatch,
    plan: StubPlan,
    *,
    flags: Mapping[str, bool] = FLAGS_OFF,
    checkpointer: Any = None,
    node_update_policy: str = "report",
    runtime: str = "langgraph",
):
    """`node_update_policy` 기본값이 report 인 이유: 스텁은 계약 목록을 시험하지 않는다.
    테스트 세션이 raise 를 걸어도(Plan 1 Task 7) 스텁이 계약 밖 키를 써서 실패하면
    시험하려던 것(결과 계약·누적·승인)이 아니라 스텁 모양 때문에 깨진다. 정책 자체는
    `tests/workflow/runtime/test_node_updates.py` 가 시험한다. 이 설정은 Task 6 에서
    생긴다 -- 그 전에는 없는 필드라 건너뛴다(엄격한 설정 모델은 모르는 속성 대입을 거절한다).

    `runtime='native'` 면 메모리 세션·작업 저장소를 꽂는다. `workflow.native_stores` 로 꺼내 본다.
    네이티브도 Plan 3 까지는 `_ensure_graph_initialized` 로 정적 LangGraph 를 컴파일하므로,
    체크포인터를 넘기지 않으면 메모리 체크포인터를 쓴다 -- 실제 `get_checkpointer()` 가
    PostgreSQL 에 닿지 않게 한다."""
    settings = graph_module.settings
    for attr, key in FLAG_ATTR_TO_KEY.items():
        monkeypatch.setattr(settings, attr, bool(flags.get(key, False)))
    monkeypatch.setattr(settings.config.workflow, "graph_design_enabled", False)
    monkeypatch.setattr(settings.config.workflow, "runtime", runtime)
    native_stores = None
    if runtime == "native":
        from neos.workflow.runtime import select
        from neos.workflow.runtime.sessions import InMemorySessionStore
        from neos.workflow.runtime.turns import NativeTurns
        from neos.workflow.runtime.work import InMemoryWorkStore, WorkLifecycle

        sessions, lifecycle = InMemorySessionStore(), WorkLifecycle(InMemoryWorkStore())
        monkeypatch.setattr(select, "_turns", NativeTurns(sessions, lifecycle, max_carried_items=200))
        # 승인 서비스 싱글턴이 이전 테스트의 워크플로를 쥔 채 남지 않게 한다.
        monkeypatch.setattr(select, "_approvals", None)
        native_stores = (sessions, lifecycle)
        if checkpointer is None:
            checkpointer = memory_checkpointer()
    if hasattr(settings.config.workflow, "node_update_policy"):
        monkeypatch.setattr(settings.config.workflow, "node_update_policy", node_update_policy)
    monkeypatch.setattr(settings, "SMART_CACHE_ENABLED", False)
    if checkpointer is not None:

        async def _get_checkpointer():
            return checkpointer

        monkeypatch.setattr(graph_module, "get_checkpointer", _get_checkpointer)

    workflow = graph_module.MultiAgentWorkflow()
    for name in _SIDE_EFFECTS:
        if hasattr(workflow, name):
            monkeypatch.setattr(workflow, name, _AsyncNoop())

    wiring = resolve_wiring({key: bool(flags.get(key, False)) for key in FLAG_ATTR_TO_KEY.values()})
    for spec in wiring.nodes:
        monkeypatch.setattr(workflow, spec.handler, _as_node(plan.nodes.get(spec.name)))
    for branch in wiring.branches:
        monkeypatch.setattr(
            workflow, branch.router, _as_router(branch.router, plan.routes.get(branch.router))
        )
    workflow.native_stores = native_stores
    return workflow


def memory_checkpointer():
    """승인 게이트 시험용 MemorySaver. 상태의 `_event_handler`(런타임 주입 객체)는
    msgpack 으로 직렬화되지 않는다 -- 그 실패가 시험하려는 중단 의미론을 가린다.
    운영 PostgreSQL 체크포인터는 모르는 객체를 문자열로 바꾸고, Plan 2 의 코덱은
    `_` 키를 저장하지 않는다. 그래서 여기서는 pickle 폴백으로 직렬화만 통과시킨다."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return MemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))


def user_input(session_id: str = "s-contract", user_id: str = "u1", query: str = "안녕") -> dict:
    return {"query": query, "session_id": session_id, "user_id": user_id, "bypass_cache": True}
