"""Q14a in the loop: the parent binds its own task's browser, and the task's end closes it.

Real `DurableCodingLoop` (via the Anthropic harness) and real `SandboxToolExecutor`;
the browser is the fake driver from `tests/coding/test_agent_browser.py`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.coding.tools.executor import SandboxToolExecutor
from tests.coding.loop.test_anthropic_loop import INPUT, completed, harness, tool_call
from tests.coding.test_agent_browser import (
    FakeDriver,
    World,
    _enable,
    _registry,
    _resolve,
    _sessions,
)

pytestmark = pytest.mark.no_db

NAV = {"action": "navigate", "url": "https://docs.example.com/"}


def _loop(monkeypatch, sessions):
    _enable(monkeypatch)
    _resolve(monkeypatch)
    h = harness(
        [
            [tool_call("b1", "browser.v1", NAV), completed()],
            [TextDelta("done"), ModelCompleted("end_turn", ModelUsage(5, 3))],
        ],
        executor=SandboxToolExecutor(1 << 20, 10),
    )
    h.loop._tools = _registry()
    h.loop._browser = sessions
    return h


async def _step(h, checkpoint=None):
    return [e async for e in h.loop.run(replace(INPUT, owner_id="alice"), checkpoint, h.deps)]


@pytest.mark.asyncio
async def test_the_parent_browses_and_the_tasks_end_closes_the_session(monkeypatch) -> None:
    """W6. Mutation: drop the terminal close in `DurableCodingLoop.run` -> the context
    outlives its task until the idle sweep."""
    driver = FakeDriver(World(snapshot='- heading "Hello docs" [ref=e1]'))
    sessions = _sessions(driver)
    h = _loop(monkeypatch, sessions)

    events = []
    checkpoint = None
    for _ in range(6):
        events += await _step(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1] if h.repository.checkpoints else None
        if driver.contexts and driver.contexts[0].closed:
            break

    completed_tools = [e for e in events if e.type == "tool.completed"]
    assert completed_tools, [e.type for e in events]
    assert "Hello docs" in repr(completed_tools[0].payload)
    assert driver.contexts[0].closed
    assert not sessions.is_open("ct_1")


@pytest.mark.asyncio
async def test_off_the_loop_never_hands_the_executor_a_browser(monkeypatch) -> None:
    """W11: `_browser is None` -> `execute()` is called exactly as before (no kwarg)."""
    seen = []

    class Recording(SandboxToolExecutor):
        async def execute(self, session, call, **kwargs):
            seen.append(sorted(kwargs))
            return await super().execute(session, call, **kwargs)

    h = harness(
        [
            [tool_call("r1", "read_file.v1", {"path": "a.txt"}), completed()],
            [TextDelta("done"), ModelCompleted("end_turn", ModelUsage(2, 1))],
        ],
        executor=Recording(4096, 10),
    )
    await _step(h)
    await _step(h, h.repository.checkpoints[-1])

    assert seen and all("browser" not in kwargs for kwargs in seen)
