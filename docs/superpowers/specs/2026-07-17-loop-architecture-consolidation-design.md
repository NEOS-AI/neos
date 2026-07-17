# Loop 아키텍처 통합 — 설계 문서

**작성일:** 2026-07-17
**상태:** 승인됨 (구현 계획 대기)
**대상 독자:** 이 시스템을 처음 보는 코딩 에이전트. 이 문서만으로 구현 계획 수립이 가능해야 한다.
**관련 결정:** `neos/workflow/deep_analysis/DECISIONS.md` D6, D7, D18, D19
**관련 설계:** `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md`

---

## 0. 이 문서가 하는 일

NEOS 백엔드에 공존하는 4개 실행 패러다임을 진단하고, `deep_analysis` loop을
1차 실행 모델로 승격시키기 위한 3단계 전환을 설계한다.

**판정 기준(사용자 지정):** 품질/정확도 + 유지보수성/복잡도. **비용과 지연시간은 판정 기준이 아니다.**
이 선택이 설계 전반을 좌우한다 — 유지보수성이 기준이므로 "패러다임 공존" 자체가 비용으로 계상된다.

---

## 1. 현황 진단

### 1.1 4개 패러다임이 공존한다

| 패러다임 | 위치 | 실행 방식 | 규모 |
|---|---|---|---|
| **Workflow** | `neos/workflow/graph.py` | LangGraph StateGraph, 정적 노드/엣지 | 2,234줄 / 노드 31 / 조건부 엣지 11 |
| **Recursive (ROMA)** | `neos/workflow/recursive/` | Python 재귀 분해, depth 기반 | 9개 파일 |
| **HyperDeep** | `neos/workflow/hyper_deep/` | ROMA 분해 + 무거운 leaf 실행 | 2개 파일 + HDR 에이전트 |
| **Loop** | `neos/workflow/deep_analysis/` | 예산 기반 라운드 루프 | 3,464줄 |

loop의 본체는 `orchestrator.py:703`:

```python
while not await self.budgeter.should_stop(self.ledger):
    ...  # _run_round(): decompose → partition → split → reduce
```

### 1.2 "loop vs workflow"는 잘못된 질문이다

`DEEP_ANALYSIS_ORCHESTRATOR`는 LangGraph 그래프 **안의 노드 하나**다(`graph.py:358`).
`SKILL_TOOL_SELECTOR`에서 갈라져 `RESULT_INTEGRATOR`로 합류한다. 즉 현재 구조는:

- **바깥 껍데기** = LangGraph workflow (라우팅·컨텍스트·응답 생성)
- **안쪽 엔진** = 교체 가능한 deep 엔진 3종 (recursive / hyper_deep / deep_analysis)

둘은 같은 층위에서 경쟁하지 않는다. 성능 비교가 성립하지 않는다.

### 1.3 결함 목록

#### R1. 임계값 역전 — 플래그를 켜면 두 엔진이 조용히 죽는다 🔴 **신규 발견**

`neos/workflow/routing/orchestrator_router.py:98-129`의 세 블록은 플래그명·상수·임계값만
다른 거의 동일한 코드이며, **셋 다 같은 intent(`DEEP_RESEARCH`, `COMPLEX_ANALYSIS`)를 두고 경쟁**한다.

| 엔진 | 라우팅 순서 | complexity 임계값 | 결과 |
|---|---|---|---|
| `deep_analysis` | 1순위 | **0.5** | 0.5 이상 전부 흡수 |
| `hyper_deep` | 2순위 | 0.85 | 도달 불가 (0.85는 0.5를 이미 통과) |
| `recursive` | 3순위 | 0.8 | 도달 불가 |

우선순위와 임계값이 역전돼 있어, `DEEP_ANALYSIS_ENABLED=true`인 순간 뒤 두 엔진의
complexity 경로는 **100% 도달 불가능한 죽은 코드**가 된다. 에러도 경고도 없다.

이 결함은 기존 문서 어디에도 기록돼 있지 않다.

#### R2. intent 경로도 막혀 있다 (= D18 선결 조건 #3)

R1의 유일한 탈출구는 명시적 intent(`intent == IntentType.HYPER_DEEP_RESEARCH` 등)인데:

- 기본 분류기(키워드, `query_classifier.py:104-117`)는 이 intent들을 **생성하지 않는다**
- LLM 분류기는 `_VALID_INTENTS = [it.value for it in IntentType]`로 전부 허용하지만
  프롬프트 Rules에는 9개만 설명 → 사실상 방출 안 됨
- `QueryClassifierConfig.use_llm = False` (기본 꺼짐) → 키워드 경로가 기본

**R1 + R2 = `DEEP_ANALYSIS_ENABLED=true`를 켜는 순간 ROMA·Ray·HyperDeep이 통째로 도달 불가.**

#### R3. wall-clock 무한 (= D18 선결 조건 #1, 미해결)

`_deep_analysis_orchestrator_node`가 `orch.run()`을 타임아웃 없이 동기 완주시킨다.

노드는 `profile = "default"`를 하드코딩하므로 `DeepAnalysisConfig`의 기본값이 적용된다 —
`global_token_cap` **300,000**, `dig`의 `wall_clock_cap` 600s. (D18 본문이 "프로덕션 캡
global_token_cap 20000"이라 적은 것은 `DeepAnalysisDevProfileConfig`(dev 프로파일)의 값이며,
챗 노드가 실제로 타는 경로가 아니다. 즉 **실제 노출은 D18이 기록한 것보다 15배 크다.**)

챗 요청 하나가 수 분간 블로킹된다. HTTP/WS/게이트웨이 타임아웃과 충돌한다.

#### R4. 이벤트 싱크가 no-op

챗 노드는 `def sink(kind, payload): pass`를 넘긴다(D18의 의도적 선택). loop이 뿜는
claim 단위 이벤트를 챗이 전부 버린다. 같은 코어를 쓰는 두 소비 경로의 계약이 다르다.

#### R5. resume 미구현

`ledger.py:124`, `orchestrator.py:606`이 "resumed run"을 전제로 주석을 달고 있고
`Orchestrator.checkpoint` 훅도 있으나, **재개 진입점이 없다.** 설계 원칙 P4
("재개(resume)가 append-only 로그에서 나온다")가 미완성이다.

#### R6. 세 엔진 모두 기본 비활성

`enabled: False` × 3 (`neos/config/schema.py`). 프로덕션 기본값에서 세 엔진 모두 안 돈다.

### 1.4 loop은 이미 독립적이다

`deep_analysis`는 **langgraph/langchain을 코드에서 전혀 import하지 않는다.**
내부 의존은 4개뿐:

```
neos.config.settings
neos.database.deep_analysis_models
neos.tools.tools.web_search
neos.utils.time_utils
```

LangGraph에 묶는 것은 `graph.py`의 55줄짜리 노드 하나다. **분리 비용은 낮다.**

원 설계 §655가 "LangGraph 워크플로우가 하네스로 점진 대체"를 예정했고, D18이 스스로를
"그 방향의 첫 이동"으로 규정한다. 이 문서의 방향은 원 설계 의도와 일치한다.

---

## 2. 목표 구조

```
┌─────────────────────────────────────────────────┐
│  Chat (LangGraph)  = 껍데기: 라우팅·컨텍스트·응답  │
└───────────────┬─────────────────────────────────┘
                │ submit job (run_id 반환, 블로킹 없음)
                ▼
┌─────────────────────────────────────────────────┐
│  Deep Analysis Job Service  (프레임워크 프리)     │
│  ┌───────────┐  ┌────────┐  ┌────────────────┐  │
│  │Orchestrator│→ │ Ledger │← │ Event Log      │  │
│  │(단일 작성자)│  │(단일   │  │ (append-only,  │  │
│  └─────┬─────┘  │ 상태)   │  │  resume 근거)  │  │
│        │        └────────┘  └───────┬────────┘  │
│        ▼                            │           │
│  ┌───────────────┐                  ▼           │
│  │ Workers (순수) │              SSE 재생        │
│  │  discovery ◄──┼── Skill Adapter              │
│  │  retrieval ◄──┼── fetch.py (독점, 불변)       │
│  └───────────────┘                              │
└─────────────────────────────────────────────────┘
```

Chat과 API가 **동일한 job 서비스의 클라이언트**가 된다. R4(no-op 싱크)가 사라지고
챗도 claim 단위 진행을 관찰한다.

---

## 3. 단계 1 — Skill 통합

### 3.1 근거

loop은 현재 모든 근거를 범용 `web_search` 하나로 모은다. 반면 `neos/skills/builtin/`에는
연구용 소스 10종이 놀고 있다: `arxiv`, `google_scholar`, `openalex`, `pubmed`,
`semantic_scholar`, `sec_edgar`, `news_api`, `reddit`, `wikipedia`, `github_search`.

학술 1차 소스를 붙이면 `source_tier` 분포가 올라간다. **충돌 해소가 source_tier로 우열을
가리므로**(커밋 `97e2835`), 이는 품질/정확도 축에 직접 작용한다.

### 3.2 이음새가 이미 맞는다

`service.py`의 `web_search`가 쓰는 도구 생명주기와 `BaseSkill` 계약이 동일하다:

| 단계 | `WebSearchMCPTool` | `BaseSkill` |
|---|---|---|
| 초기화 | `await tool.initialize()` | `await skill.initialize()` |
| 실행 | `await tool.execute({query, max_results})` | `await skill.execute(params)` |
| 결과 | `.success` / `.data` | `SkillResult.success` / `.data` |
| 정리 | `await tool.cleanup()` | `await skill.cleanup()` |

`BaseSkill.get_input_schema()`는 이미 **Anthropic tool input_schema 형식**을 반환한다.

**주입 지점이 이미 파라미터로 열려 있다** — `service.build_orchestrator(..., search_fn=web_search)`.
`Worker(search_fn, ...)`로 그대로 전달되므로, 스킬 통합은 이 인자에 합성 discovery 함수를
넘기는 것으로 시작한다. `build_orchestrator` 시그니처 변경 없이 착수 가능하다.

### 3.3 결정: 스킬은 discovery 소스로만 들어간다

**D6 확장.** D6는 "탐색(discovery)은 `web_search` 재사용, 검색(retrieval)은 신규 `fetch.py`"를
정했다. 스킬은 **discovery 축에만** 추가되고 retrieval은 `fetch.py`가 독점한다.

**근거 — `DeterministicGrader`가 출처 무관이다** (`graders/deterministic.py`):

| 코드 | 검증 내용 |
|---|---|
| `E_NO_EVIDENCE` | 클레임에 evidence가 붙었는가 |
| `E_SOURCE_DEAD` | blob이 HTTP 2xx로 **실제 fetch**됐는가 |
| `E_QUOTE_MISMATCH` | `excerpt_matches(excerpt, blob.raw_text)` — 발췌가 **fetch된 원문에 존재**하는가 |
| `E_CONFIDENCE_INFLATED` | 구별되는 출처 수로 confidence 상한 |

어떤 도구가 URL을 찾았는지는 일절 보지 않는다. 따라서 **discovery 도구 선택은 검증 무결성에
영향을 주지 못한다.** 나쁜 선택은 주장을 적거나 나쁘게 만들 뿐, 미검증 주장을 통과시키지 못한다.

**스킬 어댑터 계약:**

- 반환 형식: `[{url, title, snippet}]` — `service.web_search`와 동일
- **URL을 주지 못하는 스킬은 discovery 소스 자격이 없다** (grader가 fetch 못 하면 `E_SOURCE_DEAD`)
- 스킬별 `SkillResult.data` → 위 형식으로 정규화하는 어댑터 필요

### 3.4 결정: 도구 선택은 워커의 LLM이 한다

**P3 위반이 아니다.** P3("위험한 자유도는 스키마에서 제거")가 겨냥하는 것은 **무결성에
영향을 주는 자유도**다 — 인용(클레임 ID 마커로만), 발췌(원문 대조로만), 서브질문 생성
(오케스트레이터 권한으로만). discovery 도구 선택은 §3.3에 의해 무결성 레버가 아니라
품질·효율 레버이므로 이 범주에 속하지 않는다.

**결정성이 깨지지 않는다.** cassette가 LLM 호출을 녹화한다(`llm.py:132`,
`cassette.remember("llm", payload, produce)`). 워커 LLM의 도구 선택은 `"llm"` 레코드로
녹화되어 replay 시 동일 재생된다. **D19의 golden 회귀 게이트가 그대로 유지된다.**

**cassette 신규 종류 `"skill"`** 을 추가한다 — `"search"`/`"fetch"`/`"llm"`과 동일 패턴,
키는 `{skill_name, params}`.

### 3.5 결정: loop 전용 셀렉터를 신규 작성한다

기존 `SKILL_TOOL_SELECTOR` / `agents/skill_based_tool_selector.py`는 우리가 빠져나오려는
워크플로우 안에 있고, loop의 요구(검증 가능성·source_tier)를 모른다. 프레임워크 프리 원칙을
지키기 위해 loop 전용 셀렉터를 새로 둔다.

**2층 구조:**

1. **셀렉터(결정론적)** — 이 질문에 제공할 **후보** 스킬 집합을 좁힌다. 필터: 검증 가능성
   (URL 반환 여부), effort, 가용성(`is_available`)
2. **워커 LLM** — 후보 중에서 tool-calling으로 실제 사용을 고른다

### 3.6 결정: 스킬은 dig effort부터

`scout`의 `token_cap`은 2,000이다. 도구 스키마 + 멀티턴 tool-calling이 들어가지 않는다.

| effort | token_cap | 도구 |
|---|---|---|
| `scout` | 2,000 | `web_search` 단독 (현행 유지) |
| `dig` | 12,000 | `web_search` + 선택된 스킬 |
| `synth` | 8,000 | 해당 없음 (조사 아님) |

### 3.7 수용 기준 (AC)

- AC1. `Worker.__init__`의 `search_fn` 계약이 변경되지 않는다 (P1 순수성 보존)
- AC2. `dig` effort 워커가 스킬을 tool-call로 호출해 discovery를 수행한다
- AC3. `scout` effort는 도구 집합이 현행과 동일하다
- AC4. URL을 반환하지 않는 스킬은 셀렉터가 후보에서 제외한다
- AC5. cassette `"skill"` 레코드로 record/replay가 결정적으로 재생된다
- AC6. 기존 golden 게이트(`test_golden_gate`)가 통과한다
- AC7. 스킬 비활성/실패 시 `web_search` 단독 경로로 graceful degradation
- AC8. 검증 사슬 무결성: 모든 클레임은 여전히 `fetch.py` blob 대조를 통과해야 verified

---

## 4. 단계 2 — 엔진 재배치

### 4.1 결정: 역할을 질의 유형으로 가른다

임계값(0.5/0.8/0.85)이 아니라 **작업의 형태**로 라우팅한다.

| 엔진 | 역할 | 판별 기준 |
|---|---|---|
| **deep_analysis** | 검증형 분석 — "이 주장이 사실인가" (인용·충돌해소·검증된 클레임만) | 검증이 필요한 질의 |
| **hyper_deep** | 장문 리포트 — "긴 보고서를 써라" (Ralph 정제 루프, 섹션 품질) | 분량·구조가 목적인 질의 |
| **recursive (ROMA)** | 일반 태스크 분해 — "여러 단계 작업을 수행하라" (research 아닌 복합 작업, Ray 병렬) | 실행형 다단계 작업 |

### 4.2 이 결정이 해소하는 것

- **R1(임계값 역전):** 세 엔진이 같은 intent를 두고 경쟁하지 않게 되므로 shadowing이 사라진다
- **R2(intent 미도달):** 분류기가 세 유형을 구별하는 intent를 방출해야 하므로 죽은 분기가 살아난다

### 4.3 필요 작업

1. `query_classifier`가 세 유형을 구별하는 intent를 방출하도록 확장
   - 키워드 경로와 LLM 경로 **둘 다**. LLM 프롬프트 Rules에 세 유형 설명 추가
2. `OrchestratorRouter.route()`의 3중 if-체인을 유형 기반 단일 디스패치로 재작성
3. complexity 임계값은 "deep 엔진을 쓸지 말지"의 게이트로만 남기고, "어느 엔진인지"는 유형이 결정

### 4.4 수용 기준 (AC)

- AC1. 세 엔진 모두 활성일 때 각 엔진에 도달하는 질의 사례가 테스트로 존재한다
- AC2. `orchestrator_router.py`에 동일 구조 반복 블록이 남지 않는다
- AC3. 분류기가 세 유형 intent를 방출한다 (키워드·LLM 경로 각각 테스트)
- AC4. 도달 불가능한 라우팅 분기가 0개임을 테스트로 보장한다
- AC5. 세 엔진 모두 비활성일 때 기존 경로로 무회귀

---

## 5. 단계 3 — 분리 (Job 서비스)

### 5.1 결정: durable job 서비스로 전환한다

**D7 갱신.** D7은 "M1은 인라인 asyncio + SSE, Celery는 나중"을 정했다. 이 단계가 그 "나중"이다.

| | 현재 | 목표 |
|---|---|---|
| 제출 | 챗 노드가 블로킹 완주 | `POST /api/v1/deep-analysis` → run_id 즉시 반환 (202) |
| 실행 | 요청 스레드 인라인 | Celery 워커 |
| 진행 | 챗=no-op, API=인라인 SSE | `GET /api/v1/deep-analysis/{run_id}/events` — 이벤트 로그 재생 + 라이브 tail |
| 재개 | 없음 | Ledger에서 open 질문 복원 후 라운드 속행 |

### 5.2 D18과의 관계

**이 단계는 D18을 대체한다.** D18은 "챗 경로의 라우팅 대상만 교체하는 첫 이동"이라 스스로를
규정하고, per-claim 스트리밍의 챗 편입을 "그 다음 단계(챗 SSE 프로토콜 자체를 하네스 이벤트
스키마로 통합)"로 명시했다. 이 단계가 그 다음 단계다. **모순이 아니라 예정된 승계다.**

`_deep_analysis_orchestrator_node`는 제거된다. 챗은 job을 제출하고 이벤트 스트림을 구독한다.

### 5.3 resume 설계

Ledger가 **이미 단일 상태 저장소**다(P2). 따라서 resume은 새 상태 저장소가 아니라
**진입점 추가**다:

1. run_id로 Ledger에서 open 질문 + verified 클레임 복원
2. 라운드 루프 속행 (`while not should_stop`)
3. 이미 소비된 라운드 예산은 재지출하지 않는다 (`ledger.py:124`, `orchestrator.py:606`의
   기존 주석이 이 불변식을 이미 전제한다)

### 5.4 챗 API 계약 변경 ⚠️

이 단계는 **챗 API 계약을 바꾼다** — `final_response` 한 번에서 job 핸들 + 스트림으로.
**프론트엔드 변경이 필수다.** 별도 작업(FE 일관성/안정성 검토)과 조율해야 한다.

### 5.5 수용 기준 (AC)

- AC1. `POST /api/v1/deep-analysis`가 202 + run_id를 즉시 반환한다 (블로킹 없음)
- AC2. 챗 요청이 deep analysis 실행 중 블로킹되지 않는다 (R3 해소)
- AC3. `graph.py`에서 `_deep_analysis_orchestrator_node`가 제거된다
- AC4. 챗과 전용 API가 동일한 이벤트 스트림 계약을 사용한다 (R4 해소)
- AC5. 워커 크래시 후 resume이 중복 지출 없이 라운드를 속행한다 (R5 해소)
- AC6. 이벤트 로그 재생으로 진행 중 run에 늦게 접속해도 전체 이력을 받는다
- AC7. `DEEP_ANALYSIS_ENABLED=false`일 때 무회귀

---

## 6. 단계 순서와 근거

**skill 통합 → 재배치 → 분리**

| 순서 | 이유 |
|---|---|
| 1. skill 통합 | 가장 독립적. 품질 이득이 즉시 발생. 다른 단계에 의존하지 않는다 |
| 2. 재배치 | R1·R2를 해소해야 플래그를 안전하게 켤 수 있다. 분리 전에 라우팅이 정리돼야 한다 |
| 3. 분리 | 프론트엔드 변경을 요구하므로 마지막. 앞 두 단계가 끝나야 분리 대상이 명확하다 |

각 단계는 독립적으로 실행·검증 가능하다. 단계마다 별도 구현 계획을 작성한다.

---

## 7. 범위 밖 (YAGNI)

- **C안(껍데기 반전)** — LangGraph를 하네스로 완전 대체. `deep_analysis`는 research/analysis만
  다루고 generation·multimodal·mission을 못 한다. 지금 하면 범위가 무한정 커진다.
- **auto-mutation** — D19가 명시적으로 배제. L5는 관측/게이트만.
- **비용·지연시간 최적화** — 판정 기준이 아니다. Ray 병렬화 확대 등은 이 문서의 범위 밖.
- **skills를 retrieval 경로로 사용** — §3.3에 의해 배제. `fetch.py` 독점 유지.
- **`graph.py` 전면 리팩터링** — 단계 3에서 노드 하나가 빠지는 것 외에 손대지 않는다.

---

## 8. 리스크

| # | 리스크 | 완화 |
|---|---|---|
| K1 | 스킬 tool-calling이 `dig` 토큰 예산(12,000)을 압박 | 후보 스킬 수 상한. 셀렉터가 좁힘. 예산 초과 시 `flush_partial` 기존 경로 |
| K2 | 스킬 API 장애가 워커 실패로 전파 | 스킬 실패 → `web_search` 단독 fallback (AC7). 기존 `retry_handler`/`circuit_breaker` 재사용 검토 |
| K3 | 분류기 확장이 기존 라우팅에 회귀 유발 | 기존 intent 방출은 불변으로 두고 신규 intent만 추가. 회귀 테스트 필수 |
| K4 | 단계 3의 챗 계약 변경이 프론트와 어긋남 | FE 작업과 조율. FE 준비 전까지 플래그로 격리 |
| K5 | golden 게이트가 스킬 도입으로 깨짐 | cassette `"skill"` 종류 추가 + golden 재녹화. D19 절차 준수 |

---

## 9. 시작값과 재검토 지점

구현을 막지 않도록 기본값을 정한다. 아래는 **실측 후 조정 대상**이지 미결 사항이 아니다.

| 항목 | 시작값 | 재검토 조건 |
|---|---|---|
| 셀렉터 후보 스킬 수 상한 | **3개** (+ `web_search` 상시) | `dig` 토큰 예산(12,000) 초과율이 유의미하면 하향. K1 참조 |
| resume 트리거 | **Celery 재시도** (자동) | 크래시 후 자동 재개가 중복 지출을 유발하면 수동 API로 전환 |
| `hyper_deep`/`recursive` 구별 키워드 | 단계 2 구현 시 기존 `query_classifier.py:104-117` 키워드 맵과 동일한 패턴으로 작성 | 세 유형이 서로를 잠식하면 LLM 분류기로 승격 |

**구현 중 결정하고 `DECISIONS.md`에 기록할 것:**
- 스킬 어댑터의 정규화 실패(스킬이 URL 없는 결과 반환) 시 조용히 버릴 것인가, 이벤트로 남길 것인가
  → P4(모든 것은 이벤트 로그를 통과)를 고려하면 후자가 유력
