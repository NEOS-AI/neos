import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.worker import Worker


pytestmark = pytest.mark.no_db


class FakeSelector:
    def __init__(self, skills):
        self._skills = skills
        self.asked_efforts = []

    def candidates(self, effort):
        self.asked_efforts.append(effort)
        return self._skills


async def fake_search_fn(query, k):
    return [{"url": "https://web.example/1", "title": "w", "snippet": "s"}]


@pytest.mark.asyncio
async def test_worker_without_selector_uses_plain_search(monkeypatch):
    called = {"discovery": False}

    async def spy_run_discovery(*args, **kwargs):
        called["discovery"] = True
        return [], 0

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.run_discovery", spy_run_discovery
    )
    worker = Worker(fake_search_fn)
    worker._model = "claude-opus-4-6"
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert called["discovery"] is False
    assert [u["url"] for u in urls] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_worker_scout_never_uses_discovery(monkeypatch):
    # scout은 token_cap 2000이라 도구 스키마 + 멀티턴이 안 들어간다.
    async def boom(*args, **kwargs):
        raise AssertionError("discovery must not run at scout effort")

    monkeypatch.setattr("neos.workflow.deep_analysis.worker.run_discovery", boom)
    selector = FakeSelector([])
    worker = Worker(fake_search_fn, skill_selector=selector)
    worker._model = "claude-haiku-4-5-20251001"
    urls = await worker._collect_candidates("brief", Effort.SCOUT, 5)

    assert [u["url"] for u in urls] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_worker_dig_with_candidates_uses_discovery_and_counts_tokens(monkeypatch):
    async def fake_run_discovery(*args, **kwargs):
        return [{"url": "https://arxiv.example/1", "title": "p", "snippet": "x"}], 42

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.run_discovery", fake_run_discovery
    )

    class FakeSkill:
        name = "arxiv"

    worker = Worker(fake_search_fn, skill_selector=FakeSelector([FakeSkill()]))
    worker._model = "claude-opus-4-6"
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert [u["url"] for u in urls] == ["https://arxiv.example/1"]
    assert worker._tokens == 42


@pytest.mark.asyncio
async def test_worker_dig_falls_back_to_plain_search_when_no_candidates(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("discovery must not run without candidates")

    monkeypatch.setattr("neos.workflow.deep_analysis.worker.run_discovery", boom)
    worker = Worker(fake_search_fn, skill_selector=FakeSelector([]))
    worker._model = "claude-opus-4-6"
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert [u["url"] for u in urls] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_worker_dig_degrades_to_plain_search_when_discovery_finds_nothing(
    monkeypatch,
):
    # 스킬이 전부 죽어 후보 URL이 0개면 web_search 단독 경로로 내려간다 (AC7).
    async def empty_discovery(*args, **kwargs):
        return [], 13

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.run_discovery", empty_discovery
    )

    class FakeSkill:
        name = "arxiv"

    worker = Worker(fake_search_fn, skill_selector=FakeSelector([FakeSkill()]))
    worker._model = "claude-opus-4-6"
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert [u["url"] for u in urls] == ["https://web.example/1"]
    assert worker._tokens == 13  # 실패했어도 쓴 토큰은 계상한다
