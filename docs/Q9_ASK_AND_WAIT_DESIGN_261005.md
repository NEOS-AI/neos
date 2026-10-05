# Q9 묻고 기다리기 — 설계

> **작성:** 2026-10-05 · **트랙:** Q9 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2 Q9 행 · §6 결정 3) · **dots:** F11 "에이전트 발신"의 빠진 절반 — 묻고 기다리기
> **지위:** 설계다. 이미 내린 결정(§1)은 닫혔다. 권고 기본값과 열린 질문 Q-A~Q-H 는 2026-10-05 체크포인트 ①에서 닫혔다(§11).
> 코드가 착지하면 §10 단계표의 행을 "착지(커밋)"로 바꾼다. 설계와 코드가 어긋나면 코드가 이긴다.
> **근거 규칙:** 현재 상태 서술은 전부 2026-10-05 `dev`(`39055fe6`, `8d149f39` 와 코드가 같다 — 그 사이 두 커밋은
> `.gitignore` 와 artifacts 삭제뿐이다)에서 코드로 확인했고 경로를 단다. 실호출로 확인하지 않은 서술은 **[코드 읽기]**
> 로 표시한다.

---

## 0. 한 줄

상시 에이전트의 **`autonomous` 태스크**가 `ask_user.v1` 을 부르면, 지금처럼 DENY 로 접지 않고 **질문을 소유자의 채널로
보내고 태스크를 `WAITING_USER` 로 세운다.** 런은 `running` 으로 남는다(Q10b 멈춤 · 승인 대기와 같은 모양). 소유자가 에이전트
스레드에 붙는 DM 에 답하면 게이트웨이가 그것을 답으로 적고 태스크를 `running` 으로 돌려 **같은 런의 최신 체크포인트에서**
깨운다. 루프는 승인 답과 같은 자리(`_with_approval_answers`)에서 답을 도구 입력에 싣고 `ask_user.v1` 을 실행한다. 아무도
답하지 않으면 `standing_agents.ask.expire_hours` 뒤에 만료한다.

## 1. 이미 내린 결정 (다시 열지 않는다)

| # | 결정 | 출처 |
|---|---|---|
| Q9-1 | 질문할 수 있는 것은 **에이전트의 `autonomous` 태스크만**이다. `background` 는 dots F8 처럼 메시지를 보내지 못한다. READ_ONLY 천장(`policy_mode_ceiling`)은 그대로다 | 2026-10-05 사람의 결정 |
| Q9-2 | **interactive 태스크의 `ask_user.v1` 은 지금 그대로다**(승인 카드 · `WAITING_APPROVAL` · 답은 승인 결정에 실린다). `WAITING_USER` 경로는 에이전트 태스크에만 있다 | 2026-10-05 사람의 결정 |
| 3 | `WAITING_USER` 는 Q9 몫이다. `WAITING_APPROVAL` 과 섞지 않는다(승인은 예/아니오, 질문은 자유 답) | 분석 §6 결정 3 · §4.2 Q9 행 |
| — | 재개는 사람만 시키는 것이 아니다. **답이** 시킨다. 질문의 답이 오면 재개한다. Q5 의 "Jev 는 재개하지 못한다"와는 다른 축이다 | 계획 "이미 내린 결정"(기존) |
| 6 · 13 | 에이전트에 딸린 것은 `agent_id` 키로 잡는다. 개수 제약은 인덱스 하나에만 둔다. 테넌트 경계는 user 다 | 분석 §6 · Q8 §1 |
| — | 워커는 채널로 보내지 않는다. Q10b 알림 큐에 적는다 | 메모리 channel-gateway-lives-in-the-api-process · `neos/standing/notifications.py` 독스트링 |

## 2. 지금 코드 (2026-10-05 확인)

### 2.1 `ask_user.v1` — 도구, 실행, 답

| 무엇 | 지금 | 근거 |
|---|---|---|
| 도구 정의 | 위험 등급은 `ToolRisk.USER_QUESTION` 이다. 입력은 `questions` 1~4개다(문자열 또는 `{prompt, options[2-4], multi_select}`). 설명에 "Requires approval. Do not assume the answer." 가 있다 | `neos/coding/tools/registry.py:1000-1010`, `_AskUserInput` `:621-622`, `_AskUserQuestion` `:615-618` |
| 모델은 답을 넣지 못한다 | `_ToolInput` 이 `extra="forbid"` 다. `_AskUserInput` 에는 `answers` 필드가 없다. 그래서 답은 **검증 뒤에** 입력에 합쳐야만 들어간다 | `registry.py:400-401` |
| 실행 | 샌드박스 밖 제어 도구다. `input["answers"]` 를 읽어 `{questions, answers, pairs}` 를 돌려준다. 답이 없으면 `answers=[]` 이고, 각 pair 의 `answer` 는 `""` 다 | `neos/coding/tools/executor.py:1180-1181`, `_ask_user` `:1329-1356` |
| 답을 싣는 자리 | `DurableCodingLoop._with_approval_answers` 는 승인 행의 `display_summary["answers"]` 를 꺼내 `replace(validated, input={..., "answers": [...]})` 로 합친다. `ask_user.v1` 이 아니면 그대로 돌려준다 | `neos/coding/loop/durable.py:367-376`. 부르는 곳은 `neos/coding/loop/_durable/tools.py:297` 한 곳이다 |
| 승인 쪽 답 검증 | `requires_approval_answers` 는 `ask_user.v1` 만 참이다. `ask_user_answers_complete` 는 질문 수만큼, 비지 않은 문자열 답을 요구한다 | `neos/coding/domain/approvals.py:198-212` · `neos/coding/application/approval_service.py:84-86` · `run_repository.resolve_tool_approval` `:1248-1253` |
| 자식 | 자식 런은 `ask_user.v1` 을 아예 받지 못한다(`REFUSED_TOOLS`). 이름으로 불러도 CHILD-GATE 가 `unattended=True` 로 판정한다 | `neos/subagent/stepper.py:43-58` · `neos/coding/loop/_durable/spawn.py:385-393` |

### 2.2 무인 접기는 어디서 일어나는가 (질문 1)

**접기 함수는 하나다.** `fold_for_unattended(outcome, gate)` 는 `gate.unattended` 이고 결과가 `REQUIRE_APPROVAL` 이면
`DENY` 를 돌려준다(`neos/coding/domain/approvals.py:215-232`). 이 함수를 부르는 곳은 둘이다.

1. `evaluate_approval` — 정적 판정 R₀ 뒤에 접는다(`approvals.py:244-252`). Jev 가 꺼져 있을 때의 경로다
2. `evaluate_approval_with_jev` — 정적 판정 → Jev 밴딩 → 접기 순서다. **이 순서가 계약이다**(D-L1, `neos/jev/gate.py:281-335`)

`gate.unattended` 를 정하는 것은 루프다.

- `_unattended(input)` 은 태스크 모드가 `autonomous` 나 `background` 이면 참이다(K9, `neos/coding/loop/_durable/tools.py:981-992`).
  `_background(input)` 은 `background` 일 때만 참이다(Q1 천장, `:995-997`)
- `ToolExecutionMixin._approval_gate_step` 은 `unattended=_unattended(input)`, `read_only_ceiling=_background(input)` 로
  `_evaluate_call` 을 부른다(`tools.py:232-241`). `_evaluate_call` 은 그 값을 `_approval_gate` 에 넘기고,
  `_approval_gate` 는 운영자 설정 `approval_unattended` 와 OR 해서 `ApprovalGate.unattended` 를 만든다(`durable.py:202-232`, `:306-362`)
- 자식(CHILD-GATE)은 늘 `unattended=True` 다(`spawn.py:385-393`)

그래서 **지금 에이전트 `autonomous` 태스크의 `ask_user.v1`** 은 다음 길을 간다.
R₀ = `REQUIRE_APPROVAL`(위험 등급 `USER_QUESTION`, `approvals.py:713-718`) → 접기 → `DENY` → `_commit_denied_tool`.
사유 코드는 `policy_denial_reason` 의 마지막 기본값 `policy_approval_denied` 다(`approvals.py:618-647`). 그리고
`denial_envelope` 는 이 코드에 **`denied_by: "user"`** 를 단다(`approvals.py:1016-1022`). 📌 **아무도 거절하지 않았는데
원장은 사람이 거절했다고 읽힌다.** Q9 는 에이전트 autonomous 태스크에서 이 길을 없앤다. 사람이 연 autonomous 태스크에는
이 오독이 남는다(§11.2 Q-F).

**`background` 는 접기까지 가지 않는다.** `exceeds_mode_ceiling` 이 `_evaluate_approval` 의 둘째 줄에서 이미
`DENY` 를 낸다(`approvals.py:604-615`, `:657-658`). 사유는 `policy_mode_ceiling` 이다(결정 Q9-1).

📌 **운영자나 소유자의 allow 는 `ask_user.v1` 을 빈 답으로 실행시킨다.** `allow_tools` 에 `ask_user.v1` 이 있거나 소유자의
ALLOW 규칙이 있으면 R₀ 가 `ALLOW` 이다. 이때 접기는 아무것도 하지 않고, 실행기는 `answers=[]` 를 돌려준다
(`approvals.py:696-697`, `:711-712` · `executor.py:1329-1356`). 이것은 interactive 에도 있는 지금 동작이고, 결정 Q9-2 에 따라
그쪽은 건드리지 않는다. 에이전트 autonomous 에서는 §5 가 이 경우도 질문으로 보낸다.

### 2.3 Q10b 멈춤 커밋과 재개 (질문 2 의 바탕)

| 무엇 | 지금 | 근거 |
|---|---|---|
| 멈춤 커밋 | `pause_task` 는 **한 트랜잭션**이다. 리스를 검증하고, 런을 잠그고, 판정 이벤트를 쓰고, `coding_tasks` 를 `running → paused` 로 바꾸고, `task.status.changed{status: paused, reason_code}` 를 쓴다. 이벤트는 **최신 체크포인트 id** 를 단다. 새 체크포인트는 쓰지 않는다. **런은 `running` 으로 남는다** | `neos/coding/repositories/run_repository.py:251-308` |
| 멈춤 자리 | 모델 턴의 맨 앞이다. 그 자리의 상태는 최신 체크포인트와 같다 | `neos/coding/loop/_durable/model_turn.py:200-288` |
| 승인 대기 커밋 | `request_tool_approval` 도 한 트랜잭션이다. 다만 **새 체크포인트를 쓴다**(`loop_state` 를 받는다). 도구 단계 한가운데에서 멈추기 때문이다. 그 트랜잭션에서 승인 행 · `running → waiting_approval` · `approval.requested` · `task.status.changed{status: waiting_approval}` 를 함께 쓴다 | `run_repository.py:913-1158` · 부르는 곳 `tools.py:263-282` |
| 재개 라우트 | `POST /coding/tasks/{task_id}/resume` → `CodingRunService.resume` → `resume_paused_task`. 소유 검사 하나로 `paused → running` 을 바꾸고 `task.status.changed{status: running, resumed_by: owner}` 를 쓴다. 그다음 같은 런의 **최신 체크포인트 id** 로 `_wake` 한다 | `neos/api/handlers/standing_pause_handlers.py:72-89` · `neos/coding/application/run_service.py:660-677` · `run_repository.py:310-380` |
| 깨우기 | API 프로세스의 `wake_resumed` 가 슈퍼바이저에 알리거나, Celery 로 `CodingDispatchSource.RESUME` 디스패치를 보낸다 | `neos/coding/runtime.py:917-928` |
| 멈춘 태스크의 가드 | 리스를 얻은 뒤 태스크가 `PAUSED` 면 리스를 놓고 `TaskPaused` 를 던진다. 런이 `running` 이라 리스는 얻어지기 때문이다 | `run_service.py:257-262` · `neos/coding/domain/durability.py:29-31` |
| 루프 결과 인식 | 멈춤 이벤트는 `is_pause_event` 로 알아본다. **부르는 곳이 둘이다**: `run_service.py:355` · `neos/coding/workers/execution.py:139`. 승인 대기는 `CodingLoopWaitingApproval` 예외(`execution.py:92-93`)와 `approval.requested` 이벤트(`:136-138`)로 알아본다 | |
| 조정 스윕 | `claimable_delivery_tokens` 는 `status IN ('queued','running')` 인 태스크만 깨운다. 그래서 `waiting_user` 태스크는 스윕이 깨우지 않는다 | `run_repository.py:512-550` |
| 상태 전이표 | `RUNNING → WAITING_USER` 와 `WAITING_USER → {RUNNING, CANCELLING, EXPIRED}` 가 **이미 있다.** 다만 이 상태로 보내는 코드는 0건이다 | `neos/coding/domain/models.py:41-58` · 분석 F16 행 |
| 승인 만료 | 승인 만료는 태스크를 끝내지 **않는다.** `waiting_approval → running` 으로 돌리고 깨운다. 루프가 `approval_expired` 거절로 이어 간다 | `run_repository.py:1342-1420` · `tools.py:77-81`, `:285-296` |

### 2.4 알림 큐 (Q10b · Q3)

- 워커는 적고 API 프로세스가 꺼내 보낸다. 큐는 `standing_notifications` 다. kind CHECK 는 마이그레이션 085 의 **이름 없는
  인라인 CHECK** `kind IN ('budget_warning','task_paused','question_changed')` 이다
  (`db/migrations/085_add_standing_notifications.sql:30-31`). 코드 쪽 짝은 `NOTICE_KINDS` 다(`neos/standing/notifications.py:34-38`)
- **목적지는 적을 때 `standing_agent_notify_targets` 에서 정한다.** `PostgresNotificationStore.enqueue` 의 SQL 이 대상
  테이블에서 `channel_type`·`channel_id` 를 읽는다. 대상이 없으면 적지 않는다(`notifications.py:263-292`). 📌 **목적지를 직접
  지정하는 길이 없다.** Q9 는 질문을 소유자가 최근에 말한 세션으로 보내야 하므로 이 길이 필요하다(§6)
- 중복 키 `(agent_id, dedupe_key)` 가 유일하다(085 `uq_standing_notifications_dedupe`)
- 드레인 루프는 `standing_agents.enabled ∧ notifications.enabled` 일 때만 API 프로세스 lifespan 이 띄운다(`neos/main.py:329-352`).
  보내기는 `gateway.send_to_channel(channel_type, channel_id, body)` 다. **`thread_id` 는 넘기지 않는다**(`gateway_send` `notifications.py:440-449`, `drain_once` `:414-437`)

### 2.5 채널 게이트웨이와 Q8 스레드

- `ChannelGateway.dispatch` 는 인바운드 멱등(`(session_id, idem)` claim/remember)과 세션 잠금 안에서 `_route` 를 부른다
  (`neos/api/channels/gateway.py:361-421`). 같은 메시지를 재시도하면 처음 결과를 그대로 돌려준다
- `_route` 는 `parse_channel_command` 로 갈래를 나눈다. 일반 텍스트(`CHAT`)는 코딩 바인딩이 있으면 `_steer_bound_chat` 로,
  없으면 `_run_workflow` 로 간다. `/…` 명령은 각자의 갈래로 간다(`gateway.py:423-452`)
- Q8b 의 붙이기 규칙은 `ChannelAgentThreads.open_turn` 에 있다: 플래그 둘 · `metadata["is_dm"] is True` · `mapped_owner`
  (principals 매핑) · `resolve_agent` 로 찾은 `active` 에이전트. 붙으면 `attach_session` 이 get-or-attach 한다
  (`neos/standing/channel_threads.py:129-169`). 바인딩된 세션은 게이트웨이가 이 경로로 보내지 않는다
- 세션 키는 `v2:{channel}:{scope}:{chat}:{thread}` 다. 각 칸은 `:` 를 `_` 로 바꿔 넣는다(`neos/api/channels/session_key.py:6-32`).
  Slack 은 chat 칸에 채널 id 를, thread 칸에 `thread_ts` 나 `-` 를 넣는다(`adapters/slack.py:447-452`). Telegram 은
  `dm`·chat_id·topic 을 넣는다(`adapters/telegram.py:61-66`). Discord DM 은 `dm`·채널·`-` 이다(`adapters/discord.py:624`)
- 게이트웨이는 API 프로세스에만 있다(`main.py:268-325`). Q8 은 "워커가 스레드에 쓸 필요는 Q9 에서 생기고, 그때는 큐로
  넘긴다"고 적었다(Q8 §8)

### 2.6 FE 는 `waiting_user` 를 어떻게 보여 주나 (질문 4)

`web/` 아래에 `waiting_user` 문자열은 **0건**이다(`grep -rn waiting_user web/{app,components,features,lib,hooks,tests}`).

- 투영 리듀서는 `task.status.changed` 의 `payload.status` 를 문자열 그대로 `taskStatus` 에 담는다
  (`web/features/coding/stream/projection-reducer.ts:365-368` · `event-reducer.ts:32-37`). 그래서 상태는 들어온다
- 작업 화면은 `waiting_approval` 배지(`coding-task-workspace.tsx:100`, `:114-121`)와 `paused` 배지 · 재개 버튼(`:68`, `:122-129`)만
  그린다. `waiting_user` 에는 **배지가 없다.** 종결 상태가 아니므로 Stop 버튼은 켜진다(`:43-47`)
- 태스크 목록과 셸은 `task.status` 를 원문 그대로 찍는다(`coding-task-list.tsx:111` · `coding-shell.tsx:84`). 그래서 목록에는
  `waiting_user` 가 글자로 보인다
- 결론: **FE 작업은 필요하지 않다.** 배지도 만들지 않는다(결정 Q-G, §11.2)

## 3. 이름

- 테이블 **`standing_pending_asks`**(095). Q3 의 `standing_questions`(086)와 이름이 겹치지 않는다
- 모듈 `neos/standing/asks.py` · 도메인 타입 **`PendingAsk`** · id 접두 `spa_`
- 코드의 "question"은 이미 Q3 상시 질문(`standing_questions`, 알림 kind `question_changed`)을 뜻한다. 그래서 Q9 의 **코드 이름은
  늘 `ask`** 로 짓는다(`PendingAsk`, `asks.py`, `ask_id`, 설정 `standing_agents.ask`). 계획이 정한 원장 이벤트 kind
  (`question.asked` · `question.answered`)와 알림 kind(`question_asked`)만 예외다. 둘 다 사람이 읽는 어휘이고, 접두어가 Q3 의
  것(`question_changed`)과 다르다
- 사유 코드: `ask_pending`(에이전트에 이미 대기 질문이 있다) · `no_reply_channel`(답할 채널이 없다) · `ask_expired`(§8) ·
  `ask_cancelled`(태스크가 멈춘 뒤 다시 들어왔다)

**이후 Task 들이 그대로 쓰는 이름**(계획 Task 0 "Interfaces"):

| 종류 | 이름 | 비고 |
|---|---|---|
| 테이블 | `standing_pending_asks` (095) | §4 |
| 도메인 | `PendingAsk(ask_id, agent_id, task_id, run_id, tool_call_id, questions, reply_session_id, asked_at, expires_at, answered_at, answers, status)` | `status ∈ {waiting, answered, expired, cancelled}` |
| 원장 이벤트 | `question.asked` · `question.answered` | §9.2. ~~`task.waiting_user`~~ 는 만들지 않는다 → `task.status.changed{status: waiting_user}`(§11.2 Q-A) |
| 알림 kind | `question_asked` · `ask_expired` | 095 가 085 CHECK 를 넓힌다. `ask_expired` 는 계획에 없던 것을 더했다(§11.2 Q-D) |
| 설정 | `standing_agents.ask.{enabled: false, expire_hours: 24}` | §9.1 |

## 4. 데이터 모델 (마이그레이션 095, 안)

```sql
-- 에이전트의 대기 질문. "에이전트당 대기 하나"는 아래 부분 unique 인덱스 하나에만 산다(결정 6 의 모양).
CREATE TABLE IF NOT EXISTS standing_pending_asks (
    ask_id           VARCHAR(64)  PRIMARY KEY,                          -- 'spa_' + hex
    agent_id         VARCHAR(64)  NOT NULL
                     REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    task_id          VARCHAR(64)  NOT NULL
                     REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id           VARCHAR(64)  NOT NULL
                     REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    tool_call_id     VARCHAR(128) NOT NULL,                             -- coding_approvals 와 같은 폭
    questions        JSONB        NOT NULL,                             -- 검증된 ask_user 입력의 questions 그대로
    reply_session_id TEXT         NULL,                                 -- 질문을 보낸 v2 세션. 알림 대상으로 보냈으면 NULL
    status           VARCHAR(16)  NOT NULL DEFAULT 'waiting'
                     CHECK (status IN ('waiting', 'answered', 'expired', 'cancelled')),
    asked_at         TIMESTAMPTZ  NOT NULL,
    expires_at       TIMESTAMPTZ  NOT NULL,
    answered_at      TIMESTAMPTZ  NULL,
    answers          JSONB        NULL,
    CHECK (expires_at > asked_at),
    CHECK ((status = 'answered') = (answered_at IS NOT NULL AND answers IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_pending_asks_one_waiting_per_agent
    ON standing_pending_asks(agent_id) WHERE status = 'waiting';
-- 같은 도구 호출은 질문 하나 -- 재개한 루프가 자기 질문을 찾는 열쇠다(승인의 (task, run, tool_call) 와 같다).
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_pending_asks_call
    ON standing_pending_asks(task_id, run_id, tool_call_id);
CREATE INDEX IF NOT EXISTS ix_standing_pending_asks_due
    ON standing_pending_asks(expires_at) WHERE status = 'waiting';

-- 085 의 인라인 CHECK 를 넓힌다. 이름 없는 인라인 CHECK 의 이름은 Postgres 가 <table>_<column>_check 로 짓는다 [코드 읽기].
-- DROP IF EXISTS + ADD 라서 두 번 적용해도 같다.
ALTER TABLE standing_notifications DROP CONSTRAINT IF EXISTS standing_notifications_kind_check;
ALTER TABLE standing_notifications ADD CONSTRAINT standing_notifications_kind_check
    CHECK (kind IN ('budget_warning', 'task_paused', 'question_changed', 'question_asked', 'ask_expired'));
```

- **`owner_id` 열을 두지 않는다.** 소유 검사는 `standing_agents` 와 `coding_tasks.owner_id` 를 조인해서 한다(Q8 §4 · Q13 §4.3)
- **CASCADE 사슬:** 사용자 삭제 → `standing_agents`(070)와 `coding_tasks`(038)가 CASCADE 로 지워지고, 질문 행이 따라 지워진다.
  Q9a 의 계약 테스트는 실 DB 에서 "사용자 삭제 한 문장 뒤 질문 0행"을 확인한다
- **에이전트 soft delete 는 질문을 건드리지 않는다.** 결정 2(Q13): 이미 도는 태스크는 건드리지 않는다. 지워진 에이전트는
  `resolve_agent` 가 돌려주지 않으므로 답이 닿을 수 없다. 그 질문은 만료(§8)가 정리한다
- **구현 전에 확인할 것:** 085 CHECK 의 실제 이름. 테스트 DB 에서 `pg_constraint` 로 읽는다. 이름이 다르면 `DROP IF EXISTS` 는
  침묵하고 넓힌 CHECK 와 옛 CHECK 가 함께 남는다. 그러면 `question_asked` 가 옛 CHECK 에 걸려 실패한다. 이것은 메모리
  guarded-migrations-need-hoisting 과 같은 모양의 침묵이므로, Q9a 의 "신선한 DB 2회 적용" 테스트가 `question_asked` 를 실제로
  한 줄 넣어 본다

### 4.1 저장소 프로토콜 (`neos/standing/asks.py`, Q9a)

```python
class PendingAskStore(Protocol):
    async def open(self, *, agent_id, task_id, run_id, tool_call_id, questions,
                   reply_session_id, expires_at) -> PendingAsk | None   # 대기 중이 있으면 None
    async def waiting_for_agent(self, agent_id) -> PendingAsk | None
    async def answer(self, ask_id, answers) -> PendingAsk | None         # waiting 일 때 한 번만
    async def expire_due(self, now) -> list[PendingAsk]
    async def for_call(self, task_id, run_id, tool_call_id) -> PendingAsk | None   # 더함(§11.1 ③)
```

- 메모리 구현과 Postgres 구현이 **같은 계약**을 지킨다(`tests/standing/test_pending_asks_contract.py`)
- **원장에 닿는 트랜잭션은 코딩 저장소에 둔다**(§9.2). Postgres 구현의 쓰기 셋(`open`·`answer`·`expire_due`)은
  `*_in_session(session, …)` 함수로 SQL 을 갖고, `PostgresCodingRunRepository` 의 새 메서드가 **같은 세션**에서 그것을 부른다.
  `standing_pending_asks` 의 SQL 은 `asks.py` 한 곳에만 있다. 코딩 저장소는 트랜잭션과 원장을 맡는다

## 5. 판정 — 루프는 언제 묻는가 (Q9a)

**바꾸는 자리는 `ToolExecutionMixin._approval_gate_step` 하나다**(`tools.py:232`). `fold_for_unattended` 와 `approvals.py` 는
**고치지 않는다.** 접기는 "좁히기만 한다"는 계약을 지키고, 규칙 사본이 생기지 않는다(`approvals.py:218-226` 독스트링).

```python
# neos/coding/loop/_durable/tools.py (안)
def _answerable_ask(self, input, validated) -> bool:
    """에이전트 autonomous 태스크의 ask_user -- 답할 사람이 채널에 있다(Q9)."""
    return (
        validated.name == "ask_user.v1"
        and getattr(input, "mode", "interactive") == "autonomous"   # background 는 천장이 먼저 거절한다(Q9-1)
        and getattr(input, "agent_id", None) is not None            # 사람이 연 autonomous 는 지금처럼 DENY
        and self._asks is not None                                   # None 이 off (§9.1)
    )
```

`_approval_gate_step` 은 `_answerable_ask` 가 참일 때만 **질문 갈래**로 간다. 거짓이면 지금 코드를 한 줄도 바꾸지 않고 탄다.
interactive 는 바이트 단위로 같다(결정 Q9-2).

질문 갈래는 이 순서로 간다. 승인 갈래(`tools.py:242-306`)와 같은 뼈대다. **판정이 먼저, 기록 조회가 나중이다.**

1. **판정.** `_evaluate_call(…, unattended=False, read_only_ceiling=_background(input))` 으로 판정한다. 접기만 빠지고 나머지 사슬은
   그대로 탄다: 사용자 block, deny 목록, Jev 밴딩(켜져 있으면), 소유자 규칙. 운영자의 전역 `approval_unattended` 는
   `_approval_gate` 가 계속 OR 하므로 그것이 켜져 있으면 여전히 DENY 로 접힌다(운영자가 좁힌 것을 Q9 가 넓히지 않는다)
   - `DENY` → 지금처럼 `_commit_denied_tool(policy_denial_reason(…))`
   - `ALLOW` 나 `REQUIRE_APPROVAL` → 질문으로 간다. **ALLOW 도 질문으로 보낸다.** 답 없는 `ask_user` 실행은 빈 답이기 때문이다(§2.2 📌)
2. **기존 질문.** `asks.for_call(task_id, run_id, tool_call_id)`
   - `answered` → `_with_answers(validated, ask.answers)` 를 거쳐 실행으로 간다(§7.3)
   - `waiting` → `CodingLoopWaitingUser(ask_id)` 를 던진다. 승인의 `CodingLoopWaitingApproval` 과 같은 자리다(`tools.py:281-282`)
   - `expired` → `ask_expired` 거절. `cancelled` → `ask_cancelled` 거절(§8 · §11.2 Q-C)
3. **답할 곳.** `asks.reply_destination(agent_id, owner_id)` 가 None 이면 → `no_reply_channel` 거절. 대기하지 않는다(§6.1)
4. **커밋.** `deps.repository.request_user_answer(…)` — 한 트랜잭션이다(§9.2). None 이 돌아오면 이미 대기 질문이 있는 것이다 →
   `ask_pending` 거절. 이 태스크는 계속 돈다(Review Focus 3). 성공하면 커밋 이벤트를 `_Halt` 로 낸다

- **트랜잭션 모양은 승인 대기와 같고, Q10b 멈춤과 다르다.** 새 체크포인트를 쓴다(`loop_state = self._dump_state(input, state)`).
  묻는 자리가 모델 턴의 맨 앞이 아니라 **도구 단계 한가운데**이기 때문이다. `pause_task` 는 "그 자리의 상태가 최신 체크포인트와
  같다"는 전제로 체크포인트를 쓰지 않는데(`model_turn.py:203-205`), 도구 단계에서는 그 전제가 서지 않는다. 그래서
  `request_tool_approval` 을 따른다(`run_repository.py:1012-1045`). **런이 `running` 으로 남는 것**은 둘 다 같다
- **거절은 이미 있는 `_commit_denied_tool` 로 한다.** `denial_envelope` 는 이 코드들에 `denied_by: "policy"` 를 단다
  (`approvals.py:1016-1022`). 같은 질문을 되풀이하면 기존 정체 규칙 `policy_stall_denied` 가 세 번째부터 막는다
  (`signatures.py:38-50`, `STALL_DENY_AFTER = 3`)
- **도구 설명을 고친다**(`registry.py:1003-1009`): "On ask_pending or no_reply_channel, continue without the answer; do not
  retry." 도구 설명을 고정하는 테스트가 있으면 그것도 같이 고친다
- `_with_approval_answers` 를 **`_with_answers(validated, answers)`** 로 일반화한다. 승인 갈래도 이것을 부른다. 답을 싣는
  사본이 둘이 되지 않게 하려는 것이다(메모리 fixes-land-in-one-caller-only). 승인 쪽 동작은 바뀌지 않는다

### 5.1 루프 밖 두 자리 — 멈춤과 같은 길을 낸다

`is_pause_event` 를 부르는 곳이 둘이었다(§2.3). `WAITING_USER` 도 두 곳 모두에 닿아야 한다.

| 자리 | 바꾸는 것 |
|---|---|
| `CodingRunService.advance_one_safe_point` (`run_service.py:257-262`) | 리스를 얻은 뒤 태스크가 `WAITING_USER` 면 리스를 놓고 `TaskWaitingUser` 를 던진다(`TaskPaused` 옆). 이어 달리기 디스패치가 대기 중 태스크를 한 걸음 밀지 못하게 한다 |
| `run_service.py:355` 의 이벤트 루프 | `question.asked` 는 체크포인트 id 를 달고 있으므로 지금의 "체크포인트 이벤트면 리스를 놓고 돌려준다" 갈래에서 이미 멈춘다. 따로 고칠 것이 없는지 Q9a 테스트로 확인한다 |
| `CodingTaskExecutor` (`execution.py:92-95`, `:136-141`) | `CodingTaskOutcome.WAITING_USER` 를 더한다. `CodingLoopWaitingUser`·`TaskWaitingUser` 예외와 `question.asked` 이벤트를 그 결과로 바꾼다. 이것이 없으면 `CONTINUING` 이 되어 이어 달리기가 나간다(`:142-143`) |

## 6. 보내기 — 어디로, 무엇을 (Q9b)

### 6.1 답할 곳 (`reply_destination`)

```python
async def reply_session_for(agent_id: str) -> ThreadSession | None:
    """소유자가 가장 최근에 user 턴을 남긴, 지금 활성 스레드에 붙은 채널 세션(웹 제외)."""
```

- **턴은 에이전트의 모든 스레드에서 보고, 세션은 활성 스레드에 붙은 것만 고른다.** `/new` 회전은 세션 행을 새 스레드로 옮기지만
  턴은 보관된 스레드에 남긴다(Q8 §7). 활성 스레드의 턴만 보면 회전 직후에는 답할 세션이 없어진다
  ```sql
  SELECT s.session_id, s.channel_type
  FROM standing_agent_thread_turns turn
  JOIN standing_agent_threads t      ON t.agent_thread_id = turn.agent_thread_id AND t.agent_id = :agent_id
  JOIN standing_agent_thread_sessions s ON s.session_id = turn.session_id
  JOIN standing_agent_threads active ON active.agent_thread_id = s.agent_thread_id
                                     AND active.agent_id = :agent_id AND active.archived_at IS NULL
  WHERE turn.role = 'user' AND s.channel_type <> 'web'
  ORDER BY turn.turn_id DESC LIMIT 1
  ```
- 세션이 없으면 **알림 대상**(`standing_agent_notify_targets`)으로 간다. 이때 `reply_session_id` 는 NULL 이다
- **답할 수 없는 곳으로는 묻지 않는다.** 목적지 채널에 대해 `channels.principals` 가 소유자를 매핑하지 않으면 그 목적지는
  없는 것으로 친다. 그러면 답이 와도 §7 이 알아보지 못하고 질문은 만료까지 매달린다
- 셋 다 없으면 None 이다 → `no_reply_channel`
- **세션 → 보낼 주소.** 세션 키에서 `chat` 과 `thread` 칸을 읽는 함수 하나를 `session_key.py` 의 `build_session_key` 옆에 둔다
  (`session_key_destination(session_id) -> (channel_type, chat, thread | None) | None`). `v2:` 가 아니면(`web:` 등) None 이다.
  Q8 의 "세션 키를 파싱해서 DM 을 추측하지 않는다"는 DM 판정에 대한 규칙이고, 여기서는 DM 여부를 추측하지 않는다(붙은 세션은
  이미 DM 이다). 다만 `_part` 가 `:` 를 `_` 로 바꾸므로 거꾸로 읽기는 손실이 있을 수 있다(§11.2 Q-E)

### 6.2 알림 (`question_asked`)

- 본문(**Q9b 가 실제로 보내는 문구**, `neos/standing/asks.py` `question_notice`, 2026-10-05): 질문이 하나면 질문 그대로, 둘
  이상이면 `1. …` `2. …` 로 번호를 단다. 선택지는 각 질문 아래에 `   a) …` `   b) …` 로 붙인다. 빈 줄 뒤에, 질문이 둘 이상이면
  `Answer one line per question, in order.` 를, 맨 끝에 `Reply in this chat to answer.` 를 둔다. 상한(`notifications.max_body_chars`)을
  넘으면 질문 쪽을 `bounded_body` 로 자르고 안내 줄은 남긴다. 예:
  ```
  1. Which branch?
  2. Run tests?
     a) yes
     b) no

  Answer one line per question, in order.
  Reply in this chat to answer.
  ```
  답 나누기(§7.2)는 이 문구에 맞춘다 — 줄마다 하나, 앞의 `1.`·`1)` 번호는 뗀다
- 중복 키 `question:{ask_id}`
- **목적지를 직접 지정하는 적기**가 필요하다(§2.4 📌). `NotificationStore` 에 `enqueue_to(notice, target, *, now)` 를 더하고,
  Postgres 쪽에는 같은 SQL 의 `*_in_session` 변형을 둔다. 기존 `enqueue` 는 그대로 둔다
- 드레인은 `thread_id` 없이 보낸다(§2.4). 답할 세션이 Slack 스레드(`thread` 칸이 `-` 가 아님)이면 질문은 부모 DM 에 간다.
  답은 §7.1 의 "붙는 DM 이면 된다" 규칙으로 받으므로 동작은 맞다. 다만 Slack 스레드 안에서 묻고 싶으면 `standing_notifications`
  에 `thread_id` 열이 있어야 한다. **이번에는 하지 않는다**(§11.2 Q-E)
- **질문 행과 알림 행은 같은 트랜잭션에 쓴다**(§9.2). 따로 쓰면, 질문 커밋 뒤 알림 쓰기 전에 워커가 죽었을 때 태스크는
  `waiting_user` 인데 질문은 나가지 않는다. 그런데 `waiting_user` 태스크는 조정 스윕이 깨우지 않으므로(§2.3) 아무도 그것을 다시
  적지 않고, 질문은 만료까지 조용히 매달린다. 계획의 `enqueue_question(notice_store, ask) -> bool` 은 같은 함수의 독립 실행판으로
  남는다. 테스트와 중복 키 확인에 쓴다
- **워커는 게이트웨이를 부르지 않는다.** Q9b 테스트는 게이트웨이 호출 0회를 확인한다

## 7. 답 받기와 재개 (Q9c)

### 7.1 무엇이 답인가

게이트웨이의 `_route` 맨 앞, `CHAT` 갈래의 첫 줄에서 **따로 이름 붙인 작은 함수** `_answer_waiting_question` 을 부른다
(Q9c 착지 모양). 바인딩 확인은 그 함수 안에서 한다 — 바인딩된 세션이면 None. 트랙 Q15 가 `_route` 앞단에 전사 단계를 더하므로,
통합(Phase C)은 **전사 → 답 확인** 순서로 둔다:

```python
if command.kind is ChannelCommandKind.CHAT:
    answered = await self._answer_waiting_question(message)   # 바인딩·플래그·실패는 None
    if answered is not None:
        return answered                       # 확인 문구. 워크플로우는 돌지 않는다
    binding = await self._binds.get(message.session_id)
    ...
```

다음을 **전부** 만족할 때만 답이다. 하나라도 어긋나면 지금과 똑같이 대화로 간다.

1. `ask_effective(config)` 이 참이다(§9.1)
2. **`CHAT` 이다.** `/new` 같은 명령과 모르는 `/…` 는 답이 아니다(갈래가 다르다)
3. **바인딩된 세션이 아니다.** 바인딩된 세션의 말은 그 코딩 태스크의 조향이다. Q8 §5 규칙 5 와 같은 이유다
4. **Q8 의 붙이기 규칙을 통과한다**: DM(`metadata["is_dm"] is True`) · `mapped_owner` · `resolve_agent` 가 돌려준 `active` 에이전트.
   그리고 `attach_session` 이 그 에이전트의 활성 스레드를 돌려준다. **이미 붙어 있을 필요는 없다.** 이번 메시지로 붙어도 된다
   (§11.1 ①)
5. `waiting_for_agent(agent.agent_id)` 가 질문을 돌려주고, 그 태스크가 아직 `waiting_user` 다(§7.3 의 트랜잭션이 확인한다)

- **Review Focus 1(다른 채널의 답):** Slack 으로 물었어도 소유자의 Telegram DM 은 4번을 통과하면 답이다. 질문 행에는 "어느 세션에서
  답해야 한다"가 없다. `reply_session_id` 는 보낸 곳의 기록일 뿐이다
- **Review Focus 2(엉뚱한 말):** 권고대로 질문 대기 중 소유자의 다음 DM 은 무엇이든 답이 된다. 그래서 확인 문구에 질문을 싣는다:
  ```
  Answer recorded — resuming.
  Q: <첫 질문 prompt, 120자에서 자름>(+N more)
  ```
  잘못 답했으면 사용자가 태스크를 멈출 수 있다(Stop). 되돌리기는 하지 않는다
- **경합:** 두 채널에서 동시에 답이 오면 `answer` 의 `WHERE status = 'waiting'` 이 하나만 통과시킨다. 진 쪽 메시지는 보통 대화로
  간다. 같은 메시지의 재시도는 게이트웨이의 인바운드 멱등이 처음 결과를 돌려주므로 재개는 한 번이다(`gateway.py:376-381`, `:397-402`)
- **그룹 채널 · 미매핑 · 다른 소유자의 메시지**는 4번에서 떨어진다

### 7.2 답 → `answers` 목록

`ask_user_answers_complete` 는 질문 수만큼 비지 않은 답을 요구한다(`approvals.py:202-212`). 채널 메시지는 하나다.

- 질문이 하나면 `answers = [text]`
- 둘 이상이면 비지 않은 줄로 나눈다. 앞의 `1.`·`1)` 번호를 떼고, 줄 수가 질문 수와 같으면 그것을 순서대로 쓴다. 다르면 **모든
  질문에 메시지 전체**를 답으로 준다. 모델은 `pairs` 로 어떤 답이 어디에 갔는지 본다
- 선택지(`options`)는 맞춰 보지 않는다. 자유 답을 그대로 넘긴다(결정 3: 질문은 자유 답)
- 결정 Q-B(2026-10-05, §11.2)로 닫혔다

### 7.3 재개 — Q10b 재개 경로를 그대로 쓴다 (질문 2)

1. **한 트랜잭션** `PostgresCodingRunRepository.answer_user_question(ask_id, owner_id, answers, now)`. 모양은
   `resume_paused_task`(`run_repository.py:310-380`)와 `resolve_tool_approval`(`:1186-1335`)을 섞은 것이다:
   - 질문 행을 `FOR UPDATE` 로 잠근다. 조건은 `status = 'waiting'`, 태스크의 `owner_id = :owner_id`, 에이전트의 `owner_id` 가
     같고 `deleted_at IS NULL` 이다
   - `answer_in_session` 으로 `answered` · `answered_at` · `answers` 를 적는다
   - `UPDATE coding_tasks SET status = 'running' … WHERE task_id = :task_id AND status = 'waiting_user'`. **0행이면 롤백**하고
     None 을 돌려준다. 그 사이 사람이 멈췄거나 만료된 것이다. 메시지는 보통 대화로 간다
   - `question.answered{ask_id, channel_type}` + `task.status.changed{status: running, resumed_by: "answer"}`. 두 이벤트 모두
     **같은 런의 최신 체크포인트 id** 를 단다(`resume_paused_task` 의 서브쿼리 `:337-354` 와 같다). 런은 한 번도 닫히지 않았다
2. **`CodingRunService.resume_answered(...)`** 가 그 트랜잭션을 부르고, `resume` 과 똑같이 `self._wake(task_id, checkpoint_id)`
   한다(`run_service.py:660-677`). 깨우기 실패는 로그만 남긴다. 태스크가 `running` 이므로 조정 스윕이 찾는다. 게이트웨이는 이 서비스를
   `neos.coding.runtime.coding_run_service` 로 얻는다(`coding_bridge.py:33-36` 와 같은 방식)
3. 깨어난 워커는 최신 체크포인트를 복원한다. 그 체크포인트는 §5 의 커밋이 쓴 것이고 `pending_tool_calls` 의 머리가 그
   `ask_user.v1` 이다. 도구 단계는 §5 의 1 → 2 로 가서 `answered` 를 찾는다
4. **답이 도구 입력에 닿는 자리:** `_with_answers(validated, ask.answers)` 다. 지금의 `_with_approval_answers`(`durable.py:367-376`)와
   같은 모양이다 — **검증 뒤에** `input["answers"]` 를 합친다. 모델은 스키마로 `answers` 를 넣을 수 없으므로(`extra="forbid"`)
   이 길이 답의 유일한 입구다. 그다음 실행기 `_ask_user` 가 `pairs` 를 만든다(`executor.py:1329-1356`)
5. **스레드 기록(Q8):** 커밋이 성공하면 게이트웨이 쪽 처리기가 질문을 assistant 턴으로, 답을 user 턴으로 에이전트 스레드에 적는다.
   멱등 키는 질문 `ask:{ask_id}`, 답은 인바운드 `idempotency_key` 다. 질문 턴의 세션은 `reply_session_id` 이고, NULL 이면 답한
   세션이다. **기다리는 동안에는 질문 턴이 필요 없다.** 그동안 오는 소유자의 DM 은 전부 답이기 때문이다. 그래서 워커가 스레드에 쓸
   필요가 사라진다(Q8 §8 의 "워커에서 돌지 않는다"를 지킨다). 쓰기 실패는 Q8 §8 처럼 경고 + `standing_thread_failures_total{op}` 로
   남기고 답은 그대로 처리한다

📌 **Q10b 재개 라우트(`POST /coding/tasks/{id}/resume`)는 `waiting_user` 를 재개하지 않는다**(`409 task_not_paused` 그대로).
대기 중 태스크를 깨우는 것은 답뿐이다. 사람이 손으로 재개하면 답 없이 깨어나고, §5 의 2 에서 `waiting` 을 다시 만난다.

## 8. 만료 (Q9d) — 태스크를 끝내지 않는다 (결정 Q-C)

**승인 만료의 전례를 따른다**(`run_repository.py:1342-1420`): 만료는 태스크를 `running` 으로 돌리고 깨운다. 루프는 `ask_user.v1`
에 `ask_expired` 거절을 돌려주고 답 없이 이어 간다. `WAITING_USER → EXPIRED` 전이와 런 닫기는 **쓰지 않는다.**

- Celery beat 폴러 `expire_standing_asks`(60초)다. 등록은 `configure_standing_ask_beat_schedule(schedule, *, enabled)` 하나로 한다.
  Q3 의 `configure_standing_question_beat_schedule`(`neos/workflow/celery_app.py:227-235`)과 같은 모양이고, `enabled` 는
  `ask_effective(config)` 다
- 한 트랜잭션 `expire_user_questions(limit, now)`: `ix_standing_pending_asks_due` 로 `FOR UPDATE SKIP LOCKED` 해서 꺼낸다(승인 만료
  `run_repository.py:1352-1358` 와 같다) → 질문 `expired` → 태스크 `waiting_user → running` →
  `task.status.changed{status: running, reason_code: ask_expired}`(새 kind 없음, 결정 Q-A). 이벤트는 같은 런의 최신 체크포인트 id 를 단다.
  트랜잭션 뒤에 `_wake` 한다(승인 만료 `approval_service.expire_pending` 과 같다)
- 깨어난 루프는 §5 의 2 에서 `expired` 를 찾고 `ask_expired` 로 거절한다. 이 거절 갈래는 Q9a 가 이미 만든다
- 같은 트랜잭션에서 알림 `ask_expired`(결정 Q-D)를 한 줄 적는다. 목적지는 그 질문의 `question:{ask_id}` 알림 행과 같은 곳이다
  (`INSERT … SELECT channel_type, channel_id FROM standing_notifications WHERE agent_id = … AND dedupe_key = 'question:' || ask_id`).
  중복 키는 `ask_expired:{ask_id}` 다
- **이미 답한 질문은 만료하지 않는다**(`WHERE status = 'waiting'`). 태스크가 이미 `waiting_user` 가 아니면(취소 등) 질문만 `expired` 로
  닫고 태스크는 건드리지 않는다

### 8.1 대기 중 취소

`WAITING_USER → CANCELLING` 은 전이표에 있다. 그런데 Stop 경로 `mark_task_cancelled`(`run_repository.py:233-249`)는 질문 행을 모른다.
**질문을 두고 태스크만 취소하면, 그 `waiting` 행이 부분 unique 인덱스를 쥐고 있어서 그 에이전트의 다음 질문이 만료 때까지 전부
`ask_pending` 이 된다.** 그래서 Q9a 는 `mark_task_cancelled` 의 같은 트랜잭션에서
`UPDATE standing_pending_asks SET status = 'cancelled' WHERE task_id = :task_id AND status = 'waiting'` 를 한다. 태스크를
`waiting_user` 밖으로 보내는 곳은 넷이다: 답(§7.3) · 만료(§8) · 취소(여기) · 태스크 삭제. 삭제는 종결 상태만 지울 수 있으므로
(`task_repository.py:76`) 해당하지 않는다. Q9a 는 이 넷을 이름으로 세는 테스트를 둔다(메모리 verify-by-name-not-by-count).

## 9. 설정 · 원장 · 배선

### 9.1 설정

```python
class StandingAskConfig(StrictConfigModel):
    enabled: bool = False
    expire_hours: int = Field(default=24, ge=1)

class StandingAgentsConfig(StrictConfigModel):
    ...
    ask: StandingAskConfig = Field(default_factory=StandingAskConfig)
```

- **켜졌는지는 함수 하나가 정한다:** `ask_effective(config) = standing.enabled ∧ ask.enabled ∧ notifications.enabled ∧ threads.enabled`.
  알림이 꺼져 있으면 질문이 나가지 않고(드레인이 없다, `main.py:329-352`), 스레드가 꺼져 있으면 답을 알아볼 수 없다(§7.1 의 4).
  둘 중 하나라도 꺼져 있는데 `ask.enabled` 만 켜져 있으면 **지금처럼 DENY** 다. 기동 때 경고 한 줄을 남긴다. 스키마 검증으로
  막지는 않는다 — 프로파일 하나를 켜는 순서가 기동을 깨지 않게 한다
- 루프는 설정을 읽지 않는다. **포트는 늘 배선한다**(Q9b): `_prepare_real_coding_loop` 가 `build_agent_asks(config, …)` 로 포트를
  만들어 넘기고, 켜졌는지는 포트의 `enabled()` 가 **호출 때마다** `ask_effective(config)` 로 본다. 꺼져 있으면 에이전트 태스크도
  지금처럼 무인 DENY 다(배선된 실제 포트로 시험한다). 게이트웨이 쪽(`build_channel_ask_answers`)도 늘 배선하고 플래그를 호출 때마다
  읽는다. 테스트에서 `asks=None` 은 여전히 off 다
- `StrictConfigModel` 은 모르는 키를 거절한다. 그래서 development 프로파일에서 켜는 일은 스키마 키가 착지한 **뒤에**, 통합 단계에서
  오케스트레이터가 한다(계획 Global Constraints). 서브에이전트는 `config/neos.development.yaml` 을 고치지 않는다
- 계측: `standing_ask_total{outcome}`(Q9c 가 착지시켰다, 2026-10-05 통제자 결정) — `asked`·`refused_pending`·`refused_no_channel`
  (루프의 질문 갈래) · `lookup_failed`(답할 곳 조회 실패, `resolve_reply_destination`) · `answered`(게이트웨이의 답) · `expired`(Q9d 가 더한다).
  값은 `neos/standing/asks.py` `ASK_OUTCOMES` 한 곳에 있다. 다른 standing 카운터처럼
  `neos_` 접두를 붙이지 않는다

### 9.2 원장 이벤트와 FE fixture (질문 3)

| 트랜잭션 | 위치 | 이벤트 |
|---|---|---|
| 묻기 | `PostgresCodingRunRepository.request_user_answer` | `question.asked{ask_id, tool_call_id, questions(prompt 목록), expires_at, reply_channel_type}` → `task.status.changed{status: waiting_user}` |
| 답 | `…answer_user_question` | `question.answered{ask_id, channel_type}` → `task.status.changed{status: running, resumed_by: answer}` |
| 만료 | `…expire_user_questions` | `task.status.changed{status: running, reason_code: ask_expired}` (결정 Q-C — 태스크는 이어 간다) |

- **세 트랜잭션 모두 `neos/coding/` 아래에 둔다.** `tests/coding/test_event_kinds.py` 는 `neos/coding` 의 `event_type=` 키워드를
  AST 로 훑어 fixture 와 **정확히 일치**하는지 본다(`test_event_kinds.py:14-22`, `_CODING_ROOT`). `neos/standing/` 에서 원장에 쓰면
  스캐너가 보지 못하고 **조용히 통과**한다. 그래서 원장 쓰기를 `asks.py` 에 두지 않는다(§4.1)
- **fixture 갱신이 필요하다. 파일은 하나이고, 읽는 쪽이 둘이다.** `tests/fixtures/coding_event_kinds.json` 에 `question.asked`·
  `question.answered` 두 항목을 더한다. 백엔드(`tests/coding/test_event_kinds.py`)는 더하지 않으면 빨개진다. 프론트
  (`web/tests/source/coding-event-kinds.test.ts`)는 각 kind 가 투영되는지(`projected: true`) 아니면 커서만 움직이는지
  (`projected: false` + `reason`)를 양방향으로 본다
  - 둘 다 **`projected: false`** 로 둔다. 이유: 화면이 볼 상태 변화는 같은 트랜잭션의 `task.status.changed` 가 이미 투영한다
    (`projection-reducer.ts:365-368`). 질문과 답의 본문은 채널에 있고, 답은 뒤따르는 `tool.completed` 의 `pairs` 에 실린다.
    `budget.judged`·`monitor.judged` 의 면제 이유와 같은 모양이다
  - 그래서 **FE 코드는 고치지 않는다.** 다만 fixture 가 FE 테스트의 입력이므로 Q9a 는 **FE 테스트를 실제로 돌려** 통과를 확인한다
  - `task.status.changed` 는 이미 fixture 에 있다. `waiting_user` 는 `status` 값일 뿐 새 kind 가 아니다(결정 Q-A)
- `CodingEvent` 는 FE 로 간다. 그래서 payload 에 **채널 id 와 세션 키를 싣지 않는다.** 채널 종류만 싣는다

## 10. 단계 — 전부 플래그 off 로 착지한다

development 에서 켜는 것은 통합 단계(Phase C)에서 오케스트레이터가 한다.

| 단계 | 무엇 | 테스트가 확인할 것 | 선행 |
|---|---|---|---|
| **Q9a** ✅ **착지(2026-10-05)** | 마이그레이션 095(§4) · `neos/standing/asks.py`(메모리·Postgres 저장소, `*_in_session`) · `request_user_answer` 트랜잭션 · `_approval_gate_step` 질문 갈래(§5) · `_with_answers` 일반화 · `TaskWaitingUser`·`CodingLoopWaitingUser`·`CodingTaskOutcome.WAITING_USER` 두 자리(§5.1) · 취소가 질문을 닫는다(§8.1) · `StandingAskConfig` · `ask_effective` · 도구 설명 · fixture 두 항목 | **계약(메모리·Postgres 같은 것):** 에이전트당 대기 하나 — **실 DB 에서 동시 `open` 둘 → 하나만**(Review Focus 3) · `answer` 는 한 번(둘째는 None) · `for_call` · 사용자 삭제 한 문장으로 0행(CASCADE) · 신선한 DB 2회 적용 + `question_asked` 알림 한 줄이 들어간다(§4 CHECK 이름) · **루프:** (a) 에이전트 autonomous → `WAITING_USER`, 도구 결과 없음, 런 `running`, 새 체크포인트의 머리가 그 호출 (b) interactive → 지금과 바이트 동일(승인 카드) (c) background → `policy_mode_ceiling` 그대로 (d) 사람이 연 autonomous(`agent_id` None) → 지금처럼 DENY (e) 대기 질문이 이미 있으면 `ask_pending` 거절이고 **그 태스크는 다음 단계를 계속 돈다** (f) 답할 곳이 없으면 `no_reply_channel`, 대기하지 않는다 (g) allow 목록에 있어도 질문으로 간다 (h) `ask_effective` 가 거짓이면 지금과 같다 (i) `waiting` 질문이 있는 태스크에 이어 달리기가 와도 모델을 부르지 않는다 (j) 대기 중 취소 → 질문 `cancelled`, 다음 질문이 열린다 · `test_event_kinds.py` 와 FE `coding-event-kinds.test.ts` 통과 | Q8 ✅ |
| **Q9b** ✅ **착지(2026-10-05)** | `reply_session_for`(§6.1) · `session_key_destination` · `enqueue_to` + `*_in_session` · 알림 본문 · `request_user_answer` 가 같은 트랜잭션에서 알림을 적는다 | 최근 말한 세션 고르기(두 채널 중 나중 것) · **회전 뒤에도 옛 턴으로 세션을 고른다** · 붙은 세션이 없으면 알림 대상 · principals 가 그 채널의 소유자를 매핑하지 않으면 그 목적지는 없다 · 둘 다 없으면 None · 같은 질문을 두 번 적어도 한 줄(중복 키 `question:{ask_id}`) · 질문 행과 알림 행은 함께 있거나 함께 없다 · 워커에서 게이트웨이 호출 0회 · 본문에 선택지와 "Reply in this chat to answer." | Q9a |
| **Q9c** ✅ **착지(2026-10-05)** | 게이트웨이 `_route` 의 답 갈래(§7.1) · `neos/standing/ask_answers.py` · `answer_user_question` 트랜잭션 · `CodingRunService.resume_answered` · 스레드에 질문·답 턴 · `main.py` 배선(늘 배선하고 플래그는 호출 때마다 읽는다) | **실제 게이트웨이로:** **Review Focus 1** Slack 으로 묻고 Telegram DM 으로 답한다 → 재개(wake 한 번, 런 같음, 체크포인트 = 최신) · **Review Focus 2** 확인 문구에 질문 요약이 들어 있다 · `/new` 등 명령은 답이 아니다 · 미매핑 발신자 · 다른 소유자 · 그룹 채널 · 바인딩된 세션의 메시지는 답이 아니고 지금과 같이 흐른다 · 같은 인바운드 재시도(멱등 키)는 재개 한 번 · 두 채널 동시 답 → 답 하나 · 알림 대상으로 물었고 아직 붙지 않은 DM 의 답도 답이다 · 스레드에 질문(assistant)·답(user) 턴 · 답 뒤 루프가 `answers` 를 도구 입력에 싣고 `pairs` 가 맞다 · 태스크가 이미 `waiting_user` 가 아니면 답이 아니다 | Q9b |
| **Q9d** | `expire_user_questions` · Celery 태스크와 `configure_standing_ask_beat_schedule` · `docs/CONFIGURATION.md` 영어 절 하나 · 이 문서 단계표 | 만료 시각이 지나면 질문 `expired` + 태스크 `waiting_user → running` + wake 한 번 + 루프가 `ask_expired` 거절로 이어 간다 + 알림 한 줄(질문과 같은 목적지) · 런은 닫히지 않는다 · 이미 답한 질문은 만료하지 않는다 · 취소된 태스크의 질문은 태스크를 건드리지 않고 닫힌다 · 두 폴러가 동시에 돌아도 만료 한 번(SKIP LOCKED) · 플래그 off 면 beat 등록이 없다 | Q9c |

- 실 DB 테스트의 사용자 id 접두는 `test_q9_` 다(병렬 트랙과 테스트 DB 를 공유한다)
- **Q9a 가 설계에서 바꾼 것**(2026-10-05): ① fixture 에는 `question.asked` 하나만 더했다. `question.answered` 를 쓰는 코드는
  Q9c 가 만든다 — 코드 없이 fixture 에 먼저 넣으면 `tests/coding/test_event_kinds.py` 가 "fixture 에 있는데 소스에 없다"로 빨개진다
  ② 루프 포트(`AgentAsks`)의 조립(`_prepare_real_coding_loop`)은 Q9b 로 미뤘다. 포트의 `reply_destination` 이 Q9b 의
  `reply_session_for` 이고, 그것 없이 배선하면 늘 `no_reply_channel` 이다. 그래서 Q9a 만으로는 플래그를 켜도 질문하지 않는다
  ③ 저장소 계약에 `cancel_for_task` 를 더했다(§8.1 의 취소). `open` 은 `asked_at` 도 받는다(호출자의 시계)
  ④ `NOTICE_KINDS` 에 `question_asked`·`ask_expired` 를 미리 더했다 — 095 CHECK 와 코드가 짝을 이루게(테스트가 둘을 비교한다)
  ⑤ 085 CHECK 의 실제 이름은 테스트 DB 에서 `standing_notifications_kind_check` 로 확인했다(2회 적용 테스트가 그 이름 하나만 남는지 본다)
  ⑥ 질문 갈래의 `mode == autonomous` 조건은 background 에 대해서는 두 겹째 방어다 — background 는 갈래에 들어와도 천장
  (`read_only_ceiling`)이 `policy_mode_ceiling` 으로 거절한다. 그래서 "background 를 갈래에 넣기" 변이 하나만으로는 죽지 않고, 갈래의
  천장까지 함께 지운 변이가 죽는다
- **Q9b 가 설계에서 바꾼 것**(2026-10-05): ① **루프 포트는 늘 배선한다**(`_prepare_real_coding_loop` → `build_agent_asks`).
  켜졌는지는 포트의 `enabled()` 가 호출 때마다 `ask_effective(config)` 로 본다 — §9.1 의 "`ask_effective` 일 때만 만든다"를 바꿨다.
  그래서 "포트가 배선됐고 플래그가 꺼짐"이 실제 조합이 되고, 그 조합이 지금과 같다는 것을 실제 포트로 시험한다(행 (h))
  ② 질문 id 는 루프가 먼저 만든다(`new_ask_id`) — 알림의 중복 키 `question:{ask_id}` 가 질문 커밋 **전에** 필요하다. `open`·
  `open_in_session`·`request_user_answer` 가 `ask_id` 를 받는다 ③ `request_user_answer` 는 `notice`·`notice_target` 을 받아
  같은 트랜잭션에서 `enqueue_to_in_session` 으로 적는다. 알림을 못 쓰면 질문도 없다(실 DB 테스트) ④ 답할 세션의 SQL 은
  `neos/standing/threads.py` 의 저장소 메서드 `reply_session` 에 두었다(그 테이블의 SQL 이 사는 곳). `reply_session_for` 는 그것을 부른다
  ⑤ 목적지 조회가 실패하면 None(→ `no_reply_channel`)이다. 묻지 못하는 것이 답할 수 없는 곳에 묻는 것보다 낫다
  ⑥ `enqueue_question(notice_store, ask, *, owner_id, now, max_body_chars)` — 목적지를 질문의 `reply_session_id` 에서, 없으면 알림
  대상에서 읽는다. 루프는 이것을 쓰지 않는다(같은 트랜잭션에서 적는다). 다시 적기·운영 도구용이다
- **Q9c 가 설계에서 바꾼 것**(2026-10-05): ① 답 확인은 `_route` 의 `CHAT` 갈래 **첫 줄**의 `_answer_waiting_question` 이다. 바인딩 확인은
  그 함수 안에서 한다(§7.1) — Q15 의 전사 단계와 통합 순서를 맞추기 위해서다 ② 답 확인 중 예외는 경고 한 줄과 None(→ 대화)이다.
  답 확인은 대화를 막지 못한다 ③ `answer_user_question` 은 `channel_type` 을 받아 `question.answered{ask_id, channel_type}` 에
  싣는다(채널 id·세션 키는 싣지 않는다). 결과는 `AskAnswerCommit(ask, events, checkpoint_id)` 이고, 태스크가 이미 `waiting_user` 가
  아니면 트랜잭션을 되돌려 질문은 `waiting` 으로 남는다 ④ 질문을 찾은 **뒤에** 세션을 붙인다 — 대기 질문이 없는 DM 은 이 경로에서
  아무것도 쓰지 않는다(붙이기는 Q8b 의 대화 경로가 한다) ⑤ 스레드의 질문 턴은 알림과 같은 번호(`1. …`)를 단다. 세션은
  `reply_session_id`(없으면 답한 세션), 멱등 키는 `ask:{ask_id}` 다. 답 턴의 멱등 키는 인바운드 `idempotency_key` 다
  ⑥ `standing_ask_total{outcome}` 을 이 단계가 착지시켰다(Q9a·Q9b 자리 포함, §9.1)
- 플래그 **on** 분기의 `main.py` 배선은 Q8c·Q13b 와 같은 이유로 앱 수준 테스트가 없다(앱은 import 때 한 번 조립된다). 대신
  게이트웨이를 직접 만든 테스트로 덮는다

## 11. 결정과 열린 질문

### 11.1 권고 기본값 — 이 문서가 확정한다

| 항목 | 확정 | 권고와 다른 점 |
|---|---|---|
| 답을 알아보는 법 | 에이전트에 대기 질문이 있으면 소유자의 다음 DM(명령 제외)이 답이다. 확인 문구는 "Answer recorded — resuming." + 질문 요약이다 | ① **"붙은 세션"을 "붙는 세션"으로 넓혔다**(§7.1 의 4). 근거: 권고의 둘째 목적지(알림 대상)로 물으면 붙은 세션이 없다. 그 DM 은 Q8b 의 `open_turn` 이 첫 턴에 붙이지만(`channel_threads.py:129-169`), 그것은 `_run_workflow` 안에서 일어난다(`gateway.py:481-485`). 답 확인은 그보다 앞이므로, "이미 붙은"을 요구하면 그 답은 대화로 새고 질문은 만료까지 매달린다. ② 바인딩된 세션은 답이 아니다(Q8 §5 규칙 5) |
| 동시 질문 | 에이전트당 대기 질문 하나다. 둘째는 `ask_pending` 거절이고 그 태스크는 계속 돈다 | 없음. ③ 계약에 `for_call` 을 더했다. 재개한 루프가 자기 질문을 찾는 열쇠다. 승인의 `get_tool_approval(task, run, tool_call)` 과 같은 자리다(`tools.py:263-267`) |
| 어디로 묻나 | 최근 말한 붙은 채널 세션 → 알림 대상 → 없으면 `no_reply_channel` | ④ "최근 말한"을 **에이전트의 모든 스레드의 턴**으로 본다(회전, §6.1). ⑤ principals 가 소유자를 매핑하지 못하는 목적지는 없는 것으로 친다(§6.1) |
| 만료 | `expire_hours`(기본 24) 뒤 **`waiting_user → running` + `ask_expired` 거절로 이어 간다** + 소유자 알림(결정 Q-C, 승인 만료 전례) | ⑥ ~~런을 `failed(ask_expired)` 로 닫는다~~ → 결정 Q-C 로 철회. 런은 닫지 않는다. ⑦ 알림 kind `ask_expired` 를 095 CHECK 에 더했다(결정 Q-D) |
| 보내기 | 워커는 큐에 `question_asked` 로 적고 API 프로세스가 보낸다 | ⑧ **질문 행과 같은 트랜잭션에서** 적는다(§6.2). ⑨ 목적지를 직접 정하는 적기 `enqueue_to` 를 더했다(지금 `enqueue` 는 알림 대상만 안다, `notifications.py:263-292`) |
| 스레드 기록 | 질문은 assistant 턴, 답은 user 턴이다 | ⑩ **두 턴 모두 답이 올 때 API 프로세스가 적는다**(§7.3 의 5). 만료된 질문은 스레드에 남지 않는다 |
| 무인 접기를 바꾸는 자리 | 계획은 "`approvals.py` 또는 설계가 정한 곳"이라 했다 → `tools.py` `_approval_gate_step` 하나로 정했다. `approvals.py` 는 고치지 않는다 | ⑪ ALLOW 도 질문으로 보낸다(§5 의 1) |
| 멈춤 트랜잭션의 모양 | 계획은 "Q10b 와 같은 모양"이라 했다 → 런이 `running` 으로 남는 것은 같고, **체크포인트는 승인 대기처럼 새로 쓴다**(§5) | ⑫ 근거: 묻는 자리가 도구 단계 한가운데다(`model_turn.py:203-205` 의 전제가 서지 않는다) |

### 11.2 체크포인트 ① 결정 (2026-10-05, 닫힘)

위 ①~⑫ 와 필수 셋(§5.1 의 `TaskWaitingUser` 가드 + `CodingTaskOutcome.WAITING_USER` · §8.1 취소가 질문을 닫는다 · 095 가 085 CHECK
를 지우기 전에 테스트 DB 에서 실제 이름을 확인한다)은 받아들여졌다(⑥ 은 Q-C 로 철회).

1. ✅ **Q-A** — `task.waiting_user` kind 를 만들지 않는다. `task.status.changed{status: waiting_user}` 로 간다. fixture 에는
   `question.asked`·`question.answered` 두 kind 만 더한다
2. ✅ **Q-B** — 줄 수가 질문 수와 같으면 줄마다 나누고, 다르면 메시지 전체가 모든 질문의 답이다(§7.2). 질문 알림 본문은 "한 줄에 한
   질문씩 답하라"고 말한다
3. ✅ **Q-C** — **만료는 태스크를 끝내지 않는다.** 승인 만료 전례대로 `waiting_user → running`, 루프가 재개되고 `ask_user.v1` 은
   `ask_expired` 거절을 받는다(§8). `WAITING_USER → EXPIRED` 전이와 런 닫기는 쓰지 않는다
4. ✅ **Q-D** — 알림 kind `ask_expired` 를 095 CHECK 에 더한다
5. ✅ **Q-E** — DM 주소를 v2 세션 키에서 거꾸로 읽는 것을 받아들인다. 질문은 DM 최상위로 간다(Slack 스레드 안으로 보내지 않는다)
6. ✅ **Q-G** — FE 배지는 만들지 않는다
7. ↪ **후속(범위 밖)** — **Q-F** 사람이 연 autonomous 태스크의 무인 DENY 가 `policy_approval_denied` · `denied_by: "user"` 로 적힌다
   (§2.2). **Q-H** 웹 에이전트 대화(`ChatStreamPipeline`)에서 답하기. 둘 다 로드맵 별건 후보로만 남긴다

## 12. 되돌리지 말 것

- `fold_for_unattended` 를 고쳐 질문을 통과시키기 → 접기가 "넓히는" 함수가 되고, 자식(CHILD-GATE)과 Jev 경로가 같은 함수를 쓰므로
  고침이 거기까지 번진다. 질문 갈래는 `_approval_gate_step` 에서 접기를 **부르지 않는** 길이다
- `background` 태스크에 질문을 허락하기 → 결정 Q9-1(dots F8)
- interactive 의 `ask_user` 를 `WAITING_USER` 로 보내기 → 결정 Q9-2
- 답을 스키마 검증 전에 넣기 → 모델이 `answers` 를 지어낼 길이 열린다. `extra="forbid"` 가 지금 그것을 막는다
- 질문 행과 알림 행을 다른 트랜잭션에 쓰기 → 질문이 나가지 않은 채 태스크가 기다린다(§6.2)
- 원장 이벤트를 `neos/coding/` 밖에서 쓰기 → `test_event_kinds.py` 스캐너가 못 보고 조용히 통과한다(§9.2)
- 취소·만료·답 중 하나에서 질문 행을 닫지 않기 → 부분 unique 인덱스가 그 에이전트의 다음 질문을 전부 `ask_pending` 으로 만든다(§8.1)
- 워커에서 게이트웨이로 보내기 → 경고 한 줄로 사라진다(메모리 channel-gateway-lives-in-the-api-process)
- 질문 대기 중의 소유자 DM 을 대화로도 돌리기(답 + 워크플로우) → 같은 말이 두 맥락에 들어간다
- 확인 문구에서 질문 요약을 빼기 → 엉뚱한 말이 답이 된 것을 사용자가 알아차릴 길이 없다(Review Focus 2)
- `CodingEvent` payload 에 채널 id·세션 키를 싣기 → FE 로 간다
- 스키마에 키가 생기기 전에 development.yaml 에 `ask:` 를 넣기 → `extra="forbid"` 로 기동이 멈춘다
