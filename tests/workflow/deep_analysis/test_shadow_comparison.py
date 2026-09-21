"""섀도가 낸 제안을 기록된 run 과 맞대 본다 (로드맵 J3: "제안만 비교").

## 같음의 정의는 원장에서 빌려 온다

`claim_hash` 는 `_upsert_claim` 이 클레임을 **병합할 때** 쓰는 바로 그
함수다. 섀도가 자기만의 동일성 규칙을 쓰면 원장이 한 클레임으로 세는 둘을
여기서는 둘로 세고, 그 차이가 "조사 워커가 새 클레임을 냈다" 로 보고된다.

## 다름은 실패가 아니라 **정보**다

조사 워커가 옛 워커와 다르게 탐색하는 것이 이 비교의 요점이다. 그래서
보고서는 판정("통과/실패")이 아니라 세 갈래와 그 갈래를 해석하는 데 필요한
사실을 싣는다.

특히 **빗나간 URL 수**가 같이 실려야 한다. 섀도가 프로덕션보다 적은 증거로
돌았다면 제안이 빈약한 것은 워커 탓이 아니다 -- 그 사실 없이 갈래만 보면
비교가 워커를 잘못 나무란다.

## 상태를 미리 거르지 않는다

기록된 클레임에는 verified 도 rejected 도 있다. verified 만 비교하면 "조사
워커가 놓친 것" 이 좁아 보이고, 전부 뭉치면 놓친 것의 무게를 알 수 없다.
그래서 상태를 **그대로 실어** 보고서를 읽는 쪽이 고르게 한다 -- 미리 거르는
것은 독자 대신 결정하는 것이다.
"""

from __future__ import annotations

import pytest

from neos.workflow.deep_analysis.models import ProposedClaim

pytestmark = pytest.mark.no_db


def _recorded(text: str, status: str = "verified"):
    from neos.workflow.deep_analysis.shadow import RecordedClaim

    return RecordedClaim(text=text, status=status)


def _compare(recorded, proposed, *, served=(), missed=()):
    from neos.workflow.deep_analysis.shadow import compare_claims

    return compare_claims(
        recorded,
        [ProposedClaim(text=text, confidence=0.5) for text in proposed],
        served_urls=list(served),
        missed_urls=list(missed),
    )


def test_a_claim_both_sides_found_is_shared() -> None:
    result = _compare([_recorded("평균은 42.5 다")], ["평균은 42.5 다"])

    assert result.shared == ("평균은 42.5 다",)
    assert result.only_recorded == ()
    assert result.only_shadow == ()


def test_sameness_uses_the_ledgers_own_rule() -> None:
    """원장이 한 클레임으로 병합하는 둘을 여기서 둘로 세면 안 된다.

    `claim_hash` 는 정규화를 거치므로 공백·대소문자 차이는 같은 클레임이다.
    섀도가 문자열을 그대로 비교하면 그 차이가 "새 클레임" 으로 보고된다.
    """
    from neos.workflow.deep_analysis.text_norm import claim_hash

    # 이 테스트가 무엇에 기대는지 먼저 못 박는다 -- 정규화가 이 둘을 같게
    # 보지 않는다면 아래 단언은 다른 것을 재고 있다.
    assert claim_hash("MoE  routing lowers cost") == claim_hash(
        "moe routing lowers cost"
    )

    result = _compare(
        [_recorded("MoE  routing lowers cost")], ["moe routing lowers cost"]
    )

    assert result.only_shadow == ()
    assert len(result.shared) == 1


def test_a_claim_only_the_recorded_run_found_carries_its_status() -> None:
    """놓친 것의 **무게**가 상태에 있다.

    verified 를 놓친 것과 rejected 를 놓친 것은 다른 이야기다 -- 후자는
    오히려 잘한 일일 수 있다.
    """
    result = _compare(
        [_recorded("놓친 클레임", "verified"), _recorded("기각됐던 것", "rejected")],
        [],
    )

    assert [(c.text, c.status) for c in result.only_recorded] == [
        ("놓친 클레임", "verified"),
        ("기각됐던 것", "rejected"),
    ]


def test_a_claim_only_the_shadow_found_is_not_an_error() -> None:
    """다르게 탐색하는 것이 요점이므로 새 제안은 기대되는 결과다."""
    result = _compare([], ["조사 워커가 새로 낸 것"])

    assert result.only_shadow == ("조사 워커가 새로 낸 것",)


def test_the_report_carries_what_the_archive_could_not_serve() -> None:
    result = _compare([], [], missed=["https://a", "https://b"], served=["https://c"])

    assert result.missed_urls == ("https://a", "https://b")
    assert result.served_urls == ("https://c",)


def test_a_shadow_that_fetched_nothing_new_says_so_plainly() -> None:
    """빗나감이 0 이면 비교는 증거 차이가 아니라 **판단 차이**를 말한다.

    그 구별이 J3 의 전부다: 제안이 다른 이유가 증거가 없어서인지 워커가
    다르게 봐서인지.
    """
    result = _compare([_recorded("A")], ["A"], served=["https://c"])

    assert result.missed_urls == ()
    assert result.evidence_was_complete is True


def test_a_shadow_that_missed_a_url_does_not_claim_completeness() -> None:
    result = _compare([_recorded("A")], ["A"], missed=["https://a"])

    assert result.evidence_was_complete is False


def test_duplicate_proposals_collapse_the_way_the_ledger_would() -> None:
    """`_upsert_claim` 은 같은 해시를 한 행으로 병합한다.

    섀도가 둘로 세면 "조사 워커가 더 많이 냈다" 는 거짓 신호가 생긴다.
    """
    result = _compare([], ["같은 문장", "같은  문장"])

    assert result.only_shadow == ("같은 문장",)
