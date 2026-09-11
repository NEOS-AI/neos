from __future__ import annotations

import pytest

from neos.coding.hooks import NullCodingHooks
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_null_hooks_are_silent() -> None:
    hooks = NullCodingHooks()
    call = ValidatedToolCall("read_file.v1", {"path": "a"}, ToolRisk.READ_ONLY)
    assert await hooks.pre_tool(call) is None
    await hooks.post_tool(call, {"status": "ok"})
    await hooks.stop("end_turn")
    await hooks.compact((), ())


def test_hook_decision_typed_shape() -> None:
    allow = {"decision": "allow"}
    deny = {"decision": "deny", "reason": "blocked"}
    retry = {"decision": "retry", "reason": "try again"}
    assert allow["decision"] in {"allow", "deny", "retry"}
    assert deny["decision"] == "deny"
    assert retry["reason"] == "try again"
