from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.coding.commands.export import export_transcript
from neos.coding.commands.service import (
    CodingCommandService,
    cost_payload_from_loop_state,
    format_cost_line,
    format_help,
)
from neos.coding.commands.types import CommandStatus
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.phases import SteeringMode

pytestmark = pytest.mark.no_db


class _Runs:
    def __init__(self) -> None:
        self.steered: list[tuple[str, str, str]] = []
        self.stopped: list[str] = []

    async def steer(self, *, task_id, owner_id, instruction, mode):
        assert mode is SteeringMode.SAFE_POINT
        self.steered.append((task_id, owner_id, instruction))
        return SimpleNamespace(steering_id="cs_1")

    async def stop(self, *, task_id, owner_id):
        del owner_id
        self.stopped.append(task_id)


class _Snapshots:
    def __init__(self, snapshot=None, *, missing: bool = False) -> None:
        self.snapshot = snapshot
        self.missing = missing

    async def get_owned(self, task_id, owner_id):
        del task_id, owner_id
        if self.missing:
            return None
        return self.snapshot


@pytest.mark.asyncio
async def test_service_queues_compact_as_canonical_slash() -> None:
    runs = _Runs()
    service = CodingCommandService(runs=runs, snapshots=_Snapshots())
    result = await service.invoke(
        text="/compact keep plan", task_id="ct_1", owner_id="u1"
    )
    assert result.status is CommandStatus.QUEUED
    assert result.name == "compact"
    assert runs.steered == [("ct_1", "u1", "/compact keep plan")]


@pytest.mark.asyncio
async def test_service_denies_loop() -> None:
    runs = _Runs()
    service = CodingCommandService(runs=runs, snapshots=_Snapshots())
    result = await service.invoke(
        text="/loop 5m check deploy", task_id="ct_1", owner_id="u1"
    )
    assert result.status is CommandStatus.DENIED
    assert runs.steered == []
    assert "disabled" in result.message.lower()


@pytest.mark.asyncio
async def test_service_injects_plan_prompt() -> None:
    runs = _Runs()
    service = CodingCommandService(runs=runs, snapshots=_Snapshots())
    result = await service.invoke(text="/plan auth", task_id="ct_1", owner_id="u1")
    assert result.status is CommandStatus.QUEUED
    assert result.name == "plan"
    assert runs.steered[0][2].startswith("Switch to plan")
    assert "auth" in runs.steered[0][2]


@pytest.mark.asyncio
async def test_service_cost_reads_snapshot() -> None:
    snapshot = SimpleNamespace(
        latest_checkpoint=SimpleNamespace(
            loop_state={"cost_micros": 9, "input_tokens": 3, "output_tokens": 1}
        )
    )
    service = CodingCommandService(runs=_Runs(), snapshots=_Snapshots(snapshot))
    result = await service.invoke(text="/cost", task_id="ct_1", owner_id="u1")
    assert result.status is CommandStatus.OK
    assert result.payload["cost_micros"] == 9
    assert "9" in result.message


@pytest.mark.asyncio
async def test_service_export_redacts_and_omits_loop_state() -> None:
    snapshot = SimpleNamespace(
        latest_checkpoint=SimpleNamespace(
            loop_state={
                "secret": "should-not-leak",
                "transcript": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "token sk-" + ("a" * 20)}
                        ],
                    }
                ],
            }
        )
    )
    service = CodingCommandService(runs=_Runs(), snapshots=_Snapshots(snapshot))
    result = await service.invoke(text="/export", task_id="ct_1", owner_id="u1")
    assert result.status is CommandStatus.OK
    blob = str(result.payload)
    assert "should-not-leak" not in blob
    assert "sk-" not in blob
    assert result.payload["message_count"] == 1


@pytest.mark.asyncio
async def test_service_cost_missing_task() -> None:
    service = CodingCommandService(runs=_Runs(), snapshots=_Snapshots(missing=True))
    with pytest.raises(CodingTaskNotFound):
        await service.invoke(text="/cost", task_id="ct_missing", owner_id="u1")


def test_help_lists_loop_as_disabled() -> None:
    text = format_help()
    assert "/compact" in text
    assert "/loop [disabled]" in text
    assert "/clear" in text


def test_cost_line_and_export_helpers() -> None:
    payload = cost_payload_from_loop_state(
        {"cost_micros": 2, "input_tokens": 4, "output_tokens": 1}
    )
    assert format_cost_line("ct_1", payload) == "ct_1 cost_micros=2 tokens=4+1"
    windowed = cost_payload_from_loop_state(
        {
            "cost_micros": 9,
            "input_tokens": 4,
            "output_tokens": 1,
            "cache_read_tokens": 8,
            "cache_write_tokens": 3,
            "reasoning_tokens": 2,
        }
    )
    assert (
        format_cost_line("ct_1", windowed)
        == "ct_1 cost_micros=9 tokens=4+1 cache=8+3 reasoning=2"
    )
    exported = export_transcript(
        {"transcript": [{"role": "user", "content": [{"text": "hi"}]}]}
    )
    assert exported["messages"][0]["role"] == "user"
    assert "loop_state" not in exported
