from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from neos.coding.application.run_service import CodingRunService, InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.phases import CodingPhaseKind
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.anthropic import AnthropicCodingLoop, AnthropicLoopConfig
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.coding.sandbox.observability import CodingToolAuditEvent
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry
from tests.coding.fakes import (
    InMemoryCodingRunRepository,
    InMemorySandboxBindingRepository,
    ScriptedCodingModel,
)


class CountingCrashExecutor:
    def __init__(self, *, crash_after=None) -> None:
        self.delegate = SandboxToolExecutor(max_preview_bytes=64_000, max_entries=100)
        self.crash_after = crash_after
        self.write_count = 0

    async def execute(self, session, call):
        result = await self.delegate.execute(session, call)
        if call.name == "write_file.v1":
            self.write_count += 1
            if self.crash_after == "write_file":
                raise RuntimeError("injected crash after write_file")
        return result


class CrashRepository(InMemoryCodingRunRepository):
    def __init__(self, *, crash_after=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.crash_after = crash_after

    async def complete_tool_execution(self, claim, *, result, now):
        event = await super().complete_tool_execution(claim, result=result, now=now)
        if self.crash_after == "complete_tool_execution":
            raise RuntimeError("injected crash after complete_tool_execution")
        return event


class RealLoopHarness:
    def __init__(
        self,
        *,
        provider,
        session,
        repository,
        binding_repository,
        runs,
        executor,
        events,
        now,
    ) -> None:
        self.provider = provider
        self.session = session
        self.repository = repository
        self.binding_repository = binding_repository
        self.runs = runs
        self.executor = executor
        self.events = events
        self.now = now

    async def advance(self, *, worker_id="worker-1"):
        return await self.runs.advance_one_safe_point(
            task_id="ct_real", worker_id=worker_id
        )

    async def advance_until_complete(self, *, worker_id="worker-1") -> None:
        for _ in range(20):
            event = await self.advance(worker_id=worker_id)
            if event.type == "run.completed":
                return
        raise AssertionError("real loop did not complete within 20 safe points")

    def elapse(self, delta) -> None:
        self.now.value += delta

    def disable_crash(self) -> None:
        self.executor.crash_after = None
        self.repository.crash_after = None

    @property
    def write_count(self):
        return self.executor.write_count

    @property
    def completed_tool_ids(self):
        return {key[1] for key in self.repository.completed_tools}

    @property
    def final_text(self):
        state = self.repository.checkpoints[-1].loop_state
        for message in reversed(state["transcript"]):
            for content in message["content"]:
                if content.get("type") == "text":
                    return content["text"]
        return None

    @property
    def audit_events(self):
        return [
            asdict(CodingToolAuditEvent.from_result(
                provider="memory", tool=call[1],
                operation="execute",
                outcome="ok",
            ))
            for call in sorted(self.completed_tool_ids_with_names)
        ]

    @property
    def completed_tool_ids_with_names(self):
        names = {}
        for checkpoint in self.repository.checkpoints:
            for call in checkpoint.loop_state.get("pending_tool_calls", ()):
                names[call["tool_call_id"]] = call["name"]
        return {
            (tool_id, names.get(tool_id, "unknown"))
            for tool_id in self.completed_tool_ids
        }

    async def replacement_lease(self):
        run = await self.repository.latest_run("ct_real")
        old = await self.repository.acquire_execution_lease(
            task_id="ct_real",
            run_id=run.run_id,
            worker_id="old",
            now=self.now.value,
            expires_at=self.now.value + timedelta(seconds=1),
        )
        claim = await self.repository.claim_tool_execution(
            lease=old,
            tool_call_id="tool_stale",
            now=self.now.value,
            claim_expires_at=self.now.value + timedelta(seconds=1),
        )
        phase = (await self.repository.begin_phase(
            lease=old, kind=CodingPhaseKind.IMPLEMENT, now=self.now.value
        )).phase
        self.elapse(timedelta(seconds=2))
        current = await self.repository.acquire_execution_lease(
            task_id="ct_real",
            run_id=run.run_id,
            worker_id="current",
            now=self.now.value,
            expires_at=self.now.value + timedelta(seconds=30),
        )
        return old, current, claim, phase

    async def commit_checkpoint(self, lease, phase):
        return await self.repository.commit_phase_checkpoint(
            lease=lease,
            phase=phase,
            tool_call_id="tool_stale",
            result={"status": "ok"},
            loop_state={"current_instruction": "test"},
            workspace_revision="1",
            now=self.now.value,
        )

    async def replace_binding_with_lease(self, lease):
        current_lease = self.repository.execution_leases.get(lease.task_id)
        if current_lease != lease:
            return False
        binding = self.binding_repository.current
        return (
            await self.binding_repository.replace(
                replace(binding, run_id=lease.run_id),
                expected_version=binding.version,
                now=self.now.value,
            )
            is not None
        )


@pytest.fixture
async def real_loop_harness(tmp_path):
    harnesses = []

    async def create(*, script, metrics=None, crash_after=None):
        now = SimpleNamespace(value=datetime(2026, 7, 19, tzinfo=UTC))
        provider = MemorySandboxProvider(root=tmp_path / f"sandbox-{len(harnesses)}")
        binding_repository = InMemorySandboxBindingRepository()
        bindings = SandboxBindingService(
            repository=binding_repository,
            provider=provider,
            limits=SandboxLimits.safe_defaults(),
            snapshot_cadence=10,
            clock=lambda: now.value,
        )
        bound = await bindings.resolve("ct_real", "pending")
        await bound.session.write_file("calc.py", b"def add(a, b): raise NotImplementedError\n")
        await bound.session.write_file(
            "test_calc.py",
            b"from calc import add\n\ndef test_add(): assert add(2, 3) == 5\n",
        )
        events = InMemoryCodingEventStore()
        tasks_repository = InMemoryCodingTaskRepository()
        tasks = CodingTaskService(tasks_repository, events, clock=lambda: now.value)
        await tasks.create_task(owner_id="u1", prompt="Implement add", task_id="ct_real")
        repository = CrashRepository(
            task_prompts={"ct_real": "Implement add"}, crash_after=crash_after
        )
        executor = CountingCrashExecutor(crash_after=crash_after)
        loop = AnthropicCodingLoop(
            model=ScriptedCodingModel(script),
            tools=CodingToolRegistry.default(command_allowlist=frozenset({"pytest"})),
            executor=executor,
            bindings=bindings,
            config=AnthropicLoopConfig(model="claude-test", system="code"),
            metrics=metrics,
            clock=lambda: now.value,
        )
        runs = CodingRunService(
            tasks=tasks_repository,
            runs=repository,
            events=events,
            interrupter=InProcessRunInterrupter(),
            loop=loop,
            clock=lambda: now.value,
        )
        await runs.ensure_started(task_id="ct_real")
        result = RealLoopHarness(
            provider=provider,
            session=bound.session,
            repository=repository,
            binding_repository=binding_repository,
            runs=runs,
            executor=executor,
            events=events,
            now=now,
        )
        harnesses.append(result)
        return result

    yield create
    for harness in harnesses:
        await harness.provider.close()
