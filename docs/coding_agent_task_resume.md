# Coding Agent 작업 재개 문서

**작성일:** 2026-07-25 · **최종 정정:** 2026-08-16 (dev 병합·워크트리 제거 반영)
**작업 위치:** **`dev` 직접** — 워크트리는 제거됐다
**근거:** `docs/superpowers/plans/*coding*`, `*sandbox*`, `*durable*`, git 커밋 이력,
`.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/progress.md`

> ✅ **2026-08-16: 플랜14 Task 5까지 dev에 병합됐다** (`508dd275`). 마이그레이션 045가
> dev에 있고 **E-S1이 충족**됐다. 워크트리 `.worktrees/managed-sandbox-control-plane`은
> 제거했고 브랜치 `feature/managed-sandbox-control-plane`만 남아 있다.
> **아래 본문의 워크트리 경로는 당시 기록이며 지금은 존재하지 않는다** — 명령을 그대로
> 복사하지 말고 저장소 루트에서 실행할 것.
>
> SDD 원장 3종은 워크트리 제거 전에 `.superpowers/sdd/<plan>/`(저장소 루트)로 옮겨 뒀다.
> `.superpowers/`는 gitignore이므로 **커밋에는 없고 이 머신에만 있다.**

> ⚠️ **플랜 문서의 체크박스는 신뢰하지 말 것.** 전 플랜의 `- [x]`가 0개다.
> 실제 진행 상황은 git 커밋 메시지와 `.superpowers/sdd/<plan>/progress.md`에만 있다.

> 📌 **이 트랙은 이제 로드맵의 트랙 E다.**
> [DEEP_ANALYSIS_HARNESS_ROADMAP.md §12](DEEP_ANALYSIS_HARNESS_ROADMAP.md)가 요약·출하
> 기준(E-S1~E-S4)·미해결 인벤토리(CA1~CA7)를 갖고, 이 문서는 **상세 원장**으로 남는다.
> 충돌하면 실측 근거가 더 최신인 쪽이 이긴다.

---

## 1. 워크트리 현황

**2026-08-08 실측 (아래 원문은 2026-07-25 기준이며 절반이 낡았다):**

```
/Users/ywsung/Desktop/neos                                           d73cec44 [dev]
/Users/ywsung/Desktop/neos/.worktrees/managed-sandbox-control-plane  89196755 [feature/managed-sandbox-control-plane]
```

**남은 워크트리는 하나뿐이다.** `deep-analysis-entailment-eval`은 정리됐고,
`anthropic-caching-advisor`는 **디렉터리가 사라진 채 `prunable`로 남아 있다**(§5).

`managed-sandbox-control-plane` 상태:

| 항목 | 2026-07-25 (원문) | 2026-08-08 (실측) | 2026-08-14 (현재) |
|---|---|---|---|
| dev 대비 | +11 / **−17** | +11 / **−232** | `a9f37c6a`로 **합류 완료** (충돌 0건) |
| 미커밋 변경 | 2파일 | **2파일 그대로 — 2주째 미해결** | ✅ **종결** — CA5-b 구현으로 판정·채택 (`c7876999`) |
| `tests/coding` | — | — | **587 passed / 22 skipped** (`5aa31a22` 기준) |

> ⚠️ **위 22개 skip은 전부 `@pytest.mark.integration`이다.** `CODING_TEST_DATABASE_URL`이
> 설정되지 않아 **한 번도 실행되지 않았다** — 펜싱·클레임 상태 필터·CLEANED 컬럼
> 클리어링·조인 쿼리는 *발행되는 SQL과 바인드 파라미터*만 검증됐고 실제 Postgres에서는
> 미검증이다. **CHECK 제약 위반은 지금까지 실행된 어떤 테스트도 잡지 못한다.**
> 재개하는 사람이 가장 먼저 할 일은 DB를 붙이고
> `CODING_TEST_DATABASE_URL=... pytest -m integration tests/coding/managed`를 한 번 돌리는 것이다.

> 🔴 **−232라는 숫자에 겁먹지 말 것. 드리프트는 커밋 수가 아니라 공유 파일의 겹침으로 잰다.**
> 이 브랜치가 건드린 24파일 중 **19개가 신규 파일**(`neos/coding/managed/**` ·
> `tests/coding/managed/**` · `db/migrations/045`)이라 충돌 대상이 아니다.
> 045는 dev 최신이 044이므로 **번호 충돌도 없다.**
> 공유 파일은 5개이고 **그중 dev가 실제로 바꾼 것은 3개뿐이다:**
>
> | 파일 | dev 변화 | 워크트리 변화 | 충돌 |
> |---|---|---|---|
> | `neos/config/schema.py` | **26커밋** +311/−16 | 1커밋 +22/−0 | 🟡 가능 |
> | `config/neos.default.yaml` | 2커밋 +3/−5 | 1커밋 +19/−0 | 🟢 소규모 |
> | `neos/observability/metrics.py` | 1커밋 +10/−0 | 1커밋 +43/−0 | 🟢 순수 추가 |
> | `tests/coding/test_durability_metrics.py` | **0커밋** | 1커밋 | ⚪ 불가 |
> | `tests/config/test_sandbox_config.py` | **0커밋** | 1커밋 | ⚪ 불가 |
>
> **병합 비용의 지배 요인은 드리프트가 아니라 §4의 미커밋 변경 소유권이다.**

### 1.1 ⚠️ 정정 — "병합하면 `AgenticGrader`가 `TypeError`" (F3)는 틀렸다

`docs/TODO_260729.md` F3과 로드맵이 이 브랜치를 **병합 시점 폭발물**로 적었다.
근거는 워크트리에 `max_output_tokens` 없는 `AgenticGrader(...)` 호출부가 11곳
보인다는 것이었다. **실측 결과 그런 일은 일어나지 않는다.**

이 브랜치의 11커밋이 건드린 파일에 **`deep_analysis`는 0개**다. 즉
`service.py`와 `test_agentic_grader.py`는 브랜치가 손대지 않았고, rebase하면
**dev 버전이 그대로 온다.** 워크트리에서 보이던 11곳은 브랜치의 변경이 아니라
**2주 전 dev 파일의 낡은 사본**이며 rebase 순간 사라진다.

> **오독의 성격을 남겨둔다:** 워킹트리에서 *본 것*을 브랜치가 *바꾼 것*으로 착각했다.
> 워크트리 격리의 대가다 — **체크아웃 상태와 브랜치 변경을 눈으로 구분할 수 없다.**
> 다음에 같은 판정을 할 때는 `git diff --name-only $(git merge-base dev <브랜치>) <브랜치>`로
> **브랜치가 실제로 바꾼 파일만** 본다.

---

## 2. Coding Agent 트랙 전체 계보 (완료분)

2026-07-18 ~ 07-25, 14개 플랜. 각 단계는 **durable(내구성) 우선** 원칙으로 쌓였다 —
"프로세스가 죽어도 상태가 남고, 재접속하면 이어진다"가 일관된 목표다.

| # | 플랜 | 내용 | 상태 |
|---|---|---|---|
| 1 | `2026-07-18-neos-coding-phase0.md` | Phase 0 기반, 마이그레이션 038 | ✅ |
| 2 | `2026-07-18-coding-outbox-dispatcher.md` | outbox 디스패처 | ✅ |
| 3 | `2026-07-18-coding-production-streaming-hardening.md` | 프로덕션 스트리밍 경화 | ✅ |
| 4 | `2026-07-19-coding-backend-durability.md` | 내구성 계약, 워커·툴 클레임 펜싱, 원자적 체크포인트 (039) | ✅ |
| 5 | `2026-07-19-coding-development-supervisor.md` | 개발 슈퍼바이저, 태스크 자동 시작 | ✅ |
| 6 | `2026-07-19-coding-celery-worker.md` | Celery 워커 런타임 + 디스패처 + 관측 | ✅ |
| 7 | `2026-07-19-coding-sandbox-foundation.md` | 샌드박스 계약, Docker 스냅샷/재개, 보안 런타임 (040/041) | ✅ |
| 8 | `2026-07-19-durable-phase-vertical-slice.md` | durable phase 수직 슬라이스 | ✅ |
| 9 | `2026-07-19-real-model-sandbox-tool-loop.md` | 실 모델 런타임 + 한정 툴 실행 + 안전 한도 | ✅ |
| 10 | `2026-07-21-coding-tool-approval.md` | 내구성 툴 승인 — 안전 지점, 원자적 해결/만료, 재접속 안전 UI (042) | ✅ |
| 11 | `2026-07-21-coding-projection-frame-batching.md` | 프레임 단위 프로젝션 배칭 (10k 리플레이 검증) | ✅ |
| 12 | `2026-07-22-durable-coding-public-text-stream.md` | 펜스된 공개 텍스트 파트 영속화·스트림·브라우저 투영 (043) | ✅ |
| 13 | `2026-07-23-coding-workspace-gateway.md` | 워크스페이스 게이트웨이 8 tasks (044) | ✅ |
| 14 | `2026-07-25-managed-sandbox-control-plane.md` | 관리형 샌드박스 컨트롤 플레인 10 tasks (045) | 🔵 **진행 중** |

### 마이그레이션 궤적

```
038_add_coding_phase0.sql
039_add_coding_runs_checkpoints.sql
040_add_coding_execution_leases.sql
041_add_coding_sandbox_bindings.sql
042_add_coding_approvals.sql
043_add_coding_text_parts.sql
044_add_coding_workspace_edits.sql
045_add_coding_managed_sandboxes.sql   ← 현재 작업
```

### 직전 완료: Workspace Gateway (2026-07-23 ~ 07-25)

8개 태스크 전부 커밋됨 — 마지막 커밋 `ebe10721 test(coding): verify workspace gateway recovery`.

1. 내구성 워크스페이스 편집 도메인 + 설정 + 마이그레이션 044
2. 의도 기반 사용자 편집 변형 · 조정
3. 정확히 한 번 안전 지점 편집 주입
4. 소유자 스코프 워크스페이스 REST + 스냅샷 투영
5. kind 바인딩 watcher + 대화형 PTY WebSocket
6. 브라우저 워크스페이스 데이터 · 드래프트 · 스트림 스토어
7. 리사이즈 가능한 파일 · diff · 터미널 dock
8. Docker 수직 슬라이스 · 운영 · 전체 검증

### 2.1 그 이후 dev에서 일어난 일 (2026-08-08 추가)

워크트리가 멈춰 있는 동안 **dev의 코딩 트랙에도 커밋이 하나 들어왔다.**

| 커밋 | 내용 |
|---|---|
| `7f4beca1` | `_prepare_real_coding_loop()`가 `AnthropicCodingModel`을 `TrackedCodingModel`로 감싼다 (`neos/coding/runtime.py`) |

이것은 코딩 트랙의 작업이 아니라 **로드맵 트랙 D의 D1c**(데이터셋 콜렉터를 계측
사각지대까지 확장)가 지나가며 배선한 것이다. 코드 주석이 설계 의도를 명시한다:

- 계측은 **전송 계층 밖에서** 감싼다 → D4(네이티브 SDK 전환)가 그 아래를 바꿔도
  함께 무너지지 않는다
- 코딩 루프는 Celery 워커에서 도는데, **D1b 이후 레코드가 그 프로세스에서 바로
  디스크에 남으므로**(`neos/dataset/record_sink.py`) `graph.py` flush 지점을
  지나갈 필요가 없다

> ⚠️ **재개 시 이 배선을 깨지 말 것.** Task 5 이후 프로덕션 팩토리를 건드리게 되면
> (Task 10) `runtime.py`를 반드시 지나간다. 로드맵 **E-S4**가 이 배선의 유지를
> 출하 기준으로 고정하고 있다.

**dev 기준 검증 베이스라인 (2026-08-08 실측):** `tests/coding` **457 passed / 16 skipped**.

---

## 3. 🔵 진행 중 — Managed Sandbox Control Plane

**플랜:** `docs/superpowers/plans/2026-07-25-managed-sandbox-control-plane.md` (10 tasks, 1201줄)
**스펙:** `docs/superpowers/specs/2026-07-25-managed-sandbox-control-plane-design.md`
**베이스:** `c5f881a4` · **HEAD:** `89196755`

### 목표

기존 `SandboxProvider` / `SandboxSession`은 **실행 데이터 플레인**으로 남긴다.
별도 `neos.coding.managed` 패키지가 PostgreSQL 원장 · 애플리케이션 서비스 · Celery 조정자 ·
capability 인식 어댑터로 **admission · 할당 · 헬스 · 아카이브 복구 · 정리**를 소유한다.
브라우저는 한정된 소유자 스코프 투영만 받고, provider 참조나 raw 에러는 절대 받지 않는다.

### 핵심 설계 원칙 — 의도적 fail-closed

- 선택된 provider가 불가용이면 **신규 태스크 거부**
- 기존 태스크는 **동일 provider에서만** 재접속·복구
- **자동 크로스 프로바이더 failover 금지**
- 크로스 프로바이더 복구는 **검증된 portable 워크스페이스 아카이브에서 운영자 승인 시에만**

**Non-goals:** 자동 provider 선택/비용 최적화, 프로세스·메모리·PTY·소켓 라이브 마이그레이션,
멀티 에이전트 코디네이터, 일반 아웃바운드 네트워크, 과금 정산, GitHub App 크리덴셜/push/PR 생성,
provider 스냅샷을 벤더 간 portable로 취급하는 것.

### 태스크 진행 상황

| Task | 내용 | 상태 | 커밋 |
|---|---|---|---|
| 1 | 관리형 샌드박스 도메인 · 설정 · 마이그레이션 045 | ✅ 완료 (리뷰 clean) | `c5f881a4..777fdd33` |
| 2 | 내구성 admission · 쿼터 예약 | ✅ 완료 (리뷰 clean, minor 2건 유예) | `777fdd33..9245d5d5` |
| 3 | provider 헬스 서킷 · 안정적 에러 매핑 | ✅ 완료 (리뷰 clean) | `9245d5d5..3e3935f1` |
| 4 | capability 인식 어댑터 포트 · 결정론적 fake 어댑터 | ✅ 완료 | `3e3935f1..89196755` |
| 5 | 펜스된 할당 · 모호한 결과 복구 · 바인딩 | ⬜ **다음 차례** | — |
| 6 | 라이프사이클 조정 · 정리 SLO · Celery 전달 | ⬜ | — |
| 7 | portable 아카이브 · 운영자 승인 복구 | ⬜ | — |
| 8 | 소유자 투영 · 관리자 제어 API | ⬜ | — |
| 9 | 브라우저 샌드박스 상태 · 실행 게이팅 | ⬜ | — |
| 10 | E2B · Modal 벤치마크 어댑터 · 수직 슬라이스 · 운영 | ⬜ | — |

### 현재 코드 구조

```
neos/coding/managed/
├── __init__.py
├── domain.py            # ManagedSandboxState, ProviderCircuitState, transition_allocation (순수)
├── repository.py        # PostgreSQL 원장
├── admission.py         # AdmissionRequest, AdmissionPolicy, 쿼터 예약
├── health.py            # provider 헬스 서킷
└── adapters/
    ├── base.py          # ManagedSandboxAdapter 프로토콜, frozen 요청/결과 계약
    ├── fake.py          # 결정론적 fake + 타입 지정 1회성 결함 주입
    └── docker_shadow.py # Docker shadow 어댑터 ← 미커밋 변경 있음

tests/coding/managed/
├── test_domain.py, test_repository.py, test_admission.py, test_health.py
├── adapters/conformance.py, test_fake.py, test_docker_shadow.py
└── integration/test_postgres_admission.py

db/migrations/045_add_coding_managed_sandboxes.sql
```

### Task 1–4에서 내려진 범위 결정 (재개 시 반드시 지킬 것)

원장 `progress.md`에 기록된 결정들:

1. **`transition_allocation`은 순수 함수로 유지.** version/fence 검사는
   **Task 5의 repository claim/commit에서 필수**로 구현한다.
2. **provider NotFound 소유권 검증은 Task 6 cleanup 서비스에서 필수.**
3. **유예된 minor 2건 (Task 2):**
   - 트랜잭션 쿼터 거부가 admission denial TTL이 아니라 reservation lease에서 재평가 시점을 도출
   - 내구 `policy_version`이 `AdmissionPolicy.version` 영속화 대신 하드코딩
4. **유예된 minor 1건 (Task 1):** 마이그레이션이 reservation 타임스탬프/상태 대응을 강제하지 않음
   → **Task 2 repository 트랜잭션이 이를 유지해야 한다.**

### Task 4 완료 상태 (`89196755`)

- frozen 관리형 할당/결과 계약 + 정확한 async `ManagedSandboxAdapter` 프로토콜
- 타입 지정 validation / capability / ownership / not-found / timeout 실패
- 결정론적 fake: 1회성 결함 주입, 명시적 create-then-timeout 모호성, 멱등 재발견,
  호출 기록·카운터 (Task 5에서 사용)
- 공유 conformance 스위트: 할당 리플레이, 재발견, inspect, suspend/resume, 검증된 파괴
- Docker shadow 어댑터: 컨테이너·볼륨 생성에 allocation/idempotency/ownership 라벨 주입,
  inspect·destroy 전 Docker 메타데이터 검증, 데몬 헬스 프로브
- Docker는 network mode가 `none`일 때만 네트워크 차단을 선언. allowlist·메모리 스냅샷 미지원 →
  네트워크 정책을 약화시키는 대신 **요청 자체를 거부**
- **프로덕션 팩토리 배선은 의도적으로 미변경**

검증: `pytest -q tests/coding/managed/adapters` → **17 passed**, ruff check/format 통과.
테스트는 `no_db` 마킹, 외부 네트워크·Docker 데몬 불사용.

**Task 4가 남긴 우려 — 해소됨 (2026-08-11, CA5):**
- 현 Docker provider에 공개 관리형 라벨 확장점이 없어, shadow 어댑터가 커맨드 러너를 감싸고
  private 속성으로 config를 읽는다. shadow 어댑터에 격리되어 있고 프로덕션 팩토리에는 미배선.
  → **CA5-a로 해소** (`51a21fc4`..`0148d7fa`). `build_create_args`가 `extra_labels`
  파라미터를 얻어 `create_args.index("--user")` 포지셔널 argv 스플라이스(그 플래그가
  더는 방출되지 않게 되는 날 `ValueError`를 냈을 코드)를 제거했고, `DockerSandboxProvider`가
  공개 `resource_labels()` 컨텍스트 매니저 + 읽기 전용 접근자를 얻어 shadow 어댑터가
  더는 자신이 소유하지 않는 provider를 변경하지 않는다. 리뷰 후 클레임 락에
  실패 시 해제 · 오래된 클레임 재확보 · create 이후 조정(reconciliation)도 추가됐다.
- Docker 멱등성은 단일 어댑터 프로세스 내 동시 호출과 라벨 재발견 기반 재시도에서만 보호된다.
  기존 Docker provider가 **크로스 프로세스 원자적 create 프리미티브를 노출하지 않는다.**
  프로덕션 팩토리 채택 전 이것부터 경화해야 한다.
  → **CA5-b로 해소** (`c7876999`). §4의 출처 불명 미커밋 변경(`docker_shadow.py`)을
  Docker 볼륨을 클레임 락으로 쓰는 크로스 프로세스 원자적 create 구현으로 판정하고
  채택했다.

---

## 4. 🔴 재개 전 즉시 확인 — 미커밋 변경의 출처

> ✅ **해결됨 (2026-08-11, `c7876999`).** 두 파일의 미커밋 변경을 CA5-b(크로스
> 프로세스 원자적 create) 구현으로 판정하고 채택했다 — 로드맵 **CA2**는 종결됐다.
> 판정 근거 넷과 절차는 아래 「원장 무결성 문제 — 정정 완료」 절을 참고할 것.

```bash
cd /Users/ywsung/Desktop/neos
git status --short
#  M neos/coding/managed/adapters/docker_shadow.py       (+305 −33)
#  M tests/coding/managed/adapters/test_docker_shadow.py (+206)
```

변경 내용 (diff 확인 결과): `ManagedAdapterTimeoutError` / `SandboxError` import 추가,
`CLAIM_TOKEN_LABEL` 신설, 할당 리플레이 로직을 `_replayed_allocation()` 헬퍼로 추출,
`hashlib`·`uuid` 도입.

**성격:** Task 5(펜스된 할당 · 모호한 결과 복구)의 선행 작업으로 보이나,
Task 5 브리프·리포트가 생성되지 않았고 원장에도 기록이 없다.

> ⚠️ **이 워크트리에는 "리뷰 후 출처 불명 미커밋 변경 등장" 전례가 두 번 있다.**
> 원장 9번 줄: *"Task 2: implementer blocked — RED preceded unknown-provenance production
> files; preserved uncommitted and reassigned for fresh ownership review."*
> 원장 24번 줄: *"Task 3: BLOCKED — unexpected uncommitted changes appeared in Task 2
> production and test files after review; ownership must be resolved before dependent work."*
>
> 두 번 모두 **의존 작업을 시작하기 전에 소유권을 먼저 해결**하는 것으로 처리했다.
> 같은 절차를 밟을 것 — 지우지 말고 보존한 채 출처를 판정한 뒤 Task 5로 넘어가라.

### 원장 무결성 문제 — 정정 완료 (2026-08-11)

`progress.md`는 **이중 기록 + Task 4 누락** 두 문제를 함께 갖고 있었다.

1. **이중 기록.** 17번째 줄 빈 줄 이후 Task 1–3이 다른 커밋 해시로 다시 나온다.
   git 이력으로 확정한 실제 계보는
   `591640ce → 29ab632d → 777fdd33 → 79645f2e → 8b6ef183 → d8f4e2e4 → d308443e →
   9245d5d5 → 2d38f1a6 → 3e3935f1 → 89196755`이며, **첫째 블록**의 해시가 이와
   일치하므로 첫째 블록이 실제다.
2. **Task 4 누락.** 두 블록 모두 Task 3에서 끝나 Task 4 항목이 아예 없었다.
   즉 로드맵 §12.2의 "Task 4 ✅"는 **원장 근거 없이** 커밋 존재에만 기대고 있었다.

**CA2 소유권 판정 (해소).** `docker_shadow.py`(+305/−33)·`test_docker_shadow.py`(+206)의
미커밋 변경을 **CA5-b(크로스 프로세스 원자적 create) 구현으로 판정하고 채택**했다.
근거 넷: (1) 내용이 CA5-b와 일치(클레임 볼륨 락), (2) Task 4 커밋 12분 뒤 mtime으로
동일 세션, (3) `tests/coding/managed/adapters` 30 passed(Task 4 시점 17 → +13),
(4) 신규 테스트가 클레임 경로를 직접 겨냥.

> ⚠️ **원장 파일은 git에 없다.** `.superpowers/`가 `.gitignore:42`로 무시되므로
> `progress.md`는 워크트리 로컬 사본일 뿐이고 `git clean -fdx`로 사라진다.
> **이 절이 그 원장의 영속 기록이다.**

---

## 5. ⚠️ 방치된 브랜치 — anthropic-caching-advisor

> 🔴 **정정 (2026-08-08): 워크트리는 이미 사라졌다.** 아래 원문은 워크트리가 살아
> 있던 시절의 서술이다. 현재 `.worktrees/`에는 `managed-sandbox-control-plane`
> 하나뿐이고, `git worktree list`가 이 항목을 **`prunable`**로 표시한다
> (디렉터리 삭제 시점 ~2026-07-27).
>
> **커밋 7개는 브랜치 `codex/anthropic-caching-advisor`(`0fe2fa29`)에 살아남았다.**
> 그러나 로드맵 §10.1이 경고한 대로 `git worktree remove`는 **gitignore 대상 파일을
> 경고 없이 삭제**하므로, 그 워크트리 안에 산출물이 있었다면 **재생성 불가**이며
> 무엇이 있었는지 확인할 방법도 없다. 체크리스트를 밟았다는 기록은 없다.
>
> 즉 **결정은 여전히 미결이고(로드맵 CA6), 대상이 "워크트리"가 아니라 "브랜치"로
> 바뀌었을 뿐이다.** 브랜치를 지우면 그때는 커밋까지 사라진다.

```
codex/anthropic-caching-advisor  0fe2fa29   ← 브랜치는 생존, 워크트리는 소멸
원문 기준 dev 대비: -332 커밋 / +7 커밋      ← 2026-07-11 이후 방치
```

7개 커밋이 미병합 상태다:

```
4af72620 feat(config): add Anthropic caching and advisor settings
e8005ec6 feat(anthropic): add request feature policy
497bd4f5 feat(anthropic): track cache and advisor cost
48a51cda feat(chat): enable Anthropic prompt caching
5b2fb007 fix(chat): read Anthropic streaming usage metadata
06d8bbd7 feat(chat): add config-controlled Anthropic advisor
0fe2fa29 perf(retrieval): warm Anthropic document cache
```

플랜: `docs/superpowers/plans/2026-07-11-anthropic-prompt-caching-advisor.md` (53 steps)
스펙: `docs/superpowers/specs/2026-07-11-anthropic-prompt-caching-advisor-design.md`

**리베이스 비용이 크다.** 특히 role-based model routing이
`neos/providers/anthropic.py`와 `neos/utils/llm_factory.py`를 크게 바꿨으므로 충돌이 확실하다.
**병합할지 폐기할지 결정이 필요하다** (로드맵 CA6).

> 단, §1.1에서 배운 것을 여기에도 적용할 것: **커밋 수가 아니라 공유 파일의 겹침으로
> 재라.** 위 "332 커밋"은 낡았고 검증되지 않은 수치다. 결정 전에
> `git diff --name-only $(git merge-base dev codex/anthropic-caching-advisor) codex/anthropic-caching-advisor`로
> 실제 충돌면부터 측정한다 — 그 결과가 폐기/병합 판단을 바꿀 수 있다.

---

## 6. 재개 절차 (Managed Sandbox Task 6부터)

**2026-08-11 갱신.** CA2·CA3·CA4·CA5는 전부 종결됐다(§3·§4). dev는 이미 `a9f37c6a`로
이 워크트리에 병합됐고, 플랜 14 Task 5(펜스된 할당 · 모호한 결과 복구 ·
provider-reference 암호화, `1b9d2ad5`·`f38e357e`·`5aa31a22`)도 완료됐다. **더는
미커밋 변경 소유권 판정도, 병합 순서 결정도 남아 있지 않다.** 다음 재개는
플랜 14 **Task 6(라이프사이클 조정 · 정리 SLO · Celery 전달)** 부터다.

```bash
cd /Users/ywsung/Desktop/neos

# 1) 기존 베이스라인 확인
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/coding/managed
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/coding tests/coding
/Users/ywsung/Desktop/neos/.venv/bin/ruff format --check neos/coding tests/coding

# 2) Task 6 착수
#    - 라이프사이클 조정 · 정리 SLO · Celery 전달 (플랜 Task 6)
#    - Task 7이 image_identity 기록에 의존한다 — 아직 없다면 Task 6 범위에서 결정할 것
```

플랜 Task 6 위치: `docs/superpowers/plans/2026-07-25-managed-sandbox-control-plane.md:659`

**2026-08-11 실측 베이스라인:** dev → 워크트리 merge(`a9f37c6a`) 직후
`pytest -q tests/coding`는 **537 passed / 18 skipped**다. `tests/coding/managed`는
merge 이후 갱신되지 않았으므로 재개 시 위 1)로 다시 실측할 것.

> ⚠️ **알려진 한계 세 가지 — Task 6 이후 작업은 이를 전제로 시작할 것.**
> (1) 펜싱 SQL·클레임 상태 필터·CLEANED 컬럼 정리·join 쿼리는 이 환경에
> `CODING_TEST_DATABASE_URL`이 없어 스크립트 fake 세션 대상 SQL/바인드파라미터로만
> 검증했다 — 실제 Postgres로 검증한 적이 **한 번도 없다.** (2) provider-reference
> AES-GCM cipher는 어떤 프로덕션 호출자에도 배선되지 않았다 — `decrypt()`는 아직
> 호출되지 않는다. Celery 조정자가 실제로 배선할 몫이다. (3) 결정론적으로 계산되는
> `ownership_digest`는 `_rediscover()` 복구 경로에서 아직 비교되지 않는다.
> 상세는 로드맵 §12.6 E-S3 각주.

---

## 7. 참조

- **로드맵 트랙 E:** [DEEP_ANALYSIS_HARNESS_ROADMAP.md](DEEP_ANALYSIS_HARNESS_ROADMAP.md) §12
  — 출하 기준 E-S1~E-S4, 미해결 인벤토리 CA1~CA7, 트랙 D와의 접점
- 코딩 에이전트 설계: [NEOS_CODING.md](NEOS_CODING.md)
- 최종 수용 게이트: 플랜 `:1201`
- 관련 문서: [deep_analysis_task_task_resume.md](archive/deep_analysis_task_task_resume.md),
  [role_based_model_routing_task_resume.md](archive/role_based_model_routing_task_resume.md)
- SDD 원장: `.superpowers/sdd/2026-07-25-managed-sandbox-control-plane/` 와
  `.superpowers/sdd/2026-08-11-coding-agent-track-e-resume/` (저장소 루트, gitignore)
  (⚠️ 이중 기록 — §4 「원장 무결성 문제」, 로드맵 CA4)
- 전체 로드맵: `docs/ROADMAP.md` — ⚠️ 여기에는 **코딩 트랙이 한 번도 등장하지 않는다**
  (로드맵 CA7)
