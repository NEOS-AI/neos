# Coding Backend Durability Design

> 작성일: 2026-07-19
> 상태: 승인된 설계
> 선행 구현: `4e740e3 test: verify durable coding phase slice`

## 1. 목적

현재 durable fake loop의 in-memory vertical slice를 PostgreSQL에서도 안전하게
실행할 수 있는 내구성 경계로 확장한다. 이 설계의 핵심 불변식은 다음과 같다.

1. checkpoint를 참조하는 event가 보이면 해당 checkpoint도 반드시 존재한다.
2. phase 완료 event, checkpoint, phase 상태 변경은 전부 commit되거나 전부 rollback된다.
3. 한 task의 active run은 유효한 execution lease를 가진 worker 하나만 진행한다.
4. 만료된 worker는 fencing token 검증에 실패하여 후속 write를 수행할 수 없다.
5. worker가 언제 종료되더라도 steering 요청은 적용되거나 다시 claim할 수 있다.
6. 새 worker는 프로세스 메모리 없이 checkpoint만으로 instruction과 loop state를 복원한다.

## 2. 범위

### 포함

- PostgreSQL 원자적 safe-point commit
- in-memory repository의 동일 command 계약
- task별 execution lease와 fencing token
- steering claim lease와 만료 claim 복구
- safe-point steering의 원자적 run 전환
- immediate steering의 원자적 영속 상태 전환
- checkpoint의 canonical instruction 저장과 복원
- PostgreSQL repository 계약 및 fault-injection 테스트
- lease, recovery, checkpoint 관련 저카디널리티 metric 정정

### 제외

- task 생성 후 worker를 자동으로 기동하는 runtime supervisor
- Celery 또는 별도 coding worker queue
- 실제 model adapter와 sandbox tool 실행
- frontend reconnect fixture 개선
- 사용자 UI 변경

제외 항목은 이 설계 완료 후 다음 vertical slice에서 순차적으로 처리한다.

## 3. 선택한 접근

application service가 여러 CRUD repository 호출을 조합하지 않는다. 대신
`CodingDurabilityRepository`가 비즈니스 단위 command를 단일 DB transaction으로
수행한다. 서비스와 loop는 command input과 결과만 이해하며 SQLAlchemy session이나
SQL insert 순서를 알지 않는다.

이 방식은 FK만 deferred로 변경하는 것보다 강한 crash consistency를 제공하고,
application service 전체에 DB session을 전달하는 방식보다 저장소 경계를 명확하게
유지한다.

## 4. 데이터 모델

### 4.1 Execution lease

`coding_run_leases` 테이블을 추가한다.

| 필드 | 의미 |
|---|---|
| `task_id` | lease의 유일한 소유 범위, PK |
| `run_id` | lease가 진행할 active run |
| `worker_id` | 현재 lease owner |
| `fencing_token` | task별 단조 증가 정수 |
| `acquired_at` | 최초 획득 시각 |
| `expires_at` | lease 만료 시각 |
| `heartbeat_at` | 마지막 갱신 시각 |

획득 규칙:

- row가 없거나 `expires_at <= now`인 경우에만 획득한다.
- 재획득할 때 `fencing_token`을 반드시 증가시킨다.
- 동일 `worker_id`의 갱신은 token을 유지하고 만료 시각만 연장한다.
- 모든 phase/checkpoint/run 전환 command는 `task_id`, `run_id`,
  `worker_id`, `fencing_token`을 검증한다.
- token이 현재 row보다 작거나 owner가 다르면 `StaleExecutionLease`를 발생시킨다.

기본 lease TTL은 30초이며 heartbeat 권장 주기는 10초다. 값은 runtime 설정으로
주입하지만 repository command는 절대 시각을 전달받아 deterministic하게 테스트한다.

### 4.2 Steering claim lease

`coding_steering_requests`에 다음 필드를 추가한다.

- `claimed_by VARCHAR(128)`
- `claimed_at TIMESTAMPTZ`
- `claim_expires_at TIMESTAMPTZ`

claim 대상은 `pending` 또는 `claimed AND claim_expires_at <= now`인 요청이다.
재claim은 같은 steering row를 사용하며 새 요청을 만들지 않는다. 적용 완료 시 claim
필드를 유지해 audit 근거로 남기고 status만 `applied`로 변경한다.

### 4.3 Tool execution claim

`coding_tool_executions`는 실행 전 claim을 표현할 수 있도록 다음 필드를 추가한다.

- `worker_id VARCHAR(128)`
- `fencing_token BIGINT`
- `claimed_at TIMESTAMPTZ`
- `claim_expires_at TIMESTAMPTZ`

status는 `claimed`, `completed`, `failed`만 허용한다. 같은 `tool_call_id`의 claim이
만료되지 않았다면 다른 worker는 `busy` 결과를 받는다. 만료된 claim은 더 높은 현재
execution fencing token을 가진 worker만 재획득할 수 있다. `completed` row는 다시
claim하지 않고 저장된 result를 반환한다.

### 4.4 Canonical loop state

모든 checkpoint의 `loop_state_json`은 최소한 다음 필드를 가진다.

```json
{
  "phase_index": 0,
  "transcript": [],
  "current_instruction": "durable instruction",
  "pending_instruction": null
}
```

- `current_instruction`은 현재 run을 진행하는 canonical instruction이다.
- steering checkpoint에서는 새 instruction을 `current_instruction`과
  `pending_instruction`에 함께 저장한다.
- 새 run이 첫 phase를 완료하면 `pending_instruction`만 `null`로 바꾸고
  `current_instruction`은 유지한다.
- worker 재시작 시 메모리 cache보다 checkpoint 값을 우선한다.
- checkpoint가 없는 최초 run만 durable task prompt 또는 `run.started` command input을
  사용한다.

## 5. Repository command 계약

### 5.1 Lease command

```python
async def acquire_execution_lease(
    *, task_id: str, run_id: str, worker_id: str,
    now: datetime, expires_at: datetime,
) -> ExecutionLease | None: ...

async def renew_execution_lease(
    lease: ExecutionLease, *, now: datetime, expires_at: datetime
) -> ExecutionLease: ...

async def release_execution_lease(lease: ExecutionLease) -> None: ...
```

획득 실패는 정상 contention이므로 `None`을 반환한다. 갱신과 write에서 stale token은
예외로 구분한다.

### 5.2 Phase 시작

```python
async def begin_phase(
    *, lease: ExecutionLease, kind: CodingPhaseKind, now: datetime
) -> CodingPhase: ...
```

transaction 안에서 lease를 검증하고 `(task_id, phase_kind)`의 다음 attempt를 계산한 뒤
phase row와 `phase.started` event를 함께 저장한다. 동시에 실행된 두 worker가 같은
attempt를 선택하지 않도록 row/advisory lock을 사용한다.

동일 run에 `active` 상태인 phase가 이미 있으면 새 attempt를 만들거나
`phase.started`를 다시 발행하지 않고 기존 phase를 반환한다. 새 attempt는 이전 phase가
terminal 상태이고 loop가 해당 phase에 다시 진입할 때만 생성한다.

### 5.3 Tool result claim

```python
async def claim_tool_execution(
    *, lease: ExecutionLease, tool_call_id: str, now: datetime
) -> ToolExecutionClaim: ...

async def complete_tool_execution(
    claim: ToolExecutionClaim, *, result: Mapping[str, Any], now: datetime
) -> CodingEvent: ...
```

`claim_tool_execution`은 `claimed`, `completed`, `busy` 중 하나를 반환한다. 실제 side
effect는 `claimed`를 받은 worker만 수행한다. 완료된 결과는 그대로 재사용한다.
tool claim에도 worker와 fencing token을 저장해 만료 worker의 완료 write를 거부한다.

### 5.4 원자적 safe-point commit

```python
async def commit_phase_checkpoint(
    *, lease: ExecutionLease, phase: CodingPhase,
    tool_call_id: str, result: Mapping[str, Any],
    loop_state: Mapping[str, Any], workspace_revision: str,
    now: datetime,
) -> PhaseCheckpointCommit: ...
```

하나의 transaction에서 다음 순서로 처리한다.

1. lease와 fencing token 검증
2. task event sequence 잠금 및 다음 seq 할당
3. checkpoint insert
4. checkpoint ID를 포함한 `phase.completed` event와 outbox insert
5. phase status를 `completed`로 변경
6. task `last_seq`, `updated_at`, `last_activity_at` 갱신

checkpoint와 event가 같은 seq를 사용한다. FK는 transaction 내 checkpoint가 먼저
존재하므로 즉시 constraint를 유지할 수 있다. command가 성공한 뒤에만 checkpoint
metric을 증가시킨다.

### 5.5 원자적 steering 적용

```python
async def apply_steering_at_safe_point(
    *, lease: ExecutionLease, checkpoint: CodingCheckpoint,
    worker_id: str, claim_expires_at: datetime, now: datetime,
) -> SteeringApplication | None: ...
```

하나의 transaction에서 다음을 수행한다.

1. lease 검증
2. pending 또는 만료 claimed steering 한 건 claim
3. 새 event seq 할당
4. 새 instruction을 가진 steering checkpoint insert
5. `steer.applied` event와 outbox insert
6. steering status를 `applied`로 변경
7. 기존 run을 `cancelled`로 변경
8. attempt가 증가한 새 running run insert
9. execution lease의 run ID와 fencing token을 새 run으로 전환

새 run 전환 시 fencing token을 증가시킨다. 호출자는 반환된 새 lease와 run을 사용한다.

Immediate steering은 process interruption을 먼저 수행하되, process가 실제로 멈춘 뒤
동일한 원자 command로 interruption checkpoint와 run 전환을 commit한다. interruption
실패 시 run을 running으로 유지하고 steering을 pending 상태로 되돌릴 수 있어야 한다.

## 6. Event와 FK 정책

- `coding_events.checkpoint_id` FK는 유지한다.
- checkpoint를 참조하는 event는 반드시 atomic command에서 checkpoint insert 뒤에
  기록한다.
- checkpoint 없는 event에는 `checkpoint_id=NULL`을 사용한다.
- 기존 CRUD `append()` API로 checkpoint ID를 전달하는 것을 금지하고, 방어적으로
  `ValueError` 또는 전용 예외를 발생시킨다.
- phase completion, steering application, interruption에는 atomic command만 사용한다.

## 7. Application service 흐름

`CodingRunService.advance_one_safe_point()`는 다음 흐름을 따른다.

1. active run 조회
2. execution lease 획득; 실패하면 `RunAlreadyLeased` 반환
3. latest checkpoint에서 canonical instruction 복원
4. 현재 safe point에서 steering atomic command 시도
5. `begin_phase()`로 append-only phase 시작
6. durable tool claim 획득 후 tool 실행 또는 completed result 재사용
7. `commit_phase_checkpoint()` 호출
8. run이 끝나지 않았으면 lease 갱신, 끝났으면 run 완료와 lease release

서비스 인스턴스의 `_instructions`는 제거한다. worker ID는 runtime worker가 생성하고
서비스 호출에 명시적으로 전달한다.

## 8. 오류 처리와 복구

| 오류 지점 | 복구 결과 |
|---|---|
| phase 시작 transaction 전 crash | 아무 상태 변화 없음 |
| phase 시작 후 tool claim 전 crash | lease 만료 후 같은 active phase를 복구 |
| tool side effect 중 crash | tool별 reconciliation 필요; fake tool은 claim 만료 후 재시도 |
| tool result 완료 후 checkpoint 전 crash | completed result 재사용, tool side effect 중복 없음 |
| safe-point transaction 중 crash | 전체 rollback 또는 전체 commit |
| steering claim 직후 crash | claim lease 만료 후 다른 worker가 재claim |
| lease 만료 worker의 지연 write | fencing token 실패로 거부 |

실제 shell/file tool의 exactly-once side effect는 일반적으로 불가능하므로 다음 sandbox
slice에서 idempotency key와 workspace revision reconciliation을 추가한다. 이 설계는
중복 실행을 최소화하고 stale worker의 DB commit을 차단하는 범위까지 보장한다.

## 9. Metric 의미

- `coding_checkpoint_total{phase}`: atomic checkpoint commit 성공 후 한 번 증가
- `coding_phase_duration_seconds{phase}`: 최초 persisted phase start부터 commit까지
- `coding_steering_latency_seconds{outcome}`: requested부터 applied 또는 expired까지
- `coding_resume_total{outcome}`: 새 worker가 기존 active run의 lease를 획득해 복구를
  시도한 경우에만 증가
- `coding_lease_contention_total{outcome}`: acquired, busy, stale_write

label에는 고정된 phase와 outcome만 사용하며 task, run, worker, instruction은 포함하지
않는다.

## 10. 테스트 전략

### 10.1 Migration 계약

- execution lease와 steering claim 필드 존재
- 필요한 unique/index/FK 존재
- tool claim의 fencing 필드 존재

### 10.2 PostgreSQL repository 계약

- checkpoint insert가 completion event보다 먼저 같은 transaction에서 실행됨
- 중간 statement 실패 시 checkpoint, event, phase 상태가 전부 rollback됨
- stale fencing token write 거부
- 동시에 두 lease acquire 시 하나만 성공
- 만료된 lease 재획득 시 token 증가
- 만료 steering claim 재claim 가능
- safe steering 적용 결과가 checkpoint, event, run, steering에 동시에 반영

### 10.3 Application 통합

- 새 service/worker 인스턴스가 checkpoint instruction을 복원
- tool result 완료 직후 crash해도 실행 횟수 1회
- 두 worker가 동시에 advance해도 phase completion 1회
- steering 적용 중 fault injection 후 재claim하여 정상 완료
- five-phase 순서와 append-only attempt 유지

### 10.4 회귀

- owner가 아닌 사용자는 lease를 직접 획득할 API가 없음
- existing REST/WS snapshot과 replay 계약 유지
- metrics에 ID나 사용자 입력 label이 없음

## 11. 수용 기준

다음 조건을 모두 만족하면 backend durability slice가 완료된다.

1. 실제 PostgreSQL test transaction에서 첫 phase checkpoint가 FK 오류 없이 commit된다.
2. fault injection으로 atomic command 각 statement 경계를 실패시켜도 부분 상태가 없다.
3. 같은 task에서 유효한 execution lease는 하나뿐이다.
4. stale worker write가 fencing token으로 거부된다.
5. claimed steering은 worker crash 후 lease 만료를 거쳐 재적용된다.
6. 새 worker가 원래 instruction과 latest transcript를 checkpoint에서 복원한다.
7. 완료 tool result는 crash-resume 후 재실행하지 않는다.
8. backend coding regression suite가 모두 통과한다.

## 12. 후속 순서

이 설계 구현 완료 후 다음 순서로 진행한다.

1. feature flag 기반 development worker supervisor와 task 자동 시작
2. frontend uninterrupted-vs-restored convergence fixture 강화
3. metric dashboard와 recovery alert
4. real model adapter와 sandbox command vertical slice
