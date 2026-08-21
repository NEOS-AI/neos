from pathlib import Path

import yaml

from scripts.deep_analysis_diagnostician import (
    constant_best,
    score_sample,
    summary_field_paths,
)


def _c(label, evidence=("clamp.exhausted",)):
    return {"label": label, "evidence": list(evidence), "reason": "왜냐하면"}


def test_recall_counts_the_fraction_of_truth_labels_found():
    result = score_sample(
        [_c("assembly_clamp"), _c("gate_definition"), _c("judge_budget")],
        truth=["assembly_clamp", "degraded_join"],
        contemporaneous=["assembly_clamp", "degraded_join"],
        valid_paths={"clamp.exhausted"},
    )
    assert result["recall"] == 0.5
    assert result["hits"] == ["assembly_clamp"]


def test_a_candidate_citing_a_path_absent_from_the_summary_is_discarded():
    """근거 없는 문장은 판정 대상이 아니라 폐기 대상이다 (설계 §13.2).

    근거 단위는 이제 `run_id:seq` 이벤트 id가 아니라 요약의 점(`.`) 표기
    필드 경로다 -- 요약에 이벤트 id가 아예 없어서(정정 사유), 요약에
    실제로 존재하는 경로만 유효하다.
    """
    result = score_sample(
        [_c("assembly_clamp", evidence=["clamp.does_not_exist"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp.exhausted"},
    )
    assert result["discarded"] == ["assembly_clamp"]
    assert result["recall"] == 0.0


def test_a_candidate_citing_nothing_is_discarded():
    result = score_sample(
        [_c("assembly_clamp", evidence=[])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp.exhausted"},
    )
    assert result["discarded"] == ["assembly_clamp"]
    assert result["recall"] == 0.0


def test_an_intermediate_path_is_a_valid_citation():
    """`clamp.exhausted`뿐 아니라 `clamp` 자체도 인용 가능하다 (태스크 3)."""
    result = score_sample(
        [_c("assembly_clamp", evidence=["clamp"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp", "clamp.exhausted"},
    )
    assert result["kept"] == ["assembly_clamp"]


def test_reproducing_the_contemporaneous_answer_is_recorded_separately():
    """#13처럼 두 칸이 갈리는 표본에서 '계측 부족'을 가려낸다."""
    result = score_sample(
        [_c("instrumentation")],
        truth=["assembly_clamp"],
        contemporaneous=["instrumentation"],
        valid_paths={"clamp.exhausted"},
    )
    assert result["recall"] == 0.0
    assert result["reproduced_contemporaneous"] is True


def test_evidence_on_target_is_recorded_but_absent_without_a_signal_map():
    result = score_sample(
        [_c("assembly_clamp", evidence=["clamp.exhausted"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp.exhausted"},
    )
    assert "evidence_on_target" not in result


def test_evidence_on_target_true_when_the_cited_path_matches_the_signal_map():
    result = score_sample(
        [_c("assembly_clamp", evidence=["clamp.exhausted"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp.exhausted"},
        signal_map={"assembly_clamp": ["clamp.exhausted", "clamp.dropped_primary"]},
    )
    assert result["evidence_on_target"] == [
        {"label": "assembly_clamp", "on_target": True}
    ]


def test_evidence_on_target_false_when_the_cited_path_is_off_the_signal_map():
    """기록만 한다 -- recall이나 폐기에는 영향이 없다 (태스크 4)."""
    result = score_sample(
        [_c("assembly_clamp", evidence=["gate.codes"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"gate.codes", "clamp.exhausted"},
        signal_map={"assembly_clamp": ["clamp.exhausted"]},
    )
    assert result["evidence_on_target"] == [
        {"label": "assembly_clamp", "on_target": False}
    ]
    # off-target 이어도 유효한 경로를 댔으므로 폐기되지 않고, recall은 그대로다.
    assert result["kept"] == ["assembly_clamp"]
    assert result["recall"] == 1.0


def test_discarded_candidates_get_no_evidence_on_target_entry():
    result = score_sample(
        [_c("assembly_clamp", evidence=["clamp.missing"])],
        truth=["assembly_clamp"],
        contemporaneous=["assembly_clamp"],
        valid_paths={"clamp.exhausted"},
        signal_map={"assembly_clamp": ["clamp.exhausted"]},
    )
    assert result["discarded"] == ["assembly_clamp"]
    assert result["evidence_on_target"] == []


def test_summary_field_paths_enumerates_leaves_and_intermediate_nodes():
    """`clamp.exhausted`도, `clamp`도 둘 다 인용 가능해야 한다 (태스크 3)."""
    paths = summary_field_paths({
        "clamp": {"exhausted": 1, "dropped_primary": 0},
        "budget": {"by_stage": {"worker_analysis": {"reserved": 100}}},
    })
    assert "clamp" in paths
    assert "clamp.exhausted" in paths
    assert "clamp.dropped_primary" in paths
    assert "budget" in paths
    assert "budget.by_stage" in paths
    assert "budget.by_stage.worker_analysis" in paths
    assert "budget.by_stage.worker_analysis.reserved" in paths


def test_summary_field_paths_of_an_empty_summary_is_empty():
    assert summary_field_paths({}) == set()


def test_constant_best_finds_the_strongest_fixed_prediction():
    """아무것도 읽지 않는 예측기의 점수. 이것이 구속력 있는 기준선이다."""
    key = {
        "11": {"truth": ["assembly_clamp", "degraded_join"]},
        "12": {"truth": ["budget_floor_formula"]},
        "13": {"truth": ["assembly_clamp"]},
        "14": {"truth": ["assembly_clamp", "instrumentation"]},
        "15": {"truth": ["assembly_clamp"]},
        "16": {"truth": ["subquestion_coverage"]},
    }
    labels = ["assembly_clamp", "degraded_join", "instrumentation",
              "budget_floor_formula", "subquestion_coverage", "gate_definition"]
    # The best k-combination must be found by exhaustive search, not hand-picked.
    # The actual maximum is 5/6 from {assembly_clamp, budget_floor_formula, subquestion_coverage}.
    assert abs(constant_best(key, labels) - 5 / 6) < 1e-9


def test_the_real_key_baseline_matches_what_the_key_records():
    """기준선이 조용히 바뀌면 관문의 의미가 바뀐다.

    `answer_key.yaml` 이 `baseline_constant_best` 를 스스로 적어두고, 이
    테스트가 계산값과 대조한다. 정답키를 고치면 여기서 실패하고, 그때는
    스펙 §6의 관문(>= constant_best)을 다시 계산해야 한다.

    ⚠️ 값을 손으로 박지 않는다 -- 계획 작성 중 4/6 이라고 박았다가 실제
    최선 조합이 5/6 인 것을 놓칠 뻔했다.
    """
    prereg = Path("scripts/diagnostician_backtest")
    key_doc = yaml.safe_load((prereg / "answer_key.yaml").read_text())
    labels = yaml.safe_load((prereg / "labels.yaml").read_text())["labels"]
    computed = constant_best(key_doc["samples"], labels)
    recorded = key_doc["baseline_constant_best"]
    assert abs(computed - recorded) < 1e-9, (
        f"정답키가 적은 기준선 {recorded:.3f} 과 계산값 {computed:.3f} 이 다르다"
    )
