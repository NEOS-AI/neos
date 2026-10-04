# 심층분석 하네스 통합 로드맵 — 코딩 루프로 조사하는 검증형 분석

> **이 문서가 로드맵의 정본이다.** 앞으로의 계획·변경·판정은 여기에 적는다.
> **착지한 작업의 경위는 [DEEP_ANALYSIS_HARNESS_DONE.md](DEEP_ANALYSIS_HARNESS_DONE.md)에 있다** — 여기는 남은 것과
> 지켜야 할 것만 든다.
>
> **수치와 판정의 원본은 여전히 이 문서가 아니다:** 수치는 `deep_analysis_events` 테이블과
> `artifacts/deep-analysis-funnel/<ts>/`, 판정은 `neos/workflow/deep_analysis/DECISIONS.md`
> (D1~D98)다. **충돌하면 원본이 이긴다.**

> 🔴 **2026-09-15 전면 개편.** 방향이 바뀌었다 — 워커는 "JSON 한 번 내는 응답자"에서
> **샌드박스에서 코드를 짜고 돌리는 에이전트 루프**로 간다(§2). 그리고 프롬프트·런타임 전략을
> Fable 5.1 기준으로 다시 세웠다(§5·§6).
>
> 지난 판본은 git 에 있다. 절 번호는 판본마다 다르다:
>
> ```bash
> git show c071585a:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md > /tmp/roadmap_full.md   # 3,199줄 전임본
> git show 31b37111:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md > /tmp/roadmap_0911.md   # 2026-09-11 압축본
> git show 0fbfdbe4:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md > /tmp/roadmap_1002.md   # 2026-10-03 압축 직전(1,358줄, 취소선 이력 전부)
> ```
>
> 개편과 압축에서 **버린 결론은 없다.** 2026-10-03 압축은 착지 경위를 DONE 문서로 옮겼을 뿐이다 —
> 절 번호(§1~§15, §12.1~§12.12)는 코드 주석이 가리키므로 **바꾸지 않았다.**

### 이 문서를 갱신하는 규칙

- **종결한 항목은 §11 인벤토리에서 지운다.** ✅로 남기지 않는다 — 유령 백로그가 남은 일을 과대평가하게 만든다
- **착지한 항목의 경위는 DONE 문서에 적는다.** 여기에는 "✅ 착지(날짜) — DONE §n" 한 줄만 남긴다. 착지가 만든
  **지켜야 할 규칙**(되돌리지 말 것·받아들인 위험)은 여기에 남긴다
- **새 표본 경계가 생기면 §8에 먼저 적는다.** 사전 등록보다 먼저다
- **반증된 서술은 지우지 말고 취소선으로 남긴다** — 근거 없이 사라진 결론은 되살아난다. 착지로 해소된 취소선은
  DONE 문서로 옮겨도 된다
- **절대 수치는 적지 않는다.** 적어야 하면 측정 날짜를 함께 적는다
- **§4·§5·§12의 설계와 코드가 어긋나면 코드가 이긴다**

**기준 시점: 2026-10-03** (압축 + 같은 날 사람의 결정 묶음 — §11 결정 색인 2026-10-03 행. 압축. 내용 기준은 트랙 Q 2026-10-02 · L 2026-09-24 · J·K 2026-09-28 코드 대조(`403aeb77`) ·
그 앞은 2026-09-15). 트랙 Q 의 정본은 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md)

---

## 1. 한눈에 — 트랙 열세 개

| 트랙 | 상태 | 남은 것 |
|---|---|---|
| **A. 심층분석 하네스** | 🟢 출하 기준 6/6 · ✅ **#23·#24 돌았다(2026-10-03)** — BUDGET2 는 P-1~P-3 셋 다 맞았고(D104), **CITE1 의 원인 = 자기 클레임 침묵 폐기**(`children_join` 이 노드 자신의 verified 를 빼먹는다, D103 수정 규칙 · D104) | 처방 사전 등록 — 좁은 수정(`children_join` 에 자기 클레임) 과 J4 중 하나씩 · verified 119→82 감시(D104 §5) |
| **B. 역할 기반 모델 라우팅** | ✅ 안정 | 유지보수. effort 축이 붙었다(K5) |
| **C. 프론트엔드** | ✅ FE1~FE17 · 이벤트 짝 fixture 셋(DA · 코딩 · 챗 SSE, [DONE §6](DEEP_ANALYSIS_HARNESS_DONE.md)) | 새 kind 는 세 fixture 중 하나를 거친다(§13 C) |
| **D. 프레임워크 이탈** | 🟢 D1·D3a 완료 | D2 · D4(전송만 SDK로) · D3b. **J가 D4의 수요처가 된다** |
| **E. 코딩 에이전트** | 🟢 플랜 14개 완료 · development 프로파일 실제 루프 on · ✅ **E-S2 결정(2026-10-03): development 에서 켠다**, staging·production 은 B2 게이트 뒤(설정 검증이 Docker·managed 를 요구한다) | 잔여는 [PLAN_260913.md](PLAN_260913.md) A~H. managed provider **B2 게이트 미충족** |
| **F. 개선 루프 서브에이전트화** | 🔴 닫힘 | 재개하려면 새 스펙 + 새 사전 등록 |
| **G. 그래프 계약·검증** | 🟢 C3·C4 live · ✅ **development 에서 켰다**(2026-10-03, `workflow.graph_design_enabled`) | M-0 재측정(사전 등록 완료) · staging·production 기본값은 그대로 off |
| **H. 플러그인 런타임** | 🟢 H1 완료 · H3 코드 완료 · ✅ **H3 development 에서 켰다**(2026-10-03, G 와 같은 플래그) | H2 · H4 · H5 |
| **I. 서브에이전트 노드 그래프** | 🟢 GS0~GS5 완료, 플래그 off | M-0 표본 → M-1 사전 등록 → GS6 |
| **J. 코딩 루프 조사** | 🟢 **J0·J1·J1.5·J2·J3 착지**, 전부 플래그 off — 조사 자식이 게이트된 코딩 도구로 스크립트를 돌리고 그 계산이 진짜 원장 위에서 verified 가 된다([DONE §1](DEEP_ANALYSIS_HARNESS_DONE.md)) | **J4**(#23 판정 뒤) → J5 → J6. ⚠️ 계약 §3.2 downgrade 는 managed·memory provider 에 남았다(§12.11) |
| **K. Fable 5.1 적응** | 🟢 **표본 없이 되는 K 는 다 썼다** — K0·K1·K1b·K1c·K1d·K2·K2b·K3(기본 off)·K4a·K4b·K5①~④·K6·K7·P-05(기본 off)·K9 모드·오버레이([DONE §2](DEEP_ANALYSIS_HARNESS_DONE.md)) | K5⑤ 벤치 · P-02 interactive 투입 · K10 · K11 · K8. **K3 를 켜는 것은 A1·A2 숫자 뒤** |
| **L. Jev 확률 판정 층** | 🟢 **L0·L1·L2 완료 · L4 코드 착지 · D-L1·D-L2·D-L3 닫힘**, 핀 `jev-1.13.0`([DONE §3](DEEP_ANALYSIS_HARNESS_DONE.md)) · ✅ **L6 착지(2026-10-03, D99)** — 인용 클레임 판정자 = Jev, #23 부터 · **L3 게이트**는 개발 오버레이(`make dev-jev-enforce`)에서 잠정 경계로 켠다 | 가격 하나 · L4 사후 백테스트(#23 원장) · L5(건너뛰었다 — D99 §3) · L7. ⚠️ `DeterministicGrader` 는 교체 대상이 **아니다** · 경계값은 전부 **잠정**이다 |
| **Q. 상시 에이전트** (2026-09-30) | ✅ **development 에서 켰다**(2026-10-03 — 상시 에이전트·트리거·예산 봉투+멈춤·알림·상시 질문·비밀 브로커·기기 브리지는 `neos.development.yaml`, Jev 감시자 Q5b 멈춤·브라우저 Q14a 는 `make dev-jev-enforce`). 🟢 **Q0 결정 · 가드 전부와 능력 대부분 착지**(2026-09-30~10-02): Q1 · Q2(+사용자 규칙) · Q3 · Q4a·b · Q5(섀도)·Q5b · Q6a·b·c · Q10a·b · Q11a·b · Q13a~f · Q14a·b·c · Q16a·b·c([DONE §7](DEEP_ANALYSIS_HARNESS_DONE.md)). `PAUSED` 의 작성자가 생겼다(Q10b·Q5b) | 착지했지만 **켤 수 없는 것:** 감시자 경계 실측(Q5b) · B2 배선 + 관리형 브라우저 통로(Q14c) · 벤더 SDK 바인딩·증거·실계정 스모크(Q6c). **아직 없는 항목:** Q7 · Q8 · Q9 · Q12 · Q15 · Q17(트랙 P 테넌트 격리 뒤) · Q18. **별건:** 스케줄 태스크의 워커 채널 전송 구멍 · Q11 장기 프로세스 op · Q14 규칙을 출처까지 · 실 Redis 시험의 CI 화. 순서는 [dots 분석 §4](OPENAI_DOTS_ANALYSIS_260930.md) |

**기본 플래그** — 두 제품 표면이 아직 프로덕션 기본 경로에 없다. 줄 번호는 적지 않는다.

```
DeepAnalysisConfig.enabled            = False
DeepAnalysisConfig.subagent_enabled   = False
SandboxConfig.enabled                 = False   (development: true, provider memory)
CodingModelConfig.enabled             = False   (development: true)
WorkflowConfig.graph_design_enabled   = False
WorkflowConfig.subagent_nodes_enabled = False
# J:  deep_analysis.code_research_enabled = False
# L:  jev.enabled                    = False
#     jev.tool_risk_shadow_enabled   = False
#     jev.tool_risk_gate_enabled     = False
#     jev.judge_shadow_enabled       = False   ⚠️ 읽는 코드가 없다 (2026-09-28)
# Q:  standing_agents.enabled · jev.monitor(.enforce) · standing_agents.budget.enforce ·
#     standing_agents.questions · coding_model.secret_broker · 커넥터·브라우저·기기 브리지 — 전부 off
#     (정확한 키는 각 설계 문서와 CONFIGURATION.md)
# L6: jev.judge_enabled              = False   (sample-23.yaml: true, D99)
```

**development 프로파일 (2026-10-03)** — 스키마 기본값은 위 그대로다. `config/neos.development.yaml` 이 켜는 것:
`graph_design_enabled`(G·H3) · `standing_agents.{enabled, triggers, budget.enforce, notifications, questions}`(Q) ·
`coding_model.secret_broker`(Q6) · `coding_model.device_bridge`(Q16). `config/samples/dev-jev-enforce.yaml`
(`make dev-jev-enforce`)이 더하는 것: Jev L3 게이트 · Q5b 감시자 멈춤 · L6 판정자 · Q14a 브라우저 — **경계는 전부 잠정값**.
Jev 를 development.yaml 에 넣지 않는 이유: 테스트·CI 가 그 프로파일을 읽는다(실호출 과금 · 401 폴백 오염).
**켤 수 없어 켜지 않은 것:** Q14c·Q6c(B2 배선·벤더 증거 전에는 팩토리가 거절) · Q11 MCP(연결할 서버가 정해지지 않았다 — 서버 없이 켠 플래그는 아무것도 하지 않는다)

---

## 2. 방향 전환 — 무엇이 바뀌고 무엇이 그대로인가

### 2.1 바뀐 것

이 로드맵을 처음 쓸 때 심층분석 워커는 **요청 한 번에 JSON 하나를 내는 무상태 함수**였다
(`prompts/worker_brief.md` v5: "JSON 외 출력 금지"). 그 사이 코딩 에이전트 트랙(E)이 Claude Code와
Hermes Agent를 분석해 다음을 **코드로** 만들었다.

- durable 1-step 루프 — 모델 턴 XOR 도구 배치, lease·체크포인트·재개
- 샌드박스 포트 — memory/Docker, managed 할당 평면(B2 진행 중), `network=none`
- 서브에이전트 런타임 — explore/implement, park/fold, depth-1 nested, cancel cascade
- 스킬 카탈로그와 점진 공개 — `load_skill.v1`, `search_tools.v1`
- 승인된 교훈만 주입하는 학습 경로

그리고 심층분석은 **이미 그 하네스 위를 지나간다** — `harness_bridge.py`가 DA의 실제 LLM 호출을
`create_coding_model` + `collect_model_turn`으로 보내고(§8 경계 7), `subagent_adapter.py`가 DA를
`SubagentRuntime`의 호스트로 붙였다(플래그 off).

**그래서 질문이 바뀌었다.** "워커 프롬프트를 어떻게 고치나"가 아니라
**"조사와 리포트 작성을 코딩 에이전트가 코드를 짜서 푸는 일로 만들면, 검증 규율을 어떻게 지키나"** 다.

### 2.2 그대로인 것 — 이것이 전환을 가능하게 한다

`DIRECTION_260717.md` §2.1이 적은 비대칭은 그대로다.

> **discovery는 자유롭게 넓히고, retrieval과 검증은 좁게 통제한다.**

`DeterministicGrader`는 **출처 무관**이다 — 어떤 도구가 URL을 찾았는지 보지 않고, 발췌가
fetch된 원문에 문자 그대로 있는지만 본다. 따라서 워커를 코딩 에이전트로 바꿔도 **채점 계약은
바뀌지 않는다.** 바뀌는 것은 워커가 할 수 있는 일의 폭이다.

| 층 | 전환 전 | 전환 후 | 규율 |
|---|---|---|---|
| discovery | 검색 + 스킬 tool-calling | **+ 코드** (파싱·크롤 계획·표 추출·통계) | 자유 |
| retrieval | `fetch.py` 독점, blob 해시 | **그대로.** 샌드박스에는 fetch blob이 읽기 전용으로 들어간다 | 좁음 |
| 분석 | 발췌를 옮겨 적기만 | **코드로 계산한 클레임**(§4.3) | 재실행으로 검증 |
| 조립 | `final_compose` 한 번 + 게이트 재시도 | **리포트를 산출물 파일로 쓰고 검사기를 도구로 돌린다**(§4.4) | 게이트는 그대로 |
| 원장 | 오케스트레이터 단일 작성자 | **그대로** | P2 |

### 2.3 가져오지 않는 것

[PLAN_260913.md §2.1](PLAN_260913.md)의 금지 목록이 J에도 그대로 걸린다. 특히:

- ❌ `while(true)` 루프, 자식을 끝까지 돌리는 `run_until_done`, coordinator/mailbox
- ❌ Hermes식 호스트 `execute_code` — **코드는 샌드박스에서만, 네트워크 없이** 돈다
- ❌ 워커가 원장에 직접 쓰기 — 코딩 워커의 산출물은 **제안**이고 오케스트레이터가 쓴다
- ❌ 샌드박스가 켜져 있다고 승인·검증 생략 (CC `autoAllowBashIfSandboxed` 반패턴)

---

## 3. 북극성과 출하 기준

### 3.1 목표 상태

> ✅ **2026-10-03 일반화(사람의 결정):** NEOS 의 1차 실행 모델은 **재실행 가능한 검증이 붙은 코드 실행**이다.
> 검증형 분석은 그 한 사례다 — 코딩 태스크도, 상시 에이전트도 같은 문장 아래 선다. 한계도 같이 적는다:
> **검증할 수 있는 부분을 코드로 한다** — 재실행으로 검증되지 않는 판단(의미 정합성 등)은 판정자의 몫으로 남는다.
>
> **검증형 분석을 NEOS의 1차 실행 모델로 승격한다.** 사용자가 "이 주장이 사실인가"를 물으면,
> 모든 문장이 검증된 클레임으로 역추적되는 리포트가 나온다. 실패하면 조용히 degrade하지 않고
> 원장에 이유를 남긴다.
>
> **그 조사는 코드로 한다.** 워커는 샌드박스에서 스크립트를 쓰고 돌려 증거를 모으고 계산한다.
> **계산한 사실도 검증된 사실이어야 한다** — 스크립트와 입력이 원장에 있고, 채점기가 다시 돌려
> 같은 값을 얻을 때만 클레임이 된다.
>
> **그리고 하네스는 조립된 구조다.** 부품은 교체 가능하되 **무엇이 조립됐는지는 원장이 답한다.**

### 3.2 출하 기준 S1~S6 — 전부 ✅ (2026-08-18). 그러나 출하 신호가 아니다

| # | 기준 | 근거 |
|---|---|---|
| S1 | LLM이 조립한 리포트가 실제로 나온다 | 표본 #1 |
| S2 | 게이트가 알맹이 있는 리포트를 통과시킨다 | 표본 #5, **n=1** ⚠️ (#20 통과 1, #21 **0**) |
| S3 | 리포트 본문이 보존된다 | 전제 정정 |
| S4 | 정지 사유가 원장에서 구분된다 | 무이벤트 정지 0건 |
| S5 | 스위트가 결정론적으로 통과 | 시드 5종 + 벽시계 상한 6분 |
| S6 | 실패가 사용자에게도 보인다 | fixture가 라벨 커버리지를 센다 |

> 🔴 **6/6은 "출하하라"가 아니다.** 조용한 실패를 막는 기준이지 조사 품질의 증명이 아니다.
> W6(승격)의 관문은 **리덕션 층**(§7)과 `ROADMAP.md`의 R1·R2·R6이다. S2를 다시 두껍게 세우는 것은 필수에 가깝다.

### 3.3 J가 더하는 출하 기준 — 넷 다 착지 (2026-09-28)

| # | 기준 | 왜 | 상태 |
|---|---|---|---|
| **S7** | 계산 클레임은 **재실행 없이는 verified가 되지 않는다** | 코드가 만든 숫자는 발췌보다 더 그럴듯하게 틀린다 | 🟢 실제 경로에서 초록 — `tests/workflow/deep_analysis/test_code_research_e2e.py` |
| **S8** | 코딩 워커의 모든 실행이 원장에서 **스크립트 digest + 입력 raw_ref + 출력 digest**로 복원된다 | "매니페스트 없는 런은 표본이 아니다"의 확장 | 🟢 모든 실행이 `script_executed` 로 남는다(버린 시도 포함). `evidence_refs` 는 **상한 집합**이고 정확한 입력은 클레임의 `inputs` 가 싣는다 |
| **S9** | 플래그 off일 때 워커 프롬프트·도구 목록·이벤트 어휘가 **바이트 단위로** 같다 | 트랙 I가 세운 방법. 켜는 커밋만 경계가 된다 | 🟢 `test_code_research_invariants.py` (I1 절) |
| **S10** | 샌드박스를 요구하는 프로파일에서 샌드박스가 없으면 **실패한다**(비샌드박스 폴백 없음) | PLAN_260913 B5를 DA 경로에도 | 🟢 설정 검증. ⚠️ managed·memory provider 의 계약 §3.2 downgrade 는 남았다(§12.11) |

경위: [DONE §1.4](DEEP_ANALYSIS_HARNESS_DONE.md)

### 3.4 L이 더하는 출하 기준 (설계, 미충족)

| # | 기준 | 왜 |
|---|---|---|
| **S11** | Jev 판정은 정적 정책 결과를 **좁히기만** 한다 | `DENY → ALLOW`·`REQUIRE_APPROVAL → ALLOW` 전이를 **변이 테스트가** 막는다. 확률이 denylist 를 이기면 게이트가 아니라 우회로다 |
| **S12** | Jev 가 없을 때 하네스는 **정적 정책으로 떨어지되 조용히 떨어지지 않는다** | D-L1(§12.4). `jev_unavailable` 없는 폴백은 없다 — "새 fallback을 이벤트 없이 추가하기"(§9)는 L에서도 금지다 |
| **S13** | 모든 판정 이벤트에 **밴드 임계값 · 루브릭 digest · 해소된 모델 id**가 실린다 | 임계값을 모르면 과거 판정을 재현할 수 없다 = **그 런은 표본이 아니다** |

---

## 4. 목표 아키텍처 — 트랙 J: 코딩 루프로 조사한다

### 4.1 한 장

```
Orchestrator (단일 작성자, 원장, TokenBudget, 라운드 스케줄) ── 바뀌지 않음
   │  Assignment(질문, 예산, 허용 도구, 샌드박스 프로파일)
   ▼
SubagentRuntime  (spec = research | analyze | compose, fail-closed 카탈로그)
   │  1-step: 모델 턴 XOR 도구 배치 · park/fold · lease
   ▼
Coding-loop worker ─────────────── tools ─────────────────────────────┐
   │ search.v1        (discovery, 자유)                                │
   │ fetch.v1         (retrieval → fetch.py, blob 해시, 원장이 기록)   │
   │ list/read/search_text  (워크스페이스 = 이번 질문의 blob 마운트)   │
   │ write_file/edit_file   (scratch 스크립트·표·초안)                 │
   │ execute.v1       (샌드박스 python, network=none, allowlist argv)  │
   │ load_skill.v1    (분석 스킬: 표 추출·통계·PDF·비교)               │
   │ check_claims.v1  (DeterministicGrader를 읽기 전용 도구로)         │
   │ submit.v1        (구조화 제안 — 원장에 쓰지 않는다)                │
   ▼                                                                   │
Proposal(claims[quote|computed], subquestions, dead_ends, artifacts) ◀┘
   │
   ▼
Orchestrator → DeterministicGrader(+재실행) → AgenticGrader(judge ≠ worker) → 원장
```

### 4.2 설계 결정 — 왜 이 모양인가

| 결정 | 이유 | 대안과 기각 사유 |
|---|---|---|
| **워커는 서브에이전트 런타임 위의 자식이다** | 1-step·lease·fold·cancel cascade가 이미 있고 테스트돼 있다 | DA 전용 루프 신설 → "고침은 한 호출부에만 도착한다"의 재발 |
| **fetch는 도구지만 구현은 `fetch.py` 하나** | retrieval 독점과 blob 해시가 `E_SOURCE_DEAD`·`E_QUOTE_MISMATCH`의 전제다 | 샌드박스에 네트워크를 연다 → 채점기가 볼 수 없는 원문이 생긴다 |
| **샌드박스는 `network=none`, blob은 읽기 전용 마운트** | 코드가 가져온 바이트는 원장에 없다 = 검증 불가 | allowlist 네트워크 → 재현성과 적대적 입력 경계가 둘 다 흐려진다 |
| **출력 계약은 `submit.v1` 도구 스키마** | "JSON 외 출력 금지" 문장이 도구 계약으로 바뀐다(CE ②) | 자유 텍스트 + 파서 → A5 "JSON 파싱은 llm.py 한 곳"과 충돌 |
| **검사기를 워커에게 도구로 준다** | 워커가 제출 전에 스스로 발췌 불일치를 잡는다. 판정은 여전히 오케스트레이터 쪽 채점기가 한다 | 검사기 비공개 → 게이트 재시도로 비용을 치른다 |
| **판정자는 코딩 루프가 아니어도 된다** | judge ≠ worker. 판정자에게 코드가 필요하면 **별도 인스턴스**의 analyze 자식을 쓴다 | 같은 자식이 제안·판정 → E3 재발 |

### 4.3 계산 클레임 (computed claim) — J의 새 계약

지금 규칙은 **"비교 표현은 같은 excerpt가 비교 대상과 방향을 모두 직접 명시할 때만"** 이다
(`worker_brief.md`). 그래서 두 출처의 숫자를 나눠 "A는 B의 2.3배"라고 말하는 클레임은
**원리적으로 만들 수 없다.** 코딩 워커가 여는 가장 큰 가치가 여기 있고, 가장 큰 위험도 여기 있다.

```
ComputedEvidence
  script_digest    sha256(스크립트 바이트)         — 스크립트 본문은 blob 저장소
  inputs           [raw_ref, ...]                    — 전부 fetch blob이어야 한다
  runtime          named sandbox profile + image digest
  output_digest    sha256(정규화된 stdout)
  claimed_value    클레임 본문이 인용하는 값
  premises         [claim_id, ...]                   — 입력 수치 각각의 quote 클레임
```

**채점 규칙 (설계):**

| 코드 | 강제하는 것 |
|---|---|
| `E_COMPUTE_INPUT_UNFETCHED` | 입력이 전부 원장의 fetch blob인가 |
| `E_COMPUTE_NOT_REPRODUCED` | 채점기가 **같은 프로파일에서 다시 돌려** 같은 output_digest를 얻는가 |
| `E_COMPUTE_VALUE_MISMATCH` | 클레임 본문의 값이 출력에 있는가 |
| `E_COMPUTE_PREMISE_UNVERIFIED` | 계산이 기대는 입력 수치가 각각 **verified quote 클레임**인가 |
| confidence 상한 | 전제 클레임들의 **최소** 상한을 넘지 못한다 |

> ⚠️ **재실행은 커밋 경로에서 하지 않는다.** 설계 부록 A2(커밋 경로 네트워크 I/O 금지)와 같은 이유다 —
> 재실행은 채점 단계의 사전 작업이고 결과만 원장에 온다.
>
> ⚠️ **비결정적 스크립트는 거절한다**(시간·난수·해시 순서). "가끔 재현된다"는 verified가 아니다.

### 4.4 리포트를 프로그램 산출물로 쓴다

`compose` 자식은 리포트를 **워크스페이스 파일**로 쓰고, 제출 전에 `check_claims.v1`로
인용 커버리지·고아 인용·가용 verified 대비 인용 비율을 **스스로 돌린다.** 게이트는 오케스트레이터
쪽에 그대로 있다 — 자식의 검사는 비용 절감이지 판정이 아니다.

클레임은 프롬프트에 한꺼번에 싣지 않고 **파일로 공개한다**(질문별 디렉터리, `search_text`로 찾기).
이것이 CE ③(선행 적재 → 점진 공개)의 구현 경로다.

> 🔴 **이것이 CITE1을 고친다고 주장하지 않는다.** D92의 강등 152건이 전부 `input_bound`였다는 사실은
> "점진 공개가 리덕션 손실을 줄일 것"이라는 **가설**의 근거일 뿐이다. 원인 판별(#23)보다 먼저
> 리덕션 층을 바꾸면 D40·D51의 반복이다 — **원인을 모르는 채 고친다.** J4는 #23 판정 뒤다.

### 4.5 단계 — 전부 플래그 off로 착지한다

| 단계 | 내용 | 선행 | 표본 필요 |
|---|---|---|---|
| ~~**J0**~~ ✅ | [계약 문서](DEEP_ANALYSIS_CODE_RESEARCH_CONTRACT.md) (2026-09-15) | — | 없음 |
| ~~**J1**~~ ✅ | 도구 경계 · S9 바이트 동일 테스트 (2026-09-23, 빈 표면은 J1.5 가 채웠다) — [DONE §1.1](DEEP_ANALYSIS_HARNESS_DONE.md) | J0 | 없음 |
| ~~**J1.5**~~ ✅ | `execute.v1` → 계산 클레임 → 재실행 → verified, 진짜 원장 위에서 (2026-09-28) — [DONE §1.2](DEEP_ANALYSIS_HARNESS_DONE.md). 📌 남긴 규칙: 조사 게이트는 **재실행 가능성**으로 판정한다(§12.3) · 스크립트 blob(`sandbox-script://`)은 증거·입력이 될 수 없다(I4) · 계산의 premises ID 는 **다음 라운드에** 공개된다 · research 자식도 계산 클레임을 내되 전제는 **같은 질문**(채점기 규칙 2) | J1 · CHILD-GATE | 없음 |
| ~~**J2**~~ ✅ | 계산 클레임 채점기 + 재실행 + 이벤트 짝 · **GRADE1** 전용 판정 프롬프트 `judge_computed.md` (2026-09-28) — [DONE §1.3](DEEP_ANALYSIS_HARNESS_DONE.md). 📌 런 매니페스트 `prompts` 에 `judge_computed` 키가 늘었다 | J1 | 없음 |
| ~~**J3**~~ ✅ | 오프라인 섀도 (2026-09-21). ⚠️ brief 가 **지금** 원장 상태로 조립되므로 "그때 그 패스"의 재현이 아니다 | J2 | 없음(카세트) |
| ~~**J4**~~ 🟢 | compose 자식 + 클레임 파일 공개 + `check_claims.v1` — **착지(2026-10-03, D105)**, `deep_analysis.compose_child_enabled`(기본 off). 계약과 달리 `code_research_enabled` 와 **따로** 켠다(한 표본에 처방 하나) | ✅ CITE1 원인 판정(D104) | ✅ #25 사전 등록(D105) → #25 무효(배선 결함 셋, D106) → #26 무효(체크포인트 가림 깊이 · **API 사용 한도 소진**, D107). → 선행 둘 충족(키 교체 · 라이브 dry run **3/3 제출**) → **#27 사전 등록(D108)** |
| **J5** | 라이브 표본 **C-계열**(새 계보, §8 경계 8). research만 → analyze 추가 → compose 추가, **한 표본에 하나씩** | J4 · 사전 등록 | ✅ |
| **J6** | 분석 스킬 학습: 반복된 스크립트를 스킬 후보로 **staged** — 승인 전 미주입(`learn.write_approval`) | J5 | ✅ |

**J가 기다리는 인프라:** development는 Docker(`network=none`)로 충분하다. staging·production은
PLAN_260913 **B2 게이트**(managed provider)가 선행이다. Docker를 production 경계로 쓰지 않는다.

> ✅ **결정 (2026-09-15): J의 staging·production 샌드박스는 B2 게이트에 묶는다.**
> - `research-offline-v1` 프로파일은 B2와 **같은 named profile 체계**로 등록한다. DA 전용 샌드박스 경로를 따로 만들지 않는다
> - B2 게이트(실 SDK·실계정 smoke·region/residency·보안 검토)를 통과하기 전에는 development 밖에서 J 플래그를 켤 수 없다. **설정 검증이 거부한다**(S10)
> - B2 게이트가 늦어져도 J1~J3은 development(Docker `network=none`)와 카세트로 진행한다. **C-계열 라이브 표본(J5)도 B2 전에는 development 프로파일에서만** 돈다
> - 게이트 조건이 바뀌면 이 줄이 아니라 [재검토 §8.2](MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md)를 고친다

---

## 5. 프롬프트·런타임 전략 — 트랙 K: Fable 5.1

**입력:** [fable-5-1-multiagent-spec.md](fable-5-1-multiagent-spec.md) (R-01~R-08, P-01~P-07).
이 스펙은 **Anthropic 공식 문서 "Prompting Claude Fable 5.1"을 바탕으로 한다.** 프롬프트 블록은
공식 권장 문구를 **그대로** 쓴다(§10.5).

> ✅ **K0 착지 (2026-09-15)** — `models.yaml` 에 `claude-fable-5-1`(`selectable: false`, 기능 오버라이드로만) ·
> 카탈로그 `mid_conversation_system`. 상세는 [DONE §2.1](DEEP_ANALYSIS_HARNESS_DONE.md).
>
> 📌 **원문이 정한 사실 셋 — 계속 걸린다:**
> - **thinking은 끌 수 없다.** Fable 5.1로 라우팅하는 순간이 켜는 순간이다
> - **강제 `tool_choice`(any/tool)가 400이다.** 코딩 루프는 쓰지 않는다. `ui_frame_generator.py`가 쓰지만 Fable로 가지 않는다
> - **최근 턴을 남기는 컴팩션도 허용된다** — 남긴 턴의 thinking만 떼면 된다
>
> ⚠️ 원문 대조 중 발견: 카탈로그 `claude-sonnet-5` 가격(3/15)이 레퍼런스(2/10)와 다르다. 범위 밖이라 고치지 않았다 — 별건

### 5.1 NEOS 프롬프트 전략 — 일곱 원칙

스펙을 이 저장소의 흉터와 겹쳐 읽으면 원칙은 일곱으로 줄어든다.

1. **모델에게는 판단을, 사람에게는 절차를.** "제약을 줄이라"는 모델 지시에 대한 말이다.
   측정 절차(사전 등록·정확히 1회·규칙 하나 = 표본 하나)는 풀지 않는다 — 풀면 효과를 잴 수 없다.
2. **첫 문장이 모드를 선언한다.** 자율(DA 워커·백그라운드 코딩) vs 사람이 보는 모드(Code UI).
   P-01의 "사용자가 실시간으로 보지 않는다"와 R-04의 "진행을 알리라"는 **같은 프롬프트에 둘 수 없다.**
   모드는 오버레이로 고르고(G11) 섞지 않는다.
3. **지시는 계약으로.** 출력 형식 문장 → 도구 스키마(`submit.v1`). JSON 예시 리터럴 → 스키마(CE ②).
4. **이력은 절대 고치지 않는다. 반복 주입은 턴 한정 system으로.** 리마인더를 넣었다 빼는 순간
   thinking 바인딩(400)과 프롬프트 캐시가 동시에 깨진다(R-01·R-02).
5. **effort가 1차 레버다.** 모델 교체·프롬프트 형용사("깊이 생각하라")는 2차다. 레벨 이름은
   모델 간 같은 사고량이 아니므로 **스윕은 모델별로 다시 한다**(R-05).
6. **억제 문구를 지우는 것이 문구를 더하는 것보다 먼저다.** 이전 세대용 "서술하지 말라"·
   "포맷 줄이라"는 Fable 5.1에서 반대로 작동한다(P-07·R-04).
7. **프롬프트 변경은 버전이 붙은 측정 대상이다.** `<!-- version: N -->` + golden 게이트
   (`deep_analysis_l5.md` §4) + G12. 문구 하나 = 표본 하나.

### 5.2 갭 표 — 스펙 항목 × NEOS 현재 (2026-09-15 대조, 2026-09-28 갱신)

착지 경위는 전부 [DONE §2.1](DEEP_ANALYSIS_HARNESS_DONE.md). 여기는 **남은 갭과 지킬 규칙**만 든다.

| ID | 스펙 | 상태 | 남은 갭 · 지킬 것 | K 티켓 |
|---|---|---|---|---|
| **R-01** | 이력 append-only, 원본 그대로 재전송 | ✅ K1 · K1c · K1b | 비-append 편집의 thinking 제거는 **`_guard_thinking_prefix` 한 곳**에서만 한다 — 경로별로 고치지 않는다. 이 계정에서 바인딩 불일치는 400 이 아니라 **조용하다**(§5.6) | ~~K1~~ · ~~K1c~~ · ~~K1b~~ |
| **R-02** | 턴 한정 system message (`clear_at`) | ✅ K2 · K2b | `deferred` 는 도구의 **정적** 속성이다 — 공개 때 뒤집으면 배열이 흔들려 버그가 고침의 탈을 쓰고 돌아온다. `mid_conversation_tools` 는 `claude-fable-5-1` 에만(어느 모델이 받는지는 로컬에서 알 수 없다) | ~~K2~~ · ~~K2b~~ |
| **R-03** | 서브에이전트 즉시 반환 + `await` 도구 | ✅ K3 (기본 off) | **켜는 것은 A1·A2 숫자 뒤**(§5.3, 표본 경계). 결과 전달은 append 만 | ~~K3~~ |
| **R-04** | progress thinking 렌더 | ✅ K4a · K4b | 프롬프트 절반은 **K9·K11 뒤** — 스펙이 자율 모드를 제외하는데 DA 워커는 항상 자율이다 | ~~K4a~~ · ~~K4b~~ |
| **R-05** | effort 역할별 외부화, 중간 변경 | ✅ ①~③ · 채팅 · ④ DA · ④ 코딩 | **⑤ 벤치 러너**(모델별 스윕). 모델별·`everyday` 기본값은 채팅·DA·코딩에 함께 걸린다 — 그 값을 정하는 커밋은 세 지표의 경계다(§8 행 10). ⚪ preflight 는 effort 없이 찌른다 — 역할이 받지 않는 레벨의 400 은 여기서 보이지 않는다 | **K5** P1 |
| **R-06** | `refusal` 정상 분기, base64 필터 | ✅ K6 | 도구 결과 매핑은 **만들어지는 자리**에 건다(§14) | ~~K6~~ |
| **R-07** | 클라이언트 compaction = 요약 1건 + 새 user 턴 | ✅ K7(가드로) · P-05(기본 off) | 가드는 **유효성**을 지키지 요약 품질을 지키지 않는다 | ~~K7~~ · ~~P-05~~ |
| **R-08** | `max_tokens` = 사고 + 응답 | `ModelLimits.thinking_budget` 필드는 있음 | 긴 산출물(compose)의 한도 산식 + 예산 노트 | **K8** P2 |
| **P-01** | 자율 완수 블록 | ✅ 코딩 autonomous(K9) | ⚪ DA 쪽은 아직 — DA 워커는 **항상 자율**이지만 워커 프롬프트를 움직이면 #23 전 금지 | **K9** P0 |
| **P-02** | 변경·테스트 범위 제한 | ✅ 코딩 **autonomous** 만(K9) | ⚪ interactive 투입은 §8 경계 11 의 행 하나 — autonomous 효과를 본 뒤. 조사: "질문을 넓히지 않는다"로 번역(`worker_brief`의 범위 규칙과 합친다) | **K9** |
| **P-03** | 배칭 넛지(턴마다 새 사본) | `_using_tools`에 병렬 허용 문장(정적) | K2 착지로 선행 풀림 | **K10** P1 |
| **P-04** | 부분 편집 선호 | 없음 | 한 문장. 조사 워커엔 무관 | **K10** |
| **P-05** | compaction 요약 6항목 보존 | ✅ 착지, 기본 off (2026-09-25) | **켜기** = 코딩 에이전트 지표의 표본 경계(§8 행 11). ⚠️ 별건: 요약기 입력이 `json.dumps(prefix)[:12_000]` — **앞에서** 자르므로 긴 대화에서 가장 **최근** 부분이 요약기에 닿지 않는다(공식 지시 (4) 의 재료가 빠진다). 문구 하나 = 표본 하나라 P-05 와 섞지 않았다 | 입력 절단 |
| **P-06** | low effort 검색 유도 | — | **scout(everyday)가 직접 해당.** 1차 대응은 그 턴만 effort 상향(K5) | **K11** P2 |
| **P-07** | 억제 문구 제거 | 코딩 `_tone` 미감사. DA 프롬프트는 JSON 계약이지 안티포매팅이 아니다 | grep 감사 → 제거. `final_compose`에는 "mannered prose" 한 줄 후보 | **K11** |

### 5.3 K3 — 비동기 서브에이전트: 채택 (2026-09-15 결정) · 착지 (2026-09-22, 기본 off)

| | park/fold (지금) | 즉시 반환 + await (R-03) |
|---|---|---|
| 1-step 법 | 그대로 | **지킬 수 있다** — 자식 결과는 부모의 다음 safe point에 user 메시지로 append, `await_subagent.v1` = 명시적 park |
| lease·체크포인트 | 단순 | 부모 lease 동안 자식 여럿이 도는 상태를 체크포인트에 넣어야 한다 |
| PLAN_260913 §2.1 | 준수 | "부모 계속 코딩+알림" 금지를 **개정했다** (1-step 안의 append로 한정) |
| DA에 미치는 영향 | **없다** — DA의 부모는 LLM이 아니라 오케스트레이터이고, 라운드 fan-out이 이미 비동기다 | 없다 |
| 이득이 나는 곳 | — | Code 제품의 LLM 부모만 |

> **결정:** Anthropic 공식 스펙의 방식(R-03)을 채택한다. DA(트랙 J)는 여전히 영향이 없다.
>
> **개정의 경계:** 가져오는 것은 **즉시 반환 + 다음 safe point의 user 메시지 append + 명시적 `await_subagent.v1`** 이다.
> CC식 `while(true)` 부모 루프의 notification drain·mailbox·coordinator는 **여전히 금지**다.
> 결과 전달은 append만 한다(K1 선행). 자식 여럿이 부모 lease 아래 도는 상태는 체크포인트에 들어가야 한다.
>
> ⚠️ **A1 베이스라인은 여전히 켜기 전 조건이다.** 결정은 구현 방향이고, 기본값을 켜는 근거는 A1·A2 숫자다.
> park/fold를 켜는 커밋과 비동기 spawn을 켜는 커밋은 코딩 에이전트 지표의 경계다.

### 5.4 컨텍스트 엔지니어링 정책 (구 §9, K에 편입)

| # | 규칙 | 이 저장소의 흉터 | 이제 어디서 구현되나 |
|---|---|---|---|
| ① | 제약 → 판단 | `final_compose.md` v2·v3·v5 | K11(억제 문구) · 원칙 1 |
| ② | 예시 → 인터페이스 | `node_summary.md` JSON 리터럴 | **J1 `submit.v1`** |
| ③ | 선행 적재 → 점진 공개 | 강등 152건 전부 `input_bound` | **J4 클레임 파일 공개** |
| ④ | 반복 → 정밀 | `[C:claimid]` 지시 세 겹 | J4 `check_claims.v1`이 지시를 검사로 바꾼다 |
| ⑤ | 수동 → 자동 메모리 | 채택 안 함 | J6 staged 스킬(승인 게이트)로만 |
| ⑥ | 단순 스펙 → 풍부한 참조 | F1 사망 원인 | J0 계약 문서 |

**①~④는 같은 자리를 가리킨다. 그래서 한 표본에 둘 이상 넣지 않는다.** CITE1 판정 전 착수 금지는 유지한다.
`final_compose.md` 계보(v2 맹목 재굴림 방지 · v3 질문 텍스트 요구 · v5 길지만 나쁜 재시도)는
**되돌리면 아픈 흉터다** — 무엇을 되돌리는지 알고 되돌린다.

### 5.5 K 순서

```
✅ K0 · K1 · K2 · K7 (09-15) · K1c · K1d (09-17) · K2b · K6 · K4a (09-19) · K3 (09-22, 기본 off)
✅ K1b · K4b (09-24) · P-05 (09-25, 기본 off) · K5 ①~④ (09-21~28) · K9 모드·오버레이·P-02 autonomous (09-28)
K5 ⑤ 벤치 러너 ─> 모델별 스윕 ─┬─> 워커를 Fable 5.1로 라우팅 (§8 경계 9)
K9 (DA 쪽 · P-02 interactive) ─┘
K9 ─> K11 억제 문구 감사
K10 배칭 넛지 · K8 max_tokens (K5 값 뒤)
```

> ⚠️ **가짜로 확인하지 못한 가정 하나:** assistant 턴 안에서 thinking 블록을 **맨 앞에** 모은다(`_completed_turn`).
> K1b 네 세션에서 thinking 은 늘 턴 첫 블록이었다 — **반증되지 않았을 뿐 확인되지 않았다.** 중간에 오는 응답이
> 관측되면 스트림 순서를 보존하도록 고친다.

### 5.6 K1b · K4b 실측 (2026-09-24)

전문은 [DONE §2.2](DEEP_ANALYSIS_HARNESS_DONE.md). 앞으로도 걸리는 사실만 남긴다.

- **NEOS 경로 재전송은 서명 바인딩을 깨지 않는다** — 네 세션 모든 턴 `input_transformations: []`, 음성 대조가 진단이 살아 있음을 보였다
- 🔴 **이 계정에서는 바인딩 불일치가 400 이 아니라 200 이다.** 알려 주는 에러가 없으므로 `_guard_thinking_prefix` 가 유일한 방어다
- **`thinking.display` 를 보내지 않으면 본문이 빈다**(서버 기본 `omitted`, SDK 독스트링이 틀렸다). 카탈로그 `thinking_display` 를 선언한 모델에만 싣는다
- **reasoning 토큰은 output 의 내역이다** — API 는 `usage.output_tokens_details.thinking_tokens` 에 싣고, 예산 합에 따로 더하지 않는다
- K1b 가 Fable 5.1 라우팅(§8 경계 9)의 선행이라던 것은 풀렸다. 남은 조건은 K5·K9 다

---

## 6. 미래 지향 전략 — 모델 세대가 바뀌어도 버티는 하네스

### 6.1 세대가 바뀔 때 깨지는 곳은 세 층이다

| 층 | Fable 5.1에서의 예 | 흡수 장치 | 없으면 |
|---|---|---|---|
| **와이어 계약** | thinking 바인딩 검증, `clear_at`, `display: updates` | 프로바이더 어댑터 + **요청 바이트 계약 테스트**(K1) | 400으로 전멸 — 조용하지 않아서 차라리 낫다 |
| **행동 기본값** | 서술량 감소, 포맷 감소, 허가 질문, 파일 전체 재작성 | **family별 프롬프트 오버레이**(카탈로그가 가리킨다) + 억제 문구 감사 | 조용히 품질이 바뀐다 — **가장 위험하다** |
| **제어 의미** | effort 레벨 이름이 같아도 사고량이 다르다 | **모델별 effort 스윕 벤치**(K5) | 옛 스윕 값이 새 모델에서 조용히 틀린다 |

**둘째 층이 가장 위험한 이유는 에러가 나지 않기 때문이다.** 그래서 모델 교체는 §8 표본 경계다
(판정자 교체 E3가 채점 계열 전체를 끊었다).

### 6.2 다섯 가지 베팅

1. **자유는 discovery 쪽으로, 규율은 원장 쪽으로.** 모델이 강해질수록 워커의 도구·코드·자율을 넓힌다.
   채점기·원장·예산은 넓히지 않는다. 강한 모델일수록 **그럴듯하게 틀린 것**을 더 잘 만든다.
2. **도구를 늘리지 말고 코드와 스킬을 늘린다.** Claude Code와 Hermes가 같은 곳으로 수렴했다 —
   작은 고정 도구셋 + 샌드박스 + 마크다운 스킬. 새 분석 능력은 **스킬 파일 + 계약**으로 들어온다(J6).
3. **서버 기능 우선, 폴백은 이벤트와 함께.** 서버사이드 compaction·context editing·턴 한정 system이
   되면 쓴다. 폴백을 더할 때는 그것이 남기는 이벤트를 함께 정의한다(§9).
4. **모델 사실은 카탈로그에만.** 창·가격·effort 지원·thinking 규칙. 확인 못 한 값은 적지 않는다.
   코드에 `if model.startswith("claude-fable")`가 생기면 그것이 결함이다.
5. **평가 인프라가 제품이다.** 카세트 · 사전 등록 · 판독기 · effort×모델 벤치 · 프롬프트 버전 게이트.
   새 세대가 오면 **다시 재는 비용**이 이 로드맵의 속도를 정한다.

### 6.3 하지 않는 베팅

- ❌ "새 모델이니 프롬프트를 통째로 다시 쓴다" — 스펙 §3 비목표. 흉터가 사라진다
- ❌ "모델이 알아서 하니 채점기를 느슨하게" — 베팅 1의 반대
- ❌ 라이브 카탈로그를 정본으로(models.dev류) — YAML이 정본이다
- ❌ 모델이 런타임에 새 에이전트 타입을 발명 — 카탈로그 fail-closed

---

## 7. 지금의 병목 — 인용 생산 사슬

> ✅ **2026-10-03: #23·#24 를 돌렸다.** #23 원 규칙 판정은 W-2 로 보류(D102), 귀속 규칙을 고쳐 #24 판독 전에 등록(D103),
> #24 가 BUDGET2 를 확인하고 CITE1 원인을 **후보 ② 자기 클레임 침묵 폐기**로 묶었다(D104). 아래 실행 순서는 기록으로 남긴다.

**트랙 A에서 코드로 할 수 있는 일은 비었다.** 남은 것은 라이브 표본 하나다.

```
#21  예산을 21% 풀었다 → 검증 클레임 68→91 → 게이트 통과 1→0
      ⇒ 병목은 재료(조사 깊이)가 아니다                              [D86]
#22  판정자 교체 후 기준선 재수립. 지배적 반려는 여전히 인용 계열     [D89]
D90  조립기가 가용 verified 클레임의 절반 이하만 인용한다 (#21 0.43 · #22 0.28)
D91  writer 1.00 · clamp 0.70~0.77 · selection 0.56~0.63
      ⇒ `final_compose` 는 무죄. 손실은 `reduce_node` 의 출력에 있다
D92  리덕션의 2/3 가 LLM 에 닿지도 못한다 (79 대 152, 152건 전부 input_bound)
      ⇒ 후보 셋: ① LLM 미탑재 ② 자기 클레임 침묵 폐기 ③ 절단
D93  사전 등록을 표본보다 먼저 세웠다 (판독기 + 테스트 14 + 재현 게이트)
D94  🔴 preflight 가 통과했는데 세 역할이 전부 401 — 키 존재만 봤다
D95  🔴 identity-linked 키는 `anthropic-workspace-id` 필요. 고칠 자리가 아홉 곳
```

| 무엇 | 상태 |
|---|---|
| 키 | ✅ `ANTHROPIC_WORKSPACE_ID` 는 필요 없다(2026-09-23 실호출) · `TAVILY_API_KEY` 채워짐(2026-09-28). 동작 여부는 아래 2 의 preflight 가 실호출로 본다 |
| 사전 등록 | ✅ **D98**(2026-09-24) — #23 은 BUDGET2 를 끄고 CITE1 을 가른다, #24 가 BUDGET2 를 잰다. 재현 게이트는 **독립 집계**(파서 대 SQL) |
| 판독기·테스트 14 | ✅ 재사용 |

경위: [DONE §5](DEEP_ANALYSIS_HARNESS_DONE.md)

**#23 실행 순서** (DECISIONS D98 §6 — 이대로 한 번만 돈다)

```
0. 도는 동안 DA 재개 버튼을 누르지 않는다(§10.1). 스크립트는 `jobs.execute_run` 을 프로세스 안에서
   부르므로 Celery 재전달(§10.1)은 이 경로에 걸리지 않는다 — Celery 로 옮겨 돌리지 않는다
1. (키는 채워졌다 — 2026-09-28)                                    ← 사람
2. NEOS_CONFIG_PATH=config/samples/sample-23.yaml \
     .venv/bin/python scripts/deep_analysis_funnel_sample.py        ← preflight 가 안에서 먼저 돈다
   (D99: 판정자는 Jev 다. preflight 가 Jev 판정자에도 실호출을 보낸다 — TYPESAFE_API_KEY 필요)
   dev 5 + default 1, 정확히 1회. 실패해도 재시도하지 않는다
3. 판정 전에 보존한다: 아티팩트 디렉터리를 저장소에 강제로 더하고(gitignore),
   여섯 런의 deep_analysis_* 행을 pg_dump 로 떠서 함께 둔다          ← #1~#22 가 사라진 경로
4. scripts/deep_analysis_reduction_attribution.py --run <여섯 접두사> --expect-budget2 off --expect-claim-judge jev
   독립 집계 게이트가 실패하면 판정하지 않는다
5. `judge_backend` 분포(jev · llm_fallback)를 먼저 적는다(D99 §2). 그다음
   W-1·W-2·W-3′·W-4′·Q-1~Q-3 을 읽고, 그다음 판정 코드를 읽는다
```

**#24** (D101) — #23 이 돌고 보존·판정된 **뒤에** 같은 순서로 한 번 돈다. 다른 것은 오버레이 하나다:
`NEOS_CONFIG_PATH=config/samples/sample-24.yaml` (BUDGET2 on, 판정자는 #23 과 같은 Jev). 판독은
`--expect-budget2 on --expect-claim-judge jev`, 기대값 P-1~P-3 의 기준선은 #23 이다.

> ⚠️ **그전에 `node_summary` 프롬프트나 리덕션 층을 손대는 것은 D40·D51의 반복이다.**
> **J4(점진 공개 조립)도 여기에 걸린다** — 가장 매력적인 처방이 가장 먼저 원인 판별을 오염시킨다.

---

## 8. 표본 경계 — 나란히 놓으면 안 되는 것

다음 사전 등록은 반드시 "이 중 어느 것도 가로지르지 않는다"를 적는다.

| # | 커밋 | 무엇이 바뀌었나 | 비교 불가 대상 |
|---|---|---|---|
| 1 | `59e34624` (C3) | 실패한 호출의 토큰이 질문에 청구된다 | 조사 정지 시점 |
| 2 | `43303acd` (C3-m1) | 판정자 토큰이 질문에 청구된다 | 조사 정지 시점 |
| 3 | `e11953ad`+`b3abefaa` (E3) | 판정자 `claude-sonnet-5` → `claude-opus-4-8` | **채점 결과 전부** |
| ~~4~~ | ~~`6ec71567` (G3-m1)~~ | ~~인용 게이트 분모~~ | ✅ 백테스트(D87)로 무효화 |
| 5 | BUDGET2 | 리덕션 클램프가 `available_for_reduction` 을 안다 | **리덕션 층 전부** |
| 6 | D2 | fetch가 429·503·전송 오류를 재시도한다 | **확보한 증거의 양**과 하류 전부 |
| 7 | `f9b6c261` | DA 호출이 코딩 하네스를 거친다(사용량 추출·중단 사유) | ⚠️ **경계 여부 미판정.** 카세트 백테스트로 토큰 회계가 같음을 보이기 전까지 조사 지출(L-1) 계보를 가로질러 놓지 않는다 |
| **8** | J 플래그를 켜는 커밋 | 워커가 코딩 루프가 된다 | **경계가 아니라 새 계보(C-계열)다.** #1~#23과 어떤 수치도 나란히 놓지 않는다. C-계열 안에서도 research/analyze/compose를 켜는 커밋이 각각 경계다 |
| **9** | K: 워커·판정자를 Fable 5.1로 라우팅하는 커밋 | thinking이 항상 켜진다(끌 수 없다) | 채점 결과 · 토큰 지출 · 벽시계 |
| **13** | K1c 착지 (2026-09-17) | **심층분석이 thinking 블록을 대화에 되돌려 싣는다** — `run_discovery` 의 도구 루프가 assistant 턴을 그대로 다시 보내므로 입력 토큰과 모델 행동이 같이 바뀐다. 자식도 같다 | **조사 지출(L-1) 계보** · 발견(discovery) 결과 · 자식 fold 요약. ⚠️ 경계 7(하네스 경유)과 **같은 방향으로 겹친다** — 둘을 함께 백테스트로 풀지 않으면 귀속이 불가능하다 |
| **12** | K0·K1·K2·K7 착지 (2026-09-15) | **코딩 루프**가 thinking 블록을 돌려보낸다(sonnet-5·opus-5는 adaptive가 기본이라 이미 블록이 오고 있었다) · pre_generate 훅의 system 노트가 system 프롬프트에서 메시지로 옮겼다 · 편집 경계에서 thinking을 뗀다 | **코딩 에이전트 지표(A1 베이스라인)** — 토큰·캐시 적중·완료율. **심층분석은 가로지르지 않는다**: DA 브리지(`harness_bridge.py`)는 thinking을 싣지 않고 system 노트를 쓰지 않는다 |
| **10** | K5: effort 기본값을 정하는 커밋 | 역할별 사고량 | 채점 결과 · 토큰 지출. **effort 변경마다 행을 더한다** |
| **11** | K9·K11: 오버레이·억제 문구 제거 | 워커 행동 기본값 | 채점 결과. 문구 하나 = 행 하나. 📌 2026-09-28 autonomous 오버레이(P-01 두 블록 + P-02)는 **행을 더하지 않는다** — autonomous 로 돈 태스크가 없어 비교할 이전이 없다, **새 계보의 시작**이다. interactive 에 넣는 날이 이 표의 행이다 |
| **15** | K2b 착지 (2026-09-19) | **Fable 5.1 의 `tools[]` 가 커졌다.** deferred 도구까지 매 요청에 선언하므로(17→18, `defer_loading` 으로 감춘다) **입력 토큰이 매 턴 늘고 캐시 경계도 달라진다.** 동시에 도구 공개가 더는 thinking 을 떼지 않으므로 **모델 행동도 같이 바뀐다** | 코딩 에이전트 **토큰·캐시 적중·완료율**. `mid_conversation_tools` 가 켜진 모델에서만. ⚠️ **K4a 는 경계가 아니다** — 이벤트만 더할 뿐 모델이 보는 것은 하나도 바뀌지 않는다 |
| **14** | K6 착지 (2026-09-19) | **거절이 `unknown`에서 분리됐다.** 같은 거절이 전에는 텍스트가 있으면 `model_output_incomplete`로, 없으면 **빈 텍스트 재시도**로 끝났다. 이제 `model_refused` 하나로 끝나고 재시도가 사라지므로 **호출 수와 지출도 함께 움직인다** | 코딩 에이전트 **실패 코드 분포**와 재시도 횟수. ⚠️ 토큰 경계는 **`image_tool`이 켜진 배포에서만** — 기본 off라 나머지 배포에서는 tool_result 바이트가 그대로다 |
| **16** | L3: Jev 도구 위험 게이트를 켜는 커밋 | **도구 호출이 확률 판정으로 차단된다.** 같은 입력이 같은 밴드에 떨어진다는 보장이 없다(σ≈0.01, §12.2) | 코딩 에이전트 **완료율 · 실패 코드 분포 · 승인 횟수**. DA 워커에 켜는 커밋은 **C-계열 안에서 또 하나의 경계**다 |
| **19** | `17dc2c19` (D106) | 도구 이름이 와이어에서 인코딩된다 · DA 자식이 자기 프롬프트(P-01·P-02)를 받는다 · memory 샌드박스 루트 절대경로 | **코딩 에이전트 지표**(와이어 바이트). 이 DB 에 라이브 코딩 기록이 없어 가로지를 과거 수치는 없다 |
| **18** | J4: compose 자식을 켜는 커밋(D105 — #25 는 배선 결함으로 무효, **#26 부터**, D106) | 최종 초안을 compose 자식이 쓴다 — 모든 verified 클레임을 파일로 받는다 | **조립·리포트 계열** — 인용 생산 · 리포트 게이트 · 조립 지출. 조사 지출·verified 는 가로지르지 않는다 |
| **17** | L6: 판정자를 Jev 로 교체하는 커밋 (2026-10-03, D99 — #23 부터 켠다) | 판정자 교체 — **경계 3과 같은 등급이다**. #23 은 이 경계를 가로지른 **새 채점 계보의 첫 표본**이다 | **채점 결과 전부.** C-계열과도 나란히 놓지 않는다: 새 계보를 연다. ⚠️ L5(섀도)는 판정을 바꾸지 않으므로 채점 경계가 **아니지만**, 호출이 하나 늘어나므로 **지출·벽시계 계보에는 경계다** |

**1·2는 방향이 예측 가능했다. 3·5·6은 아니다. 7은 판정 전이다. 8은 계보를 새로 연다.**

> **플래그 뒤 병합은 경계가 아니다**(트랙 I가 세운 방법). 꺼져 있으면 프롬프트·도구·계약이
> **바이트 단위로** 같음을 테스트가 고정해야 한다. 경계는 **켜는 커밋**이다. J·K도 이 방법을 따른다.

> 📌 D92 재현 게이트(79·152·152·15)는 **저장된 원장**을 읽으므로 어떤 경계에도 무효가 되지 않는다.
> 🔴 **그러나 그 원장이 로컬에 없다**(2026-09-24, 고아 볼륨까지 확인). 경계에는 면역이지만 **재료 소실에는 면역이 아니다.**
> D98 이 재현 게이트를 **독립 집계**로 바꿔 #23 의 새 원장 위에 세웠다(§7).

---

## 9. 절대 타협하지 않는 것

**설계 정본**([DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md))의
§1 5원칙과 §11 금지사항은 모든 성능·비용 논의보다 우선한다. (§번호는 그 문서의 것이다.)

**하네스 층:**

- **P2 단일 작성자** — 원장 쓰기는 오케스트레이터 한 곳
- **judge ≠ worker** — `judge: claude-opus-4-8`, 인용 클레임은 Jev(L6, D99 — `jev.judge_enabled` 일 때). ⚠️ LLM 판정자는 워커와 같은 가족이라 편향 분리가 약하다. ✅ **크로스 프로바이더 판정자는 허용된다**(2026-10-03)
- **append-only 이벤트 로그** — 예외는 의도를 표명한 트랜잭션뿐(`Ledger.purge_run()` + `SET LOCAL`)
- **매직넘버 금지** — 전부 settings. 프롬프트는 전부 파일

**플러그인 층:**

- 플러그인은 원장의 작성자가 될 수 없다
- 동적 설치 플러그인도 `TokenBudget.reserve()`를 거친다
- 매니페스트 없는 런은 표본이 아니다 — 기계가 거부한다
- judge 플러그인과 worker 플러그인은 같은 인스턴스일 수 없다

**코딩 루프 층 (J·K — 다치기 전에 세우는 것):**

- **코딩 워커는 원장에 쓰지 않는다.** `submit.v1`은 제안이다
- **샌드박스 안 코드는 네트워크가 없다.** 바이트는 `fetch.py`를 통해서만 들어온다
- **재현되지 않는 계산은 verified가 아니다**
- **자식의 LLM 호출도 `TokenBudget.reserve()`를 거친다** — fold가 사용량을 부모에 더하는 것과 별개로, 질문 예산에 청구돼야 floor 산식이 성립한다
- **대화 이력은 in-place로 고치지 않는다**(K1). 요약·리마인더·도구 목록 교체는 정해진 경로로만
- **샌드박스 ≠ 승인 생략**

**확률 판정 층 (L — 다치기 전에 세우는 것):**

- **Jev ≠ 승인 생략.** 확률은 정적 denylist 를 이기지 못한다 — **좁히는 방향으로만** 작동한다(§12.2 ②)
- **`DeterministicGrader` 는 확률 판정으로 대체되지 않는다.** 어떤 일치율이 나와도
- **임계값과 루브릭 digest 가 없는 판정 이벤트는 재현 불가다** = 그 런은 표본이 아니다
- **Jev 는 역할 라우팅 사슬(트랙 B)에 들어가지 않는다** — `everyday`/`powerful` 축이 아니다.
  섞으면 "경계마다 한 번만 해석"이 깨진다
- **일치율은 정확도가 아니다.** 쿡북이 직접 경고한 것을 근거로 승격하지 않는다(§12.1)

**하지 않기로 한 것:**

- 계약을 고쳐서 위반을 없애기(`.get()` 기본값으로 `requires` 떨어뜨리기)
- 새 fallback을 이벤트 없이 추가하기
- "동적이니까 설정이 아니다"

---

## 10. 작업 규칙 — 반복해서 다친 곳

### 10.1 라이브 표본

- ❌ 재실행 금지(정확히 1회, 자동 재시도 없음)
- ❌ 실행 중 grader 임계값·샘플링·프롬프트·모델·**effort**·한도 변경
- ❌ 5+1 단일 관측으로 인과 주장 · ❌ **여러 변경을 한 표본에**
- ✅ preflight가 모델을 **실제로 부르는지** 확인(D94)
- ✅ `manifest.json`에 실행 영수증(PID, UTC start/end, exit)과 구성 지문(model ID, **effort**, threshold, cap, **샌드박스 이미지 digest**)
- ❌ **표본이 도는 동안 재개 버튼을 누르지 않는다** (2026-09-28 코드 대조). `RESUMABLE_STATUSES` 에 `running` 이 들어 있고 DA 에는 실행 lease 가 없다. 살아 있는 run 에 resume 하면 두 번째 실행자가 뜨고, 그 실행자의 `ledger.recover()` 가 `investigating` 질문을 `open` 으로 되돌린다 → 이중 지출 · 원장 작성자 둘. 표본 하나가 그대로 오염된다
- ⚠️ **Celery 모드에서 1시간을 넘기는 표본은 재전달된다**. `task_acks_late=True` 인데 Redis `visibility_timeout` 을 설정한 곳이 없다(kombu 기본 1시간 < DA `job_time_limit`). 원래 워커가 살아 있어도 두 번째 워커가 같은 run 을 잡는다. 고치기 전까지 긴 표본은 인라인 실행으로 돌린다

### 10.2 증거 보존

`git worktree remove`는 gitignore 대상 파일을 경고 없이 삭제한다. `artifacts/deep-analysis-funnel/<ts>/`는
재생성 불가다. **J 이후에는 샌드박스 산출물(스크립트·출력)도 같은 등급이다** — 워크트리 정리 전에 옮긴다.

### 10.3 앰비언트 상태 오염 (전부 실제 발생)

| 증상 | 원인 |
|---|---|
| 전역 `settings` 싱글턴이 바뀐 채 남음 | `reload_settings_for_tests()`가 모듈 전역 재바인딩 |
| 프로세스 env가 테스트 지정값을 이김 | litellm import 시 `load_dotenv()` |
| import 시점 고정 플래그 어긋남 | `neos/main.py`의 `IS_DEBUG` |
| 테스트가 심은 AsyncMock이 전역에 남음 | `patch`는 팩토리를 복원하지 캐시된 인스턴스를 복원하지 않는다 |
| **개발 DB 에 테스트 런이 쌓임** (2026-09-24) | DB 를 쓰는 테스트가 `.env` 의 `DATABASE_URL` = `neos` 를 그대로 썼다. 09-20 의 DB 재구축도 배포 부트스트랩과 pytest 가 같은 `neos` 에서 부딪친 것이었다. ✅ 고쳤다 — `tests/conftest.py` 가 설정 로드 전에 DB 이름을 `<이름>_test` 로 강제한다(CI 도 `neos_test`) |
| **한 파일만 돌리면 깨지는 설정 테스트** (2026-09-24) | `test_config_loader.py` 10건 — `.env` 를 가린 뒤 development 프로파일을 로드하는데 코딩 루프가 크리덴셜을 요구한다. 전체 스위트에서는 **윗줄의 litellm `load_dotenv()`** 가 키를 프로세스 env 에 넣어 줘서 통과했다. 픽스처가 CI 와 같은 자리표시자를 준다 |
| **lesson·GEPA overlay 가 조용히 꺼짐** (2026-09-28 코드 대조, 운영 경로) | 코딩 Celery 전달이 끝날 때마다 `set_lesson_session_factory(None)` 을 부른다. 이 함수는 모듈 전역 `_USE_MEMORY_ONLY=True` 를 **프로세스 전체에** 고정한다(`neos/learn/lessons.py`). 같은 워커 자식에서 뒤이어 도는 DA·gepa_opt 태스크는 lesson 을 읽지 못하고, overlay 는 예외를 삼켜 `None` 을 돌려준다. 윗줄들과 뿌리가 같다 — 런 컨텍스트를 명시 객체가 아니라 모듈 전역으로 건넨다 |

### 10.4 검증 명령

```bash
.venv/bin/python -m pytest
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q
.venv/bin/pytest tests/coding tests/subagent -q

# 백테스트 판독기 — 저장된 원장만 읽는다
.venv/bin/python scripts/deep_analysis_citation_production.py --sample 21 --sample 22
.venv/bin/python scripts/deep_analysis_reduction_attribution.py --sample 21 --sample 22

# discard recall (C1) — ⚠️ 실제 판정자를 부른다
.venv/bin/python scripts/deep_analysis_discard_recall.py --run-id <run> --accumulate

# 라우팅 · 카탈로그
pytest -q tests/config/test_model_catalog.py tests/config/test_model_catalog_parity.py \
         tests/config/test_model_routing.py tests/utils/test_llm_factory_defaults.py

# 프론트
pnpm --dir web build && pnpm --dir web test:source && pnpm --dir web typecheck && pnpm --dir web typecheck:tests
cd api_gateway && cargo test --offline && cargo build --offline  # ⚠️ CI에 없다
```

> ⚠️ **절대 수치를 회귀 판정에 쓰지 말 것.** 변경 전후 `--collect-only`로 **수집 수의 증분이
> 추가한 테스트 수와 같은지** 본다. 로컬 통합 테스트는 부트스트랩된 DB가 필요하다 —
> DB 없는 실행은 회귀를 가린다.

### 10.5 낡은 문서

- ❌ `2026-07-11-deep-analysis-chatswap.md` 재실행 금지 → `DECISIONS.md` D18→D21→D22→D23
- ⚠️ `SUBAGENT_RUNTIME_DESIGN.md`·`PARENT_MEDIATED_COLLABORATION_DESIGN.md`의 "explore-only / no nested"는 P2 이전 초안이다
- ✅ **`fable-5-1-multiagent-spec.md`는 Anthropic 공식 문서 기반이다. 프롬프트 블록은 공식 권장 문구를 그대로 쓴다**(2026-09-15 결정)
  - 표현을 바꾸지 않는다. 공식 문서가 측정한 효과는 그 문구에 붙어 있다(예: P-01은 첫 문장이 효과의 핵심이다)
  - 투입 전에 공식 문서의 **현재 문구와 대조해** 스펙 파일의 문구를 맞춘다. 문서가 갱신되면 스펙 파일을 먼저 고친다
  - 삽입한 블록에는 출처 주석(스펙 ID, 예: `P-01`)을 단다 — 나중에 무엇이 공식 문구이고 무엇이 NEOS 문장인지 구별하기 위해서다
  - `coding/prompts/builder.py` 독스트링의 "제3자 시스템 프롬프트를 붙여넣지 않는다"는 **Claude Code·Hermes 등의 프롬프트 본문**에 대한 규칙이다. 모델 제공사의 공식 권장 문구에는 적용하지 않는다. PLAN_260913 §2.1의 복붙 금지도 같은 범위다
  - 그대로 쓴다고 해서 측정이 면제되지는 않는다. 블록 하나 = 표본 경계 하나(§8 행 11)

---

## 11. 남은 것 — "무엇을 기다리는가"로

| 기다리는 것 | 항목 |
|---|---|
| **사람의 손** | 🔴 **Anthropic API 사용 한도 소진**(2026-10-03, 2026-11-01 00:00Z 해제) — 한도를 올리거나 기다린다. 그 전까지 라이브 표본·dry run 불가(D107) · ~~① #23 을 한 번 돌린다~~ ✅ #23·#24 완료(2026-10-03, D102~D104) · ② **Jev 섀도·집행 가동** — `make dev-jev-enforce`(L3 게이트·Q5b 멈춤·L6, 잠정 경계) 또는 `make dev-jev-shadow`(섀도만)로 띄우고 켠 날을 적는다. 쌓이면 `make jev-shadow-report SINCE=<켠 날>` 로 **잠정 경계를 실측값으로 바꾼다**. 호출당 0.4~0.6 초가 붙는다 · ③ **Jev 가격** — 🔴 **공식 페이지에 가격이 공개돼 있지 않다**(2026-10-03 사용자 확인). 사용자가 추후 알려 주면 `models.yaml` 에 등재한다(L0 잔여). 그때까지 L6·L3·Q5b 의 Jev 호출 비용은 원장 지출에 잡히지 않는다 — 지출 계보를 읽을 때 먼저 적는다 · ④ **Q5b 경계 실측** — 지금 값은 잠정이다. ①·② 는 서로 독립이다 |
| **사람의 결정** | 없음 — 2026-10-03 두 번에 걸쳐 전부 닫혔다(아래 결정 색인) |
| **외부 선행** | **B2 배선**(Q14c 를 켠다 · J production 샌드박스 · **E-S2 의 staging·production**) · **벤더 SDK 바인딩 + 증거 + 실계정 스모크 R1~R11**(Q6c 를 연다) · **트랙 P 테넌트 격리**(Q17) · **W6**(DA 운영 경로 — Q3 를 켠다) |
| **라이브 표본** | ~~CITE1 후보 판별(#23)~~ #23 돌았다(2026-10-03) — **판정 보류**(W-2, D102) · BUDGET2 효과(#24, D101 — #23 과 같은 Jev 판정자, 사전 등록 완료) · D2 효과 · C1 · S2 두껍게 · A3·A4 · M-0 · **C-계열**(J5) · effort 스윕(K5) · **L5 판정자 섀도**(판정 불변, 지출만 움직인다) |
| **결정 뒤 구현할 것** (2026-10-03 2차) | **GS-RET** 대화 삭제 시 그래프 자식 체크포인트·전사 삭제 + 요약 보존(GS6 선행) · **Q3c** 상시 질문 diff 에 `source_url` 짝 + "갱신됨" 분류 · **L7′** Jev 핸들 채널 would-branch 섀도 · **트랙 P org 층** — GEPA overlay·레시피 org 공유, org 별 승인자(기본 org 관리자), Q17 조직 소유 에이전트 · **D102 후속** 버킷 귀속을 클레임 id 단위로 다시 세기 · D2 착지 여부 확인 |
| **새 사전 등록** | M-1 · **J4**(점진 공개 조립) · **C-계열 첫 표본** · D6 개정(DA 조사 경로 브라우저 — **필요해지면** 제안) |
| **새 스펙** | 트랙 F 재개 |
| **재료 없음** | **L4** — 코드는 착지했다. #23 의 원장으로 **사후에** 돈다(L6 이 먼저 켜졌으므로 이제 "켜기 전 근거"가 아니라 "켠 뒤 점검"이다, D99 §3) |
| **측정 없이 못 정함** | `claude-opus-5` 세대 사실(CA12) |
| **규모가 큰 별건** | D3b · D2 · D4 — 전부 W6 이후. **D4는 J가 수요를 만든다** |

**결정됨** — 내용은 각 절에, 경위는 DONE 문서에 있다. 여기는 색인이다.

| 날짜 | 결정 |
|---|---|
| 2026-09-15 | **K3** 비동기 spawn 채택(§5.3) · **J production 샌드박스는 B2 게이트에 묶는다**(§4.5) · **Fable 5.1 공식 문구 그대로 사용**(§10.5) |
| 2026-09-17 | **K1d** `SubagentSpec.thinking` 은퇴 · **J1 이미지 = 분석 번들**(pandas·numpy·pypdf·bs4) · **compose 는 `final_compose` 계약 그대로** · **analyze 는 같은 질문의 verified 만** |
| 2026-09-22 | **D-L1**(§12.4) — unattended 중간대는 **DENY**, Jev 실패·타임아웃은 **정적 정책 폴백 + `jev_unavailable`**. 받아들인 위험: **Jev 가 죽으면 게이트도 없다** → 감시 조건은 `jev_unavailable` 비율 |
| 2026-09-24 | **D-14** 분리(D98) · **D-L2** 쪼갠다 — 질문마다 제 경계, **가장 엄한 결과**, 확률을 합치지 않는다 · **D-L3** WAF 차단(`reason=provider_blocked`)은 **한 단계 좁힌다**, 다른 실패는 D-L1 (§12.12) |
| 2026-09-28 | **CHILD-GATE** 자식의 REQUIRE_APPROVAL 은 **DENY** · **GRADE1** 계산 클레임은 전용 판정 프롬프트 · **J1.5** premises ID 는 다음 라운드 briefing 에 · **research 자식도 계산 클레임**, 전제는 같은 질문으로 채점기가 강제 · **K9** 모드 신호는 태스크 요청 필드(`mode`) · **P-02** 는 autonomous 에만 먼저 · **L2 섀도**는 개발에서(`make dev-jev-shadow`) |
| 2026-09-30 | **Q0** 상시 에이전트를 넣는다, **범위는 dots 전체** · USER_ONLY 는 코드 고정·설정은 늘리기만 · `PAUSED`/`WAITING_USER` 는 쓴다 · Q3 차이 단위 = 클레임, 짝짓기 키 `claim_hash` + 증거 blob · Q5 판정자 = Jev(섀도 먼저) + 폴백 FB1~FB6 · Q13 사용자당 하나, 늘릴 수 있게 · Q16 위협 모델은 지속적 개선 — 전부 [dots 분석 §6](OPENAI_DOTS_ANALYSIS_260930.md). 📌 Q0 은 **D19·D6 을 바꾸지 않았다** |
| 2026-10-03 | **L6** 인용 클레임 판정자 = Jev, #23 부터(D99 — L4·L5 를 건너뛴 위험을 받아들였다) · **D19 개정**(D100) — 자동 후보 생성·자동 롤백 허용, 자동 승격 금지. Q7·GEPA 트랙을 막지 않는다 · **진화 fitness** — Jev·판정자를 **최대한** 쓴다: fitness 의 1차 신호는 Jev 판정과 LLM 판정자다. 결정론 검증기는 **하한(필터)** 으로 남고 `DeterministicGrader` 대체 금지(§9)는 그대로다. ⚠️ 판정자를 향한 보상 해킹은 받아들인 위험 — held-out 세트와 결정론 하한이 감시한다 · **크로스 프로바이더 판정자 허용** — 판정자는 워커와 다른 공급자일 수 있다. 트랙 B 의 "크로스 프로바이더 **폴백** 금지"는 라우팅 축이라 그대로다 · **북극성 일반화**(§3.1) · **테넌트 경계 = user** — 격리 단위·overlay·레시피 공유 범위가 user 다. Q17(조직 에이전트)은 org 단위를 열 때까지 선행 대기 · **D6 유지** — DA 조사 경로 브라우저는 필요해지면 제안(새 사전 등록) · **E-S2·G/H·Q 를 development 에서 켠다**(§1 기본 플래그) · **경계값은 잠정값으로 enforce**(L3·Q5b) |
| 2026-10-03 (2차) | **D-12 = (b)** 동적 합성(G/H)은 **H4 완료 후** DA 라이브 표본 경로에 허용한다 — 그 전에는 표본 경로에 들어오지 않는다. 허용하는 커밋은 §8 의 새 경계다 · **트랙 I 보존 = (c)** 대화를 지우면 그래프가 띄운 서브에이전트 자식의 체크포인트·전사를 지우고 **요약만 남긴다**(GS6 선행) · **P-02 interactive = (a)** autonomous 에서 효과를 잰 뒤 넣는다(§8 행 11 — 잴 지표는 PLAN A1 베이스라인) · **Q3 재표현 = (c)** `source_url` 로도 짝을 짓되 내용 해시가 다르면 **"갱신됨"** 으로 따로 센다 — 새로 검증·사라짐으로 세지 않는다 · **Jev 세 채널 = (a)** 브레이크(도구 위험, 좁히기만) · 계기판(결과 판정 — L6) · 핸들(분기 — **섀도로 would-branch 만 기록**, 채점 경계는 건드리지 않고 지출 경계만) · **조직 단위** — GEPA overlay·레시피를 **org 안에서 공유**, 승인자는 **org 마다 설정**(기본 org 관리자), **조직 소유 에이전트(Q17) 허용**. 격리의 바닥은 여전히 user 이고 org 는 그 위의 **공유·승인 층**이다 — 트랙 P 의 org 경계가 선행이다 |

> **읽는 법:** **표본 없이 되는 코드는 다 썼다.** 트랙 A의 병목은 설정이 아니라 **#23 을 한 번 돌리는 사람의 손**이다.
> J4 는 그 판정 뒤다. L6 은 사람의 결정으로 #23 **앞에** 켰다(D99). 남은 K 는 K5 ⑤ 벤치(키와 지출이 든다)와 프롬프트 층(K9 DA 쪽·K10·K11, 결정 먼저)이다.
> **새 일이 생겼다고 옛 병목이 사라지지 않았다** — 트랙 Q 가 빠르게 착지하는 동안에도 #23 은 그대로다.

### 미해결 인벤토리 (트랙 A 잔여)

| 우선 | ID | 내용 |
|---|---|---|
| 🟡 | **C1** | discard recall 재측정 — 2회 연속 n=0. 라이브 표본 하나 남음 |
| 🟢 | **CE1~CE4** | §5.4로 편입. CITE1 판정(D104) 뒤 **CE ③ 은 J4 로 착지**(D105). 나머지는 한 표본에 하나씩 |
| 🟡 | **A3·A4** | worker/판정자 상한 재보정(thinking 몫 실측 선행 — **K 경계 9와 겹친다**) |
| 🟡 | **ORPHAN2** | 조립기가 없는 클레임 id를 지어낸다. 감시 조건은 가용 verified 대비 인용 비율 |
| 🟡 | **D1**(트랙 A) | search 0건 반환 비율 7% |
| 🟡 | **GRADE2** (2026-09-28) | 필수 심사 여부(`value_est × confidence ≥ agentic_threshold`)의 `confidence` 가 행위자의 자기 보고다(출처 수 cap 으로 상한만 있다). 낮게 보고하면 샘플율만큼만 심사받는다 — 보상 해킹 표면. 질문 `confidence = max(conf, self_assessment)` 도 같은 입력이다. **#23 전에는 건드리지 않는다**(판정 경계). 기록만 |

### 트랙 J·K·L 인벤토리

| 우선 | ID | 내용 | 선행 |
|---|---|---|---|
| 🟠 P1 | **K5** | **⑤ 벤치 러너**(모델별 스윕) | 키·지출 |
| 🟠 P1 | **K9** | P-02 를 interactive 에도 넣는가 — 스펙은 코드를 고치는 모든 에이전트에 걸라고 적지만 그것은 §8 경계 11 의 행 하나다. autonomous 에서 효과를 본 뒤 정한다. DA 워커의 system 은 `"Follow the user instructions."` 한 줄 — 여기 넣으면 DA 전 호출이 바뀌므로 **#23 전 금지** | 사람 |
| 🟠 P1 | **K10** | 배칭 넛지 | K2 ✅ |
| 🟡 P2 | **K8 · K11** | K8: R-08 문구 없음, 카탈로그에 `thinking_budgets` 선언 모델 없음 → `thinking_budget=0`. 발동 조건(`xhigh`/`max`)이 없는 동안 **잠들어 있다** · K11: 코딩 `_tone` 의 `"No play-by-play"` 가 P-07 ② 가 지목한 바로 그 문구다(K4a 상태 줄과도 반대 방향). DA·자식 프롬프트엔 억제 문구 없음 | K8 은 K5 값 뒤 |
| ⚪ | **J4 · J5 · J6** | 조립 · C-계열 표본 · staged 스킬 | #23 판정 · 사전 등록 |
| 🟡 P2 | **L0 잔여** | **가격 하나.** API 가 주지 않고 **공식 페이지에도 없다**(2026-10-03). 사용자가 알려 주기로 했다 | 사람 |
| 🟡 P2 | **L4 측정** | 코드 착지(`scripts/jev_judge_backtest.py`). 로컬 원장에 채점된 클레임 0건 → **#23 원장으로 사후에** 돈다(L6 점검, D99 §3) | #23 |
| 🟢 P2 | **L2 섀도·L3 집행 가동** | 오버레이 둘(`jev-l2-shadow.yaml` · `dev-jev-enforce.yaml`)·판독기·`make` 타깃 착지. `development.yaml`·`config/neos.local.yaml` 에 넣지 **않는다**(CI 키 요구 · 테스트가 진짜 Jev 를 부른다). 경계 0.2/0.9 · 멈춤 0.9 · 판정 0.60 은 잠정값 | 사람(기동) |
| 🟡 P2 | **L3 · L5 · L7** | L3 은 개발 오버레이에서 잠정 경계로 켰다 — 실측으로 바꾸는 것이 남았다 · L5 는 L6 이 먼저 켜져 의미가 "섀도"에서 "두 판정자 대조"로 바뀐다(L4 사후 백테스트가 대신한다) · L7 분기 이전 후보 | L2 실측 · #23 원장 |

> ⚠️ **ID 충돌 주의.** 트랙 A의 D1·D2(검색·retrieval 결함)와 트랙 D의 D1~D4(프레임워크 이탈)는 다르다.
> PLAN_260913의 G1~G12·A1~A5·B1~B5도 이 문서의 트랙 G·A·B와 다르다. **K5는 PLAN G10을, K9는 G11을 흡수한다.**
> 트랙 Q 설계 문서들의 D·S·M·W·B 결정 ID 도 이 문서의 것과 다르다.

---

## 12. 트랙 L — Jev 확률 판정 층

> **상태 (2026-09-24): L0·L1 실측 끝 · L2 착지와 durable 루프 배선 끝 · L4 코드 착지(재료 없음) · D-L1~D-L3 닫힘 ·
> L3·L5~L7 은 설계.** 전부 플래그 off. 착지 경위·실측 전문은 [DONE §3](DEEP_ANALYSIS_HARNESS_DONE.md).
> 이 절은 **설계·불변식·남은 단계**다 — 설계와 코드가 어긋나면 코드가 이긴다.
>
> 착지한 것: `neos/jev/`(밴딩·게이트·루브릭·SDK 어댑터·키 해소·`claim_judge.py`·`assembly.py`) · `JevConfig` ·
> `scripts/jev_probe.py` · `scripts/jev_judge_backtest.py` · `scripts/jev_l2_shadow_report.py`.
> ⚠️ `jev.judge_shadow_enabled` 는 스키마에만 있고 **읽는 코드가 없다**(§1 기본 플래그)

### 12.1 무엇을 사는가 — 그리고 무엇을 사지 않는가

`jev`는 사고하지 않고 **확률을 낸다**. 호출은 하나다.

🔴 **패키지 이름.** 진짜 SDK 는 **`typesafe-sdk`** 다(설치·확인: `0.7.1`, 2026-09-22).
`typesafe-ai` 는 **모델이 지어내는 이름을 선점당하지 않으려고 등록된 리다이렉트 shim** 이고
기능이 없다 — 그 패키지의 메타데이터가 직접 그렇게 적고 있다. 이름을 기억에서 꺼내 쓰면
L0 이 막으려던 실패를 L0 에서 저지른다.

```python
response = await client.system_one(      # AsyncTypeSafeClient. state·questions 는 위치 인자
    {"uid": f"{rubric_digest}:{token_hex(4)}", ...},   # 판단 대상. uid 는 SDK 계약이 아니라 관례
    questions,                                          # Mapping[str, Question] — 파일에서 온다
    model=model,                                        # 해소된 id. 기본값은 `jev-latest` 다
)
```

**응답형은 둘이 아니라 셋이다**(설계는 둘이라고 적었다 — 코드가 이긴다).

| 형 | 반환 | NEOS 에서 쓰는 곳 |
|---|---|---|
| **Noul** | `NoulAnswer.noul` — `P(true)` 스칼라 | 도구 위험 밴딩(L2·L3) — "이 호출이 파괴적인가" |
| **Choice** | `probabilities` 분포 + 뽑힌 `choice` + **`confidence`** | 판정 밴딩(L4~L6) — 배타 라벨이 필요한 곳 |
| **Score** | 정수 점수별 `probabilities` + `legend` | **아직 쓰는 자리 없음.** 순서 루브릭이 필요해지면 여기다 |

`ChoiceAnswer.confidence` 가 이미 있으므로 **top-p 를 직접 구하지 않는다** — §12.4 의
"Choice 는 top-p `<0.60`" 은 그 필드를 읽는 것으로 족하다.

⚠️ **`models.list()` 는 가격을 주지 않는다** — 이름·설명·출시일뿐이다. 그래서 L0 의
카탈로그 등재는 스크립트 출력만으로 끝나지 않고, 가격은 계정 청구 정보에서 사람이
가져와야 한다(§13-B "모든 모델은 가격을 가진다"와 "추측하지 않는다"가 여기서 만난다).

> 🔴 **쿡북이 파는 것은 반복가능성이지 정확도가 아니다.** Choice 쿡북이 스스로 적었다 —
> "Haiku at temperature 0 showed 100% consistency here, demonstrating that high agreement
> doesn't guarantee correctness." 그래서 L4 의 산출물은 **일치 행렬**이고, 정확도는 정답키가
> 있는 부분집합에서만 말한다(트랙 F 가 남긴 채점기·정답키·기준선은 재사용 가능하다).

### 12.2 두 제약이 이 트랙의 모양을 정한다

**① Jev 는 결정론이 아니다.**

쿡북이 파는 수치는 질문별 확률 표준편차 `0.0102` 이고 **0 이 아니다.** §3.2 의 S5(스위트가
결정론적으로 통과)와 §4.3(비결정적 스크립트는 거절한다)에 정면으로 걸린다.

> 🔴 **`DeterministicGrader` 는 어떤 측정 결과가 나와도 교체 대상이 아니다.**
> 출처 무관 · 문자 그대로 대조 · 재실행 가능 — 이 셋이 §2.2 비대칭의 받침점이다.
> Jev 는 **이미 비결정성을 허용하는 두 자리**에만 들어간다: 승인 게이트와 `AgenticGrader`.

테스트는 카세트로 고정한다(`cassette_model.py` 와 같은 방법). 실호출이 도는 테스트는 스위트에 없다.

**② 단조 축소(monotone narrowing).** §9 "샌드박스 ≠ 승인 생략"의 확장이다.

```
정적 정책(denylist · allowlist · phase 규칙) ──▶ 결과 R₀
                                                 │
                                R₀ == DENY  ─────┴──▶ 끝. Jev 를 부르지 않는다
                                R₀ != DENY  ──────▶ Jev 밴딩 ──▶ R₁ ∈ {R₀, 더 좁은 것}
```

**Jev 는 `DENY → ALLOW` 전이를 만들 수 없고 `REQUIRE_APPROVAL → ALLOW` 도 만들 수 없다.**
좁히는 방향으로만 작동한다. 그리고 **변이 테스트로 무는지 확인한다** — §14 의 "무는지 보지 않고
세운 게이트는 없느니만 못하다"이고, K2b 의 부분 문자열 단언이 정확히 이 자리의 함정이었다.

### 12.3 어디에 꽂는가 — 구멍은 이미 파여 있다

| 자리 | 기존 코드 | Jev 가 더하는 것 |
|---|---|---|
| 도구 위험 | `ToolRisk`(4값) · `ApprovalPolicyOutcome`(`ALLOW`/`DENY`/`REQUIRE_APPROVAL`) | 정적 정책이 `DENY` 를 내지 **않은** 호출에만 Noul 밴딩을 얹는다 |
| DA 워커 도구 | J1·J1.5 가 연 표면(`fetch.v1` · `execute.v1` · `write_file`) | **DA 전용 판정 경로를 새로 만들지 않는다.** 코딩 자식은 같은 게이트를 탄다(CHILD-GATE). ⚠️ **이 원칙과 어긋나는 곳 하나 — 기록한다:** 조사 게이트(`research_gate.py`)는 `approvals.py` 가 아니라 **DA 쪽 판정**이다. 조사 자식에게는 사람 승인자가 없고, 그 규칙은 승인 정책이 아니라 **재현 조건**(재실행기가 똑같이 다시 돌릴 수 있는가)이다. 코딩의 정적 정책을 태우면 기본 manual 모드에서 `execute` 가 REQUIRE_APPROVAL → DENY 로 접혀 조사 자식이 아무것도 못 돌린다. 대가: **Jev 밴딩을 얹을 자리가 조사 쪽에는 아직 없다** — 얹는다면 `ResearchGate.authorize` 가 한 자리다 |
| 판정 | `AgenticGrader` (judge `claude-opus-4-8`) | Choice 밴딩. **L6 전에는 섀도**, 원장 판정은 바뀌지 않는다 |

세 자리 모두 **호출부가 하나여야 한다.** 승인 판정이 만들어지는 자리는 `neos/coding/domain/approvals.py`
한 곳이고, 반환부가 아니라 **판정이 만들어지는 자리**에 건다 — K6 에서 도구 결과 매핑이 둘이었고
한쪽만 고쳐졌던 것과 같은 실수를 반복하지 않는다. **사본을 먼저 센다.**

### 12.4 밴드와 중간대 — ✅ D-L1 결정 (2026-09-22)

쿡북의 기본값은 Noul `<0.30 → no` / `>0.70 → yes` / 사이는 사람, Choice 는 top-p `<0.60 → uncertain` 이다.
**그 숫자를 그대로 쓰지 않는다** — §9 "매직넘버 금지, 전부 settings"이고, 기본값은 L1·L2 **실측**에서 정한다.

정해야 하는 것은 숫자가 아니라 **중간대에서 무엇을 하는가**다. 세 경우가 서로 다른 답을 원한다.

| 경우 | 결정 | 상태 |
|---|---|---|
| 대면 런(사람이 있다) | `REQUIRE_APPROVAL` 로 올린다 | ✅ |
| **`unattended=True` 런** | **중간대는 DENY 로 접는다.** 승인할 사람이 없는 런에서 "사람에게 묻는다"는 답이 아니다 | ✅ 2026-09-22 |
| **Jev 호출 실패·타임아웃** | **정적 정책 결과(R₀)로 폴백한다** + `jev_unavailable` 이벤트 | ✅ 2026-09-22 |
| **프로바이더 앞단(WAF)이 요청을 막음** | **중간대처럼 한 단계 좁힌다** + `jev_unavailable(reason=provider_blocked)`. 대면=`REQUIRE_APPROVAL` / unattended=접기가 `DENY` | ✅ 2026-09-24 (D-L3) |

**두 결정이 반대 방향으로 보이지만 같은 규칙에서 나온다** — §12.2 ② 단조 축소다.

| Jev 의 상태 | 좁힐 근거 | 결과 |
|---|---|---|
| 대답했고 확신한다 | 있다 | 밴드대로 좁힌다 |
| 대답했는데 애매하다(중간대) | **있다** — "애매하다"는 정보다 | 대면=`REQUIRE_APPROVAL` / unattended=`DENY` |
| 대답하지 않았다(실패·타임아웃) | **없다** | 축소량 0 → `R₀` 가 그대로 선다 |
| 막혔다(WAF) | **있다** — 요청에 공격 페이로드처럼 보이는 문자열이 있었다. 그리고 그 문자열은 **공격자가 넣을 수 있다** | 중간대와 같다 |

폴백의 최악은 **"Jev 도입 이전"이지 "정책 없음"이 아니다.** 정적 정책이 `DENY` 를 낸 호출은 애초에
Jev 를 부르지도 않으므로(§12.2 ②) 폴백이 그것을 여는 경로는 존재하지 않는다.

> ⚠️ **이벤트 없는 폴백은 금지다**(§9). `jev_unavailable` 을 남기지 않으면 "조용히 바뀌는 것이
> 시끄럽게 깨지는 것보다 위험하다"의 재발이다. S12 가 이것을 출하 기준으로 세운다.
>
> 🔴 **이 결정이 만드는 긴장 — 문서가 먼저 말한다.** 가용성 폴백은 곧 **"Jev 가 죽으면 게이트도
> 없다"** 는 뜻이다. 중간대 DENY 는 Jev 가 대답할 때만 작동하므로, Jev 를 못 부르게 만드는 것이
> 게이트를 여는 가장 싼 방법이 된다. 이 트랙에서 이것은 **받아들인 위험**이고, 대신 감시 조건을
> 둔다 — L3 을 켠 뒤 `jev_unavailable` 비율이 **L2 섀도 기간의 그것보다 올라가면** 밴드를 만지기
> 전에 **가용성부터 본다.** (비율의 절대 수치는 적지 않는다. L2 가 그 기준선을 만든다.)
>
> ⚠️ unattended DENY 는 **시끄러운 실패**다. 거절 사유가 사용자에게 닿아야 한다(S6의 정신) —
> 거절 이벤트에 밴드·확률·루브릭 digest 를 싣는 것이 S13 이다.

### 12.5 단계 — 전부 플래그 off 로 착지한다

| 단계 | 내용 | 선행 | 표본 필요 |
|---|---|---|---|
| ~~**L0**~~ 🟢 | 실측 완료(2026-09-22) — `jev-1.13.0` · 패키지 `typesafe-sdk` · 응답형 셋. ❌ **가격 하나**가 남았다 — `models.yaml` 등재의 유일한 선행. 공식 페이지 미공개(2026-10-03), 사용자가 추후 제공 | 키 | 없음 |
| ~~**L1**~~ 🟢 | 착지 + 기준선 실측(2026-09-22) — `neos/jev/scorer.py`. 해소된 id 는 보낸 값이 아니라 **응답의 `model`**(S13). 기준선은 §12.7 | L0 | 없음 |
| ~~**L2**~~ 🟢 | 착지 + durable 루프 배선(2026-09-23) — `_evaluate_call` 3개 호출부 전부, 원장은 `deps.events.append`. D-L1 순서는 `fold_for_unattended` 재사용. ⚠️ **투기적 prefetch·읽기 전용 배치는 게이트가 차단 중이면 포기한다** — 판정 전에 실행하므로 Jev 를 앞지른다. **남은 것: 섀도 가동**(§11) | L1 | 없음 |
| **L3** | **게이트 켜기(실제 차단).** 밴드는 settings. 적용 순서는 development 코딩 루프 → DA 코딩 워커(J1 표면) → staging. **production 은 B2 게이트와 같은 줄에 선다** | L2 불일치 **건별** 리뷰 | ✅ (경계 16) |
| **L4** | **Jev-as-Judge 오프라인 백테스트.** 저장된 원장의 과거 클레임에 Choice 루브릭을 돌려 `AgenticGrader` 판정과 대조한다. D92 재현 게이트와 같은 이유로 **표본 경계가 아니다**. 🟡 코드 착지(2026-09-23) — **잴 원장이 없다**(§12.11). #23 의 원장이 첫 재료다 | L1 · 원장 | 없음(저장 원장) |
| **L5** | **판정자 섀도(라이브, 기록만).** 두 판정자를 모두 돌리되 **원장의 판정은 여전히 `AgenticGrader`** 다. 비용·레이턴시 실측 — 이것이 "싼 판정자" 주장의 유일한 근거가 된다 | L4 | ✅ (판정 불변, **지출 계보에는 경계**) |
| ~~**L6**~~ 🟢 | **판정자 교체 — 착지·켜짐(2026-10-03, D99, [DONE §3.8](DEEP_ANALYSIS_HARNESS_DONE.md)).** 인용 클레임 = Jev Choice, 계산 클레임·Jev 미응답 = LLM 판정자. §8 경계 3 과 같은 등급. 📌 사람의 결정으로 L4·L5 와 #23 판정을 **앞질렀다** — 받아들인 위험은 D99 §3 | ~~L5 · #23 판정~~ 사람의 결정 | ✅ (경계 17, 새 계보 — #23 부터) |
| **L7** | 하드코딩 분기 → Jev 밴드 이전 **후보 목록만** 만든다. 각 후보는 별도 사전 등록 | L3 | 후보별 |

~~**L6 을 #23 뒤에 두는 이유는 J4 와 같다.** 원인 판별 전에 가장 매력적인 처방을 먼저 넣으면
D40·D51 의 반복이다 — **원인을 모르는 채 고친다.**~~ → 2026-10-03 사람의 결정으로 L6 을 앞당겼다(D99).
이 경고는 지우지 않는다 — #23 을 읽을 때 "판정자가 바뀐 표본"이라는 사실이 이 문장의 형태로 돌아온다.

### 12.6 Jev 로 옮기지 않는 것 (L7 의 경계)

L7 이 후보로 볼 수 있는 것: `skill_selector` 의 스킬 선택 · `conflict` 의 충돌 판정 ·
라운드 계속/중단 · 서브질문 승격. **후보일 뿐이고 각각 별도 사전 등록이다.**

옮기지 않는 것은 **결정론이 계약인 자리**다.

- ❌ `DeterministicGrader` — §12.2 ①
- ❌ 인용 게이트의 분모(§8 경계 4 가 백테스트로 무효화된 그 분모)
- ❌ `TokenBudget` 클램프·예산 산식 — 확률이 개입하면 floor 산식이 성립하지 않는다
- ❌ `ComputedEvidence` 재실행 대조(§4.3) — "가끔 재현된다"는 verified 가 아니다

---

### 12.7 L1 일관성 기준선 — 실측 (2026-09-22)

15회 × 고정 루브릭(`tool_risk`, digest `f5faf377…`) × **신선한 uid**, `jev-1.13.0`.
원본: `artifacts/jev-probe/<ts>/report.json`.

| 대상 | mean | **stdev** | min~max |
|---|---|---|---|
| `git push --force origin main` (극단) | 0.939 | **0.0035** | 0.93~0.94 |
| `rm -rf node_modules` (중간대) | 0.630 | **0.0242** | 0.59~0.67 |

🔴 **이 두 줄의 차이가 이 트랙에서 가장 중요한 수치다.**

**① 쿡북의 `0.0102` 는 NEOS 의 기준선이 아니다.** 중간대에서 우리 값은 그
**2.4배**다. 들여왔다면 밴드를 2배 이상 좁게 잡았을 것이다.

**② 극단에서 잰 표준편차는 기준선이 못 된다.** 확률은 0·1 근처에서 자연히
압축되므로 극단 대상은 중간대 변동의 **1/7** 만 보여 준다. 첫 측정이 정확히
이 함정에 빠져 있었다(대상 주석이 "중간대를 겨냥한다"고 **거짓을 적고** 있었다
— 실측이 그것을 반증했다). §14 "계측을 먼저 의심한다".

**③ 밴드 임계값은 실제 대상이 몰리는 곳에서 떨어뜨려야 한다.** 중간대 대상의
범위가 `0.59~0.67` 이므로, **그 구간 안에 임계값을 두면 같은 호출이 실행할
때마다 밴드를 넘나든다.** 재현되지 않는 게이트는 게이트가 아니다.

> ⚠️ 이것은 **두 대상**의 측정이다. 밴드를 정하려면 L2 섀도가 실제 호출 분포를
> 보여 줘야 한다 — 위 세 결론은 "어디에 두면 안 되는가"를 말하지 "어디에 두라"를
> 말하지 않는다.

초안 루브릭(단일 질문 `destructive`)의 변별력 측정은 [DONE §3.2](DEEP_ANALYSIS_HARNESS_DONE.md) — 결론은 "가르지만,
되돌릴 수 없는 위험과 **나가서는 안 될 것이 나가는** 위험을 한 덩어리로 뭉친다"였고 그것이 D-L2 로 이어졌다(§12.11 ①).

### 12.8 배선이 드러낸 것 (2026-09-23)

경위는 [DONE §3.3](DEEP_ANALYSIS_HARNESS_DONE.md). **남긴 규칙:**

- 판정 이벤트는 **코딩 원장**에 간다 — 코딩 fixture(§12.9)를 거친다
- `enforce` 일 때 투기적 prefetch·읽기 전용 배치는 **포기한다** — 최적화보다 게이트가 먼저다. 섀도에서는 그대로 둔다
- 판정 이벤트는 `tool_call_id` 를 싣는다 — 중복은 개수가 아니라 이름으로 드러난다
- payload 는 JSON 이어야 한다(인메모리 저장소는 enum 을 받아 주고 진짜 원장에서 터진다) — 직렬화 테스트
- "밴딩 → 접기 → `would_be_outcome` 보정" 순서의 **구현은 하나**다. 루프는 `static_evaluator` 인자로 같은 함수를 쓴다
- 조립은 루브릭 질문과 `jev.question_thresholds` 키가 **정확히** 같지 않으면 거절한다(`neos/jev/assembly.py`) — 말없이 고르기 금지

### 12.9 코딩 스트림 짝 규칙 (2026-09-23)

코딩 원장 kind 는 `tests/fixtures/coding_event_kinds.json` 에 있고 백엔드(AST)·프론트 양방향 테스트가 문다. 짝 규칙이
드러낸 구멍 여섯(Jev 둘 · `model.refused` · `subagent.*` · `run.*` · `workspace.user_edit.*` · **그리는 컴포넌트가 0개였던
`thinkingStatus`**)과 백엔드 구멍(종결 `subagent.*` 에 `parent_id` 없음)은 [DONE §3.4](DEEP_ANALYSIS_HARNESS_DONE.md).
스냅샷과 라이브는 **디코더 하나**로 판정을 읽는다. 표본 경계 아님.

### 12.10 판정 문장과 재접속 (2026-09-23)

판정 이벤트는 `banded_outcome`(접기 **전**)과 `unattended` 를 함께 싣는다 — 없으면 "Jev 가 좁혔다"와 "unattended 접기가
DENY 했다"를 원장이 가르지 못한다(S13 의 빈칸). 문장은 Jev 가 한 일(`static → banded`)과 접기가 한 일(`banded → would_be`)을
따로 말한다. 옛 이벤트는 `would_be_outcome` 으로 읽는다. 경위: [DONE §3.5](DEEP_ANALYSIS_HARNESS_DONE.md).

### 12.11 D-L2 의 재료 · WAF · 빈 원장 · Docker 경로 (2026-09-23)

표와 경위: [DONE §3.6](DEEP_ANALYSIS_HARNESS_DONE.md).

- **① D-L2 재료** — 쪼갠 질문(`irreversible` · `exfiltration`)이 뭉침을 풀고, 🔴 단일 질문의 **맹점**을 잡는다:
  `cat ~/.aws/credentials` 를 단일 `destructive` 는 **0.10**(낮은 밴드), `exfiltration` 은 0.61 로 본다. 잡음은 같은 급
- **② WAF** — TypeSafe 앞단 WAF 가 `/etc/passwd` 가 **들어간** 요청 본문을 403 으로 막는다. 막는 것은 의도가 아니라 문자열이다 →
  공격자가 호출 단위로 게이트를 끌 수 있었다. 루브릭 문구에 그 문자열이 있으면 **그 루브릭의 모든 호출**이 막힌다 → D-L3
- **③ Docker 경로가 계약 §3.2 를 지킨다** — `/evidence` 는 진짜 읽기 전용(되읽어 확인), `DENY_ALL` 이면 `--network none`, 만족할
  수 없는 profile 은 만들기 전에 `profile_unsupported:*`. ⚠️ **아직 사실이 아닌 것:** managed provider 는 생성 시 profile 을
  `offline-v1` 로 고정해 원장의 `research-offline-v1` 과 이름이 다르고 증거를 워크스페이스에 쓴다 · memory provider 는 둘 다 없다 ·
  `evidence_readonly` 가 원장에 없다 · `read_file.v1` 이 `fetch.v1` 이 준 절대 경로를 거절한다 · 16 MiB 넘는 blob 은 원장 커밋
  **뒤에** 실패한다
- **④ L4 — 코드는 섰고 잴 것이 없다.** 로컬 원장에 채점된 클레임 0건, `artifacts/deep-analysis-funnel/` 이 디스크에 없다(§10.2 의
  "재생성 불가"가 현실이 됐다). D92 재현 게이트의 면역은 **원장이 있을 때의 이야기**다

### 12.12 D-L2 · D-L3 닫힘 — 쪼개고, 막히면 좁힌다 (2026-09-24)

- **D-L2 = 쪼갠다.** 기본 루브릭 `tool_risk_split`. **합치는 규칙을 두지 않는다** — 질문마다 제 경계(`jev.question_thresholds`,
  기본값 없음)로 단조 축소를 한 번씩 적용하고 가장 엄한 결과를 취한다. 어떤 조합도 R₀ 보다 느슨해질 수 없고(S11 을 질문마다)
  max·noisy-OR 같은 새 상수가 생기지 않는다. 대답에 질문이 하나라도 빠지면 LOW 로 읽지 않고 판정하지 않는다
- **D-L3 = WAF 차단은 좁힌다.** "요청 id 없음 + HTML 본문" 403 **두 신호를 다** 요구해 `JevProviderBlocked` 로 분류하고 중간대처럼
  다룬다(잘못된 키를 차단으로 읽으면 키를 잃은 배포가 모든 호출에 승인을 요구한다). 타임아웃·잘못된 키는 D-L1 그대로 R₀
- 🔴 **받아들인 것:** 공격 문자열이 정당한 호출에도 섞일 수 있다 — 대면이면 승인, unattended 면 거절을 받는 **거짓 양성**이다.
  감시 조건은 `reason=provider_blocked` 비율. 인코딩해서 WAF 를 피하는 길은 **재지 않아** 택하지 않았다
- **루브릭 문장도 검사한다** — `tests/jev/test_rubric_waf_safety.py` 가 **요청에 실리는** 질문 텍스트에서 트리거를 찾는다
- ⚪ **남은 것:** 질문별 경계 **값**(L2 섀도 실측이 정한다) · 가격 하나 · L3 을 켜는 결정은 L2 불일치의 건별 리뷰 뒤

---

## 13. 트랙별 한 줄 — 어디를 읽어야 하는가

### A. 심층분석 하네스
라운드 루프는 동작한다. 문제는 마지막 줄(리덕션 → 조립 → 게이트)이다. W1·W2·W3(열두 갈래) 완료,
남은 것은 W4 일부와 W6(승격). 상세: 압축본 §3·§8.

### B. 역할 기반 모델 라우팅 — 반드시 유지할 불변식
- 해석 우선순위: **user → conversation → feature override → role default**
- 역할 매핑(2026-09-28, `neos/config/schema.py` `ModelRoutingConfig` 기본값): anthropic `everyday=claude-sonnet-5` / `powerful=claude-opus-5-5`, openai `everyday=powerful=gpt-6-sol`(`gpt-5.6-*` 는 2026-09-24 은퇴)
- DA 역할: `scout=everyday` · `dig=powerful` · `synth=powerful` · `judge=everyday`(오버라이드로 `claude-opus-4-8`)
- 경계마다 한 번만 해석 · ❌ 크로스 프로바이더 폴백 · ❌ 요청마다 LLM 난이도 분류 · ✅ 모든 모델은 가격을 가진다
- ✅ 크로스 프로바이더 **판정자**는 허용된다(2026-10-03) — 판정자 선택은 라우팅 사슬이 아니다. Jev 는 여전히 사슬에 들어가지 않는다(§9)
- **effort는 모델과 같은 해석 사슬을 탄다**(K5) — 따로 사슬을 만들면 "고침은 한 호출부에만"이 재발한다

### C. 프론트엔드
어휘는 `tests/fixtures/deep_analysis_event_kinds.json` 한 파일, 백엔드는 AST로 훑어 일치를 주장, 면제는 양방향.
코딩 스트림도 같은 규율이다 — `tests/fixtures/coding_event_kinds.json`(§12.9).
챗 SSE 도 같은 규율이다 — `tests/fixtures/chat_stream_event_types.json`(2026-09-27). 백엔드는 `*Event` 클래스 **인스턴스화**를 AST 로
훑는다(`type` 이 `Literal` 기본값이라 문자열 grep 으로는 안 잡힌다).
`frontend-ci.yml`에 `paths: [web/**]`를 넣지 말 것. 📌 되돌리지 말 것: ~~프록시 라우트에 POST 없음~~ **이벤트** 프록시 라우트에 POST 없음
(2026-09-27: 재개는 **별도** 라우트 `deep-analysis/[runId]/resume` 이고 사람이 누른 버튼만 부른다 — 호출부를 이름으로 고정한
`deep-analysis-resume.test.tsx`. 재개된 run 의 이력은 `job_failed → job_resumed → …` 이라 **종결은 마지막 종결이다** — 백엔드
스트림과 프론트 훅 둘 다) ·
모르는 kind도 커서 전진 · `Record<CounterKey, …>`. **J·K·L이 만드는 kind는 이 fixture들을 거친다** — DA 원장이면 DA fixture, 코딩 원장이면 코딩 fixture.

### D. 프레임워크 이탈
```
D3a crewai 삭제 ──> ✅
D1 콜렉터 탈-LangChain ──> D1 루프·코딩 확장 ──┐
D2 스킬화 ────────────────────────────────────┼──> D4 네이티브 전환(전송만) ──> D3b langgraph 제거
```
D3b는 D4의 결과다. citation은 스킬화하지 않는다.

### E. 코딩 에이전트
플랜 14개 완료, E-S2만 남았고 배포 결정이다. 잔여 스트림 정본은 [PLAN_260913.md](PLAN_260913.md).
**J는 E의 루프·샌드박스·서브에이전트를 재사용한다 — 새로 짓지 않는다.** B2 managed provider 게이트는
[재검토 §8.2](MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md) · [B2 설계](MANAGED_SANDBOX_B2_DESIGN_260915.md).
(2026-09-28 코드 대조) E 쪽에 J 가 기대는 구멍이 둘 있다. 정본은 PLAN_260913 이지만 J 의 선행이므로 여기에도 적는다.
- **VERIFY verdict 를 아무도 읽지 않는다.** `state.verdict` 는 codec 직렬화에만 쓰인다. FAIL 이 재진입·재계획·에스컬레이션을 부르지 않는다. 코딩 태스크에는 `DeterministicGrader` 에 해당하는 결과 라벨이 없다
- **Docker·managed 세션에는 `clone_with_workspace` 구현이 없다.** 그래서 쓰기 자식(implement)이 격리 없는 memory 세션에서만 돈다

### E′. 자기개선 — GEPA (포인터만, 2026-09-28)
`neos/gepa_opt/` 는 **착지한 코드**다(커밋 `99d05697`~`403aeb77`, 8개). 코딩 overlay 하나를 staged → 사람 승인 → 주입하는 구조이고, 기본 off 다.
그런데 이 정본은 지금까지 그 존재를 적지 않았다. 운영 호출자는 없다 — evaluator 등록 0 · run 생성 0 · `approve` 호출 0.
held-out test 점수는 기록만 하고 staged 를 막지 않는다(설계가 고른 동작이다 — GEPA 문서 Risks. 게이트로 쓸지는 다시 열 문제다). ✅ 2026-10-03: D19 개정(D100)과 fitness 정책(Jev·판정자 최대 사용)이 정해져 **트랙으로 세울 수 있다** — 아직 세우지 않았다(새 스펙이 먼저다).
정본은 [GEPA_SELF_IMPROVEMENT_MIGRATION.md](GEPA_SELF_IMPROVEMENT_MIGRATION.md), 레시피 관점은 [AGENT_RECIPE_DISTILLATION_260927.md](AGENT_RECIPE_DISTILLATION_260927.md).
> F 와의 차이: F 는 **진단자가 제안**했고, GEPA 는 **평가기가 선택**한다. F 를 닫게 만든 실패는 GEPA 에 그대로 옮겨 오지 않는다. 다만 평가기가 없으면 GEPA 도 같은 자리에 선다.

### F. 개선 루프 서브에이전트화 — 닫혔다
진단자가 표본을 읽지 않고 한 이야기를 반복했다(11개 중 10개에서 3/3 같은 라벨). 채점기·정답키·기준선은
재사용 가능. **자동화가 보존해야 하는 넷:** 표본은 한 번 · 사전 등록이 먼저 · 계측을 먼저 의심 · 배달물을 잰다.
> J의 analyze 자식은 F의 진단자가 **아니다** — 원장을 고치거나 프롬프트를 제안하지 않는다.

### G. 그래프 계약·검증
노드 N이 키 K를 `requires`하면 START→N의 **모든 경로**에 K를 쓰는 노드가 있어야 한다.
`requires` 검증은 하한만이고 오늘 그 하한은 공허하다(`_create_initial_state`가 58개 키를 채운다).
**낡은 면제 플래그는 가드를 조용히 끈다** — 양방향 테스트.

### H. 플러그인 런타임
네 층을 묶는 계약(H2)과 조립 원장(H1 ✅). H3(설계 그래프)는 development 에서 켜졌다(2026-10-03). 남은 긴장 ㉰는 통계 문제(run당 6개로 층화 불가) → D-12.

### I. 서브에이전트 노드 그래프
[설계](GRAPH_SUBAGENT_INTEGRATION_DESIGN.md) · K25′(D97) · 마이그레이션 058. 1-step 법, 걸음 상한 `2·max_turns + 1`
(핸들러가 강제), 체크포인터 없는 경로에서는 조립 안 함, 보고는 unverified 검색 결과, 병렬 조인은 `defer`.
GS3 어휘만 · GS6 표본 전. ⚠️ 템플릿 없는 설계도 병렬 가지가 리듀서 없는 키를 같이 쓰면 run이 죽는다(별도 사전 등록).

### J. 코딩 루프 조사 — §4
### K. Fable 5.1 적응 — §5

### L. Jev 확률 판정 층 — §12
확률은 **좁히는 방향으로만** 쓴다. 정적 정책이 `DENY` 를 낸 호출에는 Jev 를 부르지 않고,
Jev 가 `ALLOW` 로 되돌리는 경로는 없다. 📌 되돌리지 말 것: `DeterministicGrader` 는 대체 대상이 아니다 ·
임계값·루브릭 digest 없는 판정 이벤트 금지 · 역할 라우팅 사슬(B)과 섞지 않는다.

### Q. 상시 에이전트 (포인터만, 2026-09-30)
OpenAI dots(2026-09-29)를 코드와 대조한 결과로 세운 트랙이다. **Q0 결정(2026-09-30): 범위는 dots 전체**(Q0~Q18).
뿌리는 **Q13 에이전트 개체**(태스크보다 오래 사는 1급 객체). 순서는 **가드가 능력보다 먼저**였고, 2026-10-02 까지 가드
(Q1·Q2·Q5·Q10)와 능력 대부분(Q3·Q4·Q6·Q11·Q13·Q14·Q16)이 플래그 off 로 착지했다 — [DONE §7](DEEP_ANALYSIS_HARNESS_DONE.md).
📌 L 과 같은 방향: 모드·사용자 규칙·확률은 **좁히기만** 한다. 사용자 allow 는 기본 정책의 DENY 를 뒤집지 못한다.
상시 런은 **라이브 표본이 아니다**(§8). 정본은 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md).
> ⚠️ ID 주의: 트랙 M·N·O·P 는 [분석 문서 §7.1](NEOS_MOMENTUM_ANALYSIS_20260928.md)이 이미 제안했다. Q0~Q18 은 이 트랙의 것이다.
> 📌 되돌리지 말 것: USER_ONLY 를 설정으로 **빼는** 경로 · 사용자 allow 가 기본 DENY 를 넘는 평가 순서 · `PAUSED` 를 사람 아닌 것이 푸는 경로 · Jev 가 **재개**시키는 경로(감시자는 멈추게만) · 에이전트에 딸린 데이터를 `user_id` 로 키잡기 · 무인 런의 기기 쓰기·명령(Q16) · 증거 없이 관리형 공급자에 비밀 채널 열기(Q6c) · 비밀 푸는 호출을 배치·프리페치로 앞지르기(Q11 M13).

---

## 14. 이 루프가 자기 자신에게서 배운 것

- **계측을 먼저 의심한다.** 자가 지표가 세 번 틀렸다. 루프는 틀린 지표에 성실하게 수렴한다.
- **계측기가 도는지 보는 것은 실패해야 할 때 실패하는지 보는 것이다.** `after <= before`는 버그를 되살려도 통과했다.
  자식의 `thinking="off"` 를 지킨다는 단언도 같은 모양이었다 — 읽는 속성이 없어 **언제나** 통과했고,
  "자식은 생각하지 않는다"는 거짓이 카탈로그에 그대로 남았다(K1d).
- **무는지 보지 않고 세운 게이트는 없느니만 못하다.** 변이로 확인한다.
  K2b 에서 **내가 그 함정을 직접 팠다.** 공개를 확인한다는 단언이
  `REVEALED in str(payload["messages"])` 였는데, 그 이름은 **검색 결과 안에 이미 있었다** —
  공개가 하나도 없어도 통과한다. 초록을 증거로 커밋할 뻔했다.
  **부분 문자열로 구조를 확인하지 말 것.** 블록을 찾아 이름을 꺼내 비교한다.
- **지표 정의가 바뀌면 키 이름을 바꾼다.**
- **표본 없이 답할 수 있는 질문이 자주 있다.** D34·D38·D75·D87·D90·D91·D92.
- **모르면 다음 수는 고치는 것이 아니라 재는 것이다.**
- **고침은 한 호출부에만 도착한다 — 사본을 먼저 세라.** ai-elements 29파일 · WORKSPACE1 아홉 곳.
  K2b 에서는 **호출부가 0개**였다: `_announce_reveals` 를 쓰고 임포트까지 맞춰 놓고
  **어디서도 부르지 않았다.** 테스트는 초록이었다(위 공허한 단언 때문에).
  그 상태는 고치기 전보다 **나쁘다** — `defer_loading` 은 도구를 감추는데 공개가 없으니
  deferred 도구가 **영영 닿지 않는다.** 절반만 적용된 고침은 고침이 아니다.
  K6에서 또 나왔다: 도구 결과 매핑을 만드는 곳이 **둘**(`durable.py`·`subagent_port.py`)이었고,
  한쪽은 401자로 자르고 다른 쪽은 **아무것도 하지 않았다**. 반환부가 아니라 **매핑이 만들어지는 자리**에 걸어야
  사본이 생기지 않는다 — `_execute_validated`는 return이 두 개라 반환부에 걸면 그 자체가 새 사본이다.
- **유령 백로그가 우선순위 판단을 왜곡한다.**
- **둘을 구별하는 유일한 방법은 코드를 여는 것이다.** — 이번 개편의 갭 표(§5.2)도 스펙이 아니라 코드와 대조해서 썼다.
  그렇게 쓴 표도 틀렸다. R-06의 "tool_result base64 필터 없음"은 **양방향으로** 부정확했다 —
  부모에는 이미 401자 클립이 있었고(문제는 없음이 아니라 **쓸 수 없는 조각이 남는 것**이었다),
  자식에는 클립조차 없었다. **로드맵에 적힌 현재 상태도 착수 전에 다시 읽어야 한다.**
- **측정이 도는 동안 대상을 바꾸지 말 것. 테스트 스위트도 측정이다.**
- **새 방향이 옛 병목을 지우지 않는다.** 가장 매력적인 처방(J4)이 원인 판별(#23)을 가장 먼저 오염시킨다.
- **조용히 바뀌는 것이 시끄럽게 깨지는 것보다 위험하다.** 모델 세대 교체에서 400은 고맙고, 서술량 변화는 무섭다.

---

## 15. 참조

- **설계 정본:** [DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md)
- **완료 기록:** [DEEP_ANALYSIS_HARNESS_DONE.md](DEEP_ANALYSIS_HARNESS_DONE.md) — 이 로드맵에서 착지한 작업의 경위·숫자·발견
- **결정 원장:** `neos/workflow/deep_analysis/DECISIONS.md` (D1~D98) · `DECISIONS_ARCHIVE_2026-08.md`
- **방향의 근거:** [DIRECTION_260717.md](DIRECTION_260717.md) §2.1 (discovery 자유 / 검증 좁게)
- **Fable 5.1 스펙:** [fable-5-1-multiagent-spec.md](fable-5-1-multiagent-spec.md)
- **Jev(TypeSafe) 쿡북:** [Noul 자기일관성](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook) · [Choice 자기일관성](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook) — `system_one` 호출형 · Noul/Choice 반환형 · 밴딩 · **반복가능성은 정확도가 아니다**의 출처
- **코딩 에이전트:** [PLAN_260913.md](PLAN_260913.md) (잔여 스트림 A~H, 금지 목록 §2.1 — 2026-10-03 다시 세웠다) · [SUBAGENT_RUNTIME_DESIGN.md](SUBAGENT_RUNTIME_DESIGN.md). 옛 `NEOS_CODING.md` 는 `b7d37a87` 에서 지웠다(`git show b7d37a87^:docs/NEOS_CODING.md`)
- **코드 입구:** `neos/workflow/deep_analysis/harness_bridge.py` · `subagent_adapter.py` · `neos/subagent/` · `neos/coding/loop/durable.py` · `neos/coding/loop/_durable/{spawn,compaction}.py` · `neos/coding/prompts/builder.py` · `neos/coding/model/{base,anthropic}.py`
- **L5 운영:** [deep_analysis_l5.md](deep_analysis_l5.md) — 프롬프트 버전 게이트
- **백로그 원장:** 이 문서 §11 이다. 옛 `TODO_260729.md` 는 `c4ba75c6` 에서 지웠다 — 다른 문서의 "TODO_260729 G6" 같은 인용은 `git show c4ba75c6^:docs/TODO_260729.md` 로 읽는다
- **DB 부트스트랩 정본:** `db/BOOTSTRAP_ORDER.txt` · `scripts/verify_schema_bootstrap.py`
- **설정·모델 정본:** [CONFIGURATION.md](CONFIGURATION.md)
- **전체 로드맵:** [ROADMAP.md](ROADMAP.md) — R1·R2·R6이 W6의 관문
- **평가 증거:** `artifacts/deep-analysis-funnel/<ts>/` (gitignore, 재생성 불가) · `deep_analysis_events`
- **방향 점검 (2026-09-28):** [NEOS_MOMENTUM_ANALYSIS_20260928.md](NEOS_MOMENTUM_ANALYSIS_20260928.md) — 코딩 루프 · Jev · 자기개선 · 동시성을 코드와 대조했다. 이 문서에 옮긴 것은 코드로 확인한 사실과 결정 대기뿐이다. 트랙 신설(M·N·O·P)은 **제안**이고 계획이 아니다
- **자기개선:** [GEPA_SELF_IMPROVEMENT_MIGRATION.md](GEPA_SELF_IMPROVEMENT_MIGRATION.md) · [AGENT_RECIPE_DISTILLATION_260927.md](AGENT_RECIPE_DISTILLATION_260927.md)
- **외부 비교 — OpenAI dots (2026-09-30):** [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) — 상시 에이전트 기능 22개를 NEOS 코드와 대조했다. **트랙 Q(Q0~Q18)의 정본**
- **서비스·동시성:** [MICROSERVICE_REVIEW_260927.md](MICROSERVICE_REVIEW_260927.md) — DA lease · 테넌트 격리 · 브로커는 여기서 다룬다
