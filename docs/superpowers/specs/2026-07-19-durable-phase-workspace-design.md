# Durable Phase Workspace Design

**Date:** 2026-07-19  
**Status:** Approved  
**Scope:** Coding Agent workspace UX and durable long-running agent behavior

## 1. Goal

Evolve the NEOS Coding Agent into a long-running autonomous workspace that users
can understand, reconnect to, and steer. The primary UI is a phase-oriented work
timeline with conversational explanations. The agent runs autonomously by
default and asks only for materially risky operations.

The first complete vertical slice must let a task progress through Understand,
Plan, Implement, Verify, and Review; restore the same phase and tool state after
a browser reconnect; and apply both immediate and safe-point steering at an
explicit checkpoint boundary.

## 2. Product Decisions

- The main UI is phase-oriented rather than IDE-oriented.
- Conversation remains part of the canonical timeline, but phase progress is the
  dominant information hierarchy.
- The default autonomy policy automatically permits ordinary workspace reads,
  edits, and verification commands.
- Risky actions use normalized intent-based approval, not tool-name approval.
- The composer exposes two steering modes:
  - **After current step:** finish the current tool batch, checkpoint, then apply.
  - **Interrupt now:** abort active work, reconcile the workspace, checkpoint,
    and resume in a new run.
- Development proceeds through vertical slices sharing one canonical event
  contract. Frontend UX and durable backend behavior must not evolve as separate
  protocols.

## 3. System Architecture

The existing durable delivery path remains authoritative:

```text
coding_tasks → coding_events/outbox → Redis Pub/Sub → WebSocket replay/live tail
```

The following components extend that path:

```text
User instruction
      ↓
Coding Run Coordinator
      ↓
Durable Coding Loop ───────── Checkpoint Store
      ↓                              ↑
Policy Engine                pause / resume / steer
      ↓
Sandbox Tool Runtime
      ↓
Canonical Coding Events
      ↓
PostgreSQL + Outbox → Redis → Browser Projection Store
                                  ↓
                     Phase Timeline / Diff / Terminal
```

### 3.1 Component boundaries

- **Run Coordinator:** creates runs, owns leases, and manages pause, resume,
  cancel, and steering transitions.
- **Durable Coding Loop:** performs model turns and tool-use iteration. It does
  not own transport or browser state.
- **Policy Engine:** normalizes and classifies the concrete execution intent as
  allow, ask, or deny.
- **Sandbox Tool Runtime:** provides file, search, Git, process, and terminal
  execution behind a provider-neutral interface.
- **Checkpoint Store:** persists loop transcript, workspace identity, resource
  usage, pending controls, and tool idempotency state.
- **Event Projector:** reduces canonical events into browser timeline, workspace,
  approval, and terminal projections.

### 3.2 Identity hierarchy

One task may have multiple runs due to steering, retries, or crash recovery.

```text
task_id → run_id → turn_id → tool_call_id
                     ↓
               checkpoint_id
```

Every event includes all applicable identifiers. A new run never resets the
task-level event sequence.

## 4. Canonical Events and Projection

The common event envelope is:

```json
{
  "v": 1,
  "task_id": "ct_...",
  "run_id": "cr_...",
  "turn_id": "turn_...",
  "tool_call_id": "tool_...",
  "seq": 142,
  "type": "tool.running",
  "ts": "2026-07-19T00:00:00Z",
  "payload": {}
}
```

Event families:

| Family | Events | Primary projection |
|---|---|---|
| Run | `run.started`, `run.paused`, `run.resumed`, `run.completed`, `run.failed` | Phase header and task status |
| Agent | `turn.started`, `text.delta`, `reasoning.summary`, `plan.updated` | Explanations, plan, todo |
| Tool | `tool.preparing`, `tool.running`, `tool.completed`, `tool.failed` | Tool cards and progress |
| Workspace | `file.changed`, `git.diff.updated`, `workspace.invalidated` | File tree, diff, Git state |
| Control | `approval.requested`, `approval.resolved`, `checkpoint.created`, `steer.queued`, `context.compacted`, `recovery.required` | Approval and recovery cards |

The browser maintains a task-scoped external projection store instead of
appending every delta to React component state:

```text
Timeline: phases, messages, plans, tools, approvals, checkpoints
Workspace: revision, tree, open file, diffs, Git state
Terminals: bounded ring buffer per terminal_id
```

Text and terminal deltas are coalesced every 16–50 ms or by size. Full terminal
output stays outside the conversation projection; the timeline stores a bounded
preview and a reference to the terminal buffer.

### 4.1 Reconnect and full resync

1. Fetch a REST snapshot containing phases, messages, tool states, approvals,
   todos, workspace revision, and `head_seq`.
2. Connect with `after_seq=head_seq` and replay later events.
3. Apply live events only after `caught_up`.
4. On a sequence gap, reconnect and retry durable replay.
5. On `resync_required`, clear the local projection, fetch a new full snapshot,
   and reconnect from that snapshot cursor.

The current terminal handling of `resync_required` is replaced only after this
full snapshot path exists.

## 5. Phase-Oriented Workspace UX

The main timeline uses five phases:

1. **Understand:** repository exploration, reproduction, and constraints.
2. **Plan:** execution plan, expected files, and verification strategy.
3. **Implement:** edits, commands, and tool execution.
4. **Verify:** tests, lint, type checking, and inline review.
5. **Review:** final diff, risks, evidence, and completion summary.

Each phase is `pending`, `active`, `completed`, `blocked`, or `failed`. If work
returns to an earlier kind of activity, the system appends another attempt such
as `Understand #2`; it does not rewrite history.

### 5.1 Timeline behavior

- Collapsed phases show outcome, duration, file changes, and verification count.
- The active phase expands its current tool and progress automatically.
- Failures, approvals, recovery, and steering entries expand automatically.
- Agent explanations appear between phase and tool events.
- Every tool call remains inspectable even when collapsed by default.

### 5.2 Contextual detail panel

- File or edit selection opens the diff viewer.
- Command selection opens terminal output.
- Plan selection opens todo state and dependencies.
- Checkpoint selection shows run, context, and workspace revision metadata.
- With no selection, the panel shows Git state, sandbox state, and resource use.

### 5.3 Composer and controls

- Normal submission defaults to **After current step** steering.
- **Interrupt now** is a distinct action with stronger visual weight and a
  confirmation when a non-interruptible operation is active.
- **Stop** transitions the task to a stopped terminal state.
- Instructions entered during approval wait are stored as pending steering and
  never interpreted as an approval decision.

### 5.4 Connection truthfulness

The UI distinguishes live state from checkpoint state. After reconnect, it shows
the restored checkpoint immediately while separately indicating whether the
live stream has caught up.

## 6. Durable Loop and Checkpoints

The loop is a resumable turn state machine:

```text
load checkpoint
  → assemble context
  → call model stream
  → collect tool calls
  → evaluate policy
  → execute tool batch
  → persist results
  → checkpoint
  → next turn or finish
```

Every checkpoint stores:

- canonical transcript and compact summary;
- last applied event sequence;
- phase, plan, and todo state;
- completed tool call IDs and result references;
- workspace revision, Git HEAD, and patch or snapshot reference;
- cumulative tokens, cost, and elapsed time;
- pending approval and steering instruction;
- loop stop or resume reason.

Checkpoints are mandatory after each model turn, before and after write or shell
tools, before approval wait, and after pause, interruption, compaction, or crash
recovery.

`tool_call_id` is the execution idempotency key. A recovered worker must return a
persisted result instead of rerunning a completed tool. If completion of a
non-idempotent tool is uncertain, the task enters `recovery_required` rather
than executing it automatically.

## 7. Steering Semantics

### 7.1 After current step

The coordinator records the instruction as pending, lets the active tool batch
finish, writes a checkpoint, and inserts the instruction as the next user turn.
This is the default because it preserves workspace consistency.

### 7.2 Interrupt now

1. Abort the active model stream.
2. Send `SIGINT` to the active process group.
3. Escalate to `SIGTERM` and `SIGKILL` after configured deadlines.
4. Re-read filesystem and Git state.
5. Write an interruption checkpoint.
6. Start a new run with the instruction and interruption result in context.

File writes use atomic temporary-file replacement. If a patch operation is
interrupted, file hashes and Git diff are recalculated before the next run.

If a process cannot be terminated, the sandbox is quarantined and a replacement
sandbox is restored. Two sandboxes must never retain write authority for the
same task workspace.

## 8. Autonomy and Approval Policy

Policy evaluates normalized execution intent:

```text
schema validation
  → path, command, and network normalization
  → repository policy
  → deterministic risk classification
  → allow / ask / deny
```

### 8.1 Automatically allowed

- workspace file reads, searches, creation, and edits;
- `git status`, `git diff`, and `git log`;
- ordinary lint and test commands that do not mutate dependency state;
- sandbox-localhost access;
- stdout reads and termination of an already-approved process.

### 8.2 Approval required

- deletes or large renames;
- dependency installation and lockfile mutation;
- database migration execution;
- external network access;
- credential use;
- access outside the workspace mount;
- Git commit, remote fetch, and push;
- resource-limit increases and long-lived processes;
- commands whose normalized effect cannot be classified.

### 8.3 Always denied

- sandbox escape and host device or socket access;
- secret plaintext output;
- unauthorized privileged containers;
- protected-branch force push;
- encoded or indirect policy bypass attempts.

Approval cards show the agent rationale, normalized command, working directory,
read/write paths, network destination, credential scope, and estimated impact.
An approval is bound to the normalized request hash and a scope of once, current
run, or current task. AI risk classification may request more caution but can
never override a deterministic deny rule.

## 9. Failure and Recovery

| Failure | Required behavior |
|---|---|
| Model transient error | Retry the current turn within budget, then resume from checkpoint |
| Context overflow | Trim tool results, compact transcript, and emit `context.compacted` |
| Sandbox disconnect | Verify lease, reconnect, or restore Git HEAD plus patch bundle |
| Worker crash | Acquire expired lease and resume latest checkpoint |
| Terminal command failure | Return a tool error to the loop without failing the whole task |
| Event gap | Replay from durable storage or request a full REST snapshot |
| Uncertain non-idempotent tool | Enter `recovery_required` and ask the user |

Recovery must expose its current state in the phase timeline. Silent retry loops
are not permitted.

## 10. Observability and Privacy

Traces connect `task_id`, `run_id`, `turn_id`, `tool_call_id`, `checkpoint_id`,
and `sandbox_id`.

Required metrics include phase latency, time to first useful change, tool
allow/ask/deny rate, checkpoint and resume success, steering latency, sandbox
provision and reconnect latency, compaction count, approval latency, and final
verification success.

Prompts, secrets, access tokens, and full terminal output are excluded from
default trace attributes and application logs.

## 11. Testing

- **Loop unit:** no-tool completion, multi-turn tools, errors, budgets, compact.
- **Checkpoint:** recovery around write and shell boundaries; no duplicate tools.
- **Steering:** safe-point insertion, immediate abort, process escalation.
- **Permission:** traversal, symlink, substitution, network, approval hash.
- **Projection:** snapshot plus replay converges with uninterrupted live state.
- **Fault injection:** worker crash, Redis loss, sandbox restore, duplicate/gap.
- **Playwright:** phases, diff, terminal, approval, reconnect, both steer modes.
- **Provider conformance:** Docker and managed adapters satisfy one sandbox suite.

## 12. Delivery Sequence

1. Extend canonical run, phase, checkpoint, and control events.
2. Add full REST snapshot and frontend external projection store.
3. Build the phase timeline shell and contextual detail panel.
4. Validate pause, resume, and steering with a durable fake loop.
5. Connect the provider-neutral model tool loop.
6. Add checkpoint writer and task leases.
7. Connect the sandbox tool runtime.
8. Add permission and approval execution gates.
9. Add context compaction and budgets.
10. Add fault injection, metrics, and performance optimization.

Each item is delivered as a vertical slice across durable state, events, replay,
and frontend projection. No slice may introduce a second source of task truth.

## 13. Explicit Non-Goals

- Multi-agent coordination and multiple concurrent write agents.
- A full browser IDE with direct collaborative editing.
- Production bypass mode for permission checks.
- Automatic rerun of uncertain non-idempotent operations.
- Provider-specific UI or event contracts.

