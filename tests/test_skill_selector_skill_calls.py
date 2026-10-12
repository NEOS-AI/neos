"""셀렉터 출력 계약 `skill_calls` (spec §3.2·§3.3·§3.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neos.agents.skill_based_tool_selector import SkillBasedToolSelector, SkillCall, SkillToolSelection
from neos.skills.base import SkillType
from neos.skills.manager.skill_registry import SkillInfo

pytestmark = pytest.mark.no_db

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["search", "get_by_id"]},
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["query"],
}
RA_SCHEMA = {"type": "object", "properties": {"action": {"type": "string", "enum": ["summarize"]}}, "required": []}


def _skill(name: str, schema: dict) -> dict:
    return {"name": name, "type": "research", "description": name, "capabilities": ["x"], "version": "1.0.0", "input_schema": schema}


SKILLS = [_skill("arxiv", SEARCH_SCHEMA), _skill("pubmed", SEARCH_SCHEMA), _skill("wikipedia", SEARCH_SCHEMA), _skill("research-assistant", RA_SCHEMA)]


def _parse(text: str, *, max_skills: int = 3) -> SkillToolSelection:
    return SkillBasedToolSelector()._parse_selection(
        text, SKILLS, [], fallback_query="diffusion models", max_skills=max_skills
    )


def test_a_valid_call_keeps_its_params_and_derives_selected_skills() -> None:
    selection = _parse('{"skill_calls": [{"name": "arxiv", "params": {"query": "dit", "max_results": 3}, "reason": "papers"}]}')
    assert selection.skill_calls == [SkillCall("arxiv", {"query": "dit", "max_results": 3}, "papers")]
    assert selection.selected_skills == ["arxiv"]


def test_names_outside_the_candidates_are_dropped() -> None:
    selection = _parse('{"skill_calls": [{"name": "cron", "params": {}}, {"name": "pubmed", "params": {"query": "q"}}]}')
    assert selection.selected_skills == ["pubmed"]


def test_unknown_param_keys_are_stripped() -> None:
    selection = _parse('{"skill_calls": [{"name": "arxiv", "params": {"query": "q", "bogus": 1}}]}')
    assert selection.skill_calls[0].params == {"query": "q"}


@pytest.mark.parametrize(
    "params",
    ['{"query": "q", "max_results": 500}', '{"max_results": 2}', '"not a dict"', "null"],
)
def test_invalid_params_fall_back_to_the_query(params: str) -> None:
    selection = _parse(f'{{"skill_calls": [{{"name": "arxiv", "params": {params}}}]}}')
    assert selection.skill_calls[0].params == {"query": "diffusion models"}


def test_a_skill_without_a_query_parameter_falls_back_to_empty_params() -> None:
    selection = _parse('{"skill_calls": [{"name": "research-assistant", "params": {"action": "nope"}}]}')
    assert selection.skill_calls[0].params == {}


def test_duplicate_calls_keep_the_first() -> None:
    selection = _parse(
        '{"skill_calls": [{"name": "arxiv", "params": {"query": "a"}}, {"name": "arxiv", "params": {"query": "b"}}]}'
    )
    assert [c.params["query"] for c in selection.skill_calls] == ["a"]


def test_calls_are_capped() -> None:
    selection = _parse(
        '{"skill_calls": [{"name": "arxiv", "params": {"query": "a"}}, {"name": "pubmed", "params": {"query": "b"}},'
        ' {"name": "wikipedia", "params": {"query": "c"}}]}',
        max_skills=2,
    )
    assert selection.selected_skills == ["arxiv", "pubmed"]


def test_the_legacy_name_list_still_becomes_calls_with_fallback_params() -> None:
    selection = _parse('{"selected_skills": ["arxiv"], "selected_tools": []}')
    assert selection.skill_calls == [SkillCall("arxiv", {"query": "diffusion models"}, "")]


def test_unparseable_text_selects_no_skills_even_when_a_name_appears() -> None:
    selection = _parse("I would use arxiv here")
    assert selection.skill_calls == [] and selection.selected_skills == []


def test_selection_derives_names_from_calls_and_serialises_them() -> None:
    selection = SkillToolSelection(
        selected_skills=["stale"],
        selected_tools=[],
        reasoning="",
        priority_order=[],
        skill_calls=[SkillCall("arxiv", {"query": "q"})],
    )
    assert selection.selected_skills == ["arxiv"]
    assert selection.to_dict()["skill_calls"] == [{"name": "arxiv", "params": {"query": "q"}, "reason": ""}]


def test_one_prompt_template_for_every_language() -> None:
    selector = SkillBasedToolSelector()
    ko = selector._build_selection_prompt("q", {}, SKILLS, [], "ko", 3)
    en = selector._build_selection_prompt("q", {}, SKILLS, [], "en", 3)
    assert "Korean" in ko and "English" in en
    assert ko.replace("Korean", "<L>") == en.replace("English", "<L>")
    assert "max_results" in en and "at most 3" in en and "skill_calls" in en


class _Schema:
    @classmethod
    def get_input_schema(cls) -> dict:
        return SEARCH_SCHEMA


def _info(name: str, *, auto: bool) -> SkillInfo:
    return SkillInfo(name=name, skill_class=_Schema, skill_type=SkillType.RESEARCH, description=name, capabilities=["x"], auto_execute=auto)


def test_known_unavailable_skills_are_not_candidates() -> None:
    manager = MagicMock()
    manager.registry.list_skills.return_value = [
        _info("arxiv", auto=True),
        _info("google-scholar", auto=True),
        _info("cron", auto=False),
    ]
    manager.known_unavailable.return_value = frozenset({"google-scholar"})
    selector = SkillBasedToolSelector()
    selector._skill_manager = manager
    candidates = selector._get_available_skills()
    assert [c["name"] for c in candidates] == ["arxiv"]
    assert candidates[0]["input_schema"] == SEARCH_SCHEMA


def test_skill_manager_reports_skills_whose_initialisation_failed() -> None:
    from neos.skills.manager.skill_manager import SkillManager

    manager = SkillManager()
    manager._initialized_skills.update({"arxiv": True, "news-api": False})
    assert manager.known_unavailable() == frozenset({"news-api"})


async def test_the_fallback_query_comes_from_the_caller() -> None:
    selector = SkillBasedToolSelector()
    response = MagicMock()
    response.content = '{"skill_calls": [{"name": "arxiv"}], "selected_tools": []}'
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=response)
    with patch.object(selector, "_get_available_skills", return_value=SKILLS), \
         patch.object(selector, "_get_available_tools", return_value=[]), \
         patch("neos.agents.skill_based_tool_selector.create_llm"), \
         patch("neos.agents.skill_based_tool_selector.create_tracked_llm", return_value=llm):
        selection = await selector.select_skills_and_tools(
            query="original", context={}, fallback_query="refined query"
        )
    assert selection.skill_calls[0].params == {"query": "refined query"}
