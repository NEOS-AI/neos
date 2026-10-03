# Q5b 궤적 감시자의 `PAUSED` — 설계와 착지

> **작성:** 2026-10-02 · **트랙:** Q5b (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2 Q5 행 · §6.1)
> **지위:** 착지(플래그 `jev.monitor.enforce` off, 2026-10-02). 설계와 코드가 어긋나면 코드가 이긴다.
> **선행:** Q5 감시자 섀도(2026-09-30) · [Q10b 설계](Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md) §2 P1~P9(멈춤의 길)
> 결정 MP1~MP11 은 **위임받아 Claude 가 골랐다**(Q10b·Q3 과 같은 방식). 사람이 뒤집을 수 있다.

---

## 0. 한 줄

**감시자의 `would_pause` 판정이 태스크를 `PAUSED` 로 보낼 수 있게 한다 — Q10b 가 만든 길 그대로, 기본 off, 경계는 기본값 없이.**
Jev 와 폴백 규칙은 **플래그 하나로 함께** 올라온다(§6.1 "실제로 멈추는 것은 Jev 와 폴백이 함께 섀도에서 올라올 때").
이 착지는 멈추게 할 **수 있는** 코드다. 실제로 켜는 것은 경계 실측 뒤 사람의 결정이다(MP2).

## 1. 시작 전에 확인한 것

| 사실 | 근거 | 결과 |
|---|---|---|
| `pause_task` 는 판정 종류를 인자로 받는다. 메모리·Postgres 둘 다 종류를 가리지 않는다 | `run_repository.pause_task(judgement_type=...)` · `tests/coding/fakes.py` | 저장소를 고치지 않는다. 두 번째 멈춤 장치를 만들지 않는다(MP1) |
| 런 서비스·러너는 멈춤을 **판정 종류가 아니라** `task.status.changed {status: paused}` 로 안다 | `is_pause_event` · `run_service` 의 `TaskPaused` | 런 서비스·러너·재개 라우트·FE 는 그대로 쓴다 |
| 감시자 섀도는 **자식 한 걸음 뒤**에서 판정한다. 봉투 멈춤은 **자식 앞**이다 | `_advance_one_model_turn` | 집행 자리는 봉투 옆으로 옮기고, 섀도 자리는 그대로 둔다(MP4·MP8) |
| 섀도는 판정이 없는 턴에도 원장을 **seq 0 부터 끝까지** 읽는다 | `_read_ledger(reader, task_id, limit=...)` | 켜기 전에 커서화(MP6) |
| 📌 섀도의 `getattr(monitor, "max_events", 2000)` — `TrajectoryMonitor` 에 그 속성이 **없었다**. 설정 `jev.monitor.max_events` 는 한 번도 읽기에 닿지 않았다 | `monitor.py` · `assembly.py` | 커서가 설정값을 받는다(MP6). 기본값(2000)에선 동작이 같다 |
| 태스크 원장의 `seq` 는 `UPDATE coding_tasks SET last_seq = last_seq + 1 ... RETURNING` — 그 행 잠금이 커밋까지 간다 | `_allocate_sequence_in_session` | 한 태스크 안에서 seq 순서 = 커밋 순서. 커서가 늦은 커밋을 건너뛰지 않는다(MP6) |
| 원장을 지우거나 고치는 SQL 이 없다 | `grep "DELETE FROM coding_events"` 0건 | 기억한 꼬리는 언제나 옳은 앞부분이다 |
| `model.refused` 는 곧바로 `CodingLoopFailure("model_refused", retryable=False)` 다 | `model_turn.py` `_settle_text_only_turn` | FB5 는 루프 안에서 발동하지 않는다 — 집행에서는 무관하다(MP9) |
| 재개 라우트는 `standing_agents.enabled` 블록 **안에서만** 붙는다 | `neos/main.py` | 감시자는 모든 태스크를 멈추므로 밖으로 꺼낸다(MP7) |
| 💡 테스트의 가짜 원장(`LedgerEvents`)은 저장소 이벤트(1..)와 싱크 이벤트(100..)를 **따로 번호 매겨** seq 로 정렬했다 — 커서로 읽으면 이벤트를 건너뛴다 | `tests/coding/monitor/test_monitor_in_the_loop.py` | 가짜를 실제 원장처럼(도착 순서 = seq) 고쳤다. 기존 섀도 테스트 하나가 커서 도입으로 먼저 깨져 알려 줬다 |

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| **MP1** | **같은 길.** 멈춤은 `pause_task(judgement_type="monitor.judged", judgement=판정 payload, reason_code=...)` 한 트랜잭션이다. 런은 `running`, 런 서비스는 `TaskPaused`, 러너는 `PAUSED`, 재개는 사람만(`POST /coding/tasks/{id}/resume`). `PAUSING` 은 쓰지 않는다 | Q10b P1~P8 그대로. 감시자도 safe point **안에서** 판정하므로 요청과 커밋 사이가 없다(P2) — 0초짜리 `PAUSING` 은 사실이 아니다 |
| **MP2** | **멈춤 경계에 기본값이 없다.** `enforce` 는 ① `shadow_enabled`(그러므로 `jev.enabled` 와 `pause_at_or_above`) 위에서만 켜지고 ② **경계 필드 9개 전부**(`pause_at_or_above` + 폴백 FB1~FB6 의 임계 8개)가 설정에 **적혀 있어야**(`model_fields_set`) 한다 — 값이 기본값과 같아도 적어야 한다. 아니면 설정 검증이 실패한다. 조립(`build_trajectory_monitor`)이 같은 문을 한 번 더 본다 | 폴백 기본값은 §6.1 의 "첫 기본값" — 섀도 판정을 위한 값이지 실측된 멈춤 경계가 아니다. 로드맵은 Q5 의 `PAUSED` 를 "경계 실측 뒤"로 둔다. 기본값으로 멈추면 그 실측을 건너뛴 것이 된다. 적게 하면 "이 값으로 멈춘다"를 사람이 쓴 기록이 설정에 남는다. 박자(`every_n_tool_results`)·창(`max_events`)은 경계가 아니라 빈도라 빠졌다. 방향 제약(엄하게만)은 그대로다 |
| **MP3** | **플래그 하나가 Jev 와 폴백을 함께 올린다.** 판정자마다 따로 켜는 길은 없다. `enforce` 가 켜지면 **모든** 판정이 `enforced: true` 를 싣는다 — 멈춤은 `enforced ∧ would_pause` 다 | §6.1 규율. `enforced` 를 "멈췄다"가 아니라 "이빨이 있는 판정이었다"로 두면, 원장의 판정 하나만 보고 그 `would_pause` 가 멈춤이 됐는지 안다. 섀도 표본과 집행 표본이 섞이지 않는다 |
| **MP4** | **자리와 순서.** 모델 턴의 맨 앞, 턴 예산 검사 뒤 — **봉투 멈춤 → 감시자 멈춤 → (자식 한 걸음) → …**. 봉투가 멈추면 감시자는 그 턴을 판정하지 않는다. 멈춤 트랜잭션은 한 턴에 많아야 하나다 | 자식 앞인 이유는 Q10b P3 와 같다(멈출 태스크의 자식이 한 번 더 쓰지 않는다 · 상태 = 최신 체크포인트). 봉투가 먼저인 이유: 봉투 판정은 SQL 합 하나로 싸고 결정적이며 돈이다. 감시자는 Jev 호출(네트워크·타임아웃)이다 — 이미 멈출 태스크에 Jev 를 부르지 않는다. 감시자의 박자는 원장의 마지막 `monitor.judged` 가 기억하므로, 봉투로 멈춘 태스크를 재개하면 감시자가 다음 턴에 밀린 판정을 한다 |
| **MP5** | **감시자의 고장은 멈춤이 아니다.** 원장 읽기 실패·감시자 버그 → 로그 한 줄, 멈추지 않는다(다음 판정 차례에 다시). **Jev 의 실패는 고장이 아니다** — 폴백 판정이고 그 판정은 멈출 수 있다(`jev_unavailable`). 멈춤 커밋 실패(`StaleExecutionLease`)는 그대로 올라간다 | Q10b P5 와 같은 계산: 읽기 실패에 멈추면 DB 깜빡임마다 사람이 재개해야 한다. Jev 가 죽었을 때 멈추지 못하면 폴백 규칙이 있는 이유가 없다(D-L1). 리스를 잃은 쪽은 멈춰야 한다 |
| **MP6** | **원장 커서.** `LedgerTail` 이 태스크마다 마지막으로 본 `seq` 와 최근 `max_events` 개를 기억하고 그 뒤만 읽는다. 한 워커 프로세스 안의 상태이고 태스크 64개(LRU)까지 기억한다 — 넘치면 잊고 다음에 처음부터 읽는다(값이 아니라 비용만 바뀐다). 겹친 쪽은 seq 로 한 번만 잇고, 읽다 실패해도 이은 앞부분은 버리지 않는다. 섀도 자리도 같은 커서를 쓴다 | seq 순서 = 커밋 순서(§1)라 커서가 옳다 — 합친 원장의 `created_at` 커서와 다르다. 원장은 append-only 라 다른 워커가 그 사이에 쓴 것이 있어도 기억한 앞부분은 옳다. 판정 박자를 원장이 기억하는 Q5 의 모양은 그대로다 — 커서는 읽기 비용이지 판정의 입력이 아니다. DB 쪽 커서 테이블을 두지 않은 이유: 워커가 바뀔 때 한 번 처음부터 읽는 값이 섀도 착지의 **매 턴** 값과 같다 |
| **MP7** | **재개 라우트는 멈출 수 있는 쪽이 있으면 있다.** `resume_route_mounted(config) = standing_agents.enabled or jev.monitor.enforce` 하나가 정하고, `neos/main.py` 는 그것을 `standing_agents` 블록 **밖에서** 부른다 | 감시자는 에이전트 태스크만이 아니라 모든 태스크를 멈춘다. 상시 에이전트를 끈 채 감시자만 켜면 멈춘 태스크가 돌아올 길이 없다 — 멈춤이 덫이 된다(Q10b P8). 멈출 수 없는 앱에는 여전히 라우트가 없다 |
| **MP8** | **off 는 바이트가 같다.** `enforce` 가 꺼져 있으면 판정 자리(자식 뒤)·payload(키 순서까지)·`enforced: false` 가 Q5 섀도와 같다. 켜져 있으면 섀도 자리는 판정하지 않는다 — 집행 자리가 고장 났어도 섀도 자리가 그 턴을 다시 판정하지 않는다 | Q10b P9 와 같은 규율: 켜는 커밋만 경계가 된다. 한 턴에 판정 시도는 하나 |
| **MP9** | **FB5 는 고치지 않는다.** 루프 안 자리에선 `model.refused` 뒤에 safe point 가 없다. 집행에서는 무관하다 — 거절은 이미 비재시도 실패로 런을 끝내고, 그것은 멈춤보다 강하다 | 남은 것은 **섀도 측정**의 구멍이다(FB5 의 발동 수가 0 으로 읽힌다). 루프 밖 판독이나 종료 시점 판정이 필요하고, 그것은 멈춤 경로가 아니다 — §5 |
| **MP10** | **소유자 알림은 더하지 않는다.** 화면은 기존 `paused` 배지·Resume 버튼으로 본다 | 알림 대상은 에이전트마다다(`standing_agent_notify_targets`, O2). 감시자는 사람 태스크도 멈추고, 사람 태스크에는 대상이 없다. 에이전트 태스크만 알리려면 봉투의 알림기를 감시자에 따로 배선해야 한다 — D7 "두 번 배선하지 않는다"에 걸려 이 트랙 밖으로 둔다 — §5 |
| **MP11** | **재개 뒤의 박자.** 멈춤의 `monitor.judged` 가 `tool_results` 를 기억하므로 재개한 태스크는 도구 결과 N 개가 더 쌓일 때까지 판정되지 않는다(봉투와 다르다 — P7 의 봉투는 다음 턴에 다시 멈춘다). 📌 단, FB1·FB2·FB4 는 `max_events` 창 안의 **누적** 이벤트를 센다 — 같은 증거가 창 안에 남아 있으면 N 개 뒤의 판정이 다시 멈춘다 | 감시자는 멈추게만 하고 재개시키지 못한다(트랙 L). 사람의 재개는 "N 개 더 보겠다"이지 "이 증거를 지운다"가 아니다. 재개 이후만 보는 창은 규칙의 뜻을 바꾸므로(`RULESET_VERSION`) 실측 뒤의 결정이다 |

### 2.1 표면

- 설정: `jev.monitor.enforce`(기본 `false`). 켜려면 `jev.enabled` · `jev.monitor.shadow_enabled` · 경계 9개를 **전부 명시**
  ```yaml
  jev:
    enabled: true
    model: jev-1.13.0
    monitor:
      shadow_enabled: true
      enforce: true
      pause_at_or_above: 0.8     # 실측값으로 — 아래 8개도 기본값과 같더라도 적는다
      user_only: 1
      mode_ceiling: 2
      denial_window: 10
      denials_in_window: 3
      repeated_call: 3
      refusals: 1
      spend_multiple: 4.0
      spend_warmup_turns: 5
  ```
- 이벤트: 새 kind 없음. `monitor.judged` 의 `enforced` 가 `true` 일 수 있게 됐고(fixture reason 갱신),
  멈춤은 같은 트랜잭션의 `task.status.changed {status: paused, reason_code}` 로 투영된다.
  `reason_code` = `monitor_jev` · `monitor_fallback_fb1` … `monitor_fallback_fb6`
- API: 새 라우트 없음. `POST /api/v1/coding/tasks/{task_id}/resume` 의 마운트 조건만 넓어졌다(MP7)
- FE: 바뀐 것 없음 — `paused` 배지·Resume 버튼은 판정 종류를 보지 않는다
- 마이그레이션: 없음

## 3. 테스트가 확인하는 것

| 무엇 | 테스트 |
|---|---|
| Jev 가 선을 넘으면 모델·도구 없이 멈춘다 · 판정+상태 · `reason_code` · 런은 `running` · 섀도 판정이 따로 쌓이지 않는다 | `tests/coding/monitor/test_monitor_pause.py` |
| Jev 가 대답하지 못하면 폴백(FB4)이 멈춘다 — 플래그 하나 · 선 아래 판정은 `enforced: true` 로 한 번 기록되고 계속 간다 | 같은 파일 |
| off 는 Q5 섀도와 payload(키 순서까지)가 같다 · off 의 판정 자리는 여전히 자식 뒤 | 같은 파일 |
| 사람 태스크도 멈춘다 · 자식 한 걸음보다 먼저 · 감시자 고장은 멈추지 않는다 · 읽을 수 없는 싱크는 판정하지 않는다 | 같은 파일 |
| 봉투와 감시자가 같은 턴에 멈추려 하면 멈춤 트랜잭션은 하나, 봉투의 것 · 감시자는 그 턴을 판정하지 않는다 | 같은 파일 |
| 켜져 있으면 섀도 자리가 그 턴을 다시 판정하지 않는다 · 멈춤 뒤 박자 | 같은 파일 |
| 커서: 둘째 읽기는 마지막 seq 뒤부터 · 새 것이 없으면 빈 쪽 하나 · 최근 `max_events` · 태스크별 · LRU 로 잊으면 처음부터 · 겹친 쪽 중복 없음 · 실패해도 앞부분 유지 · `max_events` 설정이 읽기에 닿는다 | `tests/coding/monitor/test_ledger_tail.py` |
| 기본 off · 섀도 없이 못 켬 · 경계 9개 각각이 빠지면 거절(매개변수화) · 섀도는 기본값으로 그대로 · 경계를 적어도 느슨하게는 못 함 · 조립이 검증 우회 설정을 막음 | `tests/coding/monitor/test_monitor_enforce_config.py` |
| 메모리·Postgres **같은 계약**: `monitor.judged` 멈춤 한 트랜잭션 · 봉투가 먼저 멈춘 태스크는 다시 못 멈춤 · 실 원장에서 커서가 멈춤의 판정까지 읽고 박자를 지킨다 | `tests/coding/monitor/test_monitor_pause_repository.py` (실 DB) |
| 재개 라우트: 멈출 쪽이 없으면 없다 · 봉투 · 감시자 집행만 켜도 있다 · 섀도만은 없다 · `main.py` 가 블록 밖에서 술어로 붙인다 · **실제 앱을 그 설정으로 띄워** 라우트가 있고 상시 에이전트 라우트는 없다 | `tests/api/test_monitor_resume_route.py` |

## 4. 변이 21/21

M1 멈춤 자리가 `enforce` 를 무시 · M2 멈춤 자리를 자식 뒤로(감시자 멈춤 빠짐) · M3 감시자를 봉투 앞으로 ·
M4 봉투가 멈춘 턴에도 감시자 판정 · M5 켜져 있는데 섀도 자리가 다시 판정(**처음엔 살았다** — 선 아래 판정은 박자가 막아 줘서
드러나지 않았다. 고장 난 집행 자리 뒤에 섀도가 재시도하는 경우를 테스트로 더했다) · M6 `enforced` 언제나 거짓 ·
M7 감시자 고장이 멈춤 자리 밖으로 · M8 선 아래 판정을 기록하지 않음 · M9 경계를 기본값에 맡김 · M10 섀도 없이 집행 ·
M11 조립 문 제거 · M12 조립이 `enforce` 를 떨굼 · M13 재개 술어가 감시자를 무시 · M14 `main.py` 가 상시 에이전트 플래그로 마운트 ·
M15 커서가 늘 0 부터 · M16 커서 중복 · M17 실패하면 꼬리를 잊음 · M18 LRU 없음 · M19 폴백 사유 코드가 `monitor_jev` ·
M20 감시자 멈춤을 `budget.judged` 로 · M21 `max_events` 를 넘기지 않음.

## 5. 남은 것

- **켜기** — 경계 실측(섀도 표본의 `would_pause` 비율, `jev_unavailable` 비율, 폴백 규칙별 발동 수 — §6.1 감시 조건) 뒤 사람이
  경계 9개를 적고 `enforce` 를 켠다. 이 트랙은 그 값을 정하지 않았다
- **FB5 측정** — 루프 밖 판독 또는 종료 시점 판정(MP9). 집행과 무관하다
- **소유자 알림** — 에이전트 태스크의 감시자 멈춤을 봉투의 알림 큐(`standing_notifications`)로. 알림기를 봉투와 감시자가 함께
  쓰게 하는 배선이 필요하다(MP10)
- **재개 이후 창** — 누적 규칙이 같은 증거로 다시 멈추는 것(MP11). 바꾸면 `RULESET_VERSION` 을 올린다
- **멈춘 태스크의 만료** — Q10b §7 과 같다(무기한 멈춘다)

## 6. 되돌리지 말 것

- 감시자 멈춤을 `pause_task` 밖의 두 번째 장치로 → 런 서비스·러너·재개가 모르는 멈춤이 생긴다
- 경계 필드를 기본값으로 집행 → 실측을 건너뛴 경계로 태스크가 멈춘다
- Jev 와 폴백을 따로 켜기 → §6.1 "함께" 규율이 깨진다
- 감시자를 봉투 앞에 → 이미 멈출 태스크에 Jev 를 부르고, 두 멈춤이 한 턴을 다툰다
- 재개 라우트를 `standing_agents` 블록 안으로 → 감시자만 켠 앱에서 멈춘 태스크가 돌아오지 못한다
- 커서를 `created_at` 으로 → 늦은 커밋을 건너뛴다(태스크 seq 는 커밋 순서라 옳다)
- 가짜 원장을 seq 정렬로 되돌리기 → 커서 테스트가 실제 원장과 다른 것을 검증한다
