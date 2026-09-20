"""`/evidence` 한도는 거절이다 (계약 §9 결정 4, 2026-09-20).

한도에 닿으면 **새 fetch 를 거절하고** 이미 있는 blob 은 빼지 않는다. 축출을
고르지 않은 이유는 사라진 blob 을 `inputs` 로 가진 계산 클레임이 채점 때
`E_COMPUTE_INPUT_UNFETCHED` 로 **나중에 조용히** 죽기 때문이다.

판단을 순수 함수에 두는 이유는 두 가지다. 원장 경로는 Postgres 를 요구해서
이 기계에서 돌지 않고, 무엇보다 **무엇을 얼마나 청구하는가**가 이 결정의
전부라서 그 부분만은 DB 없이 고정할 수 있어야 한다.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.no_db

_REPO = pathlib.Path(__file__).resolve().parents[3]

# 임포트를 모듈 상단에 두지 않는 이유: 모듈이 아직 없을 때 **파일 전체가
# 수집 실패**로 죽어서, 파일만 읽는 마이그레이션 테스트 둘이 자기 이유로
# 빨개지는 것을 볼 수 없다. 한 번의 ImportError 가 일곱 개의 판정을 가린다.


def test_a_fetch_under_the_cap_is_admitted_and_charged() -> None:
    from neos.workflow.deep_analysis.evidence_store import decide_fetch_admission

    decision = decide_fetch_admission(
        cap_bytes=100, spent_bytes=0, incoming_bytes=40, already_stored=False
    )

    assert decision.admitted is True
    assert decision.bytes_charged == 40


def test_at_the_cap_a_new_fetch_is_refused_and_nothing_is_evicted() -> None:
    from neos.workflow.deep_analysis.evidence_store import decide_fetch_admission

    decision = decide_fetch_admission(
        cap_bytes=100, spent_bytes=100, incoming_bytes=1, already_stored=False
    )

    assert decision.admitted is False
    assert decision.bytes_charged == 0
    assert decision.reason == "evidence_cap_reached"


def test_a_fetch_that_would_cross_the_cap_is_refused_whole() -> None:
    """blob 은 통째로 있거나 없다. 부분 저장은 재현을 깨뜨린다."""
    from neos.workflow.deep_analysis.evidence_store import decide_fetch_admission

    decision = decide_fetch_admission(
        cap_bytes=100, spent_bytes=90, incoming_bytes=20, already_stored=False
    )

    assert decision.admitted is False
    assert decision.bytes_charged == 0


def test_a_fetch_that_exactly_fills_the_cap_is_admitted() -> None:
    """경계는 허용 쪽이다 — 한도는 '넘지 않는다' 이지 '닿지 않는다' 가 아니다."""
    from neos.workflow.deep_analysis.evidence_store import decide_fetch_admission

    decision = decide_fetch_admission(
        cap_bytes=100, spent_bytes=60, incoming_bytes=40, already_stored=False
    )

    assert decision.admitted is True
    assert decision.bytes_charged == 40


def test_refetching_stored_content_costs_no_headroom() -> None:
    """`_store_blob` 은 `(run_id, content_hash)` 가 있으면 일찍 돌아온다.

    그 바이트를 또 세면 **쓰지도 않은 한도**를 까먹는다. 미러 URL 이 같은
    본문으로 dedup 되는 것이 의도된 동작이므로(fetch.py `_blob_hash`) 이 경로는
    드물지 않다.
    """
    from neos.workflow.deep_analysis.evidence_store import decide_fetch_admission

    decision = decide_fetch_admission(
        cap_bytes=100, spent_bytes=100, incoming_bytes=40, already_stored=True
    )

    assert decision.admitted is True
    assert decision.bytes_charged == 0


def test_migration_059_adds_the_question_evidence_counter() -> None:
    sql = (
        _REPO / "db/migrations/059_add_question_evidence_bytes.sql"
    ).read_text()

    assert "deep_analysis_questions" in sql
    assert "evidence_bytes" in sql


def test_migration_059_is_in_the_canonical_bootstrap_order() -> None:
    """정본은 산문이 아니라 `BOOTSTRAP_ORDER.txt` 다."""
    # 순서는 BOOTSTRAP_ORDER.txt 의 규칙에서 유도된다 (2026-09-20) -- 본문 대신 유도 결과.
    from scripts.verify_schema_bootstrap import bootstrap_order

    lines = bootstrap_order()

    previous = lines.index("db/migrations/058_allow_workflow_subagent_parent.sql")
    added = lines.index("db/migrations/059_add_question_evidence_bytes.sql")

    assert added > previous
