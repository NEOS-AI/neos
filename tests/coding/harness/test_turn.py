from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from neos.coding.harness import ModelTurn, collect_model_turn, iter_model_turn
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolInputDelta,
)
from neos.coding.model.errors import CodingModelError


def _request() -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=(CanonicalMessage("user", (TextContent("Inspect it"),)),),
        tools=(),
        model="claude-test",
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


class ScriptedModel:
    def __init__(self, events, *, error=None) -> None:
        self.events = list(events)
        self.error = error
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


@pytest.mark.asyncio
async def test_iter_model_turn_yields_before_the_stream_finishes() -> None:
    released = asyncio.Event()
    seen: list[object] = []

    class GatedModel:
        async def stream(self, request):
            yield TextDelta("hello")
            await released.wait()
            yield ModelCompleted("end_turn", ModelUsage(1, 1))

    async def consume() -> None:
        async for event in iter_model_turn(GatedModel(), _request()):
            seen.append(event)
            if isinstance(event, TextDelta):
                released.set()

    await asyncio.wait_for(consume(), timeout=2)
    assert isinstance(seen[0], TextDelta)
    assert seen[0].text == "hello"
    assert isinstance(seen[-1], ModelCompleted)


@pytest.mark.asyncio
async def test_collect_model_turn_collects_text_tools_and_completion() -> None:
    call = ToolCallCompleted("tool_1", "read_file.v1", {"path": "README.md"})
    completion = ModelCompleted("tool_use", ModelUsage(10, 4))
    model = ScriptedModel(
        (
            TextDelta("hello"),
            ToolInputDelta("tool_1", "read_file.v1", '{"path":'),
            call,
            completion,
        )
    )

    turn = await collect_model_turn(model, _request())

    assert turn == ModelTurn(
        text_parts=("hello",),
        tool_calls=(call,),
        completion=completion,
    )
    assert model.requests[0].turn_id == "turn_1"


@pytest.mark.asyncio
async def test_collect_model_turn_calls_on_event_in_stream_order() -> None:
    events = (
        TextDelta("hel"),
        TextDelta("lo"),
        ToolInputDelta("tool_1", "read_file.v1", '{"path":'),
        ToolCallCompleted("tool_1", "read_file.v1", {"path": "README.md"}),
        ModelCompleted("tool_use", ModelUsage(3, 2)),
    )
    seen: list[object] = []

    async def on_event(event) -> None:
        seen.append(("start", event))
        await asyncio.sleep(0)
        seen.append(("end", event))

    turn = await collect_model_turn(
        ScriptedModel(events), _request(), on_event=on_event
    )

    expected = []
    for event in events:
        expected.extend((("start", event), ("end", event)))
    assert seen == expected
    assert turn.text_parts == ("hel", "lo")
    assert turn.tool_calls == (events[3],)
    assert turn.completion is events[-1]


@pytest.mark.asyncio
async def test_collect_model_turn_propagates_coding_model_error() -> None:
    error = CodingModelError("model_rate_limited", retryable=True)
    seen: list[object] = []

    with pytest.raises(CodingModelError, match="model_rate_limited") as caught:
        await collect_model_turn(
            ScriptedModel((TextDelta("partial"),), error=error),
            _request(),
            on_event=seen.append,
        )

    assert caught.value is error
    assert caught.value.retryable is True
    assert seen == [TextDelta("partial")]


def test_importing_harness_turn_does_not_import_durable_loop() -> None:
    script = (
        "import sys\n"
        "import neos.coding.harness.turn as turn\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
        "assert 'DurableCodingLoop' not in vars(turn)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
