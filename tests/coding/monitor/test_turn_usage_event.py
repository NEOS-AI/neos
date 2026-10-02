"""FB6 reads per-turn tokens from the ledger, so `model.completed` must carry them.

Before Q5 the tokens lived only in the checkpoint's running totals -- the
ledger could not say which turn spent what.
"""

from __future__ import annotations

import pytest

from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_a_tool_use_turn_records_its_own_tokens() -> None:
    h = harness(
        [
            [tool_call("r1", "read_file.v1", {"path": "a.py"}), completed(7, 2)],
            [completed(11, 4)],
        ]
    )

    events = [event async for event in h.loop.run(INPUT, None, h.deps)]

    turns = [e.payload for e in events if e.type == "model.completed"]
    assert turns[0]["input_tokens"] == 7
    assert turns[0]["output_tokens"] == 2
