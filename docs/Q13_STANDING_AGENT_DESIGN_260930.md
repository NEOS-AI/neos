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
    name        VARCHAR(80)  NOT NULL,
    status      VARCHAR(16)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'retired')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ  NULL
);

-- 결정 6 의 "하나" 는 이 인덱스 하나에만 산다. 여럿으로 늘릴 때 지우는 것이 이것 하나다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agents_one_per_owner
    ON standing_agents(owner_id) WHERE deleted_at IS NULL;
```

- **소유자는 사용자만.** Q17(조직 에이전트)은 트랙 P 테넌트 격리 뒤다. 지금 `owner_kind` 같은 열을 미리 두지 않는다 —
  읽는 코드 없이 스키마에만 사는 필드는 이 저장소에서 반복된 실패 모양이다(`supports_video`, `PAUSED`). Q17 이 오면
  `organization_id` 를 더하고 소유 CHECK 를 그때 쓴다
- **`status` 는 에이전트 단위다.** 태스크의 `PAUSED`(Q5 감시자의 출구)와 다르다. 에이전트 `paused` 는 **새 태스크를
  만들지 않는다**(트리거·상시 질문이 멈춘다). 이미 돌고 있는 태스크는 건드리지 않는다 — 태스크 멈춤은 태스크 상태의 일이다
- **`retired` 와 `deleted_at` 을 둘 다 둔다.** retired 는 사용자가 멈춘 것(이력은 보인다), `deleted_at` 은 삭제다

### 4.2 에이전트에 딸리는 행 — `agent_id` 를 더한다

| 대상 | 변경 | 없으면 |
|---|---|---|
| `coding_tasks` | `agent_id VARCHAR(64) NULL REFERENCES standing_agents(agent_id)` + 인덱스 `(agent_id, last_activity_at DESC)` | NULL = 사람이 직접 만든 태스크(지금까지의 전부) |
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

- 커서는 `(created_at, event_id)` 쌍. 태스크마다 `seq` 가 따로라 `seq` 하나로는 합친 스트림의 커서가 되지 못한다
- DA 런(Q3)이 붙으면 DA 원장 이벤트도 합친다 — 두 원장의 어휘는 각자의 fixture 가 이미 고정한다

## 8. 단계 — 전부 플래그 off 로 착지한다

| 단계 | 무엇 | 테스트가 확인할 것 | 선행 |
|---|---|---|---|
| **Q13a** | 마이그레이션(`standing_agents` + 부분 unique 인덱스) · 도메인 · 저장소 · `resolve_agent` | 두 번째 생성이 409 · 삭제 후 다시 만들 수 있다(부분 인덱스) · 남의 id 는 404 · 부트스트랩 2회 적용 | — |
| **Q13b** | API (§7, 활동 피드 제외) · 플래그 | 플래그 off 면 라우트가 없다 · 목록이 배열 · `/me` | Q13a |
| **Q13c** | `coding_tasks.agent_id` · 에이전트가 태스크를 만드는 서비스 함수(기본 모드 `background`, `actor` 기록) | 에이전트 태스크의 `owner_id` = 에이전트 소유자 · 소유 검사가 새 경로를 만들지 않는다 | Q13a · Q1 ✅ |
| **Q13d** | 활동 피드 | 합친 커서가 두 태스크의 이벤트를 빠짐없이 한 번씩 · 남의 태스크 이벤트가 섞이지 않는다 | Q13c |
| **Q13e** | 메모 — `memory_gate` 경유, 네임스페이스 `agent:{id}` | 메모는 STAGED 로만 쓰인다 · GEPA 평가 세트에 들어가지 않는다(F18) | Q13a |
| **Q13f** | 자기소개(온보딩) — 만들어질 때 background 태스크 하나: 쓸 수 있는 채널·스킬을 읽고 자기소개 메모를 남긴다 | background 천장 안에서만 돈다 | Q13c · Q13e |

- `deep_analysis_runs.agent_id` · `scheduled_tasks.agent_id` 는 Q13 이 아니라 **그것을 쓰는 트랙(Q3·Q4)이 더한다** —
  읽는 코드 없이 열만 먼저 두지 않는다
- **여럿으로 늘리기**(결정 6 의 "필요 시")는 단계가 아니다. 인덱스를 지우고 §6 의 `agent_id=None` 뜻을 정하는 결정이다

## 9. 되돌리지 말 것

- 에이전트에 딸린 새 테이블을 `user_id`/`owner_id` **키**로 만들기 → 하나→여럿이 데이터 이전이 된다
- 에이전트를 찾는 SQL 을 `resolve_agent` 밖에 쓰기 → 여럿이 될 때 한쪽만 고쳐진다
- 에이전트 경로에서 소유 검사를 따로 구현하기 → 태스크 소유 검사는 `owner_id` 하나다
- 읽는 코드 없이 열·상태·필드를 먼저 두기(`owner_kind`, 미래 트랙의 FK) → 스키마에만 사는 필드
- 에이전트 태스크를 `interactive` 로 만들기 → 사람이 보고 있다는 거짓 신호다

## 10. 열린 질문 (사람의 결정)

1. **만드는 시점** — 사용자가 명시적으로 만든다(dots 방식, 이 설계의 가정) / 첫 사용 때 자동으로. 자동이면 모든
   사용자가 에이전트를 갖게 되고 Q13f 자기소개가 모두에게 돈다(비용)
2. **`paused` 에이전트의 진행 중 태스크** — 이 설계는 건드리지 않는다. dots 는 "방향을 바꿀 수 있다"고만 했다. 에이전트를
   멈추면 그 태스크들도 `PAUSED` 로 보내야 하는가 — 그러면 `PAUSED` 의 두 번째 작성자가 생긴다(결정 3 은 감시자·예산만 적었다)
3. **이름 규칙** — 길이·중복 허용. 사용자당 하나인 동안에는 중복이 문제가 아니지만 여럿이 되면 채널에서 이름으로 부를 때 문제가 된다
