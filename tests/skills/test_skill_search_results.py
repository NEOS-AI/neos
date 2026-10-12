"""각 스킬이 자기 결과 모양을 `SearchResult` 로 바꾼다 (spec §3.5). 네트워크 없음."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.skills.base.search_results import collect_items
from neos.skills.manager.auto_discovery import discover_skills
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "neos" / "skills" / "builtin"
_CLASSES = {info.name: info.skill_class for info in discover_skills(BUILTIN_DIR, check_deps=False)}


def _convert(name: str, data, metadata=None) -> list[SearchResult]:
    skill = _CLASSES[name]()
    return skill.to_search_results(
        SkillResult(success=True, data=data, metadata=metadata or {}, skill_name=name)
    )


# (스킬, 결과 data, 기대 title, 기대 url, 기대 content 에 들어 있을 조각)
CASES = [
    ("arxiv", {"papers": [{"title": "Attention", "full_summary": "We propose", "entry_url": "http://arxiv.org/abs/1706.03762", "arxiv_id": "1706.03762"}]},
     "Attention", "http://arxiv.org/abs/1706.03762", "We propose"),
    ("arxiv", {"title": "Single", "summary": "by id", "entry_url": "http://arxiv.org/abs/1"},
     "Single", "http://arxiv.org/abs/1", "by id"),
    ("pubmed", {"papers": [{"title": "Vaccine", "full_summary": "Efficacy", "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/1/", "pmid": "1"}]},
     "Vaccine", "https://pubmed.ncbi.nlm.nih.gov/1/", "Efficacy"),
    ("wikipedia", {"articles": [{"title": "AI", "full_content": "Artificial", "url": "https://en.wikipedia.org/wiki/AI"}], "lang": "en"},
     "AI", "https://en.wikipedia.org/wiki/AI", "Artificial"),
    ("openalex", {"works": [{"title": "Work", "abstract": "Abs", "doi": "https://doi.org/10.1/x", "openalex_id": "W1"}]},
     "Work", "https://doi.org/10.1/x", "Abs"),
    ("openalex", {"authors": [{"name": "Ada", "openalex_id": "A1", "works_count": 3, "cited_by_count": 9}]},
     "Ada", "A1", "works: 3"),
    ("semantic-scholar", {"papers": [{"paper_id": "p1", "title": "S2", "abstract": "Abs", "url": "https://www.semanticscholar.org/paper/p1"}]},
     "S2", "https://www.semanticscholar.org/paper/p1", "Abs"),
    ("semantic-scholar", {"citations": [{"paper_id": "p2", "title": "Citing"}]},
     "Citing", "https://www.semanticscholar.org/paper/p2", ""),
    ("google-scholar", {"papers": [{"title": "GS", "snippet": "Snip", "url": "https://x"}]},
     "GS", "https://x", "Snip"),
    ("google-scholar", {"paper_title": "Cited", "cited_by_count": 7, "cited_by_link": "https://c"},
     "Cited", "https://c", "Cited by 7"),
    ("sec-edgar", {"filings": [{"company_name": "Apple", "form_type": "10-K", "filed_date": "2025-11-01", "description": "Annual", "url": "https://sec"}]},
     "Apple 10-K (2025-11-01)", "https://sec", "Annual"),
    ("github-search", {"repositories": [{"name": "langchain/langgraph", "description": "Graphs", "url": "https://github.com/langchain/langgraph"}]},
     "langchain/langgraph", "https://github.com/langchain/langgraph", "Graphs"),
    ("github-search", {"code_results": [{"name": "graph.py", "path": "src/graph.py", "repository": "o/r", "url": "https://g"}]},
     "o/r/src/graph.py", "https://g", "src/graph.py"),
    ("github-search", {"issues": [{"title": "Bug", "body": "Crash", "url": "https://i"}]},
     "Bug", "https://i", "Crash"),
    ("reddit", {"posts": [{"title": "Thread", "selftext": "Body", "url": "https://reddit.com/r/x/1"}]},
     "Thread", "https://reddit.com/r/x/1", "Body"),
    ("news-api", {"articles": [{"title": "News", "description": "Desc", "content": "Full", "url": "https://n"}]},
     "News", "https://n", "Desc"),
]


@pytest.mark.parametrize(("name", "data", "title", "url", "fragment"), CASES)
def test_each_skill_converts_its_own_result_shape(name, data, title, url, fragment) -> None:
    converted = _convert(name, data)
    assert len(converted) == 1
    item = converted[0]
    assert isinstance(item, SearchResult)
    assert item.source == name
    assert item.title == title
    assert item.url == url
    assert fragment in item.content


def test_scores_match_what_hdr_used_before() -> None:
    assert _convert("arxiv", CASES[0][1])[0].score == 0.95
    assert _convert("pubmed", CASES[2][1])[0].score == 0.95
    assert _convert("wikipedia", CASES[3][1])[0].score == 0.85


def test_research_assistant_summary_becomes_one_result() -> None:
    converted = _convert("research-assistant", {"summary": "short", "original_length": 99}, {"action": "summarize"})
    assert [r.content for r in converted] == ["short"]
    assert converted[0].source == "research-assistant"


def test_research_assistant_references_and_analysis() -> None:
    refs = _convert("research-assistant", {"urls": ["https://a"], "dois": ["10.1/x"], "total_references": 2})
    assert "https://a" in refs[0].content and "10.1/x" in refs[0].content
    analysis = _convert("research-assistant", {"quality_score": 75, "key_points": ["k1"]})
    assert "75/100" in analysis[0].content and "k1" in analysis[0].content


def test_unknown_shapes_convert_to_nothing() -> None:
    assert _convert("arxiv", None) == []
    assert _convert("arxiv", {"papers": "not a list"}) == []
    assert collect_items({"papers": [1, {"title": "ok"}]}, "papers") == [{"title": "ok"}]


def test_the_base_class_converts_nothing() -> None:
    class _Bare(BaseSkill):
        async def initialize(self) -> bool:
            return True

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(success=True)

        async def cleanup(self) -> None:
            return None

    bare = _Bare("bare", SkillType.CUSTOM)
    assert bare.to_search_results(SkillResult(success=True, data={"x": 1})) == []
