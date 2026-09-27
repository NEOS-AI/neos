"""Search engine contract tests. The engine module is imported, not defined here."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neos.gepa_opt.engine import run_search
from neos.gepa_opt.types import EngineConfig

pytestmark = pytest.mark.no_db


def _run(coro):
    return asyncio.run(coro)


def test_all_error_val_fails_without_overlay() -> None:
    calls = {"n": 0}

    def evaluator(*_args, **_kwargs):
        raise RuntimeError("val failed")

    def reflector(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("reflector must not be called")

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=10,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert calls["n"] == 0
    assert result.status == "failed"
    assert result.overlay is None
    assert result.error_code == "RuntimeError"


def test_empty_train_fails() -> None:
    def evaluator(*_args, **_kwargs):
        return (1.0, {"ok": True})

    def reflector(*_args, **_kwargs):
        raise AssertionError("reflector must not be called")

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
            reflector=reflector,
        )
    )
    assert result.error_code == "empty_train"
    assert result.overlay is None


def test_skip_perfect_does_not_call_reflector() -> None:
    calls = {"n": 0}

    def evaluator(*_args, **_kwargs):
        return (1.0, {"ok": True})

    def reflector(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("reflector must not be called")

    result = _run(
        run_search(
            seed={"instr": "a"},
            val=[{"id": "v"}],
            train=[{"id": "t"}],
            test=[],
            max_evals=3,
            max_token_cost=100,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert calls["n"] == 0
    assert result.component_cursor == 0


def test_accept_stages_overlay() -> None:
    def evaluator(candidate, *_args, **_kwargs):
        instr = candidate["instr"] if isinstance(candidate, dict) else getattr(candidate, "instr")
        if instr == "a":
            return (0.5, {"note": "x"})
        if instr == "b":
            return (0.9, {"note": "y"})
        raise AssertionError(f"unexpected instr {instr!r}")

    def reflector(*_args, **_kwargs):
        return SimpleNamespace(
            component_name="instr",
            delta={"instr": "b"},
            usage=SimpleNamespace(
                input_tokens=2,
                output_tokens=3,
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
            max_evals=20,
            max_token_cost=1000,
            config=EngineConfig("gepa", True),
            evaluator=evaluator,
            reflector=reflector,
        )
    )
    assert result.status == "succeeded"
    assert result.overlay["status"] == "staged"
    assert result.overlay["components"]["instr"] == "b"
