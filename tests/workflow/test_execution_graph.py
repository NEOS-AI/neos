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
