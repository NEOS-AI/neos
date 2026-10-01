# Q4 이벤트 트리거 · Q10 에이전트 예산 봉투 — 설계와 첫 착지

> **작성:** 2026-10-01 · **트랙:** Q4 · Q10 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2)
> **지위:** Q4a · Q10a 는 **착지했다**(플래그 off). Q4b · Q10b 는 설계만 있다. 설계와 코드가 어긋나면 코드가 이긴다.
> **근거 규칙:** 현재 상태 서술은 전부 2026-10-01 `dev`(`0094c9b6`)에서 확인했고 경로를 단다.
> **선행:** [Q13 설계](Q13_STANDING_AGENT_DESIGN_260930.md) a~f 전부 착지 · Q1 background ✅ · Q5 감시자 섀도 🟢

---

## 0. 한 줄

**바깥 세계가 에이전트를 깨우는 길(Q4)과, 깨어난 에이전트가 쓸 수 있는 돈의 상한(Q10)을 같이 세운다.**
Q4 가 먼저 열리면 낯선 발신자가 소유자의 돈을 쓰는 길이 생긴다. 그래서 둘은 한 문서에 있다.

## 1. 이번에 내린 결정 (2026-10-01, 사람의 결정)

| # | 결정 | 왜 |
|---|---|---|
| D1 | **Q10 의 출구는 둘로 나눈다.** 봉투가 바닥나면 **새 태스크를 거절**한다(막는다). 진행 중 태스크는 safe point 에서 **섀도로만** 기록한다(`budget.judged`). `PAUSED` 로 보내는 길은 Q5 와 함께 쓰는 별도 단계(Q10b)다 | `PAUSED` 로 보내는 코드가 0건이다 — 전이·리스 해제·재개 API·FE 이벤트가 전부 없다. 로드맵도 "`PAUSED` 작성"을 Q5 경계 실측 뒤의 단계로 적었다. 새 태스크 거절은 `PAUSED` 없이 된다 |
| D2 | **Q4 는 webhook 원천만 먼저.** 채널 원천(지정 Slack 채널)은 Q4b | 채널 원천은 "누가 쓴 메시지가 발동시키나"(아래 §5 열린 질문 1)와 `require_mention`·`allowed_channels` 가 얽혀 있다 |
| D3 | **서명 비밀은 마스터 키에서 파생한다.** `secret = HMAC(NEOS_TRIGGER_SIGNING_KEY, trigger_id)` — DB 에 비밀이 없다 | HMAC 검증에는 비밀 원문이 필요해 해시로 저장할 수 없다. 앱 레벨 암호화 유틸이 없다. 교체는 트리거를 다시 만들거나 마스터 키를 바꾸는 것이다 |

## 2. Q4a — 서명된 webhook 이 background 태스크가 된다 ✅ 착지

### 2.1 데이터 — `standing_agent_triggers` (마이그레이션 074)

| 열 | 뜻 |
|---|---|
| `trigger_id` | `st_` + hex |
| `agent_id` | **키다**(Q13 결정 6). `ON DELETE CASCADE` — 아래 📌 |
| `source` | `CHECK (source IN ('webhook'))` — 채널 원천은 그것을 읽는 코드(Q4b)와 함께 넓힌다 |
| `prompt_template` | 소유자가 쓴 지시. 빈 값 거절 |
| `filters` | `[{"path": "a.b", "equals": <JSON 값>}]` — 전부 맞아야 발동. 빈 배열은 언제나 |
| `enabled` · `deleted_at` | 끄기 · 지우기(소프트) |

- **`owner_id` 열이 없다.** 소유 검사는 `standing_agents` 를 거쳐 조인한다(Q13 설계 §4.3 "되돌리지 말 것")
- 📌 **`ON DELETE CASCADE` 인 이유:** 사용자 삭제는 `users → standing_agents` 로 CASCADE 된다. `coding_tasks` 는 `owner_id` 로도
  함께 지워져 `NO ACTION` 이 막지 않지만, 이 테이블에는 `owner_id` 가 없어 `NO ACTION` 이면 **사용자 삭제가 실패한다.**
  테스트가 실 DB 에서 확인한다(`test_deleting_the_owner_is_not_blocked_by_triggers`)
- **배달 멱등성은 새 테이블이 아니다.** `channel_inbound_idempotency`(053)를 `session_id = trigger:{trigger_id}` 로 쓴다.
  claim → remember(task_id) → abandon 계약이 "같은 배달이면 같은 태스크"와 정확히 같다

### 2.2 발동 — `neos/standing/triggers.py` `fire_trigger`

```
배달 ─▶ 꺼진 트리거?  ─▶ refused(trigger_disabled)
     ─▶ 필터 불일치?  ─▶ filtered            (claim 하지 않는다 — 필터를 고치면 같은 배달이 통과한다)
     ─▶ claim(trigger:{id}, delivery_id)
          졌다 ─▶ duplicate(먼저 연 task_id, 아직 여는 중이면 None)
          이겼다 ─▶ open_agent_task(mode=BACKGROUND, envelope=봉투)
                      거절 ─▶ abandon + refused(사유)   (에이전트를 다시 켠 뒤의 재전송은 발동해야 한다)
                      예외 ─▶ abandon + 다시 던짐
                      성공 ─▶ remember(task_id) + fired
```

- **본문은 언제나 untrusted 다.** 프롬프트 = 소유자 템플릿 + 고정 안내 한 줄(`UNTRUSTED_NOTICE`) + `wrap_untrusted_document(본문,
  "webhook:{trigger_id}")`. 본문에 `</untrusted_document>` 가 있어도 감싸개는 끝에서 한 번만 닫힌다(테스트)
- **트리거 태스크는 언제나 background 다**(READ_ONLY 천장, Q1). 바깥 세계가 보낸 일을 사용자가 맡긴 일(autonomous)로 올리지 않는다
- 에이전트는 `open_agent_task` 로만 연다 → 멈춘 에이전트(`agent_paused`) · 봉투(Q10a) 규칙이 그대로 걸린다
- 필터는 **타입까지** 같아야 맞다: `1 ≠ "1"`, `1 ≠ true`(bool 은 int 의 하위 타입이라 따로 막았다), 없는 키 ≠ `null`

### 2.3 서명과 HTTP

```
POST /api/v1/standing-agents/{agent_id}/triggers          {prompt_template, filters?} → 201 + secret(한 번만) + delivery_path
GET  /api/v1/standing-agents/{agent_id}/triggers          → 배열 (비밀 없음)
PATCH/DELETE /api/v1/standing-agents/{agent_id}/triggers/{trigger_id}
POST /api/v1/standing-triggers/{trigger_id}/deliveries    ← 인증 의존성 없음. 서명이 인증이다
     X-Neos-Timestamp: <유닉스 초>
     X-Neos-Delivery:  <[A-Za-z0-9_:-]{1,128}>
     X-Neos-Signature: v1=<hex HMAC-SHA256(secret, "{timestamp}.{delivery}." + body)>
```

- **배달 id 는 서명 안에 있다.** 밖에 있으면 창(기본 300초) 안에서 가로챈 요청을 id 만 바꿔 되풀이해 태스크와 예산을 찍어 낼 수 있다
- 📌 **배달 id 에 `.` 을 금한다.** 초안은 id 를 자유 문자열로 두었는데, 그러면 (id `a`, 본문 `b.c`)와 (id `a.b`, 본문 `c`)가 같은
  바이트에 서명된다 — 가로챈 요청을 **새 id 로** 되풀이할 수 있다. 경계가 하나로 정해지도록 문자 집합을 좁혔다(테스트가 이 재생을 직접 시도한다)
- **인증 실패는 전부 같은 401** 이다: 모르는 트리거 · 틀린 서명 · 창 밖 시각 · 모양이 틀린 헤더 · 헤더 없음. 모르는 트리거도 아무도 모르는
  비밀로 같은 검사를 한다 — 응답 모양으로도 시간으로도 있고 없음이 갈리지 않게
- 본문 상한(`max_body_bytes`, 기본 64KiB)은 **서명을 보기 전에** 413 이다
- 서명이 맞으면 결과와 상관없이 **202** 이고 본문 `{status, task_id, reason}` 이 결과를 말한다. 서명을 가진 발신자는 인증된 쪽이다
- 비밀은 만들 때 **한 번만** 응답에 싣는다. 파생이라 다시 보여 줄 수 있지만 보여 주는 길이 하나면 새는 길도 하나다
- 마운트: `standing_agents.enabled` **그리고** `standing_agents.triggers.enabled`. 트리거가 켜졌는데 `NEOS_TRIGGER_SIGNING_KEY`
  가 없거나 32자 미만이면 **설정 검증에서 시작을 거부한다**(`validate_standing_trigger_signing_key`)

## 3. Q10a — 에이전트 × 달력 월 봉투 ✅ 착지

### 3.1 지출은 따로 세지 않는다

루프는 매 단계 태스크의 **최신 체크포인트**에서 이어 간다(`run_service.advance_one_safe_point` → `latest_checkpoint(task_id)`).
그래서 체크포인트의 `cost_micros` 는 **태스크 전 생애의 누적**이다 — 재시도 런도 이어 받고, 자식(서브에이전트) 비용도 부모에
접혀 있다(`loop/_durable/spawn.py`).

```
봉투 지출(에이전트, 달) = Σ  최신 체크포인트(t).cost_micros
                          t ∈ 그 달에 연 그 에이전트의 태스크
```

- 📌 **Q13 설계 §4.3 의 `standing_agent_budgets(agent_id, period_start)` 테이블은 만들지 않았다.** 카운터를 두면 턴마다 더하는
  자리가 생기고, 그 자리를 빠뜨리거나 두 번 지나는 경로가 이중 계상·누락이 된다. 읽을 때 합하면 정본이 체크포인트 하나다.
  에이전트별 한도가 필요해지면(§5 열린 질문 3) 그때 한도 **설정** 테이블을 둔다 — 지출 카운터가 아니다
- 태스크는 **연 달에 속한다.** 달을 넘겨 도는 태스크의 지출은 연 달에 남는다
- 보관(archived)된 태스크도 센다 — 보관해도 쓴 돈은 그대로다. 체크포인트가 없는 태스크(첫 단계 전)는 0
- 달은 **UTC 달력 월**이다. 서울 11월 1일 01:00 은 아직 10월이다(테스트)

### 3.2 판정 — `envelope_verdict`

| 조건 | 사유 코드 |
|---|---|
| 전체 지출 ≥ 월 한도 | `budget_envelope_exhausted` (모든 모드) |
| background 이고 background 지출 ≥ ⌊한도 × `background_share`⌋ | `budget_background_share_exhausted` |
| background 가 아니고 `reserve_background_share` 가 켜졌고 (전체 − background) 지출 ≥ 한도 − ⌊한도 × 몫⌋ | `budget_handed_over_share_exhausted` |

- 경계에 **닿으면** 넘은 것이다 — 남은 것이 0 인 봉투로 연 태스크는 첫 턴에서 넘는다
- background 는 고정 몫만, 사용자가 맡긴 autonomous 는 봉투 전부. background 지출도 전체에 들어간다
- 🆕 **`reserve_background_share`**(기본 off, 2026-10-01): 켜면 background 몫은 **예약**이다 — autonomous 는 그 몫을 뺀 나머지까지만
  쓰고, 그 판정은 autonomous **자기 지출**(전체 − background)로 한다. 꺼져 있으면 autonomous 가 몫을 먹어 그달 background 가
  아무것도 못 할 수 있다 — 상시 에이전트가 "상시"이려면 켜는 쪽이다. 몫 1.0 으로 켜면 autonomous 몫은 0 이다. 판정 payload 가
  이 값을 싣는다(재계산 가능)
- 설정: `standing_agents.budget.{enabled=false, monthly_limit_micros=20_000_000, background_share=0.5, reserve_background_share=false}` — 매직넘버 없음(§9)

### 3.3 두 자리

| 자리 | 하는 일 | 근거 |
|---|---|---|
| `open_agent_task`(새 태스크) | **막는다** — `AgentTaskRefused(사유 코드)`. 자기소개(Q13f)·트리거(Q4a) 둘 다 이 문을 지난다. 멈춘 에이전트는 봉투를 읽기 **전에** 거절한다(쿼리 비용 없음) | D1 |
| 모델 턴 safe point(진행 중) | **섀도** — 에이전트 태스크만, 넘었을 때만 원장을 읽고, 이 **런**에 아직 없으면 `budget.judged` 하나(`enforced: false`). 봉투 고장은 런을 바꾸지 않는다 | D1 · Q5 와 같은 규율 |

- `LoopInput.agent_id` 를 더했다(권한에는 쓰지 않는다 — 소유 검사는 `owner_id` 하나다). `CodingRunService` 가 태스크에서 싣는다
- `budget.judged` 는 코딩 이벤트 fixture 에 `projected: false` + 사유로 등록했다 — 화면이 아니라 활동 피드·원장 판독기가 읽는다
- 조립은 `build_agent_envelope` 하나(`None` 이 off): API 의존성(`get_envelope`)과 코딩 런타임(`runtime.py`)이 같은 팩토리를 부른다

## 4. 단계

| 단계 | 무엇 | 테스트가 확인할 것 | 상태 |
|---|---|---|---|
| **Q4a** | 074 · `triggers.py` · 소유자 API · 서명 배달 API · 설정 검증 | 저장소 메모리·Postgres **같은 계약** · 남의 에이전트에 못 단다 · 지운 에이전트의 트리거는 배달에서 사라진다 · 사용자 삭제가 막히지 않는다(실 DB) · DB 에 비밀이 없다 · 필터 타입 엄격 · 서명: 본문·배달 id·시각 전부 서명 안, **`.` 이동 재생 거절** · 같은 배달 = 같은 태스크(두 멱등성 저장소) · 같은 id 라도 트리거가 다르면 다른 배달 · 거절·예외는 claim 을 풀어 재전송이 발동 · 인증 실패 6종이 **같은 401** · 413 은 서명 전 · 플래그 off 면 라우트 없음(제공되는 라우트로 읽는다) | ✅ 2026-10-01 |
| **Q10a** | `budget.py` · `open_agent_task` 게이트 · safe point 섀도 · `budget.judged` | 경계(≥) · 몫 내림 · 12월→1월 · UTC · 지출 원천 메모리·Postgres **같은 계약**(실 체크포인트를 seq 역순으로 써서 **최신**을 고르는지) · 남의 에이전트·사람 태스크·지난달·체크포인트 없음 제외 · 보관도 센다 · 자기소개도 봉투 안 · 루프: 런당 한 번, 새 런은 다시, 사람 태스크는 판정 자체를 안 함, 고장은 런을 안 바꿈 · 런 서비스가 `agent_id` 를 싣는다 | ✅ 2026-10-01 |
| **Q4b** | 채널 원천 — 지정 채널의 인바운드를 트리거로 | §5 열린 질문 1·2 가 먼저 | 📐 |
| **Q10b** | 진행 중 태스크의 봉투 초과 → `PAUSING → PAUSED` · 사람만 쓰는 재개 API · `task.status.changed` 투영 | Q5 와 **같은 길**을 쓴다(감시자·봉투가 `PAUSED` 의 두 작성자, 분석 §6 결정 3). Q5 경계 실측 뒤 | 📐 |

## 5. 열린 질문 (사람의 결정)

1. **Q4b 채널 원천의 발신자** — (a) 소유자에게 매핑된 사람(`channels.principals`)만 · (b) 채널 구성원 누구나(dots 방식, 본문은
   untrusted·background 이므로 위험은 **비용**이다 — Q10a 봉투가 그 상한이다) · (c) 트리거마다 허용 목록
2. **Q4b 와 대화 경로의 관계** — 감시 채널의 메시지가 트리거를 발동시키면서 **동시에** 보통 대화 응답도 받는가. `require_mention`
   이 켜진 배포에서는 멘션 없는 메시지가 어댑터에서 이미 버려진다 — 트리거가 그보다 앞에 서야 한다
3. **에이전트별 한도** — 지금은 배포 설정 하나가 모든 에이전트의 한도다. 사용자·에이전트별로 바꿀 수 있어야 하는가(그러면 Q2 의
   "좁히기만" 과 같은 방향 — 배포 한도를 **낮추기만**?)
4. **봉투 경고** — 넘기 전에(예: 80%) 소유자에게 알릴 것인가. 알림 경로(`send_to_channel`)는 있다

## 6. 되돌리지 말 것

- 트리거 본문을 `wrap_untrusted_document` 밖에서 프롬프트에 넣기 → 바깥 세계가 소유자의 지시를 쓴다
- 트리거 태스크를 autonomous 로 올리기 → READ_ONLY 천장이 풀린다
- 배달 id 를 서명 밖에 두거나 `.` 을 허용하기 → 창 안 재생으로 태스크·예산을 찍어 낸다
- 인증 실패를 사유별 다른 응답으로 → 트리거 id 존재 여부가 샌다
- 봉투 지출을 카운터로 따로 세기 → 정본이 둘이 된다(체크포인트와 카운터)
- 봉투 게이트를 `open_agent_task` 밖에 두기 → 새 입구(Q3·Q4b)가 생길 때마다 우회로가 된다
