from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.coding.domain.durability import StaleExecutionLease, ToolExecutionDisposition
from neos.coding.domain.phases import CodingCheckpoint, SteeringMode, SteeringRequest
from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.loop.durable import COMPACT_REF_THRESHOLD_BYTES
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


def _pair(
    call_id: str, body: dict, *, name: str = "execute.v1"
) -> tuple[CanonicalMessage, CanonicalMessage]:
    return (
        CanonicalMessage(
            "assistant",
            (ToolUseContent(call_id, name, {"path": f"{call_id}.txt"}),),
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

    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is True
    assert state["phase"] == "verify"
    assert state["verdict"] == "PASS"


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

    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is True
    assert state["phase"] == "plan"
    assert list(state["critical_files"]) == ["src/app.py"]


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


def _error_signature(name: str, tool_input: dict) -> str:
    canonical = json.dumps(
        tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256((name + canonical).encode("utf-8")).hexdigest()


class _ErrorExecutor(Executor):
    async def execute(self, session, call, **kwargs):
        self.calls.append(call)
        return SimpleNamespace(
            to_mapping=lambda: {
                "status": "error",
                "reason_code": "tool_execution_failed",
                "workspace_revision": "1",
            }
        )


def _pending_tool_checkpoint(h, *, instruction: str | None = None, **overrides):
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    tool_input = {"path": "a.txt", "content": "x"}
    dumped["transcript"] = [
        {"role": "user", "content": [{"type": "text", "text": "Fix it"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_call_id": "toolu_1",
                    "name": "write_file.v1",
                    "input": tool_input,
                }
            ],
        },
    ]
    dumped["pending_tool_calls"] = [
        {
            "tool_call_id": "toolu_1",
            "name": "write_file.v1",
            "input": tool_input,
        }
    ]
    dumped["pending_tool_index"] = 0
    dumped["instructions_loaded"] = True
    dumped["pending_instruction"] = instruction
    dumped.update(overrides)
    return CodingCheckpoint("cc_pending", "ct_1", "cr_1", 1, dumped, "1", NOW)


@pytest.mark.asyncio
async def test_tool_result_secret_prefixes_are_redacted_before_persist() -> None:
    token = "sk-" + ("e" * 20)

    class SecretPrefixExecutor(Executor):
        async def execute(self, session, call, **kwargs):
            self.calls.append(call)
            session.writes += 1
            return SimpleNamespace(
                to_mapping=lambda: {
                    "status": "ok",
                    "workspace_revision": "1",
                    "preview": f"token {token}",
                }
            )

    h = harness([[tool_call(), completed()]], executor=SecretPrefixExecutor())
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["preview"] == "token <redacted>"
    assert token not in json.dumps(result)


@pytest.mark.asyncio
async def test_empty_end_turn_checkpoints_one_retry_and_is_not_success() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    events = await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is False
    assert state["empty_retry_count"] == 1
    assert events[-1].payload.get("reason_code") == "empty_retry"
    last = state["transcript"][-1]
    assert last["role"] == "user"
    assert last["content"][0]["text"]


@pytest.mark.asyncio
async def test_think_only_end_turn_is_not_success() -> None:
    h = harness(
        [[TextDelta("<think>planning</think>"), ModelCompleted("end_turn", ModelUsage(2, 1))]]
    )
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is False
    assert state["empty_retry_count"] == 1


@pytest.mark.asyncio
async def test_think_block_with_public_text_is_terminal() -> None:
    h = harness(
        [
            [
                TextDelta("<think>planning</think> done"),
                ModelCompleted("end_turn", ModelUsage(2, 1)),
            ]
        ]
    )
    await collect(h)
    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True


@pytest.mark.asyncio
async def test_empty_end_turn_retry_then_fails_incomplete() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(INPUT, None)
    dumped = h.loop._dump_state(INPUT, state)
    dumped["empty_retry_count"] = 1
    dumped["instructions_loaded"] = True
    checkpoint = CodingCheckpoint("cc_empty", "ct_1", "cr_1", 1, dumped, "1", NOW)
    with pytest.raises(CodingLoopFailure, match="model_output_incomplete") as caught:
        await collect(h, checkpoint)
    assert caught.value.retryable is False
    assert h.repository.checkpoints == []


@pytest.mark.asyncio
async def test_unknown_empty_stop_is_not_success() -> None:
    h = harness([[ModelCompleted("unknown", ModelUsage(1, 1))]])
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is False
    assert state["empty_retry_count"] == 1


def test_pending_instruction_waits_until_tool_pairs_close() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    checkpoint = _pending_tool_checkpoint(h, instruction="Inspect cache first")
    restored = h.loop._restore(INPUT, checkpoint)
    assert restored.pending_instruction == "Inspect cache first"
    assert restored.has_pending_tool is True
    assert restored.transcript[-1].role == "assistant"
    texts = [
        item.text
        for message in restored.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert "Inspect cache first" not in texts
    dumped = h.loop._dump_state(INPUT, restored)
    assert dumped["pending_instruction"] == "Inspect cache first"

    checkpoint.loop_state["pending_tool_index"] = 1
    closed = h.loop._restore(INPUT, checkpoint)
    assert closed.pending_instruction is None
    assert closed.has_pending_tool is False
    closed_texts = [
        item.text
        for message in closed.transcript
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert "Inspect cache first" in closed_texts


@pytest.mark.asyncio
async def test_pending_instruction_is_not_spliced_into_tool_result() -> None:
    h = harness([[tool_call(), completed()]])
    checkpoint = _pending_tool_checkpoint(h, instruction="Inspect cache first")
    await collect(h, checkpoint)
    state = h.repository.checkpoints[-1].loop_state
    assert state["pending_instruction"] == "Inspect cache first"
    assert state["pending_tool_index"] == 1
    blob = json.dumps(state["transcript"])
    assert "Inspect cache first" not in blob
    assert state["transcript"][-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_identical_tool_errors_are_stall_denied_before_fourth_execute() -> None:
    same = {"path": "a.txt", "content": "x"}
    h = harness(
        [
            [tool_call("t1", "write_file.v1", same), completed()],
            [tool_call("t2", "write_file.v1", same), completed()],
            [tool_call("t3", "write_file.v1", same), completed()],
            [tool_call("t4", "write_file.v1", same), completed()],
        ],
        executor=_ErrorExecutor(),
    )
    await collect(h)
    assert h.repository.checkpoints[-1].loop_state["last_error_count"] == 1
    await collect(h, h.repository.checkpoints[-1])
    assert h.repository.checkpoints[-1].loop_state["last_error_count"] == 2
    await collect(h, h.repository.checkpoints[-1])
    state = h.repository.checkpoints[-1].loop_state
    assert state["last_error_count"] == 3
    assert state["last_error_signature"] == _error_signature("write_file.v1", same)
    events = await collect(h, h.repository.checkpoints[-1])
    assert len(h.executor.calls) == 3
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_stall_denied"
    results = [
        item
        for message in h.repository.checkpoints[-1].loop_state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert results[-1]["content"]["reason_code"] == "policy_stall_denied"
    assert results[-1]["content"]["denied_by"] == "policy"


@pytest.mark.asyncio
async def test_stall_count_resets_on_ok_and_different_signature() -> None:
    first = {"path": "a.txt", "content": "x"}
    second = {"path": "b.txt", "content": "y"}
    h = harness(
        [
            [tool_call("t1", "write_file.v1", first), completed()],
            [tool_call("t2", "write_file.v1", second), completed()],
            [tool_call("t3", "write_file.v1", first), completed()],
        ],
        executor=_ErrorExecutor(),
    )
    await collect(h)
    await collect(h, h.repository.checkpoints[-1])
    state = h.repository.checkpoints[-1].loop_state
    assert state["last_error_count"] == 1
    assert state["last_error_signature"] == _error_signature("write_file.v1", second)

    ok_harness = harness([[tool_call("t3", "write_file.v1", first), completed()]])
    dumped = state
    dumped["pending_tool_calls"] = [
        {
            "tool_call_id": "t3",
            "name": "write_file.v1",
            "input": first,
        }
    ]
    dumped["pending_tool_index"] = 0
    dumped["transcript"] = dumped["transcript"] + [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_call_id": "t3",
                    "name": "write_file.v1",
                    "input": first,
                }
            ],
        }
    ]
    await collect(
        ok_harness,
        CodingCheckpoint("cc_ok", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    after = ok_harness.repository.checkpoints[-1].loop_state
    assert after["last_error_count"] == 0
    assert after["last_error_signature"] == ""


@pytest.mark.asyncio
async def test_stall_deny_from_restored_count_skips_execute() -> None:
    same = {"path": "a.txt", "content": "x"}
    h = harness([[tool_call(), completed()]])
    checkpoint = _pending_tool_checkpoint(
        h,
        last_error_signature=_error_signature("write_file.v1", same),
        last_error_count=3,
    )
    events = await collect(h, checkpoint)
    assert h.executor.calls == []
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_stall_denied"


def _transcript_tool_results(state) -> list[dict]:
    return [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]


class _FatExecutor(Executor):
    def __init__(self, payload: dict, *, name: str | None = None) -> None:
        super().__init__()
        self._payload = payload
        self._name = name

    async def execute(self, session, call, **kwargs):
        if self._name is None or call.name == self._name:
            self.calls.append(call)
            return SimpleNamespace(to_mapping=lambda: dict(self._payload))
        return await super().execute(session, call, **kwargs)


@pytest.mark.asyncio
async def test_pre_tool_prevent_closes_pair_and_is_terminal() -> None:
    h = harness([[tool_call(), completed()]], hooks=_DecisionHook("prevent", "stop"))
    events = await collect(h)

    assert h.executor.calls == []
    denied = [event for event in events if event.type == "tool.denied"]
    assert denied
    assert denied[-1].payload["reason_code"] == "hook_prevented"
    assert denied[-1].payload["name"] == "write_file.v1"
    assert denied[-1].payload["preview"]
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is True
    assert state["pending_tool_index"] == 1
    results = _transcript_tool_results(state)
    assert results[-1]["status"] in {"denied", "error"}
    assert results[-1]["content"]["reason_code"] == "hook_prevented"
    assert results[-1]["content"]["denied_by"] == "hook"

    follow = await collect(h, h.repository.checkpoints[-1])
    assert follow == []
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_pre_tool_prevent_does_not_continue_remaining_tools() -> None:
    h = harness(
        [
            [
                tool_call("t1", "write_file.v1", {"path": "a.txt", "content": "x"}),
                tool_call("t2", "write_file.v1", {"path": "b.txt", "content": "y"}),
                completed(),
            ]
        ],
        hooks=_DecisionHook("prevent"),
    )
    await collect(h)
    assert h.executor.calls == []
    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is True
    assert state["pending_tool_index"] == 1
    assert len(state["pending_tool_calls"]) == 2
    results = _transcript_tool_results(state)
    assert len(results) == 1
    assert results[0]["content"]["reason_code"] == "hook_prevented"

    follow = await collect(h, h.repository.checkpoints[-1])
    assert follow == []
    assert h.executor.calls == []
    later = h.repository.checkpoints[-1].loop_state
    assert later["pending_tool_index"] == 1
    assert len(_transcript_tool_results(later)) == 1


@pytest.mark.asyncio
async def test_pre_tool_deny_is_not_terminal() -> None:
    h = harness([[tool_call(), completed()]], hooks=_DecisionHook("deny"))
    events = await collect(h)
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_hook_denied"
    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is False
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1


def _fat_payload(*, preview_prefix: str = "") -> dict:
    chunk = "x" * 200
    return {
        "status": "ok",
        "workspace_revision": "1",
        "preview": f"{preview_prefix}{chunk}",
        "entries": [{"text": f"{preview_prefix}{chunk}-{index}"} for index in range(30)],
    }


@pytest.mark.asyncio
async def test_latest_tool_result_over_threshold_is_persisted_as_ref() -> None:
    fat = _fat_payload()
    assert (
        len(json.dumps(fat, sort_keys=True, separators=(",", ":")).encode())
        >= COMPACT_REF_THRESHOLD_BYTES
    )
    h = harness(
        [
            [tool_call(), completed()],
            [TextDelta("noted"), ModelCompleted("end_turn", ModelUsage(1, 1))],
        ],
        executor=_FatExecutor(fat),
    )
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    results = _transcript_tool_results(state)
    assert results[-1]["content"]["compacted"] is True
    digest = results[-1]["content"]["sha256"]
    assert digest in state["compacted_bodies"]
    assert "x" * 200 in state["compacted_bodies"][digest]
    assert "entries" not in results[-1]["content"]

    await collect(h, h.repository.checkpoints[-1])
    request_results = {
        item.tool_call_id: dict(item.content)
        for message in h.model.requests[-1].messages
        for item in message.content
        if isinstance(item, ToolResultContent)
    }
    assert request_results["toolu_1"]["compacted"] is True
    assert "entries" not in request_results["toolu_1"]


@pytest.mark.asyncio
async def test_latest_read_file_result_is_not_ref_compacted() -> None:
    fat = _fat_payload(preview_prefix="     1|")
    h = harness(
        [[tool_call("r1", "read_file.v1", {"path": "big.txt"}), completed()]],
        executor=_FatExecutor(fat, name="read_file.v1"),
    )
    await collect(h)
    results = _transcript_tool_results(h.repository.checkpoints[-1].loop_state)
    assert results[-1]["content"].get("compacted") is not True
    assert results[-1]["content"]["preview"].lstrip().startswith("1|")
    assert len(results[-1]["content"]["entries"]) == 30


def test_shrink_old_tool_results_skips_read_file_pairs() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    read_body = {"preview": "     1|" + ("R" * 80), "entries": [{"text": "     1|hi"}]}
    exec_body = {"stdout": "E" * 80}
    read_msg = CanonicalMessage("tool", (ToolResultContent("r1", "ok", read_body),))
    exec_msg = CanonicalMessage("tool", (ToolResultContent("e1", "ok", exec_body),))
    names = {"r1": "read_file.v1", "e1": "execute.v1"}
    bodies: dict[str, str] = {}
    shrunk_read = h.loop._shrink_old_tool_results(read_msg, bodies, names)
    shrunk_exec = h.loop._shrink_old_tool_results(exec_msg, bodies, names)
    assert dict(shrunk_read.content[0].content) == read_body
    assert shrunk_exec.content[0].content["compacted"] is True
    assert _sha256_payload(exec_body) in bodies


def test_shrink_old_tool_results_skips_unpaired_line_numbered_read() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    read_body = {"preview": "     1|kept-full", "entries": [{"text": "     1|kept-full"}]}
    message = CanonicalMessage("tool", (ToolResultContent("orphan", "ok", read_body),))
    bodies: dict[str, str] = {}
    shrunk = h.loop._shrink_old_tool_results(message, bodies, {})
    assert dict(shrunk.content[0].content) == read_body
    assert bodies == {}


def test_compact_keeps_full_read_file_prefix_or_drops_pair() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_messages=100,
        max_transcript_bytes=1_048_576,
        max_transcript_tokens=300,
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=config)
    old_body = {"preview": "     1|" + ("Z" * 1200), "entries": [{"text": "full"}]}
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *_pair("old", old_body, name="read_file.v1"),
        *_pair("active", {"preview": "kept"}),
    )
    compacted = h.loop._compact(transcript)
    results = {
        item.tool_call_id: dict(item.content)
        for message in compacted
        for item in message.content
        if isinstance(item, ToolResultContent)
    }
    if "old" in results:
        assert results["old"].get("compacted") is not True
        assert results["old"] == old_body
    assert "active" in results
    assert results["active"] == {"preview": "kept"}


@pytest.mark.asyncio
async def test_readonly_batch_denies_secret_read_without_execute() -> None:
    h = harness(
        [
            [
                tool_call("secret", "read_file.v1", {"path": ".env"}),
                tool_call("ok", "read_file.v1", {"path": "a.txt"}),
                completed(),
            ]
        ],
        approval_evaluator=evaluate_approval,
    )

    events = await collect(h)

    assert any(event.type == "tool.denied" for event in events)
    assert all(call.input.get("path") != ".env" for call in h.executor.calls)
    denied = next(event for event in events if event.type == "tool.denied")
    assert denied.payload.get("reason_code") in {
        "policy_approval_denied",
        "policy_secret_path_denied",
    }


def test_verdict_and_critical_files_round_trip_in_loop_state() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = replace(
        h.loop._restore(INPUT, None),
        verdict="FAIL",
        critical_files=("src/app.py", "tests/test_app.py"),
    )
    dumped = h.loop._dump_state(INPUT, state)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_1", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert dumped["verdict"] == "FAIL"
    assert dumped["critical_files"] == ["src/app.py", "tests/test_app.py"]
    assert restored.verdict == "FAIL"
    assert restored.critical_files == ("src/app.py", "tests/test_app.py")


@pytest.mark.asyncio
async def test_tool_started_is_emitted_before_execute() -> None:
    h = harness([[tool_call(), completed()]])
    events = await collect(h)
    types = [event.type for event in events]
    assert "tool.started" in types
    assert "tool.completed" in types
    assert types.index("tool.started") < types.index("tool.completed")
    started = next(event for event in events if event.type == "tool.started")
    assert started.payload["name"] == "write_file.v1"
    assert "a.txt" in started.payload["preview"]
    assert len(started.payload["preview"]) <= 200
    completed_event = next(event for event in events if event.type == "tool.completed")
    assert completed_event.payload["name"] == "write_file.v1"
    assert completed_event.payload["preview"]


@pytest.mark.asyncio
async def test_tool_denied_payload_includes_name_and_preview() -> None:
    h = harness([[tool_call(), completed()]], hooks=_DecisionHook("deny"))
    events = await collect(h)
    denied = next(event for event in events if event.type == "tool.denied")
    assert denied.payload["name"] == "write_file.v1"
    assert "a.txt" in denied.payload["preview"]
    assert denied.payload["reason_code"] == "policy_hook_denied"


def test_read_stamps_round_trip_offset_and_limit() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    stamps = {
        "exists.txt": {
            "mtime": "2026-07-19T00:00:00+00:00",
            "digest": "abc123",
            "full": False,
            "offset": 10,
            "limit": 40,
        }
    }
    state = replace(h.loop._restore(INPUT, None), read_stamps=stamps)
    dumped = h.loop._dump_state(INPUT, state)
    restored = h.loop._restore(
        INPUT,
        CodingCheckpoint("cc_1", "ct_1", "cr_1", 1, dumped, "1", NOW),
    )
    assert dumped["read_stamps"]["exists.txt"]["offset"] == 10
    assert dumped["read_stamps"]["exists.txt"]["limit"] == 40
    assert dict(restored.read_stamps) == stamps
