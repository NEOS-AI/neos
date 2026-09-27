"""설계 그래프 서브에이전트 노드의 진행이 챗 SSE 에 닿는가.

이전에는 `graph_subagent_step` / `graph_subagent_folded` 가 설계 원장(구조적 로그 +
OTel span)으로만 갔다. 챗 화면에는 일반 `node_started/completed` 만 보였고, 자식이
몇 걸음 갔는지·끝났는지·실패했는지는 보이지 않았다.

지키는 것:
- 자식 보고서 **본문은 싣지 않는다.** 본문은 unverified 검색 결과로만 간다
  (`subagent_nodes.py`, 트랙 I). 화면에 올리면 미검증 텍스트가 조사 결과처럼 보인다.
- 스트림 큐가 차도 그래프를 멈추지 않는다 -- 진행 표시는 버려도 되는 정보다.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from neos.api.adapters.stream_adapter import graph_subagent_event_from
from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback
from neos.workflow.events import forward_graph_subagent_event

pytestmark = pytest.mark.no_db

_FOLDED = {
    "node": "explore_web",
    "label": "Investigating with a subagent",
    "run_id": "sa_1",
    "status": "completed",
    "exit_reason": "completed",
    "error_code": None,
    "truncated": False,
    "steps": 3,
    "turn_count": 2,
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_micros": 1200,
    "unverified": True,
    # 섞여 들어와서는 안 되는 것 -- 필터가 걸러야 한다.
    "summary": "SECRET REPORT BODY",
}


@pytest.mark.asyncio
async def test_the_stream_callback_enqueues_without_blocking():
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    callback = WorkflowStreamCallback(session_id="c1", event_queue=queue)

    callback.on_graph_subagent_event("graph_subagent_step", {"node": "explore_web", "steps": 1})

    event = queue.get_nowait()
    assert event.event == "graph_subagent"
    assert event.node_name == "explore_web"
    assert event.data["kind"] == "graph_subagent_step"


@pytest.mark.asyncio
async def test_a_full_queue_drops_progress_instead_of_stalling_the_graph():
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("occupied")
    callback = WorkflowStreamCallback(session_id="c1", event_queue=queue)

    callback.on_graph_subagent_event("graph_subagent_step", {"node": "explore_web"})

    assert queue.qsize() == 1


def test_forwarding_tolerates_handlers_without_the_hook():
    class Legacy:
        pass

    class Broken:
        def on_graph_subagent_event(self, kind, payload):
            raise RuntimeError("boom")

    forward_graph_subagent_event(None, "graph_subagent_step", {})
    forward_graph_subagent_event(Legacy(), "graph_subagent_step", {})
    forward_graph_subagent_event(Broken(), "graph_subagent_step", {})


def test_the_sse_event_carries_status_but_never_the_report_body():
    event = graph_subagent_event_from({"kind": "graph_subagent_folded", **_FOLDED})

    wire = json.loads(event.model_dump_json())
    assert wire["type"] == "neos:graph_subagent"
    assert wire["phase"] == "folded"
    assert wire["node"] == "explore_web"
    assert wire["label"] == "Investigating with a subagent"
    assert wire["status"] == "completed"
    assert wire["steps"] == 3
    assert "SECRET REPORT BODY" not in json.dumps(wire)
    assert "summary" not in wire


def test_a_step_event_reports_progress_against_its_cap():
    event = graph_subagent_event_from(
        {
            "kind": "graph_subagent_step",
            "node": "explore_web",
            "label": "Investigating with a subagent",
            "run_id": "sa_1",
            "step_kind": "continuing",
            "steps": 2,
            "max_advances": 9,
        }
    )

    assert event.phase == "step"
    assert event.status == "running"
    assert (event.steps, event.max_steps) == (2, 9)
