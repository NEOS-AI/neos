from __future__ import annotations

import pytest

from neos.coding.hooks import NullCodingHooks, StopDecision
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_null_hooks_are_silent() -> None:
    hooks = NullCodingHooks()
    call = ValidatedToolCall("read_file.v1", {"path": "a"}, ToolRisk.READ_ONLY)
    assert await hooks.pre_tool(call) is None
    await hooks.post_tool(call, {"status": "ok"})
    assert await hooks.stop("end_turn") is None
    await hooks.compact((), ())


def test_hook_decision_typed_shape() -> None:
    allow = {"decision": "allow"}
    deny = {"decision": "deny", "reason": "blocked"}
    retry = {"decision": "retry", "reason": "try again"}
    assert allow["decision"] in {"allow", "deny", "retry"}
    assert deny["decision"] == "deny"
    assert retry["reason"] == "try again"


def test_stop_decision_allows_prevent_and_retry() -> None:
    prevent: StopDecision = {"decision": "prevent"}
    retry: StopDecision = {"decision": "retry", "reason": "missing verdict"}
    allow: StopDecision = {"decision": "allow"}
    assert prevent["decision"] in {"allow", "prevent", "retry"}
    assert retry["decision"] == "retry"
    assert allow["decision"] == "allow"
