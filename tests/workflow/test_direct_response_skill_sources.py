"""skip 경로에서도 스킬이 돌면 직접 응답이 그 출처로 답한다 (spec §2)."""

import pytest

import neos.workflow.graph  # noqa: F401 -- 계약 등록
from neos.skills.base.search_results import SKILL_EXECUTOR_VIA
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.enums import WorkflowNode
from neos.workflow.processors.response_generator import ResponseGenerator
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db


def _generator() -> ResponseGenerator:
    return ResponseGenerator.__new__(ResponseGenerator)


def _state(results):
    return {"original_query": "최신 DiT 논문", "search_results": results, "conversation_context": ""}


def _skill_result(title, url, content):
    return SearchResult(source="arxiv", title=title, content=content, url=url, metadata={"skill": "arxiv", "via": SKILL_EXECUTOR_VIA})


def test_skill_sources_are_numbered_into_the_prompt() -> None:
    prompt = _generator()._direct_response_prompt(
        _state([_skill_result("Paper A", "https://arxiv.org/abs/1", "alpha body")]), "ko"
    )
    assert "[출처]" in prompt
    assert "[1] Paper A — https://arxiv.org/abs/1" in prompt
    assert "alpha body" in prompt
    assert "외부 검색이 필요 없다고" not in prompt


def test_results_from_other_sources_do_not_change_the_prompt() -> None:
    other = SearchResult(source="web", title="W", content="c", url="https://w", metadata={})
    with_other = _generator()._direct_response_prompt(_state([other]), "ko")
    without = _generator()._direct_response_prompt(_state([]), "ko")
    assert with_other == without
    assert "[출처]" not in without


def test_the_contract_declares_the_read() -> None:
    assert "search_results" in NODE_CONTRACTS[WorkflowNode.DIRECT_RESPONSE.value].reads
