# NEOS 로드맵 🗺️

**최종 갱신:** 2026-07-17
**검증 방식:** 모든 항목을 코드로 확인했다. 근거 파일 경로를 각 항목에 단다.
확인하지 못한 것은 **미확인**으로 명시한다.
**관련 설계:** [`docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md`](superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md)
**방향성 논의:** [`docs/DIRECTION_260717.md`](DIRECTION_260717.md) — 이 문서는 "무엇을", 그쪽은 "왜"다.

---

## 📍 현재 상태 — NEOS가 지금 할 수 있는 것

### 실행 엔진 (4종 공존)

| 엔진 | 위치 | 방식 | 기본값 |
|---|---|---|---|
| **Workflow** | `neos/workflow/graph.py` (2,234줄) | LangGraph StateGraph, 노드 31 / 조건부 엣지 11 | 활성 |
| **Loop (deep_analysis)** | `neos/workflow/deep_analysis/` (3,464줄) | 예산 기반 라운드 루프, 검증된 클레임만 리포트 반영 | `enabled=False` |
| **HyperDeep** | `neos/workflow/hyper_deep/` + `neos/agents/search_agents/hyper_deep_research/` | ROMA 분해 + 무거운 leaf (Ralph 정제 루프) | `enabled=False` |
| **Recursive (ROMA)** | `neos/workflow/recursive/` (9 파일) | Python 재귀 분해, depth 기반 | `enabled=False` |

> ⚠️ deep 엔진 3종은 **모두 기본 비활성**이다 (`neos/config/schema.py:616, 579, 589`).
> 프로덕션 기본값에서 실제로 도는 것은 LangGraph workflow뿐이다.

### 검증형 분석 (deep_analysis loop) — NEOS의 핵심 차별점

- **결정론적 검증** (`neos/workflow/deep_analysis/graders/deterministic.py`):
  `E_NO_EVIDENCE`(증거 유무) / `E_SOURCE_DEAD`(HTTP 2xx 실제 fetch) /
  `E_QUOTE_MISMATCH`(발췌가 원문에 존재) / `E_CONFIDENCE_INFLATED`(출처 수로 confidence 상한)
- **append-only 이벤트 로그**: `deep_analysis_events` (`neos/database/deep_analysis_models.py:193`)
- **단일 상태 저장소 Ledger** + 예산 관리 Budgeter (`ledger.py`, `budgeter.py`)
- **record/replay cassette** — `"search"`/`"fetch"`/`"llm"` 레코드로 결정적 재생 (`cassette.py`)
- **L5 개선 신호 분석** — 이벤트 로그 read-only 집계 (`analytics.py`),
  주기 리포트 (`neos/tasks/deep_analysis_report_task.py`), API (`neos/api/handlers/deep_analysis_analytics_handlers.py`)
- 충돌 해소(`conflict.py`), 인용(`citation.py`), 합성(`synthesizer.py`)
- **의존성 4개뿐** — langgraph/langchain을 전혀 import하지 않는다 (프레임워크 프리)

### 스킬 시스템

- **빌트인 15종** (`neos/skills/builtin/`):
  연구 소스 10종 — `arxiv`, `google-scholar`, `openalex`, `pubmed`, `semantic-scholar`,
  `sec-edgar`, `news-api`, `reddit`, `wikipedia`, `github-search`
  기타 5종 — `canvas`, `cron`, `docx`, `pdf`, `research-assistant`
- **자동 발견** — `discover_skills(skills_dir: Path)`가 임의 디렉터리를 스캔
  (`SKILL.md` + `skill.py` 규약, `neos/skills/manager/auto_discovery.py`)
- **의존성 검사** — `neos/skills/manager/dependency_checker.py`
- ⚠️ 자동 발견은 **opt-in** — `skill_manager.py:28` `use_auto_discovery: bool = False` 기본

### 멀티모달 / 문서 처리

- **PDF** — PyMuPDF 주 파서 + PyPDF2 fallback (`pipelines/pdf_parser.py`, 470줄)
- **Word** — python-docx (`word_parser.py`, 295줄)
- **Excel** — openpyxl (`excel_parser.py`, 226줄)
- **PPT** — python-pptx (`ppt_parser.py`, 337줄)
- 이미지 / 텍스트 / CSV / 통합 컨텍스트 파이프라인 (`pipelines/`)
- 지식 그래프 추출·적재·검색 (아래 "최근 완료" 참조)

### API 표면 (`neos/api/handlers/` — 25개 핸들러)

chat / query / unified / rag_chat / similarity_chat / deep_research / async_research /
deep_analysis / deep_analysis_analytics / research_session / multimodal / document /
artifact / export / template / refinement / vote / analytics / skills /
**approval** / **autonomy** / **ui_submit(A2UI)** / **scheduled_tasks** / workflow_stream / auth

### 운영 기반

- **Celery** 4큐 (default/search/analysis/generation, 우선순위·라우팅) — `neos/workflow/celery_app.py:48-62`
- **Celery Beat** — `beat_schedule` (`celery_app.py:123`), cron 폴러 (`neos/tasks/scheduled_task_runner.py`)
- **Ray 분산** — `neos/workflow/ray_actors/` (7 파일), `recursive/distributed_orchestrator.py`
- **분산 추적** — Jaeger/OTLP (`neos/workflow/telemetry.py`, `neos/observability/core.py:125`)
- **Rate Limiting** — Sliding Window, Redis 기반 (`neos/utils/rate_limiter.py`)
- **Circuit Breaker** — `neos/utils/circuit_breaker.py`
- **캐시** — 시맨틱 캐시 / 스마트 캐시 매니저 / 무효화 (`neos/utils/semantic_cache.py` 외)
- **메모리 3종** — short_term / episodic / long_term + context_assembly (`neos/memory/`)
- **LLM 프로바이더 4종** — Anthropic / OpenAI / Gemini / Ollama (`neos/providers/`)

---

## ✅ 최근 완료 — 낡은 로드맵이 "미완료"로 표기했으나 실제로는 구현된 것

> 이전 로드맵은 아래 항목들을 전부 `[ ]`로 두고 있었다. 로드맵이 현실과 유리된 주된 원인이다.

### LLM Provider

| 항목 | 상태 | 근거 |
|---|---|---|
| **Google Gemini 통합** | ✅ 완료 | `neos/providers/gemini.py` |
| **Ollama — 로컬 모델 지원** | ✅ 완료 | `neos/providers/ollama.py` (`create_llm`/`list_models`/`validate_config`) |
| 프로바이더 확장 포인트 | ✅ 완료 | `neos/providers/base.py` `ModelProviderBase` ABC, `neos/utils/llm_factory.py` 레지스트리 위임 + `register_provider()` |

### 분산 시스템 (구 "2026 Q1")

| 항목 | 상태 | 근거 |
|---|---|---|
| **Celery 기반 작업 큐** | ✅ 완료 | `neos/workflow/celery_app.py` — 4큐/우선순위/`task_routes`(48-62), `neos/workflow/celery_tasks.py`, `neos/tasks/` |
| **장애 복구 및 재시도** | ✅ 완료 | `celery_app.py:64-71` (`task_max_retries=3`, `task_reject_on_worker_lost`, soft/hard 타임아웃), `neos/utils/circuit_breaker.py` |
| **분산 추적 (Jaeger/Zipkin)** | ✅ 완료 | `neos/workflow/telemetry.py` (Jaeger 백엔드), `neos/observability/core.py:123-126` (OTLP exporter), `neos/config/schema.py:490` |
| **에이전트 로드 밸런싱** | 🟡 부분 | `neos/workflow/distributed/` — `work_queue.py`, `supervisor.py`, `agent_registry.py`, `collaboration.py`(ContractNetProtocol), Ray `executor_pool.py`. Celery 큐 우선순위. **전용 로드밸런서는 없음** — 큐 우선순위 + Ray 풀로 대체 |

### 써드파티 통합 (구 "Q2-Q4")

| 항목 | 상태 | 근거 |
|---|---|---|
| **Slack 봇** | ✅ 완료 | `neos/api/channels/adapters/slack.py` |
| **Discord 봇** | ✅ 완료 | `neos/api/channels/adapters/discord.py` |
| **Telegram 봇** (로드맵에 없던 것) | ✅ 완료 | `neos/api/channels/adapters/telegram.py` |
| 채널 게이트웨이 / 어댑터 인터페이스 | ✅ 완료 | `neos/api/channels/gateway.py`, `base.py` (`ChannelMessage` 정규화) |

### 지식 그래프 — **수단은 바뀌었으나 목표는 달성**

| 항목 | 상태 | 근거 |
|---|---|---|
| **지식 그래프 구축** | ✅ 완료 (PostgreSQL) | `neos/database/models.py:237` `knowledge_graphs` 테이블, `neos/pipelines/document/knowledge_graph.py`(추출), `neos/services/kg_population_service.py`(적재) |
| **관계 기반 검색** | ✅ 완료 | `neos/services/kg_search_strategy.py`, `neos/config/schema.py:427` `KnowledgeGraphConfig` (`max_traversal_depth=2`, `search_weight=0.3`, `min_confidence=0.7`) |
| **Neo4j 연동** | ❌ 미채택 → 철회 권고 | grep 0건. 아래 "보류/철회" 참조 |
| **시각화 지원** | ⬜ 미확인 | API는 존재 (`get_document_knowledge_graph`, `neos/api/handlers/document_handlers.py`). 프론트엔드 시각화는 미확인 |

### 성능 및 보안

| 항목 | 상태 | 근거 |
|---|---|---|
| **API Rate Limiting** | ✅ 완료 (알고리즘 상이) | `neos/utils/rate_limiter.py` `RedisRateLimiter` — **Sliding Window** (토큰 버킷 아님). API키별/IP별, 초·분·시·일 단위 |
| 사용량 분석 | 🟡 부분 | `neos/api/handlers/analytics_handlers.py`, `neos/observability/` (Prometheus 메트릭) |
| 자동 스케일링 | ⬜ 미확인 | 코드 레벨 근거 없음. 인프라(K8s/HPA) 영역일 수 있음 |

### 문서 분석 (이전 로드맵이 `[x]`로 표기 — **검증 결과 정확**)

PDF/Word/Excel/PPT 파서 4종 모두 실제 라이브러리를 사용하는 구현체다 (위 "현재 상태" 참조).

---

## 🆕 로드맵에 아예 없었으나 구현된 자산

> 로드맵-현실 괴리의 나머지 절반. 지난 몇 달의 작업 대부분이 로드맵 **밖**에서 일어났다.

| 자산 | 근거 | 비고 |
|---|---|---|
| **deep_analysis 하네스** | `neos/workflow/deep_analysis/` (3,464줄), `neos/workflow/deep_analysis/DECISIONS.md`, `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md` | 검증형 분석의 본체 |
| **L5 개선 신호 분석** | `deep_analysis/analytics.py`, `neos/tasks/deep_analysis_report_task.py`, `docs/deep_analysis_l5.md` | 이벤트 로그 read-only 집계 |
| **ROMA 재귀 에이전트** | `neos/workflow/recursive/` (9 파일) | 태스크 분해 |
| **HyperDeep 리서치** | `neos/workflow/hyper_deep/`, `neos/agents/search_agents/hyper_deep_research/`, `docs/HYPER_DEEP_RESEARCH_WITH_RALPH_LOOP.md` | 장문 리포트 |
| **Ray 분산 실행** | `neos/workflow/ray_actors/` (7 파일), `recursive/distributed_orchestrator.py`, `docs/RAY_BASED_HDR.md` | sibling 병렬 |
| **워크플로우 하네스** | `neos/workflow/harness/` (14 파일) — `contract_builder.py`, `contract_compiler.py`, `checkers/`(citations/sources/freshness/metadata/model_based), `repair.py`, `trace.py`, `privacy.py`, `cache_policy.py`, `task_dag.py`. `docs/HARNESS_WHITEPAPER.md`, `docs/HARNESS_IMPLE.md` | **hyper_deep 전용 검증계** — deep_analysis graders와 별개 (아래 "보류/철회" K 항목) |
| **실행 승인 워크플로우** | `neos/api/handlers/approval_handlers.py` — 승인 응답, 스킬 allowlist, resume 스트리밍 | |
| **자율성 슬라이더** | `neos/workflow/enums.py:96-101` (`AutonomyLevel` MANUAL/ASSISTED/AUTONOMOUS), `neos/workflow/autonomy/policy.py`, `autonomy_handlers.py`, `docs/AGENT_CONTROL_SLIDER.md` | |
| **A2UI (UI 프레임)** | `neos/api/handlers/ui_submit_handlers.py`, `docs/NEOS_OPENCLAW.md` | 폼 생성 → 제출 → 워크플로우 재invoke |
| **OpenClaw cron 스케줄링** | `neos/skills/builtin/cron/`, `neos/tasks/scheduled_task_runner.py`, `neos/api/handlers/scheduled_tasks_handlers.py`, `db/migrations/023_add_scheduled_tasks.sql` | Celery Beat 1분 폴러 |
| **채널 어댑터 레이어** | `neos/api/channels/` | Slack/Discord/Telegram |
| **메모리 3종** | `neos/memory/` — short_term / episodic / long_term / context_assembly | |
| **시맨틱 캐시** | `neos/utils/semantic_cache.py`, `smart_cache_manager.py`, `cache_invalidation.py` | |
| **리포트 익스포트** | `neos/api/handlers/export_handlers.py` — markdown/html/pdf/canvas | |
| **Open Responses 호환** | `neos/api/models/open_responses.py`, `docs/OPEN_RESPONSES_SPEC.md` | |
| **코딩 에이전트** | `neos/coding/` (loop·model·sandbox·tools·workers·transport·outbox·persistence·repositories) + `neos/coding/managed/`(관리형 샌드박스 컨트롤 플레인), `db/migrations/038..046`, `docs/NEOS_CODING.md` | 플랜 14개 전부 완료. **기본 꺼짐** — `sandbox.enabled`·`coding_model.enabled` 둘 다 `False`. 출하 기준은 `DEEP_ANALYSIS_HARNESS_ROADMAP.md` §12.6의 E-S1~E-S4 |

> 📌 **코딩 에이전트 행은 2026-08-25에 추가됐다 (CA7).** 트랙 하나가 이 문서에
> 통째로 빠져 있었다 — `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §12가 70여 파일과
> 마이그레이션 아홉 개를 추적하는 동안 마스터 로드맵은 그것을 몰랐다. 이 표의
> 취지("로드맵 밖에서 일어난 작업")에 가장 정확히 해당하는 항목이면서 가장 늦게
> 실렸다.

---

## 🚧 진행 중 — Loop 아키텍처 통합 3단계

> **출처:** [`docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md`](superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md) (승인됨)
> **판정 기준:** 품질/정확도 + 유지보수성/복잡도. **비용·지연시간은 판정 기준이 아니다.**
> **목표:** `deep_analysis` loop을 1차 실행 모델로 승격

### 해소 대상 결함 (코드로 재확인함)

| # | 결함 | 근거 (직접 확인) |
|---|---|---|
| **R1** | **임계값 역전** — `DEEP_ANALYSIS_ENABLED=true`인 순간 hyper_deep·recursive의 complexity 경로가 **도달 불가능한 죽은 코드**가 된다 | `neos/workflow/routing/orchestrator_router.py:98-129`. deep_analysis 1순위 **0.5** → hyper_deep 2순위 0.85 → recursive 3순위 0.8. 0.5 이상을 1순위가 전부 흡수 |
| **R2** | intent 경로도 막힘 — 기본 키워드 분류기가 `HYPER_DEEP_RESEARCH`/`RECURSIVE_RESEARCH` intent를 방출하지 않음 | `neos/workflow/routing/query_classifier.py:104-117`, `QueryClassifierConfig.use_llm=False` |
| **R3** | **wall-clock 무한** — 챗 노드가 `orch.run()`을 타임아웃 없이 동기 완주 | `graph.py` `_deep_analysis_orchestrator_node`: `profile = "default"` 하드코딩 → `global_token_cap` **300,000** (`schema.py:635`). dev 프로파일 20,000(`schema.py:610`)의 **15배** |
| **R4** | 이벤트 싱크가 no-op — 챗이 claim 단위 이벤트를 전부 버림 | `graph.py`: `def sink(kind, payload): pass` |
| **R5** | resume 미구현 — 주석·훅은 있으나 재개 진입점 없음 | `deep_analysis/ledger.py:124`, `orchestrator.py:606` |
| **R6** | 세 엔진 모두 기본 비활성 | `schema.py:616`(deep_analysis), `:579`(recursive), `:589`(hyper_deep) 모두 `enabled: bool = False` |

### 단계 1 — Skill 통합 (다음 착수 대상)

**목표:** loop의 discovery 소스를 `web_search` 단독 → `web_search` + 스킬로 확장.
학술 1차 소스를 붙여 `source_tier` 분포를 올린다 (충돌 해소가 source_tier로 우열을 가리므로 품질 축에 직접 작용).

**핵심 결정 (스펙 §3):**
- 스킬은 **discovery 축에만** — retrieval은 `fetch.py`가 독점 (D6 확장)
- 도구 선택은 **워커 LLM**이 tool-calling으로 (P3 위반 아님 — 무결성 레버가 아니라 품질 레버)
- 2층 구조: 결정론적 셀렉터가 후보를 좁힘(상한 **3개** + `web_search` 상시) → 워커 LLM이 선택
- **`dig` effort부터** (`scout`의 token_cap 2,000에는 도구 스키마가 안 들어감)
- cassette 신규 종류 `"skill"` 추가 → 결정적 재생 유지 (D19 golden 게이트 보존)
- 주입 지점이 이미 열려 있음 — `service.build_orchestrator(..., search_fn=web_search)` (시그니처 변경 불필요)

**⚠️ 착수 전 스펙 보정 필요 (본 검증에서 발견 — 아래 "다음" N1 참조):**
스펙 AC4("URL을 반환하지 않는 스킬은 셀렉터가 후보에서 제외")를 `data["url"]` 유무로 순진하게 구현하면
**arxiv·pubmed·openalex — 스펙 §3.1이 통합 근거로 든 바로 그 학술 1차 소스 3종 — 이 전부 배제된다.**

### 단계 2 — 엔진 재배치

임계값이 아니라 **작업의 형태**로 라우팅 (R1·R2 해소):

| 엔진 | 역할 | 판별 기준 |
|---|---|---|
| **deep_analysis** | 검증형 분석 — "이 주장이 사실인가" | 검증이 필요한 질의 |
| **hyper_deep** | 장문 리포트 — "긴 보고서를 써라" | 분량·구조가 목적인 질의 |
| **recursive (ROMA)** | 일반 태스크 분해 — "여러 단계 작업을 수행하라" | 실행형 다단계 작업 |

작업: 분류기가 세 유형 intent를 방출하도록 확장(키워드·LLM 경로 **둘 다**) →
`OrchestratorRouter.route()`의 3중 if-체인을 유형 기반 단일 디스패치로 재작성 →
complexity는 "deep 엔진을 쓸지 말지"의 게이트로만 남김

### 단계 3 — 분리 (Job 서비스) ⚠️ **챗 API 계약 변경**

| | 현재 | 목표 |
|---|---|---|
| 제출 | 챗 노드가 블로킹 완주 | `POST /api/v1/deep-analysis` → run_id 즉시 반환 (202) |
| 실행 | 요청 스레드 인라인 | Celery 워커 |
| 진행 | 챗=no-op, API=인라인 SSE | `GET /api/v1/deep-analysis/{run_id}/events` — 이벤트 로그 재생 + 라이브 tail |
| 재개 | 없음 | Ledger에서 open 질문 복원 후 라운드 속행 |

- D7("M1은 인라인 asyncio + SSE, Celery는 나중") 갱신 — 이 단계가 그 "나중"
- D18을 **대체**한다 (모순이 아니라 예정된 승계). `_deep_analysis_orchestrator_node` 제거
- 현재 API는 인라인 SSE로 구현돼 있음 (`neos/api/handlers/deep_analysis_handlers.py:48` `start_deep_analysis`, `asyncio.Queue` 기반 `event_sink`) → 202+run_id 방식으로 전환
- **프론트엔드 변경 필수** (`web/` — Next.js). `web/hooks/use-chat-stream.ts` 등과 조율. FE 준비 전까지 플래그로 격리

### 순서 근거

**skill 통합 → 재배치 → 분리.**
①가장 독립적·품질 이득 즉시 → ②R1·R2를 해소해야 플래그를 안전하게 켤 수 있음 → ③FE 변경을 요구하므로 마지막

---

## ⏭️ 다음 — 근거 있는 제안

> 원칙: **이미 있는 자산에서 뻗어나오는 것만.** 각 항목에 왜 지금 / 의존 / 규모를 단다.

### N1. 스킬 URL 정규화 어댑터 — 🔴 단계 1의 선결 조건

**발견:** 연구 소스 10종이 **전부 URL을 반환하지만 키 규약이 7가지로 갈린다.**

| 스킬 | URL 필드 | `data["url"]`로 잡히나 |
|---|---|---|
| `semantic-scholar`, `sec-edgar`, `reddit`, `wikipedia`, `news-api`, `github-search` | `url` | ✅ |
| `google-scholar` | `url` + `link` | ✅ |
| **`arxiv`** | `entry_url`(abs 페이지), `pdf_url` | ❌ **배제됨** |
| **`pubmed`** | `pubmed_url` | ❌ **배제됨** |
| **`openalex`** | `oa_url`, `doi`, `landing_page_url`, `homepage_url` | ❌ **배제됨** |

스펙 §3.1은 "학술 1차 소스를 붙이면 source_tier가 올라간다"를 스킬 통합의 **근거**로 든다.
그런데 AC4를 문자 그대로 구현하면 그 근거인 arxiv·pubmed·openalex가 전부 탈락한다. **자기모순이다.**

**추가 발견 — `fetch.py`는 HTML 전용이다:**
`fetch_url`이 content-type 검사 없이 2xx면 무조건 `html_to_text(response.text)`를 돌린다
(`neos/workflow/deep_analysis/fetch.py:83-87`). PDF URL을 주면:
HTTP 200 → `E_SOURCE_DEAD` **미발동** → 바이너리가 mojibake로 디코딩 → 발췌 대조 실패 →
**`E_QUOTE_MISMATCH`로 클레임 기각**. 오류 코드가 원인을 오도한다.

이것이 실제 문제인 이유: `openalex/skill.py:142`가 `oa_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url")`로
**PDF를 우선**한다. arxiv도 `pdf_url`을 노출한다. 순진한 매핑은 조용히 실패한다.

**작업:** 스킬별 URL 매핑 테이블 (HTML 랜딩 페이지 **우선**, PDF 회피) + `image_url` 등 오선택 방지.
`openalex`는 `landing_page_url` → `doi`(→`https://doi.org/…`) 순, `arxiv`는 `entry_url`(abs).

- **왜 지금:** 단계 1 착수 즉시 막히는 지점. 스펙 AC4 보정도 함께
- **의존:** 없음 (단계 1의 일부로 선행)
- **규모:** 소 (매핑 테이블 10개 + 정규화 함수). 단 `fetch.py` PDF 지원까지 가면 중

### N2. `fetch.py` content-type 게이트

최소한 non-HTML content-type을 **명시적 코드로 기각**해야 한다 (`E_QUOTE_MISMATCH`로 오도되지 않게).
선택지: (a) content-type 화이트리스트 → 비HTML은 전용 코드로 기각, (b) PDF 텍스트 추출 추가
(`pipelines/pdf_parser.py`의 PyMuPDF를 이미 보유 — 재사용 가능).

- **왜 지금:** N1과 같은 뿌리. (b)를 택하면 학술 PDF가 1급 증거원이 되어 §3.1의 품질 논거가 완성된다
- **의존:** N1과 동반. `fetch.py`는 D6상 retrieval 독점 지점이라 변경 영향이 국소적
- **규모:** (a) 소 / (b) 중. **(a)를 먼저** — P4(모든 것은 이벤트 로그를 통과)에 맞춰 기각을 이벤트로 남긴다

### N3. 오디오 STT 완결

**현황:** 파이프라인 뼈대·MIME 라우팅·레지스트리 등록이 **이미 끝나 있다.**
`multimodal_workflow.py:49` `registry.register(InputType.AUDIO, AudioPipeline())`,
`pipelines/router.py:50-53` (audio/mpeg·mp3·wav·ogg), `audio_pipeline.py` 214줄 —
분석·요약·인사이트 로직까지 작성됨.
**막힌 곳은 함수 하나다:** `_speech_to_text()`가 `"Speech-to-text not yet implemented"`를 반환
(`audio_pipeline.py:183`).

- **왜 지금:** 잔여 작업이 국소적(함수 1개). 이미 `neos/providers/ollama.py`가 있어 로컬 Whisper 옵션도 열림
- **의존:** 없음
- **규모:** 소~중 (Whisper API 연결) — 로드맵의 "오디오 요약"·"다국어"는 STT가 붙는 순간 대부분 따라온다

### N4. 감사 로그 — 이벤트 로그 패턴 재사용

`deep_analysis_events`가 이미 append-only이고 `analytics.py`가 **read-only 집계 패턴**을 확립했다
("This service NEVER writes to the event log"). 같은 패턴을 API 호출 축에 적용한다.

- **왜 지금:** 패턴이 이미 검증됨. 단계 3이 이벤트 스트림을 1급 계약으로 만들면 감사 로그는 그 위의 소비자
- **의존:** 단계 3과 이벤트 스키마 정합. `Organization` 모델(N5)과 결합해야 의미가 큼
- **규모:** 중

### N5. 다중 테넌시 **강제**

**현황이 위험하다:** `Organization`(`models.py:388-449`), `OrganizationAdmin`,
`usage_quota`/`usage_current` JSONB, `billing_customer_id`가 **전부 정의돼 있으나**,
`organization_id`의 실사용처는 `neos/api/services/oauth_service.py:202` — **신규 가입 시 할당 한 줄뿐이다.**
어떤 쿼리도 org로 스코핑되지 않는다. 즉 **모델은 다중 테넌시처럼 보이지만 격리는 없다.**

- **왜 지금:** "모델이 있으니 된다"는 착각이 실제 격리 부재보다 위험하다. 명시적 판단이 필요
- **의존:** N4(감사 로그)와 같이 가야 함. `rate_limiter.py`의 쿼터와 `usage_quota` 연결
- **규모:** 중~대 (모든 데이터 접근 경로 스코핑 — 회귀 위험 높음)

### N6. 플러그인 시스템 = 외부 스킬 디렉터리

**로더가 이미 완성돼 있다.** `discover_skills(skills_dir: Path)`는 임의 경로를 받아
`SKILL.md` + `skill.py` 규약으로 스캔하고, `dependency_checker.py`가 의존성을 검사한다.
남은 것은 마켓플레이스가 아니라 **(a) 외부 경로 설정 노출, (b) 신뢰·샌드박싱, (c) 버저닝**이다.
샌드박싱 자산도 일부 있다 — `ray_actors/sandbox_executor.py`(RestrictedPython), `sandboxed_executor.py`.

- **왜 지금:** 단계 1이 스킬을 loop의 1급 discovery 소스로 만들면, 외부 스킬 = 외부 지식원이 된다.
  N1의 URL 계약이 외부 스킬에도 그대로 적용되므로 계약이 먼저 서야 한다
- **의존:** 단계 1 + N1 (URL 정규화 계약)
- **규모:** 중 — 실질 비용은 로더가 아니라 **샌드박싱·신뢰 모델**이다. 그 전엔 "내부 전용 외부 디렉터리"로 한정 권고

### N7. L5 신호 → golden 회귀 연결

`analytics.py`가 개선 신호를 내고 D19는 auto-mutation을 명시적으로 배제했다(관측/게이트만).
사람이 읽는 주기 리포트는 `tasks/deep_analysis_report_task.py`로 이미 있다.
다음 자연스러운 한 걸음은 **신호를 golden 회귀 게이트와 연결**하는 것 —
`E_QUOTE_MISMATCH`/`E_CONFIDENCE_INFLATED` 빈도가 유의미하게 오르면 게이트가 잡도록.

- **왜 지금:** 단계 1이 discovery 소스를 바꾸면 검증 실패율 분포가 이동한다. 그 변화를 관측할 계기가 필요
- **의존:** 단계 1 (cassette `"skill"` + golden 재녹화)
- **규모:** 소

### N8. 첨부 → LLM 멀티모달 입력 (FE↔BE 감사 #4b) — ✅ **종결 (2026-09-06)**

**무엇이 닫혔나.** 첨부가 실제로 모델에 도달한다. 정책은 `neos/services/attachment_blocks.py`
하나에 있고(분류·거부 게이트·해석·상한·렌더), `chat_llm_service` 의 **세 메시지 조립 사본이
전부** 그것을 부른다 — 넷째가 생기면 빨개지는 가드 테스트가 붙어 있다. 카탈로그에 `vision`
플래그가 생겼고 그 유일한 독자는 거부 게이트다. 이미지 4종·PDF 는 원본으로, TXT·MD 는 텍스트
블록으로, DOC/DOCX 는 `word_parser` 추출 텍스트로 간다. vision 없는 모델에 이미지·PDF 를
붙이면 스트림은 `code:"attachment_unsupported"` 로, 비스트림은 422 로 **이유와 함께 거부한다.**
설계는 `docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`,
계획은 `docs/superpowers/plans/2026-09-05-n8-attachment-multimodal.md`.

**설계 결정 다섯 중 둘은 코드가 이미 답을 갖고 있었다** — 프로바이더별 블록 조립은 필요 없었고
(LangChain 표준 블록 + 프로바이더 번역기), URL 전달은 애초에 불가능했다(`storage_url` 이
`s3://`·`file://`). 나머지 셋만 실제 결정이었다.

> 🔴 **이 기능은 병합 직전까지 테스트 밖에서 동작한 적이 없었다.** 최종 전체 브랜치 리뷰가
> 잡았다 — `multimodal-input.tsx` 가 업로드 응답에서 `pathname` 을 구조분해하는데 라우트는
> `name` 을 돌려주므로 `filename` 이 통째로 빠지고, `postRequestBodySchema` 의
> `filename: z.string().min(1)` 이 **첨부 달린 채팅 요청 전체를 400 으로 거부**했다. 선재
> 결함이고 한 줄이었다. 태스크별 리뷰는 여섯 번 다 통과했는데, 이음매를 보는 리뷰만이 이것을
> 볼 수 있었다. 이제 업로드 라우트의 **실제 응답 모양**을 **실제 스키마**에 통과시키는
> e2e 테스트가 `web/tests/source/attachment-upload-to-chat-schema.test.ts` 에 있다.

> 🔴 **그리고 통과한 리뷰 여덟 번이 보안 결함 하나를 놓쳤다 (2026-09-10).**
> 검증 절차를 다시 돌리자 `_load_document` 가 클라이언트가 준 `documentId`(작은
> 순차 PK)로 `Document` 를 조회하면서 **소유권을 검사하지 않는다**는 것이 나왔다.
> 저장소에는 이미 강제 패턴이 있었고(`get_owned_document`, `document_service` 의
> `user_id` 필터) 첨부 경로만 그것을 우회했다 — 자기 대화에 남의 문서 id 를 넣어
> 그 내용을 모델에게 읽히는 것이 가능했다. `resolve_attachments` 가 대화 소유자를
> 받아 두 조회 모두 거르고, 소유하지 않은 문서는 **없는 문서와 구별되지 않는다**
> (존재를 확인해주지 않기 위해서다). 태스크별 리뷰도 전체 브랜치 리뷰도 이것을
> 보지 못했다 — 과거 커밋이 세운 규약을 읽는 **git 이력 렌즈**만이 잡았다.
>
> 그 수정을 검증하니 이번엔 **테스트가 수정을 지키지 못하고 있었다.** 단언이
> `"user_id" in str(stmt)` 였는데 그건 WHERE 절이 없어도 SELECT 컬럼 목록만으로
> 참이라, 필터 두 줄을 지워도 19개가 전부 초록이었다. 지금은 컴파일된 SQL 의
> WHERE 를 보고, 필터를 지우면 3개가 빨개진다.

**이후 닫은 것 (2026-09-06 ~ 09-11).**

- ✅ **소유권 검사** — `resolve_attachments(…, owner_user_id)`, 두 조회 경로 모두 필터
- ✅ **게이트 범위** — 대화 전체가 아니라 **현재 턴**의 첨부만 판정한다. 예전에는
  이미지를 한 번 올린 대화를 vision 없는 모델로 바꾸면 텍스트 질문까지 영구히 막혔다
- ✅ **거부가 모든 경로에 도달** — similarity 챗 경로가 오류 청크를 빈 content 로
  둔갑시키던 것을 고쳤다(`chat_message_processor`), 세 엔드포인트에 422 매핑 추가
- ✅ **`attachment_notices` 가 화면까지** — 비스트림 핸들러가 버리던 것을 실었고,
  프론트가 어시스턴트 메시지 위에 사유를 그린다. 값은 통과 경로를 믿지 않고
  `attachmentNoticesFromMessageMetadata` 가 모양을 확정한 뒤 넘긴다
- ✅ **거부 `code` 전달** — 디스패처가 `attachment_unsupported` 를 흘리지 않는다
- ✅ **클라이언트 입력 방어** — `documentId`·`metadata`·`name` 이 잘못된 타입이면
  500 이 아니라 §4.5 의 거부/강등으로 간다. 세 번 같은 모양으로 터졌기에 잘못된
  필드 표를 훑는 테스트를 두어 네 번째를 막는다
- ✅ **예산 우회** — EXTRACT(Word 추출 텍스트)도 UTF-8 바이트로 예산에 계상된다
- ✅ **Ollama 오거부** — `model_known()` 이 "모른다"와 "못 한다"를 가른다. 카탈로그가
  아는 모델이 `vision: false` 일 때만 거부하고, 모르는 모델은 프로바이더가 말한다
- ✅ **사본 가드 확장** — 이름 두 개·`for` 문만 보던 것을 `…messages` 전반과
  컴프리헨션까지 넓혔다. 그 과정에서 걸린 비조립기 둘은 "독자"로 따로 기록해,
  새 이름이 나오면 사람이 조립기인지 독자인지 판정하게 만들었다
- ✅ **(b) 고아 API 삭제** — `/api/v1/multimodal/*` 네 라우트와 핸들러·서비스를 지웠다
- ✅ **(c) `supports_video` 제거** — 읽는 곳 없는 필드를 카탈로그에서 뺐다
- ✅ `lru_cache` 오염, `int(document_id)` 500, 빈 추출 텍스트의 조용한 소실

**남은 것.**

- 🟡 `multimodal_workflow` · `ImagePipeline` · `pipelines/vision/` 은 HTTP 진입점이
  사라져 **현재 아무도 import 하지 않는다.** 지우지 않기로 한 결정이며 해당 모듈
  상단에 그 사실과 날짜가 적혀 있다 — 방치와 구별하기 위해서다
- 🟡 사본 가드는 여전히 `chat_llm_service` **한 모듈 안**만 본다. 다른 모듈에 생긴
  조립 사본은 잡지 못한다 — 넓히려면 별개 작업이다

---

**착수 당시 현황:** 첨부 왕복은 **프론트와 DB까지만** 닫혀 있다. 업로드
(`app/(chat)/api/files/upload/route.ts`) → `extractAttachments`
(`web/lib/message-parts.ts:81`) → BE `MessageAttachment`(`chat_models.py:131`) 저장
(`chat_stream_pipeline.py:180`) → 새로고침 시 file 파트로 복원
(`web/lib/utils.ts`)까지 동작하고 화면에도 파일명과 함께 뜬다.

**끊긴 곳은 모델 직전이다.** `chat_llm_service._build_messages`
(`neos/services/chat_llm_service.py:88-97`)가 각 메시지에서 `role`과 `content`만 읽고
나머지를 버린다. `neos/services/chat_llm_service.py`와 `neos/providers/` 어디에도
image·vision·base64·media 처리가 **한 줄도 없다**(2026-09-04 확인). 즉 사용자가 붙인
파일은 저장되고 보이지만 **모델은 한 번도 본 적이 없다.**

배선을 잇는 작업이 아니라 프로바이더별 멀티모달 입력 지원을 **챗 경로에** 새로 만드는
작업이며(⚠️ 저장소 전체로는 백지가 아니다 — 아래 (a)), 착수 전에 정해야 할 것이 다음처럼
여럿이다:

- **프로바이더별 content block 포맷** — Anthropic과 OpenAI의 이미지 블록 모양이 다르다.
  `ModelProviderBase` 계약을 어디까지 공통화할지가 첫 갈림길 ‖ ⚠️ **아래 (a)가 이 질문을 바꾼다**
- **모델별 지원 여부** — 카탈로그가 모델 사실의 단일 원천이므로 `vision` 류 능력 플래그는
  `neos/config/models.yaml`에 두는 것이 `selectable`과 일관된다 ‖ ⚠️ **아래 (c): 그 자리에
  이미 죽은 선례가 있다**
- **이미지 대 문서 분기** — 허용 MIME 9종 중 PDF·DOCX·TXT·MD는 이미지가 아니다.
  텍스트 추출(`pipelines/`의 기존 파서 재사용) 대 원본 첨부 중 무엇을 보낼 것인가
- **URL 대 base64** — 저장이 S3/RustFS `storage_url`이라 프로바이더가 URL을 받는지,
  받더라도 서명 URL 수명이 요청보다 긴지
- **미지원 모델 fallback** — 첨부가 있는 대화에서 vision 미지원 모델을 고르면
  거부할 것인가, 텍스트만 보낼 것인가, 조용히 무시할 것인가

**그러나 백지에서 시작하는 작업이 아니다 (2026-09-05 실측).** 위 문단이 겨눈
`neos/providers/`와 `chat_llm_service.py` 밖에 **이미 완성돼 돌아가는 멀티모달 층이 따로
있다.** 다음 넷이 앞의 설계 결정 다섯 개의 값을 바꾼다 — 그러므로 brainstorming은 백지가
아니라 이 넷에서 출발한다.

- **(a) 프로바이더별 이미지 블록 조립은 이미 세 벌 있다.** `neos/workflow/pipelines/vision/`의
  `vision_claude.py`·`vision_gpt4o.py`·`vision_gemini.py`가 각자 SDK를 직접 부르고,
  `image_pipeline.py:21,221`이 `VisionModelFactory`로 그중 하나를 고른다. 모델 ID는 셋 다
  `get_vision_model_id()`로 카탈로그에서 읽는다(하드코딩 아님). `neos/providers/`에 한 줄도
  없다는 서술은 그대로 맞지만 **저장소에 없다는 뜻은 아니다.** 다만 이들은 SDK 직호출이고
  챗 경로는 LangChain 메시지 계약이라 그대로는 못 쓴다 → **첫 갈림길은 "공통화를 어디까지"가
  아니라 "두 층을 합칠까, 나란히 둘까"다.** 나란히 두면 프로바이더별 블록 조립 사본이
  둘이 된다 — `DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7 WORKSPACE1이 아홉 사본을 하나로 모은
  것과 같은 범주의 부채를 새로 만드는 선택이다
- **(b) 그 층은 라이브인데 아무도 부르지 않는다.** `/api/v1/multimodal/query`·`/image/analyze`·
  `/supported-types`가 `main.py:576`으로 마운트돼 있고 셋 다 `get_current_active_user`를
  문다(`multimodal_handlers.py:35,128,195`). 그런데 `web/` 전체에서 이 경로를 호출하는 코드가
  **한 건도 없다** — FE의 "multimodal"은 전부 `multimodal-input.tsx`라는 컴포넌트 이름이다.
  즉 이미지 → 모델 경로는 **존재하되 아무도 밟지 않는 고아 표면**이고, N8은 첨부를 그 표면으로
  보낼지(`MultimodalService` 재사용) 챗 안에 두 번째 경로를 낼지를 함께 정해야 한다
- **(c) 능력 플래그 선례가 이미 카탈로그에 있고, 죽어 있다.** `models.yaml:178`의
  `gemini-1.5-pro-latest`가 `supports_video: true`를 갖는다. `ModelSpec`이 파싱하고
  (`model_config.py:73`), 레거시 필드 목록에도 실려 있고(`:260`), 테스트가 값까지 지키는데
  (`tests/config/test_model_catalog.py:211`) **프로덕션에서 읽는 코드가 0건이다.** 그러므로
  `vision` 플래그의 질문은 "어디에 둘까"가 아니라 **"읽는 곳 없이 스키마에만 사는 플래그를
  하나 더 만들지 않으려면 무엇이 그것을 읽어야 하는가"**다. 낡은 면제 플래그가 가드를 조용히
  끄는 것과 같은 실패 모양이다
- **(d) Vision 기본 모델이 한 세대 뒤에 있다.** `models.yaml:294`의 `defaults.vision`이
  `gpt4o → gpt-4o`이고 이 항목은 `selectable: false`인 레거시다. Gemini 별칭도
  `gemini-1.5-pro-latest`다. 챗은 `claude-sonnet-5`/`gpt-5.6` 세대를 쓰는데 **이미지 분석만
  옛 세대로 돈다.** 첨부를 챗에 이으면 한 대화 안에서 두 세대가 섞인다 — 별칭을 올릴 것인가,
  첨부 경로는 사용자가 고른 챗 모델을 그대로 쓸 것인가. (a)와 같은 결정의 다른 얼굴이다

- **왜 지금은 아닌가:** 위 다섯이 전부 설계 결정이라 구현부터 시작하면 되돌리기 비싸다.
  brainstorming으로 설계를 먼저 확정할 것 — 출발점은 (a)~(d)
- **의존:** 없음(기능적으로는 독립). 다만 `_build_messages`를 건드리므로
  LLM 입력을 만지는 다른 작업과 같은 시기에 하지 않는 편이 안전하다
- **규모:** 중~대 ‖ ⚠️ **재추정 대상 (2026-09-05).** (a)를 어느 쪽으로 정하느냐에 따라
  규모가 양방향으로 움직인다 — 기존 `vision/` 구현을 챗 계약으로 끌어올리면 프로바이더별
  조립을 새로 짓지 않으므로 **줄고**, 나란히 두기로 하면 사본 하나를 더 유지하는 값이
  붙어 **는다.** 설계 확정 전의 "중~대"는 두 경우를 합친 폭이다

### 우선순위 요약

| 순위 | 항목 | 규모 | 차단 요소 |
|---|---|---|---|
| 1 | **N1** 스킬 URL 정규화 + 스펙 AC4 보정 | 소 | 없음 — **단계 1의 선결 조건** |
| 2 | **N2(a)** fetch content-type 게이트 | 소 | N1과 동반 |
| 3 | **단계 1** Skill 통합 | 중 | N1 |
| 4 | **N7** L5 → golden 연결 | 소 | 단계 1 |
| 5 | **단계 2** 엔진 재배치 | 중 | 없음 (단계 1과 병렬 가능) |
| 6 | **N3** 오디오 STT | 소~중 | 없음 (독립) |
| ~~7~~ | ~~**N8** 첨부 → LLM 멀티모달 입력~~ | — | ✅ **2026-09-06 종결** (10 커밋 + 최종 수정 웨이브) |
| 8 | **단계 3** 분리 (Job 서비스) | 대 | 단계 1·2 + **FE 조율** |
| 9 | **N4+N5** 감사 로그 + 테넌시 강제 | 대 | 단계 3 |
| 10 | **N6** 플러그인(외부 스킬) | 중 | 단계 1 + N1 |

---

## 🛑 보류 / 철회

### 철회 권고

| 항목 | 판단 | 이유 |
|---|---|---|
| **Neo4j 연동** | ❌ 철회 | 목표(지식 그래프·관계 기반 검색)는 **PostgreSQL로 이미 달성**됐다 (`knowledge_graphs` 테이블, `kg_search_strategy.py`, `max_traversal_depth=2`). Neo4j 도입은 **운영 DB를 하나 더 늘리는 것** — 통합 스펙의 판정 기준이 "유지보수성/복잡도"이므로 정면 충돌한다. pgvector와 같은 DB에 있다는 이점도 잃는다. *재검토 조건:* traversal depth 2로 부족한 질의 패턴이 실측되면 |
| **토큰 버킷 알고리즘** | ❌ 철회 | 목표(rate limiting)는 **Sliding Window로 달성**됐다 (`rate_limiter.py` — "Fixed Window보다 정확, sorted set으로 메모리 효율적, 분산 환경 지원"). 알고리즘 교체의 근거가 없다. 로드맵이 목표가 아니라 **수단**을 항목으로 적었던 사례 |
| **Cohere 통합** | ❌ 철회 권고 | `pyproject.toml:84`에 `cohere>=5.0.0` **의존성만 선언**돼 있고 `neos/providers/`에 구현이 없다. 프로바이더 4종(Anthropic/OpenAI/Gemini/Ollama)이 이미 있고 Cohere의 고유 이점이 불명확하다. 확장 포인트(`ModelProviderBase`)가 열려 있으므로 필요해지면 언제든 추가 가능 — 로드맵 항목으로 유지할 이유가 없다. **미사용 의존성 정리 권고** |

### 방향 충돌로 보류

| 항목 | 판단 | 이유 |
|---|---|---|
| **고급 워크플로우 빌더 UI** (드래그앤드롭) | 🛑 보류 — 방향 충돌 | 통합 스펙의 방향은 **loop 승격**이다. loop은 예산 기반 자율 라운드 루프(`while not should_stop`)이지 사용자가 배선하는 DAG가 아니다. "사용자가 그래프를 그린다"는 모델은 승격 방향과 **상충**한다. 게다가 §7이 `graph.py` 전면 리팩터링을 YAGNI로 배제했다. *재검토 조건:* 단계 3 이후 엔진 역할이 확정되면 |
| **자동 워크플로우 생성 / Few-shot Learning / 사용 패턴 학습** | 🛑 보류 — 방향 충돌 | **D19가 auto-mutation을 명시적으로 배제**했다 (L5는 관측/게이트만). "AI가 워크플로우를 자동 생성·최적화"는 그 결정과 정면 충돌한다. 코드 근거도 0건(grep) |
| **실시간 협업** (다중 사용자 세션/공유/워크스페이스/권한) | 🛑 보류 | 코드 0건. `distributed/collaboration.py`는 **에이전트 간** Contract Net Protocol이지 사용자 협업이 아니다 — 이름이 오해를 부른다. **단계 3이 챗 API 계약을 바꾸므로**(`final_response` → job 핸들 + 이벤트 스트림) 그 전에 착수하면 두 번 만든다. *재검토 조건:* 단계 3 완료 후 |
| **영상 분석 에이전트** | 🛑 보류 | 현재 `InputType.VIDEO`는 **MIME/확장자 매핑만** 존재하고(`pipelines/router.py:58-62, 95-99`) **핸들러 파이프라인이 없다**(grep: router.py 외 0건) — 영상 업로드 시 라우팅 불가. 오디오 STT(N3)도 미완인 상태에서 영상은 더 크다(프레임 추출+자막+요약 = STT 포함). **N3 완료 후 재평가** |
| **Zapier / Notion / Confluence 통합** | 🛑 보류 | grep 0건. 단, 채널 어댑터 레이어(`neos/api/channels/base.py` `ChannelAdapterBase`)가 확장 포인트로 이미 있어 착수 비용은 낮다. **수요 근거가 나오면** 착수 — 유행 기능으로 선제 구현할 이유 없음 |
| **Ollama 모델 다운로드 관리 / 프라이버시 모드** | 🛑 보류 | `providers/ollama.py`에 pull/download 없음. `harness/privacy.py`는 존재하나 **다른 목적**(하네스 프라이버시)이며 "프라이버시 모드"와의 관계 **미확인**. 온프레미스 배포 옵션도 미확인 — 인프라 영역일 수 있음 |
| **모델 간 자동 전환** | 🛑 보류 | grep 0건 (`fallback_model`/`auto_switch` 등). 확장 포인트(`ModelProviderBase`, `LLMFactory._providers` 레지스트리)는 열려 있음 |
| **플러그인 마켓플레이스 / 커뮤니티 플러그인** | 🛑 보류 | N6(외부 스킬 디렉터리)이 선행. 마켓플레이스는 **신뢰·샌드박싱이 풀린 뒤의 문제**다. 순서를 거꾸로 잡으면 안 됨 |
| **컴플라이언스 리포트 / 데이터 보존 정책** | 🛑 보류 | 보존 설정은 `trace_retention_days: int = 30` (`schema.py:346`) **하나뿐**. N4(감사 로그)가 선행 |

### 재검토 필요 (신규 제기)

| 항목 | 이유 |
|---|---|
| **검증 시스템 이중화** | `neos/workflow/harness/checkers/`(hyper_deep 리포트용 — citations/sources/freshness/metadata/model_based + `repair.py`)와 `neos/workflow/deep_analysis/graders/`(claim용 — deterministic/agentic/report)가 **별개의 검증계**다. 통합 스펙의 판정 기준이 유지보수성이므로 이 중복은 **계상 대상**이다. 단, 스펙 §1.1의 "4개 패러다임" 표에 harness는 없다 — 진단 범위 밖이었다. **단계 2가 엔진 역할을 가른 뒤**(deep_analysis=검증형 / hyper_deep=장문 리포트) 두 검증계의 경계가 명확해지면 "통합 vs 명시적 분리"를 결정할 수 있다. 지금 결정하기엔 근거 부족 — **단계 2 이후 재검토**. 규모 중~대 |
| **`docs/NEOS_BACKEND_ARCHITECTURE.md` 부재** | 이 문서는 **존재하지 않는다.** 커밋 `b200ab6` "delete all outdated docs"로 삭제됐다(`cc1e2c5`에서 작성 후 여러 차례 갱신되다 삭제). 아키텍처 전반을 서술하는 단일 문서가 현재 없고, `docs/` 25개 문서가 기능별로 흩어져 있다. 로드맵-현실 괴리의 **구조적 원인 중 하나**로 보인다 — 갱신 지점이 없으면 문서는 낡는다. 재작성 여부 판단 필요 |

---

## 부록 — 검증 방법

각 항목은 아래 방식으로 확인했다. **"미확인"은 확인하지 못했다는 뜻이지 미구현이라는 뜻이 아니다.**

- 파일 존재 — `ls`, `find`
- 실구현 vs 스텁 — 파서/엔진의 실제 라이브러리 import 및 반환값 확인
  (예: `audio_pipeline.py`는 파일이 존재하지만 `_speech_to_text`가 스텁 — **파일 존재만으로 판정하면 오판한다**)
- 연동 여부 — grep (Neo4j, Cohere, 모델 자동 전환 등)
- 등록/라우팅 — 레지스트리 등록 지점 확인 (`registry.register(InputType.AUDIO, ...)`)
- 실사용 — 필드/모델이 정의만 됐는지 실제로 쓰이는지 (예: `organization_id`는 정의는 있으나 실사용처 1곳)
