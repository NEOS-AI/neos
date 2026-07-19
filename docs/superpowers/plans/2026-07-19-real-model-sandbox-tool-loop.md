# Real Model Sandbox Tool Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Anthropic-backed, provider-neutral coding loop that executes strictly validated tools inside the existing durable sandbox runtime and resumes without duplicating completed mutations.

**Architecture:** Keep provider events, tool policy, sandbox execution, sandbox lifecycle, and durable orchestration in separate focused modules. `AnthropicCodingLoop` advances only one safe point per worker invocation and reuses the existing execution lease, fencing token, tool claim, checkpoint, and event infrastructure.

**Tech Stack:** Python 3.11+, `anthropic==0.102.0`, Pydantic v2, SQLAlchemy async sessions, PostgreSQL SQL migrations, pytest/pytest-asyncio, existing Memory and Docker sandbox providers.

## Global Constraints

- Provider SDK values must not cross the `CodingModel` boundary.
- Canonical recovery state contains completed transcript messages only; streamed deltas are observable events.
- Tool names and JSON schemas are versioned durable contracts.
- Direct argv execution only; reject shell `-c`, network clients, destructive Git commands, publishing, and unknown executables.
- Every tool call is a safe point; never automatically repeat a mutation whose completion cannot be proven.
- The loop advances at most one durable safe point per `advance_one_safe_point()` call.
- Prompts, credentials, unrestricted file content, argv details, and environment values must not enter audit labels or durable event metadata.
- Default CI performs no network calls; real Anthropic tests are explicitly opt-in.

---

## File Map

- `neos/coding/model/base.py`: canonical requests, messages, stream events, usage, limits, and `CodingModel` protocol.
- `neos/coding/model/anthropic.py`: Anthropic SDK streaming normalization and error mapping.
- `neos/coding/tools/registry.py`: stable tool definitions, JSON-schema validation, risk classification, and policy decisions.
- `neos/coding/tools/executor.py`: canonical bounded results and `SandboxSession` dispatch.
- `neos/coding/sandbox/bindings.py`: sandbox binding domain model and lifecycle service.
- `neos/coding/repositories/sandbox_repository.py`: in-memory and PostgreSQL binding repositories.
- `neos/coding/loop/anthropic.py`: one-safe-point durable model/tool orchestration.
- `neos/coding/runtime.py`: real-loop construction and dependency wiring.
- `neos/config/schema.py`, `neos/config/loader.py`, config YAML files, `.env.template`: strict model/tool-loop configuration.
- `db/migrations/041_add_coding_sandbox_bindings.sql`: durable binding table and constraints.
- Corresponding `tests/coding/model`, `tests/coding/tools`, `tests/coding/sandbox`, `tests/coding/loop`, `tests/config`, and vertical-slice tests verify each boundary.

### Task 1: Canonical Coding Model Contract

**Files:**
- Create: `neos/coding/model/__init__.py`
- Create: `neos/coding/model/base.py`
- Create: `tests/coding/model/__init__.py`
- Create: `tests/coding/model/test_base.py`

**Interfaces:**
- Produces: `CodingModel.stream(request: ModelRequest) -> AsyncIterator[ModelEvent]`, `ModelRequest`, `CanonicalMessage`, `TextDelta`, `ToolInputDelta`, `ToolCallCompleted`, `ModelCompleted`, `ModelUsage`, and `ModelLimits`.

- [ ] **Step 1: Write the failing contract tests**

```python
def test_model_request_rejects_incomplete_transcript_messages() -> None:
    with pytest.raises(ValueError, match="completed transcript"):
        ModelRequest(
            system="work safely",
            messages=(CanonicalMessage(role="assistant", content=()),),
            tools=(),
            model="claude-test",
            limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
            task_id="ct_1",
            run_id="cr_1",
            turn_id="turn_1",
        )


def test_tool_call_requires_object_input() -> None:
    with pytest.raises(ValueError, match="tool input must be an object"):
        ToolCallCompleted(tool_call_id="tool_1", name="read_file.v1", input=[])
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `.venv/bin/pytest tests/coding/model/test_base.py -q`

Expected: collection fails with `ModuleNotFoundError: neos.coding.model`.

- [ ] **Step 3: Implement immutable canonical types and protocol**

```python
@dataclass(frozen=True, slots=True)
class ModelLimits:
    max_output_tokens: int
    timeout_sec: float

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1 or self.timeout_sec <= 0:
            raise ValueError("model limits must be positive")


@dataclass(frozen=True, slots=True)
class ToolCallCompleted:
    tool_call_id: str
    name: str
    input: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.input, Mapping):
            raise ValueError("tool input must be an object")


ModelEvent = TextDelta | ToolInputDelta | ToolCallCompleted | ModelCompleted


class CodingModel(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
```

Represent canonical content with explicit `TextContent`, `ToolUseContent`, and `ToolResultContent` dataclasses. Validate that each stored message has at least one completed content block and roles are `user`, `assistant`, or `tool`.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/coding/model/test_base.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the contract**

```bash
git add neos/coding/model tests/coding/model
git commit -m "feat: define coding model contract"
```

### Task 2: Anthropic Streaming Adapter

**Files:**
- Create: `neos/coding/model/anthropic.py`
- Create: `tests/coding/model/test_anthropic.py`
- Modify: `neos/coding/model/__init__.py`

**Interfaces:**
- Consumes: `CodingModel`, `ModelRequest`, and canonical model events from Task 1.
- Produces: `AnthropicCodingModel(client, max_tool_input_bytes=65536, max_tool_input_depth=16)` and stable `CodingModelError(code, retryable)`.

- [ ] **Step 1: Write synthetic stream tests**

```python
@pytest.mark.asyncio
async def test_fragmented_tool_json_becomes_one_completed_call() -> None:
    client = FakeAnthropicClient(events=[
        content_start("toolu_1", "read_file.v1"),
        input_delta('{"path":'),
        input_delta('"README.md"}'),
        content_stop(),
        message_delta(stop_reason="tool_use"),
    ])
    events = [event async for event in AnthropicCodingModel(client).stream(request())]
    assert events[-2] == ToolCallCompleted(
        tool_call_id="toolu_1",
        name="read_file.v1",
        input={"path": "README.md"},
    )
    assert events[-1].stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_oversized_partial_json_fails_before_accumulating_more() -> None:
    model = AnthropicCodingModel(
        FakeAnthropicClient(events=[content_start("t", "read_file.v1"), input_delta("x" * 9)]),
        max_tool_input_bytes=8,
    )
    with pytest.raises(CodingModelError, match="tool_input_too_large"):
        _ = [event async for event in model.stream(request())]
```

Add cases for text deltas, malformed JSON, non-object JSON, nesting overflow, usage mapping, timeout, rate limit, authentication failure, and generic SDK transport failure.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/coding/model/test_anthropic.py -q`

Expected: collection fails because `AnthropicCodingModel` does not exist.

- [ ] **Step 3: Implement provider conversion and sanitized errors**

```python
class AnthropicCodingModel:
    def __init__(self, client: AsyncAnthropic, *, max_tool_input_bytes: int = 65_536, max_tool_input_depth: int = 16) -> None:
        self._client = client
        self._max_tool_input_bytes = max_tool_input_bytes
        self._max_tool_input_depth = max_tool_input_depth

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        payload = _to_anthropic_request(request)
        try:
            async with asyncio.timeout(request.limits.timeout_sec):
                async with self._client.messages.stream(**payload) as stream:
                    async for raw in stream:
                        for event in _normalize(raw, self._max_tool_input_bytes, self._max_tool_input_depth):
                            yield event
        except anthropic.RateLimitError as error:
            raise CodingModelError("model_rate_limited", retryable=True) from error
        except TimeoutError as error:
            raise CodingModelError("model_timeout", retryable=True) from error
```

Keep SDK imports and SDK-shaped fixtures confined to this module and its tests.

- [ ] **Step 4: Run adapter and contract tests**

Run: `.venv/bin/pytest tests/coding/model -q`

Expected: all tests pass without network access.

- [ ] **Step 5: Commit the adapter**

```bash
git add neos/coding/model tests/coding/model
git commit -m "feat: normalize anthropic coding streams"
```

### Task 3: Versioned Tool Registry and Policy

**Files:**
- Create: `neos/coding/tools/__init__.py`
- Create: `neos/coding/tools/registry.py`
- Create: `tests/coding/tools/__init__.py`
- Create: `tests/coding/tools/test_registry.py`

**Interfaces:**
- Produces: `CodingToolRegistry.default(command_allowlist)`, `validate(name, input) -> ValidatedToolCall`, `ToolRisk`, `PolicyDecision`, and provider-neutral tool definitions.

- [ ] **Step 1: Write policy tests for allow, deny, and schema errors**

```python
def test_read_file_is_read_only_and_normalizes_path() -> None:
    call = registry().validate("read_file.v1", {"path": "src/main.py"})
    assert call.risk is ToolRisk.READ_ONLY
    assert call.input == {"path": "src/main.py"}


@pytest.mark.parametrize("argv", [
    ["bash", "-c", "pytest"],
    ["git", "push"],
    ["git", "reset", "--hard"],
    ["curl", "https://example.com"],
    ["npm", "publish"],
])
def test_command_policy_denies_unsafe_argv(argv: list[str]) -> None:
    decision = registry().decide("execute.v1", {"argv": argv})
    assert decision.allowed is False
    assert decision.reason_code.startswith("policy_")
```

Also cover absolute paths, `..`, `.git` writes, NUL bytes, unknown fields, invalid regex/limits, unknown tools, command timeout/output caps, env-name filtering, and allowlisted `pytest`, `ruff`, `mypy`, `pnpm`, and read-only `git` subcommands.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/coding/tools/test_registry.py -q`

Expected: collection fails because the registry module does not exist.

- [ ] **Step 3: Implement closed schemas and fail-closed policy**

```python
class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str


def _decide_execute(data: Mapping[str, object], allowlist: frozenset[str]) -> PolicyDecision:
    argv = tuple(str(value) for value in data["argv"])
    executable = PurePosixPath(argv[0]).name
    if executable not in allowlist:
        return PolicyDecision(False, "policy_executable_not_allowed")
    if executable in {"sh", "bash", "zsh"} and len(argv) > 1 and argv[1] == "-c":
        return PolicyDecision(False, "policy_shell_command_denied")
    if _is_destructive_or_networked(argv):
        return PolicyDecision(False, "policy_operation_denied")
    return PolicyDecision(True, "policy_allowed")
```

Use Pydantic models with `extra="forbid"` to generate stable JSON schemas for `list_tree.v1`, `stat.v1`, `read_file.v1`, `search_text.v1`, `git_status.v1`, `git_diff.v1`, `git_log.v1`, `write_file.v1`, and `execute.v1`.

- [ ] **Step 4: Run registry tests**

Run: `.venv/bin/pytest tests/coding/tools -q`

Expected: all tests pass.

- [ ] **Step 5: Commit registry and policy**

```bash
git add neos/coding/tools tests/coding/tools
git commit -m "feat: add coding tool policy registry"
```

### Task 4: Bounded Sandbox Tool Executor

**Files:**
- Create: `neos/coding/tools/executor.py`
- Create: `tests/coding/tools/test_executor.py`
- Modify: `neos/coding/tools/__init__.py`

**Interfaces:**
- Consumes: `ValidatedToolCall` and existing `SandboxSession` methods.
- Produces: `SandboxToolExecutor.execute(session, call) -> ToolResult`, where `ToolResult.to_mapping()` is safe for durable storage.

- [ ] **Step 1: Write executor boundary tests**

```python
@pytest.mark.asyncio
async def test_read_file_truncates_and_checksums_original_content() -> None:
    executor = SandboxToolExecutor(max_preview_bytes=4, max_entries=10)
    result = await executor.execute(session_with_file(b"abcdef"), read_call("a.txt"))
    assert result.status == "ok"
    assert result.preview == "abcd"
    assert result.original_bytes == 6
    assert result.truncated is True
    assert result.checksum == hashlib.sha256(b"abcdef").hexdigest()


@pytest.mark.asyncio
async def test_execute_never_serializes_environment_values() -> None:
    result = await executor.execute(session(), execute_call(["pytest", "-q"], {"TOKEN": "secret"}))
    assert "secret" not in json.dumps(result.to_mapping())
```

Add dispatch tests for every registered tool, UTF-8 replacement behavior, entry bounds, stdout/stderr bounds, timeout mapping, sandbox policy errors, missing files, and revision propagation.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/coding/tools/test_executor.py -q`

Expected: collection fails because `SandboxToolExecutor` is absent.

- [ ] **Step 3: Implement dispatch and canonical results**

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["ok", "error", "denied"]
    reason_code: str
    preview: str | None
    original_bytes: int | None
    truncated: bool
    checksum: str | None
    workspace_revision: str
    entries: tuple[Mapping[str, object], ...] = ()


async def execute(self, session: SandboxSession, call: ValidatedToolCall) -> ToolResult:
    if call.name == "read_file.v1":
        content = await session.read_file(str(call.input["path"]))
        return self._bounded_bytes(content, workspace_revision=await self._revision(session))
    if call.name == "write_file.v1":
        revision = await session.write_file(str(call.input["path"]), str(call.input["content"]).encode())
        return ToolResult.ok(workspace_revision=str(revision))
    return await self._dispatch_non_file_tool(session, call)
```

Convert `CommandResult` to two separately bounded stdout/stderr fields and include only the executable category in audit data.

- [ ] **Step 4: Run executor and sandbox regressions**

Run: `.venv/bin/pytest tests/coding/tools tests/coding/sandbox/test_memory_workspace.py tests/coding/sandbox/test_process.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit executor**

```bash
git add neos/coding/tools tests/coding/tools
git commit -m "feat: execute bounded coding tools in sandbox"
```

### Task 5: Durable Sandbox Bindings and Recovery

**Files:**
- Create: `db/migrations/041_add_coding_sandbox_bindings.sql`
- Create: `neos/coding/sandbox/bindings.py`
- Create: `neos/coding/repositories/sandbox_repository.py`
- Create: `tests/coding/test_migration_041_contract.py`
- Create: `tests/coding/sandbox/test_bindings.py`
- Create: `tests/coding/repositories/test_sandbox_repository.py`

**Interfaces:**
- Consumes: existing `SandboxProvider`, `SandboxLimits`, `Sandbox`, and `Snapshot`.
- Produces: `SandboxBinding`, `SandboxBindingRepository`, and `SandboxBindingService.resolve(task_id, run_id) -> BoundSandboxSession`.

- [ ] **Step 1: Write migration and lifecycle tests**

```python
def test_migration_creates_unique_task_binding_with_cas_version() -> None:
    sql = Path("db/migrations/041_add_coding_sandbox_bindings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS coding_sandbox_bindings" in sql
    assert "UNIQUE (task_id)" in sql
    assert "version BIGINT NOT NULL" in sql
    assert "latest_snapshot_id" in sql


@pytest.mark.asyncio
async def test_missing_sandbox_restores_latest_snapshot_and_swaps_binding() -> None:
    bound = await service_with_missing_sandbox_and_snapshot().resolve("ct_1", "cr_2")
    assert bound.binding.sandbox_id == "sb_restored"
    assert bound.binding.version == 2
```

Add cases for new creation persisted before session open, healthy reuse, suspended resume, missing-without-snapshot error, image mismatch, CAS conflict cleanup, snapshot cadence, and terminal destruction.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/coding/test_migration_041_contract.py tests/coding/sandbox/test_bindings.py tests/coding/repositories/test_sandbox_repository.py -q`

Expected: tests fail because migration and binding modules do not exist.

- [ ] **Step 3: Add migration and binding model**

```sql
CREATE TABLE IF NOT EXISTS coding_sandbox_bindings (
    task_id VARCHAR(64) PRIMARY KEY REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    sandbox_id VARCHAR(128) NOT NULL UNIQUE,
    provider VARCHAR(32) NOT NULL,
    image_digest VARCHAR(255),
    workspace_revision VARCHAR(128) NOT NULL,
    latest_snapshot_id VARCHAR(128),
    health_state VARCHAR(32) NOT NULL,
    mutation_count INTEGER NOT NULL DEFAULT 0 CHECK (mutation_count >= 0),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id)
);
```

```python
@dataclass(frozen=True, slots=True)
class SandboxBinding:
    task_id: str
    run_id: str
    sandbox_id: str
    provider: str
    image_digest: str | None
    workspace_revision: str
    latest_snapshot_id: str | None
    health_state: str
    mutation_count: int
    version: int
```

- [ ] **Step 4: Implement repository CAS and lifecycle service**

Use `UPDATE ... WHERE task_id = :task_id AND version = :expected_version RETURNING ...` for replacements. On a lost CAS after creating/restoring a sandbox, destroy the unowned sandbox and resolve the winning binding. Raise stable `SandboxBindingError("sandbox_unrecoverable", retryable=True)` if neither sandbox nor snapshot exists.

- [ ] **Step 5: Run binding and provider tests**

Run: `.venv/bin/pytest tests/coding/test_migration_041_contract.py tests/coding/sandbox/test_bindings.py tests/coding/repositories/test_sandbox_repository.py tests/coding/sandbox/test_runtime_ownership.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit durable bindings**

```bash
git add db/migrations/041_add_coding_sandbox_bindings.sql neos/coding/sandbox/bindings.py neos/coding/repositories/sandbox_repository.py tests/coding/test_migration_041_contract.py tests/coding/sandbox/test_bindings.py tests/coding/repositories/test_sandbox_repository.py
git commit -m "feat: persist coding sandbox bindings"
```

### Task 6: One-Safe-Point Anthropic Coding Loop

**Files:**
- Create: `neos/coding/loop/anthropic.py`
- Create: `tests/coding/loop/test_anthropic_loop.py`
- Modify: `neos/coding/loop/__init__.py`
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/domain/durability.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/repositories/test_durability_repository.py`

**Interfaces:**
- Consumes: `CodingModel`, `CodingToolRegistry`, `SandboxToolExecutor`, `SandboxBindingService`, and existing `LoopDependencies` repository lease APIs.
- Produces: `AnthropicCodingLoop.run()` compatible with `CodingRunService.advance_one_safe_point()` and `commit_model_checkpoint()` for fenced checkpoints that intentionally have no sandbox execution claim.

- [ ] **Step 1: Write durable orchestration tests**

```python
@pytest.mark.asyncio
async def test_one_invocation_executes_and_checkpoints_one_tool_call() -> None:
    loop, deps = harness(model_events=[tool_call("toolu_1", "write_file.v1", {"path": "a.txt", "content": "x"})])
    events = [event async for event in loop.run(loop_input(), None, deps)]
    assert sandbox_write_count(deps, "a.txt") == 1
    assert deps.repository.checkpoints[-1].loop_state["pending_tool_index"] == 1
    assert sum(event.type == "tool.completed" for event in events) == 1


@pytest.mark.asyncio
async def test_completed_claim_is_reused_without_reexecuting_mutation() -> None:
    loop, deps = harness_with_completed_claim("toolu_1", result={"status": "ok", "workspace_revision": "2"})
    _ = [event async for event in loop.run(loop_input(), checkpoint_before_tool(), deps)]
    assert sandbox_write_count(deps, "a.txt") == 0
```

Add tests for policy denial checkpointing without claim, BUSY claim, malformed input feedback, text-only completion, multiple tool calls across multiple invocations, transcript digest, transcript compaction, turn/tool/error/token/cost budgets, provider retryable errors, stale fencing, unknown mutation outcome, cancellation, and sanitized emitted deltas.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/coding/loop/test_anthropic_loop.py -q`

Expected: collection fails because `AnthropicCodingLoop` does not exist.

- [ ] **Step 3: Implement checkpoint state and event collection**

```python
@dataclass(frozen=True, slots=True)
class AgentLoopState:
    transcript: tuple[CanonicalMessage, ...]
    turn_count: int
    tool_count: int
    consecutive_tool_errors: int
    pending_tool_calls: tuple[ToolCallCompleted, ...]
    pending_tool_index: int
    transcript_digest: str


async def run(self, input: LoopInput, checkpoint: CodingCheckpoint | None, deps: LoopDependencies) -> AsyncIterator[CodingEvent]:
    lease = deps.lease
    if lease is None:
        raise RuntimeError("real coding loop requires an execution lease")
    state = self._restore(input, checkpoint)
    bound = await self._bindings.resolve(input.task_id, input.run_id)
    if state.has_pending_tool:
        async for event in self._advance_one_tool(input, state, bound, deps):
            yield event
        return
    async for event in self._advance_one_model_turn(input, state, bound, deps):
        yield event
```

- [ ] **Step 4: Add an atomic fenced checkpoint command without a tool claim**

```python
@dataclass(frozen=True, slots=True)
class ModelCheckpointCommit:
    checkpoint: CodingCheckpoint
    event: CodingEvent


class CodingRunRepository(Protocol):
    async def commit_model_checkpoint(
        self,
        *,
        lease: ExecutionLease,
        event_type: str,
        event_payload: Mapping[str, Any],
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        now: datetime,
    ) -> ModelCheckpointCommit: ...
```

Implement it in both repositories as one fenced transaction that locks the run, allocates the next task sequence, inserts the checkpoint, event, and outbox record, and rejects a stale `fencing_token`. Use this path for a completed text-only turn, schema rejection, and policy denial; it must never insert or update `coding_tool_executions`.

- [ ] **Step 5: Implement claim, execute, reuse, and atomic checkpoint flow**

Acquire `claim_tool_execution()` only after schema/policy validation. For a completed claim, reuse its mapping. For a new claim, execute once and call `complete_tool_execution()`. Then call `commit_phase_checkpoint()` with the completed assistant/tool-result transcript and current workspace revision. If execution returned but completion cannot be established, raise `CodingLoopFailure("tool_outcome_unknown", retryable=False)`.

- [ ] **Step 6: Run loop and durability regressions**

Run: `.venv/bin/pytest tests/coding/loop tests/coding/test_durable_phase_vertical_slice.py tests/coding/repositories/test_durability_repository.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit the durable loop**

```bash
git add neos/coding/loop neos/coding/domain/durability.py neos/coding/repositories/run_repository.py tests/coding/loop tests/coding/repositories/test_durability_repository.py
git commit -m "feat: add durable anthropic coding loop"
```

### Task 7: Strict Configuration and Runtime Wiring

**Files:**
- Modify: `neos/config/schema.py`
- Modify: `neos/config/loader.py`
- Modify: `neos/config/settings.py`
- Modify: `neos/coding/runtime.py`
- Modify: `config/neos.default.yaml`
- Modify: `config/neos.development.yaml`
- Modify: `config/neos.staging.yaml`
- Modify: `config/neos.production.yaml`
- Modify: `config/neos.example.yaml`
- Modify: `.env.template`
- Create: `tests/config/test_coding_model_config.py`
- Modify: `tests/api/test_coding_production_registration.py`

**Interfaces:**
- Consumes: all prior constructors.
- Produces: `CodingModelConfig`, fail-closed validation, and runtime selection among disabled, fake, and Anthropic loop modes.

- [ ] **Step 1: Write configuration policy tests**

```python
def test_real_loop_requires_sandbox_and_credential_in_production() -> None:
    with pytest.raises(ValidationError, match="coding real loop requires"):
        AppConfig.model_validate({
            "environment": "production",
            "coding_model": {"enabled": True, "provider": "anthropic", "model": "claude-test"},
            "sandbox": {"enabled": False},
        })


def test_fake_and_real_loop_are_mutually_exclusive(monkeypatch) -> None:
    monkeypatch.setenv("CODING_FAKE_LOOP_ENABLED", "true")
    config = configured_real_loop()
    with pytest.raises(RuntimeError, match="cannot be enabled together"):
        create_development_coding_runtime(config=config)
```

Add positive budget validation, command allowlist validation, cost/transcript caps, command-disabled empty allowlist, secret redaction, staging/production Docker requirement, and fake/Celery/real mode conflicts.

- [ ] **Step 2: Verify failures**

Run: `.venv/bin/pytest tests/config/test_coding_model_config.py tests/api/test_coding_production_registration.py -q`

Expected: tests fail because `coding_model` is not part of `AppConfig`.

- [ ] **Step 3: Add strict nested configuration**

```python
class CodingModelConfig(StrictConfigModel):
    enabled: bool = False
    provider: Literal["anthropic"] = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    model_timeout_sec: float = Field(default=120, gt=0, le=600)
    tool_timeout_sec: float = Field(default=30, gt=0, le=300)
    max_turns: int = Field(default=20, gt=0, le=100)
    max_tool_calls: int = Field(default=50, gt=0, le=500)
    max_consecutive_tool_errors: int = Field(default=3, gt=0, le=20)
    max_output_tokens: int = Field(default=8192, gt=0)
    max_transcript_bytes: int = Field(default=1_048_576, gt=0)
    max_cost_usd: float = Field(default=5.0, gt=0)
    command_enabled: bool = True
    command_allowlist: list[str] = Field(default_factory=lambda: ["pytest", "ruff", "mypy", "pnpm", "git"])
    mutation_snapshot_interval: int = Field(default=5, gt=0)
```

Add `coding_model: CodingModelConfig` to `AppConfig`, map only the existing `ANTHROPIC_API_KEY` secret boundary, and document safe defaults in every YAML variant.

- [ ] **Step 4: Wire runtime ownership**

Construct the sandbox provider once, create `PostgresSandboxBindingRepository`, `SandboxBindingService`, registry, executor, `AsyncAnthropic(api_key=settings.config.secrets.anthropic_api_key)`, adapter, and loop. Pass the same provider to `CodingRuntime`; close it only through `CodingRuntime.close()`.

- [ ] **Step 5: Run configuration and runtime tests**

Run: `.venv/bin/pytest tests/config/test_coding_model_config.py tests/config/test_sandbox_config.py tests/config/test_startup_config.py tests/api/test_coding_production_registration.py tests/coding/sandbox/test_runtime_ownership.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit configuration and wiring**

```bash
git add neos/config neos/coding/runtime.py config .env.template tests/config/test_coding_model_config.py tests/api/test_coding_production_registration.py
git commit -m "feat: wire real coding model runtime"
```

### Task 8: Observability, Crash Recovery Vertical Slice, and Documentation

**Files:**
- Modify: `neos/observability/metrics.py`
- Modify: `neos/coding/sandbox/observability.py`
- Create: `tests/coding/test_real_model_tool_loop_vertical_slice.py`
- Create: `tests/coding/test_real_model_tool_loop_crash_recovery.py`
- Create: `tests/coding/integration/test_anthropic_opt_in.py`
- Modify: `tests/coding/fakes.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: fully wired real loop.
- Produces: bounded metrics/audit signals, deterministic Memory sandbox E2E coverage, crash-injection proof, and opt-in network smoke test.

- [ ] **Step 1: Write the Memory sandbox vertical slice**

```python
@pytest.mark.asyncio
async def test_model_reads_edits_tests_and_finishes_across_safe_points() -> None:
    harness = real_loop_harness(script=[
        tool_turn("read_file.v1", {"path": "calc.py"}),
        tool_turn("write_file.v1", {"path": "calc.py", "content": "def add(a, b): return a + b\n"}),
        tool_turn("execute.v1", {"argv": ["pytest", "-q"]}),
        text_turn("Implemented and verified add()."),
    ])
    await harness.advance_until_complete()
    assert await harness.session.read_file("calc.py") == b"def add(a, b): return a + b\n"
    assert harness.completed_tool_ids == {"tool_1", "tool_2", "tool_3"}
    assert harness.final_text == "Implemented and verified add()."
```

- [ ] **Step 2: Write crash and fencing tests**

Inject failure immediately after `write_file()` and immediately after `complete_tool_execution()`. Prove the former yields `tool_outcome_unknown` without a second write and the latter reuses the stored result after worker replacement. Assert an old fencing token cannot commit tool results, checkpoints, or binding changes.

- [ ] **Step 3: Add bounded metrics and audit assertions**

```python
assert metrics.records == [
    ("coding_model_turn_total", {"provider": "anthropic", "outcome": "tool_use"}),
    ("coding_tool_execution_total", {"tool": "write_file.v1", "outcome": "ok"}),
]
serialized = json.dumps(audit.events)
assert "secret" not in serialized
assert "file contents" not in serialized
```

Use only fixed-cardinality provider, model category, registered tool name, operation, outcome, and stable error-code labels.

- [ ] **Step 4: Add opt-in Anthropic smoke test**

Guard it with both `NEOS_RUN_ANTHROPIC_INTEGRATION=1` and `ANTHROPIC_API_KEY`. Give it a one-turn, low-token request with no mutation and skip otherwise. Never run it in default CI.

- [ ] **Step 5: Update operational documentation**

Document configuration, safe command policy, Docker network isolation, one-safe-point scheduling, snapshot/recovery behavior, `tool_outcome_unknown` operator response, opt-in test invocation, metric names, and rollback to the fake loop in `docs/NEOS_CODING.md`.

- [ ] **Step 6: Run the complete scoped verification**

Run: `.venv/bin/pytest tests/coding tests/config/test_coding_model_config.py tests/config/test_sandbox_config.py tests/config/test_startup_config.py tests/api/test_coding_production_registration.py -q`

Expected: all scoped tests pass; Docker-dependent tests may skip only when Docker is unavailable and must state the skip reason.

Run: `.venv/bin/ruff check neos/coding neos/config tests/coding tests/config/test_coding_model_config.py`

Expected: no lint errors.

- [ ] **Step 7: Commit the verified vertical slice**

```bash
git add neos/observability/metrics.py neos/coding/sandbox/observability.py tests/coding docs/NEOS_CODING.md
git commit -m "test: verify real coding tool loop recovery"
```

## Final Review Gate

- [ ] Compare every section of `docs/superpowers/specs/2026-07-19-real-model-sandbox-tool-loop-design.md` with Tasks 1-8 and record any deliberate deferral in `docs/NEOS_CODING.md`.
- [ ] Run `git diff --check` and verify no credentials, generated sandbox workspaces, recordings containing prompts, or oversized tool outputs are tracked.
- [ ] Run the scoped verification command from Task 8 once more from a clean process.
- [ ] Review the commits in order and confirm each can be reverted without invalidating an earlier migration or contract.
