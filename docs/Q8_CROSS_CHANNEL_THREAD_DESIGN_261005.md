# Q8 채널 횡단 스레드 — 설계

> **작성:** 2026-10-05 · **트랙:** Q8 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2) · **dots:** F10 "모든 채널에 걸쳐 맥락을 유지"
> **지위:** 설계다. 열린 질문 여섯 개는 2026-10-05 사람의 결정으로 닫혔다(§11). 코드는 아직 없다. 코드가 착지하면 §9 단계표의
> 행을 "착지(커밋)"로 바꾼다. 설계와 코드가 어긋나면 코드가 이긴다.
> **근거 규칙:** 현재 상태 서술은 전부 2026-10-05 `dev`(`28bb1c86`)에서 코드로 확인했고 경로를 단다. 실호출로 확인하지
> 않은 서술은 **[코드 읽기]** 로 표시한다.

---

## 0. 한 줄

**에이전트마다 활성 스레드 하나**를 두고, 소유자의 DM 채널 세션들과 웹의 에이전트 대화를 그 스레드에 **붙인다**. 붙은
세션의 대화 턴은 스레드에 쌓이고, 다음 턴의 맥락은 채널이 아니라 **스레드**에서 읽는다. 채널 세션 키(`v2:...`)와
체크포인터 thread 는 그대로 둔다. 스레드는 그 위의 **맥락 층**이지 세션을 대체하지 않는다. "새로 시작"은 스레드를
**보관하고 새로 여는 것**이다.

## 1. 이미 내린 결정 (다시 열지 않는다)

| # | 결정 | 출처 |
|---|---|---|
| 6 | 사용자당 에이전트 하나, 늘릴 수 있게. 에이전트에 딸린 것은 전부 `agent_id` 키, 개수 제약은 인덱스 하나에만 | 분석 §6 결정 6 · Q13 §4.3 이 이미 `standing_agent_threads` 를 `agent_id` 키로 예약했다 |
| 3 | `WAITING_USER` 는 Q9 몫이다. Q8 은 상태를 만들지 않는다 | 분석 §6 결정 3 |
| — | 학습은 staged 로만(D19 → D100). 선제 산출물·에이전트 메모는 학습 데이터가 아니다(F18) | 분석 §4.1 · Q13e |
| 13 | 테넌트 경계 = user. 격리 바닥은 user | 분석 §6 결정 13 |
| Q8-1~6 | 이 문서 §11 | 2026-10-05 사람의 결정 |

## 2. 지금 맥락은 어디에 붙어 있나 (2026-10-05 코드 확인)

| 경로 | 맥락의 열쇠 | 이전 턴을 보는가 | 근거 |
|---|---|---|---|
| 웹 채팅(SSE) | `conversation_id` | **본다.** 저장된 메시지 중 최근 `chat.max_history_messages` 개를 `chat_history` 로 넘긴다 | `neos/api/services/chat_stream_pipeline.py` `_run_workflow`(`prior_messages`) |
| 채널 대화(Slack·Discord·Telegram) | `session_id = v2:{channel}:{scope}:{chat}:{thread}` | **보지 않는 것으로 보인다 [코드 읽기].** `enable_history_context=True` 는 켜지만 `chat_history` 를 넘기지 않는다. `_create_initial_state` 도 `chat_history` 를 채우지 않는다. 그래서 `ConversationContextProcessor` 가 `"No chat history available"` 에서 건너뛴다. 단기 메모리(`memory:short:{user}:{session}:*`)는 `store_finding` 을 부르는 곳이 0건이라 비어 있다 | `neos/api/channels/gateway.py` `_run_workflow` · `neos/workflow/graph.py` `_create_initial_state` · `neos/workflow/processors/conversation_context_processor.py` · `neos/memory/manager.py` `store_finding` |
| 채널 ↔ 코딩 태스크 바인딩 | `channel_coding_bindings.session_id` | 코딩 태스크의 전사가 맥락이다(조향 `steer`) | `neos/api/channels/session_bind.py` · `gateway.py` `_steer_bound_chat` |
| 체크포인터 | LangGraph `thread_id = session_id`(웹은 `conversation_id`) | 승인 대기·재개용 상태다. 대화 이력을 담지 않는다 | `graph.py` `configurable.thread_id` |
| 에피소드·장기 메모리 | `user_id` | 사용자 단위라 이미 채널을 가로지른다. 다만 **턴 전사가 아니다** | `memory_manager.build_context` |

📌 **Q8 의 출발점은 "채널마다 맥락이 따로다"가 아니라 "채널 안에서도 이전 턴이 없다"이다.** 상시 에이전트가 없는
사용자의 채널 대화도 같은 결함을 갖는다. 이것은 Q8 이 아니라 **로드맵 별건 CH-HIST** 가 고친다(결정 Q8-5).

📌 **DM 인지 아닌지는 세션 키로 알 수 없다.** Slack 은 scope 자리에 팀 id 를 넣고, DM 여부를 채널 id 접두(`D`)로만
가린다. 그래서 판정은 어댑터마다 다르고, 결과는 `GateContext.is_dm` 에만 담긴다(`neos/api/channels/authz.py`).
`ChannelMessage` 에는 이 값이 없다. Q8 은 어댑터가 판정한 값을 `ChannelMessage` 까지 실어야 한다(§7).
세션 키를 파싱해서 DM 을 추측하지 않는다.

📌 **설정은 모르는 키를 거절한다**(`StrictConfigModel` = `extra="forbid"`). 그래서 development 프로파일에서 켜는 일
(결정 Q8-6)은 스키마 키를 만드는 **같은 커밋**(Q8a)에서만 할 수 있다. 먼저 yaml 에 넣으면 기동이 멈춘다.

## 3. 이름

- 테이블 `standing_agent_threads` · `standing_agent_thread_sessions` · `standing_agent_thread_turns`
- 모듈 `neos/standing/threads.py` · 도메인 타입 `AgentThread` · `ThreadTurn` · id 접두 `sat_`
- 코드에서 "thread"는 이미 세 가지를 뜻한다: LangGraph `thread_id`, 채널의 스레드 답글(`session_key` 의 다섯째 칸),
  Slack `thread_ts`. 그래서 넷째 뜻은 **항상 `agent_thread` 로 한정해 부른다.** 변수 이름에 `thread_id` 를 단독으로
  쓰지 않는다. grep 이 거짓말을 하지 않게 하려는 것으로, Q13 §3 과 같은 규칙이다
- 웹 세션의 세션 id 는 `web:{conversation_id}` 다. 채널 키(`v2:` 접두)와 이름 공간이 겹치지 않는다

## 4. 데이터 모델 (마이그레이션 092, 안)

```sql
-- 에이전트의 맥락 단위. "활성 스레드는 에이전트당 하나"는 아래 부분 unique 인덱스 하나에만 산다
-- (결정 6 과 같은 모양). F5(여러 프로젝트)로 늘릴 때 지우는 것이 이것 하나다.
-- 보관된 스레드는 몇 개든 남는다(결정 Q8-2).
CREATE TABLE IF NOT EXISTS standing_agent_threads (
    agent_thread_id VARCHAR(64) PRIMARY KEY,                      -- 'sat_' + hex
    agent_id        VARCHAR(64) NOT NULL
                    REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agent_threads_one_active_per_agent
    ON standing_agent_threads(agent_id) WHERE archived_at IS NULL;

-- 세션 -> 스레드. 세션 하나는 스레드 하나에만 붙는다. 붙는 곳은 늘 활성 스레드다(§5 · 회전은 행을 옮긴다).
CREATE TABLE IF NOT EXISTS standing_agent_thread_sessions (
    session_id      TEXT        PRIMARY KEY,                      -- v2 채널 세션 키 또는 'web:{conversation_id}'
    agent_thread_id VARCHAR(64) NOT NULL
                    REFERENCES standing_agent_threads(agent_thread_id) ON DELETE CASCADE,
    channel_type    VARCHAR(16) NOT NULL
                    CHECK (channel_type IN ('slack', 'discord', 'telegram', 'web')),
    attached_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 턴 전사. append-only 다. 보관된 스레드의 턴도 남는다(에이전트 삭제 때 함께 지운다, 결정 Q8-4).
CREATE TABLE IF NOT EXISTS standing_agent_thread_turns (
    turn_id         BIGSERIAL   PRIMARY KEY,
    agent_thread_id VARCHAR(64) NOT NULL
                    REFERENCES standing_agent_threads(agent_thread_id) ON DELETE CASCADE,
    session_id      TEXT        NOT NULL,                         -- 어느 세션에서 왔나
    channel_type    VARCHAR(16) NOT NULL,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL,
    idem_key        TEXT        NULL,                             -- 인바운드 멱등 키(재시도 중복 방지)
    xact_id         xid8        NOT NULL DEFAULT pg_current_xact_id(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agent_thread_turns_idem
    ON standing_agent_thread_turns(agent_thread_id, session_id, role, idem_key)
    WHERE idem_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_standing_agent_thread_turns_window
    ON standing_agent_thread_turns(agent_thread_id, turn_id DESC);
CREATE INDEX IF NOT EXISTS ix_standing_agent_thread_turns_feed
    ON standing_agent_thread_turns(agent_thread_id, xact_id, turn_id);
```

- **`ON DELETE CASCADE` 를 건다. Q13 §4.2 와 다르다.** Q13 의 `coding_tasks.agent_id` 는 `owner_id` 를 따로 갖고 있어서
  사용자가 삭제될 때 태스크도 같은 문장에서 함께 지워진다. 스레드 행에는 `owner_id` 가 없다(키는 `agent_id` 뿐, Q13 §9).
  그래서 cascade 가 없으면 NO ACTION 이 사용자 삭제를 막는다
- **에이전트 `DELETE` 는 soft(`deleted_at`)지만 스레드는 hard 로 지운다**(결정 Q8-4). cascade 는 에이전트 행이 실제로 지워질
  때만 돈다. 그래서 `StandingAgentStore.delete` 가 `deleted_at` 을 적는 **같은 트랜잭션**에서
  `DELETE FROM standing_agent_threads WHERE agent_id = :agent_id` 를 함께 실행한다. 세션과 턴은 cascade 로 따라간다.
  보관된 스레드도 함께 지운다. Q13a 의 저장소 계약 테스트에 "삭제 뒤 턴 0행"이 더해진다
- **`xact_id`.** 창을 조립할 때는 `turn_id` 순서로 충분하다. 턴 하나가 조금 늦게 커밋돼도 다음 턴에서 보이기 때문이다.
  그러나 API 피드(Q8c)의 커서는 Q13d 와 같은 이유로 `turn_id` 를 쓸 수 없다. 늦게 커밋된 턴이 이미 지나간 커서 뒤로
  떨어져 영영 건너뛰어지기 때문이다. 그래서 피드 커서는 `(xact_id, turn_id)` + `pg_snapshot_xmin` 미만 규칙을 따른다
  (마이그레이션 072 와 같다)
- **`owner_id` 열을 두지 않는다.** 소유 검사는 `standing_agents` 를 거쳐 조인한다(Q13 §4.3 📌)

## 5. 붙이는 규칙 — 어느 세션이 스레드에 닿는가

**채널 세션**은 다음을 **전부** 만족할 때만 붙는다. 하나라도 어긋나면 지금과 똑같이 동작한다(스레드 없음).

1. 플래그 `standing_agents.enabled` 와 `standing_agents.threads.enabled` 가 둘 다 켜져 있다
2. **DM 이다**(결정 Q8-1): 어댑터가 판정한 `is_dm` 값이 참이다(§2 📌). 그룹 채널은 어떤 명령으로도 붙지 않는다
3. **발신자가 소유자로 매핑된다**: `resolve_channel_principal` 이 NEOS `user_id` 를 돌려준다. `channels.principals` 가
   비어 있으면 아무 세션도 붙지 않는다. Q4b 의 발신자 규칙(`sender_admitted`)과 같은 함수를 쓴다
4. 그 사용자에게 `resolve_agent` 가 에이전트를 돌려주고, 에이전트가 `active` 다. `paused`·`retired` 에이전트는 이미 붙은
   세션의 턴도 **쓰지 않는다**. 대화 자체는 막지 않는다. 에이전트 상태는 "새 일을 만들지 않는다"는 뜻이고(Q13 §4.1),
   대화를 끊는 데까지 넓히지 않는다
5. 세션이 코딩 태스크에 바인딩돼 있지 않다. 바인딩된 세션은 태스크 조향이 맥락이다(`_steer_bound_chat`). 같은 메시지가
   두 맥락에 들어가지 않게 한다

**웹 세션**(결정 Q8-3)은 인증된 소유자 자신이므로 2·3 대신 **대화 소유 검사**(파이프라인의 `authorized_conversation`)를
쓴다. 웹 대화는 자동으로 붙지 않는다. 소유자가 "에이전트 대화"로 연 대화(§8 `POST .../thread/web-conversation`)만
붙는다. 웹의 다른 대화는 지금처럼 자기 이력만 본다. 웹 대화 목록 전부가 에이전트 맥락에 섞이지 않게 하려는 것이다.

- **채널 DM 은 첫 턴에서 자동으로 붙는다.** 사용자가 따로 명령하지 않아도 된다(dots: "대화를 나눠 관리할 필요가 없다").
  붙은 사실은 활동 피드에 남긴다
- **에이전트를 찾는 SQL 은 `resolve_agent` 하나뿐이다**(Q13 §6). 스레드를 찾는 SQL 도 `resolve_agent_thread(agent)` 하나로
  모은다. get-or-create 이고, 활성 하나 인덱스와 경합하면 다시 읽는다

## 6. 맥락 조립 — 다음 턴은 무엇을 보는가

```python
# neos/standing/threads.py (안)
async def thread_window(store, agent_thread_id: str, *, limit: int) -> list[ThreadTurn]:
    """활성 스레드의 user/assistant 턴 중 최근 `limit` 개, 오래된 것부터."""
```

- `limit` 은 **기존 설정 `chat.max_history_messages` 를 그대로 쓴다.** 웹 채팅과 같은 값이다. 새 매직넘버를 만들지 않는다
- 조립한 창은 웹 채팅과 **같은 모양의 `chat_history`** 로 워크플로우에 넘긴다(`{"role", "content", "timestamp"}`).
  워크플로우·`ConversationContextProcessor` 는 고치지 않는다
- **다른 세션에서 온 턴은 출처를 붙인다.** 턴의 `channel_type` 이 지금 세션과 다르면 내용 앞에 `[slack]`·`[web]` 같은
  표지를 붙인다. 모델이 "아까 Slack 에서 말한 것"을 구별할 수 있어야 맥락이 유지된다는 F10 의 뜻이 산다
- 체크포인터의 `thread_id` 는 **세션 id 그대로다**(채널은 `session_id`, 웹은 `conversation_id`). 승인 대기와 재개는
  세션 단위로 남는다. 스레드는 대화 이력만 공급한다

## 7. 회전 — "새로 시작"은 보관하고 새로 연다 (결정 Q8-2)

```python
async def rotate_agent_thread(store, agent: StandingAgent) -> AgentThread:
    """한 트랜잭션: 활성 스레드에 archived_at → 새 스레드 INSERT → 붙은 세션 행을 새 스레드로 UPDATE."""
```

- **에이전트 단위다.** 스레드가 에이전트당 하나이므로, 어느 채널에서 `/new` 를 쳐도 **모든 붙은 세션**의 맥락이 새로
  시작한다. `/new` 응답에 이 사실을 한 줄로 알린다("이 에이전트의 대화를 새로 시작했습니다 — Slack·Telegram·웹 모두")
- **세션은 떼지 않고 옮긴다.** 붙은 세션은 회전 뒤에도 붙어 있다. 그래서 다음 턴이 붙기 규칙(§5)을 다시 거치지 않는다
- 보관된 스레드는 읽기 전용이다. 피드 API 로 볼 수 있고, 창 조립에는 쓰이지 않는다
- 경합: 두 `/new` 가 동시에 오면 활성 하나 인덱스가 하나를 실패시킨다. 실패한 쪽은 다시 읽은 활성 스레드를 돌려준다.
  회전이 두 번 일어나지 않는다
- 웹에는 `/new` 가 없다. 같은 동작을 `POST .../thread/rotate` 가 한다(§8)

## 8. 배선

| 자리 | 바꾸는 것 | 단계 |
|---|---|---|
| 어댑터 3종 | 이미 계산한 `is_dm` 을 `ChannelMessage.metadata["is_dm"]` 에 싣는다. 값이 없으면 DM 이 아니다(fail-closed) | Q8b |
| `gateway._run_workflow` | §5 판정 → 붙으면 (a) user 턴 기록 (b) 창으로 `chat_history` 를 채움 (c) 실행 (d) `final_response` 가 나오면 assistant 턴 기록 | Q8b |
| ~~`gateway._resume_workflow_approval`~~ | ~~재개해서 `final_response` 가 나오면 assistant 턴을 기록한다~~ → **하지 않는다**(Q8b, 2026-10-05). 재개는 `RuntimeWorkflowApprovals.decide` 가 백그라운드에서 `astream` 을 돌리며 **청크를 버리고**, 게이트웨이에는 `"{request_id} approved"` 만 돌아온다. 소유자도 재개 결과를 받지 못한다. 스레드는 소유자가 본 것을 적으므로 승인으로 끊긴 턴은 사용자 턴만 남는다. 재개 결과가 채널로 가지 않는 결함은 로드맵 별건 **CH-RESUME** | — |
| `gateway._run_new` | 붙은 세션이면 `rotate_agent_thread`. 지금 하는 세션 정리는 그대로 한다 | Q8b |
| `ChatStreamPipeline._run_workflow` | 대화가 붙은 웹 세션이면 `prior_messages` 대신 `thread_window` 로 `chat_history` 를 채우고, 사용자·assistant 턴을 스레드에 기록한다. **SSE 이벤트는 바뀌지 않는다** — `chat_stream_event_types.json` fixture 에 새 kind 가 없다 | Q8d |

- **스레드는 대화를 막지 못한다.** 스레드 읽기·쓰기가 실패하면 경고 한 줄을 남기고 스레드 없이 대화한다. 스레드는 맥락이지
  가드가 아니다. Q4b 의 "트리거는 대화를 막지 못한다"와 같은 규칙이다. 다만 실패 수는 계측한다(Prometheus 카운터
  `standing_thread_failures_total{op}` — op 는 `open`·`close`·`rotate`. 저장소의 다른 카운터처럼 `neos_` 접두가 없다). 조용히 사라지는 실패는 이 저장소에서 반복됐다
- **멱등.** 채널 인바운드는 이미 `(session_id, idem)` 으로 한 번만 처리된다. 턴 쓰기도 같은 `idem` 을 `idem_key` 에 싣는다.
  웹은 저장된 사용자 메시지 id 를 쓴다
- **동시성.** 세션 잠금(`_inflight`)은 세션 단위이고, 두 세션이 동시에 같은 스레드에 말할 수 있다. 각 턴은 시작할 때의 창을
  읽는다. 동시에 들어온 두 턴은 서로를 보지 못한다. 잠금을 스레드 단위로 넓히지 않는다. 넓히면 한 채널의 느린 워크플로우가
  다른 채널을 막는다. 이것은 받아들이는 비용이다
- **웹 턴은 두 곳에 산다.** `chat_messages`(웹 화면이 그리는 정본)와 스레드 턴(맥락의 정본)이다. 중복이지만 각자의 독자가
  다르다. 웹 화면이 스레드 턴을 읽게 바꾸면 FE 대화 모델 전체가 바뀌므로 하지 않는다. 웹 대화에서 메시지를 지우거나
  고쳐도 스레드 턴은 바뀌지 않는다. 이것은 받아들이는 비용으로 기록한다
- **워커에서 돌지 않는다.** 게이트웨이와 SSE 파이프라인은 API 프로세스에 있다. 그래서 스레드 쓰기도 API 프로세스에서만
  일어난다. 워커가 스레드에 쓸 필요는 Q9(질문 발신)에서 생기는데, 그때는 Q10b 처럼 큐로 넘긴다

## 9. API

```
GET    /api/v1/standing-agents/{agent_id}/thread                           # 활성 스레드 + 붙은 세션 목록     (Q8c)
GET    /api/v1/standing-agents/{agent_id}/threads                          # 보관 포함 목록, 배열             (Q8c)
GET    /api/v1/standing-agents/{agent_id}/threads/{agent_thread_id}/turns?after=&limit=   # 피드, 커서 (xact_id, turn_id) (Q8c)
POST   /api/v1/standing-agents/{agent_id}/thread/rotate                    # §7                              (Q8c)
DELETE /api/v1/standing-agents/{agent_id}/thread/sessions/{session_id}     # 세션 떼기                        (Q8c)
POST   /api/v1/standing-agents/{agent_id}/thread/web-conversation          # 웹 "에이전트 대화"를 만들거나 기존 것을 돌려준다 (Q8d)
```

- 전부 `resolve_agent` 를 거친다. 남의 에이전트는 404 다(Q13 §6). 남의 스레드 id 도, 남의 세션 떼기도 404 다
- **읽기는 부작용이 없다**(Q8c): `GET .../thread` 는 활성 스레드가 없으면 열지 않고 `{"thread": null, "sessions": []}` 다
- **회전은 에이전트 상태를 보지 않는다**: 새로 시작은 일을 만들지 않는다. 채널의 `/new` 와 같다
- **떼기는 스위치가 아니다**: 뗀 세션의 다음 DM 은 붙이기 규칙(§5)을 다시 거쳐 다시 붙는다. 잘못 붙은 세션이나 안 쓰는
  세션을 목록에서 정리하는 것이다. 채널을 계속 빼 두려면 차단 목록이 필요하다 — 아직 정하지 않았다
- 피드 커서는 `(xact_id, turn_id)` 를 감싼 불투명 문자열이다(`TurnCursor`). 읽을 수 없으면 422. 한 쪽 상한은 500(활동 피드와 같다)
- 웹 에이전트 대화는 **에이전트당 하나**다. 그 대화의 메시지 전송은 기존 `/chat/conversations/{id}/messages/stream` 을
  그대로 쓴다. 새 스트림 엔드포인트를 만들지 않는다. FE 는 그 대화를 사이드바에서 구별해 보여 주기만 하면 된다
  (BFF·`use-chat-stream.ts` 는 그대로다)

## 10. 단계 — 전부 플래그 off 로 착지한다(development 에서는 켠다)

| 단계 | 무엇 | 테스트가 확인할 것 | 선행 |
|---|---|---|---|
| **Q8a** ✅ **착지(2026-10-05)** | 마이그레이션 092 · `neos/standing/threads.py`(메모리·Postgres 저장소, `resolve_agent_thread`, `thread_window`, `rotate_agent_thread`) · 에이전트 삭제가 스레드를 함께 지운다 · 설정 `standing_agents.threads.enabled`(스키마 기본 off) **+ `config/neos.development.yaml` 에서 on**(결정 Q8-6, 같은 커밋) | 테스트 47(계약 43 · 설정 4) · 변이 12/12. 메모리·Postgres **같은 계약** · 활성 하나(경합 시 둘째가 첫째를 다시 읽는다) · 회전이 한 트랜잭션: 보관 + 새 스레드 + 세션 이동, 동시 회전 둘 = 회전 하나 · 창은 활성 스레드만, `limit` 경계 · 같은 `idem_key` 두 번 쓰기 = 한 행 · **에이전트 DELETE 뒤 스레드·세션·턴 0행**(보관된 것 포함) · **사용자 삭제가 한 문장으로 지운다**(실 DB) · 남의 에이전트 스레드는 None · 신선한 DB 2회 적용 · development 프로파일로 설정이 로드된다 | Q13 ✅ |
| **Q8b** ✅ **착지(2026-10-05)** | 어댑터 `is_dm`(어댑터마다 판정 함수 하나를 게이트와 `metadata` 가 함께 쓴다) · `neos/standing/channel_threads.py`(붙이기 규칙·창·기록·회전) · 게이트웨이 배선(§8) · `main.py` 는 늘 배선하고 플래그는 호출 때마다 읽는다 | 테스트 26(게이트웨이 17 · 어댑터 9) · 변이 15/15. **실제 게이트웨이로**: Slack DM 턴 → Telegram DM 다음 턴의 `chat_history` 에 `[slack]` 표지와 함께 있다 · 그룹 채널·principals 미매핑·바인딩 세션·`paused` 에이전트는 붙지 않고 동작이 지금과 바이트 동일 · 스레드 저장소가 던져도 응답이 나오고 카운터가 오른다 · ~~승인 재개가 assistant 턴을 닫는다~~ 승인으로 끊긴 턴은 사용자 턴만 남는다(§8) · Slack 의 `/new` 뒤 Telegram 의 다음 턴이 빈 창을 본다 · 플래그 off 면 저장소를 부르지 않는다 | Q8a |
| **Q8c** ✅ **착지(2026-10-05)** | API 읽기·회전·떼기(§9) · 마이그레이션 093(피드 커서 인덱스) · `neos/api/handlers/standing_thread_handlers.py` · ~~활동 피드에 "세션 붙음"·"회전" 항목~~ → **넣지 않았다**(아래) | 테스트 32(계약 19 · API 13) · 변이 11/11. 플래그 off 면 라우트가 없다(`test_retired_routes._routes()` 로 읽는다 — `app.routes` 는 포함 라우터를 감춘다) · 커서가 늦은 커밋을 건너뛰지 않는다(실 DB) · 남의 에이전트·남의 스레드 id 는 모든 동사에서 404 · 목록이 배열 | Q8b |
| **Q8d** ✅ **착지(2026-10-05)** | 웹 에이전트 대화: 엔드포인트(§9) · `ChatStreamPipeline` 배선(§8) · 마이그레이션 094(스레드당 웹 세션 하나) · FE 사이드바 **"Agent" 진입점** + BFF `POST /api/standing-agent/conversation` | 테스트 BE 23(파이프라인 끝까지 5 · API 4 · 계약 4 · 기존 갱신) + FE 4 · 변이 10/10. 실제 `ChatStreamPipeline.run` 으로: Slack 턴이 웹 대화의 LLM `conversation_messages` 에 `[slack]` 으로 들어간다 · 웹 턴이 다음 Slack DM 의 창에 `[web]` 으로 보인다 · 붙지 않은 웹 대화는 동작이 지금과 같다 · 남의 대화를 에이전트 대화로 지정할 수 없다 · SSE 이벤트 fixture 가 바뀌지 않는다(양방향 테스트 통과) · 에이전트당 하나 | Q8c |

- **Q8a 가 설계에서 바꾼 것**(2026-10-05): ① 피드 커서 인덱스 `(agent_thread_id, xact_id, turn_id)` 는 092 에 넣지 않았다 —
  읽는 Q8c 가 더한다. `xact_id` 열은 첫 쓰기부터 있어야 하므로 092 에 있다 ② **회전과 붙이기의 경합**: 회전이 커밋되기 직전에
  옛 활성 스레드를 읽은 `attach_session` 은 세션 행을 보관된 스레드에 남길 수 있다. 그래서 `attach_session` 은 같은 에이전트의
  보관 스레드에 붙은 세션을 활성 스레드로 옮긴다(다른 에이전트의 행은 건드리지 않고 None) ③ 메모리 에이전트 저장소에
  `add_delete_listener` · `is_live` 를 더했다 — Postgres 가 같은 트랜잭션에서 하는 스레드 삭제를 메모리 구현이 흉내 내는 자리다
  ④ 저장소 메서드는 `agent_id` 를 받고, 소유 검사는 호출자의 `resolve_agent` 몫이다. 모듈 함수 `resolve_agent_thread` ·
  `rotate_agent_thread` 는 `StandingAgent` 를 받는다
- ~~⚠️ **Q8a 만으로는 아무것도 스레드를 읽거나 쓰지 않는다.**~~ → Q8b(2026-10-05)가 첫 독자다. development 에서는 소유자의 DM 이
  이제 스레드에 붙는다 — `channels.principals` 에 소유자 매핑이 있어야 한다
- **Q8b 가 설계에서 바꾼 것**(2026-10-05): ① 승인 재개 행을 지웠다(§8 — 재개 결과는 버려진다, CH-RESUME) ② 소유자 매핑은
  게이트웨이의 `user_id` 가 아니라 `channel_threads.mapped_owner` 가 직접 한다 — principals 가 비면 게이트웨이의 `user_id` 는
  매핑되지 않은 값(봇 사용자 id)이다 ③ 창은 이번 턴을 쓰기 **전에** 읽는다 — 이번 턴은 `query` 가 나른다(웹 파이프라인의
  `history_messages[:-1]` 과 같은 이유) ④ 스레드에 적는 사용자 턴은 발신자 표지(`[U_alice]`) 없는 본문이다 — DM 의 발신자는
  소유자 하나다 ⑤ 미매핑 발신자는 principals 가 있으면 게이트웨이가 워크플로우 전에 이미 거절한다(`_NO_OWNER`) — 스레드는 그
  전에 판정하지만 결과는 같다(붙지 않는다)
- ⚠️ 배포·개발 DB 에 092 를 적용해야 한다(`scripts/apply_schema.py`). 적용 전에는 에이전트 `DELETE` 가 없는 테이블을 지우려다
  실패한다 — dev DB 는 마이그레이션을 조용히 놓친 이력이 있다(066~090, 2026-10-03)
- **Q8c 가 설계에서 바꾼 것**(2026-10-05): ① 활동 피드(F17, Q13d)에 "세션 붙음"·"회전"을 넣지 않았다. 활동 피드는 코딩 원장의
  `CodingEvent` 를 합친 것이고, 그 이벤트 종류는 FE↔BE fixture(`coding_event_kinds.json`)가 양방향으로 고정한다. 스레드 사건을
  섞으려면 코딩 이벤트 계약을 깨야 한다. 같은 정보는 스레드 API 가 준다(세션의 `attached_at`, 스레드의 `created_at`·`archived_at`)
  ② 저장소에 부작용 없는 읽기 넷을 더했다: `active` · `get_thread`(에이전트 범위) · `detach_session`(에이전트 범위) · `turns_after`
  ③ ⚠️ 플래그 **on** 분기(`main.py` 마운트)는 테스트가 없다 — Q13b 와 같은 이유(앱은 import 때 한 번 조립된다)
- **Q8d 가 설계에서 바꾼 것**(2026-10-05): ① **FE 에는 DB 작업이 없다** — FE 는 더 이상 자체 DB 를 쓰지 않고 FE 채팅 id 가 곧 BE
  `conversation_id` 다(`web/lib/adapters/chat-adapters.ts`). 그래서 BE 가 만든 대화를 FE 는 `/chat/{id}` 로 그대로 연다
  ② "사이드바에서 구별해 보여 주기" 대신 **사이드바 "Agent" 진입점** 하나를 두었다. 그 대화는 채팅 기록에 에이전트 이름을 제목으로
  한 보통 대화로도 보인다 ③ 파이프라인은 이력을 **두 곳 모두** 스레드 창으로 바꾼다 — 워크플로우의 `chat_history`(Step 4)와 최종 LLM 의
  `conversation_messages`(Step 6). 이번 턴은 방금 저장한 사용자 메시지 레코드(첨부 포함)로 끝에 둔다 ④ "에이전트당 하나"는 094 의
  부분 unique 인덱스(스레드당 웹 세션 하나)가 지킨다 — 회전은 세션 행을 옮기므로 같은 뜻이다. 동시에 두 번 만들면 진 쪽이 자기 대화를
  지우고 이긴 쪽을 돌려준다 ⑤ 소유자가 웹에서 그 대화를 지웠으면(`status='deleted'`) 엔드포인트가 세션을 떼고 새로 만든다
  ⑥ 웹 턴의 멱등 키는 저장된 사용자 메시지 id 다 ⑦ ⚠️ 웹 대화의 `chat_messages` 와 스레드 턴은 따로 산다(§8 받아들인 비용) — 웹에서
  메시지를 고치거나 지워도 스레드 턴은 그대로다
- **Q9 가 Q8 위에 더할 것**(지금 만들지 않는다): "답할 세션" = 소유자가 가장 최근에 말한 붙은 세션. 턴 테이블을 조회해
  얻으므로 새 열이 필요 없다. 이 조회 함수는 그것을 처음 읽는 Q9 가 만든다
- **Q15(음성)** 는 음성 → 텍스트를 user 턴으로 기록한다. 턴 `role` 은 늘리지 않는다

## 11. 결정 (2026-10-05, 사람의 결정)

1. ✅ **그룹 채널** — **DM 만** 붙인다. 그룹 세션을 붙이는 명령(`/attach`)을 만들지 않는다
2. ✅ **`/new`** — **스레드를 보관하고 새로 연다.** `reset` 표식 턴은 쓰지 않는다. 회전은 에이전트 단위다(§7)
3. ✅ **웹 채팅** — **웹에서도 스레드에 말한다.** 웹 대화 하나를 에이전트 대화로 지정해 스레드에 붙인다. 기존 스트림
   엔드포인트를 재사용한다(Q8d)
4. ✅ **보존** — **에이전트를 지울 때 턴도 지운다.** 보관된 스레드까지 같은 트랜잭션에서 지운다(§4)
5. ✅ **채널 이력 결함** — **로드맵 별건(CH-HIST)** 으로 올린다. Q8 은 에이전트 소유자의 DM 만 고친다
6. ✅ **development 프로파일** — **켠다.** 스키마 키가 생기는 Q8a 커밋에서 함께 켠다(§2 📌)

## 12. 되돌리지 말 것

- 스레드 행을 `user_id`/`owner_id` 키로 만들기 → 에이전트가 여럿이 되는 순간 데이터 이전이 된다
- 그룹 채널 세션을 붙이기 → 남의 말이 소유자 맥락에 들어가고, DM 의 내용이 그룹에 새어 나간다(결정 Q8-1)
- 세션 키를 파싱해서 DM 을 추측하기 → Slack 에서 틀린다
- 웹 대화를 지정 없이 자동으로 붙이기 → 웹 대화 목록 전부가 에이전트 맥락에 섞인다
- 에이전트 soft delete 뒤 턴을 남기기 → 결정 Q8-4
- 스레드 실패가 대화를 막기 · 스레드 실패를 계측 없이 삼키기
- 스레드 턴을 학습 데이터(GEPA 평가 세트·교훈 후보)로 쓰기 → F18. Q7 은 메시지 **피드백**을 읽지 턴 전사를 읽지 않는다
- 체크포인터 `thread_id` 를 에이전트 스레드로 바꾸기 → 승인 대기가 세션 사이에서 섞인다
- 스키마에 키가 생기기 전에 development.yaml 에 `threads:` 를 넣기 → `extra="forbid"` 로 기동이 멈춘다
