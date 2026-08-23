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


def test_static_nodes_are_alphabetical_and_therefore_not_execution_order() -> None:
    """`nodes` 는 `static_topology` 의 `tuple(sorted(...))` 라 **알파벳순**이다.
    순서에 의미가 있다고 읽으면 이 브랜치가 걷어낸 버그가 되살아난다 --
    옛 코드는 목록 인덱스로 "직전 노드" 를 골라 이 run 이 건너뛴 노드의
    종료 시각을 기록했다. 실행 순서라면 `refinement_checker` 가 맨 앞이고
    `response_generator` 가 맨 뒤여야 하는데, 알파벳순이라 그렇지 않다."""

    nodes = static_execution_graph(
        compiled=object(), flags=dict.fromkeys(STATIC_FLAG_KEYS, True)
    ).nodes

    assert list(nodes) == sorted(nodes)
    # 알파벳순이 실행 순서와 **실제로 다르다**는 증거. 이게 없으면 두 순서가
    # 우연히 같은 그래프에서도 위 단언이 통과한다.
    assert nodes.index("response_generator") < nodes.index("search_orchestrator")


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


class _AsyncNoop:
    """`execute_workflow` 가 부르는 DB·캐시·메모리 협력자의 자리를 채운다."""

    async def __call__(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_a_static_run_emits_its_topology_hash_and_source(
    monkeypatch, caplog
) -> None:
    """🔴 **필드가 아니라 배출을 본다.** `ExecutionGraph.topology_hash` 를
    단언하는 테스트는 이미 여럿 있고 전부 초록이었지만, 그 값이 span 이나
    로그로 **나가지 않으면** 정적 run 은 여전히 해시 없는 run 이다 -- 설계된
    run 과 조인할 상대가 없다는 G2-e 의 문제가 그대로 남는다. 그래서 이
    테스트는 `execute_workflow` 를 끝까지 돌리고 목적지 두 곳(span 속성 ·
    구조적 로그)에 값이 실제로 도착했는지만 본다.

    `graph_design_enabled` 는 기본값 `False` 다 -- 즉 이 단언은 **꺼진
    경로**를 겨눈다. 폴백 run 만 무언가를 남기고 정적 run 은 아무것도 남기지
    않는 것이 정확히 G2-e 가 못 고친 상태였다.
    """

    import logging

    from neos.config import settings as settings_module
    from neos.workflow import graph as graph_module
    from neos.workflow.graph import MultiAgentWorkflow

    attributes: list[dict] = []
    real_set = graph_module.set_span_attributes

    def _spy(span, attrs):
        attributes.append(dict(attrs))
        return real_set(span, attrs)

    monkeypatch.setattr(graph_module, "set_span_attributes", _spy)

    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", False
    )
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    async def _fake_stream(execution_graph, initial_state, config):
        # `_create_workflow_result` 가 직접 인덱싱하는 키 다섯을 채운다 --
        # 빠지면 실행이 except 로 떨어져 이 테스트가 "성공한 run" 이 아니라
        # "실패한 run" 의 배출을 보게 된다.
        yield {
            "response_generator": {
                "final_response": "ok",
                "response_metadata": {},
                "execution_time_ms": 1,
                "errors": [],
                "execution_steps": [],
            }
        }

    monkeypatch.setattr(workflow, "graph_astream_source", _fake_stream)
    monkeypatch.setattr(graph_module.settings, "SMART_CACHE_ENABLED", False)
    for name in (
        "_check_cached_response",
        "_load_memory_context",
        "_apply_research_template",
        "_record_session_start",
        "_save_episode_memory",
        "_record_session_complete",
        "_cache_workflow_result",
        "_auto_save_dataset",
    ):
        monkeypatch.setattr(workflow, name, _AsyncNoop())

    expected = static_execution_graph(
        compiled=object(), flags=current_static_flags()
    ).topology_hash

    with caplog.at_level(logging.INFO, logger="neos.workflow.graph"):
        await workflow.execute_workflow(
            {
                "query": "안녕",
                "session_id": "s-hash",
                "user_id": "u1",
                "bypass_cache": True,
            },
            use_checkpointer=False,
        )

    emitted = {key: value for attrs in attributes for key, value in attrs.items()}
    assert emitted["graph.topology_hash"] == expected
    assert emitted["graph.source"] == "static"

    logged = [
        record.getMessage()
        for record in caplog.records
        if record.name == "neos.workflow.graph"
    ]
    assert any(expected in message and "graph.source=static" in message for message in logged)


@pytest.mark.asyncio
async def test_a_failure_while_resolving_the_graph_takes_the_normal_error_path(
    monkeypatch,
) -> None:
    """`_resolve_execution_graph` 는 정적 경로에서도 `static_topology` 를 거쳐
    `inspect.getsource` + `ast.parse` 를 돈다 -- `_StaticExtractionError` 나
    `OSError` 가 여기서 나올 수 있다. 이 호출이 `try` 밖에 있으면 그 예외가
    핸들러 없이 그대로 밖으로 나가 `on_workflow_error` 도 에러 결과도 없다.
    그것도 **플래그가 꺼진 경로**에서 그렇다 -- 꺼진 run 이 이전과 구별되지
    않아야 한다는 전제와 어긋난다."""

    from neos.config import settings as settings_module
    from neos.workflow import graph as graph_module
    from neos.workflow.graph import MultiAgentWorkflow

    errors: list[Exception] = []

    class _Handler:
        async def on_workflow_start(self, workflow_input): ...
        async def on_node_start(self, *args, **kwargs): ...
        async def on_node_progress(self, *args, **kwargs): ...
        async def on_node_complete(self, *args, **kwargs): ...
        async def on_workflow_complete(self, result): ...
        async def on_workflow_error(self, error, node_name=None):
            errors.append(error)
        async def on_approval_request(self, pending_approvals, session_id): ...

    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", False
    )

    async def _explode(**kwargs):
        raise OSError("could not get source code")

    monkeypatch.setattr(workflow, "_resolve_execution_graph", _explode)
    monkeypatch.setattr(graph_module.settings, "SMART_CACHE_ENABLED", False)
    for name in (
        "_check_cached_response",
        "_load_memory_context",
        "_apply_research_template",
        "_record_session_start",
        "_record_session_failed",
    ):
        monkeypatch.setattr(workflow, name, _AsyncNoop())

    result = await workflow.execute_workflow(
        {
            "query": "안녕",
            "session_id": "s-boom",
            "user_id": "u1",
            "bypass_cache": True,
        },
        event_handler=_Handler(),
        use_checkpointer=False,
    )

    assert [type(error) for error in errors] == [OSError]
    assert result["success"] is False
