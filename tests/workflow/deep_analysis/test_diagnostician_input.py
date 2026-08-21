import json

from scripts.deep_analysis_diagnostician import build_summary


def _row(run_id: str, seq: int, kind: str, payload: dict):
    return (run_id, seq, kind, json.dumps(payload))


def test_summary_counts_events_by_kind():
    rows = [
        _row("r1", 1, "claim_verified", {}),
        _row("r1", 2, "claim_verified", {}),
        _row("r1", 3, "claim_rejected", {}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["events"]["claim_verified"] == 2
    assert summary["events"]["claim_rejected"] == 1


def test_summary_splits_budget_by_stage():
    rows = [
        _row("r1", 1, "token_budget_reserved",
             {"reservation_id": "a", "reserved_tokens": 100,
              "stage": "worker_analysis"}),
        _row("r1", 2, "token_budget_settled",
             {"reservation_id": "a", "reserved_tokens": 100,
              "actual_tokens": 40}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    stage = summary["budget"]["by_stage"]["worker_analysis"]
    assert stage["reserved"] == 100
    assert stage["settled"] == 40
    assert stage["calls"] == 1


def test_summary_counts_zero_token_passes():
    rows = [
        _row("r1", 1, "pass_completed", {"status": "failed", "tokens": 0}),
        _row("r1", 2, "pass_completed", {"status": "completed", "tokens": 900}),
    ]
    summary = build_summary(
        rows, run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    assert summary["passes"]["zero_token"] == 1
    assert summary["passes"]["productive"] == 1


def test_summary_reports_delivered_body_median_across_runs():
    """배달 각주/원마커/글자 수는 run당 값의 중앙값이다 -- 이 프로젝트의
    "배달 각주 중앙값" 어휘가 가리키는 계산 (§ 2026-08-18 표본 #16 판정).

    세 run 모두 본문이 있으므로 홀수 개라 중앙값이 모호하지 않다.
    """
    bodies = {
        "r1": "짧다[1]",
        "r2": "본문[1][2] [C:aaa] 남음\n\n## 출처\n[1] x\n[2] y",
        "r3": "본문[1][2][3] 남음\n\n## 출처\n[1] x",
    }
    summary = build_summary(
        [], run_ids=["r1", "r2", "r3"], report_bodies=bodies,
        config_fingerprint={},
    )
    delivered = summary["delivered"]
    assert delivered["runs_total"] == 3
    assert delivered["runs_with_body"] == 3
    assert delivered["runs_missing_body"] == 0
    # footnote counts per run: r1=1, r2=2, r3=3 -> median 2
    assert delivered["footnotes_median"] == 2
    assert delivered["raw_markers_median"] == 0  # only r2 has a raw marker
    assert delivered["sources_section_count"] == 2


def test_summary_counts_runs_with_no_delivered_body_as_a_signal():
    """본문이 없는 run은 빈 문자열로 섞이지 않고 별도로 세어진다 (태스크 3).

    `report_bodies`에 없는 run은 "본문 없음"이지, 각주 0개인 본문이 아니다
    -- 섞으면 `footnotes_median`이 실제 배달 본문의 중앙값이 아니게 된다.
    """
    summary = build_summary(
        [], run_ids=["r1", "r2"], report_bodies={"r1": "본문[1]"},
        config_fingerprint={},
    )
    delivered = summary["delivered"]
    assert delivered["runs_total"] == 2
    assert delivered["runs_with_body"] == 1
    assert delivered["runs_missing_body"] == 1
    assert delivered["footnotes_median"] == 1
    assert delivered["chars_median"] == len("본문[1]")


def test_summary_delivered_is_all_none_and_zero_when_no_body_ever_arrives():
    summary = build_summary(
        [], run_ids=["r1"], report_bodies={}, config_fingerprint={}
    )
    delivered = summary["delivered"]
    assert delivered["runs_with_body"] == 0
    assert delivered["runs_missing_body"] == 1
    assert delivered["footnotes_median"] is None
    assert delivered["raw_markers_median"] is None
    assert delivered["chars_median"] is None
    assert delivered["sources_section_count"] == 0


def test_summary_schema_is_identical_for_empty_and_full_input():
    """표본마다 같은 스키마여야 비교가 성립한다."""
    empty = build_summary(
        [], run_ids=[], report_bodies={}, config_fingerprint={}
    )
    full = build_summary(
        [_row("r1", 1, "claim_verified", {})],
        run_ids=["r1"],
        report_bodies={"r1": "x"},
        config_fingerprint={"global_token_cap": 140000},
    )
    assert set(empty) == set(full)
    assert set(empty["delivered"]) == set(full["delivered"])


def test_the_aggregator_never_branches_on_a_sample_identifier():
    """표본별로 요약을 고르면 정답을 아는 사람이 답을 흘릴 수 있다.

    스펙 §2의 방어를 코드로 고정한다 -- 집계 소스에 표본 id나 아티팩트
    타임스탬프가 등장하면 실패한다.
    """
    import inspect

    from scripts import deep_analysis_diagnostician as mod

    source = inspect.getsource(mod.build_summary)
    for forbidden in ("2026080", "2026081", "#11", "#16", "sample_id"):
        assert forbidden not in source, f"집계가 표본을 안다: {forbidden}"
