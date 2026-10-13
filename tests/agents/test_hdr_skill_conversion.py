"""HDR 은 스킬이 소유한 변환을 쓴다 -- 사본을 두지 않는다 (spec §5)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import neos.agents.search_agents.hyper_deep_research.skills_integration as integration
from neos.skills.base import SkillResult
from neos.skills.manager.auto_discovery import discover_skills

pytestmark = pytest.mark.no_db

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "neos" / "skills" / "builtin"
_CLASSES = {info.name: info.skill_class for info in discover_skills(BUILTIN_DIR, check_deps=False)}


class _Registry:
    def get_skill(self, name):
        return _CLASSES[name]()


class _Manager:
    def __init__(self, data):
        self.registry = _Registry()
        self._data = data

    async def execute_skill(self, name, params):
        return SkillResult(success=True, data=self._data[name], skill_name=name)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(integration.asyncio, "sleep", AsyncMock())


async def test_arxiv_rows_keep_their_shape() -> None:
    manager = _Manager({"arxiv": {"papers": [{"title": "T", "full_summary": "S", "entry_url": "U", "arxiv_id": "1", "authors": "A", "published": "P", "pdf_url": "F"}]}})
    rows = await integration.SkillsIntegrator(manager)._search_with_arxiv(["q"], {})
    assert rows == [{
        "source": "arxiv", "title": "T", "content": "S", "url": "U", "score": 0.95,
        "metadata": {"arxiv_id": "1", "authors": "A", "published": "P", "pdf_url": "F"},
    }]


async def test_wikipedia_rows_keep_summary_and_language() -> None:
    manager = _Manager({"wikipedia": {"articles": [{"title": "W", "full_content": "C", "url": "U", "summary": "S"}], "lang": "ko"}})
    rows = await integration.SkillsIntegrator(manager)._search_with_wikipedia(["q"], {}, "ko")
    assert rows[0]["metadata"] == {"summary": "S", "language": "ko"}
    assert rows[0]["score"] == 0.85


async def test_stats_count_converted_rows() -> None:
    manager = _Manager({"pubmed": {"papers": [{"title": "A"}, {"title": "B"}]}})
    integrator = integration.SkillsIntegrator(manager)
    rows = await integrator._search_with_pubmed(["q"], {})
    assert integrator.stats["pubmed_results"] == 2
    # URL 이 없는 항목은 예전처럼 "" 다 (None 이 아니다).
    assert [row["url"] for row in rows] == ["", ""]


async def test_conversion_comes_from_the_skill_not_a_copy() -> None:
    # 변환을 스킬 쪽에서 바꾸면 HDR 도 따라 바뀌어야 한다 -- 사본이 남아 있으면 안 바뀐다.
    class _Patched(_CLASSES["arxiv"]):
        def to_search_results(self, result):
            return [integration_marker]

    from neos.workflow.state import SearchResult

    integration_marker = SearchResult(source="arxiv", title="from-skill", content="", url="u")
    manager = _Manager({"arxiv": {"papers": [{"title": "T"}]}})
    manager.registry.get_skill = lambda name: _Patched()
    rows = await integration.SkillsIntegrator(manager)._search_with_arxiv(["q"], {})
    assert [row["title"] for row in rows] == ["from-skill"]
