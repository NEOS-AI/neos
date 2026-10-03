# Q10b 봉투 집행(`PAUSED`) · Q3 상시 질문 — 설계와 착지

> **작성:** 2026-10-02 · **트랙:** Q10b · Q3 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2)
> **지위:** Q10b · Q3 착지(둘 다 플래그 off, 2026-10-02). 설계와 코드가 어긋나면 코드가 이긴다.
> **선행:** [Q4·Q10 설계](Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md) Q10a · [Q13 설계](Q13_STANDING_AGENT_DESIGN_260930.md) a~f · Q5 감시자 섀도
> 결정 P1~P9 · O1~O6 · SQ1~SQ10 은 **위임받아 Claude 가 골랐다**(Q2·Q4b·Q6 과 같은 방식). 사람이 뒤집을 수 있다.

---

## 0. 한 줄

**Q10b — 봉투를 넘은 진행 중 에이전트 태스크를 `PAUSED` 로 보내고, 사람만 재개한다.** `PAUSED` 의 첫 작성자다
(분석 §6 결정 3: `PAUSED` 는 감시자 Q5 와 봉투 Q10 의 출구).
**Q3 — 에이전트가 같은 질문을 주기적으로 심층분석(DA)에 다시 묻고, verified 클레임 집합이 달라졌을 때만 알린다.**
둘이 같은 문서에 있는 이유는 **소유자 알림 경로**(§4)를 함께 쓰기 때문이다 — D7 "두 번 배선하지 않는다".

## 1. 시작 전에 확인한 것

| 사실 | 근거 | 결과 |
|---|---|---|
| `PAUSED` 로 보내는 코드가 0건이다. 전이표에는 `RUNNING → PAUSING → PAUSED → QUEUED` 가 있다 | `neos/coding/domain/models.py` `_ALLOWED_TRANSITIONS` | 전이표를 실제 경로에 맞춘다(P2) |
| SQL 은 전이표를 거치지 않고 상태를 직접 쓴다. 승인 대기는 런을 `running` 에 둔 채 **태스크만** `waiting_approval` 로 바꾸고, 결정되면 `running` 으로 되돌린다 | `run_repository.request_tool_approval` · `resolve_tool_approval` | 멈춤도 같은 모양(P1) |
| 리스 획득은 **런**의 상태만 본다. 태스크 상태는 보지 않는다 | `acquire_execution_lease` 의 `canonical.status = 'running'` | 멈춘 태스크도 리스는 얻는다 → 런 서비스가 막아야 한다(P4) |
| 워커가 고르는 태스크는 `queued`·`running` 뿐이다 | `claimable_task_ids` · `claimable_delivery_tokens` | 멈춘 태스크는 그대로면 아무도 집지 않는다 |
| 러너는 `None` 을 **완료**로 읽는다 | `CodingTaskRunner.run` — `event is None or run.completed → COMPLETED` | 멈춤은 `None` 이 아니라 이름 붙은 이벤트·예외로(P4) |
| 📌 **채널 게이트웨이는 API 프로세스에만 있다.** Celery 워커에서 `ChannelGateway.get_instance()` 는 `RuntimeError` 다. 기존 스케줄 태스크의 채널 전송(`scheduled_task_runner._send_to_channel`)은 그 예외를 경고 한 줄로 삼킨다 — **워커에서 보낸 스케줄 결과는 어디에도 가지 않았다** | `main.py` lifespan 만 `ChannelGateway(...)` 를 만든다 · `gateway.py` `_INSTANCE` | 알림은 durable 큐에 적고 API 프로세스가 보낸다(O1). 기존 스케줄 태스크의 구멍은 이 트랙 범위 밖 — §7 |
| `send_to_channel` 은 어댑터가 없으면 경고만 남기고 **돌아온다** | `gateway.py` | 보낸 것으로 세려면 먼저 어댑터를 본다(O4) |

## 2. Q10b — 결정

| # | 결정 | 이유 |
|---|---|---|
| **P1** | 멈춤은 **태스크만** `paused` 로 바꾼다. **런은 `running` 으로 남는다** | 승인 대기와 같은 모양이다. 재개가 새 런을 만들 필요 없이 같은 런의 최신 체크포인트에서 이어 간다. 런을 닫으면 재개가 "재시도"가 되고 attempt 가 는다 |
| **P2** | 전이표에 `RUNNING → PAUSED` 와 `PAUSED → RUNNING` 을 더한다. `PAUSING` 은 **루프 밖에서** 멈춤을 요청할 때(Q5 의 바깥 감시자 등)의 대기 상태로 남긴다 | 봉투는 safe point **안에서** 스스로 판정하므로 멈춤 요청과 커밋 사이가 없다. 그 0초짜리 중간 상태를 쓰는 것은 사실이 아니다 |
| **P3** | 판정 자리는 **모델 턴의 맨 앞** — 턴 예산 검사 뒤, 분리된 자식(detached children)에게 한 걸음을 주기 **전** | ① 멈출 태스크의 자식이 한 번 더 쓰지 않는다. ② 그 자리의 상태는 최신 체크포인트와 같아서 멈춤이 새 체크포인트를 쓸 필요가 없다. 재개는 그 체크포인트에서 이어 간다 |
| **P4** | 멈춤은 한 트랜잭션: 판정(`budget.judged`, `enforced: true`) + `running → paused` + `task.status.changed {status: paused, reason_code}`. 루프는 상태 이벤트를 돌려주고, 런 서비스는 그것을 **완료로 읽지 않고** 리스를 놓고 돌려준다. 러너는 `PAUSED` 결과를 낸다. 멈춘 태스크에 리스가 잡히면 런 서비스가 루프를 부르기 전에 `TaskPaused` 를 던진다 | `None` 은 완료다. 리스 획득이 태스크 상태를 보지 않으므로 마지막 문은 런 서비스다 |
| **P5** | **판정을 읽지 못하면 멈추지 않는다**(루프 안). 새 태스크 열기(`open_agent_task`)는 지금처럼 판정 예외가 그대로 올라가 **열지 않는다** | 판정은 매 턴 다시 한다 — 일시적 고장의 값은 많아야 한 턴이다. 계속되는 DB 고장이면 루프 자신의 커밋이 먼저 실패한다. 반대로 읽기 실패에 멈추면 DB 깜빡임마다 사람이 재개해야 한다 |
| **P6** | 재개는 **사람만** — `POST /coding/tasks/{id}/resume`(소유자 인증 라우트, 어떤 도구도 닿지 않는다). 멈추지 않은 태스크는 409 `task_not_paused`. 재개는 워커를 깨운다(디스패치 출처 `resume` — 메트릭 라벨 집합이 하나 는다) | Q5 결정: "재개는 사람만". 깨우기 실패는 재개를 되돌리지 않는다 — 태스크가 `running` 이면 조정(reconciliation) 스윕이 찾는다 |
| **P7** | 재개는 **봉투를 다시 묻지 않는다.** 여전히 넘은 에이전트는 다음 모델 턴 전에 다시 멈춘다(모델 호출 없음, 판정 이벤트 하나) | 재개 라우트는 멈춤의 원인을 모른다 — 봉투든 감시자(Q5)든 같은 라우트다. 원인을 아는 쪽이 다음 safe point 에서 다시 판정하는 것이 원인마다 재개 규칙을 두는 것보다 하나뿐인 자리다 |
| **P8** | 멈춘 태스크도 **취소된다**(Cancel). 런이 `running` 이라 기존 취소 경로가 그대로 닫는다 | 멈춤이 덫이 되면 안 된다 |
| **P9** | `enforce` 가 꺼져 있으면(기본) Q10a 섀도와 **바이트가 같다**. 켜져 있으면 섀도 자리는 판정하지 않는다(멈춤 자리가 이미 했다) | S9 와 같은 규율: 켜는 커밋만 경계가 된다 |

### 2.1 표면

- 설정: `standing_agents.budget.enforce`(기본 `false`) · `standing_agents.budget.warn_ratio`(기본 `0.8`, 0<r<1)
- API: `POST /api/v1/coding/tasks/{task_id}/resume` — `standing_agents.enabled` 일 때만 **라우트가 있다**
- FE: `paused` 배지 · Resume 버튼(`coding-task-workspace.tsx`) · BFF `app/(code)/api/coding/tasks/[taskId]/resume`
- 이벤트: 새 kind 없음. `budget.judged` 의 `enforced` 가 `true` 일 수 있게 됐고, 화면은 기존 `task.status.changed` 로 본다

## 3. Q10b — 테스트가 확인하는 것

| 무엇 | 테스트 |
|---|---|
| 넘으면 모델·도구 없이 멈춘다 · 판정+상태 이벤트 · 런은 `running` · 섀도 판정은 안 쌓인다 | `tests/standing/test_agent_budget_pause.py` |
| 자식 한 걸음보다 먼저 · 사람 태스크는 판정 없음 · 읽기 실패는 멈추지 않음 · off 는 Q10a 섀도 | 같은 파일 |
| 멈춤은 완료가 아니다 · 러너 `PAUSED` + 수명주기 · 리스를 얻어도 안 움직인다 · 소유자만 재개 · 깨우기 실패도 재개 · 멈춘 태스크 취소 | `tests/coding/application/test_run_service_pause.py` |
| 메모리·Postgres **같은 계약**: 한 트랜잭션 · 워커가 안 집는다 · 두 번 못 멈춘다 · 놓은 리스로 못 멈춘다 · 재개는 한 번 · 남의 것은 없음 | `tests/standing/test_pause_repository.py` (실 DB) |
| 라우트 202/409/404 · 기본 앱에는 없다 | `tests/api/test_standing_pause_api.py` |
| FE 배지·버튼·BFF 경로 · 스티어 입력기는 재개하지 않는다 | `web/tests/source/coding-phase-workspace.test.ts` |

변이 20/20(§8).

## 4. 소유자 알림 — Q10b 와 Q3 이 함께 쓴다

| # | 결정 | 이유 |
|---|---|---|
| **O1** | **워커는 보내지 않고 적는다.** durable 큐 `standing_notifications`(085) 에 적고, API 프로세스의 lifespan 루프가 꺼내 보낸다 | §1 📌 — 어댑터는 API 프로세스에만 있다. 워커에 어댑터를 따로 띄우면 Discord 처럼 게이트웨이 연결이 필요한 어댑터가 둘이 된다 |
| **O2** | 알림 대상은 에이전트마다 **채널 하나**(`standing_agent_notify_targets`, `agent_id` 키). `standing_agents` 에 열을 더하지 않는다 | 에이전트 응답 모양과 PATCH 가 그대로다. 딸린 것은 `agent_id` 키(Q13 §4.3) |
| **O3** | **목적지는 적을 때 정한다.** 대상이 없으면 적지 않는다. 대상을 바꿔도 이미 적힌 알림은 원래 곳으로 간다 | 적힌 행 하나가 "어디로 무엇을"을 다 말한다. 대상을 나중에 붙이면 아직 안 쓰인 중복 키라 다음 판정에서 적힌다 |
| **O4** | **한 번은 중복 키가 보장한다** — `(agent_id, dedupe_key)` 유일. 봉투 경고 `budget_warning:YYYY-MM`(D7: 달마다 한 번) · 멈춤 `task_paused:{task_id}:{seq}` · 상시 질문 `question:{question_id}:{da_run_id}` | 판정은 매 턴 돈다. 세는 자리를 두지 않고 DB 제약 하나로 |
| **O5** | 보내기는 `SKIP LOCKED` 로 꺼내고 다음 시도를 5분 미뤄 둔 뒤 보낸다. 실패는 30초에서 두 배씩(상한 1시간), `max_attempts` 뒤 `failed`. **어댑터 없음도 실패다** | API 워커가 여럿이어도 둘이 같은 알림을 보내지 않는다. `send_to_channel` 은 어댑터가 없어도 돌아오므로 그것을 성공으로 세면 조용히 사라진다 |
| **O6** | 알림 적기 실패는 **판정을 바꾸지 않는다**(멈춤은 멈춘다) | 알림은 판정의 부산물이다 |

- 설정: `standing_agents.notifications.{enabled=false, poll_interval_seconds=10, batch_size=20, max_attempts=5, max_body_chars=3500}`
- API: `GET/PUT/DELETE /api/v1/standing-agents/{agent_id}/notify-target` — 알림이 켜졌을 때만 있다
- 봉투 경고(D7)는 봉투 **전체**의 `warn_ratio` 다. background 몫을 먼저 넘으면 경고 없이 멈춤 알림이 간다(테스트가 그 경우를 적는다)
- 📌 **변이가 찾은 위험 하나:** Postgres `enqueue` 에서 `target.agent_id = :agent_id` 가 빠지면 대상 없는 에이전트의 알림이 **다른 에이전트의 채널로** 간다. 처음 쓴 테스트는 그 변이를 살려 뒀다 — 대상 있는 에이전트와 없는 에이전트를 같이 두는 테스트를 더했다(`test_a_notice_never_borrows_another_agents_target`)

## 5. Q3 — 상시 질문

| # | 결정 | 이유 |
|---|---|---|
| **SQ1** | `ScheduledTask` 를 넓히지 않고 **`agent_id` 키 테이블**(`standing_questions` · `standing_question_runs`)을 둔다. 주기·`skip_locked` 폴러·croniter 는 같은 모양 | `ScheduledTask` 는 `user_id` 키에 워크플로우 의미이고 채널 전송이 워커에서 죽어 있다(§1). 에이전트에 딸린 것은 `agent_id`(Q13 결정 6) |
| **SQ2** | DA 런은 **기존 제출 계약 그대로** 연다(`create_run` + `submit_deep_analysis_job`) — 인라인·Celery 실행자, 재시도·재개는 DA 의 것 | 새 실행 경로를 만들지 않는다. 사용자가 여는 DA 와 같은 런이다(`user_id` = 소유자, 대화 없음) |
| **SQ3** | **제출과 정산을 나눈다.** 폴러가 매 분 ① 끝난 DA 런을 정산(차이 계산 → 알림)하고 ② 때가 된 질문을 제출한다. 질문마다 진행 중 런은 **하나**(부분 unique 인덱스) | 실행자에 무관하다 — DA 완료 훅을 DA 쪽에 심지 않는다. 겹친 런이 서로의 기준선이 되지 않는다 |
| **SQ4** | 차이의 단위는 **클레임**(결정 4), 1차 짝짓기 키는 `DAClaim.hash`(= `claim_hash(text)`, 런 안 정체성 그대로 — 결정 8), 보조 키는 인용 증거의 `DAEvidence.raw_ref`(= `DABlob.content_hash`) 집합 | 새 해시 정의를 만들지 않는다(결정 8) |
| **SQ5** | 분류: **새로 검증**(지금 verified, 직전엔 verified 아님, 재표현 후보 아님) · **반증**(직전 verified, 같은 해시가 지금 rejected) · **사라짐**(직전 verified, 지금 verified 도 rejected 도 아님) · **재표현 후보**(짝 없는 지금의 verified 중 증거가 짝 없는 직전 verified 와 겹치는 것) | 결정 8 그대로 — 재표현이 알림 폭주가 되지 않게 따로 센다 |
| **SQ6** | **알림은 새로 검증 또는 반증이 있을 때만.** 사라짐·재표현 후보는 본문에 수만 싣는다. 첫 정산(기준선)은 알리지 않는다 | "달라졌을 때만"(Q3 행). 사라짐은 검색 운에 흔들린다 — 그것만으로 알리면 소음이다 |
| **SQ7** | 기준선은 **직전에 정산된 완료 런**이다. 실패한 런은 기준선이 되지 않는다 | 실패 런의 빈 집합을 기준으로 삼으면 다음 런의 전부가 "새로 검증"이 된다 |
| **SQ8** | 제출 문: 기능 플래그 · 에이전트 `active` · 봉투(Q10a)의 **background** 판정. 막히면 그 회차는 건너뛰고 사유를 남긴다. 📌 **DA 지출은 봉투에 들어가지 않는다**(봉투는 코딩 체크포인트의 `cost_micros` 합이고 DA 원장에는 비용 열이 없다) — 그래서 주기 하한(SQ9)과 에이전트당 개수 상한이 비용의 상한이다 | "봉투 게이트를 새 입구 밖에 두지 말 것"(Q4·Q10 §6). 지출 합산은 DA 비용 계량이 생길 때 |
| **SQ9** | 만들 때 cron 의 **가장 짧은 간격**이 `min_interval_minutes`(기본 360) 이상이어야 한다. 에이전트당 `max_per_agent`(기본 5) | DA 런은 비싸고 무인이다 |
| **SQ10** | 알림 본문은 사람에게 가는 평문이다. 클레임 문장은 분류마다 `max_claims_per_section`(기본 5)까지, 전체는 `max_body_chars` 로 자른다 | 클레임 문장은 웹 출처에서 온 모델 출력이다 — 채널로 가는 길에 상한을 둔다 |

### 5.1 표면

- 설정: `standing_agents.questions.{enabled=false, max_per_agent=5, min_interval_minutes=360, profile="default",
  max_claims_per_section=5, settle_timeout_minutes=720}`
- API(`standing_agents.enabled` 와 `questions.enabled` 둘 다일 때만 **라우트가 있다**):

  ```
  POST   /api/v1/standing-agents/{agent_id}/questions                 {question, cron_expression} → 201
  GET    /api/v1/standing-agents/{agent_id}/questions
  PATCH  /api/v1/standing-agents/{agent_id}/questions/{question_id}   {enabled}
  DELETE /api/v1/standing-agents/{agent_id}/questions/{question_id}
  GET    /api/v1/standing-agents/{agent_id}/questions/{question_id}/runs   # 정산 이력(차이는 해시와 수)
  ```

  거절: 빈 질문·`invalid_cron`·`cron_too_frequent` 422, 개수 초과 `too_many_questions` 409, 남의 것 404
- 폴러: Celery beat `poll-standing-questions`(60초, 같은 두 플래그) → `neos.tasks.poll_standing_questions`.
  태스크마다 새 `DatabaseManager`(새 이벤트 루프). ⚠️ **Celery beat 없이는 돌지 않는다** — 기존 스케줄 태스크와 같다
- 마이그레이션 086: `standing_questions` · `standing_question_runs`(질문마다 진행 중 하나 = 부분 unique 인덱스) — 둘 다 CASCADE
- 정산이 시한(`settle_timeout_minutes`)을 넘기면 `{"reason": "timeout"}` 으로 실패 처리 — 죽은 잡이 다음 회차를 막지 않는다.
  지운 질문의 진행 중 런은 정산하되 알리지 않는다
- 📌 **보조 키의 한계(관찰):** blob 해시는 **내용**의 해시라(`fetch._blob_hash`) 같은 URL 이라도 페이지가 바뀌면 해시가 바뀐다.
  자주 갱신되는 출처를 인용한 재표현은 보조 키로 짝이 나지 않고 "새로 검증 + 사라짐"으로 나온다. 결정 8 을 그대로 따랐고,
  넓히려면(예: `source_url` 을 보조 키에 더하기) 사람의 결정이다

### 5.2 테스트가 확인하는 것

| 무엇 | 테스트 |
|---|---|
| 정규화 해시가 짝 · 새로 검증/반증/사라짐/재표현 후보 · 증거 없는 클레임은 증거로 짝나지 않음 · 반증은 재표현에 가려지지 않음 · 요약은 해시만 · 본문 상한·한 줄 · cron 하한 | `tests/standing/test_question_diff.py` |
| 메모리·Postgres **같은 계약**: 소유 · 개수 상한 · 때가 된 것만(꺼짐·지움·진행 중 제외) · 실패는 기준선 아님 · 진행 중 하나(실 DB 인덱스) · 두 폴러가 같은 질문을 못 집음 · 사용자 삭제가 안 막힘 | `tests/standing/test_standing_questions.py` |
| 실 DA 원장에서 클레임과 증거 blob 집합 읽기 | 같은 파일 |
| 폴: 기준선은 침묵 · 바뀌면 한 번(새로 검증+반증) · 안 바뀌면 침묵 · 실패 런 뒤 기준선은 그 전 정산 · 시한 · 멈춘 에이전트·봉투 초과는 건너뜀 · 제출 실패 사유와 해제 · 지운 질문은 침묵 | 같은 파일 |
| API 201/422/409/404 · 남의 에이전트 경로로 못 닿음 · 기본 앱에 라우트·beat 없음 · 태스크 이름 | `tests/api/test_standing_questions_api.py` |

변이 24/24.

## 6. 단계

| 단계 | 무엇 | 상태 |
|---|---|---|
| **Q10b** | 봉투 집행 → `PAUSED` · 사람만 재개 · FE · 소유자 알림 큐·대상·경고(D7) | ✅ 2026-10-02 (플래그 off) |
| **Q3** | 상시 질문 — §5 | ✅ 2026-10-02 (플래그 off) |

## 7. 남은 것

- **Q5 의 `PAUSED`** — 같은 길(`pause_task` 의 판정 종류만 다르다: `monitor.judged`). 경계 실측 뒤
- 기존 `ScheduledTask` 의 채널 전송이 워커에서 죽어 있는 것(§1 📌) — 이 큐로 옮길 수 있다. 이 트랙 범위 밖이라 기록만 한다
- 멈춘 태스크의 만료(`PAUSED → EXPIRED`) — 지금은 무기한 멈춘다
- 브라우저 세션(Q14)은 멈춤에서 닫지 않는다 — 재개가 이어 쓰게 둔다. 오래 멈추면 세션이 낡는다

## 8. 변이

Q10b 20/20 — 멈춤 자리를 자식 뒤로 · `enforce` 무시 · 멈춘 태스크가 리스로 움직임 · 멈춤을 완료로 · 러너가 멈춤을 잊음 ·
`TaskPaused` 를 실패로 · 재개 소유 검사 빠짐 · 멈추지 않은 태스크 재개 · 멈춤의 리스 검사 빠짐 · 판정 `enforced` 거짓 ·
**대상 없는 알림이 남의 대상을 빌림**(처음엔 살았다 — §4 📌) · 남의 에이전트에 대상 · 어댑터 없는 전송 성공 · 포기 없음 ·
꺼낸 알림 재꺼냄 · 경고 임계 빠짐 · 경고가 달마다가 아님 · 409 대신 202 · 사람 태스크 멈춤 · 읽기 실패에 멈춤.

Q3 24/24 — 재표현이 증거를 안 봄 · 반증 없음 · 사라짐을 알림 · 반증이 재표현 짝 · 정확한 문장으로 짝 · 첫 런을 빈 기준선과 비교 ·
실패 런이 기준선(Postgres·메모리 각각) · 멈춘 에이전트 제출 · 봉투 무시 · 봉투를 autonomous 로 판정 · 진행 중 무시 ·
두 폴러가 같은 질문 · 개수 상한 하나 넘김 · 생성 소유 검사 빠짐 · cron 하한 없음 · 시한 없음 · 지운 질문 알림 ·
중복 키가 질문 단위 · API 경로의 에이전트 불일치 · 본문 여러 줄 · 다른 클레임의 증거 · 남의 정산 이력 · 바뀌어도 침묵.

## 9. 되돌리지 말 것

- 멈춤에서 런을 닫기 → 재개가 재시도가 되고 attempt 가 는다
- 멈춤 자리를 자식 한 걸음 뒤로 → 멈출 태스크가 한 번 더 쓴다
- 런 서비스의 `TaskPaused` 문 지우기 → 리스 획득은 태스크 상태를 보지 않는다
- 멈춤을 `None` 으로 돌려주기 → 러너가 완료로 읽는다
- 워커에서 게이트웨이로 직접 보내기 → 워커에는 게이트웨이가 없다(조용히 사라진다)
- `enqueue` 에서 대상의 `agent_id` 조건 빼기 → 남의 채널로 간다
- 상시 질문의 기준선에 실패 런을 쓰기 → 다음 런의 전부가 "새로 검증"이 된다
- 재표현 후보·사라짐을 알림 사유로 → 검색 운이 알림 폭주가 된다(결정 8)
- 상시 질문의 제출을 봉투 판정 밖에 두기 → 새 입구가 우회로가 된다(Q4·Q10 §6)
