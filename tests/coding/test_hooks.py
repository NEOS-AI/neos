from __future__ import annotations

import pytest

from neos.coding.hooks import (
    HookDecision,
    NullCodingHooks,
    StopDecision,
    post_tool_prevented,
)
from neos.coding.loop.hooks import invoke_post_generate, invoke_pre_generate
from neos.coding.model.base import CanonicalMessage, TextContent
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_null_hooks_are_silent() -> None:
    hooks = NullCodingHooks()
    call = ValidatedToolCall("read_file.v1", {"path": "a"}, ToolRisk.READ_ONLY)
    assert await hooks.pre_tool(call) is None
    assert await hooks.post_tool(call, {"status": "ok"}) is None
    assert await hooks.stop("end_turn") is None
    await hooks.compact((), ())
    assert await hooks.pre_generate(()) is None
    assert await hooks.post_generate("ok", ()) is None


def test_hook_decision_typed_shape() -> None:
    allow: HookDecision = {"decision": "allow"}
    deny: HookDecision = {"decision": "deny", "reason": "blocked"}
    retry: HookDecision = {"decision": "retry", "reason": "try again"}
    prevent: HookDecision = {"decision": "prevent", "reason": "stop now"}
    assert allow["decision"] in {"allow", "deny", "retry", "prevent"}
    assert deny["decision"] == "deny"
    assert retry["reason"] == "try again"
    assert prevent["decision"] == "prevent"


def test_stop_decision_allows_prevent_and_retry() -> None:
    prevent: StopDecision = {"decision": "prevent"}
    retry: StopDecision = {"decision": "retry", "reason": "missing verdict"}
    allow: StopDecision = {"decision": "allow"}
    assert prevent["decision"] in {"allow", "prevent", "retry"}
    assert retry["decision"] == "retry"
    assert allow["decision"] == "allow"


def test_post_tool_prevented_reads_decision_mapping() -> None:
    assert post_tool_prevented({"decision": "prevent", "reason": "stop"})
    assert not post_tool_prevented({"decision": "allow"})
    assert not post_tool_prevented({"status": "ok", "hooked": True})
    assert not post_tool_prevented(None)
    assert not post_tool_prevented("prevent")


@pytest.mark.asyncio
async def test_invoke_pre_generate_is_append_only_user_and_system_note() -> None:
    transcript = (CanonicalMessage("user", (TextContent("keep me"),)),)

    class _Notes:
        async def pre_generate(self, before):
            assert before == transcript
            return {"system": " extra system ", "append": " user note "}

    note = await invoke_pre_generate(_Notes(), transcript)
    assert note["system"] == "extra system"
    assert note["append"] == "user note"


@pytest.mark.asyncio
async def test_invoke_pre_generate_ignores_transcript_rewrite() -> None:
    class _Rewrite:
        async def pre_generate(self, before):
            return {
                "messages": [],
                "transcript": [],
                "append": "keep this",
            }

    note = await invoke_pre_generate(_Rewrite(), ())
    assert note == {"system": "", "append": "keep this"}
    assert "messages" not in note
    assert "transcript" not in note


@pytest.mark.asyncio
async def test_invoke_pre_generate_swallows_errors() -> None:
    class _Boom:
        async def pre_generate(self, before):
            raise RuntimeError("hook exploded")

    assert await invoke_pre_generate(_Boom(), ()) == {"system": "", "append": ""}
    assert await invoke_pre_generate(object(), ()) == {"system": "", "append": ""}


@pytest.mark.asyncio
async def test_invoke_post_generate_is_observe_only() -> None:
    seen: list[tuple[str, tuple[CanonicalMessage, ...]]] = []

    class _Watch:
        async def post_generate(self, text, transcript):
            seen.append((text, transcript))
            return {"append": "must not apply", "transcript": []}

    transcript = (CanonicalMessage("user", (TextContent("hi"),)),)
    assert await invoke_post_generate(_Watch(), "model text", transcript) is None
    assert seen == [("model text", transcript)]


@pytest.mark.asyncio
async def test_invoke_post_generate_swallows_errors() -> None:
    class _Boom:
        async def post_generate(self, text, transcript):
            raise RuntimeError("hook exploded")

    await invoke_post_generate(_Boom(), "text", ())
    await invoke_post_generate(object(), "text", ())
