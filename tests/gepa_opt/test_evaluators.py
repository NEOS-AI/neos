"""Evaluator registry. No default coding fitness and no status scorer."""

from __future__ import annotations

import pytest

from neos.gepa_opt.evaluators import clear_evaluators, get_evaluator, register_evaluator

pytestmark = pytest.mark.no_db


def setup_function() -> None:
    clear_evaluators()


def test_registered_fake_is_the_function_that_is_called() -> None:
    def score(_candidate, _example):
        return (1.0, {"ok": True})

    register_evaluator("coding_overlay", score)
    assert get_evaluator("coding_overlay") is score
    assert get_evaluator("coding_overlay")({"instr": "a"}, {"id": "t"})[0] == 1.0


def test_registry_rejects_a_scorer_that_reads_task_status() -> None:
    def score(_candidate, _example):
        label = "CodingTaskStatus"
        return (0.0, {"saw": label})

    with pytest.raises(ValueError):
        register_evaluator("coding_overlay", score)
    assert get_evaluator("coding_overlay") is None


def test_registry_rejects_a_scorer_that_reads_verdict() -> None:
    def score(_candidate, _example):
        label = "VERDICT"
        return (0.0, {"saw": label})

    with pytest.raises(ValueError):
        register_evaluator("coding_overlay", score)


def test_evaluators_module_does_not_import_deep_analysis_graders() -> None:
    from pathlib import Path

    text = Path("neos/gepa_opt/evaluators.py").read_text(encoding="utf-8")
    assert "deep_analysis" not in text
    assert "judge.md" in text
    assert "report_judge.md" in text
