import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import (
    ExecutionLease,
    StaleExecutionLease,
    ToolExecutionDisposition,
)
from neos.coding.domain.approvals import (
    ApprovalDecision,
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.domain.events import make_event
from neos.coding.loop.anthropic import (
    AnthropicCodingLoop,
    AnthropicLoopConfig,
    CodingLoopFailure,
)
from neos.coding.loop.base import (
    LoopDependencies,
    LoopInput,
    WorkspaceEditContext,
)
from neos.coding.model.anthropic import CodingModelError
from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ToolCallCompleted,
    ToolInputDelta,
)
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.registry import CodingToolRegistry
from tests.coding.fakes import InMemoryCodingRunRepository, RecordingCodingAuditSink

NOW = datetime(2026, 7, 19, tzinfo=UTC)


class Model:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        for event in turn:
            yield event


class Events:
    def __init__(self):
        self.items = []

    async def append(self, *, task_id, event_type, payload, **ids):
        event = make_event(
            task_id=task_id,
            seq=100 + len(self.items),
            event_type=event_type,
            payload=payload,
            now=NOW,
            **ids,
        )
        self.items.append(event)
        return event


class Executor:
    def __init__(self, *, fail_after_mutation=False):
        self.calls = []
        self.fail_after_mutation = fail_after_mutation

    async def execute(self, session, call):
        self.calls.append(call)
        session.writes += call.name == "write_file.v1"
        if self.fail_after_mutation:
            raise RuntimeError("connection lost after mutation")
        return ToolResult.ok(workspace_revision=str(session.writes + 1))


class Bindings:
    def __init__(self, *, mutation_error=None):
        self.session = Session()
        self.mutation_error = mutation_error

    async def resolve(self, lease):
        return SimpleNamespace(
            binding=SimpleNamespace(workspace_revision="1", provider="memory"),
            session=self.session,
        )

    async def record_mutation(self, lease, *, workspace_revision):
        if self.mutation_error is not None:
            raise self.mutation_error
        return None


class Session:
    def __init__(self) -> None:
        self.writes = 0

    async def workspace_revision(self) -> int:
        return self.writes + 1


@dataclass
class Harness:
    loop: AnthropicCodingLoop
    repository: InMemoryCodingRunRepository
    events: Events
    model: Model
    executor: Executor
    bindings: Bindings
    deps: LoopDependencies


def tool_call(call_id="toolu_1", name="write_file.v1", input=None):
    return ToolCallCompleted(call_id, name, input or {"path": "a.txt", "content": "x"})


def completed(input_tokens=5, output_tokens=3):
    return ModelCompleted("tool_use", ModelUsage(input_tokens, output_tokens))


def harness(
    turns,
    *,
    completed_tools=None,
    executor=None,
    config=None,
    audit=None,
    bindings=None,
    approval_evaluator=lambda _call: ApprovalPolicyOutcome.ALLOW,
):
    repository = InMemoryCodingRunRepository(completed_tools=completed_tools)
    repository.execution_leases["ct_1"] = LEASE
    run = CodingRun("cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW)
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    events = Events()
    model = Model(turns)
    executor = executor or Executor()
    bindings = bindings or Bindings()
    loop = AnthropicCodingLoop(
        model=model,
        tools=CodingToolRegistry.default(command_allowlist=frozenset({"git"})),
        executor=executor,
        bindings=bindings,
        config=config or AnthropicLoopConfig(model="claude-test", system="code"),
        audit=audit,
        clock=lambda: NOW,
        approval_evaluator=approval_evaluator,
    )
    deps = LoopDependencies(repository=repository, events=events, lease=LEASE)
    return Harness(loop, repository, events, model, executor, bindings, deps)


LEASE = ExecutionLease("ct_1", "cr_1", "worker", 1, NOW, NOW + timedelta(minutes=1))
INPUT = LoopInput("ct_1", "cr_1", "Fix it")


async def collect(h, checkpoint=None):
    return [event async for event in h.loop.run(INPUT, checkpoint, h.deps)]


@pytest.mark.asyncio
async def test_user_workspace_edits_are_added_to_the_model_transcript() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(5, 3))]])
    input = LoopInput(
        "ct_1",
        "cr_1",
        "Fix it",
        workspace_edits=(
            WorkspaceEditContext("cwe_1", "src/app.py", "13"),
        ),
    )

    _ = [event async for event in h.loop.run(input, None, h.deps)]

    messages = h.model.requests[0].messages
    assert len(messages) == 2
    assert messages[-1].role == "user"
    text = messages[-1].content[0].text
    assert "src/app.py @ revision 13" in text
    assert "read files before changing them" in text


@pytest.mark.asyncio
async def test_one_invocation_executes_and_checkpoints_one_tool_call() -> None:
    h = harness([[tool_call(), completed()]])
    events = await collect(h)
    assert h.bindings.session.writes == 1
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1
    assert sum(event.type == "tool.completed" for event in events) == 1


@pytest.mark.asyncio
async def test_workspace_write_requests_approval_before_claim_or_execution() -> None:
    h = harness([[tool_call(), completed()]], approval_evaluator=evaluate_approval)

    events = await collect(h)

    assert [event.type for event in events] == [
        "model.text_part.started",
        "model.text_part.completed",
        "approval.requested",
        "task.status.changed",
    ]
    assert h.repository.tool_execution_calls == []
    assert h.bindings.session.writes == 0


@pytest.mark.asyncio
async def test_approved_write_resumes_existing_claim_path_once() -> None:
    h = harness([[tool_call(), completed()]], approval_evaluator=evaluate_approval)
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1", approval_id=requested.approval_id,
        owner_id="test-owner", decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
    )

    await collect(h, h.repository.checkpoints[-1])

    assert h.bindings.session.writes == 1
    assert len(h.repository.tool_execution_calls) == 1


@pytest.mark.asyncio
async def test_denied_write_commits_result_without_execution() -> None:
    h = harness([[tool_call(), completed()]], approval_evaluator=evaluate_approval)
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1", approval_id=requested.approval_id,
        owner_id="test-owner", decision=ApprovalDecision.DENY,
        now=NOW + timedelta(seconds=1),
    )

    events = await collect(h, h.repository.checkpoints[-1])

    assert h.bindings.session.writes == 0
    assert events[-1].type == "tool.denied"
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1


@pytest.mark.asyncio
async def test_completed_claim_is_reused_without_reexecuting_mutation() -> None:
    h = harness(
        [[tool_call(), completed()]],
        completed_tools={
            ("ct_1", "toolu_1"): {"status": "ok", "workspace_revision": "2"}
        },
    )
    await collect(h)
    assert h.bindings.session.writes == 0
    assert h.repository.tool_execution_calls == []


@pytest.mark.asyncio
async def test_multiple_tool_calls_execute_across_invocations() -> None:
    h = harness(
        [
            [
                tool_call("one"),
                tool_call("two", input={"path": "b.txt", "content": "y"}),
                completed(),
            ]
        ]
    )
    await collect(h)
    assert h.bindings.session.writes == 1
    await collect(h, h.repository.checkpoints[-1])
    assert h.bindings.session.writes == 2
    assert len(h.model.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call,reason",
    [
        (tool_call(name="unknown.v1"), "policy_unknown_tool"),
        (tool_call(input={"path": "a.txt"}), "policy_schema_invalid"),
    ],
)
async def test_policy_or_schema_denial_checkpoints_without_claim(call, reason) -> None:
    audit = RecordingCodingAuditSink()
    h = harness([[call, completed()]], audit=audit)
    events = await collect(h)
    assert h.repository.tool_claims == {}
    assert (
        h.repository.checkpoints[-1].loop_state["transcript"][-1]["content"][0][
            "status"
        ]
        == "denied"
    )
    assert events[-1].payload["reason_code"] == reason
    assert audit.events == [
        {
            "provider": "memory",
            "tool": call.name if call.name == "write_file.v1" else "unknown",
            "operation": "validate",
            "outcome": "denied",
            "error_code": reason,
        }
    ]


@pytest.mark.asyncio
async def test_text_only_completion_uses_model_checkpoint_without_claim() -> None:
    h = harness([[TextDelta("finished"), ModelCompleted("end_turn", ModelUsage(2, 1))]])
    events = await collect(h)
    assert h.repository.tool_claims == {}
    assert events[-1].type == "model.completed"
    assert (
        h.repository.checkpoints[-1].loop_state["transcript"][-1]["content"][0]["text"]
        == "finished"
    )


@pytest.mark.asyncio
async def test_model_text_uses_one_durable_part_lifecycle() -> None:
    h = harness(
        [[TextDelta("hel"), TextDelta("lo"), ModelCompleted("end_turn", ModelUsage(2, 1))]]
    )

    events = await collect(h)
    text_events = [event for event in events if event.type.startswith("model.text")]

    assert [event.type for event in text_events] == [
        "model.text_part.started",
        "model.text_delta",
        "model.text_delta",
        "model.text_part.completed",
    ]
    assert [event.payload.get("delta") for event in text_events[1:3]] == [
        "hel",
        "lo",
    ]
    assert len({event.payload["part_id"] for event in text_events}) == 1
    assert len({event.turn_id for event in text_events}) == 1


@pytest.mark.asyncio
async def test_oversized_unicode_delta_fails_before_public_persistence() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_text_delta_bytes=5,
        max_public_text_bytes=10,
    )
    h = harness([[TextDelta("안녕"), completed()]], config=config)

    with pytest.raises(CodingLoopFailure, match="model_text_delta_too_large"):
        await collect(h)

    part = next(iter(h.repository.text_parts.values()))
    assert part.content == ""


@pytest.mark.asyncio
async def test_streaming_deltas_are_sanitized_and_not_recovery_content() -> None:
    h = harness(
        [
            [
                TextDelta("token sk-ant-secret"),
                ToolInputDelta("x", "write_file.v1", '{"content":"secret"}'),
                tool_call("x"),
                completed(),
            ]
        ]
    )
    events = await collect(h)
    model_delta = next(e for e in events if e.type == "model.text_delta")
    tool_delta = next(e for e in events if e.type == "model.tool_input_delta")
    assert model_delta.payload["delta"] == "token sk-ant-secret"
    assert "secret" not in str(tool_delta.payload)
    assert "partial_json" not in str(h.repository.checkpoints[-1].loop_state)


@pytest.mark.asyncio
async def test_busy_claim_is_retryable() -> None:
    h = harness([[tool_call(), completed()]])
    h.repository.tool_claims[("ct_1", "toolu_1")] = (
        SimpleNamespace(disposition=ToolExecutionDisposition.CLAIMED),
        NOW + timedelta(minutes=1),
    )
    with pytest.raises(CodingLoopFailure, match="tool_execution_busy") as caught:
        await collect(h)
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_provider_error_preserves_retryability() -> None:
    h = harness([CodingModelError("model_rate_limited", retryable=True)])
    with pytest.raises(CodingLoopFailure, match="model_rate_limited") as caught:
        await collect(h)
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_unknown_mutation_outcome_is_non_retryable() -> None:
    audit = RecordingCodingAuditSink()
    h = harness(
        [[tool_call(), completed()]],
        executor=Executor(fail_after_mutation=True),
        audit=audit,
    )
    with pytest.raises(CodingLoopFailure, match="tool_outcome_unknown") as caught:
        await collect(h)
    assert caught.value.retryable is False
    assert audit.events[-1]["outcome"] == "error"
    assert audit.events[-1]["error_code"] == "tool_outcome_unknown"


@pytest.mark.asyncio
async def test_stale_mutation_bookkeeping_is_unknown_outcome() -> None:
    audit = RecordingCodingAuditSink()
    h = harness(
        [[tool_call(), completed()]],
        bindings=Bindings(mutation_error=StaleExecutionLease("ct_1")),
        audit=audit,
    )

    with pytest.raises(CodingLoopFailure, match="tool_outcome_unknown") as caught:
        await collect(h)

    assert caught.value.retryable is False
    assert audit.events[-1]["error_code"] == "tool_outcome_unknown"


@pytest.mark.asyncio
async def test_cancellation_is_not_wrapped() -> None:
    h = harness([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await collect(h)


@pytest.mark.asyncio
async def test_turn_and_tool_budgets_are_durable() -> None:
    config = AnthropicLoopConfig(
        model="claude-test", system="code", max_turns=1, max_tools=1
    )
    h = harness([[tool_call("one"), tool_call("two"), completed()]], config=config)
    await collect(h)
    with pytest.raises(CodingLoopFailure, match="tool_budget_exceeded"):
        await collect(h, h.repository.checkpoints[-1])


@pytest.mark.asyncio
async def test_transcript_digest_and_compaction_are_deterministic() -> None:
    config = AnthropicLoopConfig(
        model="claude-test", system="code", max_transcript_messages=2
    )
    h = harness([[tool_call("one"), tool_call("two"), completed()]], config=config)
    await collect(h)
    first = h.repository.checkpoints[-1]
    await collect(h, first)
    state = h.repository.checkpoints[-1].loop_state
    assert len(state["transcript"]) <= 2
    assert len(state["transcript_digest"]) == 64


@pytest.mark.asyncio
async def test_transcript_byte_cap_preserves_pending_multi_tool_structure() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_bytes=700,
        max_text_delta_bytes=700,
        max_public_text_bytes=700,
    )
    calls = [
        tool_call("one", input={"content": "x" * 4000}),
        tool_call("two", input={"content": "y" * 4000}),
    ]
    h = harness([[TextDelta("z" * 600), *calls, completed()]], config=config)

    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    encoded = json.dumps(
        state["transcript"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    assert len(encoded) <= 700
    assert [call["tool_call_id"] for call in state["pending_tool_calls"]] == [
        "one",
        "two",
    ]
    assistant = next(
        message for message in state["transcript"] if message["role"] == "assistant"
    )
    assert [item["tool_call_id"] for item in assistant["content"]] == ["one", "two"]


@pytest.mark.asyncio
async def test_tiny_completed_transcript_cap_fails_before_checkpoint() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_bytes=8,
        max_text_delta_bytes=8,
        max_public_text_bytes=8,
    )
    h = harness([[TextDelta("finished"), completed()]], config=config)

    with pytest.raises(CodingLoopFailure, match="transcript_budget_exceeded") as caught:
        await collect(h)

    assert caught.value.retryable is False
    assert h.repository.checkpoints == []


@pytest.mark.asyncio
async def test_pending_tool_structure_over_cap_fails_before_execution() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_bytes=250,
        max_text_delta_bytes=250,
        max_public_text_bytes=250,
    )
    calls = [
        tool_call(f"tool_{index}", input={"content": "x" * 1000})
        for index in range(10)
    ]
    h = harness([[*calls, completed()]], config=config)

    with pytest.raises(CodingLoopFailure, match="transcript_budget_exceeded"):
        await collect(h)

    assert h.repository.checkpoints == []
    assert h.executor.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,code",
    [
        (
            AnthropicLoopConfig(model="claude-test", system="code", max_total_tokens=1),
            "token_budget_exceeded",
        ),
        (
            AnthropicLoopConfig(
                model="claude-test",
                system="code",
                max_cost_micros=1,
                input_cost_micros_per_million=1_000_000,
            ),
            "cost_budget_exceeded",
        ),
    ],
)
async def test_token_and_cost_budgets_stop_before_checkpoint(config, code) -> None:
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(2, 0))]],
        config=config,
    )
    with pytest.raises(CodingLoopFailure, match=code):
        await collect(h)
    assert h.repository.checkpoints == []


@pytest.mark.parametrize(
    "field",
    ["input_cost_micros_per_million", "output_cost_micros_per_million"],
)
def test_negative_model_prices_are_rejected(field) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        AnthropicLoopConfig(model="claude-test", system="code", **{field: -1})


@pytest.mark.asyncio
async def test_reclaimed_mutating_claim_is_never_executed() -> None:
    h = harness([[tool_call(), completed()]])
    h.repository.tool_claims[("ct_1", "toolu_1")] = (
        SimpleNamespace(disposition=ToolExecutionDisposition.CLAIMED),
        NOW - timedelta(seconds=1),
    )
    with pytest.raises(CodingLoopFailure, match="tool_outcome_unknown") as caught:
        await collect(h)
    assert caught.value.retryable is False
    assert h.bindings.session.writes == 0


@pytest.mark.asyncio
async def test_reclaimed_read_only_claim_is_safely_rerun() -> None:
    call = tool_call("read_1", "read_file.v1", {"path": "a.txt"})
    h = harness([[call, completed()]])
    h.repository.tool_claims[("ct_1", "read_1")] = (
        SimpleNamespace(disposition=ToolExecutionDisposition.CLAIMED),
        NOW - timedelta(seconds=1),
    )

    events = await collect(h)

    assert len(h.executor.calls) == 1
    assert sum(event.type == "tool.completed" for event in events) == 1
    assert h.bindings.session.writes == 0


@pytest.mark.asyncio
async def test_text_completion_marks_terminal_intent_for_next_invocation() -> None:
    h = harness([[TextDelta("finished"), ModelCompleted("end_turn", ModelUsage(2, 1))]])
    await collect(h)
    checkpoint = h.repository.checkpoints[-1]
    assert checkpoint.loop_state["terminal_pending"] is True
    assert await collect(h, checkpoint) == []
    assert len(h.model.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["max_tokens", "future_reason"])
async def test_nonterminal_no_tool_stop_reasons_fail_closed(stop_reason) -> None:
    h = harness([[TextDelta("partial"), ModelCompleted(stop_reason, ModelUsage(2, 1))]])

    with pytest.raises(CodingLoopFailure) as caught:
        await collect(h)

    assert caught.value.code == "model_output_incomplete"
    assert caught.value.retryable is False
    assert h.repository.checkpoints == []


@pytest.mark.asyncio
async def test_tool_error_budget_checkpoints_before_failure_and_does_not_repeat_event() -> None:
    config = AnthropicLoopConfig(
        model="claude-test", system="code", max_consecutive_tool_errors=1
    )
    h = harness([[tool_call(), completed()]], config=config)
    h.executor.execute = lambda session, call: _error_result()

    first_events = []
    with pytest.raises(CodingLoopFailure, match="tool_error_budget_exceeded"):
        async for event in h.loop.run(INPUT, None, h.deps):
            first_events.append(event)
    checkpoint = h.repository.checkpoints[-1]
    assert sum(event.type == "tool.completed" for event in first_events) == 1

    with pytest.raises(CodingLoopFailure, match="tool_error_budget_exceeded"):
        await collect(h, checkpoint)
    assert sum(event.type == "tool.completed" for event in first_events) == 1


async def _error_result():
    return ToolResult(
        "error", "command_failed", None, None, False, None, "1", exit_code=1
    )
