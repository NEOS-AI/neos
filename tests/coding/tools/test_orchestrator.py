from __future__ import annotations

import pytest

from neos.coding.tools.orchestrator import partition_leading_readonly
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


def _call(name: str, risk: ToolRisk) -> ValidatedToolCall:
    return ValidatedToolCall(name, {"path": "a"} if risk is not ToolRisk.COMMAND else {"argv": ["pytest"]}, risk)


def test_empty_calls_yield_empty_partitions() -> None:
    batch, rest = partition_leading_readonly(())
    assert batch == ()
    assert rest == ()


def test_leading_readonly_are_batched_until_max() -> None:
    calls = tuple(_call(f"read_{i}", ToolRisk.READ_ONLY) for i in range(12))
    batch, rest = partition_leading_readonly(calls, max_batch=10)
    assert [item.name for item in batch] == [f"read_{i}" for i in range(10)]
    assert [item.name for item in rest] == ["read_10", "read_11"]


def test_write_stops_the_readonly_batch() -> None:
    calls = (
        _call("read_file.v1", ToolRisk.READ_ONLY),
        _call("search_text.v1", ToolRisk.READ_ONLY),
        _call("write_file.v1", ToolRisk.WORKSPACE_WRITE),
        _call("read_file.v1", ToolRisk.READ_ONLY),
    )
    batch, rest = partition_leading_readonly(calls)
    assert [item.name for item in batch] == ["read_file.v1", "search_text.v1"]
    assert [item.name for item in rest] == ["write_file.v1", "read_file.v1"]


def test_leading_mutate_is_a_singleton_rest() -> None:
    calls = (
        _call("write_file.v1", ToolRisk.WORKSPACE_WRITE),
        _call("read_file.v1", ToolRisk.READ_ONLY),
    )
    batch, rest = partition_leading_readonly(calls)
    assert batch == ()
    assert [item.name for item in rest] == ["write_file.v1", "read_file.v1"]
