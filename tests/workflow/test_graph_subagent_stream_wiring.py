"""설계 그래프의 서브에이전트 호스트가 걸음·폴드를 챗 스트림 핸들러까지 넘기는가.

`_build_subagent_host` 의 `emit` 은 원래 설계 원장(로그 + span)에만 썼다. 이제
`execute_workflow` 가 받은 이벤트 핸들러에도 넘긴다 -- 원장 기록은 그대로다.
"""

from __future__ import annotations

import pytest

from neos.workflow import subagent_nodes
from neos.workflow.graph import MultiAgentWorkflow

pytestmark = pytest.mark.no_db


class _Recorder:
    def __init__(self):
        self.events = []

    def on_graph_subagent_event(self, kind, payload):
        self.events.append((kind, payload))


def _captured_emit(monkeypatch):
    captured = {}

    def fake_factory(*, provider, max_active, emit):
        captured["emit"] = emit
        return object()

    monkeypatch.setattr(subagent_nodes, "build_workflow_subagent_host", fake_factory)
    return captured


def test_host_events_reach_the_stream_handler_and_the_ledger(monkeypatch):
    captured = _captured_emit(monkeypatch)
    workflow = MultiAgentWorkflow()
    recorded = []
    monkeypatch.setattr(
        workflow, "_record_design_events", lambda events, span: recorded.extend(events)
    )
    handler = _Recorder()

    workflow._build_subagent_host(None, event_handler=handler)
    captured["emit"]("graph_subagent_step", {"node": "explore_web", "steps": 1})

    assert handler.events == [("graph_subagent_step", {"node": "explore_web", "steps": 1})]
    assert [event.kind for event in recorded] == ["graph_subagent_step"]


def test_without_a_handler_only_the_ledger_is_written(monkeypatch):
    captured = _captured_emit(monkeypatch)
    workflow = MultiAgentWorkflow()
    recorded = []
    monkeypatch.setattr(
        workflow, "_record_design_events", lambda events, span: recorded.extend(events)
    )

    workflow._build_subagent_host(None)
    captured["emit"]("graph_subagent_folded", {"node": "explore_web"})

    assert [event.kind for event in recorded] == ["graph_subagent_folded"]
