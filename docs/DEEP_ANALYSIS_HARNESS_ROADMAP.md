# 심층분석 하네스 통합 로드맵 — 코딩 루프로 조사하는 검증형 분석

> **이 문서가 로드맵의 정본이다.** 앞으로의 계획·변경·판정은 여기에 적는다.
>
> **수치와 판정의 원본은 여전히 이 문서가 아니다:** 수치는 `deep_analysis_events` 테이블과
> `artifacts/deep-analysis-funnel/<ts>/`, 판정은 `neos/workflow/deep_analysis/DECISIONS.md`
> (D1~D97)다. **충돌하면 원본이 이긴다.**

> 🔴 **2026-09-15 전면 개편.** 방향이 바뀌었다 — 워커는 "JSON 한 번 내는 응답자"에서
> **샌드박스에서 코드를 짜고 돌리는 에이전트 루프**로 간다(§2). 그리고 프롬프트·런타임 전략을
> Fable 5.1 기준으로 다시 세웠다(§5·§6).
>
> **직전 판본(2026-09-11 압축본, 518줄)** 은 git에 있다. 그 판본의 절 번호는 이 문서와 다르다:
>
> ```bash
> git show 31b37111:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md > /tmp/roadmap_0911.md   # 압축본
> git show c071585a:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md > /tmp/roadmap_full.md   # 3,199줄 전임본
> ```
>
> 이번 개편에서 **버린 결론은 없다.** 인용 생산 사슬(§7)·표본 경계(§8)·타협하지 않는 것(§9)·
> 작업 규칙(§10)은 그대로 옮겼다. 트랙 C·D·F·G·H의 서술은 줄였고, 줄인 상세는 압축본에 있다.

### 이 문서를 갱신하는 규칙

- **종결한 항목은 §11 인벤토리에서 지운다.** ✅로 남기지 않는다 — 유령 백로그가 남은 일을 과대평가하게 만든다
- **새 표본 경계가 생기면 §8에 먼저 적는다.** 사전 등록보다 먼저다
- **반증된 서술은 지우지 말고 취소선으로 남긴다** — 근거 없이 사라진 결론은 되살아난다
- **절대 수치는 적지 않는다.** 적어야 하면 측정 날짜를 함께 적는다
- **§4·§5·§6은 아직 설계다.** 코드가 착지하면 그 줄을 "착지(커밋)"로 바꾸고, 설계와 코드가 어긋나면 **코드가 이긴다**

**기준 시점: 2026-09-15**

---

## 1. 한눈에 — 트랙 열한 개

| 트랙 | 상태 | 남은 것 |
|---|---|---|
| **A. 심층분석 하네스** | 🟢 출하 기준 6/6 · 코드 인벤토리 비었다 | 🔴 **라이브 표본 #23** — `ANTHROPIC_WORKSPACE_ID` 값 하나에 막혀 있다(§7) |
| **B. 역할 기반 모델 라우팅** | ✅ 안정 | 유지보수. **effort 축이 들어오면 여기에 붙는다**(K5) |
| **C. 프론트엔드** | ✅ FE1~FE17 종결 | J·K가 새 이벤트 kind를 만들면 짝 규칙(fixture)이 다시 문다 |
| **D. 프레임워크 이탈** | 🟢 D1·D3a 완료 | D2 · D4(전송만 SDK로) · D3b. **J가 D4의 수요처가 된다** |
| **E. 코딩 에이전트** | 🟢 플랜 14개 완료 · development 프로파일 실제 루프 on | E-S2 배포 결정 · 잔여는 [PLAN_260913.md](PLAN_260913.md) A~H. managed provider **B2 게이트 미충족** |
| **F. 개선 루프 서브에이전트화** | 🔴 닫힘 | 재개하려면 새 스펙 + 새 사전 등록 |
| **G. 그래프 계약·검증** | 🟢 C3·C4 live(플래그 off) | 켜는 결정 · M-0 재측정(사전 등록 완료) |
| **H. 플러그인 런타임** | 🟢 H1 완료 · H3 코드 완료(꺼짐) | H2 · H4 · H5 |
| **I. 서브에이전트 노드 그래프** | 🟢 GS0~GS5 완료, 플래그 off | M-0 표본 → M-1 사전 등록 → GS6 |
| **J. 코딩 루프 조사** 🆕 | 🔵 **설계** — 이 개편의 중심(§4) | J0 계약 문서 → J1~J6. **플래그 off로 착지, 표본은 새 계보** |
| **K. Fable 5.1 적응** 🆕 | 🔵 **갭 분석 완료**(§5.2) — 코드 없음 | K1(이력 불변) · K2(턴 한정 system) · K7(컴팩션 형태)이 P0. **K3(비동기 spawn) 채택 결정**(2026-09-15) — PLAN_260913 §2.1 개정됨 |

**기본 플래그** — 두 제품 표면이 아직 프로덕션 기본 경로에 없다. 줄 번호는 적지 않는다.

```
DeepAnalysisConfig.enabled            = False
DeepAnalysisConfig.subagent_enabled   = False
SandboxConfig.enabled                 = False   (development: true, provider memory)
CodingModelConfig.enabled             = False   (development: true)
WorkflowConfig.graph_design_enabled   = False
WorkflowConfig.subagent_nodes_enabled = False
# J가 더할 것(설계): deep_analysis.code_research_enabled = False
```

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

### 3.3 J가 더하는 출하 기준 (설계, 미충족)

| # | 기준 | 왜 |
|---|---|---|
| **S7** | 계산 클레임은 **재실행 없이는 verified가 되지 않는다** | 코드가 만든 숫자는 발췌보다 더 그럴듯하게 틀린다 |
| **S8** | 코딩 워커의 모든 실행이 원장에서 **스크립트 digest + 입력 raw_ref + 출력 digest**로 복원된다 | "매니페스트 없는 런은 표본이 아니다"의 확장 |
| **S9** | 플래그 off일 때 워커 프롬프트·도구 목록·이벤트 어휘가 **바이트 단위로** 같다 | 트랙 I가 세운 방법. 켜는 커밋만 경계가 된다 |
| **S10** | 샌드박스를 요구하는 프로파일에서 샌드박스가 없으면 **실패한다**(비샌드박스 폴백 없음) | PLAN_260913 B5를 DA 경로에도 |

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
| **J0** | 계약 문서: `research/analyze/compose` 스펙, `ComputedEvidence`, 새 거절 코드, 이벤트 kind, 샌드박스 프로파일 `research-offline-v1` | — | 없음 |
| **J1** | 도구 경계: `fetch.v1`→`fetch.py`, blob 읽기 전용 마운트, `submit.v1`, 카탈로그 fail-closed 셋째 타입. **S9 바이트 동일 테스트** | J0 | 없음 |
| **J2** | 계산 클레임 채점기 + 재실행 + 이벤트 짝(fixture 양방향) | J1 | 없음(합성 fixture·변이 테스트) |
| **J3** | **오프라인 섀도**: 저장된 blob·카세트로 코딩 워커를 돌려 제안만 비교. 원장에 쓰지 않는다 | J2 | 없음(카세트) |
| **J4** | compose 자식 + 클레임 파일 공개 + `check_claims.v1` | **#23 판정** · J3 | 사전 등록 |
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

> ⚠️ **카탈로그에 `claude-fable-5-1`의 사실이 없다** (2026-09-15). `models.yaml`의 `claude-fable-5`
> 접두사가 가장 긴 일치로 먹을 뿐이다. context window·thinking 바인딩·effort 지원을
> **지어내서 적지 않는다** — 확인 못 한 모델 사실은 추측하지 않는다(메모리 규칙). K0이 첫 일이다.

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

### 5.2 갭 표 — 스펙 항목 × NEOS 현재 (2026-09-15 코드 대조)

| ID | 스펙 | NEOS 지금 | 갭 | K 티켓 |
|---|---|---|---|---|
| **R-01** | 이력 append-only, 원본 그대로 재전송 | 공통 메시지 형식(`coding/model/base.py`)에 **thinking 블록 타입이 없다.** `_to_anthropic_request`는 model·system·messages·tools·max_tokens만 보낸다 — `ModelLimits.thinking_budget`은 **와이어에 닿지 않는다** | 지금은 thinking을 재전송하지 않아서 400이 안 날 뿐이다. 켜는 순간 깨진다. 요청 prefix 바이트 동일 테스트 없음 | **K1** P0 |
| **R-02** | 턴 한정 system message (`clear_at`) | 경로 없음. 공통 형식에 mid-conversation system 역할 없음 | 공통 형식 확장 + 미지원 프로바이더 폴백(tool_result 뒤 text 블록) | **K2** P0 |
| **R-03** | 서브에이전트 즉시 반환 + `await` 도구 | **park/fold** — 부모가 자식을 기다린다(`_durable/spawn.py`) | park/fold를 즉시 반환 + 다음 safe point append + `await_subagent.v1`로 교체. PLAN_260913 §2.1 금지는 **2026-09-15 개정** | **K3** P1 |
| **R-04** | progress thinking 렌더 | 없음 | Code UI 상태 라인 + 이벤트 kind(C 짝 규칙) | **K4** P1 |
| **R-05** | effort 역할별 외부화, 중간 변경 | 코딩/채팅에 effort 필드 없음. G10 OPEN | G10을 K5로 흡수. DA 역할 scout/dig/synth/judge 각각 | **K5** P1 |
| **R-06** | `refusal` 정상 분기, base64 필터 | `normalize_stop_reason`(`coding/model/stop.py`)은 세 결과만 알고 **`refusal`은 `"unknown"`으로 뭉개진다.** tool_result base64 필터 없음 | 넷째 결과 `refusal` → 분기 → 원장 이벤트(무재시도). `unknown`과 섞이면 거절이 조용한 실패가 된다 | **K6** P1 |
| **R-07** | 클라이언트 compaction = 요약 1건 + 새 user 턴 | **정확히 금지된 형태다** — `(head,) + transcript[tail_start:]`로 최근 이력 일부를 붙이고, 요약은 `inject_previous_summary`로 **system을 다시 쓴다**(G2) | 형태 교체. **G2 CLOSED를 재개한다** | **K7** P0 |
| **R-08** | `max_tokens` = 사고 + 응답 | `ModelLimits.thinking_budget` 필드는 있음 | 긴 산출물(compose)의 한도 산식 + 예산 노트 | **K8** P2 |
| **P-01** | 자율 완수 블록 | 코딩 프롬프트 `_tasks`에 "비가역·워크스페이스 밖이면 멈춰라"만 있음 | 자율 오버레이. DA 워커는 **항상 자율 모드** | **K9** P0 |
| **P-02** | 변경·테스트 범위 제한 | `_tasks`에 범위 한 줄 | 코딩: 확장. 조사: "질문을 넓히지 않는다"로 번역(`worker_brief`의 범위 규칙과 합친다) | **K9** |
| **P-03** | 배칭 넛지(턴마다 새 사본) | `_using_tools`에 병렬 허용 문장(정적) | K2 선행 | **K10** P1 |
| **P-04** | 부분 편집 선호 | 없음 | 한 문장. 조사 워커엔 무관 | **K10** |
| **P-05** | compaction 요약 6항목 보존 | 컴팩션 프롬프트 미감사 | K7과 함께 | **K7** |
| **P-06** | low effort 검색 유도 | — | **scout(everyday)가 직접 해당.** 1차 대응은 그 턴만 effort 상향(K5) | **K11** P2 |
| **P-07** | 억제 문구 제거 | 코딩 `_tone` 미감사. DA 프롬프트는 JSON 계약이지 안티포매팅이 아니다 | grep 감사 → 제거. `final_compose`에는 "mannered prose" 한 줄 후보 | **K11** |

### 5.3 K3 — 비동기 서브에이전트: 채택 (2026-09-15 결정)

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
K0 카탈로그: fable-5-1 사실 확인(공식 문서) — 확인 못 하면 적지 않는다
 ├─ K1 이력 불변 + prefix 바이트 동일 테스트 ──┐
 ├─ K7 컴팩션 형태 교체 (G2 재개) ─────────────┼─> thinking 켜기 (§8 경계 9)
 └─ K2 턴 한정 system ─> K10 배칭 넛지         │
K5 effort 필드 + 벤치 러너 ─> 모델별 스윕 ──────┘
K9 자율/대면 오버레이 (G11) ─> K11 억제 문구 감사
K6 refusal · K4 progress · K8 max_tokens        (독립)
K1 ─> K3 비동기 spawn + await_subagent.v1       (채택. 기본 on은 A1·A2 숫자 뒤)
```

**K1·K7이 thinking을 켜는 선행이다.** 순서를 뒤집으면 첫 tool 루프가 400으로 전멸하고,
preflight가 "키가 있다"만 보고 통과했던 D94와 같은 모양으로 실패한다.

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
| **`ANTHROPIC_WORKSPACE_ID` 값 하나** | 🔴 사람이 넣어야 한다. #23의 유일한 선행 |
| D93 사전 등록 | 🔴 다시 써야 한다 — BUDGET2·D2가 경계 둘을 새로 만들었다(D-14) |
| 판독기·테스트 14·재현 게이트 | ✅ 재사용 가능 |

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
| **8** 🆕 | J 플래그를 켜는 커밋 | 워커가 코딩 루프가 된다 | **경계가 아니라 새 계보(C-계열)다.** #1~#23과 어떤 수치도 나란히 놓지 않는다. C-계열 안에서도 research/analyze/compose를 켜는 커밋이 각각 경계다 |
| **9** 🆕 | K: thinking을 켜는 커밋 | 워커·판정자가 thinking을 쓴다 | 채점 결과 · 토큰 지출 · 벽시계 |
| **10** 🆕 | K5: effort 기본값을 정하는 커밋 | 역할별 사고량 | 채점 결과 · 토큰 지출. **effort 변경마다 행을 더한다** |
| **11** 🆕 | K9·K11: 오버레이·억제 문구 제거 | 워커 행동 기본값 | 채점 결과. 문구 하나 = 행 하나 |

**1·2는 방향이 예측 가능했다. 3·5·6은 아니다. 7은 판정 전이다. 8은 계보를 새로 연다.**

> **플래그 뒤 병합은 경계가 아니다**(트랙 I가 세운 방법). 꺼져 있으면 프롬프트·도구·계약이
> **바이트 단위로** 같음을 테스트가 고정해야 한다. 경계는 **켜는 커밋**이다. J·K도 이 방법을 따른다.

> 📌 D92 재현 게이트(79·152·152·15)는 **저장된 원장**을 읽으므로 어떤 경계에도 무효가 되지 않는다.

---

## 9. 절대 타협하지 않는 것

**설계 정본**([DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md))의
§1 5원칙과 §11 금지사항은 모든 성능·비용 논의보다 우선한다. (§번호는 그 문서의 것이다.)

**하네스 층:**

- **P2 단일 작성자** — 원장 쓰기는 오케스트레이터 한 곳
- **judge ≠ worker** — `judge: claude-opus-4-8`. ⚠️ 워커와 같은 가족이라 편향 분리가 약하다
- **append-only 이벤트 로그** — 예외는 의도를 표명한 트랜잭션뿐(`Ledger.purge_run()` + `SET LOCAL`)
- **매직넘버 금지** — 전부 settings. 프롬프트는 전부 파일

**플러그인 층:**

- 플러그인은 원장의 작성자가 될 수 없다
- 동적 설치 플러그인도 `TokenBudget.reserve()`를 거친다
- 매니페스트 없는 런은 표본이 아니다 — 기계가 거부한다
- judge 플러그인과 worker 플러그인은 같은 인스턴스일 수 없다

**코딩 루프 층 🆕 (J·K — 다치기 전에 세우는 것):**

- **코딩 워커는 원장에 쓰지 않는다.** `submit.v1`은 제안이다
- **샌드박스 안 코드는 네트워크가 없다.** 바이트는 `fetch.py`를 통해서만 들어온다
- **재현되지 않는 계산은 verified가 아니다**
- **자식의 LLM 호출도 `TokenBudget.reserve()`를 거친다** — fold가 사용량을 부모에 더하는 것과 별개로, 질문 예산에 청구돼야 floor 산식이 성립한다
- **대화 이력은 in-place로 고치지 않는다**(K1). 요약·리마인더·도구 목록 교체는 정해진 경로로만
- **샌드박스 ≠ 승인 생략**

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

### 10.2 증거 보존

`git worktree remove`는 gitignore 대상 파일을 경고 없이 삭제한다. `artifacts/deep-analysis-funnel/<ts>/`는
재생성 불가다. **J 이후에는 샌드박스 산출물(스크립트·출력)도 같은 등급이다** — 워크트리 정리 전에 옮긴다.

### 10.3 앰비언트 상태 오염 4종 (전부 실제 발생)

| 증상 | 원인 |
|---|---|
| 전역 `settings` 싱글턴이 바뀐 채 남음 | `reload_settings_for_tests()`가 모듈 전역 재바인딩 |
| 프로세스 env가 테스트 지정값을 이김 | litellm import 시 `load_dotenv()` |
| import 시점 고정 플래그 어긋남 | `neos/main.py`의 `IS_DEBUG` |
| 테스트가 심은 AsyncMock이 전역에 남음 | `patch`는 팩토리를 복원하지 캐시된 인스턴스를 복원하지 않는다 |

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
| **값 하나** | `ANTHROPIC_WORKSPACE_ID` — #23의 유일한 선행 |
| **사람의 결정** | **D-14**(BUDGET2를 CITE1 판별과 한 표본에?) · **D-12**(동적 합성을 표본 경로에) · **E-S2** · 트랙 G/H 켜기 · 트랙 I 보존 정책 |
| **결정됨** 🆕 (2026-09-15) | **K3** 비동기 spawn 채택(§5.3) · **J production 샌드박스는 B2 게이트에 묶는다**(§4.5) · **Fable 5.1 공식 문구 그대로 사용**(§10.5) |
| **라이브 표본** | CITE1 후보 판별(#23) · BUDGET2 효과 · D2 효과 · C1 · S2 두껍게 · A3·A4 · M-0 · 🆕 **C-계열**(J5) · 🆕 effort 스윕(K5) |
| **새 사전 등록** | D93 다시 쓰기 · M-1 · 🆕 **J4**(점진 공개 조립) · 🆕 **C-계열 첫 표본** |
| **새 스펙** | 트랙 F 재개 · 🆕 **J0 계약 문서** |
| **표본 없이 되는 코드** 🆕 | **J1·J2·J3**(플래그 off, S9) · **K0·K1·K2·K7**(thinking을 켜기 전까지 행동 불변) · K6 · K4 |
| **측정 없이 못 정함** | `claude-opus-5` 세대 사실(CA12) · 🆕 `claude-fable-5-1` 세대 사실(K0) |
| **규모가 큰 별건** | D3b · D2 · D4 — 전부 W6 이후. **D4는 J가 수요를 만든다** |

> **읽는 법:** 이번 개편으로 **표본 없이 할 수 있는 코드**가 다시 생겼다(J1~J3, K0~K2·K7).
> 그러나 트랙 A의 병목은 여전히 `.env` 한 줄이고, J4는 그 뒤다. **새 일이 생겼다고 옛 병목이 사라지지 않았다.**

### 미해결 인벤토리 (트랙 A 잔여)

| 우선 | ID | 내용 |
|---|---|---|
| 🟡 | **C1** | discard recall 재측정 — 2회 연속 n=0. 라이브 표본 하나 남음 |
| 🟢 | **CE1~CE4** | §5.4로 편입. **CITE1 판정 전 착수 금지** |
| 🟡 | **A3·A4** | worker/판정자 상한 재보정(thinking 몫 실측 선행 — **K 경계 9와 겹친다**) |
| 🟡 | **ORPHAN2** | 조립기가 없는 클레임 id를 지어낸다. 감시 조건은 가용 verified 대비 인용 비율 |
| 🟡 | **D1**(트랙 A) | search 0건 반환 비율 7% |

### 트랙 J·K 인벤토리 🆕

| 우선 | ID | 내용 | 선행 |
|---|---|---|---|
| 🔴 P0 | **J0** | 계약 문서(스펙 셋 · `ComputedEvidence` · 거절 코드 · 이벤트 kind · 프로파일) | — |
| 🔴 P0 | **K0** | `claude-fable-5-1` 카탈로그 사실 — 공식 문서 확인 | — |
| 🔴 P0 | **K1** | thinking 블록을 공통 형식에 추가, 원본 보존, prefix 바이트 동일 테스트 | K0 |
| 🔴 P0 | **K7** | 컴팩션 = 요약 1건 + 새 user 턴. G2 재개 | K1 |
| 🔴 P0 | **K2** | 턴 한정 system message + 폴백 | K1 |
| 🟠 P1 | **J1·J2** | 도구 경계 · 계산 클레임 채점기 | J0 |
| 🟠 P1 | **K5** | effort 카탈로그 필드(G10 흡수) + 역할별 설정 + 벤치 러너 | K0 |
| 🟠 P1 | **K9** | 자율/대면 오버레이(G11) | — |
| 🟠 P1 | **K6 · K4 · K10** | refusal 분기+base64 필터 · progress 렌더 · 배칭 넛지 | K10은 K2 |
| 🟡 P2 | **J3** | 오프라인 섀도(카세트) | J2 |
| 🟡 P2 | **K8 · K11** | `max_tokens` 산식 · 억제 문구 감사 | — |
| ⚪ | **J4 · J5 · J6** | 조립 · C-계열 표본 · staged 스킬 | #23 판정 · 사전 등록 |
| 🟠 P1 | **K3** | 비동기 spawn(즉시 반환 · safe point append · `await_subagent.v1`) — 기본 off | K1. 켜기는 A1·A2 |

> ⚠️ **ID 충돌 주의.** 트랙 A의 D1·D2(검색·retrieval 결함)와 트랙 D의 D1~D4(프레임워크 이탈)는 다르다.
> PLAN_260913의 G1~G12·A1~A5·B1~B5도 이 문서의 트랙 G·A·B와 다르다. **K5는 PLAN G10을, K9는 G11을 흡수한다.**

---

## 12. 트랙별 한 줄 — 어디를 읽어야 하는가

### A. 심층분석 하네스
라운드 루프는 동작한다. 문제는 마지막 줄(리덕션 → 조립 → 게이트)이다. W1·W2·W3(열두 갈래) 완료,
남은 것은 W4 일부와 W6(승격). 상세: 압축본 §3·§8.

### B. 역할 기반 모델 라우팅 — 반드시 유지할 불변식
- 해석 우선순위: **user → conversation → feature override → role default**
- 역할 매핑: anthropic `everyday=claude-sonnet-5` / `powerful=claude-opus-5`, openai `everyday=gpt-5.6-terra` / `powerful=gpt-5.6-sol`
- DA 역할: `scout=everyday` · `dig=powerful` · `synth=powerful` · `judge=everyday`(오버라이드로 `claude-opus-4-8`)
- 경계마다 한 번만 해석 · ❌ 크로스 프로바이더 폴백 · ❌ 요청마다 LLM 난이도 분류 · ✅ 모든 모델은 가격을 가진다
- 🆕 **effort는 모델과 같은 해석 사슬을 탄다**(K5) — 따로 사슬을 만들면 "고침은 한 호출부에만"이 재발한다

### C. 프론트엔드
어휘는 `tests/fixtures/deep_analysis_event_kinds.json` 한 파일, 백엔드는 AST로 훑어 일치를 주장, 면제는 양방향.
`frontend-ci.yml`에 `paths: [web/**]`를 넣지 말 것. 📌 되돌리지 말 것: 프록시 라우트에 POST 없음 ·
모르는 kind도 커서 전진 · `Record<CounterKey, …>`. **J·K가 만드는 kind는 이 fixture를 거친다.**

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

### F. 개선 루프 서브에이전트화 — 닫혔다
진단자가 표본을 읽지 않고 한 이야기를 반복했다(11개 중 10개에서 3/3 같은 라벨). 채점기·정답키·기준선은
재사용 가능. **자동화가 보존해야 하는 넷:** 표본은 한 번 · 사전 등록이 먼저 · 계측을 먼저 의심 · 배달물을 잰다.
> J의 analyze 자식은 F의 진단자가 **아니다** — 원장을 고치거나 프롬프트를 제안하지 않는다.

### G. 그래프 계약·검증
노드 N이 키 K를 `requires`하면 START→N의 **모든 경로**에 K를 쓰는 노드가 있어야 한다.
`requires` 검증은 하한만이고 오늘 그 하한은 공허하다(`_create_initial_state`가 58개 키를 채운다).
**낡은 면제 플래그는 가드를 조용히 끈다** — 양방향 테스트.

### H. 플러그인 런타임
네 층을 묶는 계약(H2)과 조립 원장(H1 ✅). 남은 긴장 ㉰는 통계 문제(run당 6개로 층화 불가) → D-12.

### I. 서브에이전트 노드 그래프
[설계](GRAPH_SUBAGENT_INTEGRATION_DESIGN.md) · K25′(D97) · 마이그레이션 058. 1-step 법, 걸음 상한 `2·max_turns + 1`
(핸들러가 강제), 체크포인터 없는 경로에서는 조립 안 함, 보고는 unverified 검색 결과, 병렬 조인은 `defer`.
GS3 어휘만 · GS6 표본 전. ⚠️ 템플릿 없는 설계도 병렬 가지가 리듀서 없는 키를 같이 쓰면 run이 죽는다(별도 사전 등록).

### J. 코딩 루프 조사 🆕 — §4
### K. Fable 5.1 적응 🆕 — §5

---

## 13. 이 루프가 자기 자신에게서 배운 것

- **계측을 먼저 의심한다.** 자가 지표가 세 번 틀렸다. 루프는 틀린 지표에 성실하게 수렴한다.
- **계측기가 도는지 보는 것은 실패해야 할 때 실패하는지 보는 것이다.** `after <= before`는 버그를 되살려도 통과했다.
- **무는지 보지 않고 세운 게이트는 없느니만 못하다.** 변이로 확인한다.
- **지표 정의가 바뀌면 키 이름을 바꾼다.**
- **표본 없이 답할 수 있는 질문이 자주 있다.** D34·D38·D75·D87·D90·D91·D92.
- **모르면 다음 수는 고치는 것이 아니라 재는 것이다.**
- **고침은 한 호출부에만 도착한다 — 사본을 먼저 세라.** ai-elements 29파일 · WORKSPACE1 아홉 곳.
- **유령 백로그가 우선순위 판단을 왜곡한다.**
- **둘을 구별하는 유일한 방법은 코드를 여는 것이다.** — 이번 개편의 갭 표(§5.2)도 스펙이 아니라 코드와 대조해서 썼다.
- **측정이 도는 동안 대상을 바꾸지 말 것. 테스트 스위트도 측정이다.**
- 🆕 **새 방향이 옛 병목을 지우지 않는다.** 가장 매력적인 처방(J4)이 원인 판별(#23)을 가장 먼저 오염시킨다.
- 🆕 **조용히 바뀌는 것이 시끄럽게 깨지는 것보다 위험하다.** 모델 세대 교체에서 400은 고맙고, 서술량 변화는 무섭다.

---

## 14. 참조

- **직전 판본:** `git show 31b37111:docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` · 전임본 `c071585a`
- **설계 정본:** [DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md)
- **결정 원장:** `neos/workflow/deep_analysis/DECISIONS.md` (D1~D97) · `DECISIONS_ARCHIVE_2026-08.md`
- **방향의 근거:** [DIRECTION_260717.md](DIRECTION_260717.md) §2.1 (discovery 자유 / 검증 좁게)
- **Fable 5.1 스펙:** [fable-5-1-multiagent-spec.md](fable-5-1-multiagent-spec.md)
- **코딩 에이전트:** [NEOS_CODING.md](NEOS_CODING.md) · [PLAN_260913.md](PLAN_260913.md) (CC·Hermes·iii 분석 결론, 금지 목록 §2.1) · [SUBAGENT_RUNTIME_DESIGN.md](SUBAGENT_RUNTIME_DESIGN.md)
- **코드 입구:** `neos/workflow/deep_analysis/harness_bridge.py` · `subagent_adapter.py` · `neos/subagent/` · `neos/coding/loop/durable.py` · `neos/coding/loop/_durable/{spawn,compaction}.py` · `neos/coding/prompts/builder.py` · `neos/coding/model/{base,anthropic}.py`
- **L5 운영:** [deep_analysis_l5.md](deep_analysis_l5.md) — 프롬프트 버전 게이트
- **백로그 원장:** [TODO_260729.md](TODO_260729.md)
- **DB 부트스트랩 정본:** `db/BOOTSTRAP_ORDER.txt` · `scripts/verify_schema_bootstrap.py`
- **설정·모델 정본:** [CONFIGURATION.md](CONFIGURATION.md)
- **전체 로드맵:** [ROADMAP.md](ROADMAP.md) — R1·R2·R6이 W6의 관문
- **평가 증거:** `artifacts/deep-analysis-funnel/<ts>/` (gitignore, 재생성 불가) · `deep_analysis_events`
