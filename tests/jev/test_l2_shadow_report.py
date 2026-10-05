"""L2 섀도 판독기 (`scripts/jev_l2_shadow_report.py`) · 섀도 오버레이."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import jev_l2_shadow_report as report

pytestmark = pytest.mark.no_db


def scored(p_irr: float, p_exf: float, *, static="allow", jev="allow", call="c"):
    return {
        "event_type": "jev_risk_scored",
        "task_id": "t",
        "tool_call_id": call,
        "payload": {
            "tool": "execute.v1",
            "static_outcome": static,
            "banded_outcome": jev,
            "would_be_outcome": jev,
            "enforced": False,
            "questions": [
                {"name": "irreversible", "probability": p_irr},
                {"name": "exfiltration", "probability": p_exf},
            ],
        },
    }


def unavailable(reason: str):
    return {
        "event_type": "jev_unavailable",
        "task_id": "t",
        "tool_call_id": "u",
        "payload": {"reason": reason, "static_outcome": "allow", "enforced": False},
    }


def test_rates_count_blocks_apart_from_other_failures():
    rows = [scored(0.1, 0.1), scored(0.1, 0.1), unavailable("provider_blocked"), unavailable("TimeoutError")]
    out = report.summarize(rows)
    assert out["calls"] == 4
    assert out["unavailable_rate"] == 0.5
    assert out["provider_blocked_rate"] == 0.25


def test_only_calls_jev_would_have_narrowed_are_listed():
    rows = [
        scored(0.1, 0.1, call="same"),
        scored(0.1, 0.61, jev="require_approval", call="narrowed"),
    ]
    out = report.summarize(rows)
    assert [d["tool_call_id"] for d in out["disagreements"]] == ["narrowed"]
    assert out["disagreements"][0]["probabilities"]["exfiltration"] == 0.61


def test_a_blocked_call_that_narrows_is_a_disagreement_too():
    row = unavailable("provider_blocked")
    row["payload"]["would_be_outcome"] = "require_approval"
    assert len(report.summarize([row])["disagreements"]) == 1


def test_candidate_bounds_reband_the_recorded_probabilities():
    rows = [scored(0.05, 0.61), scored(0.75, 0.02), scored(0.95, 0.3)]
    out = report.summarize(rows, [report.Bounds.parse("0.2:0.9"), report.Bounds.parse("0.3:0.7")])
    assert out["rebanded"]["0.2:0.9"]["irreversible"] == {"low": 1, "mid": 1, "high": 1}
    # 0.3 은 LOW 가 아니다 -- `p < low_below` 다(게이트의 밴딩과 같은 경계 규칙).
    assert out["rebanded"]["0.3:0.7"]["exfiltration"] == {"low": 1, "mid": 2}


def test_histogram_puts_one_in_the_top_bin():
    assert report.histogram([0.0, 0.95, 1.0]) == [1, 0, 0, 0, 0, 0, 0, 0, 0, 2]


def test_bounds_must_be_ordered():
    with pytest.raises(ValueError):
        report.Bounds.parse("0.9:0.2")


def test_the_shadow_overlay_loads_as_shadow_only(tmp_path, monkeypatch):
    """오버레이가 기동을 통과하고, **게이트는 꺼져 있다**."""
    from neos.config import loader
    from neos.jev.assembly import _noul_questions

    overlay = Path("config/samples/jev-l2-shadow.yaml")
    monkeypatch.setattr(loader, "DEFAULT_DOTENV_PATH", tmp_path / "missing.env")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "neos-test-placeholder")
    monkeypatch.setenv("NEOS_TRIGGER_SIGNING_KEY", "neos-test-trigger-signing-key-placeholder")
    monkeypatch.setenv("NEOS_SECRET_BROKER_KEY", "neos-test-secret-broker-key-placeholder")
    jev = loader.load_app_config(config_path=str(overlay)).jev
    assert jev.enabled and jev.tool_risk_shadow_enabled
    assert jev.tool_risk_gate_enabled is False
    assert set(jev.question_thresholds) == set(_noul_questions(jev.tool_risk_rubric))
    assert "tool_risk_gate_enabled" not in yaml.safe_load(overlay.read_text())["jev"]
