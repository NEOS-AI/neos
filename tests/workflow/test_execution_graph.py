"""`ExecutionGraph` -- 이번 호출이 실제로 쓰는 그래프를 값 하나로 들고 다닌다.

`MultiAgentWorkflow` 는 모듈 레벨 싱글턴이고(`graph.py:3398`) 요청들이
공유한다. 그래서 이 값은 **인스턴스 속성이 아니라 호출 스코프**로만 흐른다
(`graph.py:376-383` 의 요구).
"""

import dataclasses

import pytest

from neos.workflow.execution_graph import (
    STATIC_FLAG_KEYS,
    ExecutionGraph,
    current_static_flags,
    static_execution_graph,
)


def test_execution_graph_is_frozen_so_a_request_cannot_mutate_anothers_view() -> None:
    graph = ExecutionGraph(
        compiled=object(), nodes=("a",), topology_hash="deadbeefdeadbeef", source="static"
    )
    assert dataclasses.is_dataclass(graph)
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.source = "designed"  # type: ignore[misc]


def test_current_static_flags_covers_every_flag_the_extractor_knows() -> None:
    """`static_topology` 는 알 수 없는 키가 오면 즉시 실패하고, **빠진** 키는
    기본값('전부 켬')으로 조용히 채운다. 후자가 위험하다 -- 실제로 꺼진
    기능이 켜진 것으로 계산되면 해시가 그 run 의 그래프를 서술하지 않는다.
    그래서 매핑 전체를 덮는지 길이로 단언한다."""

    flags = current_static_flags()
    assert set(flags) == set(STATIC_FLAG_KEYS)
    assert len(flags) == 5


def test_static_execution_graph_reports_static_source_and_a_stable_hash() -> None:
    compiled = object()
    flags = dict.fromkeys(STATIC_FLAG_KEYS, True)

    first = static_execution_graph(compiled=compiled, flags=flags)
    second = static_execution_graph(compiled=compiled, flags=flags)

    assert first.source == "static"
    assert first.compiled is compiled
    assert first.topology_hash == second.topology_hash
    assert len(first.topology_hash) == 16
    # 정적 그래프의 노드는 실제 배선에서 나온다 -- 손으로 나열한 목록이 아니다.
    assert "response_generator" in first.nodes


def test_a_disabled_flag_changes_the_static_hash() -> None:
    """플래그가 그래프를 바꾸면 해시도 바뀌어야 한다. 안 바뀌면 서로 다른
    배포의 run 이 같은 해시로 조인돼 비교가 거짓이 된다."""

    all_on = dict.fromkeys(STATIC_FLAG_KEYS, True)
    recursive_off = {**all_on, "recursive": False}

    assert (
        static_execution_graph(compiled=object(), flags=all_on).topology_hash
        != static_execution_graph(compiled=object(), flags=recursive_off).topology_hash
    )


@pytest.mark.asyncio
async def test_resolve_execution_graph_returns_the_static_graph_when_design_is_off() -> None:
    """플래그가 꺼져 있으면(기본값) 설계 경로를 아예 타지 않고, 컴파일된
    정적 그래프가 그대로 실려 나온다."""

    from neos.config import settings as settings_module
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "안녕", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert resolved.compiled is workflow.graph
    assert resolved.nodes


@pytest.mark.asyncio
async def test_resolving_the_execution_graph_leaves_no_per_call_state_on_the_shared_instance() -> None:
    """G2-c 의 핵심 가드. `MultiAgentWorkflow` 는 모듈 레벨 싱글턴이라 요청들이
    공유한다(`graph.py:376-383`) -- `_resolve_execution_graph` 의 반환값이
    인스턴스나 클래스 어디에든 남으면 나중 요청이 앞 요청의 그래프를
    실행한다. 이 테스트는 "존재 여부"(속성 이름의 집합)가 아니라 "정확히
    그 객체·그 내용인가"를 본다 -- `self.graph = 설계된_그래프` 처럼 **기존**
    속성에 다른 값을 덮어쓰는 리크는 이름 집합만 보는 검사로는 안 잡힌다.

    이름에 "concurrent"를 쓰지 않는다: 이미 초기화된 경로에서
    `_ensure_graph_initialized` 는 실제로 양보하는 await 지점이 없으므로,
    `asyncio.gather` 로 감싸도 두 코루틴은 사실상 순차 실행된다 -- 이
    경로에서는 진짜 인터리빙을 재현할 수 없다. 그래서 이름과 문서를
    실제로 검증하는 성질(공유 인스턴스에 흔적이 남지 않는다)에 맞춘다.
    """

    import asyncio as _asyncio

    from neos.config import settings as settings_module
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    # 넷 다 "호출 전" 스냅샷 -- 이후 비교는 전부 이 스냅샷 대비다.
    graph_before = workflow.graph
    checkpointer_cache_before = dict(workflow._graphs_by_checkpointer)
    instance_attrs_before = set(vars(workflow))
    class_attrs_before = set(vars(MultiAgentWorkflow))

    first, second = await _asyncio.gather(
        workflow._resolve_execution_graph(
            user_input={"query": "q1", "session_id": "s1"},
            use_checkpointer=False,
            span=None,
        ),
        workflow._resolve_execution_graph(
            user_input={"query": "q2", "session_id": "s2"},
            use_checkpointer=False,
            span=None,
        ),
    )

    assert first.source == "static"
    assert second.source == "static"

    # 동일 객체인가(존재가 아니라) -- `self.graph = r.compiled` 형태의 리크를 잡는다.
    assert workflow.graph is graph_before
    # 키 집합이 아니라 내용 전체 -- `_graphs_by_checkpointer[새_키] = ...` 형태의
    # 리크를 잡는다. `setdefault` 처럼 키가 이미 있으면 아무것도 안 남기는
    # 경로와, 새 키를 얹는 경로를 구별한다.
    assert dict(workflow._graphs_by_checkpointer) == checkpointer_cache_before
    # 인스턴스에 새 속성 이름이 안 생겼는가.
    assert set(vars(workflow)) == instance_attrs_before
    # 클래스에도 새 속성 이름이 안 생겼는가 -- `MultiAgentWorkflow._designed = r`
    # 처럼 인스턴스가 아니라 클래스에 얹는 리크는 `vars(workflow)` 로는 안 보인다.
    assert set(vars(MultiAgentWorkflow)) == class_attrs_before
