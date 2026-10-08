from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.loop import encode_state, initial_state
from neos.coding.loop.anthropic import CodingLoopFailure
from neos.coding.model.anthropic import CodingModelError
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolResultContent,
    ToolUseContent,
)
from tests.coding.loop.support import INPUT, NOW, collect, harness

pytestmark = pytest.mark.no_db


def _checkpoint(h, state) -> CodingCheckpoint:
    dumped = encode_state(INPUT, state)
    return CodingCheckpoint("cc_followup", "ct_1", "cr_1", 1, dumped, "1", NOW)


def _user_texts(transcript) -> list[str]:
    return [
        item["text"]
        for message in transcript
        if message["role"] == "user"
        for item in message["content"]
        if item.get("type") == "text"
    ]


def _prefix_transcript() -> tuple[CanonicalMessage, ...]:
    return (
        CanonicalMessage("user", (TextContent("Fix it"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("old", "read_file.v1", {"path": "old.txt"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("old", "ok", {"preview": "stale"}),),
        ),
        CanonicalMessage("user", (TextContent("keep this later note"),)),
    )


@pytest.mark.asyncio
async def test_prompt_too_long_after_compact_drops_oldest_prefix_turn() -> None:
    h = harness([CodingModelError("prompt_too_long", retryable=True)])
    state = replace(
        initial_state(INPUT),
        transcript=_prefix_transcript(),
        prompt_compact_retries=1,
        instructions_loaded=True,
    )

    events = await collect(h, _checkpoint(h, state))

    assert any(event.checkpoint_id for event in events)
    after = h.repository.checkpoints[-1].loop_state
    assert after["prompt_compact_retries"] == 2
    texts = _user_texts(after["transcript"])
    assert any("Fix it" in text for text in texts)
    assert any("keep this later note" in text for text in texts)
    assert all(
        item.get("tool_call_id") != "old"
        for message in after["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_use"
    )


@pytest.mark.asyncio
async def test_prompt_too_long_after_three_head_drops_is_non_retryable() -> None:
    h = harness([CodingModelError("prompt_too_long", retryable=True)])
    state = replace(
        initial_state(INPUT),
        transcript=_prefix_transcript(),
        prompt_compact_retries=4,
        instructions_loaded=True,
    )

    with pytest.raises(CodingLoopFailure) as caught:
        await collect(h, _checkpoint(h, state))

    assert caught.value.code == "prompt_too_long"
    assert caught.value.retryable is False
    assert h.repository.checkpoints == []


@pytest.mark.asyncio
async def test_compact_after_prompt_too_long_reattaches_recent_reads() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    reads = (
        CanonicalMessage("user", (TextContent("Fix it"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("r1", "read_file.v1", {"path": "old.txt"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("r1", "ok", {"preview": "one"}),),
        ),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("r2", "read_file.v1", {"path": "src/a.py"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("r2", "ok", {"preview": "two"}),),
        ),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("r3", "read_file.v1", {"path": "src/b.py"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("r3", "ok", {"preview": "three"}),),
        ),
        CanonicalMessage("user", (TextContent("continue from here"),)),
    )
    state = replace(
        initial_state(INPUT),
        transcript=reads,
        read_paths=frozenset({"old.txt", "src/a.py", "src/b.py"}),
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    assert after.instructions_loaded is False
    texts = [
        item.text
        for message in after.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert any("src/a.py" in text for text in texts)
    assert any("src/b.py" in text for text in texts)
    assert any("old.txt" in text for text in texts)


@pytest.mark.asyncio
async def test_compact_after_prompt_too_long_reattaches_at_most_five_reads() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    pairs: list[CanonicalMessage] = [
        CanonicalMessage("user", (TextContent("Fix it"),))
    ]
    for index in range(6):
        call_id = f"r{index}"
        path = f"src/f{index}.py"
        pairs.append(
            CanonicalMessage(
                "assistant",
                (ToolUseContent(call_id, "read_file.v1", {"path": path}),),
            )
        )
        pairs.append(
            CanonicalMessage(
                "tool",
                (ToolResultContent(call_id, "ok", {"preview": path}),),
            )
        )
    state = replace(
        initial_state(INPUT),
        transcript=tuple(pairs),
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    preview = "\n".join(
        item.text
        for message in after.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text") and "Recently read" in item.text
    )
    assert "src/f0.py" not in preview
    for index in range(1, 6):
        assert f"src/f{index}.py" in preview


@pytest.mark.asyncio
async def test_compact_after_prompt_too_long_ignores_denied_absolute_reads() -> None:
    """A denied read's path was never validated -- normalizing it raised."""
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    reads = (
        CanonicalMessage("user", (TextContent("Fix it"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("bad", "read_file.v1", {"path": "/etc/passwd"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("bad", "denied", {"reason_code": "policy"}),),
        ),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("good", "read_file.v1", {"path": "src/a.py"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("good", "ok", {"preview": "a"}),),
        ),
    )
    state = replace(
        initial_state(INPUT), transcript=reads, instructions_loaded=True
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    preview = "\n".join(
        item.text
        for message in after.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text") and "Recently read" in item.text
    )
    assert "src/a.py" in preview
    assert "/etc/passwd" not in preview


@pytest.mark.asyncio
async def test_llm_compact_passes_previous_summary_and_stores_new() -> None:
    h = harness(
        [[TextDelta("new compressed facts"), ModelCompleted("end_turn", ModelUsage(1, 1))]]
    )
    long_prefix = tuple(
        CanonicalMessage("user", (TextContent(f"note {index} " + ("x" * 20)),))
        for index in range(4)
    )
    state = replace(
        initial_state(INPUT),
        transcript=(CanonicalMessage("user", (TextContent("Fix it"),)),) + long_prefix,
        llm_compact_attempts=0,
        summary="old facts about auth",
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    prompt = h.model.requests[0].messages[0].content[0].text
    assert "old facts about auth" in prompt
    assert after.summary == "new compressed facts"
    assert all(
        "Prior context summary" not in item.text
        for message in after.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    )
    dumped = encode_state(INPUT, after)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_sum", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert dumped["summary"] == "new compressed facts"
    assert restored.summary == "new compressed facts"


@pytest.mark.asyncio
async def test_previous_summary_is_injected_after_cache_boundary() -> None:
    from neos.coding.loop.anthropic import AnthropicLoopConfig
    from neos.coding.prompts import SYSTEM_PROMPT_DYNAMIC_BOUNDARY

    system = f"static policy\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n## Session\ndynamic tail"
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(model="claude-test", system=system),
    )
    state = replace(
        initial_state(INPUT),
        summary="auth uses JWT",
        instructions_loaded=True,
    )

    await collect(h, _checkpoint(h, state))

    sent = h.model.requests[0].system
    assert "auth uses JWT" in sent
    assert sent.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY) < sent.index(
        "## Conversation summary"
    )
    assert sent.index("## Conversation summary") < sent.index("## Session")
    assert "Prior context summary" not in sent
    assert all(
        "Prior context summary" not in item.text
        for message in h.model.requests[0].messages
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    )


class _InjectCompactHooks:
    async def pre_tool(self, call):
        return None

    async def post_tool(self, call, result):
        return None

    async def stop(self, reason: str):
        return None

    async def compact(self, before, after) -> None:
        return None

    async def pre_compact(self, before):
        return {"instruction": "Keep the auth plan"}

    async def post_compact(self, before, after):
        return {"instruction": "Re-read CLAUDE.md"}


@pytest.mark.asyncio
async def test_pre_and_post_compact_inject_user_instructions() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        hooks=_InjectCompactHooks(),
    )
    state = replace(
        initial_state(INPUT),
        transcript=_prefix_transcript(),
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    texts = [
        item.text
        for message in after.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert any("Keep the auth plan" in text for text in texts)
    assert any("Re-read CLAUDE.md" in text for text in texts)


@pytest.mark.asyncio
async def test_compact_hooks_do_not_split_open_tool_pairs() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        hooks=_InjectCompactHooks(),
    )
    open_pair = (
        CanonicalMessage("user", (TextContent("read it"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("call_1", "read_file.v1", {"path": "a.py"}),),
        ),
    )

    after = await h.loop._compact_with_hook(open_pair, preserve_tools=True)

    roles = [message.role for message in after]
    assert roles[-1] == "assistant"
    assert "user" not in roles[roles.index("assistant") :]
    texts = [
        item.text
        for message in after
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert all("Keep the auth plan" not in text for text in texts)
    assert all("Re-read CLAUDE.md" not in text for text in texts)


@pytest.mark.asyncio
async def test_load_skill_allowed_tools_persist_and_restrict_visibility() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = initial_state(INPUT)
    after = await h.loop._after_result(
        state,
        ToolResultContent(
            "skill_1",
            "ok",
            {
                "status": "ok",
                "entries": (
                    {
                        "name": "guided",
                        "markdown": "use read and execute",
                        "allowed_tools": ["read_file.v1", "execute.v1"],
                    },
                ),
            },
        ),
        tool_name="load_skill.v1",
        tool_input={"name": "guided"},
    )

    dumped = encode_state(INPUT, after)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_skill", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert set(dumped["allowed_tools"]) == {"execute.v1", "read_file.v1"}
    assert restored.allowed_tools == frozenset({"read_file.v1", "execute.v1"})
    names = {tool.name for tool in h.catalog().definitions(restored)}
    assert "read_file.v1" in names
    assert "execute.v1" in names
    assert "write_file.v1" not in names
    assert "load_skill.v1" in names


@pytest.mark.asyncio
async def test_empty_skill_allowed_tools_do_not_restrict() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    after = await h.loop._after_result(
        initial_state(INPUT),
        ToolResultContent(
            "skill_1",
            "ok",
            {"status": "ok", "entries": ({"name": "open", "allowed_tools": []},)},
        ),
        tool_name="load_skill.v1",
        tool_input={"name": "open"},
    )
    names = {tool.name for tool in h.catalog().definitions(after)}
    assert after.allowed_tools == frozenset()
    assert "write_file.v1" in names


@pytest.mark.asyncio
async def test_loaded_skill_allowed_tools_union_across_skills() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    first = await h.loop._after_result(
        initial_state(INPUT),
        ToolResultContent(
            "s1",
            "ok",
            {
                "status": "ok",
                "entries": (
                    {"name": "a", "allowed_tools": ["read_file.v1", "execute.v1"]},
                ),
            },
        ),
        tool_name="load_skill.v1",
        tool_input={"name": "a"},
    )
    second = await h.loop._after_result(
        first,
        ToolResultContent(
            "s2",
            "ok",
            {
                "status": "ok",
                "entries": ({"name": "b", "allowed_tools": ["write_file.v1"]},),
            },
        ),
        tool_name="load_skill.v1",
        tool_input={"name": "b"},
    )
    assert second.allowed_tools == frozenset(
        {"read_file.v1", "execute.v1", "write_file.v1"}
    )
    names = {tool.name for tool in h.catalog().definitions(second)}
    assert "write_file.v1" in names
    assert "edit_file.v1" not in names


@pytest.mark.asyncio
async def test_llm_compact_keeps_tool_result_ref_bodies() -> None:
    import hashlib
    import json

    fat = {
        "status": "ok",
        "preview": "x" * 200,
        "entries": [{"text": f"x-{index}" * 20} for index in range(30)],
    }
    payload_text = json.dumps(
        fat, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    ref = {
        "compacted": True,
        "sha256": digest,
        "preview": ("x" * 200)[:200],
        "path": f"artifact://{digest}",
    }
    h = harness(
        [[TextDelta("compressed facts"), ModelCompleted("end_turn", ModelUsage(1, 1))]]
    )
    state = replace(
        initial_state(INPUT),
        transcript=(
            CanonicalMessage("user", (TextContent("Fix it"),)),
            CanonicalMessage("user", (TextContent("note 0 " + ("x" * 20)),)),
            CanonicalMessage("user", (TextContent("note 1 " + ("x" * 20)),)),
            CanonicalMessage(
                "assistant",
                (ToolUseContent("old", "execute.v1", {"argv": ["pytest"]}),),
            ),
            CanonicalMessage(
                "tool",
                (ToolResultContent("old", "ok", ref),),
            ),
        ),
        compacted_bodies={digest: payload_text},
        llm_compact_attempts=0,
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)

    assert after.summary == "compressed facts"
    assert after.compacted_bodies[digest] == payload_text
    results = [
        item
        for message in after.transcript
        for item in message.content
        if isinstance(item, ToolResultContent)
    ]
    assert results
    assert results[-1].content.get("compacted") is True
    assert results[-1].content.get("sha256") == digest
    assert "entries" not in results[-1].content
    dumped = encode_state(INPUT, after)
    assert dumped["compacted_bodies"][digest] == payload_text
    assert dumped["summary"] == "compressed facts"


def _search_tools_transcript() -> tuple[CanonicalMessage, ...]:
    return (
        CanonicalMessage("user", (TextContent("Fix it"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("st1", "search_tools.v1", {"query": "web"}),),
        ),
        CanonicalMessage(
            "tool",
            (
                ToolResultContent(
                    "st1",
                    "ok",
                    {
                        "status": "ok",
                        "entries": (
                            {
                                "name": "web_fetch.v1",
                                "description": "Fetch a URL",
                                "input_schema": {"type": "object"},
                            },
                        ),
                    },
                ),
            ),
        ),
        CanonicalMessage("user", (TextContent("later note " + ("x" * 40)),)),
    )


@pytest.mark.asyncio
async def test_compact_keeps_revealed_tool_definitions() -> None:
    h = harness(
        [[TextDelta("facts"), ModelCompleted("end_turn", ModelUsage(1, 1))]]
    )
    state = replace(
        initial_state(INPUT),
        transcript=_search_tools_transcript(),
        revealed_tools=frozenset({"web_fetch.v1"}),
        llm_compact_attempts=0,
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)
    names = {tool.name for tool in h.catalog().definitions(after)}

    assert "web_fetch.v1" in after.revealed_tools
    assert "web_fetch.v1" in names
    dumped = encode_state(INPUT, after)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_rev", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert "web_fetch.v1" in restored.revealed_tools
    assert "web_fetch.v1" in {
        tool.name for tool in h.catalog().definitions(restored)
    }


@pytest.mark.asyncio
async def test_compact_recovers_revealed_tools_from_transcript() -> None:
    h = harness(
        [[TextDelta("facts"), ModelCompleted("end_turn", ModelUsage(1, 1))]]
    )
    state = replace(
        initial_state(INPUT),
        transcript=_search_tools_transcript(),
        revealed_tools=frozenset(),
        llm_compact_attempts=0,
        instructions_loaded=True,
    )

    after = await h.loop._compact_after_prompt_too_long(state)
    names = {tool.name for tool in h.catalog().definitions(after)}

    assert "web_fetch.v1" in after.revealed_tools
    assert "web_fetch.v1" in names


@pytest.mark.asyncio
async def test_skill_allowed_tools_deny_disallowed_tool() -> None:
    from tests.coding.loop.support import tool_call, completed

    h = harness([[tool_call(), completed()]])
    state = replace(
        initial_state(INPUT),
        allowed_tools=frozenset({"read_file.v1", "execute.v1"}),
        instructions_loaded=True,
    )

    events = await collect(h, _checkpoint(h, state))

    denied = [event for event in events if event.type == "tool.denied"]
    assert denied
    assert denied[-1].payload["reason_code"] == "policy_skill_denied"
    assert h.executor.calls == []
