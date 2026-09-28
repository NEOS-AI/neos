import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-gepa-opt-not-a-real-key")

from pathlib import Path

import pytest

from neos.config.settings import settings
from neos.gepa_opt.inject import coding_turn_overlay, load_approved_components

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]


async def test_flag_off_returns_same_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", False)
    static = "code"
    result = await coding_turn_overlay(static, "owner")
    assert result is static


async def test_flag_on_missing_components_returns_static(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", True)

    async def _none(owner_id: str) -> None:
        assert owner_id == "owner"
        return None

    monkeypatch.setattr("neos.gepa_opt.inject.load_approved_components", _none)
    result = await coding_turn_overlay("code", "owner")
    assert result == "code"


async def test_flag_on_appends_sorted_components(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", True)
    long_body = "first " * 200
    assert len(long_body) > 400
    components = {"b": "second", "a": long_body}

    async def _components(owner_id: str) -> dict[str, str]:
        assert owner_id == "owner"
        return components

    monkeypatch.setattr("neos.gepa_opt.inject.load_approved_components", _components)
    static = "code\nYou must keep the static sentence."
    result = await coding_turn_overlay(static, "owner")
    assert result.endswith(long_body + "\n### b\nsecond") or result.endswith("second")
    assert long_body in result
    assert "second" in result
    assert result.endswith("second")
    assert "## Optimized overlay" in result
    assert result.index("### a") < result.index("### b")
    assert "may be stale" not in result
    assert "You must keep the static sentence." in result


async def test_component_you_must_sentence_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", True)
    sentence = "You must keep this sentence."

    async def _components(owner_id: str) -> dict[str, str]:
        return {"rule": sentence}

    monkeypatch.setattr("neos.gepa_opt.inject.load_approved_components", _components)
    result = await coding_turn_overlay("code", "owner")
    assert sentence in result
    assert "may be stale" not in result


async def test_missing_store_leaves_the_prompt_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", True)
    monkeypatch.setattr(
        "neos.learn.lessons.resolve_lesson_session_factory",
        lambda: None,
    )
    assert await load_approved_components("owner") is None
    assert await coding_turn_overlay("code", "owner") == "code"


async def test_store_errors_leave_the_prompt_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.config.learn, "gepa_overlay", True)

    def _boom() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("neos.learn.lessons.resolve_lesson_session_factory", _boom)
    assert await load_approved_components("owner") is None
    assert await coding_turn_overlay("code", "owner") == "code"


def test_stepper_does_not_reference_coding_turn_overlay() -> None:
    source = (_ROOT / "neos" / "subagent" / "stepper.py").read_text(encoding="utf-8")
    assert "coding_turn_overlay" not in source
    assert "coding_turn_system" not in source


def test_model_turn_overlay_sits_between_summary_and_hook() -> None:
    source = (_ROOT / "neos" / "coding" / "loop" / "_durable" / "model_turn.py").read_text(
        encoding="utf-8"
    )
    summary_at = source.index("system = inject_previous_summary(system, state.summary)")
    overlay_at = source.index("system = await coding_turn_overlay(system, input.owner_id)")
    hook_at = source.index('system_note = str(note.get("system") or "")')
    assert summary_at < overlay_at < hook_at
    assert source.index("invoke_pre_generate") < overlay_at