"""Shared test support for the coding loop: fakes, the `harness` builder and checkpoints."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from neos.coding.domain.approvals import ApprovalPolicyOutcome
from neos.coding.domain.durability import ExecutionLease
from neos.coding.domain.events import make_event
from neos.coding.domain.phases import CodingCheckpoint, CodingRun, CodingRunStatus
from neos.coding.loop import Compactor, ToolCatalog, encode_state, restore_state
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop.anthropic import AnthropicCodingLoop, AnthropicLoopConfig
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.model.base import ModelCompleted, ModelUsage, ToolCallCompleted
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.registry import CodingToolRegistry
from tests.coding.fakes import InMemoryCodingRunRepository

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
    def __init__(self, *, mutation_error=None, files=None, workspace=None):
        self.session = Session(files=files, workspace=workspace)
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
    def __init__(self, files=None, workspace=None) -> None:
        self.writes = 0
        self.workspace = workspace
        self.files = {
            name: value if isinstance(value, bytes) else value.encode("utf-8")
            for name, value in dict(files or {}).items()
        }

    def clone_with_workspace(self, workspace):
        cloned = Session(files=self.files, workspace=workspace)
        cloned.writes = self.writes
        return cloned

    async def workspace_revision(self) -> int:
        return self.writes + 1

    async def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


LEASE = ExecutionLease("ct_1", "cr_1", "worker", 1, NOW, NOW + timedelta(minutes=1))
INPUT = LoopInput("ct_1", "cr_1", "Fix it")


async def collect(h, checkpoint=None):
    return [event async for event in h.loop.run(INPUT, checkpoint, h.deps)]


@dataclass
class Harness:
    loop: AnthropicCodingLoop
    repository: InMemoryCodingRunRepository
    events: Events
    model: Any
    executor: Executor
    bindings: Bindings
    deps: LoopDependencies
    #: What the loop was built with -- tests read these instead of the loop's fields.
    loop_kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def config(self) -> AnthropicLoopConfig:
        return self.loop_kwargs["config"]

    def catalog(self) -> ToolCatalog:
        """The tool catalog this harness's loop was built with."""
        return ToolCatalog(self.loop_kwargs["tools"], self.config)

    def compactor(self) -> Compactor:
        """The compactor this harness's loop was built with."""
        return Compactor(
            config=self.config,
            hooks=self.loop_kwargs["hooks"],
            model=self.loop_kwargs["model"],
            catalog=self.catalog(),
        )

    def restore(self, checkpoint, *, input=INPUT) -> AgentLoopState:
        """The state this harness's loop would resume `checkpoint` into."""
        return restore_state(
            input, checkpoint, catalog=self.catalog(), compactor=self.compactor()
        )

    def rebuilt(self, **overrides: Any) -> "Harness":
        """A new loop over the same repository, events and lease.

        A worker that resumes a stored checkpoint under a new deploy is a new
        loop instance; this is that. It is also how a test plugs in a
        dependency that needs this harness's own objects (its repository).
        """
        kwargs = {**self.loop_kwargs, **overrides}
        return replace(
            self,
            loop=AnthropicCodingLoop(**kwargs),
            model=kwargs["model"],
            executor=kwargs["executor"],
            bindings=kwargs["bindings"],
            loop_kwargs=kwargs,
        )


def tool_call(call_id="toolu_1", name="write_file.v1", input=None):
    return ToolCallCompleted(call_id, name, input or {"path": "a.txt", "content": "x"})


def completed(input_tokens=5, output_tokens=3):
    return ModelCompleted("tool_use", ModelUsage(input_tokens, output_tokens))


def harness(
    turns=(),
    *,
    model=None,
    tools=None,
    completed_tools=None,
    executor=None,
    config=None,
    audit=None,
    bindings=None,
    clock=lambda: NOW,
    approval_evaluator=lambda _call: ApprovalPolicyOutcome.ALLOW,
    hooks=None,
    subagents=None,
    command_allowlist=frozenset({"git"}),
    metrics=None,
    monitor=None,
    envelope=None,
    jev=None,
    user_rules=None,
    secrets=None,
    browser=None,
    device_bridge=None,
    asks=None,
):
    repository = InMemoryCodingRunRepository(completed_tools=completed_tools)
    repository.execution_leases["ct_1"] = LEASE
    run = CodingRun("cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW)
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    events = Events()
    loop_kwargs = dict(
        model=model if model is not None else Model(turns),
        tools=tools
        if tools is not None
        else CodingToolRegistry.default(command_allowlist=frozenset(command_allowlist)),
        executor=executor or Executor(),
        bindings=bindings or Bindings(),
        config=config or AnthropicLoopConfig(model="claude-test", system="code"),
        audit=audit,
        clock=clock,
        approval_evaluator=approval_evaluator,
        hooks=hooks,
        subagents=subagents,
        metrics=metrics,
        monitor=monitor,
        envelope=envelope,
        jev=jev,
        user_rules=user_rules,
        secrets=secrets,
        browser=browser,
        device_bridge=device_bridge,
        asks=asks,
    )
    loop = AnthropicCodingLoop(**loop_kwargs)
    deps = LoopDependencies(repository=repository, events=events, lease=LEASE)
    return Harness(
        loop,
        repository,
        events,
        loop_kwargs["model"],
        loop_kwargs["executor"],
        loop_kwargs["bindings"],
        deps,
        loop_kwargs,
    )


def checkpoint_for(state, *, input=INPUT, checkpoint_id="cc_test") -> CodingCheckpoint:
    """A stored checkpoint that holds `state` -- the way a test starts a run at state X."""
    return CodingCheckpoint(
        checkpoint_id, input.task_id, input.run_id, 1, encode_state(input, state), "1", NOW
    )


class DecisionHook:
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
