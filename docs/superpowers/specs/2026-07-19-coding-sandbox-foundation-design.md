# Coding Sandbox Foundation Design

**Date:** 2026-07-19

**Status:** Approved

**Scope:** Coding-agent sandbox foundation only

## 1. Purpose

NEOS needs an isolated code workspace that can safely execute coding-agent tools and remain usable across browser disconnects and worker restarts. This design defines that foundation before adding the real model tool loop and the browser REST/WebSocket gateway.

The foundation provides:

- a provider-independent sandbox contract;
- a deterministic in-process provider for development and conformance tests;
- a Docker CLI provider for local and development environments;
- bounded file, search, Git, and command operations;
- sandbox snapshot, suspend, resume, restore, and destroy lifecycle operations;
- reconnectable PTY and filesystem-watch streams;
- security, recovery, observability, and conformance requirements.

The model loop and browser gateway must depend only on the contracts defined here. Docker-specific behavior must not leak into those layers.

## 2. Architectural boundaries

Add the following package:

```text
neos/coding/sandbox/
  base.py          # Provider, session, and stream protocols and domain types
  memory.py        # Deterministic full-conformance provider
  docker.py        # Development Docker CLI provider
  command.py       # Injectable subprocess command runner
  paths.py         # Workspace path validation and normalization
  archive.py       # Snapshot manifest and archive validation
  streams.py       # PTY/watch cursors and bounded replay buffers
```

The principal interfaces are:

```text
SandboxProvider
  create
  get
  suspend
  resume
  snapshot
  restore
  destroy
  open_session

SandboxSession
  list_tree / stat / read_file / write_file
  search_text
  git_status / git_diff / git_log
  execute
  create_pty / write_pty / resize_pty / kill_pty
  watch_files
```

The provider owns isolation, resource allocation, lifecycle, and recovery. A session owns operations inside one workspace. Stream abstractions own cursor allocation, bounded replay, and disconnect recovery.

The future consumers are deliberately symmetrical:

```text
Model tool loop ─┐
                 ├─ SandboxProvider / SandboxSession
Browser REST/WS ─┘
```

Neither consumer may invoke Docker, access a host workspace directly, or bypass path and execution policy.

## 3. Domain model and lifecycle

Sandbox lifecycle states are:

```text
CREATING ──▶ RUNNING ──▶ SUSPENDED
                ▲             │
                └─────────────┘

CREATING / RUNNING / SUSPENDED ──▶ DESTROYED
```

`destroy` is idempotent. Operations against `SUSPENDED` are rejected except for lifecycle and metadata operations. A failed create never exposes a partially usable sandbox.

Snapshots may be created from `RUNNING` or `SUSPENDED`. Restoring a snapshot always creates a new `RUNNING` sandbox; it never mutates or resurrects the source sandbox.

Each sandbox exposes at least:

- sandbox and owner identifiers;
- current lifecycle state;
- creation, update, idle-expiry, and maximum-lifetime timestamps;
- provider and immutable base-image identity;
- workspace revision;
- declared capacity and resource limits;
- health and last failure metadata.

Provider implementations must enforce lifecycle transitions atomically and return a state conflict when concurrent operations lose the transition race.

## 4. Provider behavior

### 4.1 Memory provider

`MemorySandboxProvider` is a real reference implementation, not a mock. It uses isolated temporary workspaces and implements the entire provider contract, including lifecycle rules, snapshots, asynchronous PTYs, watcher events, cursors, and replay gaps.

It is the default provider for unit and integration tests, so higher layers remain testable when Docker is unavailable. Its externally observable behavior must match the Docker provider except where provider capability metadata explicitly differs.

Commands run as child processes with the same argument, environment, timeout, output, and process-group policies as the Docker provider. Suspend blocks all session operations even though the underlying temporary directory still exists.

### 4.2 Docker provider

`DockerSandboxProvider` uses the standard-library subprocess API through an injected `DockerCommandRunner`. No Docker SDK is introduced in this phase. The runner is the only module allowed to construct and execute Docker CLI invocations, making command construction unit-testable without Docker.

A container becomes `RUNNING` only after creation, startup, and its readiness probe all succeed. Docker labels record the sandbox ID, owner, creation time, expiry, and schema version. On application restart, the provider can rediscover owned containers from those labels. An orphan sweeper removes expired labeled containers and incomplete temporary snapshot resources.

Workspace operations run through a constrained helper or bounded `docker exec`; PTYs use a separate interactive execution path. The provider never accepts arbitrary host mount paths.

Actual Docker conformance tests are opt-in locally and must emit an explicit skip reason if Docker is absent. They should become a required isolated CI job when Docker infrastructure is available.

## 5. Workspace tools

All workspace paths pass through one validation pipeline:

1. reject NUL bytes and absolute paths;
2. normalize using POSIX workspace semantics;
3. reject parent traversal;
4. resolve every existing symlink component;
5. verify the final real path remains under `/workspace`;
6. apply operation-specific protected-path policy.

The policy rejects host or container paths such as `/etc/passwd`, traversal such as `../../secret`, symlinks escaping the workspace, credential/helper mutation under `.git`, and unsafe archive entries.

File operations are size bounded and return explicit metadata, including the resulting workspace revision. Search supports literal and regular-expression modes, glob/path filters, result limits, and output-size limits. Git operations are read-only in this foundation: status, diff, and bounded log inspection.

Command execution accepts an argument tuple rather than a shell string. It uses a validated workspace-relative current directory, an environment allowlist, bounded stdin and output, and a mandatory timeout. Timeout kills the complete process group. Results distinguish a normal non-zero exit, timeout, policy rejection, and provider transport failure; stdout and stderr report truncation independently.

## 6. Isolation policy

Docker sandboxes use the following mandatory baseline:

- non-root runtime user;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- read-only root filesystem;
- writable, size-bounded workspace and temporary filesystem only;
- CPU, memory, PID, and workspace limits;
- network disabled by default;
- no host PID or IPC namespace;
- no privileged mode or Docker socket;
- no arbitrary host mounts;
- image pinned by immutable digest outside explicitly marked local development;
- creation, execution, idle, and absolute-lifetime timeouts.

Network enablement is a future policy capability, not an option silently inherited from Docker defaults. Production configuration validation fails closed when image identity, network policy, or required resource limits are missing.

Audit records must never persist file contents, command output, environment values, or full credentials. They contain structured operation type, identifiers, duration, outcome, limit/truncation metadata, and policy-rejection reason.

## 7. Snapshots

A snapshot is a portable workspace artifact, not a captured running container image:

```text
Snapshot
├── manifest.json
│   ├── schema_version
│   ├── source_sandbox_id
│   ├── workspace_revision
│   ├── created_at
│   ├── base_image_digest
│   └── content_checksum
└── workspace.tar
```

Snapshot creation briefly prevents new writes while it establishes a consistent revision. It excludes secrets, sockets, devices, caches, and temporary credentials. Archive validation checks each entry's normalized path, type, link target, and size, plus total compressed and expanded size. Restore rejects incompatible manifests or base images and removes the new sandbox completely if checksum verification or extraction fails.

The initial snapshot-store port uses local filesystem storage. Its contract must permit a later S3-compatible implementation without changing sandbox consumers.

`suspend` preserves provider runtime metadata and stops execution for short-lived resource recovery. `snapshot` produces a durable, independently restorable artifact. PTY processes and watcher queues are runtime state and are not included in snapshots.

## 8. PTY streaming

A PTY is an independent session whose lifetime is not tied to one WebSocket connection:

```text
Client input ──▶ PTY session ──▶ sandbox process
Client WS ◀── cursor/event log ◀── stdout/stderr
```

Every output chunk receives a monotonically increasing cursor. A reconnecting consumer requests events after its last cursor. Each PTY owns a size-bounded replay buffer; requesting an evicted cursor produces `ReplayGap` rather than incomplete output disguised as complete replay.

Disconnect does not kill the process. Explicit kill, idle expiry, sandbox destroy, or process exit closes the PTY. The provider bounds sessions per sandbox, buffered bytes, input frame size, and input/resize rate. Resize and input are represented as structured control operations for audit metadata, without recording input contents.

After suspend/resume or snapshot restore, runtime PTY sessions are not revived. Consumers receive terminal stream-state events and create new PTYs when needed.

## 9. Filesystem watcher

The watcher converts raw operating-system changes into provider-independent workspace events:

```text
OS events
  → normalize
  → ignore/filter
  → debounce/coalesce
  → increment workspace revision
  → cursor event batch
```

Normalized event kinds are `created`, `modified`, `deleted`, `renamed`, `workspace_invalidated`, and `watch_overflow`. Editor temporary files, internal implementation files, and routine `.git` noise are ignored by default.

Watcher batches have monotonic cursors and bounded replay. A consumer that falls behind receives `ReplayGap`. Native watcher overflow produces `watch_overflow` followed by `workspace_invalidated`; the consumer must then reload the file tree instead of guessing missed changes.

All successful mutating workspace operations increment the workspace revision. Watcher events carry the corresponding observed revision so browser state and model-loop context can detect staleness.

## 10. Error and compensation model

The public error taxonomy is:

- `SandboxUnavailable`: provider or capacity unavailable;
- `SandboxNotFound`: unknown or already-reaped resource;
- `SandboxStateConflict`: lifecycle or concurrent-transition conflict;
- `SandboxPolicyViolation`: unsafe path, command, archive, or configuration;
- `SandboxTimeout`: bounded provider or operation timeout;
- `ReplayGap`: requested stream cursor is no longer available.

Provider-specific stderr and exception types remain internal and are attached only as sanitized diagnostic metadata.

Create failures clean resources in reverse acquisition order. Destroy is idempotent and attempts all cleanup stages. Snapshot never mutates the source workspace. Failed restore destroys its partial sandbox and artifact extraction. Long-running operations re-check lifecycle ownership before committing state. Provider-owned labels and TTL metadata allow safe orphan reconciliation after process failure.

## 11. Configuration

The existing sandbox configuration expands into these groups:

```text
SandboxConfig
├── provider: memory | docker
├── lifecycle
│   ├── create_timeout_sec
│   ├── idle_timeout_sec
│   └── max_lifetime_sec
├── resources
│   ├── cpu_limit
│   ├── memory_limit_mb
│   ├── pids_limit
│   └── workspace_limit_mb
├── execution
│   ├── command_timeout_sec
│   ├── max_output_bytes
│   └── allowed_env_names
├── streams
│   ├── max_pty_sessions
│   ├── replay_buffer_bytes
│   ├── watcher_debounce_ms
│   └── watcher_replay_events
└── docker
    ├── image
    ├── network_mode
    └── tmpfs_limit_mb
```

Development defaults may select the memory provider. Docker configuration is validated before the application starts; unsafe or internally inconsistent values do not degrade into permissive behavior.

## 12. Observability

All operations correlate `sandbox_id`, `coding_run_id`, and `task_id` where available. Required metrics include:

- lifecycle latency and failure rate by stage and provider;
- running, suspended, capacity-rejected, and orphan sandbox counts;
- command duration, timeout, and output truncation;
- snapshot size, creation/restore duration, and checksum failure;
- PTY sessions, replay gaps, and replay-buffer utilization;
- watcher lag, overflow, replay gaps, and full-resynchronization requests;
- provider error and cleanup-compensation outcomes.

Structured logs and audit events use stable operation and error codes. High-cardinality identifiers remain in logs/traces rather than metric labels.

## 13. Verification strategy

A reusable provider conformance suite runs the same externally visible scenarios against memory and Docker providers:

1. lifecycle and idempotency;
2. file, search, Git, and bounded command operations;
3. snapshot consistency, validation, restore, and cleanup;
4. PTY cursor order, reconnect replay, slow consumers, and replay gaps;
5. watcher normalization, debounce, revision order, overflow, and resync;
6. traversal, symlink escape, unsafe archives, forbidden environment, and resource-limit enforcement;
7. concurrent lifecycle transitions and operation/state races;
8. injected create, command, snapshot, restore, and transport failures.

Docker command construction and error mapping are unit-tested through the injected runner. The memory suite is required in normal test runs. The real Docker suite is opt-in while local Docker is unavailable and must clearly report why it skipped.

## 14. Completion criteria

This project is complete when:

- domain types and provider/session/stream ports are stable;
- the memory provider passes the full conformance suite;
- the Docker provider supports lifecycle and workspace operations;
- bounded file, search, read-only Git, and command tools are implemented;
- suspend, resume, snapshot, restore, and idempotent destroy work;
- PTY and watcher streams support reconnect and bounded replay;
- security rules and failure compensation have explicit tests;
- application configuration, dependency wiring, metrics, and audit events are connected;
- the normal suite passes without Docker;
- the same conformance suite passes in an environment with Docker.

## 15. Deferred work

The following are intentionally separate projects:

- the real model/tool execution loop;
- the browser REST/WebSocket workspace gateway;
- managed SaaS and Kubernetes sandbox providers;
- remote object storage for snapshots;
- multi-node PTY and watcher fan-out;
- sandbox network egress policy and package-install mediation.

The next two projects must build on this foundation in order: first the real model tool loop, then the browser REST/WebSocket gateway. This ordering lets the browser surface expose a proven execution model instead of defining a competing one.
