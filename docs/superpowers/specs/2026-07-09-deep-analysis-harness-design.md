# NEOS 심층 분석 하네스 — 통합 설계 스펙 (M0–M1)

**작성일:** 2026-07-09
**원본 설계:** [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../DEEP_ANALYSIS_HARNESS_DESIGN.md) (v1.1)
**대상:** NEOS 코드베이스에 "다중 루프 기반 하네스 아키텍처"를 신규 구현하는 코딩 에이전트
**상태:** 사용자 승인 완료 (2026-07-09) — 조건부 승인 3건 반영

> 이 스펙은 원 설계 문서를 NEOS 스택(FastAPI + PostgreSQL + async SQLAlchemy + Celery + LLMFactory)에
> 이식하기 위한 **통합 결정 사항**을 기술한다. 원 설계와 충돌하는 판단은 모두
> [neos/workflow/deep_analysis/DECISIONS.md](../../../neos/workflow/deep_analysis/DECISIONS.md)에 기록한다.
> 컴포넌트별 동작 규칙(§6), 데이터 모델 의미(§4.1/4.2), 프롬프트 명세(§7)는 **원 설계 문서가 정본(canonical)**이며
> 이 스펙은 그것을 대체하지 않고 NEOS 이식 계층만 추가한다.

---

## 0. 목표와 범위

루트 질문 하나를 받아 → 트리로 분해 → 병렬 워커로 조사 → 모든 클레임 검증 → 검증된 클레임만으로
인용 가능한 보고서를 생성하는 에이전틱 하네스를, NEOS 안에서 **신규 chat API + 신규 구현체**로 추가한다.
장기적으로 현재의 `neos/workflow/` LangGraph 방식을 이 루프 기반 방식으로 대체한다.

**이번 작업 범위: M0–M1 수직 슬라이스만.** (원 설계 §11.10: M1 완료 전 병렬화/에이전틱 채점 착수 금지.)

---

## 1. 사용자 승인 결정 (아키텍처 포크)

| # | 결정 | 근거 |
|---|---|---|
| D1 | **PostgreSQL 이식** (SQLite-per-run 아님) | NEOS 네이티브. 단일 작성자(P2)는 앱 레벨 + advisory lock으로 보존. |
| D2 | **NEOS 인프라 재사용 + 순수 LLM 콜러** | settings/web_search/cost_calculator 재사용. 단 LLM 호출은 LangChain 아닌 순수 async SDK 콜러(A5 요건 보존). |
| D3 | **M0–M1 수직 슬라이스 우선** | 원 설계의 마일스톤 순서 준수. |

## 1.1 조건부 승인에 붙은 필수 조건 (설계 위반과 동급)

1. **`UNIQUE (run_id, hash)`** — 원 설계의 전역 `hash UNIQUE`는 단일 실행 전제였다. run_id 멀티테넌시
   도입 시 전역 유니크로 두면 서로 다른 run이 같은 사실을 발견할 때 hash 충돌 → 증거 병합 + confidence
   상향이 **run 경계를 넘어** 발생한다(교차 검증 → 교차 오염). 반드시 `(run_id, hash)`로 스코프.
   **모든 원장 읽기 쿼리에 run_id 필터가 빠짐없이 걸리는지 리뷰 체크리스트 항목으로 강제.**
2. **`pg_advisory_xact_lock(hashtextextended(run_id, 0))`** — `commit_pass` 트랜잭션 진입 시 한 줄.
   run별 단일 작성자를 **DB 강제 불변식**으로 만든다. Celery 다중 프로세스 이전 시에도 그대로 살아남는다.
   `hashtext()`(int4)가 아닌 `hashtextextended()`(bigint)를 써서 run_id 간 32비트 락 키 충돌을 제거.
3. **blob 테이블 3규칙** — (a) **PK = `(run_id, content_hash)`** — content_hash=`sha256(raw_text)[:16]`,
   run 스코프. 같은 run 내 중복 fetch만 제거하고 run 간에는 별개 행(전역 PK는 run별 보존 정책과 충돌해
   댕글링 참조 유발 → DECISIONS D4), (b) **핫 패스에서 이 테이블 JOIN 금지** — raw는 채점기가
   `(run_id, content_hash)`로 단건 조회할 때만 읽는다(원 설계 §4 원칙 유지), (c) 보존 정책 — run 완료 +
   보고서 검증 후 해당 run의 raw 삭제 가능(excerpt는 evidence에 남으므로 종합/재현에 지장 없음).
4. **Celery 마이그레이션 리스크 2건을 DECISIONS.md에 지금 기록** — (a) 단일 작성자: advisory lock으로
   선제 해결, (b) **A1 partial 시맨틱은 Celery로 이전되지 않음** — `asyncio.wait_for` 취소는 같은
   프로세스라 `flush_partial()`이 버퍼에 닿지만, Celery 하드 타임아웃은 프로세스를 죽여 버퍼가 증발.
   해법은 그때 결정(soft time limit 핸들러 flush / 워커의 점진 체크포인트). 지금은 "M2 partial AC는
   Celery에서 재검증 필요"를 알려진 리스크로 못 박는다. 부수: 인라인 SSE 긴 run은 nginx
   `proxy_read_timeout`에 걸릴 수 있으니 dev 프로파일 밖 실행 전 확인.

---

## 2. 모듈 배치

신규 모듈 **`neos/workflow/deep_analysis/`** — 기존 `recursive/`, `hyper_deep/`, (무관한 계약검증)
`harness/`와 나란히 배치. `deep_analysis`로 명명해 `harness/`(출력 계약 검증) 및 `deep_research`(SSE 에이전트)와
충돌 회피. `workflow/` 하위에 두는 이유: 장기적으로 대체 대상이 `workflow/` 패키지 전체이기 때문.

```
neos/workflow/deep_analysis/
├── __init__.py
├── DECISIONS.md          # 원 설계와 충돌하는 모든 판단 기록 (모듈 로컬, 코드와 함께 이동)
├── llm.py                # 순수 async 콜러(Anthropic/OpenAI SDK). 방어적 JSON 파서 1곳 + usage 토큰 집계
├── config.py             # settings.DEEP_ANALYSIS_* 로드 + dev 프로파일 오버라이드
├── models.py             # §5 dataclass/Enum 전부
├── ledger.py             # Ledger — 유일한 작성자 (async SQLAlchemy)
├── budgeter.py           # M1: 스텁(k=1 SCOUT 고정). 전체 구현은 M2
├── orchestrator.py       # 메인 루프. M1: k=1, SCOUT-only, 병렬/에이전틱 없음
├── graders/
│   ├── __init__.py
│   └── deterministic.py  # 형식 진실성 게이트 (LLM 호출 금지)
├── worker.py             # investigate() + flush_partial()
├── synthesizer.py        # M1: 단층 리듀스
├── citation.py           # CitationRenderer (결정론)
├── fetch.py              # httpx fetch → HTML→텍스트(NFC) → blob 저장 + 메타
├── cassette.py           # LLM + fetch record/replay (A7). 골든 통합 테스트 인프라 겸용
└── prompts/
    ├── decompose.md
    ├── worker_brief.md
    ├── node_summary.md
    └── final_compose.md  # judge.md는 M3(에이전틱 채점)에서 추가
```

---

## 3. 데이터 모델 — PostgreSQL 이식

원 설계 §4 DDL의 5개 테이블 → NEOS 공유 DB에 async SQLAlchemy 모델. **`deep_analysis_` 접두어** +
`run_id` 컬럼으로 스코프. Alembic 마이그레이션은 `db/migrations/`.

### 3.1 테이블 (원 설계 컬럼 의미 그대로 + run_id)

- `deep_analysis_runs(id, root_question, profile, status, created_at, ...)` — run 메타(신설, 멀티테넌시 루트)
- `deep_analysis_questions(id, run_id, parent_id, text, status, depth, value_est, confidence, spent_tokens, cap_tokens, fail_streak)`
- `deep_analysis_claims(id, run_id, question_id, text, hash, status, confidence)` — **`UNIQUE (run_id, hash)`**
- `deep_analysis_evidence(id, run_id, claim_id, source_url, excerpt, raw_ref, det_grade, agent_grade)` — `raw_ref` = blob id
- `deep_analysis_feedback(id, run_id, claim_id, code, detail, salvage, attempt, resolved)`
- `deep_analysis_events(seq, run_id, ts, kind, qid, payload)` — append-only. **`BEFORE UPDATE OR DELETE`
  거부 트리거로 DB 강제**(원 설계 §11.3 → DECISIONS D8)
- `deep_analysis_blobs(run_id, content_hash, url, http_status, fetched_at, raw_text)` —
  **PK = `(run_id, content_hash)`**(§1.1-3a, DECISIONS D4)

원 설계의 상태 CHECK 제약, status 4상태(claims), 질문 상태기계(§4.1), 클레임 생애주기(§4.2)는 **원 설계 정본 그대로**.

### 3.2 이식 파생 규칙

- **run_id 필터 강제 (구조로):** `Ledger`는 생성자에서 run_id를 받고(`Ledger(session, run_id)`), 읽기
  메서드(`open_questions`, `children`, `verified_claims`, `pending_feedback`, `verified_summaries`,
  `gain_history`, `total_spent`, `get_claim`, `root_question`)는 **run_id를 인자로 받지 않는다** — 인스턴스가
  자기 run만 보므로 필터 누락이 타입 수준에서 불가능(P3의 앱 레이어 버전, DECISIONS D3).
- **단일 작성자 강제:** `commit_pass`는 트랜잭션 시작 시 `SELECT pg_advisory_xact_lock(hashtextextended(:run_id, 0))`.
  워커는 DB 세션을 절대 받지 않는다(P1/P2). Ledger만 세션 보유.
- **blob 보존:** `_finalize` 성공(report_graded ok) 후 해당 run의 blobs.raw_text를 NULL 처리 가능
  (M1에서는 보존, 정책 훅만 마련).

---

## 4. 순수 LLM 콜러 (`llm.py`)

LangChain 미사용. `AsyncAnthropic`/`AsyncOpenAI`(이미 pyproject 의존성: `anthropic==0.102.0`,
`openai==2.37.0`) 직접 사용. **A5 두 요건이 이 파일 안에 산다:**

1. **방어적 JSON 파서 단일화** — 코드펜스 제거 → 첫 `{`부터 마지막 `}`까지 절단 → `json.loads` →
   실패 시 1회 재요청 → 재실패 시 호출부에 예외. decompose/worker/judge/node_summary 전부 공유.
2. **usage 기반 토큰 집계** — 자체 추정 금지. `response.usage.input_tokens/output_tokens` 사용.
   예산 사다리 + gain_decay 전체가 이 숫자 위에 있음. NEOS `cost_calculator`에 연동.

모델 ID/API 키는 `settings`에서. (D2 준수: 인프라는 재사용, 콜 경로는 순수.)

---

## 5. 설정 (`settings.DEEP_ANALYSIS_*`)

원 설계 §8 `config.yaml` 상수 전부를 `DEEP_ANALYSIS_*` settings로 보존(기존 `RECURSIVE_*`/`HYPER_DEEP_*`
패턴). **dev 프로파일**(A7: `global_token_cap=20000, parallel_workers=2, max_depth=2`)을 요청별 선택 가능.
코드 내 매직넘버 금지(원 설계 §11.6).

---

## 6. 워커 도구 — 재사용 + 신규 fetch.py

- **탐색(discovery):** NEOS `neos/tools/tools/web_search.py`(`WebSearchMCPTool`) 재사용.
- **검색(retrieval):** 신규 `fetch.py`. NEOS `link_follower`는 *링크 추출*용이라 A2/A3가 요구하는
  HTML→텍스트(NFC 정규화)→blob+사이드카 메타를 만족하지 못함. 따라서 의도적으로 얇게 중복 구현:
  - fetch(httpx) → HTML→텍스트 1회 변환(이 텍스트를 blob에 저장, 워커는 반드시 이 텍스트에서 발췌 — A3)
  - blob row 생성: `id=sha256(raw_text)[:16], url, http_status, fetched_at, raw_text`
  - 사이드카 메타는 파일 대신 **컬럼**(url, http_status, fetched_at)으로 접음(A2). 채점기는 이 컬럼만 읽음.

`normalize_for_hash()`(클레임 hash용)와 `normalize_for_match()`(발췌 대조용)는 원 설계 A3대로 **다른 함수**로 분리.

---

## 7. Chat API 표면

신규 라우터 `neos/api/deep_analysis_routes.py` → `handlers/deep_analysis_handlers.py`, `main.py`에
**`POST /api/v1/deep-analysis`**로 등록. 기존 `deep_research` SSE 핸들러를 모델로 함.

- 요청: `{ question, conversation_id?, profile? }`
- **SSE 스트림.** 이벤트 타입은 `deep_analysis_events` 테이블 `kind`와 1:1 대응(`question_opened`,
  `pass_completed`, `claim_verified`, `synth_pass`, `report_graded`, ...). 원 설계의 이벤트 로그(P4)가
  곧 스트리밍 계약 — 관측과 API가 같은 정본.
- 최종 이벤트에 렌더된 보고서. `ChatService`로 conversation 연결(deep_research와 동일).
- **M1: 요청 태스크 내 인라인 실행**(dev 프로파일, 작은 캡). 상태가 events/ledger 테이블에 있으므로
  긴 run의 Celery 이전은 나중에 non-breaking하게 가능(리스크는 §1.1-4에 기록).

---

## 8. M0–M1 상세 범위 및 완료 기준(AC)

### M0. 뼈대
`models.py` + `Ledger` + Alembic 마이그레이션 + `config.py` + `recover()`.
- **AC-a:** 질문 `open→investigating→resolved` 전이 성공, 불법 전이는 예외.
- **AC-b:** 같은 `(run_id, hash)` 클레임 2회 커밋 시 evidence 병합 + `confidence = min(0.95, +0.15)`.
- **AC-c:** `recover()`가 `investigating`→`open` 복귀.
- **AC-d (이식 추가):** 다른 run_id의 같은 hash 클레임은 **병합되지 않음**(교차 오염 없음 검증).

### M1. 최소 수직 슬라이스
`Worker`(web_search + fetch.py) + `DeterministicGrader` + `Orchestrator`(k=1, SCOUT-only) +
단층 리듀스 + `CitationRenderer` + chat API + cassette 레이어.
- **AC-a:** 루트 질문 하나로 end-to-end 실행 → 모든 `[C:id]` 인용이 verified 클레임으로 해소되는 보고서 산출.
- **AC-b:** 조작된 excerpt가 실제로 `E_QUOTE_MISMATCH`로 잡힘.

### M2–M4로 명시 연기 (원 설계 §11.10)
Budgeter 점수/사다리, asyncio 병렬, SPLIT, AgenticGrader, feedback/repair 순환, 계층 리듀스,
충돌 처리, ReportGrader. (**M2 partial AC는 Celery 이전 시 재검증 필요 — §1.1-4b**)

---

## 9. 원 설계의 금지 사항(§11) + 부록 A는 전량 유효

원 설계 §11 금지 10항목과 부록 A(A1~A7)는 이 이식에서도 **본문과 동일한 구속력**을 가진다.
특히 A5(llm.py 단일화), A6(aging 인메모리 — DECISIONS.md 1번), A7(cassette 선구축)은 M0–M1에 직접 관련.

---

## 10. 테스트 전략 (원 설계 §10 + 이식 추가)

- **단위:** DeterministicGrader 전체 LLM 없이. `normalize_for_hash`/`normalize_for_match` 픽스처 전수.
- **계약:** FakeWorker(스크립트된 WorkerResult)로 Orchestrator↔Ledger 커밋 경로를 LLM 없이 검증.
- **골든 통합:** cassette(LLM+httpx 녹화)로 고정 질문 1개 end-to-end 스냅샷.
- **이식 추가:** run_id 격리 테스트 — 두 run이 같은 hash를 발견해도 병합/오염 없음(AC-M0-d).
