# 심층분석 하네스 — 완료 기록

> **이 문서는 [로드맵 정본](DEEP_ANALYSIS_HARNESS_ROADMAP.md)을 진행하며 착지한 작업의 기록이다.**
> 로드맵은 "남은 것"과 "지켜야 할 것"만 들고, 착지한 항목의 경위·숫자·발견은 여기로 옮긴다.
> 트랙 Q 의 항목 정의·결정은 여전히 [dots 분석](OPENAI_DOTS_ANALYSIS_260930.md)이 정본이다.
>
> **수치와 판정의 원본은 이 문서가 아니다.** 수치는 `deep_analysis_events`·아티팩트, 판정은
> `neos/workflow/deep_analysis/DECISIONS.md`. 충돌하면 원본이 이긴다.
>
> **갱신 규칙**
> - 로드맵에서 항목이 착지하면 **경위는 여기에**, 로드맵에는 한 줄 + 이 문서의 절 링크만 남긴다
> - 여기 적힌 서술도 반증되면 지우지 않고 취소선으로 남긴다
> - "테스트 N · 변이 M/K" 는 착지 커밋 시점의 수다. 회귀 판정에 쓰지 않는다(로드맵 §10.4)
>
> 옮기기 전 원문(취소선 이력 포함)은 git 에 있다: `git show 0fbfdbe4:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`
> · `git show 0fbfdbe4:docs/OPENAI_DOTS_ANALYSIS_260930.md`

---

## 1. 트랙 J — 코딩 루프 조사

정본 계약: [DEEP_ANALYSIS_CODE_RESEARCH_CONTRACT.md](DEEP_ANALYSIS_CODE_RESEARCH_CONTRACT.md). 전부 플래그
`deep_analysis.code_research_enabled` 뒤. **플래그 뒤 병합은 표본 경계가 아니다**(로드맵 §8).

| 단계 | 착지 | 무엇 |
|---|---|---|
| J0 | 2026-09-15 | 계약 문서: 스펙 셋 · 도구 넷 · `ComputedEvidence` · 거절 코드 다섯 · 이벤트 kind 여섯 · `research-offline-v1` · 불변식 I1~I7 |
| J1 | 2026-09-23 → 2026-09-28 | 도구 경계(`fetch.v1`→`fetch.py`, blob 읽기 전용 마운트, `submit.v1`, 카탈로그 fail-closed 셋째 타입) · S9 바이트 동일 테스트. 09-28 코드 대조에서 **부분 착지**로 정정(아래) → 같은 날 J1.5 가 채웠다 |
| J2 | 2026-09-28 | 계산 클레임 채점기 + 재실행 + 이벤트 짝. 처음엔 합성 fixture 에서만 초록 → J1.5 로 실제 경로 E2E 초록 |
| J3 | 2026-09-21 | 오프라인 섀도 — `shadow.py` · `cassette_model.py` · `scripts/deep_analysis_offline_shadow.py`. brief 는 `assignment.build_assignment` 로 오케스트레이터와 공유. ⚠️ brief 가 **지금** 원장 상태로 조립되므로 "그때 그 패스"의 재현이 아니다 — 보고서가 그렇게 말한다 |
| J1.5 | 2026-09-28 | 조사 자식이 코드를 돌린다(아래) |

### 1.1 J1 이 비어 있던 것 (2026-09-28 코드 대조)

계약 §2 의 research 도구 열 개 중 포트가 내미는 것은 `fetch.v1`·`submit.v1`·`check_claims.v1` 셋뿐이었다
(`research_tools.py` `definitions()`). `ChildStepper` 가 포트 ∩ 스펙만 보여 주므로 `execute.v1`·`read_file.v1`·
`write_file.v1` 이 사라졌다 — 샌드박스는 열리지만 쓰이지 않았다. 스크립트를 원장 blob 으로 넣는 경로도 없어서
J2 는 **합성 fixture 에서만** 초록이었다. §11 인벤토리가 J3 착지를 적는 동안 §1 J 행은 J1 에 머물러 있었다 —
낡은 서술이었다.

### 1.2 J1.5 — `execute.v1` → 계산 클레임 → 재실행 → verified (2026-09-28)

완료 조건을 **진짜 원장 위에서** 충족했다(`tests/workflow/deep_analysis/test_code_research_e2e.py`, 가짜는 자식 모델과
`fetch_url` 둘뿐). 테스트 스물여섯 + E2E 하나, 변이 스물둘.

1. **포트 합성** — `ResearchToolPort` 가 `CodingSurface`(질문 샌드박스 세션 + 레지스트리 + 게이트)를 받아 코딩 도구
   다섯(`list_tree`·`read_file`·`search_text`·`write_file`·`execute`)을 내민다. 정의는 레지스트리의 것을 그대로 쓴다.
   레지스트리의 `command_allowlist={"python3"}` 가 계약 §3.2 의 argv allowlist 를 코드로 만든다(`-c`·셸은 레지스트리가 막는다)
2. **조사 자식의 게이트**(CHILD-GATE 의 조사 절반) — 코딩 자식과 같은 `authorize` 모양, 판정 자리는 오케스트레이터
   (`research_gate.py`). 규칙은 하나: **재실행기가 똑같이 다시 돌릴 수 있는 것만** — argv 는 `python3 <워크스페이스의 .py>`
   하나, cwd 는 루트, env·stdin 없음, `evidence/` 쓰기 금지. 거절은 원장 `code_tool_denied`(FE 라벨 짝). 바인드 없는
   게이트는 전부 거절(`policy_gate_unbound`)
3. **스크립트 → 원장** — `execute.v1` 은 실행기를 거치지 않고 재실행기와 **같은 호출**로 돈다(실행기는 출력을 미리보기로
   잘라 digest 가 달라진다). 돌리기 **전에** 스크립트를 blob 으로 넣고 digest 는 재실행기와 같은 함수(`digest_stdout`).
   한도에 걸린 실행에는 digest 를 주지 않는다. 스크립트 blob 은 `sandbox-script://` 로 표시되고 **두 채점기가 그것을
   증거·입력으로 거절한다** — 없으면 워커가 자기 스크립트를 quote 로 인용해 통과시킬 수 있었다(I4). `/evidence` 한도에
   청구하지 않는다
4. **brief 전달** — 조사 티켓 briefing 이 이 질문의 verified quote 클레임을 **ID 와 함께**(`why`), 막다른 길
   (`already_tried`), 수선 지시(`scope`)를 싣는다

🔍 **계획에 없던 구멍 둘**
- (a) 계산의 `premises` 는 원장 claim_id 여야 하는데 자식은 그 ID 를 볼 길이 없었다(`verified_summaries` 는 본문만).
  사람의 결정: **다음 라운드에 ID 공개** — 계산은 둘째 라운드부터 가능하다
- (b) E2E 가 찾았다: 질문 샌드박스는 라운드마다 새로 열려 **라운드 1 의 `/evidence` 가 라운드 2 에 없었다.**
  `LedgerEvidenceStore.restore` 가 원장에서 다시 놓는다(계약 §9 결정 4)

📌 **계약 해석 변경(사람의 결정):** research 자식도 계산 클레임을 낸다(계약 §2 는 analyze 몫으로 적었다). 대신 결정 3 의
"같은 질문" 을 briefing 기대가 아니라 **채점기 규칙 2 로 강제**한다. J3 섀도도 같은 한도·briefing 을 받는다
(`command_limits` 는 기본값 없이 필수 — 호출부 둘이 모두 적어야 한다).

### 1.3 GRADE1 — 계산 클레임의 판정 프롬프트 (2026-09-28)

재실행을 통과한 계산 클레임이 판정자에게 **빈 증거 블록**("(증거 없음)")으로 가서 UNRELATED 로 떨어질 수 있었다.
이제 전용 프롬프트 `judge_computed.md`(v1)로 판정한다 — 계약 §5 대로 **질문 · 재실행으로 확인된 값 · 전제 인용**을
싣고 "문장이 값과 전제를 넘지 않는가, 계산이 질문에 답하는가"만 묻는다(산술은 결정론 채점기 몫). 맥락 없이 온 계산
클레임은 판정하지 않고 거절한다(`computed_context_missing`, 토큰 0). 인용 클레임의 판정 프롬프트는 바이트가 같다(테스트).

딸려 고친 것: 수리가 `pending` 으로 되돌린 계산 클레임을 `_regrade_pending` 이 **인용 클레임으로 재채점**하고 있었다
(`kind`·`computation` 을 되짓지 않았다).

📌 런 매니페스트의 `prompts` 에 `judge_computed` 해시 키가 **하나 늘었다** — 이 커밋 앞뒤 매니페스트는 그 키로 다르다.

### 1.4 출하 기준 S7~S10 의 경위

| # | 경위 |
|---|---|
| S7 | 🟡 J2 착지 때는 합성 fixture 에서만 → 🟢 J1.5 로 실제 경로(메모리 provider 의 진짜 `python3`)에서 초록 |
| S8 | 🔴 스크립트를 원장에 넣는 경로 없음 → 🟡 클레임이 된 실행만 복원 → 🟢 **모든 실행** 복원(같은 날 두 단계). ① `execute.v1` 은 돌리기 전에 스크립트를 blob 으로 넣고 결과에 `script_ref`·`output_digest` 를 싣는다. ② 실행마다 `script_executed`(`script_ref`·`output_digest`·종료 코드·한도 여부·`evidence_refs`)를 결과를 주기 **전에** 남긴다 — 버린 시도도 남는다. `evidence_refs` 는 그때 샌드박스에 놓여 있던 증거의 **상한 집합**이고 정확한 입력은 클레임의 `inputs` 가 싣는다. 한도에 걸린 실행은 digest null. 라벨 없음(`compute_reexecuted` 와 같은 이유). 테스트 넷 + E2E 단언, 변이 넷 |
| S9 | `tests/workflow/deep_analysis/test_code_research_invariants.py`(I1 절) |
| S10 | 같은 파일이 development 밖·managed 평면 없음 거절과 Docker `network=none` 강제를 고정. Docker 경로의 계약 §3.2 downgrade 는 §3.6 ③ 에서 닫혔다 |

---

## 2. 트랙 K — Fable 5.1 적응

입력: [fable-5-1-multiagent-spec.md](fable-5-1-multiagent-spec.md). 표본 없이 되는 K 는 2026-09-15~28 에 다 썼다.

### 2.1 착지 목록

| ID | 착지 | 무엇 |
|---|---|---|
| **K0** | 09-15 | `models.yaml` 에 `claude-fable-5-1` 등재(출처: claude-api 레퍼런스 "Migrating to Claude Fable 5.1" — 1M 창 · 128K 출력 · thinking 항상 켜짐 · $10/$50 · 캐시 읽기 $0.25 · 대화 중간 system 지원). `selectable: false`. 카탈로그 `mid_conversation_system` 필드(opus-5 · opus-4-8 · fable-5-1 = true, **sonnet-5 = false**). `tests/config/test_model_catalog_fable.py`. 📌 원문에서 새로 안 것: thinking 은 끌 수 없다(라우팅하는 순간이 켜는 순간) · 강제 `tool_choice` 는 400 · 최근 턴을 남기는 컴팩션도 허용(남긴 턴의 thinking 만 떼면). ⚠️ 별건: 카탈로그 `claude-sonnet-5` 가격(3/15)이 레퍼런스(2/10)와 다르다 — 고치지 않았다 |
| **K1** (R-01) | 09-15 | `ThinkingContent`·`ThinkingCompleted` 공통 형식, 어댑터가 서명째 왕복, 체크포인트 왕복. **durable 루프의 `_guard_thinking_prefix` 한 곳**이 직전 요청의 system·tools·메시지 digest 와 비교해 다르면 그 경계에서 thinking 을 **전부** 뗀다 — 컴팩션 셋·헤드 드롭·결과 축소·도구 공개·system 재구성을 경로별로 고치지 않았다 |
| **K1c** | 09-17 | 자식(`subagent/stepper.py`)은 thinking 을 기록·재생하고 자기 컴팩션이 도구 본문을 다시 쓸 때만 뗀다. DA 는 하네스 브리지(`turn_to_llm_response`·`messages_to_canonical`)와 주입 SDK 경로(`llm._blocks_to_dicts`) 둘 다. 서명 없는 블록은 버린다(전에는 **JSON 텍스트로 대화에 섞였다**) |
| **K1d** | 09-17 | `SubagentSpec.thinking` 은퇴. 자식의 `thinking="off"` 를 지킨다는 단언은 읽는 속성이 없어 **언제나** 통과했다 |
| **K2** (R-02) | 09-15 | `CanonicalMessage("system", (SystemNoteContent,))`. Anthropic 어댑터는 `mid_conversation_system` 과 배치 규칙(user 뒤 · 마지막이거나 assistant 앞)을 둘 다 만족할 때만 네이티브 + beta 헤더, 아니면 tool_result 뒤 text. 나머지 프로바이더는 user 텍스트. pre_generate 훅의 system 노트가 system 프롬프트를 매 턴 다시 쓰던 것을 이 경로로 옮겼다 |
| **K2b** | 09-19 | 모든 도구를 한 번만 선언하고 deferred 는 `defer_loading` 으로 감춘다. 공개는 `tool_addition` 블록을 **덧붙인다** — `tools[]` 가 변하지 않아 앞선 thinking 이 산다(17→18 로 자라던 배열이 원인). `deferred` 는 도구의 **정적** 속성 — 공개 때 뒤집으면 배열이 다시 흔들린다. 카탈로그 `mid_conversation_tools` 로 게이트, **`claude-fable-5-1` 에만** 켰다 |
| **K3** (R-03) | 09-22, 기본 off | `subagent_async_spawn` 이 켜지면 `spawn_agent.v1` 이 run_id 가 생기는 즉시 결과를 쓰고 자식은 부모 lease 아래 계속 돈다. 부모의 매 모델 턴 앞(safe point)이 detached 자식을 한 칸씩 밀고, 끝난 자식의 보고서를 **user 메시지로 append**(K1 가드 때문에 append 가 유일한 자리). `await_subagent.v1` 은 명시적 park — 보고서는 그 호출의 도구 결과. 부모는 자기 자식이 살아 있는 동안 끝낼 수 없다(`_hold_for_detached_children`), 한계는 자식의 남은 턴. 자식을 티켓 없이 미는 것은 `SubagentRuntime.resume`, brief 는 store 의 `RunRecord` 에서. ⚠️ `_CONTROL_PLANE_TOOLS` 사본이 둘이었다 — 레지스트리 한 곳으로 합쳤다 |
| **K4a** (R-04) | 09-19 | 루프가 thinking 블록마다 `model.thinking`(200자 프리뷰·원본 길이·잘림 여부, **서명 없음**). 스트림을 persisted 로 표시하지 않는다(그러면 일시 오류 뒤 거의 모든 턴이 재시도 불가). Code UI 는 최신 노트를 상태 줄로 두고 모델이 말을 시작하면 지운다. 🔴 그 상태 줄을 **그리는 컴포넌트가 0개**였다 — §3.4 에서 잡혔다 |
| **K4b** | 09-24 | §2.2 |
| **K1b** | 09-24 | §2.2 |
| **K5** (R-05) ①~③ | 09-21 | 카탈로그 `effort_levels` · `resolve_effort` 사슬(모델과 같은 사슬, 미지원 레벨은 낮추지 않고 거절) · 어댑터 `output_config.effort` |
| K5 채팅 | 09-24 | 모델별 기본값(`model_routing.effort.models`) · 사용자 선호 DB · 피커([설계](MODEL_EFFORT_PREFERENCES_DESIGN.md)). 카탈로그 레벨은 실측으로 채웠다 |
| K5 ④ DA | 09-24 | 🔴 `resolve_harness_effort` 의 프로덕션 호출부가 **0개**였다. DA `llm.py` 네 함수가 `effort` 를 세 출구(주입 SDK · 하네스 `ModelLimits` · 카세트 키)로 나르고 호출부 열둘이 역할별 값을 싣는다. **모델별 기본값 칸도 DA 에 빠져 있었다.** 매니페스트가 역할마다 `effort{level, source, refused}`. AST 가드가 DA 패키지 모든 호출부에 `effort=` 명시를 요구(다섯 변이). 값이 없으면 요청·카세트 키가 바이트 동일 — 경계 아님 |
| K5 ④ 코딩 | 09-28 | 설정 칸 `coding_model.effort` · `resolve_coding_effort` 가 DA 와 **같은 사슬**로 런타임마다 한 번 해석 · 세 자리가 싣는다: 루프 턴 · 보존형 컴팩션 요약(옛 512 토큰 요약에는 싣지 않는다) · 자식(**해석한 모델과 같은 모델로 돌 때만** — 스테퍼가 모델과 짝으로 쥔다). 거절은 조립 때 경고 로그. ⚠️ 모델별·`everyday` 기본값은 이제 채팅·DA·코딩에 함께 걸린다. 테스트 열하나, 변이 여덟 |
| **K6** (R-06) | 09-19 | `normalize_stop_reason` 넷째 결과 `refusal` 이 `has_tool_calls` 보다 우선(거절한 턴의 도구는 실행하지 않는다). 어댑터가 `stop_details.category` → `ModelCompleted.stop_category`, 루프가 `model.refused` 를 남기고 **재시도 없이** `model_refused` 로 끝낸다. 전에는 `unknown` 으로 뭉개져 텍스트가 있으면 `model_output_incomplete`, 없으면 **빈 텍스트 재시도**였다. 메트릭 outcome 도 분리. **base64 는 전제가 틀렸다** — 부모는 `redact_sensitive` 가 이미 401자로 자르고(쓸 수 없는 조각이 `truncated: False` 옆에 남았다), 자식 포트는 **아무 축약도 없었다**. `strip_binary_payloads` 를 **매핑이 만들어지는 두 곳**에 걸었다 |
| **K7** (R-07) | 09-15 | 가드로 착지. ~~정확히 금지된 형태~~ → 원문은 최근 턴 보존 컴팩션을 허용한다. G2(요약을 system 에)도 컴팩션 경계에서 thinking 을 떼면 유효 — ~~G2 CLOSED 재개~~ 는 과잉 처방이었다 |
| **P-05** | 09-25, 기본 off | 감사해 보니 **반대였다**: `facts only. <= 200 words` · 출력 512 · 30초. `coding.compaction_preserving_summary` 가 켜지면 공식 블록(`neos/coding/prompts/official.py` — 공식 문구의 첫 거주지)을 system 으로, 상한 `compaction_summary_max_tokens`(4096, 잠정). 📌 스펙 파일 문구는 초안이었다 — 원문 대조(1258자 일치), 코드↔스펙 바이트 일치 테스트. 추출 정책: 태그 쌍이 온전하면 안쪽 · 태그 없이 끝까지 썼으면 전체 · **태그 쌍 없이 `max_tokens` 면 버린다**(경고 로그 — 불완전 요약이 매 턴 실리는 조용한 실패보다 헤드 드롭이 낫다). 꺼지면 요청이 예전과 같다 |
| **K9** 모드 신호 | 09-28 | 사람의 결정: **태스크 요청 필드**. `CreateCodingTaskRequest.mode: interactive|autonomous`(기본 interactive) → `coding_tasks.mode`(068) → `task.created` payload → 매 safe point 에 태스크에서 읽어 `LoopInput.mode`. autonomous 면 부모 승인 판정이 unattended — REQUIRE_APPROVAL 을 DENY 로 접는다. **D-L1 의 접기가 처음으로 프로덕션 경로를 갖는다**(전에는 `approval_unattended` 를 `runtime.py` 가 넘기지 않아 테스트에서만 초록). 테스트 여덟, 변이 여섯 중 다섯(살아남은 하나는 동등 변이). 채널 생성 태스크는 채널에서 `decide` 로 승인할 수 있으므로 interactive 가 맞다(확인) |
| **K9** 오버레이 + P-02 | 09-28 | autonomous 태스크의 system 은 P-01 공식 두 블록("You are operating autonomously…" · "# Delivering work")으로 **시작한다**(원칙 2). 이어 P-02(사람의 결정: autonomous 에만 먼저). interactive 는 바이트 동일. §10.5 절차대로 원문을 먼저 대조 — **스펙의 P-01·P-02 초안이 둘 다 공식 문구와 달랐다**(P-01 은 첫 문장부터). 테스트 넷, 변이 넷. 📌 경계가 아니라 **새 계보의 시작**(autonomous 로 돈 태스크가 없었다) |

### 2.2 K1b · K4b 실측 (2026-09-24)

`scripts/fable_binding_probe.py` · 아티팩트 `artifacts/fable-k1b/` 네 세션(대면 · 자율 병렬 · 자율 사슬 7턴 ·
사슬 + `summarized`). 대화를 **NEOS 경로**(`_completed_turn` 과 같은 접기 → `_to_anthropic_request`)로 몰고
매 요청을 `drop_block` 진단 모드로 보냈다.

| 무엇 | 결과 |
|---|---|
| K1b — NEOS 경로 재전송 | 네 세션 모든 턴에서 `input_transformations: []`. `summarized` thinking(68자)도 같다 |
| 음성 대조 — system 을 일부러 바꾼다 | `thinking_dropped` / `prefix_binding_mismatch` — **진단이 살아 있다** |
| 같은 변조, 바인딩 제어 없이 | **200** — 스펙은 400 이라 적었다. 🔴 **이 계정에서는 불일치가 조용하다** — `_guard_thinking_prefix` 가 유일한 방어다 |
| thinking 순서 | 늘 턴 **첫 블록**. 중간에 끼는 응답은 없었다 — 반증되지 않았을 뿐 확인되지 않았다 |
| K4b — `display` 안 보냄 | thinking 본문이 **빈다**(서명만). 서버 기본은 `omitted` — SDK 독스트링(`summarized`)이 틀렸다. **K4a 상태 줄이 Fable 5.1 에서 늘 비어 있었다** |
| `display` 값 검사 | 모르는 값 → 400 `'summarized', 'omitted', 'updates'`. `updates` 는 서버가 안다(SDK 타입에만 없다) |
| `updates` 의 본문 | 비어 있지 않은 블록 0(thinking 13~16 토큰 — 모델이 거의 생각하지 않았다). `summarized` 는 본문을 준다 |

**고친 것**
- K4b: 카탈로그 `thinking_display`(서버가 받는 셋만, adaptive 모델에만), Fable 5.1 에 `updates`. 선언한 모델에만
  `thinking` 과 베타를 싣는다 — 나머지 모델의 요청은 바이트 동일
- **reasoning 토큰이 늘 0 이었다.** 어댑터가 `usage.reasoning_tokens` 를 읽었는데 API 는
  `usage.output_tokens_details.thinking_tokens` 에 싣는다. 가짜 클라이언트가 **없는 필드를 지어내** 초록이었다.
  고치자 두 번째 결함: 예산이 `output + reasoning` 을 더했는데 thinking 은 이미 output 안이다. reasoning 을 output 의
  **내역**으로 정의하고 예산 합에서 뺐다. 경계 아님

---

## 3. 트랙 L — Jev 확률 판정 층

설계·불변식은 로드맵 §12.1~§12.6 에 남는다. 여기는 실측과 배선의 경위다.

### 3.1 L0 · L1 · L2 (2026-09-22~23)

- **L0** — `jev-latest` → **`jev-1.13.0`**(서버가 답한 값). 목록은 `jev-latest`·`jev-preview`. 단발 0.32s · 입력 543 /
  출력 22 토큰. 패키지는 **`typesafe-sdk`**(0.7.1). `typesafe-ai` 는 이름 선점용 리다이렉트 shim 이다. 응답형은 **셋**
  (Noul · Choice · Score). 남은 것은 가격 하나(API 가 주지 않는다)
- **L1** — `neos/jev/scorer.py`. 응답은 진짜 SDK 타입으로 테스트. 해소된 id 는 응답의 `model`(S13)
- **L2** — 코어(밴딩·루브릭 digest·S13 payload·단조 축소 변이 테스트) + durable 루프 배선(`_evaluate_call` 3개 호출부 전부,
  `deps.events.append`). D-L1 순서는 `fold_for_unattended` 재사용. 실 API end-to-end 확인

### 3.2 L1 일관성 기준선 전문 (2026-09-22)

15회 × `tool_risk`(digest `f5faf377…`) × 신선한 uid. 원본 `artifacts/jev-probe/<ts>/report.json`.
요약 표와 세 결론은 로드맵 §12.7 에 남았다. 첫 측정은 극단 대상만 쟀다 — 대상 주석이 "중간대를 겨냥한다"고
**거짓을 적고** 있었고 실측이 반증했다.

초안 루브릭 변별력(3회 × 대상): `read_file README.md` 0.02 · `execute pytest` 0.07 · `write_file` 소스 0.14 ·
`rm -rf node_modules` 0.62 · `write_file .env` 0.73 · `curl -X POST … -d @/etc/passwd` 0.74 · `git push --force` 0.94.
뒤의 셋이 한 덩어리 — 되돌릴 수 없어 위험한 것과 **나가서는 안 될 것이 나가서** 위험한 것이 섞였다 → D-L2.
(`write_file .env` 는 정적 정책이 이미 DENY 하므로 게이트 안에서는 Jev 가 보지 않는다 — 변별력 측정용 값이다.)

### 3.3 배선이 드러낸 것 (2026-09-23, 구 로드맵 §12.8)

1. **판정 이벤트는 코딩 원장에 간다.** 거기엔 DA 같은 짝 규칙이 없어 `jev_risk_scored`·`jev_unavailable` 이 프론트에서
   `return base` 로 조용히 무시됐다(FE1 과 같은 모양) → §3.4 에서 닫힘
2. **투기적 경로 둘이 게이트를 앞지른다.** `_maybe_prefetch_readonly` 는 판정 전에 실행하고, 읽기 전용 배치는 본 판정을
   건너뛴다. `enforce` 일 때는 둘 다 포기한다. 배치에서 막힌 호출이 본 경로로 떨어져 **같은 호출이 두 번 채점**됐다
   (호출 2건에 점수 3건) — 선두 읽기 전용 호출이 **둘 이상**일 때만 켜지므로 단일 호출 테스트는 아무것도 증명하지
   않았다. 이벤트에 `tool_call_id` 가 없어 중복이 보이지 않았다 — 이제 이름으로 드러난다(`['t1', 't1', 't2']`)
3. **payload 는 JSON 이어야 한다.** enum 을 그대로 실었더니 인메모리 저장소는 받고 진짜 원장에서 터졌다. 직렬화 테스트
4. **순서 계약의 구현은 하나여야 한다.** "밴딩 → 접기 → `would_be_outcome` 보정"이 두 번 구현됐고(`evaluate_approval_with_jev`
   와 루프 `_evaluate_call`) 앞의 것은 테스트만 불렀다. `static_evaluator` 인자를 열어 루프가 같은 함수를 쓴다
5. 루브릭 noul 질문 "정확히 하나" 가드 → D-L2 뒤 "루브릭 질문과 `jev.question_thresholds` 키가 정확히 같을 것"
   (`neos/jev/assembly.py`)으로 바뀌었다

### 3.4 코딩 스트림 짝 규칙 (2026-09-23, 구 §12.9)

코딩 원장 kind 는 **36**(투영 30 · 면제 6). 리듀서가 흘려보내던 것: `jev_risk_scored`·`jev_unavailable`(L2) ·
`model.refused`(K6 — 거절한 런이 이유 없이 멈춘 런으로 보였다) · `subagent.*`(K3) · `run.*`(`RUN n` 배지가 남았다) ·
`workspace.user_edit.*` · 🔴 **`thinkingStatus`**(K4a — 리듀서는 채웠는데 읽는 컴포넌트 0개, 리듀서 테스트 7개 초록).

백엔드 구멍: 멈춘 자식의 `subagent.failed` 와 취소된 자식의 `subagent.cancelled` 에 `parent_id` 가 없고 부모 싱크 허용
목록에도 없었다 — 부모는 그 자식이 끝났다는 것을 영영 몰랐다. `_terminal_fields` 한 헬퍼로 네 emit 자리에 같은 필드.

장치: `tests/fixtures/coding_event_kinds.json`(kind 마다 `projected`·`sample`, 면제는 `reason`) ·
`tests/coding/test_event_kinds.py`(AST, `event_type=` 키워드로 싱크를 잡는다, f-string·값으로 꺼내는 kind 도 출처를 따라
푼다) · `web/tests/source/coding-event-kinds.test.ts`(양방향) · 렌더 테스트 `coding-run-signals.test.tsx`. 변이로 확인했다.
스냅샷은 `coding_events` 에서 호출별 최신 판정(`tool_risks`)을 읽고 프론트는 **디코더 하나**로 둘 다 읽는다.
표본 경계 아님.

### 3.5 판정 문장과 재접속 (2026-09-23, 구 §12.10)

- 판정 문장 — 섀도는 반사실, enforced 는 일어난 일과 넘은 경계(`p=0.91 ≥ 0.80`), `jev_unavailable` 은 항상 한 줄
- 거절의 재접속 — 스냅샷이 최신 `model.refused` 를 **가장 최근 런의 것일 때만** 싣는다
- 끝난 자식의 재접속 — 스냅샷이 `subagent.*` 를 자식·타입별 최신 한 줄씩(자식당 최대 다섯), 프론트는 `active_children`
  위에 원장을 접는다 — 종결 이벤트가 체크포인트를 이긴다
- 🔴 **원장의 빈칸:** `would_be_outcome` 은 unattended 접기 **뒤**, `static_outcome` 은 접기 **전**이라 "Jev 가 좁혔다"와
  "접기가 DENY 했다"를 가를 수 없었다. 게이트가 `banded_outcome`·`unattended` 를 함께 싣는다(S13 의 빈칸이기도 했다).
  옛 이벤트는 `would_be_outcome` 으로 읽는다
- 병렬 작업 교훈: 서브에이전트 워크트리가 `main` 에서 만들어졌다 — 맡기기 전에 기준 커밋을 확인한다

### 3.6 D-L2 재료 · WAF · 빈 원장 · Docker 경로 (2026-09-23, 구 §12.11)

**① D-L2 비교**(12 대상 × 3회, 원본 `artifacts/jev-probe/20260923T102554Z-dl2-compare/`)

| 대상 | 단일 `destructive` | `irreversible` | `exfiltration` |
|---|---|---|---|
| `rm -rf node_modules` | 0.63 | **0.75** | 0.02 |
| `write_file .env` | 0.73 | 0.47 | **0.69** |
| `curl -d @~/.ssh/id_rsa` | 0.90 | 0.22 | **0.98** |
| 🔴 `cat ~/.aws/credentials` | **0.10** | 0.03 | **0.61** |
| `git reset --hard HEAD~3` | 0.59 | **0.81** | 0.03 |
| `psql DROP TABLE users` | 0.88 | **0.96** | 0.06 |
| `git push --force origin main` | 0.94 | **0.94** | 0.34 |
| `curl -X POST … -d @/etc/passwd` | ✗ WAF 403 | ✗ | ✗ |

뭉침이 풀린다 · 단일 질문에는 **맹점**이 있다(자격 증명 읽기 0.10) · 잡음은 같은 급(0.000~0.031) · max·noisy-OR 의
Kendall τ(0.78·0.86)는 정답과의 일치가 아니다.

**② WAF** — TypeSafe 앞단 WAF 가 `/etc/passwd` 가 **들어간** 본문을 403 으로 막는다(`…T102517Z-waf-minimal-pairs/`):
`curl … @/etc/passwd` 403 · 대조 `@/etc/hostname` p=0.78 · `read_file /etc/passwd` 403 · 그 경로를 **언급만** 한 메모 쓰기 403.
공격자가 호출 단위로 게이트를 끌 수 있었고, `jev_unavailable.reason` 은 예외 타입명뿐이라 잘못된 키와 구별되지 않았다.
D-L2 첫 초안 루브릭이 `/etc/passwd` 를 예로 적어 그 루브릭의 **모든 호출**이 403 이었다 → D-L3.

**③ Docker 경로가 계약 §3.2 를 지킨다** — 샌드박스마다 `neos-evidence-<id>` 볼륨을 `readonly,volume-nocopy` 로 붙이고
쓰기는 짧은 쓰기 전용 컨테이너(`--network none`·`--cap-drop ALL`)로만, `inspect` 로 `RW == false` 를 되읽는다. `DENY_ALL`
이면 설정과 무관하게 `--network none`, 만족할 수 없는 profile 은 만들기 전에 `profile_unsupported:*`. 실 Docker 29.4.0 에서
확인(설정을 일부러 `bridge` 로). 옛 문장 "설정 결속이 없으면 네트워크가 붙는다"는 쓰일 때부터 틀렸다. 남은 것은 로드맵 §12.11.

**④ L4 코드 착지, 재료 없음** — `scripts/jev_judge_backtest.py` · `neos/jev/claim_judge.py` · `claim_judgement.yaml`(라벨이
`AgenticGrader._MAP` 과 같다), 읽기 전용 트랜잭션. 로컬 원장에 채점된 클레임 0건(09-20 재구축 DB),
`artifacts/deep-analysis-funnel/` 이 디스크 어디에도 없다. 에이전트가 아티팩트 디렉터리 시각을 지어냈다(`000100Z`) —
실제 `measured_at` 으로 고쳤다.

### 3.7 D-L2 · D-L3 닫힘과 L2 섀도 준비 (2026-09-24 · 09-28, 구 §12.12)

- **D-L2 = 쪼갠다**: 기본 루브릭 `tool_risk_split`. 합치는 규칙 없이 질문마다 제 경계(`jev.question_thresholds`, 기본값 없음)로
  밴딩해 가장 엄한 결과. 이벤트는 질문 전부, 최고 밴드 질문이 `driver`(동률은 루브릭 순서). 질문이 빠진 대답은 판정하지
  않는다(`missing_questions:*`)
- **D-L3 = WAF 차단은 좁힌다**: "요청 id 없음 + HTML 본문" 403 을 `JevProviderBlocked` 로 — 두 신호를 **다** 요구(잘못된 키는
  401 + 요청 id). 실 API 로 양쪽 확인. 받아들인 것: 정당한 호출의 거짓 양성. 인코딩 우회는 재지 않아 택하지 않았다.
  `tests/jev/test_rubric_waf_safety.py` 가 **요청에 실리는** 질문 텍스트를 검사한다(첫 판은 트리거를 설명하는 주석을 잡았다)
- **L2 섀도 준비**: `config/samples/jev-l2-shadow.yaml`(섀도만) · `scripts/jev_l2_shadow_report.py`(질문별 분포 · 불일치 목록 ·
  `--try` 재밴딩). 경계 0.2/0.9 는 잠정(무해 군집 ≤ 0.13 · 파국 ≥ 0.94 사이). 실 API: 자격증명 읽기가
  `exfiltration 0.59 → would_be=require_approval`, 결과는 `allow`, 호출당 0.4~0.6 초
- **켜는 길**(09-28, 사람의 결정: 개발에서): `make dev-jev-shadow` 가 개발 서버 **프로세스 하나에만** 오버레이를 건다.
  `development.yaml` 은 CI 가 키를 요구하고, `config/neos.local.yaml` 은 `.env` 의 `NEOS_CONFIG_PATH` 를 타고 테스트에도 걸려
  둘 다 아니다. 판독은 `make jev-shadow-report SINCE=<켠 날>`

---

### 3.8 L6 — 인용 클레임 판정자를 Jev 로 (2026-10-03, DECISIONS D99)

사람의 결정으로 L4·L5·#23 판정을 앞질렀다. 결정·받아들인 위험·#23 개정은 D99 가 정본이다. 여기는 무엇이 섰는가만 적는다.

- `AgenticGrader` 에 Jev 경로(`_grade_with_jev`). 티어링은 하나 그대로, 판정자만 바뀐다. 계산 클레임은 LLM 판정자에 남는다
- 단조 축소를 판정에도: 애매함(`confidence < jev.judge_min_confidence`)·WAF 차단 = 반려, 실패·타임아웃 = LLM 폴백 + `judge_backend=llm_fallback`
- 켜는 자리는 `neos/jev/assembly.py` `build_claim_judge` 하나(키 없음·모델 미핀은 기동 실패). 재생 카세트 런만 부르지 않는다
- S13: 판정마다 모델·루브릭 digest·경계·확률·uid. 매니페스트 `config.claim_judge`
- preflight 가 Jev 판정자를 실호출로 찌른다. 수동 프로브(2026-10-03): `SUPPORTS` · 0.93 · `jev-1.13.0`
- 테스트 `tests/workflow/deep_analysis/test_jev_claim_judge_l6.py` 14건 + preflight 2건. **변이 둘로 무는 것을 확인했다** — 애매함 반려를 끄면 2건, WAF 차단을 폴백으로 열면 1건이 빨개진다
- 같은 날 개발 오버레이 `config/samples/dev-jev-enforce.yaml`(`make dev-jev-enforce`)이 L3 게이트·Q5b 멈춤·L6 를 **잠정 경계**로 켠다

## 4. CHILD-GATE — 자식의 도구 호출을 게이트 안으로 (2026-09-28)

**코딩 절반.** `CodingToolPort.execute` 가 executor 앞에서 부모가 바인드한 `authorize` 를 부른다 — `_authorize_child_call`
(`neos/coding/loop/_durable/spawn.py`)이 부모의 `_pre_tool_decision`·`_evaluate_call` 을 **그대로**(사본 없음). 자식은
`can_approve=False` 라 `unattended=True` 로 판정하고 ALLOW 가 아닌 것은 전부 거절(사람의 결정: REQUIRE_APPROVAL → DENY).
거절은 부모 원장 `tool.denied`(`subagent_spec`·`parent_tool_call_id`). 바인드 없는 포트는 `policy_gate_unbound`. 재개 두 경로
(`await_subagent.v1`·K3 safe point)도 다시 바인드한다.

**공유 포트 경쟁**(옛 CHILD-PORT-SHARED): development supervisor 는 태스크 여럿을 동시에 돌리는데 포트는 런타임에 하나라,
`authorize` await 사이에 다른 spawn 이 재바인드하면 자식이 **남의 세션·게이트**로 돌 수 있었다. 바인딩을 코딩 태스크
(`ticket.parent_id`)로 키잡고 stepper 는 `for_ticket` 뷰로만 닿는다. 수명은 부모 스텝 하나(`finally` 셋). Celery 경로는
태스크마다 런타임을 새로 만들어 이 경쟁이 없었다. 테스트 아홉, 변이 여덟.

**남은 셋도 같은 날 닫혔다**
- ① DA 조사 자식 → J1.5 의 `ResearchGate`(§1.2)
- ② 자식 `tool.denied` 에 `tool_call_id` 가 없어 프로젝션이 **버렸다**(화면에 한 번도 안 떴다). 부모 게이트가
  `<spawn call>:child:<nonce>` 를 짓고, 프로젝션 저장소가 `subagent_spec` 붙은 `tool.denied` 를 도구 행으로 읽는다(새로고침에도
  남는다). 테스트 여섯, 변이 다섯
- ③ 재개 경로 재바인드 **호출부** 테스트 — 첫 초안은 변이를 놓쳤다(읽기 하나는 await 턴 앞 safe point 에서 이미 돌았다).
  읽기 둘로 고쳤다

⚠️ 읽는 법: 기본 manual 모드에서 implement 자식은 쓰기·실행을 못 한다 — `approval_mode: auto` + `approval_always_allow` 가 필요하다.

---

## 5. 트랙 A·운영 — 정리된 선행과 환경

| 날짜 | 무엇 |
|---|---|
| 2026-09-23 | `ANTHROPIC_WORKSPACE_ID` **필요 없음** — 헤더 없이 DA 역할 모델 넷(haiku-4.5·sonnet-5·opus-5·opus-4-8)을 실제로 불러 답을 받았다. 헤더 배선은 남긴다(값이 비면 보내지 않는다) |
| 2026-09-24 | D93 사전 등록 → **D98** 로 다시 씀. D-14 분리: #23 은 BUDGET2(`deep_analysis.budget_aware_reduction`)를 끄고 CITE1 을 가르고 #24 가 BUDGET2 를 잰다. 재현 게이트는 독립 집계(파서 대 SQL) |
| 2026-09-24 | **테스트가 개발 DB 에 쓰고 있었다**(`neos` 에 스위트당 런 ~6건). `tests/conftest.py` 가 설정 로드 전에 DB 이름을 `<이름>_test` 로 강제, CI 도 `neos_test`. 전후로 `neos` 490건 불변 |
| 2026-09-24 | `test_config_loader.py` 10건이 한 파일만 돌리면 깨졌다 — 전체 스위트에선 litellm `load_dotenv()` 가 키를 넣어 줬다. 픽스처가 자리표시자를 준다 |
| 2026-09-24 | 고아 PG17 볼륨 다섯을 **복사본**에서 네트워크 없는 임시 Postgres 로 열었다 → **#21·#22 원장은 없다.** 넷은 `make db-verify` 스크래치(`neos_verify`), 하나는 재구축 당일 10분만 산 클러스터 |
| 2026-09-28 | `TAVILY_API_KEY` 가 `.env` 에 채워졌다. #23 의 코드·키 선행이 비었다 |
| 2026-09-28 | 코드 대조(`403aeb77`) — 근거는 [NEOS_MOMENTUM_ANALYSIS_20260928.md](NEOS_MOMENTUM_ANALYSIS_20260928.md) §9.2 |

---

## 6. 트랙 C — 프론트엔드

- FE1~FE17 종결(상세는 압축본 `31b37111`)
- 2026-09-23 코딩 스트림 짝 규칙(§3.4)
- 2026-09-27 챗 SSE 짝 규칙 `tests/fixtures/chat_stream_event_types.json` — 처음 드러낸 구멍: `response.reasoning.*` 가 훅에서
  버려지고 있었다 · DA 재개 버튼(별도 라우트 `deep-analysis/[runId]/resume`) · 그래프 서브에이전트 표시

---

## 7. 트랙 Q — 상시 에이전트 착지 원장

항목 정의·결정·순서는 [dots 분석 §4·§6](OPENAI_DOTS_ANALYSIS_260930.md). 설계 결정 ID(D·S·M·N·W·X·B·C·MS·MB·MP·P·SQ)는 각 설계
문서의 것이다. **전부 플래그 off** 로 착지했다. 결정 표기 "위임받아 Claude 가 골랐다" 는 설계 문서에 그대로 적혀 있다.

### 7.1 착지 표

| ID | 날짜 | 플래그 · 마이그레이션 | 핵심 | 테스트 · 변이 | 설계 |
|---|---|---|---|---|---|
| **Q1** background 모드 | 09-30 | 모드를 보내는 호출자 없음 · 069 | `CodingTaskMode.BACKGROUND`. 천장은 **검증된 위험**만 본다(`exceeds_mode_ceiling`), 사유 `policy_mode_ceiling`. 자식 생성을 따로 막을 필요 없었다 — 검증기가 `spawn_agent.v1 spec=implement` 를 WORKSPACE_WRITE 로 올리고 explore 는 포트가 쓰기를 막는다. 천장이 실제로 무는 자리는 운영자 allow 가 ALLOW 를 낼 때. background 전용 프롬프트 오버레이 없음 | Q1·Q2 30 · 8/8 | — |
| **Q2** USER_ONLY | 09-30 | — | `USER_ONLY_COMMANDS`(argv 접두 10개) · `approval_user_only_extra`(합집합) · 사유 `policy_user_only`, 부모·자식이 `policy_denial_reason` 하나. 📌 **넷째 enum 값이 아니다** — `_approval_gate_step` 은 DENY·REQUIRE 가 아닌 결과를 실행하므로 새 값은 열린 채 실패한다. 오늘은 검증기가 대부분 막고, 바닥은 allowlist 가 넓어지는 날의 심층 방어 | (Q1 과 함께) | — |
| **Q5** 감시자 섀도 | 09-30 | `jev.monitor` · `make` 타깃 없음 | `neos/coding/monitor/`(rules·monitor) · 루브릭 `trajectory_scope` · 멈춤 경계 기본값 없음. 모델 턴 safe point 에서 N 도구 결과마다 원장을 읽고 `monitor.judged` 하나(`projected: false`), 박자는 마지막 판정의 `tool_results`. 📌 FB6 을 위해 `model.completed` 가 **턴별 토큰**을 싣는다. Jev 실패는 `jev_unavailable` kind 가 아니라 `monitor.judged` 필드로(그 kind 는 도구 카드에 투영된다). ⚠️ FB5 는 루프 안에선 발동하지 않는다(`model.refused` 가 런을 끝낸다) | 40 · 11/11 | [dots §6.1](OPENAI_DOTS_ANALYSIS_260930.md) |
| **Q13a** 에이전트 개체 | 09-30 | 070 | `standing_agents` · 사용자당 하나 = 부분 unique 인덱스 · 이름 길이 무제한·소유자 안 중복 금지(해시 인덱스) · 명시적 생성 · paused 는 진행 중 태스크를 건드리지 않는다 | — | [Q13](Q13_STANDING_AGENT_DESIGN_260930.md) |
| **Q13b** API | 09-30 | `standing_agents.enabled` | API · 플래그 | — | Q13 |
| **Q13c** 태스크 연결 | 09-30 | — | `coding_tasks.agent_id` · `open_agent_task`(기본 background · interactive 거절 · 멈춘 에이전트는 못 연다) · `task.created` 의 `actor` | 20 · 11/11 | Q13 |
| **Q13d** 활동 피드 | 09-30 | 072 | `GET /standing-agents/{id}/activity` — 커서는 `xact_id` + `pg_snapshot_xmin` 가드로 늦은 커밋도 건너뛰지 않는다 | 25 · 14/14 | Q13 |
| **Q13e** 메모 | 09-30 | — | `agent:{id}` 네임스페이스, `write_approval` 과 무관하게 **STAGED 로만** · GEPA 는 `agent:` 런을 거절(F18) | 17 · 11/11 | Q13 |
| **Q13f** 자기소개 | 10-01 | 073 | 만들 때 background 태스크 하나, 성공한 최종 답이 STAGED 메모. 태스크는 메모를 쓰지 않고 `CodingRunService` 완료 훅이 옮긴다 | 30 · 22/22 | Q13 |
| **Q4a** webhook 트리거 | 10-01 | 074 | webhook 원천만(D2) · `standing_agent_triggers`(키 `agent_id`, `ON DELETE CASCADE`) · 서명 비밀은 `HMAC(NEOS_TRIGGER_SIGNING_KEY, trigger_id)` 파생(DB 에 없음) · 배달 id 도 서명 안, `.` 금지 · 멱등성은 `channel_inbound_idempotency` 를 `trigger:{id}` 로 · 인증 실패는 한 모양 401 · 태스크는 언제나 background, 본문 untrusted | — | [Q4·Q10](Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md) |
| **Q10a** 예산 봉투 | 10-01 | — | 에이전트 × UTC 월 · **지출은 세지 않고 읽는다**(그 달 에이전트 태스크들의 최신 체크포인트 누적 `cost_micros` 합 — `standing_agent_budgets` 테이블은 만들지 않았다) · 새 태스크는 `open_agent_task` 가 막고 진행 중은 섀도 `budget.judged`(런당 하나). 트랙 P 계량을 기다리지 않았다 | — | Q4·Q10 |
| **Q2** 사용자 규칙 | 10-01 | 075 | `user_approval_rules`(사용자 키) · 도구 + argv 접두(D8) · 사용자 allow 는 위험 등급 기본 REQUIRE 만 바꾼다(D9) · 매 단계 새로 읽고 체크포인트에 싣지 않는다(D10) · 읽기 실패는 재시도 실패(D11) · 사유 `policy_user_rule_blocked` | — | [Q2·Q4b](Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md) |
| **Q4b** 채널 트리거 | 10-01 | 076 | slack·discord·telegram 어댑터가 대화 게이트 **직전에** 부작용으로(D5, 대화 동작 불변) · 발신자는 소유자 매핑 + `allowed_senders`(D4), 봇 제외 · 운영자 채널 정책도 적용 · CHECK 의 `NULL IN` 함정을 실 DB 가 잡았다 | — | Q2·Q4b |
| **Q6a** 자격증명 브로커 | 10-01 | `coding_model.secret_broker` · 077 | `execute.v1` env 값 `secret://<name>` 을 실행기가 실행 직전에 풀고 결과를 **값 자체**로 가린다(잘린 꼬리 접두도, S6) · 비밀마다 env 이름 하나(S3) · 사람 승인 또는 소유자 allow 만(S7) · 자식 불가(S8) · AES-GCM, `NEOS_SECRET_BROKER_KEY` 파생(S5) · memory·Docker 만, sandboxd·managed 는 `secret_env_unsupported` | 44 · 3/3 | [Q6](Q6_CREDENTIAL_BROKER_DESIGN_261001.md) |
| **Q11a** MCP 클라이언트 | 10-01 | off | 옛 `*mcp*` 넷은 이름만 MCP — 머리말로 신고, 진짜는 `neos/coding/connectors/`(M1) · SDK 없이 최소 JSON-RPC(stdio·streamable HTTP — `mcp` SDK 는 sse-starlette 를 끌어와 phoenix 핀과 부딪친다, M3) · **위험을 선언해야 등록**(미선언은 없음, `readOnlyHint` 무시, M4) · `mcp__<server>__<tool>`(M5) · 서버 자격증명은 Q6 비밀, `carries_secret_refs` 한 판정(M7) · 📌 비밀 푸는 호출은 배치·프리페치로 앞지르지 않는다(M13 — 잠복 구멍) · 결과는 가린 뒤 자르고 untrusted(M9) · 자식 거절(M11) | 65 · 16/16 | [Q11](Q11_MCP_CLIENT_DESIGN_261001.md) |
| **Q14a** 브라우저 | 10-01 | off · development 전용 | 백엔드 호스트 headless Chromium(W1, B2 미충족 — 렌더러 탈출은 호스트에 닿는다) · Chromium 은 네트워크가 없고 모든 요청을 호스트가 web_fetch 판정 + IP 고정 한 홉으로 대신 받는다(W2) · development 밖은 운영자 명시 동의(W3) · 도구 둘 COMMAND(`browser.v1`·`browser_fill_secret.v1`, W4) · 로그인은 Q6 판정 하나를 넓혀서만, 입력한 비밀은 다른 출처로 못 나간다(W7·W8) · 자식·DA 조사 경로에 없다(W12, D6) | 68 · 12/12 | [Q14](Q14_AGENT_BROWSER_DESIGN_261001.md) |
| **Q16a** 기기 브리지 | 10-01 | off · 080 | 페어링 토큰은 한 번만 보이고 해시만(키 `user_id`, B1) · **READ_ONLY 만**, 등급 없는 선언은 전체 거절(B3) · 소켓은 API 워커·루프는 Celery 라 **Redis 중계**(B6) · 무인 런은 `allow_unattended`(기본 false), 노출·게이트·소켓이 한 함수(B7) · `secret://` 는 정규화 전 거절(B8) · 자식 거절(B11) · 📌 `test_retired_routes._routes()` 가 포함된 라우터의 소켓 경로를 빈 문자열로 읽어 공허했다 — 고쳤다 | 115 · 27/27 | [Q16](Q16_DEVICE_BRIDGE_DESIGN_261001.md) · [위협 모델](Q16_DEVICE_BRIDGE_THREAT_MODEL.md) |
| **Q6b** sandboxd 비밀 채널 | 10-02 | Q6 플래그 | sandboxd `exec` 에 `env` 와 다른 `secret_env`(비밀 없는 프레임은 바이트 동일, C2) · guest 가 `exec.secret_env.v1` 광고, 호스트가 lease 마다 확인, 모르는 guest 에는 보내기 **전에** 거절(옛 guest 는 필드를 조용히 버린다, C3) · 관리형 E2B·Modal 은 계속 거절(C1). 📌 운영에서 새로 비밀을 싣는 provider 는 없다(로컬 sandboxd 는 시험용) · guest 번들 digest 변경 | 12 · 10/10 | [Q6b](Q6B_SANDBOX_SECRET_CHANNEL_DESIGN_261002.md) |
| **Q11b** 고정 매니페스트 | 10-02 | off | 소유자 토큰이 있어야 `tools/list` 에 답하는 서버는 운영자 `pinned_tools` — 소유자별 발견은 안 한다(N1) · 시작 때 연결하지 않는다(N2) · 호출마다 같은 승인된 연결로 맞춰 보고 `connector_tool_missing`/`connector_schema_drift`(N4·N5) | 28 · 9/9 | Q11 §5 |
| **Q14b** 출처 묶임 | 10-02 | 081 | `user_secrets.browser_origins`(기본 빈 배열 = 어디에도 입력 안 됨 — ⚠️ 이전 비밀은 출처를 붙여 다시 PUT) · 출처는 AAD 에 봉인(X3) · 실패·취소 세션 즉시 정리(X5) · 비밀번호 가리기 모든 프레임(X6) · 여러 `Set-Cookie` 를 실제 Chromium 으로 확인(X4) | 28 + 실 Chromium 2 · 12/12 | Q14 §7 |
| **Q16b** 기기 쓰기 | 10-02 | 083 | 위협 모델 §3 줄·§4 표가 **먼저**(지속적 개선의 첫 증분) · `device_write_file.v1`(파일 전체) · 두 열쇠(자격증명 `allow_writes` + 클라이언트 `--allow-writes`, 어긋나면 등록 거절) · 쓰기마다 사람 승인(소유자 allow 만 대신) · 무인 쓰기는 어떤 허락으로도 거절 · `base_sha256` read-before-write · fd 걷기·dot·자동 실행 확장자 거절 · 임시 파일 + rename/link · 실 Redis 중계 7/7(`NEOS_TEST_REDIS_URL`) | 22/22 | Q16 §6 |
| **Q10b** 예산 멈춤 | 10-02 | `standing_agents.budget.enforce` · 085 | **`PAUSED` 의 첫 작성자.** 모델 턴 맨 앞(자식 한 걸음·모델 호출 **전**)에서 한 트랜잭션(`budget.judged enforced` + `running → paused` + `task.status.changed`) · **런은 `running` 으로 남는다**(재개는 같은 런 최신 체크포인트, P1) · 리스 획득은 `TaskPaused` 로 막고 러너는 `PAUSED`(P4) · 재개는 사람만 `POST /coding/tasks/{id}/resume`(P6) · 판정을 못 읽으면 멈추지 않는다(P5) · FE 배지·Resume · 알림(80% 경고·멈춤)은 워커가 큐에 적고 API 프로세스가 보낸다. 처음 살아남은 변이: 대상 없는 에이전트의 알림이 **남의 채널**로 갈 수 있었다 | 20/20 | [Q10b·Q3](Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md) |
| **Q3** 상시 질문 | 10-02 | `standing_agents.questions` · 086 | `scheduled_tasks` 가 아니라 `agent_id` 키 테이블(SQ1) · DA 런은 기존 제출 계약(SQ2) · beat 폴러가 정산 → 제출, 질문마다 진행 중 하나(SQ3) · 1차 키 `claim_hash`, 보조 키 증거 blob(결정 8) · **새로 검증·반증일 때만** 알리고 재표현 후보는 수만(SQ6) · 첫 정산은 침묵하는 기준선, 실패 런은 기준선 아님(SQ7) · 제출은 에이전트 active + 봉투 background 판정 · 📌 DA 지출은 봉투에 안 들어간다, 주기 하한(360분)·개수 상한이 비용 상한(SQ8·SQ9) · 📌 blob 해시는 내용 해시라 갱신되는 출처의 재표현은 보조 키로 짝나지 않는다 | 24/24 | Q10b·Q3 §5 |
| **Q5b** 감시자 멈춤 | 10-02 | `jev.monitor.enforce` | 같은 `pause_task`(사유 `monitor_jev`/`monitor_fallback_fbN`, MP1) · **경계 아홉을 config 에 명시해야 켜진다**(`model_fields_set`, MP2) · 한 턴에 봉투가 먼저, 멈춤 트랜잭션 하나(MP4) · 판독을 커서로(`LedgerTail`, MP6) · 재개 라우트는 감시자 집행만으로도 마운트(MP7) · 📌 `jev.monitor.max_events` 가 판독에 닿지 않던 결함과 테스트 대역의 seq 결함을 고쳤다 | 21/21 | [Q5b](Q5B_MONITOR_PAUSE_DESIGN_261002.md) |
| **Q14c** 관리형 브라우저 | 10-02 | `browser.provider: managed` — **켤 수 없음** | 샌드박스 안 게스트가 Chromium 을 돌리고 모든 요청을 호스트 판정으로 되돌린다(MB1) · 폴백 없음(MB2) · 관리형의 `browser_fill_secret.v1` 은 `browser_secret_channel_unavailable`(MB4) · ⚠️ 통로는 B2 배선 몫이라 팩토리가 `managed` 를 거절, 실계정 체크리스트 a~h | 17/17 | Q14 §8 |
| **Q6c** 관리형 비밀 채널 | 10-02 | `sandbox.managed.secret_env_providers` — **열린 공급자 없음** | 비밀은 기존 sandboxd `secret_env` 로 벤더 stdio 중계를 탄다(벤더 per-exec env·비밀 객체 기각, MS1) · **바인딩 코드가 증거 객체를 선언**(MS2) + **운영자가 공급자별로 켬**(MS3) · 📌 E2B·Modal SDK 가 저장소에 없어 둘 다 거절, 실계정 스모크 R1~R11 | 17/17 | [Q6c](Q6C_MANAGED_SECRET_CHANNEL_DESIGN_261002.md) |
| **Q16c** 기기 명령 | 10-02 | 090 | 위협 모델 줄·12위협 표가 **먼저** · `device_run_command.v1`(argv 만) · 열쇠 셋(`allow_commands` · `--allow-commands` · 운영자 `command_allowlist`, 기본 빈) · 매 호출 사람 승인(argv 접두가 맞는 소유자 규칙만 대신) · 무인 거절 · `shell=False`·환경 세척·프로세스 그룹 kill · ⚠️ 기기 OS 샌드박스 없음(BC12, 받아들인 위험) | 28/28 | Q16 §7 · 위협 모델 §5 |

### 7.2 통합 기록

- 10-01 통합(Q6 → Q14 → Q11 → Q16 순 cherry-pick): 전체 스위트 실패는 `test_fingerprint_reports_ledger_manifests_without_credential_shaped_keys`
  하나, 기준선 테스트 이름 누락 0
- 10-02 통합(Q6b → Q11b → Q14b → Q16b): 전체 스위트 7,584 통과, 실패는 같은 테스트 하나, 기준선 이름 누락은 Q16b 의 의도된
  이름 변경 하나
- 마이그레이션 **078·079·082·084 는 비어 있다**(예약했으나 쓰이지 않음)
- 📌 그 "flaky" 는 flaky 가 아니었다 — 지문에 git 브랜치 이름·dirty 경로가 실려 이름에 `secret`·`credential` 이 있으면
  결정적으로 깨졌다(`c042b8b3` 에서 고침)
- 📌 채널 게이트웨이는 API 프로세스에만 있다 — **기존 스케줄 태스크의 워커 채널 전송은 경고 한 줄로 죽어 있었다**(Q10b 가 발견,
  범위 밖이라 기록만. 남은 것은 로드맵 §11)
