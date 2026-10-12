"""公共実行器 -- 状態を知らない。グラフノードが状態を読み書きする (spec §2.1, §4)."""

from __future__ import annotations

import asyncio

import pytest

from neos.skills.base import SkillResult
from neos.skills.base.search_results import SKILL_EXECUTOR_VIA
from neos.skills.executor import SkillExecutionLimits, execute_skill_calls
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db

LIMITS = SkillExecutionLimits(timeout_seconds=1.0, max_results_per_skill=5, max_content_chars=4000)


class FakeSkill:
    def __init__(self, name: str) -> None:
        self.name = name

    def to_search_results(self, result: SkillResult) -> list[SearchResult]:
        return [
            SearchResult(source=self.name, title=title, content=content, url=f"https://{self.name}/{i}")
            for i, (title, content) in enumerate(result.data)
        ]


class FakeRegistry:
    def __init__(self, names) -> None:
        self._skills = {name: FakeSkill(name) for name in names}

    def get_skill(self, name):
        return self._skills.get(name)


class FakeRunner:
    def __init__(self, behaviours) -> None:
        self.behaviours = behaviours
        self.registry = FakeRegistry(behaviours)
        self.calls: list[tuple[str, dict]] = []

    async def execute_skill(self, name, params):
        self.calls.append((name, dict(params)))
        return await self.behaviours[name](params)


def _ok(*items):
    async def run(params):
        return SkillResult(success=True, data=list(items))

    return run


def _call(name, **params):
    return {"name": name, "params": params, "reason": ""}


async def test_stage_one_runs_concurrently() -> None:
    inflight = 0
    peak = 0

    async def tracked(params):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1
        return SkillResult(success=True, data=[("t", "c")])

    runner = FakeRunner({"arxiv": tracked, "pubmed": tracked})
    await execute_skill_calls([_call("arxiv", query="q"), _call("pubmed", query="q")], runner=runner, limits=LIMITS)
    assert peak == 2


async def test_one_timeout_does_not_block_the_others() -> None:
    async def slow(params):
        await asyncio.sleep(5)

    runner = FakeRunner({"arxiv": slow, "pubmed": _ok(("P", "body"))})
    limits = SkillExecutionLimits(timeout_seconds=0.05, max_results_per_skill=5, max_content_chars=4000)
    outcome = await execute_skill_calls([_call("arxiv", query="q"), _call("pubmed", query="q")], runner=runner, limits=limits)
    assert [r.title for r in outcome.results] == ["P"]
    assert {s.skill: s.reason_code for s in outcome.steps} == {"arxiv": "timeout", "pubmed": "ok"}


async def test_failures_raises_and_unknown_names_are_skipped_with_reasons() -> None:
    async def failed(params):
        return SkillResult(success=False, error="no key")

    async def boom(params):
        raise RuntimeError("boom")

    runner = FakeRunner({"news-api": failed, "reddit": boom})
    outcome = await execute_skill_calls(
        [_call("news-api", query="q"), _call("reddit", query="q"), _call("ghost", query="q")], runner=runner, limits=LIMITS
    )
    assert outcome.results == ()
    assert {s.skill: s.reason_code for s in outcome.steps} == {
        "news-api": "skill_failed",
        "reddit": "error",
        "ghost": "unknown_skill",
    }


async def test_cancellation_is_not_swallowed() -> None:
    async def cancelled(params):
        raise asyncio.CancelledError

    runner = FakeRunner({"arxiv": cancelled})
    with pytest.raises(asyncio.CancelledError):
        await execute_skill_calls([_call("arxiv", query="q")], runner=runner, limits=LIMITS)


async def test_research_assistant_runs_second_on_stage_one_results() -> None:
    seen = {}

    async def summarize(params):
        seen.update(params)
        return SkillResult(success=True, data=[("Summary", "short")])

    runner = FakeRunner({"arxiv": _ok(("Paper A", "alpha")), "research-assistant": summarize})
    outcome = await execute_skill_calls(
        [_call("research-assistant"), _call("arxiv", query="q")], runner=runner, limits=LIMITS
    )
    assert [name for name, _ in runner.calls] == ["arxiv", "research-assistant"]
    assert "Paper A" in seen["content"] and "alpha" in seen["content"]
    assert seen["action"] == "summarize"
    assert [r.title for r in outcome.results] == ["Paper A", "Summary"]


async def test_research_assistant_is_skipped_without_stage_one_results() -> None:
    async def failed(params):
        return SkillResult(success=False, error="x")

    runner = FakeRunner({"arxiv": failed, "research-assistant": _ok(("S", "s"))})
    outcome = await execute_skill_calls(
        [_call("arxiv", query="q"), _call("research-assistant")], runner=runner, limits=LIMITS
    )
    assert [name for name, _ in runner.calls] == ["arxiv"]
    assert {s.skill: s.reason_code for s in outcome.steps}["research-assistant"] == "no_input"


async def test_results_are_capped_truncated_and_tagged() -> None:
    items = [(f"T{i}", "x" * 500) for i in range(9)]
    runner = FakeRunner({"arxiv": _ok(*items)})
    limits = SkillExecutionLimits(timeout_seconds=1.0, max_results_per_skill=2, max_content_chars=200)
    outcome = await execute_skill_calls([_call("arxiv", query="q")], runner=runner, limits=limits)
    assert [r.title for r in outcome.results] == ["T0", "T1"]
    assert all(len(r.content) <= 201 for r in outcome.results)
    assert all(r.metadata == {"skill": "arxiv", "via": SKILL_EXECUTOR_VIA} for r in outcome.results)
    assert outcome.steps[0].result_count == 2


async def test_steps_render_as_execution_steps() -> None:
    runner = FakeRunner({"arxiv": _ok(("T", "c"))})
    outcome = await execute_skill_calls([_call("arxiv", query="q")], runner=runner, limits=LIMITS)
    step = outcome.steps[0].to_execution_step()
    assert step["step"] == "skill_execution"
    assert step["skill"] == "arxiv" and step["status"] == "ok" and step["reason_code"] == "ok"
    assert step["result_count"] == 1 and isinstance(step["duration_ms"], int) and "timestamp" in step


async def test_no_calls_means_no_work() -> None:
    outcome = await execute_skill_calls([], runner=FakeRunner({}), limits=LIMITS)
    assert outcome.results == () and outcome.steps == ()
