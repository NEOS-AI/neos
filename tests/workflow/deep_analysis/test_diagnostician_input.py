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
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
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
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
    stage = summary["budget"]["by_stage"]["worker_analysis"]
    assert stage["reserved"] == 100
    assert stage["settled"] == 40
    assert stage["calls"] == 1


def test_summary_counts_zero_token_passes():
    rows = [
        _row("r1", 1, "pass_completed", {"status": "failed", "tokens": 0}),
        _row("r1", 2, "pass_completed", {"status": "completed", "tokens": 900}),
    ]
    summary = build_summary(rows, report_markdown="", config_fingerprint={})
    assert summary["passes"]["zero_token"] == 1
    assert summary["passes"]["productive"] == 1


def test_summary_reads_the_delivered_report():
    summary = build_summary(
        [],
        report_markdown="본문[1] 그리고 [C:abc123] 남음\n\n## 출처\n[1] x",
        config_fingerprint={},
    )
    assert summary["delivered"]["footnotes"] == 1
    assert summary["delivered"]["raw_markers"] == 1
    assert summary["delivered"]["sources_section"] is True


def test_summary_schema_is_identical_for_empty_and_full_input():
    """표본마다 같은 스키마여야 비교가 성립한다."""
    empty = build_summary([], report_markdown="", config_fingerprint={})
    full = build_summary(
        [_row("r1", 1, "claim_verified", {})],
        report_markdown="x",
        config_fingerprint={"global_token_cap": 140000},
    )
    assert set(empty) == set(full)


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
