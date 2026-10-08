"""Thinking reaches the UI as a bounded status line (roadmap K4a).

Fable 5.1 writes less user-facing text during long tool chains, so a turn can
look silent for minutes. The model's running notes arrive as thinking blocks,
which the loop already captures and replays (K1) but never showed anyone.

What goes to the ledger is a preview, not the block: the signature is opaque
and proves provenance, so it has no business in a display event, and a full
block is the wrong size for one status line.
"""

from __future__ import annotations

import pytest

from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ThinkingCompleted,
)
from tests.coding.loop.support import collect, harness

pytestmark = pytest.mark.no_db


def _thinking_events(h):
    return [item for item in h.events.items if item.type == "model.thinking"]


@pytest.mark.asyncio
async def test_a_thinking_block_becomes_one_status_event() -> None:
    h = harness(
        [
            [
                ThinkingCompleted("Reading the config first.", "sig-1"),
                TextDelta("done"),
                ModelCompleted("end_turn", ModelUsage(2, 1)),
            ]
        ]
    )

    await collect(h)

    events = _thinking_events(h)
    assert len(events) == 1
    assert events[0].payload["preview"] == "Reading the config first."
    assert events[0].payload["truncated"] is False


@pytest.mark.asyncio
async def test_the_signature_never_reaches_the_ledger() -> None:
    h = harness(
        [
            [
                ThinkingCompleted("Checking.", "sig-secret"),
                ModelCompleted("end_turn", ModelUsage(1, 1)),
            ]
        ]
    )

    await collect(h)

    payload = _thinking_events(h)[0].payload
    assert "signature" not in payload
    assert "sig-secret" not in str(payload)


@pytest.mark.asyncio
async def test_a_long_block_is_clipped_and_says_so() -> None:
    h = harness(
        [
            [
                ThinkingCompleted("x" * 5000, "sig-1"),
                ModelCompleted("end_turn", ModelUsage(1, 1)),
            ]
        ]
    )

    await collect(h)

    payload = _thinking_events(h)[0].payload
    assert payload["truncated"] is True
    assert len(payload["preview"]) < 5000
    assert payload["chars"] == 5000


@pytest.mark.asyncio
async def test_every_block_in_a_turn_gets_its_own_line() -> None:
    h = harness(
        [
            [
                ThinkingCompleted("First I read.", "sig-1"),
                ThinkingCompleted("Now I edit.", "sig-2"),
                ModelCompleted("end_turn", ModelUsage(1, 1)),
            ]
        ]
    )

    await collect(h)

    assert [item.payload["preview"] for item in _thinking_events(h)] == [
        "First I read.",
        "Now I edit.",
    ]


@pytest.mark.asyncio
async def test_a_turn_without_thinking_emits_nothing() -> None:
    h = harness([[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(1, 1))]])

    await collect(h)

    assert _thinking_events(h) == []
