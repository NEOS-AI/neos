import json
from pathlib import Path

import pytest
import yaml

from scripts.deep_analysis_diagnostician import build_summary, summary_field_paths

pytestmark = pytest.mark.no_db

PREREG = Path("scripts/diagnostician_backtest")


def _load(name: str) -> dict:
    return yaml.safe_load((PREREG / name).read_text(encoding="utf-8"))


def _row(run_id: str, seq: int, kind: str, payload: dict):
    return (run_id, seq, kind, json.dumps(payload))


def _exhaustive_summary() -> dict:
    """`build_summary`가 아는 모든 이벤트 kind를 한 번씩 낸 표본.

    동적 카운터(`events`/`gate.codes`/`budget.by_stage`/`stop_reasons`)의
    잎(leaf) 경로는 그 kind가 실제로 발생해야만 `summary_field_paths`에
    나타난다 -- 그래서 신호 지도가 이런 잎을 가리켰다면, 이 표본이 그
    kind를 내지 않는 한 존재 검증이 통과할 수 없다. #16의 결함(신호 지도가
    가리킨 `questions.open`/`questions.resolved`가 어떤 표본에도 존재한 적이
    없었던 것, D79 정정)이 사전 등록 단계에서 잡히려면 이 표본이 진짜로
    포괄적이어야 한다.
    """
    rows = [
        _row("r1", 1, "claim_verified", {}),
        _row("r1", 2, "claim_rejected", {}),
        _row("r1", 3, "entailment_filter_skipped", {}),
        _row("r1", 4, "report_assembly_degraded", {}),
        _row("r1", 5, "node_reduction_degraded", {}),
        _row("r1", 6, "llm_truncated", {}),
        _row("r1", 7, "token_budget_reserved",
             {"reservation_id": "a", "reserved_tokens": 10,
              "stage": "worker_analysis"}),
        _row("r1", 8, "token_budget_settled",
             {"reservation_id": "a", "actual_tokens": 5}),
        _row("r1", 9, "finalization_prompt_clamped", {
            "exhausted": True, "dropped_primary": 1,
            "primary_chars_after": 10, "anchor_chars_before": 20,
            "anchor_chars_after": 15, "distinct_claims_after": 3,
        }),
        _row("r1", 10, "report_graded",
             {"code": "OK", "judge": "present", "uncited_ratio": 0.1}),
        _row("r1", 11, "pass_completed",
             {"status": "completed", "tokens": 5, "verified": 1,
              "candidates": 2, "tier1": 1, "resolved_gate": "resolved"}),
        _row("r1", 12, "question_opened", {"depth": 0, "value_est": 1.0}),
        _row("r1", 13, "abandoned", {}),
        _row("r1", 14, "dead_end", {"text": "x"}),
        _row("r1", 15, "token_budget_exhausted", {}),
        _row("r1", 16, "investigation_stopped_at_floor", {}),
        _row("r1", 17, "investigation_stopped_at_input_bound", {}),
    ]
    return build_summary(
        rows, run_ids=["r1"],
        report_bodies={"r1": "본문[1]\n\n## 출처\n[1] x"},
        config_fingerprint={},
    )


def test_label_set_is_closed_and_sized():
    labels = _load("labels.yaml")["labels"]
    assert len(labels) == len(set(labels)), "라벨이 중복된다"
    assert len(labels) == 17


def test_every_key_label_is_in_the_closed_set():
    labels = set(_load("labels.yaml")["labels"])
    samples = _load("answer_key.yaml")["samples"]
    for sample_id, entry in samples.items():
        for field in ("truth", "contemporaneous"):
            unknown = set(entry[field]) - labels
            assert not unknown, f"#{sample_id} {field}에 집합 밖 라벨: {unknown}"


def test_answer_key_covers_samples_11_through_16():
    samples = _load("answer_key.yaml")["samples"]
    assert set(samples) == {"11", "12", "13", "14", "15", "16"}
    for entry in samples.values():
        assert entry["quote"], "인용 없는 정답은 근거 없는 정답이다"
        assert entry["decision"].startswith("D")


def test_signal_map_covers_every_label():
    labels = set(_load("labels.yaml")["labels"])
    signals = _load("signal_map.yaml")["signals"]
    assert set(signals) == labels, "라벨과 신호 지도가 어긋난다"


def test_signal_map_paths_resolve_in_the_summary_schema():
    """신호 지도의 경로가 실제로 존재하는 요약 필드를 가리키는가.

    이름만 맞고 존재하지 않는 경로를 가리키면 그 라벨의 `evidence_on_target`은
    구조적으로 영원히 거짓이 된다 -- #16이 그렇게 죽었다(`questions.open`/
    `questions.resolved`, D79 정정). 이 테스트는 라벨 집합의 일치만 보던
    `test_signal_map_covers_every_label`이 놓친 자리를 채운다: 모든 이벤트
    kind를 한 번씩 낸 포괄적 표본(`_exhaustive_summary`)에 대해
    `summary_field_paths`를 계산하고, 신호 지도의 모든 경로가 거기 있는지
    확인한다. `instrumentation`처럼 빈 목록(`[]`)인 라벨은 검증할 경로가
    없다는 것 자체가 주장이므로 건너뛴다.
    """
    signals = _load("signal_map.yaml")["signals"]
    valid_paths = summary_field_paths(_exhaustive_summary())

    missing: dict[str, list[str]] = {}
    for label, paths in signals.items():
        absent = [path for path in paths if path not in valid_paths]
        if absent:
            missing[label] = absent
    assert not missing, f"신호 지도가 존재하지 않는 경로를 가리킨다: {missing}"
