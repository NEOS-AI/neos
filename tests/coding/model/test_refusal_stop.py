"""The adapter carries the refusal category out of the stream (roadmap K6).

`RawMessageDeltaEvent.delta.stop_details` is a `RefusalStopDetails` whose
`category` is one of cyber, bio, frontier_llm, reasoning_extraction or
general_harms. Without it the ledger records that a refusal happened but not
which policy produced it, which is the only part that tells an operator
whether the prompt or the task is at fault.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.coding.model.anthropic import AnthropicCodingModel
from tests.coding.model.test_anthropic import FakeAnthropicClient, event, request


def _stream(delta: SimpleNamespace) -> FakeAnthropicClient:
    return FakeAnthropicClient(
        [
            event(
                "message_start",
                message=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=11, output_tokens=0)
                ),
            ),
            event("message_delta", delta=delta, usage=SimpleNamespace(output_tokens=4)),
        ]
    )


@pytest.mark.asyncio
async def test_refusal_keeps_its_category() -> None:
    client = _stream(
        SimpleNamespace(
            stop_reason="refusal",
            stop_details=SimpleNamespace(
                type="refusal", category="cyber", explanation="Could enable harm."
            ),
        )
    )

    events = [item async for item in AnthropicCodingModel(client).stream(request())]

    assert events[-1].stop_reason == "refusal"
    assert events[-1].stop_category == "cyber"


@pytest.mark.asyncio
async def test_refusal_without_details_reports_no_category() -> None:
    client = _stream(SimpleNamespace(stop_reason="refusal", stop_details=None))

    events = [item async for item in AnthropicCodingModel(client).stream(request())]

    assert events[-1].stop_reason == "refusal"
    assert events[-1].stop_category == ""


@pytest.mark.asyncio
async def test_ordinary_turns_carry_no_category() -> None:
    client = _stream(SimpleNamespace(stop_reason="end_turn"))

    events = [item async for item in AnthropicCodingModel(client).stream(request())]

    assert events[-1].stop_reason == "end_turn"
    assert events[-1].stop_category == ""
