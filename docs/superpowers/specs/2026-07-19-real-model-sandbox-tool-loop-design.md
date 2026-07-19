# Real Model Sandbox Tool Loop Design

> Date: 2026-07-19
> Status: Approved design
> Scope: Anthropic-first provider-neutral coding model loop connected to the existing durable run and sandbox foundations

## 1. Objective

Replace the development-only fake coding loop with an optional real model loop that can inspect and modify an isolated workspace, execute a constrained set of development commands, survive worker restarts without repeating completed mutations, and emit the existing durable coding events.

This slice delivers:

- a provider-neutral `CodingModel` contract;
- an Anthropic streaming adapter;
- a stable coding tool registry with strict input schemas;
- a sandbox-backed executor for file, search, Git inspection, and bounded commands;
- durable tool claim, result reuse, and checkpoint integration;
- bounded canonical transcript and tool result artifacts;
- configuration and runtime selection between fake and Anthropic loops.

It does not deliver user approval UI, arbitrary network access, package publishing, Git push, or frontend workspace REST/WebSocket APIs.

## 2. Architectural Boundaries

```text
AnthropicCodingLoop
  ├─ CodingModel
  │    └─ AnthropicCodingModel
  ├─ CodingToolRegistry
  │    └─ schemas + risk classification + validation
  ├─ SandboxToolExecutor
  │    └─ SandboxSession file/search/git/command methods
  ├─ SandboxBindingService
  │    └─ task/run to sandbox lifecycle and recovery
  └─ CodingRunRepository
       ├─ execution lease and fencing
       ├─ durable tool claim/result reuse
       └─ atomic phase/checkpoint commit
```

`AnthropicCodingLoop` owns orchestration only. It does not import Anthropic SDK response types, Docker commands, or provider-specific sandbox classes. `AnthropicCodingModel` converts SDK events into canonical model events. `SandboxToolExecutor` receives only a provider-neutral `SandboxSession`.

The existing fake loop remains a deterministic test and development option. Real behavior is a separate implementation rather than conditional branches inside `FakeDurableCodingLoop`.

The worker-facing loop entry point advances at most one durable safe point per invocation. It returns control after a completed model turn with no tools, or after one tool call has produced a durable result and checkpoint. This keeps lease renewal, cancellation, and retry scheduling under the existing worker/runtime owner instead of hiding an unbounded agent loop inside one job.

## 3. Canonical Model Contract

The model adapter accepts a request containing:

- system instructions;
- completed canonical transcript messages;
- stable tool definitions;
- model, token, and timeout limits;
- task/run/turn identifiers for tracing only.

It yields provider-neutral events:

- `TextDelta(text)`;
- `ToolInputDelta(tool_call_id, name, partial_json)`;
- `ToolCallCompleted(tool_call_id, name, input)`;
- `ModelCompleted(stop_reason, usage)`.

Provider SDK objects never cross this boundary. The Anthropic adapter accumulates partial tool JSON with explicit byte and nesting limits and emits `ToolCallCompleted` only after the SDK reports a complete block and the JSON parses to an object.

Canonical transcript storage contains only completed `user`, `assistant`, and `tool_result` messages. Streaming deltas are observable UI events, not recovery state. A crash during a partial assistant response restarts that model turn from the preceding completed checkpoint.

## 4. Tool Registry and Initial Policy

Every tool has a stable name, versioned JSON schema, risk class, result serializer, and execution handler.

Automatically allowed read-only tools:

- `list_tree`
- `stat`
- `read_file`
- `search_text`
- `git_status`
- `git_diff`
- `git_log`

Conditionally allowed mutation:

- `write_file`, restricted to validated workspace paths and protected Git path rules.

Conditionally allowed commands:

- direct argv only;
- executable must appear in a server-side allowlist;
- command timeout, stdin, and output limits cannot exceed sandbox limits;
- shell `-c`, Git push/reset/clean, package publish, network clients, and unknown executables are denied;
- environment names must be allowlisted and values are never logged.

The initial executable allowlist is configuration-owned and intended for test, build, lint, formatter, compiler, and read-only Git commands. Repository content cannot extend it. Approval-required and bypass states are reserved for the next permission slice; this slice returns a deterministic `policy_denied` tool result instead of waiting for approval.

## 5. Durable Execution Flow

1. Acquire the existing run execution lease and fencing token.
2. Resolve the task's sandbox binding. Reuse a healthy sandbox or restore the latest compatible snapshot; otherwise create one.
3. Restore the last completed canonical transcript and checkpoint loop state.
4. Send one model request and persist normalized text/tool observation events.
5. Validate each completed tool call against the registry schema and policy before sandbox access.
6. Claim `(task_id, tool_call_id)` through the existing durable repository.
7. If the call is already complete, load its stored normalized result without executing it again.
8. If newly claimed, execute it through `SandboxToolExecutor` and commit its normalized result using the current fencing token.
9. Atomically checkpoint the completed assistant message, tool results, workspace revision, loop counters, and transcript digest.
10. Continue with the next model turn until no tool call remains or a configured budget is reached.

Each completed tool call is a safe point. A worker crash after sandbox mutation but before durable completion is handled by the existing claim state and recovery policy: the replacement worker does not blindly rerun a claimed mutation. It reconciles the claim, workspace revision, and stored result. If completion cannot be proven, the run fails with `tool_outcome_unknown` rather than risking duplicate mutation.

Schema or policy rejections never acquire a sandbox execution claim because no sandbox operation occurs. Their normalized result and the corresponding completed assistant tool request are nevertheless committed in the next checkpoint, so recovery feeds the same deterministic rejection back to the model instead of requesting the turn again.

## 6. Sandbox Binding and Recovery

A binding records the task/run association with `sandbox_id`, provider, image digest, workspace revision, latest snapshot ID, and health state. The binding is repository-backed in production and in-memory in focused tests. This slice includes the database migration, repository methods, uniqueness constraints, and compare-and-swap update required to make the production binding durable; it is not stored only in process memory or event metadata.

- New run: create a sandbox from configured `SandboxLimits` and persist the binding before the first model call.
- Normal resume: retrieve the provider sandbox and verify it is running or resumable.
- Missing sandbox with snapshot: restore the snapshot, atomically replace the binding, and continue.
- Missing sandbox without snapshot: record a retryable `sandbox_unrecoverable` failure.
- Terminal task: destroy the sandbox through runtime ownership policy.

Snapshot cadence is safe-point based: after a configured number of successful mutations and before suspension. Read-only calls do not trigger snapshots.

## 7. Result and Transcript Bounds

Tool execution produces a canonical result containing:

- `status`: `ok`, `error`, or `denied`;
- structured reason/error code;
- bounded UTF-8 preview or structured entries;
- original byte or entry count;
- truncation flag;
- SHA-256 checksum when content is truncated or artifactized;
- workspace revision after the operation;
- optional artifact reference.

Raw command environment values, credentials, full oversized stdout/stderr, and unrestricted file contents are not stored in event metadata. The transcript has per-result, per-turn, and total byte limits. When the total limit is reached, older tool payloads become compact artifact references while user instructions, assistant decisions, and tool outcome metadata remain.

## 8. Errors and Retry Semantics

- Model timeout, rate limit, and transient provider failure: do not advance the checkpoint; record a sanitized retryable phase failure.
- Malformed tool JSON or schema violation: do not access the sandbox; return a structured tool error to the next model turn.
- Policy violation: emit `denied` with a stable reason code; do not create a durable execution claim for a sandbox mutation.
- Sandbox timeout: terminate the bounded process group and store only bounded output metadata.
- Output overflow: preserve preview, original size, truncation, and checksum.
- Worker crash: fencing rejects stale commits; completed tool results are reused.
- Unknown mutation outcome: stop with `tool_outcome_unknown`; never retry automatically.
- Model/tool loop exhaustion: complete with a structured budget failure rather than continuing indefinitely.

Limits cover model turns, tool calls, consecutive tool errors, wall-clock duration, input/output tokens, transcript bytes, and estimated model cost.

## 9. Configuration

Add a strict nested coding model section with:

- real loop enabled flag;
- provider fixed to `anthropic` for this slice;
- model name;
- model and tool timeouts;
- maximum turns/tool calls/errors;
- token, transcript byte, and cost caps;
- command executable allowlist;
- mutation snapshot interval.

Production rejects an enabled real loop without an Anthropic credential reference, positive budgets, enabled sandbox configuration, and at least one safe executable when command execution is enabled. The reference resolves through the application's existing secret/configuration boundary at adapter construction time; credentials are never placed in run records, checkpoints, events, tool environments, or sandbox configuration. Fake and Celery loop mode conflicts remain fail-closed.

Tool names and schema versions are part of the durable transcript contract. A deployed version must continue decoding tool calls already present in resumable runs; incompatible registry changes require an explicit migration or a new tool version rather than silently changing an existing schema.

## 10. Observability and Audit

Reuse existing bounded-label metrics and add model turn, tool policy, tool execution, result truncation, snapshot, and resume outcomes. Labels are limited to provider, model category, tool name from the fixed registry, operation, outcome, and stable error code.

Audit records IDs, tool name, risk class, policy decision, byte counts, workspace revision, and outcome. It excludes prompt text, file content, argv beyond executable category, and environment values.

## 11. Verification Strategy

1. Unit-test Anthropic stream normalization using recorded synthetic SDK event shapes, including fragmented JSON and malformed completion.
2. Unit-test every tool schema, policy denial, executable allowlist, path validation, and result bound.
3. Run an end-to-end Memory sandbox loop that reads, edits, executes an allowlisted test, and returns a final response.
4. Inject a crash immediately after tool execution and prove resume does not repeat the write or command.
5. Verify stale fencing tokens cannot commit results or checkpoints.
6. Verify model timeout/rate limit and sandbox timeout map to stable retry/error codes without secret leakage.
7. Keep the fake loop, existing coding vertical slices, sandbox conformance, and general configuration regressions green.

Real Anthropic network tests are opt-in and require an explicit environment flag and test credential. Default CI uses deterministic fake model streams and performs no network calls.

## 12. Delivery Sequence

1. Canonical model events and `CodingModel` protocol.
2. Anthropic stream adapter and normalization tests.
3. Versioned tool registry and policy engine.
4. Sandbox executor and bounded result artifacts.
5. Sandbox binding lifecycle and snapshot recovery.
6. Durable `AnthropicCodingLoop` orchestration.
7. Runtime/config selection, metrics, and audit wiring.
8. Memory vertical slice, crash-resume tests, opt-in Anthropic test, and documentation.

Each step is independently testable and committed only after focused regression verification.
