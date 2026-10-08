"""A refusal is its own outcome, never a truncated turn (roadmap K6).

Fable 5.1 answers `stop_reason: "refusal"` with a `stop_details.category`.
Collapsed into `unknown` the loop had two wrong exits: a refusal carrying text
was raised as `model_output_incomplete` (the cause disappeared), and a refusal
carrying no text reached the empty-text retry and was sent again.
"""

from __future__ import annotations

import pytest

from neos.coding.loop.anthropic import CodingLoopFailure
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from tests.coding.loop.support import collect, harness

pytestmark = pytest.mark.no_db


def _refusal(category: str = "cyber") -> ModelCompleted:
    return ModelCompleted("refusal", ModelUsage(2, 1), stop_category=category)


@pytest.mark.asyncio
async def test_refusal_is_not_reported_as_truncated_output() -> None:
    h = harness([[TextDelta("I can't help with that."), _refusal()]])

    with pytest.raises(CodingLoopFailure) as caught:
        await collect(h)

    assert caught.value.code == "model_refused"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_refusal_reaches_the_ledger_with_its_category() -> None:
    h = harness([[TextDelta("I can't help with that."), _refusal("bio")]])

    with pytest.raises(CodingLoopFailure):
        await collect(h)

    refused = [item for item in h.events.items if item.type == "model.refused"]
    assert len(refused) == 1
    assert refused[0].payload["stop_reason"] == "refusal"
    assert refused[0].payload["stop_category"] == "bio"


@pytest.mark.asyncio
async def test_refusal_without_a_category_still_reaches_the_ledger() -> None:
    h = harness([[TextDelta("No."), ModelCompleted("refusal", ModelUsage(2, 1))]])

    with pytest.raises(CodingLoopFailure, match="model_refused"):
        await collect(h)

    refused = [item for item in h.events.items if item.type == "model.refused"]
    assert refused[0].payload["stop_category"] == ""


@pytest.mark.asyncio
async def test_empty_refusal_is_not_retried() -> None:
    h = harness(
        [
            [_refusal()],
            [TextDelta("second"), ModelCompleted("end_turn", ModelUsage(1, 1))],
        ]
    )

    with pytest.raises(CodingLoopFailure, match="model_refused"):
        await collect(h)

    assert len(h.model.requests) == 1
    assert h.model.turns, "the follow-up turn must never be asked for"
