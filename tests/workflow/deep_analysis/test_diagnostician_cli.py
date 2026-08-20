"""`write_artifacts`가 남기는 영수증 -- DB도, LLM도 건드리지 않는다.

`scripts/deep_analysis_diagnostician.py`의 `main()`/`load_sample()`은 DB와
LLM을 부르므로 여기서 테스트하지 않는다 (Task 6이 별도 승인 아래 실행한다).
이 파일은 순수 파일시스템 함수인 `write_artifacts`만 다룬다.
"""
import json

import pytest

from scripts.deep_analysis_diagnostician import write_artifacts

pytestmark = pytest.mark.no_db


def test_artifacts_keep_the_input_the_diagnostician_actually_saw(tmp_path):
    """빗나갔을 때 '그 신호가 요약에 있었나'를 사람이 확인해야 한다.

    입력을 남기지 않으면 그 질문에 영원히 답할 수 없다 (스펙 §7).
    """
    out = write_artifacts(
        tmp_path,
        manifest={"model": "claude-opus-5", "repeats": 3},
        inputs={"11": {"events": {"claim_verified": 3}}},
        outputs={"11": [{"candidates": [], "failure": None}]},
        score={"mean_recall": 0.5, "constant_best": 4 / 6},
    )
    assert (out / "manifest.json").exists()
    assert json.loads((out / "inputs/11.json").read_text())["events"][
        "claim_verified"
    ] == 3
    assert json.loads((out / "score.json").read_text())["constant_best"] > 0


def test_manifest_records_what_would_change_the_score(tmp_path):
    out = write_artifacts(
        tmp_path,
        manifest={"model": "claude-opus-5", "repeats": 3,
                  "answer_key_sha": "abc123", "git_tree_clean": True},
        inputs={}, outputs={}, score={},
    )
    manifest = json.loads((out / "manifest.json").read_text())
    for field in ("model", "repeats", "answer_key_sha", "git_tree_clean"):
        assert field in manifest


def test_outputs_are_written_per_repetition_under_the_sample_id(tmp_path):
    """`outputs`는 반복마다 별도 파일이다 -- 한 표본의 세 반복 결과가

    하나로 뭉개지면 어느 반복이 실패했는지 사람이 재구성할 수 없다.
    """
    out = write_artifacts(
        tmp_path,
        manifest={"model": "claude-opus-5", "repeats": 2},
        inputs={},
        outputs={
            "12": [
                {"candidates": [{"label": "budget_floor_formula"}],
                 "failure": None},
                {"candidates": [], "failure": "provider_error"},
            ]
        },
        score={},
    )
    first = json.loads((out / "outputs/12-0.json").read_text())
    second = json.loads((out / "outputs/12-1.json").read_text())
    assert first["failure"] is None
    assert second["failure"] == "provider_error"
