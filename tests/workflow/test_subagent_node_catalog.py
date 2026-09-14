"""트랙 I GS3 -- 설계자가 보는 것은 플래그가 꺼져 있으면 **바이트 단위로** 그대로다.

설계자 통과율(M-0)은 설계자에게 가는 문자열이 바뀌지 않았다는 전제 위에 선다. 그래서
"템플릿을 카탈로그에 넣었다" 는 변경은 두 가지를 증명해야 한다:

1. 꺼져 있으면 렌더된 프롬프트가 `NODE_CONTRACTS` 만으로 렌더한 것과 **같은 바이트**다.
2. 켜져 있으면 달라지는 것은 템플릿 카탈로그 줄 **하나**뿐이다.

프롬프트 파일 자체(v2)도 고정한다 -- 문구 변경(v3)은 M-1 사전 등록과 함께 온다.
"""

import hashlib
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

import neos.workflow.graph as graph_module
from neos.config import settings as settings_module
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.graph_designer import DesignRequest
from neos.workflow.graph_designer_llm import LlmGraphDesigner
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology

_PROMPT = Path(graph_module.__file__).parent / "prompts" / "graph_design.md"
_V2_SHA256_16 = "7af3ebdd3e0a6bc2"
_QUERY = "이 함수를 누가 부르나"


class _Designer:
    async def design(self, request):
        return GraphTopology(
            nodes=("direct_response",),
            edges=(("__start__", "direct_response"), ("direct_response", "__end__")),
            initial_writes=GRAPH_ENTRY_WRITES,
        )


def _render(request: DesignRequest) -> bytes:
    designer = LlmGraphDesigner(model=object(), prompt_path=_PROMPT, timeout_sec=1.0)
    return designer._render_prompt(request).encode("utf-8")


async def _captured_request(monkeypatch) -> DesignRequest:
    seen = {}
    original = graph_module.design_graph_or_fallback

    async def _spy(**kwargs):
        seen["request"] = kwargs["request"]
        return await original(**kwargs)

    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr(graph_module, "design_graph_or_fallback", _spy)
    monkeypatch.setattr("neos.workflow.graph.get_checkpointer", _fake_get_checkpointer)
    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _Designer())
    await workflow._ensure_graph_initialized(use_checkpointer=True)
    await workflow._resolve_execution_graph(
        user_input={"query": _QUERY, "session_id": "s-catalog"},
        use_checkpointer=True,
        span=None,
    )
    return seen["request"]


def _enable(monkeypatch, *, subagent: bool) -> None:
    config = settings_module.settings.config.workflow
    monkeypatch.setattr(config, "graph_design_enabled", True)
    if subagent:
        monkeypatch.setattr(config, "subagent_budget_micros", 10**9)
        monkeypatch.setattr(config, "subagent_nodes_enabled", True)
    monkeypatch.setattr(settings_module.settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(
        "neos.workflow.subagent_nodes._default_model_for_role",
        lambda provider, role: "claude-sonnet-5",
    )


def test_the_designer_prompt_file_is_still_v2() -> None:
    assert hashlib.sha256(_PROMPT.read_bytes()).hexdigest()[:16] == _V2_SHA256_16


@pytest.mark.asyncio
async def test_with_the_flag_off_the_rendered_prompt_is_byte_identical(monkeypatch) -> None:
    _enable(monkeypatch, subagent=False)
    request = await _captured_request(monkeypatch)
    reference = DesignRequest(
        query=_QUERY,
        catalog=tuple(NODE_CONTRACTS.values()),
        budget=settings_module.settings.config.workflow.graph_design_budget_hint,
    )
    assert request.catalog == reference.catalog
    assert _render(request) == _render(reference)
    assert b"explore_web" not in _render(request)


@pytest.mark.asyncio
async def test_with_the_flag_on_the_only_difference_is_the_template_catalog_line(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    request = await _captured_request(monkeypatch)
    reference = DesignRequest(
        query=_QUERY,
        catalog=tuple(NODE_CONTRACTS.values()),
        budget=settings_module.settings.config.workflow.graph_design_budget_hint,
    )
    assert request.catalog[: len(NODE_CONTRACTS)] == reference.catalog
    on_lines = _render(request).decode("utf-8").splitlines()
    off_lines = _render(reference).decode("utf-8").splitlines()
    added = [line for line in on_lines if line not in off_lines]
    assert added == [
        "- explore_web: reads=[original_query, subagent_runs, subagent_scope] "
        "writes=[search_results, subagent_reports, subagent_runs] requires=[original_query]"
    ]
    assert [line for line in on_lines if line not in added] == off_lines
