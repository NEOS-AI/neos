"""Remaining GEPA loop cases. Engine is async; tests drive it with fakes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neos.gepa_opt.engine import run_search
from neos.gepa_opt.types import EngineConfig

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]


def _run(coro):
    return asyncio.run(coro)


def _ok(score: float, info: dict | None = None):
    payload = {"ok": True} if info is None else info

    def evaluator(_candidate, _example):
        return (score, payload)

    return evaluator


def _reflector(text: str, delta: dict, *, finish_reason: str | None = "stop"):
    calls = {"n": 0, "prompts": []}

    def reflector(name, _curr, side_info_text):
        calls["n"] += 1
        calls["prompts"].append(side_info_text)
        return SimpleNamespace(
            component_name=name,
            delta=delta,
            usage=SimpleNamespace(input_tokens=2, output_tokens=3, finish_reason=finish_reason),
            text=text,
        )

    return reflector, calls


def test_empty_side_info_does_not_call_reflector() -> None:
    reflector, calls = _reflector("```\nb\n```", {"instr": "b"})
    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=4,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=_ok(0.5, {}),
            reflector=reflector,
        )
    )
    assert calls["n"] == 0
    assert result.component_cursor == 0
    assert result.status == "succeeded"


def test_minibatch_all_errors_fail_without_overlay() -> None:
    def evaluator(_candidate, example):
        if example.get("split") == "train":
            raise RuntimeError("train down")
        return (0.4, {"ok": True})

    def reflector(*_args):
        raise AssertionError("reflector must not be called")

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v", "split": "val"}],
            train=[{"id": "t", "split": "train"}],
            test=[],
            max_evals=20,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert result.status == "failed"
    assert result.error_code == "RuntimeError"
    assert result.overlay is None


def test_reflector_exception_fails_without_overlay() -> None:
    def reflector(*_args):
        raise ValueError("boom")

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=20,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=_ok(0.4, {"note": "x"}),
            reflector=reflector,
        )
    )
    assert result.status == "failed"
    assert result.error_code == "ValueError"
    assert result.overlay is None


def test_truncated_completion_bumps_cursor_and_continues() -> None:
    reflector, calls = _reflector("partial", {"instr": "b"}, finish_reason="length")
    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=4,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=_ok(0.4, {"note": "x"}),
            reflector=reflector,
        )
    )
    assert calls["n"] == 1
    assert result.status == "succeeded"
    assert result.component_cursor == 1
    assert [row["proposal_kind"] for row in result.candidates] == ["seed"]


def test_bad_delta_fails_without_advancing_cursor() -> None:
    reflector, _calls = _reflector("```\nb\n```", {"nope": "b"})
    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=20,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=_ok(0.4, {"note": "x"}),
            reflector=reflector,
        )
    )
    assert result.status == "failed"
    assert result.error_code == "bad_delta"
    assert result.overlay is None
    assert result.component_cursor == 0


def test_short_train_is_padded_to_three_parent_evals() -> None:
    seen = {"train": 0}

    def evaluator(_candidate, example):
        if example.get("id") == "t":
            seen["train"] += 1
        return (0.4, {"note": "x"})

    def reflector(*_args):
        return SimpleNamespace(
            component_name="instr",
            delta={"instr": "b"},
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, finish_reason="stop"),
            text="```\nb\n```",
        )

    _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=4,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert seen["train"] == 6


def test_test_payload_is_absent_from_reflector_prompt() -> None:
    reflector, calls = _reflector("```\nb\n```", {"instr": "b"})

    def evaluator(_candidate, _example):
        return (0.4, {"note": "train-val"})

    _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[{"id": "held", "secret": "UNIQUE_TEST_TOKEN"}],
            max_evals=20,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert calls["prompts"]
    assert all("UNIQUE_TEST_TOKEN" not in prompt for prompt in calls["prompts"])


def test_not_gepa_calls_reflector_once_and_stages_on_accept() -> None:
    reflector, calls = _reflector("```\nb\n```", {"instr": "b"})

    def evaluator(candidate, _example):
        return (0.9 if candidate["instr"] == "b" else 0.2, {"note": "x"})

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=20,
            max_token_cost=100,
            config=EngineConfig("not-gepa", False),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert calls["n"] == 1
    assert result.status == "succeeded"
    assert result.overlay["components"]["instr"] == "b"
    assert result.candidates[-1]["proposal_kind"] == "oneshot"


def test_seed_val_can_overshoot_max_evals() -> None:
    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v1"}, {"id": "v2"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=1,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=_ok(0.3, {"note": "x"}),
            reflector=lambda *_args: (_ for _ in ()).throw(AssertionError("no reflect")),
        )
    )
    assert result.evals_used >= 2
    assert result.status == "succeeded"
    assert result.overlay["components"]["instr"] == "a"


def test_rejected_child_is_not_the_next_parent() -> None:
    seen = []

    def evaluator(candidate, example):
        if example.get("id") == "v":
            return (0.2 if candidate["instr"] == "b" else 0.8, {"note": "x"})
        return (0.1 if candidate["instr"] == "b" else 0.6, {"note": "x"})

    def reflector(_name, curr, _side):
        seen.append(curr)
        return SimpleNamespace(
            component_name="instr",
            delta={"instr": "b"},
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, finish_reason="stop"),
            text="```\nb\n```",
        )

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=12,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert seen
    assert all(curr == "a" for curr in seen)
    assert any(row["accepted"] is False for row in result.candidates)


def test_large_side_info_is_stored_truncated() -> None:
    blob = {"note": "n" * 9000}

    def evaluator(_candidate, _example):
        return (0.4, blob)

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[],
            test=[],
            max_evals=10,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=lambda *_args: (_ for _ in ()).throw(AssertionError("no")),
        )
    )
    assert result.status == "failed"
    assert result.error_code == "empty_train"
    assert any(row["side_info"] == {"truncated": True} for row in result.score_rows)


def test_one_val_error_does_not_fail_the_seed() -> None:
    def evaluator(_candidate, example):
        if example.get("id") == "bad":
            raise TimeoutError("one")
        return (0.5, {"note": "x"})

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "bad"}, {"id": "good"}],
            train=[],
            test=[],
            max_evals=10,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=lambda *_a: None,
        )
    )
    assert result.error_code == "empty_train"
    assert result.candidates[0]["val_mean"] == pytest.approx(0.25)


def test_token_cost_counts_input_and_output_only() -> None:
    def reflector(*_args):
        return SimpleNamespace(
            component_name="instr",
            delta={"instr": "b"},
            usage=SimpleNamespace(
                input_tokens=2,
                output_tokens=3,
                cache_read_tokens=50,
                reasoning_tokens=7,
                finish_reason="stop",
            ),
            text="```\nb\n```",
        )

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=8,
            max_token_cost=5,
            config=EngineConfig("not-gepa", False),
            evaluator=_ok(0.4, {"note": "x"}),
            reflector=reflector,
        )
    )
    assert result.reflector_tokens_used == 5


def test_engine_sources_do_not_import_forbidden_modules() -> None:
    forbidden = ("gepa", "litellm", "pickle", "cloudpickle", "bwrap")
    for name in ("engine.py", "reflect.py", "pareto.py"):
        text = (_ROOT / "neos" / "gepa_opt" / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            for module in forbidden:
                assert not stripped.startswith(f"import {module}")
                assert not stripped.startswith(f"from {module}")
