"""진행 추적 -- 손으로 나열한 목록이 아니라 이번 실행에서 읽는다 (G2-b).

고치기 전의 결함 셋:
  1. `total_steps` 가 항상 19 -- 분기로 절반을 건너뛰어도 그대로였다
  2. `workflow_nodes.index(node) - 1` 로 "이전 노드" 를 추정 -- 실행 순서가
     아니라 **목록 순서**라, 건너뛴 노드의 종료 시각이 기록됐다
  3. `estimate_remaining_time` 이 목록에 없는 노드에 0.0 을 돌려줬다 --
     설계된 그래프의 모든 노드가 그러므로 사용자는 매 단계 "남은 시간 0초"
     를 봤다. 이벤트가 안 나가는 것보다 나쁘다: 틀린 것을 안다고 믿는다.
"""

import pytest

from neos.workflow.events import estimate_remaining_time


def test_eta_counts_only_nodes_this_graph_can_still_reach() -> None:
    known = estimate_remaining_time("search_orchestrator", candidates=("fact_check",))
    wider = estimate_remaining_time(
        "search_orchestrator", candidates=("fact_check", "quality_validator")
    )
    assert known > 0
    assert wider > known


def test_eta_is_not_zero_for_a_node_absent_from_the_legacy_order() -> None:
    """설계된 그래프의 노드는 `WORKFLOW_NODE_ORDER` 에 없다. 옛 구현은
    `ValueError` 를 잡아 0.0 을 돌려줬다 -- '곧 끝남' 으로 읽히는 거짓말이다."""

    eta = estimate_remaining_time("a_designed_node", candidates=("fact_check",))
    assert eta > 0


def test_eta_of_an_empty_candidate_set_is_zero() -> None:
    """남은 노드가 정말 없으면 0 이 맞다 -- 위 두 테스트와 구별되는
    유일한 경우다."""

    assert estimate_remaining_time("fact_check", candidates=()) == 0.0


class _AsyncNoop:
    """`execute_workflow` 가 부르는 DB·캐시·메모리 협력자의 자리를 채운다.
    `None` 을 돌려주는 async 호출 하나면 충분하다."""

    async def __call__(self, *args, **kwargs):
        return None


class _RecordingHandler:
    """`on_node_start` 로 들어온 (노드, step, max_steps) 를 그대로 모은다."""

    def __init__(self) -> None:
        self.starts: list[tuple[str, int, int]] = []

    async def on_workflow_start(self, workflow_input): ...
    async def on_node_start(
        self, node_name, step, total_steps, step_name=None, estimated_remaining_s=None
    ):
        self.starts.append((node_name, step, total_steps))
    async def on_node_progress(self, node_name, message, progress=0): ...
    async def on_node_complete(self, node_name, result): ...
    async def on_workflow_complete(self, result): ...
    async def on_workflow_error(self, error, node_name=None): ...
    async def on_approval_request(self, pending_approvals, session_id): ...


@pytest.mark.asyncio
async def test_node_end_is_recorded_for_the_node_actually_seen_not_the_list_neighbour(
    monkeypatch,
) -> None:
    """🔴 **분기가 노드를 건너뛰는 실행에서 검증해야 한다.** 모든 노드를
    순서대로 지나는 그래프에서는 옛 코드와 새 코드가 똑같이 통과한다 --
    §8.1.2 가 적은 그 교훈(`after <= before` 가 양쪽 0 이라 공허하게 성립해
    버그를 되살려도 통과했다)이 여기 그대로 걸린다."""

    from neos.config import settings as settings_module
    from neos.workflow import events as events_module
    from neos.workflow.graph import MultiAgentWorkflow

    ended: list[str] = []
    monkeypatch.setattr(
        events_module, "record_node_end",
        lambda node, wf_id="": ended.append(node),
    )

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    # 실행이 `query_classifier` 다음에 `response_generator` 로 **건너뛴다**.
    # 옛 코드였다면 목록상 `response_generator` 의 앞 항목을 종료시켰다.
    async def _fake_stream(execution_graph, initial_state, config):
        for name in ("query_classifier", "response_generator"):
            yield {name: {"final_response": "ok"}}

    monkeypatch.setattr(workflow, "graph_astream_source", _fake_stream)

    # `execute_workflow` 를 부르려면 DB·캐시·메모리를 타는 여덟 곳을 막아야
    # 한다. 목록은 `tests/test_workflow_graph.py:338-348` 이 확립한 것을
    # 그대로 쓴다 -- 같은 것을 두 방식으로 테스트하면 다음 사람이 어느 쪽이
    # 정본인지 모른다.
    from neos.workflow import graph as workflow_graph_module

    monkeypatch.setattr(workflow_graph_module.settings, "SMART_CACHE_ENABLED", False)
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

    handler = _RecordingHandler()
    await workflow.execute_workflow(
        {"query": "안녕", "session_id": "s-skip", "user_id": "u1", "bypass_cache": True},
        event_handler=handler,
        use_checkpointer=False,
    )

    assert [name for name, _step, _max in handler.starts] == [
        "query_classifier",
        "response_generator",
    ]
    assert ended == ["query_classifier", "response_generator"]
    # 건너뛴 노드는 하나도 종료 기록을 받지 않았다.
    assert "search_orchestrator" not in ended


class _FakeClock:
    """`events.time` 자리에 들어가 `monotonic()` 을 스트림이 정한 값으로
    돌려준다. 실제 시간에 기대면 이 테스트는 밀리초 경합이 된다."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_a_chunk_without_node_keys_does_not_close_the_pending_node(
    monkeypatch,
) -> None:
    """노드 키가 없는 chunk(`__interrupt__` 등)는 대기 중인 종료를 건드리면
    안 된다.

    🔴 **종료가 "기록됐는가" 만 보면 이 결함이 안 잡힌다.** 옛 코드도 신호
    chunk 에서 종료를 부르긴 했다 -- 문제는 **언제** 불렀는가다. 노드 하나의
    측정 구간은 그 노드의 chunk 부터 다음 노드의 chunk 까지인데, 중간에 낀
    신호 chunk 가 그 구간을 그 자리에서 끊어 **~0초 표본**을 ETA 히스토리에
    밀어 넣는다. `get_estimated_duration` 은 표본 중앙값을 쓰므로 그 노드의
    남은 시간 추정이 0 쪽으로 끌려간다 -- 이 브랜치가 걷어낸 "남은 시간
    0초" 거짓말과 같은 종류의 조용한 손실이다. 그래서 단언은 종료의
    **존재**와 **길이** 둘 다를 본다.
    """

    from neos.config import settings as settings_module
    from neos.workflow import events as events_module
    from neos.workflow import graph as workflow_graph_module
    from neos.workflow.graph import MultiAgentWorkflow

    clock = _FakeClock()
    monkeypatch.setattr(events_module, "time", clock)

    real_end = events_module.record_node_end
    ended: list[tuple[str, float | None]] = []

    def _spy_end(node, wf_id=""):
        duration = real_end(node, wf_id)
        ended.append((node, duration))
        return duration

    monkeypatch.setattr(events_module, "record_node_end", _spy_end)

    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", False
    )
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    async def _fake_stream(execution_graph, initial_state, config):
        # 시계를 **yield 직후**에 옮긴다 -- 소비자는 yield 된 chunk 를 그
        # 시점의 시계로 처리하고, 다음 chunk 를 받을 때 이 값을 본다.
        clock.now = 0.0
        yield {"query_classifier": {"final_response": None}}
        clock.now = 0.01  # 노드가 끝나자마자 도착하는 신호 chunk
        yield {"__interrupt__": ()}
        clock.now = 10.0  # 다음 노드는 10초 뒤에 끝났다
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
    monkeypatch.setattr(workflow_graph_module.settings, "SMART_CACHE_ENABLED", False)
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

    handler = _RecordingHandler()
    await workflow.execute_workflow(
        {
            "query": "안녕",
            "session_id": "s-interrupt",
            "user_id": "u1",
            "bypass_cache": True,
        },
        event_handler=handler,
        use_checkpointer=False,
    )

    # 신호 chunk 는 진행 단계로도 세지 않는다.
    assert [name for name, _step, _max in handler.starts] == [
        "query_classifier",
        "response_generator",
    ]
    # 실제 노드 둘 다 종료를 받았고, 각각 정확히 한 번씩이다.
    assert [name for name, _duration in ended] == [
        "query_classifier",
        "response_generator",
    ]
    # 그리고 구간이 신호 chunk 에서 잘리지 않았다 -- 0.01 이면 잘린 것이다.
    assert dict(ended)["query_classifier"] == pytest.approx(10.0)
