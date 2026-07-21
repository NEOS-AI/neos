# NEOS Coding Agent 구현 계획

> 작성일: 2026-07-18
> 상태: 구현 진행 중 — durable coding loop와 sandbox foundation 구현 완료
> 기준 문서: `docs/claude_code_spec.md`, `docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md`
> 외부 사례: [Shadow](https://www.ishaand.com/shadow)

## 0. 문서 목적

NEOS의 일반 채팅과 분리된 **Code 제품 영역**을 만든다. 사용자가 사이드바에서 Code를 선택하면 저장소와 격리 workspace를 연결하고, coding agent가 파일 탐색 → 계획 → 편집 → 명령 실행 → 검증을 반복한다. 사용자는 실행 중 브라우저를 닫았다 다시 열어도 같은 task를 관찰·제어하고, 도구 실행·diff·터미널·승인 요청을 실시간으로 확인할 수 있어야 한다.

이 문서는 다음을 결정한다.

- coding loop 전용 API와 durable backend 구조
- Docker 및 SaaS/Kubernetes를 포괄하는 sandbox 추상화와 보안 경계
- WebSocket 기반의 순서 보장·재연결 가능한 스트리밍 계약
- Code 전용 프론트 화면, 메시지 accumulator, 파일/terminal/diff UI
- 기존 NEOS 모듈의 재사용 범위와 신규 구현 범위
- 데이터 모델, 상태 머신, 운영·보안·관측성, 테스트 및 단계별 구현 순서

이 문서의 범위는 **단일 agent coding task를 production 수준으로 제공하는 것**까지다. Claude Code의 coordinator/team, 임의 플러그인 배포, IDE 전체 대체, 사용자 PC에 직접 연결하는 bridge는 후속 범위로 둔다.

---

## 1. 결론 요약

### 1.1 권장 구조

```text
Next.js Code UI
  ├─ REST: 생성, snapshot, 파일, diff, 승인, task 제어
  └─ WebSocket: ordered live events + client commands
                 │
                 ▼
FastAPI Coding API / WebSocket Gateway
  ├─ CodingTaskService (소유권, 상태 전이, idempotency)
  ├─ DurableEventStore (PostgreSQL source of truth)
  ├─ LiveEventBus (Redis Streams/PubSub)
  └─ CodingJobDispatcher (Celery)
                 │
                 ▼
Coding Worker
  ├─ CodingLoop (provider-neutral async generator)
  ├─ Context / compaction / budget
  ├─ Tool registry + permission + hooks
  └─ SandboxProvider port
        ├─ DockerSandboxProvider (local/dev)
        ├─ ManagedSandboxProvider (pilot: Modal/Daytona/E2B 중 선택)
        └─ KubernetesSandboxProvider (scale: gVisor/Kata)
                 │
                 ▼
Per-task sandbox + sidecar
  ├─ /workspace git checkout
  ├─ file/search/git/command APIs
  ├─ PTY WebSocket stream
  └─ filesystem watcher
```

핵심 결정은 다음과 같다.

1. **일반 chat과 coding task를 데이터·실행 수명 주기에서 분리한다.** UI shell과 인증은 공유하되 coding loop를 `chat_stream_pipeline.py` 안에 넣지 않는다.
2. **agent 실행은 브라우저 연결과 독립적이어야 한다.** WebSocket 연결 해제는 task 중단이 아니다.
3. **PostgreSQL append-only event log를 진실의 원천으로 둔다.** Redis는 live fan-out과 worker coordination용이며 유실 시 DB replay로 복구한다.
4. **WebSocket은 transport일 뿐 상태 저장소가 아니다.** 최초 REST snapshot + `after_seq` replay + live tail의 세 단계로 연결한다.
5. **sandbox 구현은 port/adapter로 감춘다.** 개발은 Docker, 초기 production은 managed sandbox, 규모·규제 요구가 생기면 Kubernetes gVisor/Kata로 이전한다.
6. **모델에게 직접 shell/filesystem 권한을 주지 않는다.** 모든 실행은 tool pipeline과 sidecar 정책을 통과한다.

### 1.2 권장 제공 전략

| 단계 | 격리 실행환경 | 이유 |
|---|---|---|
| 로컬 개발 | Docker Engine, task별 container + volume | 빠른 디버깅, 낮은 비용, production 보안 경계로 간주하지 않음 |
| 제한된 pilot | Managed sandbox provider | orchestration·snapshot·수명주기를 구매해 제품 검증을 앞당김 |
| 대규모/규제 production | Kubernetes + gVisor 또는 Kata/microVM | 네트워크·스토리지·노드·런타임 정책을 직접 통제 |

Docker 컨테이너만으로 다중 tenant의 악성 코드 실행을 production에 허용하지 않는다. 초기 managed provider 후보는 동일한 conformance suite로 검증한다. Modal은 임의 agent 코드를 위한 secure sandbox와 container/VM runtime을 제공하고, Daytona는 sandbox lifecycle·snapshot/fork API를 제공한다. E2B도 secure-access sandbox 후보로 평가한다. 자체 운영 시 gVisor는 Kubernetes `RuntimeClass`로 적용 가능하며, 더 강한 별도 커널 경계가 필요하면 Kata 계열을 택한다.

---

## 2. 목표와 비목표

### 2.1 제품 목표

- 사이드바의 `Code`에서 일반 chat과 별개의 task 목록 및 새 task 진입점을 제공한다.
- Git 저장소 URL/ref 또는 빈 workspace로 task를 만들 수 있다.
- agent가 read/search/edit/write/bash/git/test 도구를 여러 turn에 걸쳐 사용한다.
- 읽기 작업은 제한적으로 병렬화하고 write/bash는 기본 순차 실행한다.
- task가 수십 분 실행되어도 페이지 이탈·재접속·API 프로세스 재시작을 견딘다.
- 텍스트, reasoning 요약, tool input delta, tool result, diff, terminal, todo, 비용, 승인, 오류를 실시간 표시한다.
- 사용자는 stop, steer/follow-up, approve/deny, retry/resume를 수행할 수 있다.
- workspace의 파일 트리·파일 내용·git diff·terminal을 필요할 때 열어볼 수 있다.
- task별 CPU/RAM/disk/time/token/cost/network 예산을 강제한다.

### 2.2 비목표

- Phase 1에서 coordinator와 다중 write agent를 제공하지 않는다.
- 사용자 임의 Docker daemon, privileged container, host mount를 허용하지 않는다.
- browser WebSocket을 sandbox에 직접 연결하지 않는다.
- 모든 터미널 출력을 영구 보존하지 않는다. 원본 artifact 보존 정책과 UI replay event를 분리한다.
- 기존 일반 chat SSE를 즉시 WebSocket으로 마이그레이션하지 않는다.
- semantic index/Shadow Wiki는 MVP 필수 조건이 아니다. `rg`/file tree/git context를 먼저 제공한다.

---

## 3. 현재 NEOS 분석과 재사용 지도

### 3.1 그대로 재사용 가능한 기반

| 기존 모듈 | 재사용 내용 | 주의점 |
|---|---|---|
| `neos/providers/*`, `neos/utils/llm_factory.py` | 모델 provider 선택·LLM client | coding loop용 tool-call streaming adapter 필요 |
| `neos/api/models/open_responses.py` | response/item/function-call 이벤트 의미 | transport envelope의 `task_id`, `seq`, `run_id` 추가 필요 |
| `neos/api/adapters/stream_adapter.py` | legacy → OpenResponses 변환 경험 | coding 이벤트를 legacy SSE에 억지로 맞추지 않음 |
| `neos/workflow/stream_manager.py` | `Last-Event-ID`, replay 개념 | 현재 in-memory deque/TTL은 durable task log로 사용 불가 |
| `neos/workflow/celery_app.py`, `celery_tasks.py` | 장시간 비동기 job 실행 기반 | coding 전용 queue·soft/hard time limit·resume task 추가 |
| `neos/workflow/checkpointer.py`, `checkpointers/` | checkpoint 패턴 | coding state schema와 event replay 기반 checkpoint 필요 |
| `neos/workflow/autonomy/*` | 자율성 정책 개념 | 파일 경로·명령 AST·network scope를 포함하도록 확장 |
| `neos/workflow/processors/approval_processor.py` 및 approval API | human-in-the-loop 흐름 | skill 이름 중심이 아니라 구체 tool call 중심으로 일반화 |
| `neos/skills/*`, MCP manager | skill discovery와 외부 도구 확장 | sandbox tool과 server-side connector의 trust zone 구분 |
| `neos/observability/*`, `workflow/telemetry.py` | trace/metric | `task_id`, `run_id`, `turn_id`, `tool_call_id`, `sandbox_id` baggage 추가 |
| 인증·resource access dependencies | 사용자 소유권 검사 | WebSocket handshake 및 모든 task subresource에도 동일 적용 |

### 3.2 프론트에서 재사용할 기반

| 기존 모듈 | 재사용 내용 | 변경 방향 |
|---|---|---|
| `web/app/(chat)/layout.tsx`, `components/app-sidebar.tsx` | 인증된 shell과 sidebar | `/code`, `/code/tasks/[taskId]` 제품 영역 추가 |
| `web/components/ai-elements/tool.tsx` | tool 상태 카드 | coding tool renderer registry로 확장 |
| `confirmation.tsx`, 기존 approval UI | 승인 표현 | allow once/session rule/deny와 위험 설명 추가 |
| `reasoning.tsx`, `message.tsx`, `messages.tsx` | message part UI | coding 전용 accumulator 결과를 받도록 분리 |
| `use-chat-stream.ts`, `stream-types.ts` | 이벤트 처리/타입가드 경험 | 600줄대 chat hook에 coding 분기 추가 금지; 새 hook 작성 |
| `code-editor.tsx`, `diffview.tsx`, `lib/editor/*` | 코드·diff 표시 | workspace file API 및 snapshot version과 연결 |
| `use-stick-to-bottom`, `react-resizable-panels`, Shiki | 스크롤·분할 pane·highlight | Code workspace shell에서 그대로 활용 |
| SWR 및 Next.js RSC | 초기 server data fetch | task snapshot prefetch/hydration에 활용 |

### 3.3 재사용하지 말아야 할 경계

- `chat_stream_pipeline.py`는 짧은 HTTP SSE 요청의 수명에 맞춰져 있다. coding task runner로 확장하면 request lifecycle과 agent lifecycle이 다시 결합된다.
- `StreamManager`의 단일 `asyncio.Queue`는 여러 consumer에 broadcast semantics를 보장하지 않고 프로세스 재시작 시 유실된다. coding 이벤트 저장소가 될 수 없다.
- LangGraph의 정적 그래프를 coding tool loop로 사용하지 않는다. coding loop는 모델이 다음 tool을 동적으로 고르는 async generator로 만들고, durable state machine이 바깥 수명주기를 관리한다.
- 웹 앱 내부의 Vercel AI SDK tool은 Next.js 프로세스가 직접 실행하는 UI artifact 도구다. sandbox 안의 untrusted command 실행과 trust boundary가 다르다.

---

## 4. 도메인 모델과 상태 머신

### 4.1 엔티티

```text
CodingProject
  id, owner_id, repo_provider, repo_url, default_branch,
  credential_ref, settings, created_at

CodingTask
  id, project_id, owner_id, title, prompt, status,
  base_ref, working_branch, sandbox_id, active_run_id,
  model, permission_mode, budgets, last_seq,
  created_at, started_at, finished_at, last_activity_at

CodingRun
  id, task_id, attempt, status, resume_from_checkpoint_id,
  model, usage, stop_reason, error_code, started_at, finished_at

CodingEvent
  task_id, seq, event_id, run_id, turn_id, tool_call_id,
  type, payload_json, visibility, created_at
  UNIQUE(task_id, seq), UNIQUE(event_id)

CodingCheckpoint
  id, task_id, run_id, seq, loop_state_json,
  workspace_revision, transcript_blob_ref, created_at

CodingApproval
  id, task_id, run_id, tool_call_id, status,
  requested_input_hash, decision, rule_scope,
  requested_at, expires_at, decided_at, decided_by

SandboxLease
  id, task_id, provider, external_id, state,
  image_digest, resource_limits, network_policy,
  workspace_ref, expires_at, heartbeat_at

CodingArtifact
  id, task_id, kind, content_ref, sha256, byte_size,
  retention_class, created_at
```

Git access token과 provider API key 원문은 위 테이블에 저장하지 않는다. 기존 secret manager/암호화 저장소의 opaque `credential_ref`만 저장하고 sandbox에는 task 범위의 단기 credential을 주입한다.

### 4.2 Task 상태

```text
DRAFT → QUEUED → PROVISIONING → CLONING → READY → RUNNING
                                                  ├→ WAITING_APPROVAL
                                                  ├→ WAITING_USER
                                                  ├→ PAUSING → PAUSED
                                                  ├→ COMPLETED
                                                  ├→ FAILED → QUEUED(resume)
                                                  └→ CANCELLING → CANCELLED

READY/RUNNING/PAUSED → EXPIRED → ARCHIVED
```

규칙:

- 상태 전이는 `CodingTaskService.transition(expected_version, from, to)` 한 곳에서만 수행한다.
- 클라이언트 요청은 `Idempotency-Key`를 받는다. 중복 create/approve/cancel은 같은 결과를 반환한다.
- WebSocket disconnect는 상태 전이가 아니다.
- `WAITING_APPROVAL` 중에도 lease heartbeat는 유지하되 idle resource tier로 축소할 수 있다.
- terminal command 프로세스와 coding run 상태는 별도다. task 취소 시 process group → sidecar → sandbox 순으로 종료한다.

### 4.3 Event log 불변식

- `seq`는 task 단위 단조 증가 정수다. DB transaction에서 할당한다.
- 상태 변경과 그 상태를 설명하는 event append는 같은 transaction으로 커밋한다.
- event는 수정하지 않고 정정 event를 append한다.
- 모든 UI 상태는 `snapshot + events(after_seq)`로 복원 가능해야 한다.
- 큰 tool output은 object storage artifact로 저장하고 event에는 preview, sha256, ref만 둔다.
- 민감한 stdout/env/credential은 append 전에 redact한다.

---

## 5. Coding loop 아키텍처

### 5.1 loop 경계

신규 패키지 `neos/coding/`을 만들고 LangGraph에서 독립시킨다.

```text
CodingLoop.run(input, checkpoint, deps) -> AsyncIterator[CodingDomainEvent]

turn:
  1. abort/budget/deadline 확인
  2. transcript 복구 및 필요 시 compact
  3. system/project context + stable tool schema 조립
  4. model stream 소비
  5. text/reasoning/tool-input delta 이벤트 emit
  6. 완성된 tool call 검증·권한 판정
  7. 안전한 read batch 병렬 실행, mutation/command 순차 실행
  8. tool result를 transcript에 추가
  9. checkpoint + usage 저장
 10. tool call이 없으면 Stop hook/검증 후 종료
```

`CodingLoop`는 DB, Celery, WebSocket을 직접 알지 않는다. 다음 dependency를 주입한다.

```python
@dataclass(frozen=True)
class CodingLoopDeps:
    model: CodingModel
    tools: ToolRegistry
    permissions: PermissionEvaluator
    sandbox: SandboxSession
    context: ContextManager
    checkpoints: CheckpointWriter
    events: DomainEventSink
    clock: Clock
```

### 5.2 메시지와 transcript

- user/assistant/tool/result/system/summary를 provider-neutral part로 저장한다.
- provider wire object를 그대로 DB canonical format으로 쓰지 않는다.
- `tool_call_id`로 input delta, 실행, result를 연결한다.
- user message는 모델 호출 전에 영속화한다.
- 매 tool batch 완료 후 checkpoint한다. write/bash 전후에는 강제 checkpoint한다.
- transcript event와 compact summary를 모두 보존해 감사 가능하게 한다.

### 5.3 컨텍스트 수집

task 초기화 시 병렬 수집하고 workspace revision별 캐시한다.

- Git branch/default branch/status/recent commits/remotes
- repository instruction: 루트에서 현재 디렉터리까지 `AGENTS.md`, 호환 모드로 `CLAUDE.md`
- 주요 manifest와 test commands (`package.json`, `pyproject.toml`, `Cargo.toml` 등)
- bounded file tree, 언어/크기 통계
- task의 이전 memory와 사용자 설정

동적 파일 내용은 모델이 Read/Grep 도구로 가져오게 하고 초기 prompt에 전체 repo를 넣지 않는다.

### 5.4 compact와 budget

예산은 hard limit으로 강제한다.

- `max_turns`, `max_tool_calls`, `max_wall_seconds`
- `max_input_tokens`, `max_output_tokens`, `max_cost_usd`
- `max_command_seconds`, `max_output_bytes`
- sandbox `cpu`, `memory_mb`, `disk_mb`, `pids`

context window의 고정 잔여치보다 모델별 `context_window - reserved_output - tool_overhead`로 임계값을 계산한다. 먼저 오래된 tool result를 artifact reference로 축소하고, 이후 turn 묶음을 요약한다. compact 실패 3회는 circuit breaker로 중단하고 사용자가 resume할 수 있는 명시적 오류로 만든다.

### 5.5 오류 복구

| 오류 | 처리 |
|---|---|
| model 429/5xx/network | provider 정책에 따른 bounded retry; 같은 turn idempotency 유지 |
| invalid tool JSON | streaming parser 종료 후 1회 repair; 원 입력과 repair event 기록 |
| tool validation | tool result error로 모델에 반환, mutation 없음 |
| sandbox transient | health check 후 lease 재연결; 불가하면 checkpoint 기반 새 sandbox 복원 |
| worker crash | Celery redelivery → task lease 획득 → 최신 checkpoint/seq부터 resume |
| duplicate delivery | run lease와 idempotency key로 두 번째 worker 종료 |
| event fan-out loss | PostgreSQL `after_seq` replay 후 Redis live tail 재가입 |
| output too large | artifact 저장 + bounded preview event |

---

## 6. Tool, 권한, hook

### 6.1 MVP 도구

| 분류 | 도구 | 동시성 | 기본 권한 |
|---|---|---:|---|
| 탐색 | `list_files`, `read_file`, `grep`, `git_status`, `git_diff` | 최대 8 | workspace 내부 자동 허용 |
| 변경 | `apply_patch`, `write_file`, `delete_file` | 순차 | diff preview 후 정책 판정 |
| 실행 | `run_command`, `start_process`, `read_process`, `stop_process` | 순차 시작 | 명령 AST/allow-deny/승인 |
| 계획 | `todo_replace`, `todo_update` | 순차 | 자동 허용 |
| Git | `git_log`, `git_diff`, `git_commit` | mutation 순차 | commit은 설정별 ask |
| 외부 | 기존 MCP/skill 중 server-side tools | 도구별 | 별도 trust zone 정책 |

`git push`, PR 생성, package publish, cloud mutation은 MVP 기본 도구에서 제외하고 명시적 connector + 승인 기능으로 추가한다.

### 6.2 공통 tool pipeline

```text
lookup → schema validate → semantic validate → abort check
→ PreToolUse hooks → permission rules → optional user approval
→ execute in sandbox/server trust zone → normalize result
→ redact/truncate/artifact persist → PostToolUse hooks
→ event + telemetry + transcript append
```

도구 schema 순서는 안정적으로 정렬하여 provider prompt cache가 불필요하게 무효화되지 않게 한다.

### 6.3 PermissionEvaluator

판정 결과는 `ALLOW | DENY | ASK`와 이유·rule source를 반환한다.

- 경로: canonical path가 `/workspace` 안인지, symlink 탈출이 없는지 확인
- shell: 문자열 allowlist가 아니라 shell AST를 파싱하여 substitution, redirection, pipe 각 segment를 평가
- network: 기본 deny, package registry와 repo host 등 task별 egress allowlist
- secrets: env 이름만 노출하고 값은 tool output/log에서 redaction
- mutation: `.git`, credential path, system path는 agent write 금지
- destructive: recursive delete, force push, privilege escalation, daemon socket 접근은 deny 또는 ask

모드:

- `plan`: read-only tools만 허용
- `default`: 안전한 read 자동 허용, mutation/command 정책에 따라 ask
- `auto`: 정책상 허용 범위 내 자동 실행. AI classifier는 보조 신호이며 hard deny를 덮지 못함
- `bypass`: production remote sandbox에서는 제공하지 않음

승인 UI는 **정규화된 tool input, 위험 이유, 예상 영향, diff/command preview, rule 저장 범위**를 보여준다. 결정 시 원 요청의 hash를 확인해 TOCTOU를 막는다.

### 6.4 Hook

MVP hook 이벤트:

- `SessionStart`, `UserPromptSubmit`
- `PreToolUse`, `PostToolUse`, `PostToolUseFailure`
- `PermissionRequest`, `Stop`

초기에는 server-configured Python hook만 지원한다. repository가 제공하는 임의 hook executable은 sandbox 안에서만 실행하고 별도 예산·권한을 적용하는 후속 기능으로 둔다.

---

## 7. Sandbox 설계

### 7.1 추상화

신규 `neos/coding/sandbox/base.py`에 provider port를 둔다.

```python
class SandboxProvider(Protocol):
    async def create(self, spec: SandboxSpec) -> SandboxLease: ...
    async def get(self, external_id: str) -> SandboxLease: ...
    async def suspend(self, external_id: str) -> None: ...
    async def resume(self, external_id: str) -> SandboxLease: ...
    async def snapshot(self, external_id: str) -> WorkspaceSnapshot: ...
    async def destroy(self, external_id: str) -> None: ...
    async def open_session(self, lease: SandboxLease) -> SandboxSession: ...
```

`SandboxSession`은 file/search/git/command/PTY/watch interface를 제공한다. coding tool은 provider SDK가 아니라 이 interface만 사용한다.

### 7.2 sidecar

각 sandbox 내부 sidecar는 backend와 mTLS 또는 provider private channel로만 통신한다.

- file: tree/read/write/apply-patch/stat
- search: literal/regex grep, glob
- git: status/diff/log/branch/commit
- process: exec, PTY create/input/resize/kill, output cursor replay
- watch: filesystem change batch (`path`, `kind`, `version`)
- health: image version, workspace revision, capacity

browser에는 sidecar credential이나 주소를 노출하지 않는다. gateway가 인증·인가 후 proxy한다.

### 7.3 보안 baseline

- non-root UID, no privileged, no host PID/network/IPC
- Linux capabilities drop all, `no-new-privileges`, seccomp/AppArmor
- read-only root filesystem + `/workspace`, `/tmp` writable quota
- CPU/RAM/PID/disk/time cgroup 제한
- metadata service, RFC1918, cluster control plane egress 차단
- DNS proxy와 explicit domain allowlist
- Docker socket, Kubernetes service-account token mount 금지
- base image digest pinning, SBOM/취약점 scan, 정기 patch
- task별 ephemeral secret, 종료 시 revoke
- snapshot 전 credential/temp redaction
- idle suspend와 absolute TTL, orphan reaper

### 7.4 선택지 비교

| 선택지 | 장점 | 단점 | 권고 |
|---|---|---|---|
| Docker 단독 | 구현·로컬 디버깅이 쉬움 | host kernel 공유, 자체 orchestration/보안 부담 | 개발 전용 |
| E2B | agent sandbox에 특화, secure access 제공 | vendor API·지역·비용 종속 | pilot 후보 |
| Modal Sandbox | 임의 코드용 secure container, volume/image/lifecycle, VM runtime 옵션 | VM runtime 등 일부 기능 성숙도 확인 필요 | pilot 후보 |
| Daytona | lifecycle, resource, snapshot/fork API가 풍부 | 실제 격리 class와 지역/운영 SLA 검증 필요 | pilot 후보 |
| Kubernetes + gVisor | OCI/K8s 생태계 유지, `RuntimeClass` 적용 | syscall 호환성·성능·운영 난도 | self-host 기본 후보 |
| Kubernetes + Kata/microVM | 별도 커널 경계, 높은 격리 | cold start·메모리·nested virtualization 운영 부담 | 고위험 tenant 후보 |

선정은 문서 비교가 아니라 conformance/benchmark로 한다.

- 격리: cross-tenant filesystem/network/process/metadata escape 시험
- 기능: git clone, pnpm/pip/cargo install, test server/PTY, watcher, symlink
- 수명: create/resume/snapshot/destroy, orphan cleanup
- 성능: p50/p95 cold start, clone, command latency, snapshot restore
- 운영: region/data residency, audit log, quota, incident/SLA, image control
- 비용: active/idle/snapshot/egress/volume별 task 비용

### 7.5 workspace 복원

workspace source of truth는 Git + checkpoint metadata다.

1. base commit clone
2. working branch checkout
3. 마지막 checkpoint의 patch bundle 또는 workspace snapshot 복원
4. `git status`와 recorded workspace revision 비교
5. 불일치 시 task를 `NEEDS_RECOVERY`로 두고 자동 mutation 금지

SaaS snapshot에만 의존하지 않아 provider 이동성과 감사 가능성을 유지한다.

---

## 8. API 계약

### 8.1 REST

```http
POST   /api/v1/coding/projects
GET    /api/v1/coding/projects
GET    /api/v1/coding/projects/{project_id}

POST   /api/v1/coding/tasks
GET    /api/v1/coding/tasks?cursor=&status=&project_id=
GET    /api/v1/coding/tasks/{task_id}
POST   /api/v1/coding/tasks/{task_id}/messages
POST   /api/v1/coding/tasks/{task_id}/commands/{pause|resume|cancel|retry}
GET    /api/v1/coding/tasks/{task_id}/events?after_seq=&limit=
GET    /api/v1/coding/tasks/{task_id}/snapshot

POST   /api/v1/coding/tasks/{task_id}/approvals/{approval_id}
GET    /api/v1/coding/tasks/{task_id}/files/tree?revision=
GET    /api/v1/coding/tasks/{task_id}/files/content?path=&revision=
GET    /api/v1/coding/tasks/{task_id}/git/diff?base=&path=
GET    /api/v1/coding/tasks/{task_id}/artifacts/{artifact_id}
```

`POST /tasks`는 202와 `{task_id, status:"QUEUED", websocket_url, snapshot_url}`을 즉시 반환한다. repository clone이나 모델 호출을 HTTP 요청 안에서 기다리지 않는다.

follow-up message mode:

- `queue`: 현재 run 완료 뒤 실행
- `steer`: 현재 model stream을 abort하고 현재 checkpoint에서 새 지시로 계속
- `replace_pending`: 아직 실행 전인 queued message 교체

기본값은 데이터 손실 위험이 낮은 `queue`다.

### 8.2 WebSocket

```http
GET /api/v1/coding/ws?task_id={id}&after_seq={n}
Authorization: session cookie 또는 단기 WS ticket
Sec-WebSocket-Protocol: neos.coding.v1
```

연결 순서:

1. HTTP upgrade 전 task owner 검사
2. server `hello {protocol_version, task_id, head_seq, heartbeat_ms}`
3. `after_seq`가 보존 범위 안이면 event replay
4. 범위 밖이면 `resync_required {snapshot_url, head_seq}`
5. replay 완료 후 `caught_up {head_seq}`와 live tail
6. 30초 ping/pong, 지수 backoff + jitter로 재접속

서버 event envelope:

```json
{
  "v": 1,
  "task_id": "ct_...",
  "seq": 184,
  "event_id": "ce_...",
  "run_id": "cr_...",
  "turn_id": "turn_...",
  "type": "coding.tool.input.delta",
  "ts": "2026-07-18T09:30:11.123Z",
  "payload": {
    "tool_call_id": "call_...",
    "delta": "{\"path\":\"web/"
  }
}
```

client command envelope:

```json
{
  "v": 1,
  "command_id": "cc_...",
  "type": "coding.terminal.input",
  "task_id": "ct_...",
  "payload": {"terminal_id": "pty_...", "data": "pnpm test\r"}
}
```

server는 `command.ack` 또는 `command.error`로 응답한다. 승인·취소 같이 중요한 mutation은 WebSocket 명령을 받아도 내부적으로 REST와 동일한 idempotent application service를 사용한다.

### 8.3 이벤트 taxonomy

| 영역 | 이벤트 |
|---|---|
| lifecycle | `task.created`, `task.status.changed`, `run.started`, `run.completed`, `run.failed` |
| assistant | `message.started`, `text.delta`, `reasoning.summary.delta`, `message.completed` |
| tool | `tool.input.started`, `tool.input.delta`, `tool.input.completed`, `tool.started`, `tool.progress`, `tool.completed`, `tool.failed` |
| workspace | `file.changed`, `file.deleted`, `tree.invalidated`, `git.diff.updated`, `git.status.updated` |
| terminal | `terminal.started`, `terminal.output`, `terminal.exited`, `terminal.truncated` |
| control | `approval.requested`, `approval.resolved`, `budget.updated`, `checkpoint.created`, `context.compacted` |
| task UX | `todo.replaced`, `todo.updated`, `message.queued`, `message.steered` |
| protocol | `hello`, `caught_up`, `resync_required`, `heartbeat`, `error` |

OpenResponses와 의미가 같은 assistant/tool part는 내부 payload를 공유하되 coding transport envelope과 lifecycle 확장을 명시한다. `neos:` 같은 느슨한 문자열 확장 대신 `coding.*` namespace와 version을 고정한다.

### 8.4 전달 보장과 backpressure

- 전달은 at-least-once, UI 적용은 `seq` 기반 idempotent로 한다.
- client는 마지막 연속 적용 seq를 로컬 저장한다. gap 발견 시 즉시 REST replay한다.
- text/terminal delta는 서버에서 16–50ms 또는 크기 기준으로 coalesce한다.
- 상태·승인·오류·완료 event는 coalesce하지 않는다.
- 느린 client outbound queue가 한도를 넘으면 delta를 드롭하지 않고 연결을 `1013 Try Again Later`로 닫아 replay하게 한다.
- DB에는 매 토큰이 아니라 의미 있는 block/delta batch로 debounce 저장한다. message final content도 별도 snapshot으로 저장한다.

---

## 9. 프론트엔드 계획

### 9.1 정보 구조

```text
/code                         새 coding task + 최근 task
/code/tasks/[taskId]          coding workspace

Desktop layout
┌─ NEOS sidebar ─┬─ task conversation ─────┬─ workspace panel ─┐
│ Chat           │ sticky user prompt      │ Files / Diff      │
│ Code (active)  │ text/reasoning/tools    │ Editor / Terminal │
│ recent tasks   │ approval / todo         │ Git / Context     │
└────────────────┴──────────────────────────┴───────────────────┘
```

- 기존 `AppSidebar`에 제품 navigation (`Chat`, `Code`)과 mode별 recent list를 둔다.
- Code route는 resizable 2-pane을 기본으로 하고 workspace panel은 접을 수 있다.
- 모바일은 conversation 우선, workspace는 full-screen sheet/tab으로 전환한다.
- 일반 chat의 history와 coding task history를 섞지 않는다.

### 9.2 Shadow에서 채택할 스트리밍 패턴

Shadow는 장시간 task에서 client가 자유롭게 연결/해제되도록 agent와 client를 분리하고, task별 stream processor가 chunk를 broadcast한다. 페이지는 먼저 DB history를 가져오고 WebSocket 연결 시 현재 `stream-state`를 받은 뒤 incremental chunk를 누적한다. tool-call delta의 부분 JSON도 누적 파싱하고, 파일 watcher로 terminal 등 우회 변경까지 반영한다. 이 원칙을 다음처럼 강화해 적용한다.

1. **snapshot + replay + live**: Shadow의 in-memory stream-state에 durable `seq` replay를 추가한다.
2. **part map**: `Map<partId, CodingPart>`와 ordered id 배열을 분리한다. ref는 즉시 event 처리, React state는 frame 단위 commit에 사용한다.
3. **부분 JSON**: tool input delta는 문자열로 보존하고 tolerant parser로 `path`, `command` 등 표시 가능한 필드만 추출한다. 완성 전 input으로 실행하지 않는다.
4. **block markdown memoization**: 전체 assistant markdown을 매 token 재파싱하지 않고 block별 key로 memoize한다.
5. **filesystem watcher**: tool result만 믿지 않고 sidecar watcher event로 tree/diff cache를 invalidation한다.
6. **sticky prompt pair**: user/assistant turn 경계를 grouping해 현재 장시간 실행의 원 요청이 상단에 남게 한다.
7. **control density**: 기본 화면은 high-level progress, 필요 시 tool/terminal/context를 펼치는 progressive disclosure를 제공한다.

### 9.3 신규 프론트 모듈

```text
web/app/(code)/code/page.tsx
web/app/(code)/code/tasks/[taskId]/page.tsx
web/app/(code)/code/tasks/[taskId]/layout.tsx

web/features/coding/api/coding-api.ts
web/features/coding/types/events.ts
web/features/coding/stream/socket-client.ts
web/features/coding/stream/event-reducer.ts
web/features/coding/stream/partial-json.ts
web/features/coding/hooks/use-coding-task.ts
web/features/coding/hooks/use-coding-socket.ts
web/features/coding/hooks/use-workspace.ts
web/features/coding/components/coding-shell.tsx
web/features/coding/components/coding-conversation.tsx
web/features/coding/components/tool-part.tsx
web/features/coding/components/approval-card.tsx
web/features/coding/components/task-sidebar.tsx
web/features/coding/components/workspace-panel.tsx
web/features/coding/components/file-tree.tsx
web/features/coding/components/file-viewer.tsx
web/features/coding/components/diff-panel.tsx
web/features/coding/components/terminal-panel.tsx
web/features/coding/components/connection-status.tsx
```

기존 `use-chat-stream.ts`에는 coding 처리를 추가하지 않는다. coding socket reducer는 순수 함수로 만들어 event fixture replay 테스트가 가능하게 한다.

### 9.4 client state

상태를 세 종류로 분리한다.

- server snapshot: task, messages, approvals, todos, workspace revision
- ordered stream overlay: 아직 snapshot에 합쳐지지 않은 `seq > snapshot_seq` event
- local UI: open files, pane size, expanded tools, scroll lock, draft prompt

핵심 accumulator:

```ts
type CodingStreamState = {
  appliedSeq: number;
  partsById: Map<string, CodingPart>;
  orderedPartIds: string[];
  toolInputs: Map<string, { raw: string; parsed?: unknown }>;
  terminals: Map<string, TerminalBuffer>;
  approvals: Map<string, ApprovalView>;
  connection: "connecting" | "replaying" | "live" | "stale";
};
```

- `event.seq <= appliedSeq`는 무시한다.
- `event.seq > appliedSeq + 1`이면 rendering을 멈추고 gap replay한다.
- `requestAnimationFrame` 또는 30–60ms scheduler로 React commit을 batch한다.
- terminal은 xterm buffer로 보내되 conversation event에는 bounded preview만 둔다.
- `file.changed`는 열린 파일에 “새 버전 있음”을 표시한다. 사용자의 local edit가 있으면 자동 overwrite하지 않는다.

### 9.5 Chat UI 세부 기능

- assistant message는 text, reasoning summary, tool, todo, approval, checkpoint, error part를 interleave한다.
- reasoning은 진행 중 자동 open, 완료 후 기본 collapse. provider의 비공개 chain-of-thought 원문은 노출하지 않고 허용된 summary만 사용한다.
- tool card는 `preparing → awaiting approval → running → success/error/cancelled` 상태를 가진다.
- file edit는 path, `+/-` line count, diff preview, open-in-workspace를 제공한다.
- command는 normalized command, cwd, elapsed, exit code, live output tail을 제공한다.
- follow-up 입력은 실행 중 `Queue`와 `Steer`를 명확히 구분한다. submit 전에 선택 결과를 chip으로 표시한다.
- stop 버튼은 optimistic하게 `cancelling` 표시하되 server event 전에는 완료로 보이지 않는다.
- auto-scroll은 사용자가 위로 스크롤하면 해제하고 “새 업데이트” 버튼을 표시한다.

### 9.6 Workspace UI

- file tree는 tree metadata만 먼저 받고 내용은 open 시 fetch한다.
- file content 요청은 `revision`/ETag를 사용해 stale response를 거부한다.
- MVP editor는 read-only viewer + diff review다. 직접 사용자 편집은 충돌/동기화 모델을 정한 후 후속 phase에서 제공한다.
- terminal은 xterm.js를 신규 의존성으로 추가하고 PTY resize/input을 WebSocket command로 전달한다.
- workspace panel header에 branch, dirty state, diff stats, sandbox state, resource usage를 표시한다.
- modified file tree에서 파일 클릭 시 diff 또는 최신 content로 이동한다.

### 9.7 접근성·성능

- 모든 tool state는 색상 외 icon/text로 표현하고 `aria-live`는 완료/승인/오류에만 사용한다.
- virtualized conversation/file tree는 실제 측정 후 도입하되, markdown block memoization과 event batching은 처음부터 적용한다.
- terminal output과 hidden tool output이 React component tree 전체를 재렌더링하지 않도록 external store selector를 사용한다.
- reduced motion 설정에서는 새 task animation과 pulse를 비활성화한다.
- keyboard: stop, focus prompt, toggle workspace/terminal/diff, approve/deny는 충돌 없는 shortcut을 제공한다.

---

## 10. 백엔드 파일 계획

### 10.1 신규 패키지

```text
neos/coding/domain/models.py              branded IDs, task/run/event state
neos/coding/domain/events.py              versioned domain event schema
neos/coding/domain/errors.py              stable public error codes
neos/coding/application/task_service.py   commands, transitions, idempotency
neos/coding/application/run_service.py    dispatch/resume/cancel
neos/coding/application/approval_service.py
neos/coding/loop/engine.py                provider-neutral async loop
neos/coding/loop/context.py               repo context + compaction
neos/coding/loop/budget.py                hard budgets
neos/coding/loop/transcript.py            canonical messages/checkpoints
neos/coding/tools/base.py                 Tool protocol/result
neos/coding/tools/registry.py             stable ordered pool
neos/coding/tools/executor.py             partition + pipeline
neos/coding/tools/files.py
neos/coding/tools/shell.py
neos/coding/tools/git.py
neos/coding/tools/todo.py
neos/coding/permissions/evaluator.py
neos/coding/permissions/shell_parser.py
neos/coding/hooks/runner.py
neos/coding/sandbox/base.py
neos/coding/sandbox/docker.py
neos/coding/sandbox/managed.py
neos/coding/sandbox/kubernetes.py
neos/coding/events/store.py              PostgreSQL append/replay
neos/coding/events/bus.py                Redis live fan-out
neos/coding/events/publisher.py           transactional append + publish
neos/coding/repositories/task_repository.py
neos/coding/repositories/checkpoint_repository.py
neos/coding/workers/tasks.py              Celery entrypoints
neos/api/models/coding_models.py
neos/api/handlers/coding_handlers.py
neos/api/handlers/coding_ws_handlers.py
neos/api/dependencies/coding_access.py
```

Sidecar는 보안 경계와 배포 주기가 다르므로 별도 top-level package/image로 둔다.

```text
sandbox_sidecar/app.py
sandbox_sidecar/auth.py
sandbox_sidecar/workspace.py
sandbox_sidecar/files.py
sandbox_sidecar/search.py
sandbox_sidecar/git.py
sandbox_sidecar/process.py
sandbox_sidecar/watcher.py
sandbox_sidecar/security.py
docker/Dockerfile.coding-sandbox
docker/Dockerfile.sandbox-sidecar
```

### 10.2 수정 파일

- `neos/main.py`: coding HTTP/WS router, lifecycle resources 등록
- `neos/config/schema.py`, `neos/config/settings.py`: coding/sandbox/ws/budget 설정
- `neos/workflow/celery_app.py`: `coding` queue와 task routes/time limits
- `neos/database/models.py` 또는 별도 `neos/database/coding_models.py`: 신규 테이블
- `db/migrations/`: coding schema, indexes, RLS/ownership migration
- `docker-compose.dev.yml`: sandbox control-plane profile와 local provider 설정
- `web/components/app-sidebar.tsx`: Chat/Code 제품 navigation
- `web/lib/backend-routes.ts`: coding proxy route mapping
- `web/package.json`: xterm 계열 dependency

---

## 11. 데이터베이스와 보존 정책

### 11.1 인덱스

- `coding_tasks(owner_id, last_activity_at DESC)`
- `coding_tasks(project_id, status, created_at DESC)`
- `coding_events(task_id, seq)` unique
- `coding_events(run_id, created_at)`
- `coding_approvals(task_id, status, expires_at)`
- `sandbox_leases(state, expires_at)` orphan reaper
- `coding_artifacts(task_id, kind, created_at)`

### 11.2 저장 전략

- task/message/status/approval/checkpoint metadata: PostgreSQL
- live fan-out/worker lease: Redis
- 큰 transcript, stdout, diff bundle, snapshot: S3-compatible object storage
- terminal full output: 기본 7일, security event 및 final diff: task 보존기간
- sandbox filesystem: ephemeral; Git/patch/snapshot으로 복구
- user delete: task tombstone → active run cancel → credential revoke → sandbox destroy → artifact async purge

DB event insert와 Redis publish 사이의 이중 쓰기는 transactional outbox로 해결한다. worker가 event와 outbox row를 같은 transaction에 저장하고 publisher가 Redis에 전달한다. Redis 중복은 `event_id`/`seq`로 제거한다.

---

## 12. 운영, 관측성, 보안

### 12.1 설정 시작값

```text
CODING_ENABLED=false
CODING_WS_ENABLED=false
CODING_SANDBOX_PROVIDER=docker
CODING_MAX_ACTIVE_TASKS_PER_USER=3
CODING_MAX_WALL_SECONDS=3600
CODING_IDLE_SUSPEND_SECONDS=600
CODING_SANDBOX_TTL_SECONDS=7200
CODING_EVENT_REPLAY_LIMIT=5000
CODING_WS_HEARTBEAT_SECONDS=30
CODING_READ_CONCURRENCY=8
CODING_MAX_TOOL_OUTPUT_BYTES=1048576
```

값은 pilot telemetry로 조정하되 무제한 기본값은 두지 않는다.

### 12.2 metric과 trace

- task create→ready, ready→first token, turn/tool duration
- sandbox cold/resume latency와 provision failure
- active/idle/waiting approval task 수
- WS connection/reconnect/gap/resync/slow-consumer 수
- event DB append/publish lag, replay size
- tool allow/deny/ask와 approval latency
- token/cost/compact/retry, task별 CPU/RAM/disk/network
- resume 성공률, duplicate worker 차단, orphan sandbox 수

trace는 API submit → Celery dispatch → sandbox create → model turn → tool call → sidecar request를 하나의 `task_id/run_id`로 연결한다. tool input/output 원문은 기본 span attribute에 넣지 않는다.

### 12.3 위협 모델 필수 항목

- 악성 repository가 instruction/file 이름/terminal output으로 prompt injection
- model이 secret exfiltration 또는 internal network scan 시도
- symlink/path traversal로 workspace 탈출
- fork bomb, disk fill, long-running daemon, crypto mining
- WebSocket task IDOR, replay data leakage, forged approval
- tool input streaming 중 보인 값과 실행 값의 불일치
- poisoned dependency install script
- snapshot/artifact에 secret 잔존
- 동일 project의 병렬 task가 credential/branch/workspace 공유

security review gate 없이 remote untrusted repository 지원 플래그를 켜지 않는다.

---

## 13. 테스트 전략

### 13.1 단위/계약 테스트

- loop: no-tool 종료, multi-turn, tool error feedback, compact, budget, abort
- executor: read batching과 mutation serialization
- permission: path canonicalization, symlink, shell AST, network rule, approval hash
- event reducer: duplicate, gap, out-of-order, replay/live 경계
- partial JSON: 모든 prefix가 crash하지 않고 완성 JSON과 동일 결과
- state transition: invalid transition, optimistic version, idempotency
- provider adapter: 모든 sandbox가 동일 conformance suite 통과

### 13.2 통합 테스트

- task create → Docker provision → repo clone → edit → test → final diff
- WebSocket disconnect 후 `after_seq` replay와 정확히 같은 UI state
- API/worker/Redis 각각 재시작 후 task resume
- approval 대기 → 재접속 → approve → 동일 tool call 한 번만 실행
- terminal command가 만든 파일을 watcher가 UI에 반영
- stdout/artifact redaction과 oversized output truncation
- cancel이 model stream, process group, sandbox lease까지 전파

### 13.3 E2E와 부하

- Playwright: Code navigation, new task, streaming tool cards, diff open, approval, reconnect, stop
- deterministic fake model이 정해진 tool sequence를 방출해 flaky LLM 의존 제거
- 1 task당 10k event replay, 100+ concurrent sockets, slow consumer 시험
- sandbox escape/adversarial corpus를 별도 CI/security 환경에서 수행

### 13.4 수용 기준

- 브라우저를 닫아도 agent가 계속 실행되고 재접속 후 event gap이 없다.
- 동일 event replay 결과와 live 처리 결과의 serialized UI state가 동일하다.
- worker crash 뒤 마지막 완료 tool call을 중복 mutation 없이 resume한다.
- 승인되지 않은 destructive command, workspace 밖 write, private network 접근은 실행되지 않는다.
- 일반 chat SSE와 history에 회귀가 없다.
- task 종료/삭제 후 sandbox와 ephemeral credential이 정해진 시간 안에 제거된다.

---

## 14. 단계별 구현 계획

각 단계는 독립 배포·rollback 가능한 feature flag와 reviewer gate를 갖는다.

### Phase 0 — 계약과 vertical spike

**목표:** 실제 LLM 없이 durable event와 reconnect가 끝까지 흐르는 최소 경로.

- domain ID/state/event schema와 DB migration 작성
- task CRUD, owner dependency, idempotency 작성
- PostgreSQL event store + outbox + Redis bus 작성
- coding WebSocket hello/replay/live/heartbeat 구현
- 프론트 `/code` shell, socket reducer, connection 상태 구현
- fake worker가 text/tool/file event를 생성하는 E2E fixture 제공

**완료 조건:** API/WS 프로세스를 재시작해도 `/code/tasks/:id`가 같은 상태로 복원된다.

#### Durable Phase vertical slice checkpoint (2026-07-19)

- Canonical run, phase, checkpoint, tool, steering event: 구현 완료
- Full REST projection snapshot과 browser automatic resync: 구현 완료
- Phase-oriented workspace와 safe-point/immediate steering: 구현 완료
- Durable fake loop와 crash-resume tool idempotency: 구현 완료
- PostgreSQL atomic phase/checkpoint commit: 구현 완료
- Execution lease, fencing token, expired steering recovery: 구현 완료
- Durable instruction restore and fenced tool claim: 구현 완료
- PostgreSQL fault/concurrency integration suite: 구현 완료 (CI에서
  `CODING_TEST_DATABASE_URL` 설정 필요)
- Development supervisor notification + PostgreSQL reconciliation: 구현 완료
- Automatic fake-loop task startup and restart recovery: 구현 완료
- Atomic run/task start, completion, and failure lifecycle: 구현 완료
- Production Celery coding queue, post-commit dispatch, and DB reconciliation: 구현 완료
- At-least-once delivery with canonical run/lease/checkpoint recovery: 구현 완료
- Real model adapter and sandbox command/file/git execution: 다음 vertical slice로 이관
- Permission and approval execution: 다음 vertical slice로 이관

### Phase 1 — Docker sandbox와 sidecar

**목표:** 로컬에서 실제 repository와 명령을 안전한 개발용 container 안에서 조작.

- `SandboxProvider`와 conformance suite 우선 작성
- Docker provider, image digest, resource limit, cleanup 구현
- sidecar file/search/git/process/watch/health 구현
- workspace tree/content/diff REST와 terminal WS command 연결
- security baseline과 adversarial path/command tests 작성

**완료 조건:** fake agent sequence가 repo를 clone/read/edit/test하고 UI diff/terminal에 반영된다.

### Phase 2 — 단일 agent coding loop

**목표:** provider-neutral 모델 stream과 tool loop를 실제 sandbox에 연결.

- canonical transcript와 `CodingModel` adapter
- stable tool registry, executor partition, tool result artifact화
- context bootstrap, instruction discovery, budget와 compact
- checkpoint/resume와 Celery coding queue
- text/reasoning/tool-input delta를 domain event로 변환

**완료 조건:** 대표 Python/TypeScript fixture repository에서 bugfix task를 완주하고 테스트 결과를 보고한다.

### Phase 3 — 권한과 사용자 제어

**목표:** production에 필요한 human-in-the-loop와 제어면 완성.

- tool-level permission evaluator와 shell parser
- approval DB/API/UI, hash binding, expiry와 allow-once/session rule
- queue/steer follow-up, pause/resume/cancel/retry
- Stop/PreToolUse/PostToolUse hook
- cancel propagation과 orphan reaper

**완료 조건:** 재접속을 포함한 승인 흐름과 모든 cancellation race integration test가 통과한다.

### Phase 4 — Workspace UX와 스트리밍 최적화

**목표:** 장시간 task를 읽고 검토하기 좋은 Code 제품 경험.

- part map + frame-batched accumulator
- memoized markdown blocks, sticky prompt turns, tool renderer registry
- resizable file/diff/terminal/todo sidebar
- watcher-driven cache invalidation, revision/ETag conflict 표시
- scroll, keyboard, accessibility, mobile sheet
- stream coalescing, slow consumer, 10k event performance test

**완료 조건:** 30분/10k event fixture에서 입력·스크롤이 유지되고 reconnect 결과가 동일하다.

#### Frame-batched projection checkpoint (2026-07-21)

Phase 4의 스트리밍 성능 기반으로 browser projection store는 상태를 두 층으로 관리한다. `workingState`는 contiguous event마다 즉시 reduce되어 `appliedSeq`와 gap 판정의 정확성을 유지한다. React의 `useSyncExternalStore`가 읽는 `publishedState`는 animation frame마다 최신 working state로 한 번만 교체된다. 같은 frame에 10,000개 event가 들어와도 scheduler 요청과 subscriber notification은 각각 한 번이다.

다음 경계는 frame을 기다리지 않고 즉시 publish한다.

- REST snapshot 교체
- sequence gap 감지
- `caught_up`에 따른 connection basis 변경
- 명시적 `flush()`
- store `dispose()`에 따른 예약 취소

각 예약 callback은 단조 증가 generation을 캡처한다. snapshot 교체, gap, flush, dispose가 기존 frame을 취소하면 generation도 전진하므로 scheduler가 취소된 callback을 뒤늦게 호출해도 최신 snapshot을 덮어쓸 수 없다. duplicate event는 working state reference를 바꾸지 않아 frame을 예약하거나 subscriber를 호출하지 않는다.

`useCodingStream()`의 미사용 legacy React reducer도 hot path에서 제거했다. durable cursor와 local storage는 event마다 즉시 전진하지만 화면 render는 frame-batched projection publish에만 반응한다. 순수 legacy reducer는 기존 격리 테스트 호환성을 위해 남겨 둔다.

CI의 10k acceptance fixture는 wall-clock 시간 대신 scheduler 1회, notification 1회, direct reducer replay와 최종 projection deep equality를 검증한다. snapshot + batched live tail도 uninterrupted replay와 동일해야 한다. 이 변경은 backend/event/REST/WebSocket 계약을 바꾸지 않으므로 rollback은 projection store의 immediate publish 복원만으로 가능하며 데이터 migration은 필요 없다.

### Phase 5 — Managed sandbox pilot

**목표:** production multi-tenant 실행환경을 선택하고 제한된 사용자에게 개방.

- E2B/Modal/Daytona 후보 adapter 또는 최소 2개 benchmark adapter 작성
- 공통 conformance/security/performance/cost report 작성
- 선택 provider의 region, secret, snapshot, quota, incident runbook 구현
- provider outage 시 새 task 차단, 기존 task 상태 표면화, 복구 절차 구현
- allowlisted repository/organization 대상 canary

**완료 조건:** security review, provider exit plan, task cleanup SLO, canary error budget 충족.

### Phase 6 — 운영 강화와 Git workflow

**목표:** 팀 사용과 production 운영.

- GitHub App credential broker, branch/commit provenance
- push/PR snapshot card와 명시적 승인
- usage quota/billing/admin kill switch/audit export
- sandbox image supply-chain scan과 patch rotation
- optional repo index, memory, semantic search

**완료 조건:** tenant별 quota/감사/삭제 요구와 GitHub end-to-end flow가 검증된다.

### Phase 7 — 후속: coordinator

단일 agent 지표가 안정된 뒤에만 읽기 전용 조사 subagent부터 시작한다. write worker는 worktree/branch 격리와 merge conflict protocol 없이는 허용하지 않는다.

---

## 15. 구현 순서상 의존성과 커밋 단위

```text
event schema/store
  → task service/API
  → WS replay/live
  → frontend reducer/shell
  → sandbox port/conformance
  → Docker sidecar
  → tools/executor
  → model loop/checkpoint
  → permission/approval
  → workspace UX
  → managed provider
```

각 화살표를 하나의 거대한 PR로 만들지 않는다. 권장 PR 경계는 다음과 같다.

1. coding domain + DB + repository
2. task REST + durable event/outbox
3. WS gateway + reducer/reconnect UI
4. sandbox protocol + Docker sidecar
5. file/search/git/command tools
6. coding loop + fake/real model adapter
7. checkpoint/Celery resume
8. permission/approval/control
9. Code workspace UI/performance
10. managed sandbox evaluation/adapter

각 PR은 실패 테스트 → 최소 구현 → 통합 테스트 → 문서/metric 순서로 진행하고, 일반 chat regression suite를 함께 실행한다.

---

## 16. 주요 의사결정과 재검토 시점

| 결정 | 시작값 | 재검토 조건 |
|---|---|---|
| WebSocket + REST replay | coding 전용 | 일반 chat도 background task화될 때 transport 통합 검토 |
| PostgreSQL event source of truth | 채택 | event 규모가 DB 유지비/SLO를 위협할 때 Kafka/전용 log 검토 |
| Celery worker | 기존 기반 재사용 | lease/resume/장시간 task 운용이 복잡해지면 Temporal 등 durable workflow 검토 |
| Docker | 개발 전용 | production multi-tenant에는 사용하지 않음 |
| Managed sandbox | pilot 권장 | volume·region·비용·보안 요구 미충족 시 K8s 선행 |
| read-only workspace editor | MVP | user edit와 agent edit 충돌 모델 설계 후 writable editor |
| single agent | MVP | 성공률·resume·비용 지표 안정 후 coordinator |
| semantic indexing | 후순위 | `rg` 기반 성공률/latency가 목표 미달일 때 도입 |

---

## 17. 외부 근거

- Shadow 상세 설계: https://www.ishaand.com/shadow
  - stateful backend와 task별 stream processor
  - DB history + current stream-state + incremental WebSocket chunk
  - chunk ID map, tool input delta의 부분 JSON 파싱
  - filesystem watcher, file tree/editor/xterm, sticky user message, resizable workspace
- Modal Sandboxes: https://modal.com/docs/guide/sandboxes
- Modal VM Sandboxes: https://modal.com/docs/guide/vm-sandboxes
- Daytona Sandboxes: https://www.daytona.io/docs/en/sandboxes/
- E2B secure sandbox access: https://changelog.e2b.dev/docs/sandbox/secured-access
- gVisor Kubernetes integration: https://gvisor.dev/docs/user_guide/quick_start/kubernetes/

외부 제품의 기능·가격·격리 보장은 변경될 수 있으므로 Phase 5 시작 시 공식 문서와 계약 조건을 다시 확인한다.

---

## 18. 최종 판단

NEOS Coding은 기존 chat의 새로운 prompt mode가 아니라 **durable task product**로 구현해야 한다. 가장 중요한 기반은 더 화려한 editor가 아니라 다음 네 가지다.

1. task lifecycle과 append-only event log
2. checkpoint/resume 가능한 provider-neutral coding loop
3. 교체 가능한 sandbox와 강제되는 권한 경계
4. snapshot/replay/live를 동일하게 축약하는 프론트 event reducer

이 네 축을 Phase 0–3에서 먼저 완성하면 Shadow 수준의 실시간 UX를 안정적으로 얹을 수 있고, sandbox provider·모델·Git provider·향후 coordinator를 교체하거나 추가해도 제품의 중심 계약은 유지된다.

---

## 19. Sandbox foundation 구현 현황과 검증

2026-07-19 기준으로 provider-neutral sandbox foundation이 `dev` 브랜치에 구현되어 있다.

### 19.1 구현된 모듈

| 영역 | 구현 |
|---|---|
| 계약 | `neos/coding/sandbox/base.py`: lifecycle, file/search/git/command, snapshot, PTY, watcher protocol |
| 경로 정책 | `paths.py`: POSIX 상대 경로, traversal/symlink escape, Git 보호 경로 차단 |
| 스트림 | `streams.py`: bounded replay, monotonic cursor, replay gap |
| Memory provider | 실제 process group, portable snapshot, POSIX PTY, command 전후 filesystem reconciliation |
| Docker provider | 제한된 container/volume lifecycle, readiness, 보상 정리, snapshot/restore, PTY, watcher, restart rediscovery |
| 설정/runtime | nested strict config, provider factory, `CodingRuntime` shutdown ownership |
| 관측성 | bounded-label Prometheus metric과 content-free audit metadata |

Memory provider는 개발과 provider 계약 검증을 위한 실행 가능한 reference adapter다. Docker provider는 로컬 개발용이며 production multi-tenant 보안 경계로 간주하지 않는다.

### 19.2 기본 설정

기본 profile은 sandbox를 비활성화하고 provider를 `memory`로 둔다. 활성화 시 주요 설정은 다음과 같다.

```yaml
sandbox:
  enabled: true
  provider: memory
  lifecycle:
    create_timeout_sec: 30
    idle_timeout_sec: 900
    max_lifetime_sec: 14400
  resources:
    cpu_count: 1.0
    memory_bytes: 536870912
    pids: 128
    workspace_bytes: 1073741824
  execution:
    command_timeout_sec: 30
    max_output_bytes: 1048576
    max_stdin_bytes: 1048576
```

production에서 `provider: docker`를 선택하면 image는 `name@sha256:<digest>` 형식이어야 하고, network는 `none`, user는 non-root여야 한다. unsafe 값은 애플리케이션 시작 시 Pydantic validation error로 거부된다.

### 19.3 테스트 명령

Docker daemon 없이 reference provider와 scripted Docker boundary를 검증한다.

```bash
.venv/bin/pytest -q tests/coding/sandbox/test_memory_conformance.py
.venv/bin/pytest -q \
  tests/coding/sandbox/test_docker_command.py \
  tests/coding/sandbox/test_docker_provider.py \
  tests/coding/sandbox/test_docker_failures.py \
  tests/coding/sandbox/test_docker_pty.py \
  tests/coding/sandbox/test_docker_watcher.py
```

실제 Docker conformance는 명시적으로 opt-in한다. image에는 Python 3, Git, `/bin/sh`가 있어야 하며 UID/GID `10001:10001`이 `/workspace` volume을 사용할 수 있어야 한다.

```bash
CODING_TEST_DOCKER=1 \
CODING_TEST_DOCKER_IMAGE='registry/neos-sandbox@sha256:<digest>' \
.venv/bin/pytest -q tests/coding/integration/test_docker_sandbox.py -rs
```

Docker CLI, opt-in flag, digest image 중 하나라도 없으면 suite는 설치·설정 방법을 포함한 이유와 함께 skip한다.

### 19.4 현재 제한과 다음 경계

- Docker stdout/stderr capture는 bounded이며 truncation을 명시적으로 보고한다. 대용량 snapshot은 streaming object store adapter가 추가되기 전까지 설정 상한 내에서만 허용한다.
- watcher는 session write와 watcher가 열린 상태의 command 전후 fingerprint를 reconcile한다. sandbox 밖에서 발생한 장기 background 변경의 polling/sidecar push는 후속 sidecar 단계다.
- rediscovery는 NEOS label, sandbox ID, owner, container 이름을 재검증한다. distributed lease와 absolute TTL reaper는 persistence/control-plane wiring 단계에서 추가한다.
- browser는 Docker socket이나 PTY에 직접 연결하지 않는다. REST/WebSocket gateway가 sandbox session을 소유하고 cursor/revision을 클라이언트 event로 변환해야 한다.

---

## 20. Real model loop 운영과 복구

### 20.1 설정과 기본 안전 정책

real loop는 coding model과 sandbox가 모두 명시적으로 활성화된 환경에서만 사용한다. 모델 이름, turn/tool/token/cost 한도, model/tool timeout, transcript byte 한도, mutation snapshot cadence를 설정하고 Anthropic 키는 secret source로만 주입한다. 등록된 tool schema 밖의 입력은 거부하며 command는 `argv` 단위 allowlist, workspace 내부 `cwd`, 허용된 env 이름, stdin/output/time 한도를 모두 통과해야 한다. shell substitution, redirection, pipe, 보호된 `.git` 경로와 workspace 탈출은 허용하지 않는다.

Docker sandbox는 digest-pinned image, non-root UID/GID, read-only root filesystem, capability drop, resource/PID 한도와 `network=none`을 유지한다. package registry나 repository egress가 필요해도 기본 네트워크 격리를 해제하지 않고 별도의 승인된 provider/network policy로 제공한다. Memory provider는 deterministic 개발·테스트 adapter이며 production 다중 tenant 경계가 아니다.

### 20.2 one-safe-point scheduling

worker delivery 한 번은 최신 durable checkpoint에서 정확히 한 safe point만 전진한다. model-only completion 또는 tool 하나의 durable result와 phase checkpoint가 safe point다. 매 호출마다 iterator와 sandbox binding을 다시 구성하므로 브라우저나 worker process 수명에 의존하지 않는다. 동일 task의 execution lease는 fencing token을 포함한다. worker의 binding 생성·run 재결합·복원·workspace revision/snapshot bookkeeping CAS는 `coding_run_leases`의 run, worker, fencing token, 만료 시간을 같은 repository transaction에서 검증한다. 따라서 이전 token은 현재 binding version을 알고 있어도 tool result, checkpoint, steering 또는 binding 변경을 commit할 수 없다. 운영 lifecycle의 suspend/terminal destroy만 명시적인 `*_admin` API로 분리한다.

### 20.3 snapshot과 crash recovery

workspace mutation은 binding의 revision과 mutation count를 갱신하고 설정된 cadence에서 portable snapshot을 만든다. sandbox가 사라지면 호환되는 image digest와 checksum을 검증한 최신 snapshot으로 복원한다. durable tool completion 뒤 worker가 죽으면 replacement worker는 저장된 result를 재사용하고 mutation을 다시 실행하지 않는다. checkpoint 뒤에는 transcript, pending tool index, usage와 workspace revision부터 이어간다.

mutation 실행 뒤 durable completion 전 연결이 끊기면 outcome을 추측하거나 재실행하지 않고 run을 비재시도 오류 `tool_outcome_unknown`으로 중단한다. 운영자는 workspace diff/revision과 외부 부작용을 조사하고, 결과를 보존할지 snapshot에서 되돌릴지 결정한 뒤 새 task/run으로 재개한다. 자동 retry나 claim 삭제로 이 오류를 우회하면 안 된다.

### 20.4 관측성과 감사

Prometheus 지표는 다음 fixed-cardinality label만 사용한다.

| metric | labels |
|---|---|
| `coding_model_turn_total` | `provider`, `outcome` |
| `coding_tool_execution_total` | 등록된 `tool`, `outcome` |
| `coding_phase_duration_seconds` | `phase` |
| `coding_checkpoint_total` | `phase` |
| `coding_resume_total` | `outcome` |
| `coding_lease_contention_total` | `outcome` |
| `coding_sandbox_operation_total` | `provider`, `operation`, `outcome`, stable `error_code` |

model 문자열, task/run/tool-call/sandbox ID, path, argv, prompt, file/stdin/stdout 내용, secret 값은 metric label에 넣지 않는다. real loop는 injected audit sink에 validation `allowed/denied`와 execution `ok/error/reused`를 직접 보낸다. production runtime은 logging observability sink를 주입한다. audit event는 provider, 등록 tool, fixed operation/outcome과 allowlist의 stable error code만 기록하며 알 수 없는 error code는 `other`로 정규화한다. path, argv, env 값, prompt와 file/stdin/stdout 내용은 기록하지 않는다.

### 20.5 검증과 opt-in network smoke

Memory vertical slice와 crash recovery suite는 기본 CI에서 network 없이 실행한다. 실제 Anthropic smoke는 읽기 전용 one-turn/low-token 요청이며 아래 두 조건을 **모두** 만족할 때만 실행된다.

```bash
NEOS_RUN_ANTHROPIC_INTEGRATION=1 \
ANTHROPIC_API_KEY='<secret source>' \
.venv/bin/pytest tests/coding/integration/test_anthropic_opt_in.py -q -rs
```

두 변수 중 하나라도 없으면 명시적 이유로 skip하며 default CI는 외부 요청을 만들지 않는다. Postgres와 Docker integration도 기존 명시적 opt-in guard만 사용한다.

### 20.6 rollback과 설계 범위

장애 시 `CODING_MODEL_ENABLED=false`로 real model loop 등록을 중단하고 development의 `FakeDurableCodingLoop`로 rollback한다. 기존 checkpoint/event schema와 migration은 되돌리지 않아 이전 durable data를 읽을 수 있게 한다.

`2026-07-19-real-model-sandbox-tool-loop-design.md`의 1–11절은 Tasks 1–8에서 model contract, registry/policy, durable claim/checkpoint/fencing, sandbox binding/snapshot, bounded transcript/result, normalized errors/config, observability와 deterministic verification으로 반영했다. 12절 delivery sequence의 production provider rollout, multi-agent coordinator, 일반 egress, approval UI, semantic indexing과 managed/Kubernetes sandbox는 의도적으로 후속 단계로 남긴다. provider별 prompt caching과 장기 artifact/object-storage retention도 현재 Memory/Docker vertical slice 밖의 운영 작업이다.

---

## 21. Durable tool approval 운영 계약

### 21.1 실행 정책과 원자적 정지

`read_file.v1`, 검색, 목록 조회 같은 read-only 도구는 기존 validation을 통과하면 바로 실행한다. `write_file.v1` 계열 workspace mutation과 `execute.v1` command는 validation 이후, tool claim 이전에 승인을 요구한다. hard-deny된 입력은 승인으로 우회할 수 없다.

승인 요청 transaction은 checkpoint, `coding_approvals` 행, task의 `waiting_approval` 전이, `approval.requested`/`task.status.changed` event와 outbox를 함께 commit한다. 동일 `(task_id, run_id, tool_call_id)` 재전달은 같은 요청을 재사용한다. 승인 전에는 tool execution claim이 존재하지 않으며 sandbox mutation도 발생하지 않는다.

결정 transaction은 승인·task·canonical run/checkpoint를 잠그고 `coding-approval-v1` request hash와 workspace revision을 다시 확인한다. 만료가 사용자 결정보다 우선하며 불일치는 `invalidated`로 닫힌다. 결정 event와 task의 `running` 전이를 commit한 뒤에만 checkpoint ID가 포함된 worker delivery를 발행한다. replacement worker는 기존 exactly-once claim 경로로 실행한다.

### 21.2 설정과 만료 회수

```yaml
coding_model:
  approval_ttl_seconds: 900
  approval_reconciliation_batch_size: 100
```

TTL과 batch size는 양수이며 batch는 최대 1000이다. Celery Beat의 `expire-coding-approvals` task는 coding reconciliation 주기로 실행되고, `FOR UPDATE SKIP LOCKED`로 만료된 pending 요청을 제한된 batch만 claim한다. 각 요청을 `expired`로 전이한 뒤 commit 후 wake-up한다. 동시에 여러 beat/worker가 실행되어도 같은 요청은 한 번만 전이된다.

### 21.3 REST, snapshot, event 계약

결정 endpoint는 다음과 같다.

```http
POST /api/v1/coding/tasks/{task_id}/approvals/{approval_id}
Content-Type: application/json

{"decision":"approve"}
```

decision은 `approve` 또는 `deny`만 허용한다. 소유하지 않은 task/approval은 존재 여부를 숨기는 `404`, 이미 처리됨·만료·무효화·stale 상태는 정제된 `409`, schema 오류는 `422`다. 성공 응답과 task snapshot의 approval 항목은 `approval_id`, `tool_name`, bounded `risk/status`, `requested_at`, `expires_at`, allowlisted `display_summary`만 포함한다.

이벤트는 `approval.requested`, `approval.approved`, `approval.denied`, `approval.expired`, `approval.invalidated`와 이어지는 `task.status.changed`를 사용한다. 이벤트와 공개 snapshot에는 request hash, actor ID, normalized input, checkpoint loop state, file content, full argv, stdin 또는 env 값이 없다. 브라우저는 snapshot과 live/replay event를 같은 `approvalsById` projection으로 reduce하며 REST 성공만으로 optimistic 제거하지 않는다.

### 21.4 브라우저 동작과 장애 모드

승인 카드는 phase timeline과 steer composer 사이에 나타난다. 복구된 checkpoint에서도 요청 내용을 볼 수 있지만 approve/deny 버튼은 WebSocket 상태가 `live`이고 요청 상태가 `pending`일 때만 활성화된다. 각 카드는 독립적인 submitting/error 상태를 가지며, 결정 후 실제 상태 변경은 durable event 또는 새 snapshot으로만 반영한다.

- 결정 commit 후 broker publish가 불확실하면 coding reconciliation이 현재 checkpoint generation을 다시 전달한다.
- 승인 요청 중 browser/worker가 종료되어도 pending 행과 checkpoint가 복구 기준이다.
- 승인 후 worker가 중복 전달되면 tool claim/result 재사용이 mutation 중복을 막는다.
- mutation 실행 후 durable completion 전 장애는 승인 여부와 무관하게 `tool_outcome_unknown`으로 fail closed한다.
- 만료/거절/무효화는 canonical denied tool result를 transcript에 남기며 도구를 실행하지 않는다.

### 21.5 관측성, rollout, rollback

`coding_approval_total{risk,outcome}`과 `coding_approval_latency_seconds{outcome}`만 사용한다. risk와 outcome은 enum의 fixed-cardinality 값이다. 승인 audit event는 등록 tool과 bounded risk/outcome만 기록하며 task/approval ID, 입력 내용과 actor는 기록하지 않는다.

rollout 순서는 migration `042` 적용 → API/worker 배포 → Beat 활성화 → browser 배포다. 구버전 browser는 `waiting_approval` task를 실행시키지 못할 뿐 mutation을 우회하지 않는다. rollback은 model/worker 기능을 비활성화하되 migration과 pending 행을 보존한다. 기능이 꺼진 동안 pending 승인은 자동 승인하거나 실행하지 않는다. 다시 활성화하면 만료 reconciliation 또는 명시적 사용자 결정으로만 이어간다.
