import pytest

from neos.workflow.deep_analysis.discard_recall import (
    ScoringSession,
    claim_from_event,
    discards_needed_for_safe,
    false_discard_rate,
    fingerprint_digest,
    pool_sessions,
    stopping_verdict,
    value_est_from_event,
    wilson_interval,
)


pytestmark = pytest.mark.no_db


def _payload():
    return {
        "text": "discarded claim",
        "confidence": 0.6,
        "value_est": 1.0,
        "evidence": [
            {
                "source_url": "https://example.com/source",
                "excerpt": "Direct evidence.",
                "raw_ref": "0123456789abcdef",
            }
        ],
    }


def test_claim_from_event_rebuilds_claim_with_evidence():
    claim = claim_from_event(_payload())

    assert claim is not None
    assert claim.text == "discarded claim"
    assert claim.confidence == 0.6
    assert len(claim.evidence) == 1
    assert claim.evidence[0].raw_ref == "0123456789abcdef"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("text"),
        lambda p: p.update({"text": "   "}),
        lambda p: p.update({"confidence": "high"}),
        lambda p: p.update({"evidence": "not-a-list"}),
        lambda p: p.update({"evidence": [{"source_url": "u"}]}),
    ],
)
def test_claim_from_event_rejects_malformed_payload(mutate):
    payload = _payload()
    mutate(payload)

    assert claim_from_event(payload) is None


def test_value_est_from_event():
    assert value_est_from_event(_payload()) == 1.0
    assert value_est_from_event({"value_est": "x"}) is None


def test_wilson_interval_matches_known_values():
    low, high = wilson_interval(19, 38, 1.96)

    assert round(low * 100, 1) == 34.8
    assert round(high * 100, 1) == 65.2


def test_wilson_interval_handles_empty_denominator():
    assert wilson_interval(0, 0, 1.96) == (0.0, 0.0)


def test_false_discard_rate():
    assert false_discard_rate(3, 12) == 0.25
    assert false_discard_rate(0, 0) == 0.0


def test_stopping_verdict_applies_preregistered_rule():
    assert (
        stopping_verdict(0.0, 0.08, safe_upper=0.10, over_discard_lower=0.40)
        == "safe"
    )
    assert (
        stopping_verdict(0.45, 0.80, safe_upper=0.10, over_discard_lower=0.40)
        == "over_discarding"
    )
    assert (
        stopping_verdict(0.05, 0.60, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )


def test_claim_from_event_rejects_boolean_confidence():
    payload = _payload()
    payload["confidence"] = True

    assert claim_from_event(payload) is None


def test_value_est_from_event_rejects_boolean():
    assert value_est_from_event({"value_est": True}) is None
    assert value_est_from_event({"value_est": False}) is None


def test_stopping_verdict_boundaries_are_strict():
    # Exactly on a bound is not past it — both fall to inconclusive.
    assert (
        stopping_verdict(0.0, 0.10, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )
    assert (
        stopping_verdict(0.40, 1.0, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )


def test_wilson_interval_stays_in_unit_range_at_extremes():
    low, high = wilson_interval(0, 10, 1.96)
    assert low == 0.0
    assert 0.0 < high < 1.0

    low, high = wilson_interval(10, 10, 1.96)
    assert 0.0 < low < 1.0
    assert high == 1.0


# --- C1 누적: 여러 채점 세션을 하나의 분모로 --------------------------------
#
# 사전 등록된 규칙은 verified 0 일 때 n >= 35 부터만 `safe` 를 낼 수 있는데
# 5+1 런 하나는 distinct discard 를 16개 안팎 낸다. 그래서 판정에는 여러
# 세션을 합치는 것이 **필수**이고, 합치기가 그냥 더하기가 아닌 이유를 아래가
# 고정한다.


def _session(name, *, total, verified, runs=(), fp=None):
    return ScoringSession(
        artifact=name,
        fingerprint=fp if fp is not None else {"judge_model": "j-1"},
        run_ids=tuple(runs),
        total_discarded=total,
        verified=verified,
    )


def _pool(sessions):
    return pool_sessions(
        sessions, wilson_z=1.96, safe_upper=0.10, over_discard_lower=0.40
    )


def test_pooling_two_compatible_sessions_sums_the_denominator():
    pooled = _pool(
        [
            _session("a", total=16, verified=0, runs=("r1",)),
            _session("b", total=20, verified=0, runs=("r2",)),
        ]
    )

    assert pooled["total_discarded"] == 36
    assert pooled["verified"] == 0
    # n=35 가 문턱이므로 36 이면 처음으로 `safe` 에 도달한다 -- 이 테스트가
    # 확인하는 것은 합이 아니라 **합쳐야만 판정이 난다**는 사실이다.
    assert pooled["verdict"] == "safe"


def test_neither_session_alone_can_reach_the_verdict_the_pool_reaches():
    """왜 누적이 필요한지를 직접 주장한다. 없으면 위 테스트가 공허하다."""
    for total in (16, 20):
        alone = _pool([_session("x", total=total, verified=0, runs=("r",))])
        assert alone["verdict"] == "inconclusive"


def test_sessions_scored_under_different_configs_are_refused_not_averaged():
    """판정자를 바꾸면 같은 클레임이 다른 판정을 받는다 (E3 가 그 경계다).

    두 분모를 합치면 n 은 커지는데 **무엇의 n 인지**가 사라진다. 조용히
    버리지 않고 거부하는 이유는 §8.1.2 다: 버리면 사람은 그 표본이
    세어졌다고 믿는다.
    """
    pooled = _pool(
        [
            _session("a", total=16, verified=0, runs=("r1",),
                     fp={"judge_model": "claude-opus-4-8"}),
            _session("b", total=20, verified=0, runs=("r2",),
                     fp={"judge_model": "gpt-5.6-sol"}),
        ]
    )

    assert pooled["verdict"] == "incompatible_fingerprints"
    assert "total_discarded" not in pooled
    assert set(pooled["by_artifact"]) == {"a", "b"}


def test_a_run_scored_twice_is_refused_because_it_narrows_the_interval():
    """중복은 분모를 부풀려 Wilson 구간을 **실제보다 좁게** 만든다.

    즉 `safe` 를 근거 없이 앞당긴다. `score_discards` 가 run 안에서 이미 한 번
    막은 실수(같은 클레임의 여러 이벤트)와 같은 종류이고, 방향도 같다.
    """
    pooled = _pool(
        [
            _session("a", total=16, verified=0, runs=("r1", "r2")),
            _session("b", total=20, verified=0, runs=("r2", "r3")),
        ]
    )

    assert pooled["verdict"] == "overlapping_runs"
    assert pooled["overlaps"] == {"r2": ["a", "b"]}


def test_fingerprint_digest_ignores_key_order():
    """순서 때문에 합칠 수 있는 세션이 거부되면 누적이 무작위로 실패한다."""
    assert fingerprint_digest({"a": 1, "b": {"x": 2, "y": 3}}) == (
        fingerprint_digest({"b": {"y": 3, "x": 2}, "a": 1})
    )


def test_needed_for_safe_answers_when_to_stop_collecting():
    assert discards_needed_for_safe(0, 35, wilson_z=1.96, safe_upper=0.10) == 0
    # 16 에서 35 까지 19 개가 더 필요하다 -- 사람이 손으로 풀던 산술이다.
    assert (
        discards_needed_for_safe(0, 16, wilson_z=1.96, safe_upper=0.10) == 19
    )


def test_needed_for_safe_says_unreachable_rather_than_a_huge_number():
    """비율이 이미 문턱을 넘으면 표본을 더 모아도 내려오지 않는다.

    거기서 필요한 것은 표본이 아니라 필터 수정이고, 큰 수를 돌려주면
    다음 사람이 그 수만큼 표본을 태운다.
    """
    assert (
        discards_needed_for_safe(5, 10, wilson_z=1.96, safe_upper=0.10) is None
    )
