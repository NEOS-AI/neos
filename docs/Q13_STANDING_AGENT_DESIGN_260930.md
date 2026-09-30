# Q13 상시 에이전트 개체 — 설계

> **작성:** 2026-09-30 · **트랙:** Q13 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2)
> **지위:** 설계다. 코드는 아직 없다. 코드가 착지하면 §8 단계표의 행을 "착지(커밋)"로 바꾸고, 설계와 코드가 어긋나면 코드가 이긴다.
> **근거 규칙:** 현재 상태 서술은 전부 2026-09-30 `dev`(`6d8efac2`)에서 확인했고 경로를 단다.

---

## 0. 한 줄

**태스크보다 오래 사는 1급 객체 `StandingAgent`** 를 세운다. 사용자당 하나로 시작하고(결정 6), 에이전트에 딸린 것은 전부
처음부터 `agent_id` 로 키를 잡는다. 그래서 "여럿으로 늘리기"는 **unique 인덱스 하나를 지우는 일**이고 데이터 이전이 없다.

## 1. 이미 내린 결정 (다시 열지 않는다)

| # | 결정 | 출처 |
|---|---|---|
| 1 | 상시 에이전트를 방향에 넣는다. 범위는 dots 전체 | 분석 §6 결정 1 |
| 6 | 사용자당 하나로 시작, 필요 시 여럿. 제약은 unique 인덱스 하나, 딸린 것은 `agent_id` 키 | 분석 §6 결정 6 |
| 2·3 | USER_ONLY 는 코드 고정 · `PAUSED` 는 감시자·예산의 출구 | 분석 §6 결정 2·3 |
| — | 학습·메모는 staged 로만(D19) | 분석 §4.1 |

## 2. 지금 소유가 어디에 붙어 있나 (2026-09-30 코드 확인)

| 대상 | 키 | 근거 |
|---|---|---|
| 사용자 | `users.user_id VARCHAR(255) UNIQUE` | `neos/database/models.py` `User` |
| 코딩 태스크 | `coding_tasks.owner_id → users(user_id)` | `db/migrations/038_add_coding_phase0.sql` |
| 채널 ↔ 코딩 바인딩 | `channel_coding_bindings(session_id PK, task_id, owner_id)` | `050_add_channel_coding_bindings.sql` |
| 반복 태스크 | `scheduled_tasks.user_id` + `channel_type`/`channel_id` | `neos/database/models.py` `ScheduledTask` |
| 교훈·메모 | `learned_lessons.namespace` = `owner:{id}` 또는 `owner:{id}:ws:{ws}` | `049_add_learned_lessons.sql`, `neos/learn/policy.py` `namespace()` |
| 장기 메모리 | `long_term_memories (user_id, key)` unique | `neos/memory/long_term.py` |
| DA 런 | `deep_analysis_runs.user_id` (`ON DELETE SET NULL`) | `036_add_deep_analysis_tables.sql` |
| 채널 사용자 | 설정 `channels.principals` 목록 → NEOS `user_id` | `neos/api/channels/principals.py` |

📌 **전부 사용자 키다.** 결정 6 의 "user_id 로 키잡지 않는다"는 새 테이블에 대한 규칙이다. 위의 기존 표를 에이전트 키로
옮기는 것이 아니라, 에이전트가 쓰는 행에 `agent_id` 를 **더한다**(§4).

📌 **`learned_lessons.namespace` 는 문자열이라 스키마 변경 없이 에이전트 메모를 받는다** — `agent:{agent_id}` 네임스페이스.

## 3. 이름

코드에서 "agent"는 이미 세 가지를 뜻한다 — 검색 에이전트(`neos/agents/`), 코딩 에이전트(`neos/coding/`),
서브에이전트(`neos/subagent/`). 넷째를 같은 이름으로 부르면 grep 이 거짓말을 한다.

- 테이블 `standing_agents` · 패키지 `neos/standing/` · 도메인 타입 `StandingAgent` · id 접두 `sa_`
- 문서·UI 에서는 "상시 에이전트". 사용자가 붙이는 이름(`name`)은 별개다(dots 처럼 사용자가 이름을 붙인다)

## 4. 데이터 모델

### 4.1 `standing_agents`

```sql
CREATE TABLE IF NOT EXISTS standing_agents (
    agent_id    VARCHAR(64)  PRIMARY KEY,                       -- 'sa_' + hex
    owner_id    VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        TEXT         NOT NULL CHECK (btrim(name) <> ''),   -- 길이 제한 없음(결정 Q13-3)
    status      VARCHAR(16)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'retired')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ  NULL
);

-- 결정 6 의 "하나" 는 이 인덱스 하나에만 산다. 여럿으로 늘릴 때 지우는 것이 이것 하나다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agents_one_per_owner
    ON standing_agents(owner_id) WHERE deleted_at IS NULL;

-- 결정 Q13-3: 같은 소유자 안에서 이름 중복 금지. 대소문자·앞뒤 공백 무시.
-- 이름 자체가 아니라 **해시**로 건다 -- 길이 제한이 없는 TEXT 를 btree 에 그대로 넣으면
-- 약 2.7KB 를 넘는 이름이 INSERT 에서 실패한다. 이 인덱스는 여럿으로 늘릴 때도 남는다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agents_name_per_owner
    ON standing_agents(owner_id, md5(lower(btrim(name)))) WHERE deleted_at IS NULL;
```

- **소유자는 사용자만.** Q17(조직 에이전트)은 트랙 P 테넌트 격리 뒤다. 지금 `owner_kind` 같은 열을 미리 두지 않는다 —
  읽는 코드 없이 스키마에만 사는 필드는 이 저장소에서 반복된 실패 모양이다(`supports_video`, `PAUSED`). Q17 이 오면
  `organization_id` 를 더하고 소유 CHECK 를 그때 쓴다
- **`status` 는 에이전트 단위다.** 태스크의 `PAUSED`(Q5 감시자의 출구)와 다르다. 에이전트 `paused` 는 **새 태스크를
  만들지 않는다**(트리거·상시 질문이 멈춘다). 이미 돌고 있는 태스크는 건드리지 않는다 — 태스크 멈춤은 태스크 상태의 일이다
- **`retired` 와 `deleted_at` 을 둘 다 둔다.** retired 는 사용자가 멈춘 것(이력은 보인다), `deleted_at` 은 삭제다.
  두 인덱스는 `deleted_at IS NULL` 만 보므로 **retired 도 "하나"를 차지한다** — 새로 만들려면 지운다
- **이름 중복의 범위는 소유자 안이다.** 전역으로 막으면 남의 에이전트 이름이 있는지 알아낼 수 있다(N8 의 "존재를 확인해 주지 않는다")

### 4.2 에이전트에 딸리는 행 — `agent_id` 를 더한다

| 대상 | 변경 | 없으면 |
|---|---|---|
| `coding_tasks` | `agent_id VARCHAR(64) NULL REFERENCES standing_agents(agent_id)` + 인덱스 ~~`(agent_id, last_activity_at DESC)`~~ `(agent_id) WHERE agent_id IS NOT NULL`(Q13d, 읽는 쪽에 맞췄다) | NULL = 사람이 직접 만든 태스크(지금까지의 전부) |
| `deep_analysis_runs` | 같은 열 — **Q13 이 아니라 Q3(상시 질문)가 더한다** (§8) | NULL |
| `scheduled_tasks` | 같은 열 — **Q3·Q4 가 더한다** (§8) | NULL = 기존 사용자 cron |
| `learned_lessons` | 변경 없음 — `namespace = 'agent:{agent_id}'` | — |

- `ON DELETE` 는 **걸지 않는다**(기본 `NO ACTION`). 삭제는 `deleted_at` 이고, 행을 지우는 경로가 생기면 그때 정한다
- **`owner_id` 는 그대로 남는다.** 에이전트가 만든 태스크의 `owner_id` 는 에이전트의 `owner_id` 다. 권한 검사는 지금처럼
  `owner_id` 로 한다 — 에이전트를 끼웠다고 소유 검사 경로가 둘이 되면 안 된다(N8 의 교훈: 우회 경로 하나가 소유 검사를 건너뛰었다)

### 4.3 이후 트랙이 더할 것 — 전부 `agent_id` 키 (지금 만들지 않는다)

| 트랙 | 테이블(안) | 키 |
|---|---|---|
| Q8 채널 횡단 스레드 | `standing_agent_threads` | `agent_id` + 채널 세션 → 스레드 |
| Q10 예산 봉투 | `standing_agent_budgets` | `(agent_id, period_start)` |
| Q4 트리거 규칙 | `standing_agent_triggers` | `agent_id` |

📌 **되돌리지 말 것:** 위 테이블 어느 것도 `user_id`/`owner_id` 를 **키**로 쓰지 않는다. 소유 검사용으로 에이전트를
거쳐 조인할 뿐이다.

## 5. 신원 (F2) — 에이전트는 누구로 행동하는가

- **주체 문자열:** `agent:{agent_id}`. 에이전트가 만든 태스크의 `task.created` 이벤트 payload 에 `actor` 로 싣는다
  (지금 태스크 생성자는 사용자뿐이라 `actor` 가 없다 — 없으면 사람이다)
- **권한은 소유자의 것을 넘지 못한다.** 에이전트 주체는 소유자 권한의 **부분집합**이다. 지금 NEOS 권한은 소유 검사
  하나뿐이므로 부분집합 = 같은 소유 검사 + 모드 천장(Q1)이다. 에이전트가 여는 태스크는 기본 `background`, 사용자가
  맡긴 일이면 `autonomous` 다 — `interactive` 는 사람이 보고 있다는 뜻이므로 사람이 연 태스크만 쓴다. Q2 의 사용자 규칙이
  오면 그 규칙도 에이전트 태스크에 그대로 걸린다(소유자의 규칙이다)
- **자격증명은 없다.** 에이전트 전용 자격증명은 Q6(브로커)·Q17(조직) 이후다

## 6. 해석 — 요청이 어떤 에이전트에 닿는가

```python
# neos/standing/resolve.py (안)
async def resolve_agent(owner_id: str, agent_id: str | None = None) -> StandingAgent | None:
    """agent_id 가 없으면 소유자의 (유일한) 활성 에이전트. 있으면 그 에이전트 -- 소유자가 아니면 None."""
```

- **호출자는 전부 이 함수 하나를 부른다**(API · 채널 게이트웨이 · 스케줄러). 에이전트를 찾는 SQL 이 둘이 되면
  여럿으로 늘릴 때 한쪽만 고쳐진다
- 소유자가 아닌 `agent_id` 는 **없는 것과 구별되지 않는다**(404). N8 의 `documentId` 교훈 — 존재를 확인해 주지 않는다
- 여럿이 되면 `agent_id=None` 의 뜻만 바뀐다: "기본 에이전트"(사용자가 고른 것) 또는 모호함 오류. 이 결정은 그때 한다

## 7. API

```
POST   /api/v1/standing-agents                 # 만들기 {name} -- 이미 있으면 409 (결정 6)
GET    /api/v1/standing-agents                 # 목록 -- 지금은 0개 또는 1개
GET    /api/v1/standing-agents/{agent_id}      # 하나
PATCH  /api/v1/standing-agents/{agent_id}      # {name?, status?: active|paused|retired}
DELETE /api/v1/standing-agents/{agent_id}      # deleted_at
GET    /api/v1/standing-agents/{agent_id}/activity?after=<cursor>   # F17 활동 피드
GET    /api/v1/standing-agents/me              # 별칭: 유일한 에이전트 (여럿이 되면 409 로 바뀐다)
```

- **처음부터 `{agent_id}` 경로다.** `/me` 는 편의 별칭이다. 경로가 처음부터 id 를 받으면 여럿으로 늘릴 때 API 가
  깨지지 않는다 — 결정 6 의 API 판
- **목록이 처음부터 배열이다.** 같은 이유
- 코딩 핸들러와 같은 인증 의존성(`get_current_user`, `neos/api/handlers/coding_handlers.py`)을 문다. 전부 `resolve_agent` 를 거친다
- 플래그 `standing_agents.enabled = False` 면 라우터를 마운트하지 않는다(비디버그의 WS 라우트 제거와 같은 방식,
  `main.py` `_include_router_for_runtime`)

### 7.1 활동 피드 (F17)

새 테이블이 아니라 **조회**다: `coding_tasks.agent_id` 로 태스크를 고르고 그 태스크들의 코딩 원장 이벤트를 시간순으로
합친다. `monitor.judged`(Q5)도 여기서 보인다 — 사람이 섀도 판정을 읽는 첫 자리다.

- ~~커서는 `(created_at, event_id)` 쌍~~ → **커서는 `(xact_id, task_id, seq)`**(Q13d 구현 때 바꿨다, 2026-09-30). 태스크마다 `seq`
  가 따로라 `seq` 하나로는 합친 스트림의 커서가 되지 못한다. `created_at` 도 못 된다 — 호출자가 넘긴 시계이고 태스크마다
  다른 트랜잭션이 따로 커밋하므로, 이른 `created_at` 이 늦게 커밋되면 **이미 지나간 커서 뒤로 떨어져 영영 건너뛰어진다**.
  `xact_id` 는 이벤트를 쓴 트랜잭션 id(마이그레이션 072, `xid8`)이고, 독자는 `pg_snapshot_xmin` **미만만** 읽는다 — 그 아래는
  전부 끝났고 앞으로 커밋될 것은 전부 그 이상이다. 대가: 오래 열린 트랜잭션이 있으면 피드가 그만큼 **늦는다**(건너뛰지는 않는다)
- 목록 순서는 커밋 순서에 가깝지 시계 순서가 아니다. 한 태스크 안의 순서는 `seq` 가 정본이다 — 화면은 `seq` 로 정렬할 수 있다
- 보관(archived)된 태스크의 이벤트는 피드에서도 빠진다 — 태스크 목록·이벤트 API 에서 빠지는 것과 같다
- DA 런(Q3)이 붙으면 DA 원장 이벤트도 합친다 — 두 원장의 어휘는 각자의 fixture 가 이미 고정한다

## 8. 단계 — 전부 플래그 off 로 착지한다

| 단계 | 무엇 | 테스트가 확인할 것 | 선행 |
|---|---|---|---|
| **Q13a** ✅ **착지(2026-09-30)** | 마이그레이션 070(`standing_agents` + 부분 unique 인덱스 둘) · `neos/standing/`(models · store · resolve) | 메모리·Postgres **같은 계약 테스트**(실 DB) · 둘째 생성 `one_per_owner` · 삭제 후 재생성 · 남의 id 는 None · 10,000자 이름 · 하나 제약을 지운 트랜잭션 안에서 이름 인덱스가 대소문자·공백 변형을 막는다 · 틀린 id 가 소유자의 에이전트로 새지 않는다 · 신선한 DB 2회 적용 · 테스트 27 · 변이 10/10. 409 는 Q13b(API)의 일이다 — 저장소는 `StandingAgentConflict(reason)` 을 낸다 | — |
| **Q13b** ✅ **착지(2026-09-30)** | API (§7, 활동 피드 제외) · 플래그 `standing_agents.enabled` · 저장소 `update`(이름·상태, 두 저장소 계약 테스트) | 플래그 off 면 **제공되는** 라우트 목록에 없다(실제 앱) · 목록이 배열 · `/me` 가 id 로 잡히지 않는다 · 남의 에이전트는 모든 동사에서 404 · 409 에 사유 코드 · 빈 PATCH 는 422 · retired 도 하나를 차지한다 · 테스트 22 · 변이 9/9. ⚠️ 플래그 **on** 분기(`main.py` 세 줄)는 테스트가 없다 — 앱은 import 때 한 번 조립된다 | Q13a |
| **Q13c** ✅ **착지(2026-09-30)** | 마이그레이션 071 `coding_tasks.agent_id`(FK, `ON DELETE` 없음) · `neos/standing/tasks.py` `open_agent_task`(기본 `background`, `autonomous` 허용, `interactive` 거절 · `active` 가 아닌 에이전트는 `agent_paused`/`agent_retired` · 에이전트는 `resolve_agent` 로만 찾는다) · `task.created` payload 의 `actor = agent:{id}`(사람이 연 태스크에는 없다) · 두 서비스가 `task_created_payload` 하나를 함께 쓴다 · 행→`CodingTask` 변환 다섯 곳 중 읽는 세 곳을 `TASK_COLUMNS` + `task_from_row` 하나로 합쳤다 | 에이전트 태스크의 `owner_id` = 에이전트 소유자 · 소유자는 기존 `snapshot`/`list_owned` 로 보고 남은 못 본다(새 소유 검사 경로 없음) · 메모리·Postgres **같은 계약** · Postgres 읽기 다섯 곳이 전부 `agent_id` 를 돌려준다(이름으로) · 사용자 삭제가 에이전트와 태스크를 한 문장에서 함께 지운다(NO ACTION 이 막지 않는다) · 테스트 20 · 변이 11/11. ⚠️ **부르는 곳이 아직 없다** — 첫 호출자는 Q13f(자기소개)·Q4(트리거). `(agent_id, last_activity_at)` 인덱스는 그것을 읽는 Q13d 로 미뤘다(§9) | Q13a · Q1 ✅ |
| **Q13d** ✅ **착지(2026-09-30)** | `GET /standing-agents/{agent_id}/activity?after=&limit=` → `{events, next}`(이벤트 모양은 코딩 이벤트 API 와 같은 `event_response`) · `neos/standing/activity.py`(메모리·Postgres 원천) · 마이그레이션 072: `coding_events.xact_id xid8`(NULL 로 더한 뒤 기본값 — 테이블 재작성 없음) + 인덱스 `(task_id, xact_id, seq)` · `coding_tasks(agent_id) WHERE agent_id IS NOT NULL`. §4.2 의 `(agent_id, last_activity_at)` 는 읽는 쪽이 없어 **만들지 않았다** · 커서를 §7.1 설계에서 바꿨다(위) | limit 1·2·100 으로 끝까지 넘겨도 두 태스크 이벤트가 **빠짐없이 한 번씩**, 태스크 안에서는 `seq` 순 · 사람 태스크·남의 에이전트 태스크가 섞이지 않는다 · **커서보다 이른 시각이 찍힌 이벤트도 온다** · **늦게 커밋되는 트랜잭션을 건너뛰지 않는다**(열린 동안은 보류, 커밋 뒤 도착 — 실 DB) · 보관된 태스크는 빠진다 · 남의 에이전트는 None/404 · 읽을 수 없는 커서는 422 · 테스트 25 · 변이 14/14 | Q13c |
| **Q13e** ✅ **착지(2026-09-30)** | `neos/standing/memos.py` `write_agent_memo` · 네임스페이스 `agent:{id}`(`policy.agent_namespace`, 스키마 변경 없음) · kind `agent_memo` · **`memory_gate.stage_memo`** — 기존 `maybe_learn_ltm` 은 `write_approval` 이 꺼지면 장기 메모리에 바로 쓰므로 에이전트는 그것을 **쓰지 않는다** · 명령형·빈 메모 거절 · 멈춘·은퇴한 에이전트도 쓴다(진행 중 태스크가 계속 돈다, 결정 2) · F18: `policy.is_agent_namespace` 판별 하나, GEPA `insert_run_with_seed` 가 `agent:` 네임스페이스 런을 거절한다. ⚠️ GEPA 예제를 교훈에서 만드는 코드는 **아직 없다** — 만드는 쪽(Q7)이 이 판별을 쓴다 | `write_approval` **켜짐·꺼짐 둘 다** STAGED, 장기 메모리 `learn` 이 불리지 않는다 · 메모리·Postgres 교훈 저장소 같은 계약 · 소유자 네임스페이스에 안 섞인다 · **승인된** 에이전트 메모도 소유자 코딩 교훈 주입에 안 들어간다 · GEPA 거절은 세션을 열기 전 · 테스트 17 · 변이 11/11. 📌 사람이 올리는 경로: 지금 교훈 승인 HTTP API 가 없다(소유자 교훈도 같다). STAGED 메모는 큐레이터가 30일 뒤 보관한다(다른 교훈과 같은 규칙) | Q13a |
| **Q13f** ✅ **착지(2026-10-01)** | `POST /standing-agents` 가 만든 직후 background 자기소개 태스크 하나를 연다(`neos/standing/onboarding.py` `start_onboarding`, 실패해도 에이전트는 201 로 남고 `onboarding_task_id` 는 None) · 채널(켜진 것, `principals` 가 있으면 그 소유자에게 매핑된 것만)·스킬(모델이 부를 수 있는 것, 40개까지) **이름과 설명만** 프롬프트에 · **태스크는 메모를 쓰지 않는다** — READ_ONLY 천장이라 쓰는 도구가 없고, 메모 도구를 READ_ONLY 로 달면 위험을 속인다. 대신 `CodingRunService` 완료 훅(`on_completed`, 기본값이 상시 에이전트 훅이라 API 런타임·celery 워커 두 생성 지점이 따로 배선하지 않는다)이 **마지막 체크포인트 transcript 의 마지막 assistant 텍스트**를 `write_agent_memo`(STAGED)로 옮긴다 · 마이그레이션 073: `standing_agents.onboarding_task_id`(한 번만 적힌다) · `onboarded_at`(조건부 UPDATE 로 한 번만 — "이 태스크가 자기소개인가"의 정본) | 실제 `AnthropicCodingLoop` 을 `CodingRunService` 로 끝까지: 모델의 쓰기가 `policy_mode_ceiling` 으로 거절되고 쓰기 0 · 최종 답이 STAGED 메모 · 루프가 스스로 `run.completed` 를 내는 경로(가짜 루프)와 `complete_run` 경로 **둘 다** 훅을 부른다 · 답을 말한 뒤 실패한 런은 메모가 없다 · 훅 실패가 런을 실패시키지 않는다 · 두 번 불려도 메모 하나 · 빈 답은 claim 을 쓰지 않는다 · 명령형 답은 조용히 거절(최대 한 번) · 다른 에이전트 태스크·사람 태스크는 무시 · 테스트 30 · 변이 22/22(동치 변이 하나는 중복 검사라 코드에서 지웠다) | Q13c · Q13e |

- `deep_analysis_runs.agent_id` · `scheduled_tasks.agent_id` 는 Q13 이 아니라 **그것을 쓰는 트랙(Q3·Q4)이 더한다** —
  읽는 코드 없이 열만 먼저 두지 않는다
- **여럿으로 늘리기**(결정 6 의 "필요 시")는 단계가 아니다. 인덱스를 지우고 §6 의 `agent_id=None` 뜻을 정하는 결정이다

## 9. 되돌리지 말 것

- 에이전트에 딸린 새 테이블을 `user_id`/`owner_id` **키**로 만들기 → 하나→여럿이 데이터 이전이 된다
- 에이전트를 찾는 SQL 을 `resolve_agent` 밖에 쓰기 → 여럿이 될 때 한쪽만 고쳐진다
- 에이전트 경로에서 소유 검사를 따로 구현하기 → 태스크 소유 검사는 `owner_id` 하나다
- 읽는 코드 없이 열·상태·필드를 먼저 두기(`owner_kind`, 미래 트랙의 FK) → 스키마에만 사는 필드
- 에이전트 태스크를 `interactive` 로 만들기 → 사람이 보고 있다는 거짓 신호다

## 10. 결정 (2026-09-30, 사람의 결정)

1. ✅ **만드는 시점** — 사용자가 **명시적으로** 만든다(`POST`). 첫 사용 때 자동으로 만들지 않는다
2. ✅ **`paused` 에이전트의 진행 중 태스크** — **건드리지 않는다.** `PAUSED` 의 작성자는 결정 3 대로 감시자·예산 둘뿐이다
3. ✅ **이름** — 길이 제한 없음(빈 이름만 거절) · **같은 소유자 안에서 중복 금지**, 대소문자·앞뒤 공백 무시(§4.1 해시 인덱스)

## 10′. ~~열린 질문 (사람의 결정)~~ → 위 §10 으로 닫혔다

1. **만드는 시점** — 사용자가 명시적으로 만든다(dots 방식, 이 설계의 가정) / 첫 사용 때 자동으로. 자동이면 모든
   사용자가 에이전트를 갖게 되고 Q13f 자기소개가 모두에게 돈다(비용)
2. **`paused` 에이전트의 진행 중 태스크** — 이 설계는 건드리지 않는다. dots 는 "방향을 바꿀 수 있다"고만 했다. 에이전트를
   멈추면 그 태스크들도 `PAUSED` 로 보내야 하는가 — 그러면 `PAUSED` 의 두 번째 작성자가 생긴다(결정 3 은 감시자·예산만 적었다)
3. **이름 규칙** — 길이·중복 허용. 사용자당 하나인 동안에는 중복이 문제가 아니지만 여럿이 되면 채널에서 이름으로 부를 때 문제가 된다
