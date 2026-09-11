from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import StaleExecutionLease, ToolExecutionDisposition
from neos.coding.domain.phases import CodingCheckpoint, SteeringMode, SteeringRequest
from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
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
from tests.coding.fakes import RecordingCodingAuditSink
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    NOW,
    Bindings,
    Executor,
    _DecisionHook,
    collect,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def _sha256_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _pair(call_id: str, body: dict) -> tuple[CanonicalMessage, CanonicalMessage]:
    return (
        CanonicalMessage(
            "assistant",
            (ToolUseContent(call_id, "read_file.v1", {"path": f"{call_id}.txt"}),),
        ),
        CanonicalMessage("tool", (ToolResultContent(call_id, "ok", body),)),
    )


def test_compact_token_threshold_triggers_and_keeps_pairs() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_messages=100,
        max_transcript_bytes=1_048_576,
        max_transcript_tokens=300,
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=config)
    old_body = {"preview": "Z" * 1200, "entries": [{"text": "full"}]}
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *_pair("old", old_body),
        *_pair("active", {"preview": "kept"}),
    )

    compacted = h.loop._compact(transcript)
    use_ids = [
        item.tool_call_id
        for message in compacted
        for item in message.content
        if isinstance(item, ToolUseContent)
    ]
    result_ids = [
        item.tool_call_id
        for message in compacted
        for item in message.content
        if isinstance(item, ToolResultContent)
    ]
    results = {
        item.tool_call_id: dict(item.content)
        for message in compacted
        for item in message.content
        if isinstance(item, ToolResultContent)
    }

    assert set(use_ids) == set(result_ids)
    assert "active" in use_ids
    assert results["old"]["compacted"] is True
    assert results["old"]["sha256"] == _sha256_payload(old_body)
    assert "preview" in results["old"]
    assert "path" in results["old"]
    assert results["active"] == {"preview": "kept"}


def test_compact_large_payload_stores_artifact_ref_and_body() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_tokens=300,
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=config)
    old_body = {"entries": [{"text": "x" * 5000}]}
    digest = _sha256_payload(old_body)
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *_pair("old", old_body),
        *_pair("active", {"preview": "kept"}),
    )
    bodies: dict[str, str] = {}

    compacted = h.loop._compact(transcript, bodies=bodies)
    results = {
        item.tool_call_id: dict(item.content)
        for message in compacted
        for item in message.content
        if isinstance(item, ToolResultContent)
    }

    assert results["old"]["compacted"] is True
    assert results["old"]["sha256"] == digest
    assert results["old"]["preview"]
    assert results["old"]["path"] == f"artifact://{digest}"
    assert digest in bodies
    assert "x" * 5000 in bodies[digest]


def test_compact_stores_small_bodies_and_expand_restores_them() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            max_transcript_bytes=10_000_000,
            max_transcript_tokens=1_000_000,
        ),
    )
    old_body = {"preview": "tiny-body", "entries": [{"text": "ok"}]}
    digest = _sha256_payload(old_body)
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *_pair("old", old_body),
        *_pair("active", {"preview": "kept"}),
    )
    bodies: dict[str, str] = {}
    shrunk = h.loop._shrink_old_tool_results(transcript[2], bodies)
    compacted = (transcript[0], transcript[1], shrunk, *transcript[3:])
    assert digest in bodies
    expanded = h.loop._expand_artifact_refs(compacted, bodies)
    restored = {
        item.tool_call_id: dict(item.content)
        for message in expanded
        for item in message.content
        if isinstance(item, ToolResultContent)
    }
    assert restored["old"]["preview"] == "tiny-body"
    assert restored["old"].get("compacted") is None


def test_compacted_bodies_round_trip_in_loop_state() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = replace(h.loop._restore(INPUT, None), compacted_bodies={"abc": "full text"})
    dumped = h.loop._dump_state(INPUT, state)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_1", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert dict(restored.compacted_bodies) == {"abc": "full text"}


def test_read_stamps_round_trip_in_loop_state() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    stamps = {
        "exists.txt": {
            "mtime": "2026-07-19T00:00:00+00:00",
            "digest": "abc123",
            "full": False,
        }
    }
    state = replace(h.loop._restore(INPUT, None), read_stamps=stamps)
    dumped = h.loop._dump_state(INPUT, state)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_1", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert dumped["read_stamps"] == stamps
    assert dict(restored.read_stamps) == stamps


@pytest.mark.asyncio
async def test_unknown_mutation_commits_synthetic_result_and_run_lives() -> None:
    audit = RecordingCodingAuditSink()
    h = harness(
        [[tool_call(), completed()]],
        executor=Executor(fail_after_mutation=True),
        audit=audit,
    )

    events = await collect(h)

    state = h.repository.checkpoints[-1].loop_state
    results = [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert results
    assert results[-1]["status"] == "error"
    assert results[-1]["content"]["reason_code"] == "tool_outcome_unknown"
    assert state["pending_tool_index"] == 1
    assert state["consecutive_tool_errors"] == 0
    assert any(event.type == "tool.completed" for event in events)
    assert audit.events[-1]["error_code"] == "tool_outcome_unknown"


@pytest.mark.asyncio
async def test_stale_mutation_bookkeeping_synthesizes_unknown_result() -> None:
    audit = RecordingCodingAuditSink()
    h = harness(
        [[tool_call(), completed()]],
        bindings=Bindings(mutation_error=StaleExecutionLease("ct_1")),
        audit=audit,
    )

    events = await collect(h)

    state = h.repository.checkpoints[-1].loop_state
    results = [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert results[-1]["content"]["reason_code"] == "tool_outcome_unknown"
    assert state["pending_tool_index"] == 1
    assert any(event.type in {"tool.completed", "phase.completed"} for event in events)
    assert audit.events[-1]["error_code"] == "tool_outcome_unknown"


@pytest.mark.asyncio
async def test_reclaimed_mutating_claim_synthesizes_unknown_without_execute() -> None:
    h = harness([[tool_call(), completed()]])
    h.repository.tool_claims[("ct_1", "toolu_1")] = (
        SimpleNamespace(disposition=ToolExecutionDisposition.CLAIMED),
        NOW - timedelta(seconds=1),
    )

    events = await collect(h)

    state = h.repository.checkpoints[-1].loop_state
    results = [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert h.bindings.session.writes == 0
    assert h.executor.calls == []
    assert results[-1]["status"] == "error"
    assert results[-1]["content"]["reason_code"] == "tool_outcome_unknown"
    assert state["pending_tool_index"] == 1
    assert any(event.type == "tool.completed" for event in events)


def _phase_checkpoint(h, phase: str) -> CodingCheckpoint:
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    dumped["phase"] = phase
    dumped["instructions_loaded"] = True
    return CodingCheckpoint("cc_phase", "ct_1", "cr_1", 1, dumped, "1", NOW)


@pytest.mark.asyncio
async def test_verify_end_turn_without_verdict_stays_in_verify() -> None:
    h = harness([[TextDelta("tests look fine"), ModelCompleted("end_turn", ModelUsage(2, 1))]])
    events = await collect(h, _phase_checkpoint(h, "verify"))

    state = h.repository.checkpoints[-1].loop_state
    assert state["phase"] == "verify"
    assert state["terminal_pending"] is False
    texts = [
        item["text"]
        for message in state["transcript"]
        if message["role"] == "user"
        for item in message["content"]
        if item.get("type") == "text"
    ]
    assert any("VERDICT" in text for text in texts)
    assert events[-1].type == "model.completed"


@pytest.mark.asyncio
async def test_verify_end_turn_with_verdict_is_terminal() -> None:
    h = harness(
        [[TextDelta("ran pytest\nVERDICT: PASS"), ModelCompleted("end_turn", ModelUsage(2, 1))]]
    )
    await collect(h, _phase_checkpoint(h, "verify"))

    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True
    assert h.repository.checkpoints[-1].loop_state["phase"] == "verify"


@pytest.mark.asyncio
async def test_plan_end_turn_without_critical_files_stays_in_plan() -> None:
    h = harness([[TextDelta("I will edit later"), ModelCompleted("end_turn", ModelUsage(2, 1))]])
    await collect(h, _phase_checkpoint(h, "plan"))

    state = h.repository.checkpoints[-1].loop_state
    assert state["phase"] == "plan"
    assert state["terminal_pending"] is False
    texts = [
        item["text"]
        for message in state["transcript"]
        if message["role"] == "user"
        for item in message["content"]
        if item.get("type") == "text"
    ]
    assert any("Critical Files" in text for text in texts)


@pytest.mark.asyncio
async def test_plan_end_turn_with_critical_files_is_terminal() -> None:
    h = harness(
        [
            [
                TextDelta("## Critical Files:\n- src/app.py\n"),
                ModelCompleted("end_turn", ModelUsage(2, 1)),
            ]
        ]
    )
    await collect(h, _phase_checkpoint(h, "plan"))

    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True
    assert h.repository.checkpoints[-1].loop_state["phase"] == "plan"


class _StopHook(_DecisionHook):
    def __init__(self, decision: str, reason: str = "blocked") -> None:
        super().__init__("allow", reason)
        self.stop_decision = decision
        self.stop_calls = 0

    async def stop(self, reason: str):
        self.stop_calls += 1
        return {"decision": self.stop_decision, "reason": self.reason}


@pytest.mark.asyncio
async def test_stop_prevent_stays_terminal() -> None:
    hooks = _StopHook("prevent")
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(2, 1))]],
        hooks=hooks,
    )
    await collect(h)
    assert hooks.stop_calls == 1
    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True


@pytest.mark.asyncio
async def test_stop_retry_appends_user_meta_and_continues() -> None:
    hooks = _StopHook("retry", "one more check")
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(2, 1))]],
        hooks=hooks,
    )
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is False
    assert state["stop_retry_count"] == 1
    last = state["transcript"][-1]
    assert last["role"] == "user"
    assert "one more check" in last["content"][0]["text"]
    roles = [message["role"] for message in state["transcript"]]
    for index, role in enumerate(roles[:-1]):
        if role == "assistant" and any(
            item.get("type") == "tool_use"
            for item in state["transcript"][index]["content"]
        ):
            assert roles[index + 1] != "user"


@pytest.mark.asyncio
async def test_stop_retry_is_capped_at_two() -> None:
    hooks = _StopHook("retry", "again")
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(2, 1))]],
        hooks=hooks,
    )
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    dumped["stop_retry_count"] = 2
    dumped["instructions_loaded"] = True
    checkpoint = CodingCheckpoint("cc_stop", "ct_1", "cr_1", 1, dumped, "1", NOW)
    await collect(h, checkpoint)
    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True
    assert hooks.stop_calls == 1


@pytest.mark.asyncio
async def test_api_error_skips_stop_hook() -> None:
    hooks = _StopHook("retry")
    h = harness([CodingModelError("model_rate_limited", retryable=True)], hooks=hooks)
    with pytest.raises(CodingLoopFailure, match="model_rate_limited"):
        await collect(h)
    assert hooks.stop_calls == 0


@pytest.mark.asyncio
async def test_pre_tool_timeout_denies_without_execute(monkeypatch) -> None:
    from neos.coding.loop import durable as durable_mod

    monkeypatch.setattr(durable_mod, "PRE_TOOL_HOOK_TIMEOUT_SEC", 0.01)

    class SlowHook(_DecisionHook):
        async def pre_tool(self, call):
            await asyncio.sleep(0.2)
            return {"decision": "allow"}

    h = harness([[tool_call(), completed()]], hooks=SlowHook("allow"))
    events = await collect(h)
    assert h.executor.calls == []
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_hook_denied"


@pytest.mark.asyncio
async def test_spawn_agent_returns_structured_explore_handoff() -> None:
    h = harness(
        [
            [
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {"prompt": "look around", "max_turns": 8},
                ),
                completed(),
            ],
            [TextDelta("must not run"), ModelCompleted("end_turn", ModelUsage(1, 1))],
        ]
    )
    started = time.perf_counter()
    events = await collect(h)
    elapsed = time.perf_counter() - started
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result.get("delegated") is False
    assert result.get("use_phase") == "explore"
    assert result.get("note")
    assert elapsed < 1.0
    assert all(getattr(request, "task_id", None) != "spawn" for request in h.model.requests)
    assert h.model.turns  # unused inner turns remain


@pytest.mark.asyncio
async def test_spawn_agent_still_aborts_when_interrupt_is_pending() -> None:
    h = harness(
        [
            [
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {"prompt": "look around", "max_turns": 8},
                ),
                completed(),
            ]
        ]
    )
    original = h.repository.claim_tool_execution

    async def claim_and_interrupt(**kwargs):
        claimed = await original(**kwargs)
        await h.repository.queue_steering(
            SteeringRequest(
                steering_id="cs_stop",
                task_id="ct_1",
                mode=SteeringMode.INTERRUPT_NOW,
                instruction="stop",
                requested_at=NOW,
            )
        )
        return claimed

    h.repository.claim_tool_execution = claim_and_interrupt
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "aborted"


@pytest.mark.asyncio
async def test_model_request_keeps_compact_preview_instead_of_expanding() -> None:
    old_body = {"entries": [{"text": "x" * 5000}]}
    digest = _sha256_payload(old_body)
    compacted = {
        "compacted": True,
        "sha256": digest,
        "preview": "xxxx",
        "path": f"artifact://{digest}",
    }
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *_pair("old", compacted),
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = replace(
        h.loop._restore(INPUT, None),
        transcript=transcript,
        compacted_bodies={
            digest: json.dumps(old_body, sort_keys=True, separators=(",", ":"))
        },
        transcript_digest=h.loop._digest(transcript),
        instructions_loaded=True,
    )
    dumped = h.loop._dump_state(INPUT, state)
    checkpoint = CodingCheckpoint("cc_1", "ct_1", "cr_1", 1, dumped, "1", NOW)
    await collect(h, checkpoint)
    results = {
        item.tool_call_id: dict(item.content)
        for message in h.model.requests[0].messages
        for item in message.content
        if isinstance(item, ToolResultContent)
    }
    assert results["old"]["compacted"] is True
    assert results["old"]["preview"] == "xxxx"
    assert "x" * 5000 not in json.dumps(results)


@pytest.mark.asyncio
async def test_post_tool_timeout_or_error_skips_without_failing_tool(
    monkeypatch,
) -> None:
    from neos.coding.loop import durable as durable_mod

    monkeypatch.setattr(durable_mod, "PRE_TOOL_HOOK_TIMEOUT_SEC", 0.01)

    class BoomPost(_DecisionHook):
        async def pre_tool(self, call):
            return {"decision": "allow"}

        async def post_tool(self, call, result) -> None:
            await asyncio.sleep(0.2)
            raise RuntimeError("post failed")

    h = harness([[tool_call(), completed()]], hooks=BoomPost("allow"))
    events = await collect(h)
    assert h.executor.calls
    assert any(event.type == "tool.completed" for event in events)


@pytest.mark.asyncio
async def test_model_error_after_delta_is_not_retryable() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])

    class PartialThenError:
        async def stream(self, request):
            del request
            yield TextDelta("hello")
            raise CodingModelError("model_rate_limited", retryable=True)

    h.loop._model = PartialThenError()
    with pytest.raises(CodingLoopFailure, match="model_rate_limited") as caught:
        await collect(h)
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_model_error_before_delta_keeps_retryable() -> None:
    h = harness([CodingModelError("model_rate_limited", retryable=True)])
    with pytest.raises(CodingLoopFailure, match="model_rate_limited") as caught:
        await collect(h)
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_pre_tool_updated_input_is_revalidated_before_execute() -> None:
    class RewriteHook(_DecisionHook):
        async def pre_tool(self, call):
            return {
                "decision": "allow",
                "updatedInput": {"path": "rewritten.txt", "content": "ok"},
            }

    h = harness([[tool_call(), completed()]], hooks=RewriteHook("allow"))
    await collect(h)
    assert h.executor.calls[0].input["path"] == "rewritten.txt"


@pytest.mark.asyncio
async def test_pre_tool_invalid_updated_input_denies() -> None:
    class BadRewrite(_DecisionHook):
        async def pre_tool(self, call):
            return {"decision": "allow", "updatedInput": {"surprise": True}}

    h = harness([[tool_call(), completed()]], hooks=BadRewrite("allow"))
    events = await collect(h)
    assert h.executor.calls == []
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_hook_denied"


@pytest.mark.asyncio
async def test_tool_result_secrets_are_redacted_before_persist() -> None:
    class SecretExecutor(Executor):
        async def execute(self, session, call, **kwargs):
            self.calls.append(call)
            session.writes += 1
            return SimpleNamespace(
                to_mapping=lambda: {
                    "status": "ok",
                    "workspace_revision": "1",
                    "env": {"API_TOKEN": "s3cret"},
                }
            )

    h = harness([[tool_call(), completed()]], executor=SecretExecutor())
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["env"]["API_TOKEN"] == "<redacted>"
    assert "s3cret" not in json.dumps(result)
    results = [
        item
        for message in h.repository.checkpoints[-1].loop_state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert results[-1]["content"]["env"]["API_TOKEN"] == "<redacted>"


@pytest.mark.asyncio
async def test_post_tool_rewrite_is_applied_then_redacted() -> None:
    class RewritePost(_DecisionHook):
        async def pre_tool(self, call):
            return {"decision": "allow"}

        async def post_tool(self, call, result):
            rewritten = dict(result)
            rewritten["hooked"] = True
            rewritten["API_TOKEN"] = "s3cret"
            return rewritten

    h = harness([[tool_call(), completed()]], hooks=RewritePost("allow"))
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["hooked"] is True
    assert result["API_TOKEN"] == "<redacted>"
    assert "s3cret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_denied_tool_content_is_denial_envelope() -> None:
    h = harness(
        [
            [
                tool_call(
                    "toolu_1",
                    "write_file.v1",
                    {"path": "a.txt", "content": "raw-secret"},
                ),
                completed(),
            ]
        ],
        hooks=_DecisionHook("deny"),
    )
    events = await collect(h)
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_hook_denied"
    results = [
        item
        for message in h.repository.checkpoints[-1].loop_state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    content = results[-1]["content"]
    assert content["reason_code"] == "policy_hook_denied"
    assert content["status"] == "denied"
    assert content["denied_by"] == "hook"
    assert content["function_id"] == "write_file.v1"
    assert content["reason"] == "policy_hook_denied"
    assert content["args_excerpt"] == {"path": "a.txt"}
    assert "raw-secret" not in json.dumps(content)


@pytest.mark.asyncio
async def test_pre_turn_budget_veto_skips_model_request() -> None:
    h = harness(
        [[TextDelta("must not run"), ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            max_total_tokens=10,
        ),
    )
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    dumped["input_tokens"] = 11
    dumped["instructions_loaded"] = True
    checkpoint = CodingCheckpoint("cc_budget", "ct_1", "cr_1", 1, dumped, "1", NOW)
    with pytest.raises(CodingLoopFailure, match="token_budget_exceeded") as caught:
        await collect(h, checkpoint)
    assert caught.value.retryable is False
    assert h.model.requests == []
