"""스키마는 스킬이 실제로 읽는 키와 같아야 한다 (spec §3.4).

기본 스키마 `{query, action, max_results}` 를 물려받으면 셀렉터가 `year_from` 같은
필터를 쓸 수 없고, 거꾸로 스킬이 안 읽는 키를 광고하면 LLM 이 헛손질한다.
그래서 양방향으로 대조한다 -- 키는 `skill.py` 의 AST 에서 뽑는다.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import jsonschema
import pytest

from neos.skills.manager.auto_discovery import discover_skills

pytestmark = pytest.mark.no_db

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "neos" / "skills" / "builtin"

AUTO_EXECUTE = (
    "arxiv",
    "pubmed",
    "wikipedia",
    "openalex",
    "semantic-scholar",
    "google-scholar",
    "sec-edgar",
    "github-search",
    "reddit",
    "news-api",
    "research-assistant",
)

# AST 가 잡지만 LLM 입력이 아닌 키.
#   openalex.mailto       -- HTTP 요청 dict(이름이 `params`)에 넣는 값이다
#   research-assistant.content -- 실행 노드가 1단계 결과로 채운다 (spec §3.3-4)
EXEMPT = {"openalex": {"mailto"}, "research-assistant": {"content"}}


@functools.cache
def _classes() -> dict:
    return {info.name: info.skill_class for info in discover_skills(BUILTIN_DIR, check_deps=False)}


def _tree(name: str) -> ast.AST:
    return ast.parse((BUILTIN_DIR / name / "skill.py").read_text(encoding="utf-8"))


def _params_keys(name: str) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(_tree(name)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
    return keys - EXEMPT.get(name, set())


def _dispatched_actions(name: str) -> set[str]:
    actions: set[str] = set()
    for node in ast.walk(_tree(name)):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "action"
            and isinstance(node.ops[0], ast.Eq)
            and isinstance(node.comparators[0], ast.Constant)
        ):
            actions.add(node.comparators[0].value)
    return actions


def _schema(name: str) -> dict:
    return _classes()[name].get_input_schema()


@pytest.mark.parametrize("name", AUTO_EXECUTE)
def test_schema_properties_equal_the_keys_the_skill_reads(name: str) -> None:
    assert set(_schema(name)["properties"]) == _params_keys(name)


@pytest.mark.parametrize("name", AUTO_EXECUTE)
def test_action_enum_equals_the_actions_execute_dispatches(name: str) -> None:
    assert set(_schema(name)["properties"]["action"]["enum"]) == _dispatched_actions(name)


@pytest.mark.parametrize("name", AUTO_EXECUTE)
def test_schema_is_valid_json_schema(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_research_assistant_does_not_ask_the_model_for_content() -> None:
    assert "content" not in _schema("research-assistant")["properties"]
