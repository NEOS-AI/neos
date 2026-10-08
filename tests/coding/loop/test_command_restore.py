from __future__ import annotations

import pytest

from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.loop.base import LoopInput
from neos.coding.model.base import ModelCompleted, ModelUsage
from tests.coding.loop.support import INPUT, NOW, harness

pytestmark = pytest.mark.no_db


def _checkpoint(h, instruction: str, **overrides) -> CodingCheckpoint:
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    dumped["pending_instruction"] = instruction
    dumped["instructions_loaded"] = True
    dumped["cost_micros"] = 42
    dumped["input_tokens"] = 5
    dumped["output_tokens"] = 3
    dumped.update(overrides)
    return CodingCheckpoint("cc_cmd", "ct_1", "cr_1", 1, dumped, "1", NOW)


def _user_texts(state) -> list[str]:
    return [
        item.text
        for message in state.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]


def test_restore_applies_compact_instead_of_user_work() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(INPUT, _checkpoint(h, "/compact keep plan"))
    texts = _user_texts(restored)
    assert restored.pending_instruction is None
    assert any("compacted by /compact" in text for text in texts)
    assert any("keep plan" in text.lower() for text in texts)
    assert "/compact keep plan" not in texts
    assert restored.instructions_loaded is False


def test_restore_clear_keeps_task_instruction() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(INPUT, _checkpoint(h, "/clear"))
    texts = _user_texts(restored)
    assert restored.pending_instruction is None
    assert INPUT.instruction in texts
    assert any("cleared" in text.lower() for text in texts)
    assert restored.todos == ()
    assert restored.compacted_bodies == {}


def test_restore_clear_does_not_reseed_slash_as_task() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    poisoned = LoopInput("ct_1", "cr_1", "/clear")
    checkpoint = _checkpoint(
        h,
        "/clear",
        current_instruction="/clear",
        transcript=[
            {"role": "user", "content": [{"type": "text", "text": "Fix the flaky test"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Looking"}]},
            {"role": "user", "content": [{"type": "text", "text": "also logs"}]},
        ],
    )
    restored = h.loop._restore(poisoned, checkpoint)
    texts = _user_texts(restored)
    assert restored.pending_instruction is None
    assert "Fix the flaky test" in texts
    assert "/clear" not in texts
    assert texts[-1] == "Conversation context was cleared."
    dumped = h.loop._dump_state(poisoned, restored)
    assert dumped["current_instruction"] == "Fix the flaky test"
    assert dumped["pending_instruction"] is None


def test_restore_denies_loop_and_does_not_schedule() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(
        INPUT, _checkpoint(h, "/loop 5m check the deploy")
    )
    texts = _user_texts(restored)
    assert restored.pending_instruction is None
    assert any("disabled" in text.lower() for text in texts)
    assert not any("check the deploy" == text for text in texts)


def test_restore_unknown_slash_is_not_user_work() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(INPUT, _checkpoint(h, "/not-real"))
    texts = _user_texts(restored)
    assert any("Unknown command" in text for text in texts)
    assert "/not-real" not in texts


def test_restore_plan_injects_prompt() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(INPUT, _checkpoint(h, "/plan auth flow"))
    texts = _user_texts(restored)
    assert any("Switch to plan" in text for text in texts)
    assert any("auth flow" in text for text in texts)


def test_restore_cost_uses_loop_counters() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    restored = h.loop._restore(INPUT, _checkpoint(h, "/cost"))
    texts = _user_texts(restored)
    assert any("cost_micros=42" in text for text in texts)
    assert any("5+3" in text for text in texts)
