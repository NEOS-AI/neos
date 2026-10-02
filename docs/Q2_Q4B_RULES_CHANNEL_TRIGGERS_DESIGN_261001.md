# Q2 사용자 규칙 · Q4b 채널 트리거 — 설계와 착지

> **작성:** 2026-10-01 · **트랙:** Q2 · Q4b (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2)
> **지위:** 둘 다 **착지했다**(플래그 off). 설계와 코드가 어긋나면 코드가 이긴다.
> **선행:** Q2 USER_ONLY 바닥 ✅ · Q4a webhook 트리거 ✅ · Q10a 봉투 ✅ ([Q4·Q10 설계](Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md))
> **결정자:** 이번 결정 D4~D11 은 사람이 "가장 적절한 것으로 골라라"고 위임해 **Claude 가 골랐다**(2026-10-01).
> 근거를 함께 적는다 — 뒤집을 때 무엇을 다시 봐야 하는지 알 수 있게.

---

## 0. 한 줄

**가드가 능력보다 먼저다.** Q4b 로 바깥 사람이 에이전트를 깨울 길이 하나 더 열리는 날, 소유자가 "이건 막아라 / 이건
물어봐라 / 이건 그냥 해라"를 정할 수단(Q2)이 같이 선다.

## 1. 결정 (2026-10-01, 위임받아 고름)

| # | 결정 | 근거 · 버린 대안 |
|---|---|---|
| **D4** | **Q4b 발신자** = 소유자에게 매핑된 사람(`channels.principals`) **+ 트리거별 `allowed_senders`**. 봇·NEOS 자신은 언제나 아니다. principals 가 없으면 `allowed_senders` 만 | (a) 소유자만은 "고객 문의 채널을 지켜본다" 같은 핵심 용례를 못 한다. (b) 누구나는 낯선 사람이 소유자의 봉투를 쓴다 — Q10a 가 상한이지만 기본값으로 둘 위험은 아니다. (c) 허용 목록을 **소유자 위에 더하는** 꼴로 골랐다: 기본은 가장 좁고, 넓히는 것은 명시적이다 |
| **D5** | **대화 경로와 독립이다.** 어댑터가 대화 게이트 **직전에** 트리거를 부작용으로 부른다. 대화 판정은 그대로(멘션 있으면 응답, 없으면 버림). 트리거 실패는 대화에 닿지 않는다 | 트리거가 메시지를 "먹으면" 기존 대화 동작이 플래그 하나로 바뀐다. 독립이면 켜고 끄는 것이 대화에 아무 차이도 만들지 않는다. 운영자의 `ignored_channels`·`allowed_channels` 는 트리거에도 걸린다(좁히기만) — 멘션·`allowed_users` 는 대화의 규칙이라 보지 않는다 |
| **D6** | **에이전트별 한도는 아직 두지 않는다.** 배포 설정 하나. 둔다면 배포 한도를 **낮추기만** | 사용자당 에이전트가 하나인 동안 에이전트별 한도 = 사용자별 한도다. Q2·USER_ONLY 와 같은 "한 방향" 규칙 |
| **D7** | **봉투 경고는 둔다, 구현은 Q10b 와 함께.** 80% 에서 달마다 한 번, 소유자 채널로 | 알림 경로(`send_to_channel`)·소유자 채널 매핑이 Q10b 의 `PAUSED` 알림과 같은 길이다 — 두 번 배선하지 않는다 |
| **D8** | **Q2 규칙 모양** = 도구 이름 + (execute.v1 이면) argv 접두. 경로 규칙은 나중 | argv 접두 매칭은 USER_ONLY 가 이미 검증한 함수(래퍼 벗기기·플래그 값 두 읽기)를 **그대로** 쓴다. 경로 규칙은 정규화(`..`·대소문자·심볼릭 링크) 함정이 따로 있어 따로 한다 |
| **D9** | **평가 자리:** `USER_ONLY > 기본 DENY > 사용자 block > 보호 파일 REQUIRE > 사용자 require > 운영자 allow·"항상 허용" > 단계 전환 REQUIRE > READ_ONLY ALLOW > 사용자 allow > 기본값` | 분석 §4.2 Q2 의 순서를 코드 자리에 박은 것이다. **사용자 allow 는 위험 등급이 정하는 기본 REQUIRE 만** ALLOW 로 바꾼다 — 보호 파일·단계 전환 승인은 "기본 안전 요건"이라 넓히지 못한다(§4.1 "규칙은 기본 안전 요건을 넓히지 못한다") |
| **D10** | **규칙은 매 단계 새로 읽고 체크포인트에 싣지 않는다** | 실행 중에 더한 block 이 다음 단계부터 걸린다. 저장하면 재개된 태스크가 옛 규칙으로 돈다 |
| **D11** | **규칙을 읽지 못하면 그 단계는 재시도 가능한 실패**(`user_rules_unavailable`) | 규칙 없이 판정하면 block 이 조용히 빠진다(fail-open). 실패가 차라리 낫다 |

## 2. Q2 — 사용자 승인 규칙 ✅ 착지

### 2.1 데이터 — `user_approval_rules` (마이그레이션 075)

`(rule_id 'ur_', user_id → users ON DELETE CASCADE, effect allow|require|block, tool, argv_prefix JSONB 배열)` +
`UNIQUE(user_id, effect, tool, argv_prefix)`. **사용자 키다** — 규칙은 사람의 것이고, 상시 에이전트가 연 태스크도 소유자의
규칙을 쓴다(Q13 §5 "에이전트 권한은 소유자의 부분집합"). 사용자당 상한 `coding_model.approval_user_rules_max`(기본 100) —
Postgres 는 사용자 행을 잠그고 한 문장에서 센다(동시 삽입이 상한을 넘지 않게).

### 2.2 판정 — `neos/coding/domain/approvals.py`

- `UserApprovalRule` · `UserRuleEffect` · `ApprovalGate.user_rules`. 부모 게이트·자식 게이트(CHILD-GATE)·Jev 정적 판정이 전부
  `_approval_gate(state)` 하나에서 게이트를 받으므로 **세 경로에 같은 규칙**이 걸린다
- block 의 사유 코드는 `policy_user_rule_blocked`(모델에게 "재시도하지 말고 다른 길을 고르거나 왜 필요한지 말하라").
  USER_ONLY 와 겹치면 더 엄한 `policy_user_only` 가 이긴다
- **넷째 enum 값이 아니다** — Q2 USER_ONLY 와 같은 이유(`_approval_gate_step` 은 DENY·REQUIRE 가 아닌 결과를 실행한다)
- 사용자 require 는 unattended 런에서 DENY 로 접힌다(D-L1) — autonomous·background 에서 require 는 사실상 block 이다
- 사용자 allow 는 autonomous 런이 묻지 않고 실행하게 한다 — 그것이 allow 의 용도다. background 는 천장(Q1)이 먼저 막는다

### 2.3 루프 — 매 단계 새로 읽는다

`DurableCodingLoop.run()` 이 `_restore` 직후 `_with_user_rules` 로 소유자의 규칙을 `AgentLoopState.user_rules` 에 싣는다.
코덱(`_dump_loop_state`)은 필드를 명시적으로 나열하므로 이 필드는 **저장되지 않는다**(테스트가 체크포인트를 읽어 확인).
원천은 `build_user_rule_source`(`None` 이 off)이고 조립은 `runtime.py` 한 곳이다.

### 2.4 API

```
GET    /api/v1/coding/approval-rules
POST   /api/v1/coding/approval-rules          {effect, tool, argv_prefix?}  → 201 | 409 {code: rule_exists|rule_limit} | 422
DELETE /api/v1/coding/approval-rules/{rule_id}                              → 204 | 404 (남의 것도)
```

플래그 `coding_model.approval_user_rules`(기본 off) — 꺼지면 루프가 규칙을 읽지 않고 라우트가 없다. 플래그·접두 검증:
argv 접두는 execute.v1 에만, 8 토큰까지, **플래그(`-x`)는 접두가 될 수 없다**(매칭이 플래그를 건너뛰므로 영영 맞지 않는 규칙이 된다).

## 3. Q4b — 채널 트리거 ✅ 착지

### 3.1 데이터 — 마이그레이션 076

`standing_agent_triggers` 에 `channel_type`(slack|discord|telegram) · `channel_id` · `allowed_senders` 를 더하고 `source` CHECK 를
`('webhook', 'channel')` 로 넓혔다. 원천별 모양은 CHECK 하나(`standing_agent_triggers_source_shape`)로 묶는다 — webhook 행은 채널
필드가 없고, 채널 행은 둘 다 있다.

📌 **실 DB 가 잡은 함정:** 초안의 CHECK 는 `channel_type IN (...)` 만 적었다. `NULL IN (...)` 은 NULL 이고 **CHECK 는 NULL 을
통과시킨다** — channel_type 이 빈 채널 행이 들어갔다. `channel_type IS NOT NULL` 을 따로 적었다(모양별 8 경우를 실 DB 테스트가
하나씩 넣어 본다).

### 3.2 흐름

```
어댑터 _handle_message (slack · discord · telegram)
  └─ GateContext 를 만든 직후, 대화 게이트 직전:
       observe_channel_message(ctx, message_id, thread_id)   ← 던지지 않는다
         플래그 둘 다 켜짐? · 텍스트·메시지 id 있음? · 봇/자신 아님 · 운영자 채널 정책 통과?
         └─ list_for_channel(type, id) 의 트리거마다
              발신자 = 소유자 매핑 ∪ allowed_senders ?
              └─ fire_trigger(delivery = "{channel_id}:{message_id}", body = 메시지 JSON)   ← Q4a 와 같은 길
  └─ evaluate_channel_gate(...)  ← 대화는 전과 똑같다
```

- 본문은 `{channel_type, channel_id, sender, thread_id, text}` JSON 이고 `fire_trigger` 가 untrusted 로 감싼다. 필터는 이 JSON 경로로
  건다 — 예: `{"path": "thread_id", "equals": null}` 이면 스레드 답글은 발동하지 않는다
- 태스크는 언제나 background, 멈춘 에이전트·봉투(Q10a) 규칙도 그대로 — `fire_trigger` → `open_agent_task` 한 길이다
- 같은 메시지(플랫폼 재전송)는 태스크 하나. 한 채널을 여러 트리거가 보면 **각자** 발동한다(각자의 소유자·봉투로)
- 채널 트리거는 **비밀이 없다**(응답에 `secret`·`delivery_path` 가 null). 인증은 발신자다. trigger_id 로 파생되는 비밀이 있어도
  webhook 배달 경로는 원천이 webhook 이 아니면 **같은 401** 이다
- 플래그: `standing_agents.enabled` + `standing_agents.triggers.enabled` (트리거 기능 하나의 스위치 — 그래서 채널만 쓰는 배포도
  서명 키를 요구받는다. 감수했다: 스위치가 둘이면 webhook 만 켜진 줄 알고 채널이 열린 배포가 생긴다)
- ⚠️ **운영 조건:** Slack 앱이 멘션 없는 채널 메시지를 받으려면 `message.channels`(비공개는 `message.groups`) 이벤트 구독이
  있어야 한다. Discord 는 Message Content intent, Telegram 그룹은 봇 privacy mode off. 없으면 트리거는 멘션된 메시지만 본다
- 텍스트 없는 메시지(첨부만)는 발동하지 않는다

## 4. 테스트와 변이

| 항목 | 확인한 것 |
|---|---|
| Q2 판정 | 층마다 "무엇이 이기는가"를 이름으로: block 이 운영자 allow·기억된 승인·auto·사용자 allow·READ_ONLY 를 이긴다 · require 가 운영자 allow·기억·auto·사용자 allow 를 이긴다 · unattended require = DENY · allow 는 USER_ONLY·천장·비밀 경로·운영자 deny·보호 파일·단계 전환을 못 넘는다 · argv 접두가 래퍼·플래그 값을 USER_ONLY 와 같게 다룬다 · 규칙 없음 = 오늘과 같다 |
| Q2 저장소 | 메모리·Postgres 같은 계약(순서·소유자만 삭제·중복 409·사용자별 상한·사용자 삭제 CASCADE) |
| Q2 루프 | block 사유 코드 · **실행 중 추가한 규칙이 다음 단계부터** · 남의 규칙 무시 · **체크포인트에 없다** · 원천 고장 = 재시도 실패, 모델 호출 0 · allow 로 autonomous 런이 묻지 않고 실행 |
| Q4b | 저장소 계약(채널로만 찾는다 · 지운 트리거/에이전트 제외 · 발신자 교체는 채널만) · CHECK 모양 8 경우(실 DB) · 발신자 규칙(소유자 O, 다른 매핑 X, 낯선 사람 X, 허용 목록 O, principals 없으면 목록만) · 운영자 채널 정책 · background 태스크·untrusted · 같은 메시지 = 태스크 하나 · 트리거마다 각자 · 필터가 메시지 JSON 을 읽는다 · 훅의 플래그 둘·빈 텍스트·봇·**절대 던지지 않음** · 세 어댑터가 멘션 없는 메시지도 훅에 보이고 대화는 그대로 버린다 · API 모양 검증 · 채널 트리거는 webhook 경로로 발동 못 함 |

## 5. 남은 것

- **경로 규칙**(D8) — `write_file.v1` 에 경로 접두. 정규화 함정을 따로 다룬다
- **봉투 경고**(D7) — Q10b 와 함께
- **규칙 UI** — API 만 있다. 웹 설정 화면은 FE 작업이다
- **채널 트리거의 결과 알림** — 지금 태스크 결과는 활동 피드에만 남는다. 채널로 되돌려 보내는 것은 Q9(묻고 기다리기)·Q8(채널 횡단 스레드)의 길이다

## 6. 되돌리지 말 것

- 사용자 allow 를 기본 REQUIRE 보다 앞에 두기 → 보호 파일·단계 전환 승인이 사용자 규칙으로 풀린다
- 규칙을 체크포인트에 저장하기 → 재개된 태스크가 옛 규칙으로 돈다
- 규칙 읽기 실패를 "규칙 없음"으로 처리하기 → block 이 조용히 빠진다
- 트리거가 대화 메시지를 소비하게 하기 → 플래그 하나가 대화 동작을 바꾼다
- 채널 트리거 발신자 기본값을 "누구나"로 → 낯선 사람이 소유자의 봉투를 쓴다
- CHECK 에 `IN (...)` 만 쓰기 → NULL 이 통과한다
