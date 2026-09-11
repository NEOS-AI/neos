import asyncio
import json
from dataclasses import dataclass, replace
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
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
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
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
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

    async def execute(self, session, call, **kwargs):
        self.calls.append(call)
        session.writes += call.name == "write_file.v1"
        if self.fail_after_mutation:
            raise RuntimeError("connection lost after mutation")
        return ToolResult.ok(workspace_revision=str(session.writes + 1))


class Bindings:
    def __init__(self, *, mutation_error=None, files=None):
        self.session = Session(files=files)
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
    def __init__(self, files=None) -> None:
        self.writes = 0
        self.files = {
            name: value if isinstance(value, bytes) else value.encode("utf-8")
            for name, value in dict(files or {}).items()
        }

    async def workspace_revision(self) -> int:
        return self.writes + 1

    async def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


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
    hooks=None,
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
        hooks=hooks,
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
async def test_model_tool_use_is_checkpointed_before_first_execute() -> None:
    h = harness([[tool_call(), completed()]])
    order: list[str] = []
    original_commit = h.repository.commit_model_checkpoint
    original_execute = h.executor.execute

    async def recording_commit(**kwargs):
        pending = list(kwargs["loop_state"].get("pending_tool_calls") or ())
        if pending and int(kwargs["loop_state"].get("pending_tool_index", 0)) == 0:
            order.append("commit")
        return await original_commit(**kwargs)

    async def recording_execute(session, call, **kwargs):
        order.append("execute")
        assert any(
            list(item.loop_state.get("pending_tool_calls") or ())
            and int(item.loop_state.get("pending_tool_index", 0)) == 0
            for item in h.repository.checkpoints
        )
        return await original_execute(session, call, **kwargs)

    h.repository.commit_model_checkpoint = recording_commit
    h.executor.execute = recording_execute

    await collect(h)

    assert "commit" in order
    assert "execute" in order
    assert order.index("commit") < order.index("execute")


@pytest.mark.asyncio
async def test_workspace_write_requests_approval_before_claim_or_execution() -> None:
    h = harness([[tool_call(), completed()]], approval_evaluator=evaluate_approval)

    events = await collect(h)

    assert [event.type for event in events] == [
        "model.text_part.started",
        "model.text_part.completed",
        "model.completed",
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
async def test_remember_write_approval_adds_tool_to_approved_always() -> None:
    h = harness(
        [
            [tool_call("w1"), completed()],
            [
                tool_call("w2", input={"path": "b.txt", "content": "y"}),
                completed(),
            ],
        ],
        approval_evaluator=evaluate_approval,
    )
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
        remember=True,
    )

    await collect(h, h.repository.checkpoints[-1])
    assert "write_file.v1" in h.repository.checkpoints[-1].loop_state["approved_always"]

    events = await collect(h, h.repository.checkpoints[-1])

    assert not any(event.type == "approval.requested" for event in events)
    assert h.bindings.session.writes == 2
    assert "write_file.v1" in h.repository.checkpoints[-1].loop_state["approved_always"]


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
    events = await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    results = [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert results[-1]["status"] == "error"
    assert results[-1]["content"]["reason_code"] == "tool_outcome_unknown"
    assert state["pending_tool_index"] == 1
    assert any(event.type == "tool.completed" for event in events)
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
    assert len(state["transcript_digest"]) == 64
    use_ids = _transcript_tool_ids(state["transcript"], "tool_use")
    result_ids = _transcript_tool_ids(state["transcript"], "tool_result")
    assert "one" in use_ids and "two" in use_ids
    assert "one" in result_ids and "two" in result_ids


@pytest.mark.asyncio
async def test_transcript_byte_cap_preserves_pending_multi_tool_structure() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_bytes=1600,
        max_text_delta_bytes=1600,
        max_public_text_bytes=1600,
    )
    h = harness(
        [
            [
                TextDelta("z" * 700),
                tool_call("old", input={"content": "w" * 400}),
                completed(),
            ],
            [
                tool_call("one", input={"content": "x"}),
                tool_call("two", input={"content": "y"}),
                completed(),
            ],
        ],
        config=config,
    )

    await collect(h)
    await collect(h, h.repository.checkpoints[-1])
    state = h.repository.checkpoints[-1].loop_state
    encoded = json.dumps(
        state["transcript"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    assert len(encoded) <= 1600
    assert [call["tool_call_id"] for call in state["pending_tool_calls"]] == [
        "one",
        "two",
    ]
    assistant = next(
        message
        for message in reversed(state["transcript"])
        if message["role"] == "assistant"
    )
    assert [
        item["tool_call_id"]
        for item in assistant["content"]
        if item.get("type") == "tool_use"
    ] == ["one", "two"]


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
async def test_nonterminal_no_tool_stop_reasons_fail_closed() -> None:
    h = harness([[TextDelta("partial"), ModelCompleted("future_reason", ModelUsage(2, 1))]])

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
    h.executor.execute = lambda session, call, **_kwargs: _error_result()

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


def _transcript_tool_ids(transcript, content_type: str) -> list[str]:
    return [
        item["tool_call_id"]
        for message in transcript
        for item in message["content"]
        if item.get("type") == content_type
    ]


@pytest.mark.asyncio
async def test_cancel_synthesizes_aborted_results_for_pending_tool_ids() -> None:
    class CancellingExecutor(Executor):
        async def execute(self, session, call, **kwargs):
            raise asyncio.CancelledError()

    h = harness(
        [
            [
                tool_call("one"),
                tool_call("two", input={"path": "b.txt", "content": "y"}),
                completed(),
            ]
        ],
        executor=CancellingExecutor(),
    )

    with pytest.raises(asyncio.CancelledError):
        await collect(h)

    state = h.repository.checkpoints[-1].loop_state
    use_ids = _transcript_tool_ids(state["transcript"], "tool_use")
    result_items = [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]
    assert use_ids == ["one", "two"]
    assert [item["tool_call_id"] for item in result_items] == ["one", "two"]
    assert all(item["status"] == "error" for item in result_items)
    assert all(item["content"]["reason_code"] == "aborted" for item in result_items)


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_pending_interrupt_aborts_in_flight_model_turn() -> None:
    started = asyncio.Event()
    resume = asyncio.Event()
    commits: list[dict] = []

    class GatedModel:
        async def stream(self, request):
            yield TextDelta("working")
            started.set()
            await resume.wait()
            yield ModelCompleted("end_turn", ModelUsage(2, 1))

    h = harness([[TextDelta("unused"), completed()]])
    h.model = GatedModel()
    h.loop._model = h.model
    original = h.repository.commit_model_checkpoint

    async def recording_commit(**kwargs):
        commits.append(dict(kwargs.get("event_payload") or {}))
        return await original(**kwargs)

    h.repository.commit_model_checkpoint = recording_commit
    task = asyncio.create_task(collect(h))
    await started.wait()
    await h.repository.queue_steering(
        SteeringRequest(
            steering_id="cs_stop",
            task_id="ct_1",
            mode=SteeringMode.INTERRUPT_NOW,
            instruction="stop",
            requested_at=NOW,
        )
    )
    resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert h.repository.checkpoints
    assert commits
    assert commits[-1]["reason_code"] == "aborted"


@pytest.mark.asyncio
async def test_task_cancel_still_persists_aborted_checkpoint() -> None:
    started = asyncio.Event()

    class BlockingExecutor(Executor):
        async def execute(self, session, call, **kwargs):
            started.set()
            await asyncio.sleep(3600)
            return await super().execute(session, call, **kwargs)

    h = harness(
        [
            [
                tool_call("one"),
                tool_call("two", input={"path": "b.txt", "content": "y"}),
                completed(),
            ]
        ],
        executor=BlockingExecutor(),
    )
    task = asyncio.create_task(collect(h))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    state = h.repository.checkpoints[-1].loop_state
    use_ids = _transcript_tool_ids(state["transcript"], "tool_use")
    result_ids = _transcript_tool_ids(state["transcript"], "tool_result")
    assert use_ids == ["one", "two"]
    assert result_ids == ["one", "two"]


@pytest.mark.asyncio
async def test_two_leading_reads_share_one_checkpoint_excluding_following_write() -> None:
    h = harness(
        [
            [
                tool_call("read_a", "read_file.v1", {"path": "a.txt"}),
                tool_call("read_b", "read_file.v1", {"path": "b.txt"}),
                tool_call("write_c", input={"path": "c.txt", "content": "z"}),
                completed(),
            ]
        ]
    )

    events = await collect(h)

    assert [call.name for call in h.executor.calls] == [
        "read_file.v1",
        "read_file.v1",
    ]
    assert h.bindings.session.writes == 0
    assert sum(event.type == "phase.completed" for event in events) == 1
    assert sum(event.type == "tool.completed" for event in events) == 2
    state = h.repository.checkpoints[-1].loop_state
    assert state["pending_tool_index"] == 2
    assert [call["tool_call_id"] for call in state["pending_tool_calls"]] == [
        "read_a",
        "read_b",
        "write_c",
    ]

    await collect(h, h.repository.checkpoints[-1])

    assert h.bindings.session.writes == 1
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 3
    assert len(h.executor.calls) == 3


@pytest.mark.asyncio
async def test_pending_instruction_is_appended_as_user_text_then_cleared() -> None:
    h = harness(
        [
            [tool_call(), completed()],
            [ModelCompleted("end_turn", ModelUsage(2, 1))],
        ]
    )
    await collect(h)
    checkpoint = h.repository.checkpoints[-1]
    checkpoint.loop_state["pending_instruction"] = "Inspect cache first"

    await collect(h, checkpoint)

    texts = [
        item.text
        for message in h.model.requests[-1].messages
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert "Inspect cache first" in texts
    assert h.repository.checkpoints[-1].loop_state["pending_instruction"] is None


@pytest.mark.asyncio
async def test_compact_over_budget_keeps_matching_active_tool_pair_ids() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_messages=2,
    )
    h = harness(
        [
            [
                tool_call("old", input={"path": "a.txt", "content": "x" * 80}),
                completed(),
            ],
            [
                tool_call("active", input={"path": "b.txt", "content": "y" * 80}),
                completed(),
            ],
        ],
        config=config,
    )
    await collect(h)
    await collect(h, h.repository.checkpoints[-1])

    state = h.repository.checkpoints[-1].loop_state
    use_ids = _transcript_tool_ids(state["transcript"], "tool_use")
    result_ids = _transcript_tool_ids(state["transcript"], "tool_result")
    assert "active" in use_ids
    assert "active" in result_ids
    assert use_ids[-1] == result_ids[-1] == "active"


def test_compact_prefix_drop_never_splits_tool_use_result_pairs() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_messages=4,
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=config)

    def pair(call_id: str) -> tuple[CanonicalMessage, CanonicalMessage]:
        return (
            CanonicalMessage(
                "assistant",
                (ToolUseContent(call_id, "read_file.v1", {"path": f"{call_id}.txt"}),),
            ),
            CanonicalMessage(
                "tool",
                (ToolResultContent(call_id, "ok", {"body": "x" * 20}),),
            ),
        )

    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        *pair("old_1"),
        *pair("old_2"),
        *pair("active"),
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

    assert set(use_ids) == set(result_ids)
    assert "active" in use_ids
    assert "old_1" not in use_ids
    assert "old_1" not in result_ids


def test_compact_shrinks_old_results_to_preview_and_sha256() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        max_transcript_bytes=900,
        max_text_delta_bytes=900,
        max_public_text_bytes=900,
    )
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=config)
    old_body = {
        "preview": "Z" * 400,
        "path": "src/a.py",
        "entries": [{"text": "full file body"}],
    }
    digest = __import__("hashlib").sha256(
        json.dumps(
            old_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    transcript = (
        CanonicalMessage("user", (TextContent("start"),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("old", "read_file.v1", {"path": "src/a.py"}),),
        ),
        CanonicalMessage("tool", (ToolResultContent("old", "ok", old_body),)),
        CanonicalMessage(
            "assistant",
            (ToolUseContent("active", "read_file.v1", {"path": "src/b.py"}),),
        ),
        CanonicalMessage(
            "tool",
            (ToolResultContent("active", "ok", {"preview": "kept"}),),
        ),
    )

    compacted = h.loop._compact(transcript)
    results = {
        item.tool_call_id: dict(item.content)
        for message in compacted
        for item in message.content
        if isinstance(item, ToolResultContent)
    }

    assert results["old"]["compacted"] is True
    assert results["old"]["sha256"] == digest
    assert results["old"]["preview"] == "Z" * 200
    assert results["old"]["path"] == "src/a.py"
    assert results["active"] == {"preview": "kept"}


@pytest.mark.asyncio
async def test_first_turn_loads_agents_md_as_fenced_user_message() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(5, 3))]],
        bindings=Bindings(files={"AGENTS.md": b"Use ruff."}),
    )

    await collect(h)

    request = h.model.requests[0]
    assert request.system == "code"
    assert "Use ruff." not in request.system
    assert "begin workspace instructions" not in request.system
    texts = [
        item.text
        for message in request.messages
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    fenced = next(text for text in texts if "begin workspace instructions" in text)
    assert "Use ruff." in fenced
    assert "Source: AGENTS.md" in fenced
    assert h.repository.checkpoints[-1].loop_state["instructions_loaded"] is True


@pytest.mark.asyncio
async def test_explore_phase_omits_write_file_from_model_tools() -> None:
    h = harness(
        [
            [ModelCompleted("end_turn", ModelUsage(5, 3))],
            [ModelCompleted("end_turn", ModelUsage(2, 1))],
        ]
    )
    await collect(h)
    checkpoint = h.repository.checkpoints[-1]
    checkpoint.loop_state["phase"] = "explore"
    checkpoint.loop_state["terminal_pending"] = False
    checkpoint.loop_state["pending_instruction"] = "Look around"

    await collect(h, checkpoint)

    names = [tool.name for tool in h.model.requests[-1].tools]
    assert "write_file.v1" not in names
    assert "edit_file.v1" not in names
    assert "execute.v1" not in names
    assert "read_file.v1" in names


@pytest.mark.asyncio
async def test_prompt_too_long_checkpoints_without_dropping_the_task() -> None:
    h = harness([CodingModelError("prompt_too_long", retryable=True)])

    events = await collect(h)

    assert any(event.checkpoint_id for event in events)
    state = h.repository.checkpoints[-1].loop_state
    assert state["prompt_compact_retries"] == 1
    user_texts = [
        item["content"][0]["text"]
        for item in state["transcript"]
        if item["role"] == "user" and item["content"]
    ]
    assert any("Fix it" in text for text in user_texts)


@pytest.mark.asyncio
async def test_max_tokens_once_checkpoints_escalation_without_assistant_turn() -> None:
    h = harness([[TextDelta("partial"), ModelCompleted("max_tokens", ModelUsage(2, 1))]])

    events = await collect(h)

    assert any(event.checkpoint_id for event in events)
    state = h.repository.checkpoints[-1].loop_state
    assert state["output_token_escalations"] == 1
    assert all(item["role"] != "assistant" for item in state["transcript"])


@pytest.mark.asyncio
async def test_second_max_tokens_without_tools_is_incomplete() -> None:
    h = harness(
        [
            [TextDelta("partial"), ModelCompleted("max_tokens", ModelUsage(2, 1))],
            [TextDelta("still"), ModelCompleted("max_tokens", ModelUsage(2, 1))],
        ]
    )
    await collect(h)
    checkpoint = h.repository.checkpoints[-1]

    with pytest.raises(CodingLoopFailure) as caught:
        await collect(h, checkpoint)

    assert caught.value.code == "model_output_incomplete"
    assert caught.value.retryable is False
    assert h.model.requests[-1].limits.max_output_tokens == min(4096 * 4, 64_000)


@pytest.mark.asyncio
async def test_set_phase_success_updates_loop_state_phase() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(INPUT, None)
    after = await h.loop._after_result(
        state,
        ToolResultContent("phase_1", "ok", {}),
        tool_name="set_phase.v1",
        tool_input={"phase": "explore"},
    )

    assert after.phase == "explore"
    assert h.loop._dump_state(INPUT, after)["phase"] == "explore"


@pytest.mark.asyncio
async def test_hidden_tool_in_explore_phase_is_denied() -> None:
    h = harness([[tool_call(), completed()]])
    checkpoint = CodingCheckpoint(
        "cc_explore",
        "ct_1",
        "cr_1",
        1,
        {
            "transcript": [
                {"role": "user", "content": [{"type": "text", "text": "Fix it"}]},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "tool_call_id": "toolu_1",
                            "name": "write_file.v1",
                            "input": {"path": "a.txt", "content": "x"},
                        }
                    ],
                },
            ],
            "pending_tool_calls": [
                {
                    "tool_call_id": "toolu_1",
                    "name": "write_file.v1",
                    "input": {"path": "a.txt", "content": "x"},
                }
            ],
            "pending_tool_index": 0,
            "phase": "explore",
            "turn_count": 1,
            "tool_count": 0,
            "transcript_digest": "x",
            "instructions_loaded": True,
        },
        "1",
        NOW,
    )

    events = await collect(h, checkpoint)

    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_phase_denied"
    assert h.bindings.session.writes == 0
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_set_phase_to_implement_is_not_batched_past_the_approval_gate() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        approval_evaluator=evaluate_approval,
    )
    checkpoint = CodingCheckpoint(
        "cc_plan",
        "ct_1",
        "cr_1",
        1,
        {
            "transcript": [
                {"role": "user", "content": [{"type": "text", "text": "Fix it"}]},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "tool_call_id": "phase_1",
                            "name": "set_phase.v1",
                            "input": {"phase": "implement"},
                        },
                        {
                            "type": "tool_use",
                            "tool_call_id": "read_1",
                            "name": "read_file.v1",
                            "input": {"path": "a.txt"},
                        },
                    ],
                },
            ],
            "pending_tool_calls": [
                {
                    "tool_call_id": "phase_1",
                    "name": "set_phase.v1",
                    "input": {"phase": "implement"},
                },
                {
                    "tool_call_id": "read_1",
                    "name": "read_file.v1",
                    "input": {"path": "a.txt"},
                },
            ],
            "pending_tool_index": 0,
            "phase": "plan",
            "turn_count": 1,
            "tool_count": 0,
            "transcript_digest": "x",
            "instructions_loaded": True,
        },
        "1",
        NOW,
    )

    events = await collect(h, checkpoint)

    assert any(event.type == "approval.requested" for event in events)
    assert h.executor.calls == []
    assert h.repository.checkpoints[-1].loop_state["phase"] == "plan"


@pytest.mark.asyncio
async def test_readonly_tools_are_prefetched_once_during_model_stream() -> None:
    h = harness(
        [
            [
                tool_call("r1", "read_file.v1", {"path": "a.txt"}),
                tool_call("r2", "read_file.v1", {"path": "b.txt"}),
                completed(),
            ]
        ]
    )
    await collect(h)
    names = [call.name for call in h.executor.calls]
    assert names.count("read_file.v1") == 2


@pytest.mark.asyncio
async def test_spawn_agent_returns_child_summary() -> None:
    h = harness(
        [
            [
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {"prompt": "look around", "max_turns": 1},
                ),
                completed(),
            ]
        ]
    )
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    payload = completed_events[-1].payload["result"]
    assert payload.get("delegated") is False
    assert payload.get("use_phase") == "explore"
    assert payload.get("note")
    assert all(getattr(request, "task_id", None) != "spawn" for request in h.model.requests)


@pytest.mark.asyncio
async def test_spawn_agent_is_not_batched_with_other_readonly_tools() -> None:
    h = harness(
        [
            [
                tool_call("r1", "read_file.v1", {"path": "a.txt"}),
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {"prompt": "look around", "max_turns": 1},
                ),
                completed(),
            ]
        ]
    )
    first = await collect(h)
    assert all(
        event.payload.get("result", {}).get("entries") != ({"delegated": True},)
        for event in first
        if event.type == "tool.completed"
    )
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1

    events = await collect(h, h.repository.checkpoints[-1])
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    payload = completed_events[-1].payload["result"]
    assert payload.get("delegated") is False
    assert payload.get("use_phase") == "explore"
    assert not any(
        item == {"delegated": True}
        for item in (payload.get("entries") or ())
        if isinstance(item, dict)
    )


@pytest.mark.asyncio
async def test_spawn_agent_stops_inner_loop_on_interrupt() -> None:
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
    assert all(getattr(request, "task_id", None) != "spawn" for request in h.model.requests)


@pytest.mark.asyncio
async def test_llm_compact_keeps_first_user_instruction() -> None:
    from neos.coding.model.base import CanonicalMessage, TextContent

    h = harness(
        [[TextDelta("old files were edited"), ModelCompleted("end_turn", ModelUsage(1, 1))]]
    )
    state = h.loop._restore(INPUT, None)
    long_prefix = tuple(
        CanonicalMessage("user", (TextContent(f"note {index} " + ("x" * 20)),))
        for index in range(4)
    )
    state = replace(
        state,
        transcript=(state.transcript[0],) + long_prefix,
        llm_compact_attempts=0,
    )
    compacted, attempts = await h.loop._maybe_llm_compact(state, state.transcript)
    assert attempts == 1
    assert compacted[0].content[0].text == "Fix it"
    assert "old files were edited" in compacted[1].content[0].text


class _DecisionHook:
    def __init__(self, decision: str, reason: str = "blocked") -> None:
        self.decision = decision
        self.reason = reason

    async def pre_tool(self, call):
        return {"decision": self.decision, "reason": self.reason}

    async def post_tool(self, call, result) -> None:
        return None

    async def stop(self, reason: str) -> None:
        return None

    async def compact(self, before, after) -> None:
        return None


@pytest.mark.asyncio
async def test_pre_tool_deny_commits_policy_hook_denied_without_execute() -> None:
    h = harness([[tool_call(), completed()]], hooks=_DecisionHook("deny"))

    events = await collect(h)

    assert h.executor.calls == []
    assert events[-1].type == "tool.denied"
    assert events[-1].payload["reason_code"] == "policy_hook_denied"
    assert h.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1


@pytest.mark.asyncio
async def test_pre_tool_retry_returns_without_execute_or_splitting_pairs() -> None:
    h = harness([[tool_call(), completed()]], hooks=_DecisionHook("retry", "try later"))

    events = await collect(h)

    assert h.executor.calls == []
    assert any(event.type == "model.completed" for event in events)
    state = h.repository.checkpoints[-1].loop_state
    assert state["hook_retry_count"] == 1
    assert state["pending_tool_index"] == 0
    roles = [message["role"] for message in state["transcript"]]
    assert "user" not in roles[1:] or all(
        item.get("type") != "text" or "Hook requested" not in item.get("text", "")
        for message in state["transcript"]
        if message["role"] == "user"
        for item in message["content"]
    )
