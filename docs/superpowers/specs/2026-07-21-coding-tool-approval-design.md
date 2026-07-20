# Coding Tool Approval Vertical Slice Design

## 1. 목적

NEOS Coding의 실제 모델 tool loop에 reconnect-safe human approval을 추가한다.
기존 hard-deny 정책은 그대로 유지하며, 정책 검사를 통과한
`workspace_write`와 `command` tool call만 정확한 호출 단위 승인을 요구한다.

이번 범위의 완료 조건은 다음과 같다.

- 승인 전에는 mutation 또는 command가 실행되지 않는다.
- 승인된 호출은 crash, reconnect, at-least-once delivery 상황에서도 최대 한 번 실행된다.
- 거부된 호출은 run 실패가 아니라 canonical denied tool result가 되어 모델이 다른 방법을 선택할 수 있다.
- REST snapshot, WebSocket replay, live event를 처리한 UI 상태가 동일하게 수렴한다.
- 만료되거나 대상이 달라진 승인은 실행 권한으로 사용할 수 없다.

## 2. 범위

### 포함

- coding 전용 durable approval domain과 PostgreSQL 저장소
- tool risk 기반 `allow`, `deny`, `require_approval` evaluator
- approval request와 safe-point checkpoint의 atomic commit
- owner-scoped approve/deny REST API
- 승인 결정 이후 checkpoint-token 기반 worker wake-up
- 승인 requested/resolved/expired event와 snapshot projection
- coding workspace 승인 카드와 reconnect-safe reducer
- 만료 reconciliation, fixed-cardinality metrics, sanitized audit

### 제외

- allow-for-session 또는 repository-wide allowlist
- pause/resume/cancel/retry control plane
- Stop/PreToolUse/PostToolUse hook pipeline
- 일반 shell parser 또는 pipe/redirection 지원
- managed sandbox와 일반 egress 승인
- 다중 write agent와 coordinator

## 3. 기존 기반과 경계

다음 기존 기능을 재사용한다.

- `CodingToolRegistry`의 schema validation, hard-deny policy, `ToolRisk`
- `AnthropicCodingLoop`의 validation 이후, tool claim 이전 gate
- execution lease, fencing token, durable tool claim과 result reuse
- one-safe-point checkpoint와 Celery continuation token
- task-local monotonic event sequence, outbox, REST replay, WebSocket replay/live
- snapshot-first frontend hydration과 ordered projection reducer
- 기존 `Tool` 및 `Confirmation` UI primitive

legacy `pending_approvals`는 재사용하지 않는다. 이 테이블과 API는 LangGraph
session/SSE state에 결합되어 있으며 run, checkpoint, tool call, workspace revision,
canonical input hash를 안전하게 결합하지 못한다. Coding approval은 별도 aggregate와
source of truth를 가진다.

## 4. 승인 정책

승인 evaluator는 validation과 기존 hard-deny policy 이후에 실행된다.

| 조건 | 결정 |
|---|---|
| schema 또는 hard policy 위반 | `deny` |
| `ToolRisk.READ_ONLY` | `allow` |
| `ToolRisk.WORKSPACE_WRITE` | `require_approval` |
| `ToolRisk.COMMAND` | `require_approval` |

승인은 hard denial을 우회할 수 없다. 승인된 input도 재개 시 registry로 다시
검증하며, canonical hash와 workspace revision이 일치해야 한다.

## 5. Durable 데이터 모델

`coding_approvals`는 다음 필드를 가진다.

| 필드 | 의미 |
|---|---|
| `approval_id` | stable coding approval ID |
| `task_id` | 소유권과 event sequence의 task |
| `run_id` | 요청을 생성한 canonical run |
| `tool_call_id` | 모델의 stable tool call ID |
| `checkpoint_id` | pending tool call을 포함한 safe-point checkpoint |
| `tool_name` | versioned registered tool name |
| `risk` | `workspace_write` 또는 `command` |
| `workspace_revision` | 승인 요청 당시 revision |
| `request_hash` | canonical approval binding hash |
| `display_summary` | allowlisted field로 만든 sanitized 사용자 표시 정보 |
| `status` | `pending`, `approved`, `denied`, `expired`, `invalidated` |
| `requested_by` | task owner principal; agent가 이 owner를 대신해 요청 |
| `requested_at` | 요청 시각 |
| `expires_at` | 절대 만료 시각 |
| `decided_by` | 결정 principal, nullable |
| `decided_at` | 결정 시각, nullable |

`request_hash`는 versioned canonical serialization으로 계산한다. 최소 입력은
contract version, task ID, run ID, tool call ID, tool name, normalized input,
checkpoint ID, workspace revision이다. JSON key ordering과 separators를 고정하고
SHA-256을 사용한다. secret 또는 raw environment value를 추가해서는 안 된다.
정규화된 input 원문은 approval row에 중복 저장하지 않고 fenced checkpoint에서만
읽는다. `display_summary`는 tool별 allowlist formatter가 생성하며 environment,
stdin, file content를 포함하지 않는다.

제약 조건은 다음과 같다.

- `(task_id, run_id, tool_call_id)`는 유일하다.
- pending row만 approve/deny할 수 있다.
- status와 decision column 조합을 CHECK constraint로 검증한다.
- `expires_at > requested_at`이어야 한다.
- approval은 task와 run의 소유권을 바꾸지 않는다.

## 6. 요청 transaction

tool call이 `require_approval`이면 tool-execution claim을 만들기 전에 하나의
fenced repository command가 다음 변경을 원자적으로 수행한다.

1. execution lease와 canonical run을 검증한다.
2. pending tool call을 transcript/loop state에 포함한 checkpoint를 생성한다.
3. 동일 tool call의 approval을 insert하거나 기존 동일 요청을 반환한다.
4. task를 `waiting_approval`로 전이한다.
5. `approval.requested`와 `task.status.changed` event를 append한다.
6. 두 event의 outbox row를 insert한다.

commit 후 worker는 execution lease를 해제하고 `WAITING_APPROVAL` outcome을
반환한다. 이 outcome은 retry failure가 아니며 automatic continuation을 발행하지
않는다.

## 7. 결정 API와 transaction

Endpoint:

```http
POST /coding/tasks/{task_id}/approvals/{approval_id}
Content-Type: application/json

{"decision":"approve"}
```

`decision`은 `approve` 또는 `deny`만 허용한다. API는 기존 coding owner
dependency를 사용한다.

결정 transaction은 approval row를 `FOR UPDATE`로 잠그고 다음 순서를 지킨다.

1. task owner, approval/task 관계, pending status를 검증한다.
2. `expires_at <= now`이면 `expired`로 전이하고 승인 결정을 거부한다.
3. canonical run/checkpoint/tool payload로 request hash를 재계산한다.
4. hash 또는 workspace revision이 다르면 `invalidated`로 전이한다.
5. approve/deny decision과 actor/time을 기록한다.
6. task를 `running`으로 전이한다.
7. `approval.approved`, `approval.denied`, `approval.expired`, 또는
   `approval.invalidated` event와 outbox를 기록한다.

approve/deny 경쟁에서는 먼저 row lock을 획득한 pending decision만 성공한다.
후속 요청은 `409 Conflict`다. 동일 decision의 중복 제출도 stale UI를 숨기지
않도록 `409`로 응답한다. 만료는 항상 사용자 결정보다 우선한다.

commit 이후 approve와 deny 모두 approval checkpoint token으로 worker를 깨운다.
broker publish가 모호하면 기존 DB reconciliation이 recovery source가 된다.

## 8. Loop 재개

checkpoint의 pending tool call을 재개할 때 loop는 durable approval을 조회한다.

- `pending`: 실행하지 않고 `WAITING_APPROVAL`을 유지한다.
- `approved`: hash/revision을 재검증한 뒤 기존 durable tool claim/execution 경로로 진입한다.
- `denied`: canonical denied `ToolResultContent`와 checkpoint를 commit하고 다음 model turn으로 진행한다.
- `expired` 또는 `invalidated`: denied와 동일하게 안전한 canonical result를 제공하되 stable reason code를 구분한다.

승인 뒤 mutation 실행과 durable result commit 사이의 outcome이 불명확하면 기존
`tool_outcome_unknown` fail-closed 정책을 유지한다. approval을 근거로 자동
재실행하지 않는다.

## 9. Event와 projection 계약

추가 event type:

- `approval.requested`
- `approval.approved`
- `approval.denied`
- `approval.expired`
- `approval.invalidated`

event payload는 approval ID, registered tool name, risk, status, requested/expiry
timestamp, sanitized display summary만 포함한다. raw input, path, argv, environment,
prompt, file content, credential은 event에 넣지 않는다.

snapshot은 legacy approval projection 대신 `coding_approvals`를 읽는다. frontend의
`CodingApprovalView`는 request ID, tool name, risk, status, requested/expiry time,
sanitized summary를 typed field로 가진다. REST snapshot과 live reducer는 동일한
key (`approval_id`)와 동일한 resolution 규칙을 사용한다.

`task.status.changed`도 coding projection reducer에 적용하여 snapshot 이후
`waiting_approval` 상태가 workspace header에 즉시 반영되게 한다.

## 10. Frontend UX

승인 카드는 coding workspace의 steer composer 위에 표시한다.

- tool name, risk, sanitized argument summary, expiry time을 보여준다.
- approve와 deny는 request별 pending/error state를 가진다.
- stream이 `live`가 아니거나 요청이 pending이 아니거나 제출 중이면 버튼을 비활성화한다.
- API 성공 직후 optimistic removal을 하지 않는다.
- durable resolution event 또는 새 snapshot이 카드를 제거/종료 상태로 바꾼다.
- `waiting_approval`은 task header와 phase timeline에 표시한다.

기존 chat approval handler와 UI는 interaction reference로만 사용한다. Coding API와
types는 session/LangGraph contract를 import하지 않는다.

## 11. 만료와 reconciliation

기본 approval TTL은 strict configuration의 15분이다. API transaction은 현재
시각을 직접 검사하므로 expiry worker 지연이 실행 권한으로 이어지지 않는다.

reconciliation worker는 제한된 batch로 만료된 pending approval을 잠그고
`expired` 전이, task wake-up, event/outbox 기록을 수행한다. 여러 worker는
`FOR UPDATE SKIP LOCKED` 또는 동등한 claim 방식으로 같은 row를 중복 처리하지
않는다. 만료된 요청을 처리한 worker는 denied/expired tool result를 생성하도록
기존 continuation funnel을 사용한다.

## 12. 관측성과 감사

metrics는 fixed-cardinality label만 사용한다.

- `coding_approval_total{risk,outcome}`
- `coding_approval_latency_seconds{outcome}`

허용 label 값은 registered risk와 stable outcome 집합으로 제한한다. task/run/tool
call/approval/user ID, tool input, path, argv는 label에 넣지 않는다.

audit sink에는 validation decision과 approval lifecycle outcome을 기록한다. audit
metadata에도 sanitized stable code만 허용하며 raw operation input은 기록하지 않는다.

## 13. 오류와 HTTP 의미

- 잘못된 decision/schema: `422`
- task 또는 approval을 소유하지 않거나 존재하지 않음: 정보 노출을 막기 위해 `404`
- 이미 결정됨, canonical run 변경, stale request: `409`
- 만료: transaction에서 상태를 `expired`로 commit한 뒤 `409`
- DB/broker infrastructure failure: sanitized `5xx`; DB commit 전에는 아무 wake-up도 발행하지 않음

## 14. 검증 전략

### Domain/policy

- read-only allow, mutation/command require approval, hard-deny precedence
- canonical hash determinism과 field sensitivity
- invalid status transitions

### Repository/application

- approval, checkpoint, task status, event, outbox atomicity
- duplicate tool call request reuse
- concurrent approve/deny single winner
- expiry precedence와 invalidation
- owner isolation

### Loop/worker

- approval 전 sandbox 미실행
- approved mutation exactly-once claim/execution
- denied/expired canonical tool result
- crash after request commit and after decision commit recovery
- stale checkpoint token과 stale lease fencing

### Frontend

- snapshot approval hydration
- requested/resolved/expired live reduction
- task status live reduction
- reconnect and replay convergence
- duplicate click, request error, non-live disabled state

### Regression

- complete `tests/coding` suite
- coding frontend source tests and TypeScript check
- general chat approval flow regression because legacy tables/routes remain unchanged

## 15. Rollout과 rollback

coding approval은 coding model feature flag 아래에서만 생성한다. 배포 순서는
migration, read projection, backend write/decision, worker consumption, frontend 순이다.
구버전 frontend도 snapshot의 추가 approval data를 무시할 수 있어야 한다.

rollback 시 새 approval 생성을 중단하고 pending approval task는 자동 실행하지
않는다. durable row와 event는 보존한다. 운영자는 feature 재활성화 또는 명시적
deny/expire reconciliation으로 안전하게 해소한다.
