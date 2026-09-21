"""조사 스펙 셋은 카탈로그에 박혀 있다 (계약 §2).

`neos/subagent/catalog.py` 는 fail-closed 레지스트리다 — 모델이 런타임에 타입을
만들지 않는다. J 가 여는 것이 "샌드박스에서 코드를 돌리는 자식" 이므로, 어떤
자식이 어떤 도구를 갖는지는 **코드에 적혀 있어야** 하고 프롬프트가 정하면 안 된다.

깊이는 0 이다. 서브질문은 제안이고 분할은 오케스트레이터가 한다(설계 §6.3).
"""

from __future__ import annotations

import pytest

from neos.subagent.catalog import UnknownSpec, lookup_spec, may_spawn
from neos.subagent.types import SandboxMode

pytestmark = pytest.mark.no_db

RESEARCH_TOOLS = frozenset(
    {
        "search.v1",
        "fetch.v1",
        "list_tree.v1",
        "read_file.v1",
        "search_text.v1",
        "write_file.v1",
        "execute.v1",
        "load_skill.v1",
        "check_claims.v1",
        "submit.v1",
    }
)


def test_research_carries_exactly_the_contract_tools() -> None:
    spec = lookup_spec("research")

    assert spec.allowed_tools == RESEARCH_TOOLS
    assert spec.can_spawn is False
    assert spec.can_approve is False


def test_analyze_is_research_without_retrieval() -> None:
    """계약 §2: analyze 는 research 에서 `search.v1`·`fetch.v1` 을 뺀 것.

    같은 질문의 verified 클레임만 입력으로 쓰기 때문이다(2026-09-17 결정).
    retrieval 이 남아 있으면 analyze 가 조용히 조사로 번진다.
    """
    analyze = lookup_spec("analyze")

    assert analyze.allowed_tools == RESEARCH_TOOLS - {"search.v1", "fetch.v1"}


def test_compose_reads_claims_and_writes_a_report() -> None:
    spec = lookup_spec("compose")

    assert spec.allowed_tools == frozenset(
        {
            "list_tree.v1",
            "read_file.v1",
            "search_text.v1",
            "write_file.v1",
            "edit_file.v1",
            "check_claims.v1",
            "submit.v1",
        }
    )


def test_no_research_spec_may_spawn() -> None:
    """깊이 0. 서브질문은 제안이고 분할은 오케스트레이터가 한다."""
    for name in ("research", "analyze", "compose"):
        assert may_spawn(lookup_spec(name), spawn_depth=0) is False


def test_no_research_spec_binds_a_parent_workspace() -> None:
    """샌드박스는 오케스트레이터가 `research-offline-v1` 로 띄운다.

    `WORKTREE` 는 git 워크트리를 만드는 코딩 전용 모드이고 DA 에는 저장소가
    없다. `PARENT_RO` 는 부모의 바인딩을 물려받는다는 뜻인데 조사 자식에게는
    물려받을 부모 워크스페이스가 없다. 그래서 `NONE` 이다 — 이것은 계약이
    적어 준 값이 아니라 구현의 해석이고, 계약에 그렇게 적었다.
    """
    for name in ("research", "analyze", "compose"):
        assert lookup_spec(name).sandbox_mode is SandboxMode.NONE


def test_judge_is_not_a_spec() -> None:
    """계약 §2: 판정자는 스펙이 아니다. 오케스트레이터가 부른다."""
    with pytest.raises(UnknownSpec):
        lookup_spec("judge")
