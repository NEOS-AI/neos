# DECISIONS — 심층 분석 하네스 (NEOS 이식)

원 설계 [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../../docs/DEEP_ANALYSIS_HARNESS_DESIGN.md)와 충돌하거나
그 문서가 명시적으로 위임한 판단을 기록한다. 원 설계 §655 지시("구현 중 이 문서와 충돌하는 판단이
필요하면 §1의 5원칙으로 결정하고, 결정 내용을 코드 주석이 아니라 별도 DECISIONS.md에 기록") 및
부록 A6의 "DECISIONS.md 1번 항목" 요구를 이행한다.

각 결정은 **결정 / 근거 / 원 설계 대비 이탈 / 영향** 순으로 기술한다.

---

## D1. aging 상태는 인메모리 (원 설계 A6이 요구한 1번 항목)

**결정:** 점수 함수 `aging(q)`의 "마지막 선택 라운드"는 DDL/스키마에 저장하지 않고 Budgeter의 인메모리
상태(라운드 카운터 + `{qid: last_selected_round}` dict)로 구현.
**근거:** 원 설계 A6. aging은 기아 방지용 소프트 신호라 크래시 리셋이 무해.
**이탈:** 없음(원 설계가 명시 지시).
**영향:** Budgeter는 상태를 가지므로 M2에서 인스턴스 수명을 run 단위로 관리. (M1은 Budgeter 스텁이라 무영향.)

---

## D2. SQLite → PostgreSQL 이식, 단일 작성자(P2)는 앱 레벨 + advisory lock

**결정:** 원 설계의 "유일한 상태 저장소 SQLite(WAL, 파일 1개/run)"를 NEOS 공유 PostgreSQL로 이식.
5개 테이블 + blobs를 `deep_analysis_` 접두어 + `run_id` 스코프의 async SQLAlchemy 모델로 구현.
단일 작성자는 (a) 앱 레벨(Ledger만 DB 세션 보유, 워커는 순수 함수로 DB 미접근) + (b) `commit_pass`
트랜잭션 진입 시 `SELECT pg_advisory_xact_lock(hashtextextended(run_id, 0))`로 이중 보장.
**근거:** NEOS 네이티브 스택. Postgres는 WAL 파일 격리를 주지 않지만 advisory lock이 run별 단일
작성자를 **DB 강제 불변식**으로 만들어, 인라인 asyncio → Celery 다중 프로세스 이전 시에도 관례가
소리 없이 깨지지 않게 한다. 락 키는 `hashtext()`(int4 반환) 대신 `hashtextextended(run_id, 0)`
(bigint 반환)을 쓴다 — int4는 32비트라 서로 다른 run_id가 같은 락 키로 해시되어 과잉 직렬화가
발생할 수 있고, bigint 오버로드는 이 충돌을 공짜로 제거한다(정확성 문제는 아니나 무료 수정).
**이탈:** 저장소 엔진 교체(§4 DDL의 `PRAGMA journal_mode=WAL` 등 SQLite 전용 구문 제외). 단일 작성자
보장 수단이 파일시스템 격리 → 앱 규율 + advisory lock으로 변경.
**영향:** 원 설계 §11.9("exactly-once용 추가 배관 금지 — hash upsert 멱등성으로 충분")는 유지. advisory
lock은 exactly-once 배관이 아니라 동시 작성자 배제(P2 강제)이므로 §11.9 위반 아님.

---

## D3. claims UNIQUE는 `(run_id, hash)`로 스코프 (교차 오염 방지)

**결정:** 원 설계의 전역 `claims.hash UNIQUE`를 `UNIQUE (run_id, hash)`로 좁힌다. run_id 필터 강제는
체크리스트(사람 규율)가 아니라 **구조**로 만든다: `Ledger`는 생성자에서 `run_id`를 받고(`Ledger(session, run_id)`),
모든 쿼리 메서드는 `run_id`를 **인자로 받지 않는다**. 인스턴스가 자기 run만 볼 수 있으므로 필터를
잊는 것이 타입 수준에서 불가능하다. 이는 원 설계 P3("위험한 자유도는 스키마에서 제거")의 애플리케이션
레이어 버전이며, 부수적으로 원 설계 §6.1의 run_id-free 메서드 시그니처(단일 실행 전제)와 더 정확히 일치한다.
**근거:** 원 설계의 전역 hash UNIQUE는 **단일 실행 전제**였다(§6.1.3의 병렬 워커 교차 검증은 한 run 내부).
run_id 멀티테넌시를 도입한 채 hash가 전역 유니크로 남으면, 서로 다른 run이 같은 사실을 발견할 때
hash 충돌 → 증거 병합 + confidence 상향이 **run 경계를 넘어** 발생. 교차 검증 메커니즘이 교차 오염
메커니즘으로 변질된다. run_id 포팅의 파생 효과 중 유일하게 "조용히 틀어지는" 지점.
**이탈:** UNIQUE 제약 범위 확장(전역 → run 스코프).
**영향:** §6.1.3의 upsert(evidence 병합 + `confidence = min(0.95, 기존+0.15)`)는 반드시 동일 run_id
내에서만 발동. 다른 run의 동일 hash는 별개 클레임으로 공존. **동일 원칙을 blobs에도 적용(→ D4):
모든 원장 데이터는 run 스코프.**

---

## D4. blobs — 파일시스템 → 테이블 (content-addressed)

**결정:** 원 설계의 `blobs/{sha256[:16]}.txt` + `blobs/{hash}.meta.json` 사이드카를 단일 테이블
`deep_analysis_blobs(run_id, content_hash, url, http_status, fetched_at, raw_text)`로 대체. `evidence.raw_ref`는
blob의 content_hash를 담되 항상 자신의 run_id와 함께 조회. 3규칙: (a) **PK = `(run_id, content_hash)`**
— content_hash = `sha256(raw_text)[:16]`, **run 스코프**(전역 아님). 같은 run 내에서 여러 워커가 같은
페이지를 fetch하면 중복 저장 제거, run 간에는 별개 행으로 공존, (b) **핫 패스에서 이 테이블 JOIN 금지**
— raw는 DeterministicGrader가 `(run_id, content_hash)`로 단건 조회할 때만 읽음(원 설계 §4 "excerpt만
종합이 읽는 본문" 원칙을 테이블 세계에서 유지), (c) **보존 정책** — run 완료 + 보고서 검증 후 **해당
run의** raw 삭제 가능(excerpt는 evidence에 남으므로 무손실).
**근거:** nginx A-B 배포에서 파일시스템 blob 경로는 배포 간 정합성 문제를 만들지만 테이블은 없음.
A2의 사이드카 메타(url/http_status/fetched_at)를 컬럼으로 접으면 더 깔끔.
**PK를 전역 content_hash로 두면 안 되는 이유(초안 버그 수정):** 전역 PK는 두 run이 같은 페이지를
fetch할 때 blob 행을 **공유**시킨다. 그 상태에서 (c)의 run별 보존 정책이 run A 완료 후 그 행을 지우면,
같은 행을 참조하던 **진행 중인 run B의 `evidence.raw_ref`가 허공을 가리켜** run B의 대조가 전부 실패한다.
테이블에 run_id가 있는데 PK가 전역이라는 것 자체가 소유권 모호의 신호다. 참조 카운팅으로 전역 공유를
유지하는 대안은 §11.9가 금지한 종류의 배관을 자초하므로 채택하지 않는다. 대신 D3와 동일 방향으로 PK를
run 스코프로 좁혀 "모든 원장 데이터는 run 스코프"라는 단일 원칙을 세운다(run 간 중복 저장은 감수 —
절감 효과 미미).
**이탈:** raw 저장 위치(파일 → 테이블), 사이드카 메타(파일 → 컬럼), PK 스코프(전역 content hash → `(run_id, content_hash)`).
**영향:** A2의 핵심 불변식("커밋 경로에서 네트워크 I/O 금지, 채점기는 사이드카를 읽기만") 유지 —
`http_status`를 컬럼에서 읽으므로 커밋 경로 HTTP 호출 없음.

**개정(코드리뷰 #4) — 빈 본문 content_hash 구분:** content_hash는 원칙적으로 `sha256(raw_text)[:16]`
이지만, **본문 추출이 빈 경우**(모든 비-2xx 응답 + 200이지만 텍스트가 추출되지 않는 페이지)는
전부 `sha256("")`로 붕괴해 PK `(run_id, content_hash)`에서 첫 blob만 남고 서로 다른 URL/`http_status`가
뭉개진다. 그러면 죽은 404 blob과 유효한 200-빈 페이지가 한 행으로 합쳐져 DeterministicGrader가
잘못된 `http_status`로 E_SOURCE_DEAD 오탈락(또는 오통과)한다. 따라서 **빈 본문에 한해**
content_hash를 `sha256("\x00EMPTY\x00{status}\x00{url}")[:16]`로 계산해 소스별로 분리한다. 비어 있지
않은 본문은 종전대로 순수 content-address(§6.1.3 교차 검증용 동일-본문 dedup)를 유지한다. 구현:
`fetch._blob_hash`. 회귀 테스트: `tests/workflow/deep_analysis/test_fetch.py::test_empty_body_blobs_do_not_collide_across_sources`,
`::test_identical_body_still_dedups_by_content`.

---

## D5. 순수 LLM 콜러가 원 설계 llm.py를 대체 (LangChain 미사용)

**결정:** NEOS 인프라(settings, cost_calculator, web_search)는 재사용하되, LLM 호출 경로는 LangChain
`BaseLanguageModel`이 아닌 순수 `AsyncAnthropic`/`AsyncOpenAI` 콜러(`deep_analysis/llm.py`)로 구현.
**근거:** 사용자 지시("reuse NEOS infra as possible, but want to use pure LLM caller rather than langchain").
원 설계 §5의 "외부 프레임워크(LangChain 등) 사용 금지"와도 일치. 결정적으로 A5의 usage 기반 토큰
집계는 raw API `usage` 필드를 요구하는데 LangChain은 이를 일관되게 노출하지 않음 — 예산 사다리 +
gain_decay 전체가 이 숫자 위에 있으므로 순수 콜러가 기능적 필수.
**이탈:** NEOS의 `LLMFactory`/`providers`(LangChain 래핑)를 LLM 콜에는 미사용. 모델 ID/API 키만 재사용.
**영향:** A5 두 요건(방어적 JSON 파서 단일화 + usage 토큰 집계)은 `llm.py` 한 곳에 구현.

---

## D6. fetch.py 신설 (link_follower 재사용 대신)

**결정:** 탐색(discovery)은 NEOS `web_search` 재사용, 검색(retrieval)은 신규 `fetch.py`.
**근거:** NEOS `link_follower`는 링크 추출용이라 A2/A3가 요구하는 HTML→텍스트(NFC)→blob+메타를
만족하지 못함. A3(대조 기준 텍스트 통일: 저장 원문 = 발췌 기준)를 지키려면 fetch 직후 변환을 1회
수행하고 그 텍스트를 blob에 저장해야 함.
**이탈:** 배관 소폭 중복(의도된 비용).
**영향:** `normalize_for_hash()`와 `normalize_for_match()`를 A3대로 다른 함수로 분리 유지.

---

## D7. 실행 모델 — M1 인라인 SSE, Celery는 나중 (마이그레이션 리스크 2건 사전 기록)

**결정:** M1 수직 슬라이스는 요청 태스크 내 인라인 asyncio 실행 + SSE 스트리밍(deep_research 패턴).
긴 run의 Celery 이전은 상태가 events/ledger에 있으므로 나중에 non-breaking하게 가능.
**근거:** dev 프로파일(작은 캡)에는 인라인이 맞고 기존 deep_research와 일관.
**이탈:** 없음(원 설계는 실행 배포 모델 미규정).
**영향 — "later"가 오면 깨질 핵심 리스크 2건 + 부수 1건(알려진 리스크):**
1. **단일 작성자:** D2의 advisory lock으로 **선제 해결됨**.
2. **A1 partial 시맨틱은 Celery로 이전되지 않음** — `asyncio.wait_for` 취소는 같은 프로세스 안이라
   `flush_partial()`이 워커 인스턴스 버퍼에 닿지만, Celery 하드 타임아웃은 **프로세스를 죽여** 버퍼가
   증발. 해법은 이전 시점에 결정(soft time limit 핸들러에서 flush, 또는 워커가 클레임을 스크래치
   영역에 점진 체크포인트). **⚠ M2의 partial AC(타임아웃 워커 부분 클레임 커밋)는 Celery 환경에서
   재검증 필요.**
- **부수 리스크:** 인라인 SSE로 긴 run을 돌리면 nginx `proxy_read_timeout`에 걸릴 수 있음.
   dev 프로파일 밖에서 실행하기 전 확인.

---

## D8. events append-only를 Postgres DB 강제 불변식으로 승격

**결정:** 원 설계 §11.3("events 테이블 UPDATE/DELETE 금지")을 SQLite에서는 관례로만 유지했으나, 공유
Postgres로 이식하면서 DB 강제로 승격한다. `deep_analysis_events`에 `BEFORE UPDATE OR DELETE` 트리거를
걸어 `RAISE EXCEPTION`(예: `deep_analysis_events is append-only`)으로 거부한다. (대안: 애플리케이션 롤에
대해 `REVOKE UPDATE, DELETE ON deep_analysis_events` — 롤 구성이 알려진 환경에서만. 이식성은 트리거가 우위.)
**근거:** D2에서 advisory lock으로 P2를 DB 강제로 만든 것과 동일 논리. 관례에 의존하던 불변식을 저장소가
강제하면 다중 프로세스(Celery) 이전 시에도 새지 않는다.
**이탈:** 없음(원 설계 정신 강화). INSERT와 SELECT만 허용하는 것은 append-only 로그의 정의 그대로.
**영향:** Alembic 마이그레이션에 트리거 생성 포함. 테스트에서 UPDATE/DELETE 시도가 예외를 던지는지 검증.

---

## D9. blob도 워커 제안으로 반환하고 Ledger가 저장

**결정:** 워커에 `AsyncSession`을 주입하거나 워커 내부에서 `deep_analysis_blobs`를 쓰지 않는다.
PostgreSQL 이식으로 파일 기반 `raw_ref`를 DB blob으로 바꾸면서 생긴 전달 공백은
`ProposedBlob`과 `WorkerResult.blobs`를 공유 계약에 추가해 해소한다. 워커는 fetch 결과를
content-addressed blob 제안으로 반환하고, 오케스트레이터가 채점 전에 Ledger를 통해 blob을
커밋한다.

**근거:** 원 설계 P1은 워커가 DB를 읽거나 쓰지 않는다고 명시하고, 승인 스펙 D2/§3.2는 워커가
DB 세션을 절대 받지 않는다고 더 강하게 고정한다. 계획 초안의 “blob은 산출물이므로 워커가 DB에
써도 된다”는 예외는 이 두 계약과 충돌하며, 향후 Celery 격리에서도 세션 수명과 단일 작성자
보장을 흐린다. 제안 타입으로 반환하면 `(brief, effort) → WorkerResult` 계약과 P2를 모두 유지한다.

**이탈:** 원 설계 §5의 `WorkerResult`에 `blobs: list[ProposedBlob]`를 추가한다. 이는 SQLite
파일 경로였던 raw 산출물을 PostgreSQL 단일 작성자 경로로 운반하기 위한 이식 전용 확장이다.

**영향:** blob INSERT와 evidence/claim 커밋은 모두 Ledger만 수행한다. DeterministicGrader는
Ledger가 먼저 저장한 `(run_id, content_hash)` 행을 읽기만 하며 커밋 경로에서 네트워크 I/O를
하지 않는다.

---

## D10. M1에서도 orphan 인용은 숨기지 않고 실패

**결정:** `CitationRenderer`가 존재하지 않거나 verified가 아닌 `[C:id]`를 만나면
`OrphanCitationError(code="E_ORPHAN_CITE")`를 발생시킨다. 계획 초안의 `[미검증]` 치환은
채택하지 않는다.

**근거:** 원 설계 §6.8은 orphan 인용을 명시적 실패 코드로 정의하고, M1 AC는 모든 인용이
verified 클레임으로 해소되어야 한다고 요구한다. `[미검증]` 치환은 원시 마커만 제거해 AC를
겉보기로 통과시키면서 실제 인용 무결성 실패를 보고서 안에 숨긴다.

**이탈:** 구현 계획 Task 14의 M1 임시 완화(`[미검증]` 치환)에서 이탈하며, 정본인 원 설계로
복귀한다.

**영향:** orphan이 하나라도 있으면 보고서 완료 이벤트를 내보내지 않고 run이 failed로 전이한다.
M4 ReportGrader가 추가되면 같은 오류 코드가 조립 재시도 처방으로 연결된다.

---

## D11. §6.3.2 서브질문 채택은 M3로 연기, M2는 로깅만

**결정:** 워커의 `proposed_subquestions`는 M2에서 `subq_proposed` 이벤트로 로깅만 하고 채택(트리 삽입)하지 않는다.
**근거:** M2 AC(partial/SPLIT/cap/global-cap)에 서브질문 채택은 없다. 채택은 LLM 심사(중복 제거 + value_est 부여, §6.3.2)를 요구하므로 에이전틱 채점이 도입되는 M3와 함께 구현하는 것이 응집적이다. SPLIT(오케스트레이터 권한 decompose)이 트리를 키우므로 M2 AC 충족에 서브질문 채택은 불필요.
**이탈:** 원 설계 §6.3 메인 루프의 `_review_subquestions`를 M2에서 부분 구현(로깅)으로 축소.
**영향:** M3에서 `subq_proposed` 이벤트를 소비해 채택 로직을 붙인다. 로깅이 이미 있으므로 관측 연속성 유지.

---

## D12. SPLIT decompose는 주입 가능 함수로 분리

**결정:** `_do_split`의 자식 생성 decompose를 `self._split_decompose(text, verified_summaries, dead_ends)` 시임으로 분리한다(기본=`_default_split_decompose`, LLM 호출). FakeWorker 계약 테스트는 이 속성을 sync/async 스텁으로 오버라이드해 LLM 없이 SPLIT 경로를 검증한다. `_ensure_root`/`_do_split` 두 decompose 호출부는 `_maybe_await`로 감싸 sync/async 스텁을 모두 허용한다.
**근거:** 원 설계 §10 "M2 AC 전부 FakeWorker로 재현". SPLIT은 LLM decompose를 호출하므로 주입점이 없으면 계약 테스트가 불가능. §6.3.1대로 decompose 입력에 verified 요약 + dead_ends를 포함한다.
**이탈:** 없음(테스트 가능성 위한 구조적 분리 + §6.3.1 충실).
**영향:** 프로덕션에서는 `_default_split_decompose`(LLM)가 쓰인다.

---

## D13. §6.3.2 서브질문 채택은 M3에서도 재연기 — `subq_proposed` 로깅만 유지

**결정:** D11에서 M3로 연기했던 워커 `proposed_subquestions`의 트리 채택(중복 제거 + value_est
부여 후 자식 삽입, §6.3.2)을 M3에서도 **구현하지 않고** 다시 M4+로 연기한다. 오케스트레이터는
계속 `subq_proposed` 이벤트로 로깅만 한다(M2에서 붙인 관측 경로 그대로).
**근거:** M3의 세 acceptance criteria(AC-a E_OVERCLAIM 약화, AC-b E_CONTRADICTED 부정 재진입,
AC-c 재시도 캡→unverified)는 **어느 것도 서브질문 채택을 요구하지 않는다** — 셋 다 기존 질문 위의
repair→pending→regrade 루프로 닫힌다. 채택 로직은 §6.3.2대로 "중복/유사 서브질문 병합 + 상대
value_est 산정"을 위해 **독립적인 LLM 심사자**를 요구하는데, 이는 AgenticGrader(클레임 채점자)와
역할이 다르고 별도 프롬프트·검증·테스트 하네스를 필요로 한다. M3에 끼워 넣으면 세 AC와 무관한
표면적을 늘려 회귀 위험만 키운다. §1 원칙(최소 표면적, AC 주도)에 따라 채택은 계층 리듀스가
들어오는 M4에서 응집적으로 다룬다.
**이탈:** 원 설계 §6.3 메인 루프의 `_review_subquestions`(채택)를 M3에서도 로깅 부분 구현으로
유지 — D11의 연기를 한 마일스톤 더 연장.
**영향:** `subq_proposed` 이벤트는 이미 기록되므로 M4에서 소비할 데이터는 연속적으로 쌓인다.
채택 미구현이 M3 AC 충족을 막지 않음은 Task 6 통합 테스트(AC-a/b/c)가 서브질문 없이 통과함으로
입증된다.

---

## D14. AgenticGrader — 판정 불가 시 "보류" 대신 미심사 통과(label=None)

**결정:** `AgenticGrader.grade`가 judge 응답을 파싱하지 못하거나(`JSONParseError`, `call_json`이
1회 재시도 후에도 실패) 라벨이 4종 열거값(SUPPORTS/PARTIAL/UNRELATED/CONTRADICTS) 밖이면, 판정을
보류(pending) 상태로 묶어두지 않고 즉시 `Verdict(ok=True, label=None, detail="judge_unparseable"|
"judge_unknown_label")`로 미심사 통과 처리한다. 시스템을 정지시키지 않는다(§6.5 엣지 케이스).
**근거:** 원 설계는 판정 불가 시 "pending 유지"를 지시하지만, 이는 원 설계의 상태 기계에서 pending이
별도의 종착 대기 상태임을 전제한다. 우리 파이프라인에서는 det(DeterministicGrader) 통과 클레임의
기본 상태가 이미 `verified`이고, AgenticGrader는 그 위에 계층화된 티어링 심사(§6.5)일 뿐이다. 여기서
"pending"을 새로 도입하면 (a) det 통과 후 verified였던 클레임이 agentic 계층 실패만으로 미검증 상태로
격하되는 상태 역행이 생기고, (b) Ledger/오케스트레이터에 별도의 pending 재시도 배관을 요구해 §11.9
("exactly-once용 추가 배관 금지")와 충돌한다. 판정 불가는 judge의 일시적 응답 실패이지 클레임 자체의
증거 결함이 아니므로, det 통과라는 기존 신뢰를 유지한 채 이벤트로만 기록하는 편이 더 안전하다.
**이탈:** 원 설계 §6.5의 "판정 불가 시 pending 유지" 지시에서 이탈. 미심사 통과(`label=None` +
`detail`에 사유 기록)로 대체.
**영향:** M3 Task 2/3(오케스트레이터 2단계 채점, Ledger pending_feedback)은 이 미심사 통과를
`judge_unparseable`/`judge_unknown_label` detail이 있는 verdict로 관측 가능해야 한다. 재판정
재시도가 필요하면 별도 샘플링 라운드(다음 pass)에서 자연히 재티어링되며, 이는 기존 tiering
샘플러(`should_grade`)가 이미 제공하는 경로다 — 전용 pending 재시도 배관을 새로 만들 필요가 없다.

**개정(코드리뷰 #6 / §A4):** 위 미심사 통과는 **저가치 샘플링 대상**(`value_est×confidence <
agentic_threshold`)에만 적용한다. **필수 심사 대상**(mandatory, 임계 이상)은 judge 판정 불가 시
자동 `verified`를 **금지**한다 — 대신 `Verdict(ok=False, code="E_UNSUPPORTED",
detail="…_mandatory")`로 반려한다. 근거: §A4는 judge 분리를 사실상의 프롬프트 인젝션 방어층으로
규정하고 "성능·비용을 이유로 완화하지 말 것"을 요구한다. 미개정 동작은 적대적 웹 원문이 judge
출력을 비-JSON으로 깨뜨리기만 하면 고가치 클레임을 무심사로 verified 통과시키는 우회로를 열어
그 방어층을 무력화했다. 반려된 클레임은 재조사되고, 재시도 캡 소진 시 `unverified`→보고서 "한계"
섹션에 남는다(빈손 종료 없음). 저가치 샘플 경로의 D14 원결정은 그대로 유지된다.

---

## D15. 무진전 안전밸브 — 질문별 연속 무진전 라운드 상한 도달 시 강제 SPLIT/abandon

**결정:** 질문마다 **연속 무진전 라운드 수**를 오케스트레이터 인메모리 `{qid: stall_count}`로 센다.
"무진전"은 한 pass가 (a) 신규 verified 클레임 0 **AND** (b) 신규 feedback(거절) 0 **AND** (c) 토큰
증가 0 인 경우 — 또는 question_id 가드(Task 3)에 의해 커밋이 스킵된 경우로 정의한다. 진전이 하나라도
있으면 카운터를 0으로 리셋하고, 무진전이면 +1 한다. `max_stall_rounds`(config 기본 3) 도달 시 해당
질문을 강제 종료한다: `_do_split`을 호출해 depth가 허용되면 SPLIT, `depth >= max_depth`면 abandon.
**근거:** M2/M3 이월 livelock 두 종을 결정적으로 차단한다 — (1) **zero-token-partial**: 타임아웃
워커가 매 라운드 0 토큰·0 클레임 partial을 커밋해 예산은 안 줄고 상태도 안 변하는 무한 루프,
(2) **always-mismatch**: 워커가 매번 다른 question_id를 돌려줘 Task 3 가드가 커밋을 스킵하고 질문을
open으로 되돌리기만 하는 스핀. 둘 다 budgeter의 score/should_stop만으로는 멈추지 않는다(점수가
floor 위에 남아 계속 재선택). 안전밸브는 "질문이 실제로 원장을 바꿨는가"라는 단일·결정적 신호로
이 부류를 종료시킨다. 정상 진전(약화 repair→verified, 거절→feedback, 토큰 소비)은 무진전이 아니므로
정상 파이프라인에는 개입하지 않는다.
**이탈:** 없음(원 설계가 위임한 안전장치. 원 설계 §6.2 정지 조건을 보강하되 대체하지 않음 —
전역 캡·score floor는 그대로 유지되고, 안전밸브는 그 위에 질문 단위 진전 보증을 더한다).
**영향:** `neos/config/schema.py`에 `max_stall_rounds: int = 3` 추가, 오케스트레이터에
`max_stall_rounds` 주입 파라미터 + `_made_progress`/`_register_progress`/`_force_terminate_stalled`
추가, Ledger에 진전 판정용 `feedback_count(qid)` 추가. `stall_terminated` 이벤트로 관측 가능.
결정적 테스트: 매 라운드 무진전 결과만 반환하는 워커 → run이 전역 캡에 도달하지 않고 종료하며
질문이 split/abandoned로 끝난다.

---

## D16. 충돌 "양론 병기"는 LLM 재요약이 아니라 결정론적 문구 삽입

**결정:** M4 §6.7의 동급 tier 충돌 해소("해당 노드만 1회 재요약")를 LLM 재요약 경로로 구현하지
않는다. 대신 `conflict.py::resolve_conflicts`가 `summary.answer`에 결정론적 문자열 —
`\n\n(양론 병기) 상반된 근거: [C:{claim_a}] vs [C:{claim_b}] — {nature}` — 을 그대로 append한다.
등급 차이(한쪽 tier1, 다른 쪽 tier2)가 있는 경우는 상위 등급 클레임을 조용히 채택하고 양론 문구는
붙이지 않으며, 하위 등급 클레임에는 `summary.caveats`에 "하위 출처 각주" 문구만 추가한다.
**근거:** AC-b("등급 동급 시 양론 병기")는 결과 문자열에 두 `[C:id]` 마커와 "양론" 신호가 모두
존재하는지만 검증하면 충족되고, 이는 네트워크/LLM 호출 없이 순수 함수로 결정론적·테스트 가능하게
만들 수 있다. D5(순수 LLM 콜러)·D9와 같은 방향으로, 매 충돌마다 LLM 재요약을 새로 호출하는 것은
(a) 이 모듈의 표면적을 늘리고, (b) 재요약 결과가 매 실행마다 달라져 골든 테스트/재현성을 깨며,
(c) M4 예산(§6 토큰 캡)에 불필요한 추가 소비를 만든다. 두 마커를 원문 그대로 유지하면
`CitationRenderer`(D10)가 이미 각주로 해소하므로 출처 무결성도 그대로 유지된다.
**이탈:** 원 설계 §6.7의 "해당 노드만 1회 재요약"(LLM 경로)에서 결정론적 문자열 삽입으로 대체.
**영향:** `resolve_conflicts`는 순수 async 함수로 FakeLedger만으로 완전히 단위 테스트 가능
(`tests/workflow/deep_analysis/test_conflict.py`). 재조사가 필요한 경우(충돌 클레임의
`value_est >= conflict_value_threshold`)는 오케스트레이터가 소비할 질문 id 목록으로만 반환하고,
이 모듈 자체는 트리를 변형하거나 재실행을 트리거하지 않는다(Task 5에서 소비).

---

## D17. 계층 리듀스는 순차 후위 순회 — 같은 깊이 병렬은 후속 최적화로 연기

**결정:** `Synthesizer.reduce_tree`의 트리 리듀스를 **단일 순차 후위 순회(post-order DFS)**로 구현한다.
`visit(qid)`가 자식들을 하나씩 순서대로 `await visit(child)`한 뒤 자기 노드를 `reduce_node`로 요약하며,
같은 깊이(sibling)의 노드들도 병렬이 아니라 순차로 처리한다. 원 설계 §6.7이 허용하는 "같은 깊이
노드의 병렬 리듀스"는 이 마일스톤에서 구현하지 않고 후속 최적화로 남긴다.
**근거:** M4의 세 acceptance criteria(AC-a 노드당 상수 컨텍스트, AC-b 양론 병기, AC-c 조립 재시도)는
**어느 것도 병렬 리듀스를 요구하지 않는다** — 셋 다 리듀스의 *입력 경계*(자기 클레임 + 직계 자식
요약만, §6.7 불변식)와 *결과*에만 의존하며, 이 경계는 순차/병렬과 무관하게 동일하다. 순차 구현은
(a) `dict` 누적을 단일 태스크가 쓰므로 P2(단일 작성자)·D5(순수 콜러) 원칙과 자연스럽게 정합하고,
(b) 리듀스 순서가 결정적이라 캡처된 프롬프트/`node_summary` 이벤트 순서가 재현 가능해 골든·통합
테스트를 안정적으로 만들며(같은 깊이 병렬은 `asyncio.gather` 완료 순서 비결정성을 도입해 이벤트
로그 순서 검증을 깨뜨린다), (c) M4 예산 하에서 트리 규모가 작아(depth ≤ max_depth, 레벨당 ≤ 4~7)
병렬화의 실측 이득이 미미하다. §1 원칙(최소 표면적, AC 주도)에 따라 병렬화는 실제 지연이 병목으로
확인될 때 독립적으로 도입한다.
**이탈:** 원 설계 §6.7이 명시적으로 허용한 "같은 깊이 병렬 리듀스"를 채택하지 않고 순차로 구현 —
설계가 허용한 최적화의 *연기*이지 계약 위반이 아니다(입력 경계·출력 타입은 §6.7 그대로 유지).
**영향:** `reduce_tree`는 인메모리 `summaries: dict` 하나를 순차로 채우는 재귀 함수로 남는다. 병렬화가
필요해지면 리듀스 경계가 이미 노드 단위로 고립돼 있으므로(각 `reduce_node`는 자기+직계 자식만 읽음)
같은 깊이 그룹을 `asyncio.gather`로 감싸는 국소 변경으로 충분하다 — 이때 `node_summary` 이벤트
순서에 의존하는 테스트는 깊이별 그룹 단위 검증으로 완화해야 한다. 결정적 순차 순회는
`tests/workflow/deep_analysis/test_synthesizer_hier.py`(후위 순서 검증)와
`test_orchestrator_m4_integration.py`(AC-a 루트 prompt_chars 불변)로 입증된다.

---

## D18. 챗 편입 — 하네스는 단일 workflow 노드로 완주, per-claim SSE는 전용 엔드포인트 유지

**결정:** Sub-project A(챗 경로 → 하네스 전환)에서 `deep_analysis` 하네스를 LangGraph 챗
워크플로우에 편입할 때, `recursive`/`hyper_deep` 오케스트레이터와 동일한 패턴을 따른다 —
`DEEP_ANALYSIS_ENABLED` 플래그로 게이팅된 **단일 조건부 노드**(`_deep_analysis_orchestrator_node`)가
`OrchestratorRouter.route()`에서 `"deep_analysis"`로 라우팅된 뒤 하네스 오케스트레이터를
`orch.run(query)`로 **완주까지 실행**하고, `report_markdown`을 `final_response`로 매핑해
`RESULT_INTEGRATOR`로 합류한다. 챗 클라이언트는 이 노드 하나의 시작/완료라는 **노드 레벨
진행상황**만 관찰한다(`execution_steps`에 1개 항목 추가). 하네스 내부의 세밀한 claim-by-claim
스트리밍(질문 선택 → 워커 실행 → 채점 → verified/rejected 이벤트)은 챗 그래프에 노출하지 않고,
기존 전용 `/api/v1/deep-analysis` SSE 엔드포인트(M1 D7의 인라인 asyncio + SSE 경로)를 통해서만
제공한다. 즉 같은 하네스 코어(`service.build_orchestrator`/`ledger.create_run`, M0–M4 불변)를
**두 개의 서로 다른 소비 경로**로 노출한다: (a) 챗 워크플로우 노드 = 굵은 단위 진행 + 최종 리포트,
(b) 전용 SSE 엔드포인트 = 세밀한 실시간 이벤트.

**근거:** (1) **기존 배관 재사용** — 챗 워크플로우는 이미 노드 단위 진행 신호(`execution_steps`,
`RESULT_INTEGRATOR` 이후의 대화 저장·fact-check·품질 검증)를 전제로 설계돼 있고, `recursive`/
`hyper_deep`도 동일하게 "무거운 하위 작업 하나가 완주 후 결과만 상위로 반환"하는 모델을 이미
증명했다(§ enums/graph.py 조건부 등록 패턴). claim 단위 이벤트를 챗 그래프 상태로 끌어올리려면
`AgentState`에 새 스트리밍 채널을 추가하고 fact-check/conversation 저장 로직이 부분 상태를
다뤄야 해서 표면적이 커진다. (2) **최소 침습** — 하네스 M0–M4 코드(오케스트레이터/이벤트 싱크
계약)를 변경하지 않고 통합 계층(그래프 노드)만 추가하는 것이 이 서브프로젝트의 전역 제약이다.
챗 노드에서 `event_sink`를 no-op으로 넘기고 전용 엔드포인트에서만 실제 SSE 싱크를 연결하면,
동일한 `build_orchestrator` 계약을 두 경로가 그대로 공유해 하네스 코어를 건드릴 필요가 없다.
(3) **점진적 대체** — 원 설계(§655)가 예정한 "LangGraph 워크플로우가 하네스로 점진 대체"라는
방향에서, 이번 스텝은 챗 경로의 라우팅 대상만 교체하는 첫 이동이다. per-claim 스트리밍까지
챗 그래프로 옮기는 것은 그 다음 단계(챗 SSE 프로토콜 자체를 하네스 이벤트 스키마로 통합)의
범위이며, 지금 함께 하면 두 관심사(라우팅 편입 vs 스트리밍 프로토콜 재설계)가 한 커밋에
묶여 무회귀 검증이 어려워진다.

**이탈:** 없음(원 설계는 챗 통합 방식을 규정하지 않음 — 원 설계 §655는 "충돌 시 결정 후 기록"만
지시). D7(M1 인라인 SSE)과 상충하지 않는다 — D7의 SSE 경로는 `/api/v1/deep-analysis` 엔드포인트에
그대로 남고, 챗 노드는 그 경로를 우회해 오케스트레이터를 직접 호출하는 별도 소비자일 뿐이다.

**영향:** `DEEP_ANALYSIS_ENABLED=false`(기본)일 때 챗 그래프는 `deep_analysis_orchestrator` 노드를
등록조차 하지 않고 라우팅 맵에도 `"deep_analysis"` 키가 없다 — 무회귀는 노드 부재로 구조적으로
보장된다(`tests/workflow/test_deep_analysis_node.py::test_no_regression_deep_analysis_off_by_default_node_not_registered`,
`tests/workflow/routing/test_deep_analysis_routing.py::test_no_regression_deep_analysis_off_by_default`).
플래그 활성 시에도 챗 응답은 리포트 완성 후 한 번에 오므로, per-claim 진행 UI가 필요한 소비자는
계속 전용 SSE 엔드포인트를 사용해야 한다 — 챗 API 문서에 이 구분을 명시할 필요가 있다(후속 문서화
과제, 이 결정의 범위 밖).

### 프로덕션 활성화 전 선결 조건

Sub-project A final review에서 `DEEP_ANALYSIS_ENABLED=true`로 전환하기 **전에** 반드시 처리해야
한다고 플래그된 항목들이다. 기본값이 OFF이고 위 "영향" 절의 구조적 무회귀 보장이 성립하는 동안은
안전하게 미룰 수 있지만, 실제로 플래그를 켜는 순간부터는 아래 세 가지가 그대로 프로덕션 리스크가
된다.

1. **Wall-clock 바운드:** `_deep_analysis_orchestrator_node`가 `orch.run()`을 타임아웃 없이
   동기로 완주시킨다. 프로덕션 캡(`global_token_cap` 20000, effort별 `wall_clock_cap` 최대
   600s 이상)에서는 챗 요청 하나가 수 분간 블로킹될 수 있어 HTTP/WS/게이트웨이 타임아웃과
   충돌할 위험이 있다. 활성화 전 `asyncio.wait_for` 등으로 노드 레벨 예산 바운드를 씌울 것.
2. **fail_run 내구성 — ✅ 해소됨(코드리뷰 #5):** 하네스 실행이 실패하는 경로에서 노드의
   `except` 블록이 `async with` 세션을 커밋 없이 종료해, `fail_run()`이 기록한 상태 업데이트가
   롤백될 수 있었다(반복 시 `status="running"` 고아 run 누적). 이제 노드 `except`가 **별도의
   짧은 새 세션**을 열어 `Ledger(fail_session, run_id).fail_run()` 후 `commit()`하여 실패 상태를
   내구성 있게 확정한다(원 세션은 롤백/오류 상태일 수 있어 재사용하지 않는다). 회귀 테스트:
   `tests/workflow/test_deep_analysis_node.py::test_deep_analysis_node_persists_failed_status_on_run_error`.
3. **분류기 intent 미도달:** `IntentType.DEEP_ANALYSIS`를 방출하는 쿼리 분류기가 아직 없어,
   현재는 복잡도 기반 분기만 라이브이고 intent 기반 라우팅 분기는 도달 불가능한 죽은 코드다.
   활성화 시점에 분류기에 해당 intent를 추가하거나, 미도달 분기를 정리할 것.

---

## D19. L5 개선 루프 — 관측/신호 + golden 게이트만, auto-mutation 없음

**결정:** L5 개선 루프(Sub-project B)는 append-only 이벤트 로그(P4)를 개선 신호로 집계해
사람에게 제시(analytics API + 주기 Celery 리포트)하고, 프롬프트 변경을 golden 회귀 게이트로
가둔다. 신호로부터 프롬프트/설정을 **자동 변경(auto-mutation)하지 않는다.**
**근거:** 자가 수정 루프는 가드레일(승인, 롤백, 안전 한계)이 필요하며 이번 범위를 벗어난다.
§6.4의 "워커 과장 습관은 L5 신호"는 `overclaim_rate` 지표로 포착되고, §10의 "골든 통합이 L5
게이트"는 record/replay 결정성 테스트 + 프롬프트 버전 매니페스트로 공식화된다 — 둘 다 사람이
읽고 결정하는 관측 계층이지 자동 조정기가 아니다.
**이탈:** 없음(원 설계는 L5를 개념으로만 언급; 이 결정은 그 범위를 관측/게이트로 명시 한정).
**영향:** 신호는 `deep_analysis_reports` 테이블(D 신규)과 `/api/v1/deep-analysis/analytics`로
노출. 이벤트 로그는 **읽기 전용**(§11.3, D8)이며 L5는 이벤트에 쓰지 않는다. 프롬프트 버전 bump는
`test_golden_gate`의 매니페스트를 강제로 깨뜨려, golden 재녹화 + 신호 검토를 유도한다.

---

## D20. 정지 판단(should_stop)은 aging 제외 base_score로 한다

**결정:** Budgeter.should_stop의 정지 조건 2("모든 open 질문의 score < score_floor")를
`base_score = value_est×(1−conf)×gain_decay`(aging 제외)로 평가한다. 선택 우선순위
(select)의 점수는 종전대로 aging을 포함한다.
**근거:** 설계 §8 기본값이 `aging_per_round == score_floor == 0.05`다. aging을 정지 조건에
포함하면 open 질문 수가 parallel_workers를 초과할 때 미선택 질문의 aging이 1라운드 만에
floor에 도달해, `should_stop`의 조건 2가 사실상 영원히 False가 된다. 결과적으로 저가치 런도
open 집합이 소진되거나 global_token_cap(30만)에 닿을 때까지 계속 조사해 §6.2가 의도한 '수익
체감 시 조기 정지'가 무력화되고 실제 비용이 초과된다. aging은 기아 방지용 소프트 신호(D1/A6)
이므로 선택 순서에만 쓰고, '남은 실제 가치'를 재는 정지 판단에서는 제외하는 것이 옳다.
**이탈:** 원 설계 §6.2 정지 조건 2는 문자 그대로 "score"(aging 포함)를 본다. 이 결정은
정지 판단에 한해 aging 항을 뺀다. 선택 로직·점수 공식 자체는 불변.
**영향:** `Budgeter.base_score()` 신설, `should_stop`이 이를 사용. select()의 aging 포함
점수·breadth pass·사다리는 불변. 저가치 질문만 남으면 global cap 도달 전에 정지한다.

---

## D21. deep 엔진 라우팅은 complexity 임계값이 아니라 질의 유형으로 가른다 (R1 해소, D18 선결 조건 #3 해소)

**결정:** `OrchestratorRouter.route()`의 엔진별 3중 if-체인을 `_DEEP_ENGINES` 테이블 기반
**단일 디스패치**로 교체한다. 각 엔진은 자기 유형 intent를 갖고(스펙 §4.1) — `deep_analysis`
= 검증형 분석, `hyper_deep` = 장문 리포트, `recursive` = 일반 태스크 분해 — 유형 intent가
엔진을 **결정**한다. complexity 임계값은 "deep 엔진을 쓸지 말지"의 게이트로만 남고 "어느
엔진인지"는 결정하지 않는다. 유형을 지목하지 않는 레거시 intent(`DEEP_RESEARCH`,
`COMPLEX_ANALYSIS`)만 임계값 게이트를 타며, 테이블 순서(deep_analysis → hyper_deep →
recursive)상 처음으로 "활성 + 게이트 통과"인 엔진이 받는다. 분류기(`query_classifier`)는
키워드 경로와 LLM 경로 **양쪽에서** 세 유형 intent를 방출한다.

**근거 — R1(임계값 역전, 기존 문서 미기록):** 종전 `orchestrator_router.py:98-129`의 세 블록은
플래그명·상수·임계값만 다른 거의 동일한 코드였고 **셋 다 같은 intent를 두고 경쟁**했다.
라우팅 순서는 deep_analysis(1순위) → hyper_deep(2순위) → recursive(3순위)인데 임계값은
0.5 → 0.85 → 0.8로 **역전**돼 있었다. 0.85를 넘는 질의는 0.5도 이미 넘으므로 deep_analysis가
먼저 가져간다 — 즉 `DEEP_ANALYSIS_ENABLED=true`인 순간 뒤 두 엔진의 complexity 경로는
**100% 도달 불가능한 죽은 코드**가 됐다. 에러도 경고도 없다. 유일한 탈출구인 명시적
intent는 R2(아래)로 막혀 있었으므로, 플래그를 켜는 것만으로 ROMA·Ray·HyperDeep이 통째로
조용히 사라졌다. 임계값은 "얼마나 어려운가"라는 **1차원 척도**여서 세 엔진의 역할 차이를
표현할 수 없다 — 세 엔진은 난이도가 아니라 **산출물의 형태**가 다르다. 척도를 유형으로
바꾸면 경쟁 자체가 성립하지 않는다.

**근거 — R2 해소(= D18 "프로덕션 활성화 전 선결 조건" #3):** D18은 "`IntentType.DEEP_ANALYSIS`를
방출하는 쿼리 분류기가 아직 없어 intent 기반 라우팅 분기는 도달 불가능한 죽은 코드"라
기록하고 활성화 전 처리를 요구했다. 키워드 경로는 해당 intent를 아예 생성하지 않았고, LLM
경로는 `_VALID_INTENTS`에 전부 넣으면서 프롬프트 Rules에는 9개만 설명해 사실상 방출되지
않았으며, `use_llm` 기본값이 꺼짐이라 키워드 경로가 기본이었다. 이 결정으로 **세 유형 모두
양쪽 경로에서 방출**되므로 선결 조건 #3은 해소된다. (선결 조건 #1 wall-clock 바운드는
**미해소로 남는다** — 이 결정의 범위 밖이며 활성화 전 여전히 필요하다.)

**이탈:** 없음(원 설계는 챗 라우팅 방식을 규정하지 않는다). 승인 스펙
`docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md` §4를 그대로 구현한다.
**엔진은 삭제하지 않는다 — 재배치지 제거가 아니다**(스펙 §7).

**영향 — 레거시 generic intent는 여전히 우선순위로 갈린다(의도된 잔여):** 스펙 §4.2는
"세 엔진이 같은 intent를 두고 경쟁하지 않게 되므로 shadowing이 사라진다"고 하지만, 이는
**유형 intent에 대해** 성립한다. `DEEP_RESEARCH`/`COMPLEX_ANALYSIS`는 유형을 지목하지
않으므로 어느 엔진이 받을지 정의되지 않으며, 여기에 여전히 우선순위가 필요하다. 이를
`deep_analysis` 1:1로 좁히는 대안은 **회귀**다 — 현재 프로덕션에 가까운 구성
(`DEEP_ANALYSIS_ENABLED=false` + `HYPER_DEEP_AGENT_ENABLED=true`)에서 오늘 `hyper_deep`으로
가는 고복잡도 `deep_research` 질의가 `base_route`로 떨어진다. 따라서 테이블 순서로 남기되,
**R1과는 성질이 다르다**: (a) 순서가 임계값 상수의 사고가 아니라 테이블에 명시·문서화돼
있고, (b) 어떤 엔진도 100% 도달 불가가 아니다 — `hyper_deep`/`recursive`는 자기 유형
intent로 항상 도달한다. 후자를
`tests/workflow/routing/test_engine_reassignment.py::test_every_engine_is_reachable_when_all_three_are_enabled`
가 강제한다.

**영향 — 기존 intent 방출 불변(K3):** 신규 유형 키워드는 기존 `intent_keywords` 스코어링
맵에 넣지 않고 전용 전처리(`_classify_engine_intent`)로 분리했다. 저 맵은 매칭 수를 세어
`max()`로 뽑으므로 키워드를 섞으면 기존 질의의 승자가 바뀔 수 있다. 전처리는 "신규 키워드가
하나도 안 맞으면 `None`"이라 기존 방출이 **구조적으로** 불변이다. `TASK_SCHEDULING`은
라우터 `_PRIORITY_ROUTING_MAP`에서 최우선이므로 전처리가 양보한다. 회귀 고정:
`tests/workflow/utils/test_query_classifier_engine_intents.py::test_existing_intent_emission_is_unchanged`.

**영향 — 엔진 추가는 이제 테이블 한 줄이다:** `DeepEngine(name, intent, enabled_flag,
threshold_attr)`을 `_DEEP_ENGINES`에 추가하면 된다. 분기 코드는 늘지 않는다 — R1의 재발
경로가 구조적으로 닫힌다. `test_route_has_no_per_engine_repeated_blocks`가 엔진명·플래그명·
임계값명이 분기 코드에 하드코딩되는 것을 금지해 이를 강제한다.

**영향 — `_ALWAYS_SEARCH_INTENTS`에 `DEEP_ANALYSIS` 추가:** 세 유형이 실제로 방출되기
시작하므로, 엔진이 꺼진 상태에서 검증형 질의가 검색 없이 `skip_orchestrators`로 새지
않도록 `deep_analysis`를 always-search 목록에 넣는다(나머지 두 유형은 이미 있었다).

---

## D22. durable job 서비스로 전환 — D7의 "나중"이 왔다 (3a: 제출·스트림·resume)

**결정:** D7("M1은 인라인 asyncio + SSE, Celery는 나중")을 갱신한다. `POST /api/v1/deep-analysis`는
run을 만들고 job을 디스패치한 뒤 **202 + run_id를 즉시 반환**한다. 실행은 요청 밖에서 진행되고,
진행 상황은 `GET /api/v1/deep-analysis/{run_id}/events`가 append-only 이벤트 로그를
`deep_analysis_events.seq` 커서로 재생해 전달한다. `POST /api/v1/deep-analysis/{run_id}/resume`가
중단된 run의 재개 진입점이다. **실행자는 둘, 계약은 하나다** — `CELERY_ENABLED=true`면
`apply_async`, 기본값 `false`면 응답을 막지 않는 백그라운드 asyncio 태스크. 두 경로 모두 같은
이벤트 로그에 쓰므로 스트림 엔드포인트는 실행자와 무관하게 동일하게 동작한다.

**근거 — 동기 요청 안에서 완주시키려는 시도 자체가 구조적으로 틀렸다:** 세 예산을 나란히 놓으면
프론트 `maxDuration` 60s < 노드 wall-clock 캡 300s < `dig` effort 하나의 `wall_clock_cap` 600s다.
**가장 작은 예산이 클라이언트 쪽에 있으므로**, 라운드를 여러 번 도는 run은 어떤 동기 요청 예산에도
애초에 맞지 않는다. 커밋 `9763eb5`의 노드 캡은 "호출자가 떠난 뒤에도 백엔드가 자원을 붙들고 있는 것"을
막을 뿐, 사용자가 결과를 받게 하지 못한다. 비동기 job + 이벤트 스트림은 우회가 아니라 유일한 해법이다.

**근거 — 전달 매체는 `stream_manager`가 아니라 DB다:** `neos/workflow/stream_manager.py:99`의
`self._sessions: Dict[str, StreamSession] = {}`는 **프로세스 내 메모리**다. Celery 워커가 넣은
이벤트를 API 프로세스의 SSE가 볼 수 없다. 반면 `DAEvent.seq`는 BigInteger autoincrement PK라
**그 자체가 단조 커서**이고, 매체가 DB이므로 프로세스 경계를 자연히 넘는다. 커서를 0에서 시작하면
진행 중인 run의 전체 이력이 재생되므로 **AC6이 공짜로 따라온다.** D8이 이 테이블을 append-only
DB 불변식으로 만들어 뒀으므로 P4와도 일치한다. seq 폴링이 행을 건너뛰지 않는 근거는 P2(단일
작성자)다 — run당 작성자가 하나면 seq 할당 순서가 곧 커밋 순서다.

**근거 — `event_sink`를 영속화 경로로 쓰지 않는다:** `Ledger.log()`가 이미 하네스 이벤트
대부분(`question_opened`·`pass_completed`·`claim_verified` 등 14종)을 `deep_analysis_events`에
쓴다. 오케스트레이터의 `_emit`은 그 kind들과 겹치므로, job이 "DB에 쓰는 싱크"를 넘기면 같은
이벤트가 두 번 쌓인다. 겹치는 kind만 골라내는 allowlist는 오케스트레이터 내부와 조용히 결합되는
유지보수 함정이다. 대신 **`job_` 접두어 라이프사이클 이벤트 4종**(`job_started`/`job_resumed`/
`job_completed`/`job_failed`)만 직접 쓴다 — 이 접두어는 하네스의 어떤 kind와도 충돌할 수 없고,
**하네스 코어(M0–M4)를 한 줄도 바꾸지 않는다**(D18의 "최소 침습" 제약 유지). 충돌 부재는
`tests/workflow/deep_analysis/test_jobs.py::test_lifecycle_kinds_cannot_collide_with_harness_event_kinds`
가 강제한다.

**근거 — resume은 새 저장소가 아니라 진입점이다(AC5):** Ledger가 이미 단일 상태 저장소이므로(P2),
같은 run_id로 `orch.run()`을 다시 부르는 것이 곧 resume이다. 중복 지출을 막는 것은 신규 코드가
아니라 **이미 존재하던 네 불변식**이다:
1. `ledger.recover()`가 `investigating`에 잠긴 질문을 `open`으로 회수한다
2. `_ensure_root()`가 기존 루트를 찾으면 즉시 반환해 LLM 재분해를 막는다
3. `budgeter.should_stop()`이 `ledger.total_spent()`(= `DAQuestion.spent_tokens`의 DB 합계)를
   읽으므로, 크래시로 인메모리 Budgeter가 리셋돼도 소비 기록은 원장에 남는다. breadth pass도
   같은 DB 값으로 게이팅된다
4. 충돌 재조사 캡은 인메모리 카운터가 아니라 **이벤트 로그**를 게이트로 쓴다(`orchestrator.py:611`,
   `ledger.has_event`) — "resumed run은 두 번째 라운드를 쓸 수 없다"는 불변식이 이미 코드에 있었다

따라서 `resume` 플래그는 (a) 어떤 라이프사이클 이벤트를 남길지, (b) `failed` run을 `running`으로
되돌릴지만 결정한다. 이 성질 덕분에 Celery가 worker-lost로 태스크를 `resume=False`로 재배달해도
안전하다. `completed` run은 재개를 거부한다 — 리포트 조립/채점 비용 재지출은 곧 재과금이다.
회귀 고정: `tests/workflow/deep_analysis/test_orchestrator_resume.py`. **실측**: 캡 200을 2패스로
소진한 run을 새 Orchestrator 인스턴스로 재개하면 워커 패스가 **0회** 추가 실행된다.

**이탈 — D7 갱신:** D7이 예고한 "later"가 왔다. D7이 사전 기록한 리스크 2건의 현황:
1. **단일 작성자** — D2의 advisory lock으로 선제 해결됨. 변동 없음.
2. **A1 partial 시맨틱이 Celery로 이전되지 않음** — **여전히 미해소다.** `asyncio.wait_for` 취소는
   같은 프로세스 안이라 `flush_partial()`이 워커 버퍼에 닿지만, Celery **하드** 타임아웃
   (`task_time_limit`)은 프로세스를 죽여 버퍼가 증발한다. 이 결정은 (a) 태스크 시간 제한을
   run 규모에 맞게 크게 잡고(soft 3600s / hard 3900s — celery_app.py 전역 기본값 300/360s는
   `dig` 하나의 600s에도 못 미친다), (b) soft 타임아웃 예외를 잡아 `job_failed`를 남긴 뒤
   resume으로 회수하는 경로를 둔다. **그래도 하드 킬 시 진행 중 라운드의 partial 클레임은
   유실된다** — 다만 커밋된 라운드는 원장에 남으므로 resume이 그 지점부터 속행한다.
   손실 경계가 "라운드 하나"로 줄었을 뿐 사라지지는 않았다. M2의 partial AC는 **Celery
   환경에서 여전히 재검증 대상**이다.
- **부수 리스크(인라인 SSE ↔ nginx `proxy_read_timeout`)는 해소됐다.** POST가 더 이상 스트림을
  붙들지 않고, GET 스트림은 `events_stream_idle_timeout`(기본 300s)로 스스로 닫힌 뒤
  클라이언트가 `?after=<seq>`로 재접속해 이어받는다.

**영향 — 3b가 남았다:** 이 결정은 스펙 §5의 AC 중 **AC1·AC5·AC6·AC7만** 이행한다. 남은 것:
- **AC2** 챗 요청이 deep analysis 실행 중 블로킹되지 않는다
- **AC3** `graph.py`에서 `_deep_analysis_orchestrator_node`가 제거된다
- **AC4** 챗과 전용 API가 동일한 이벤트 스트림 계약을 사용한다(R4 no-op 싱크 해소)

이 셋은 **챗 API 계약을 바꾸므로 프론트엔드 변경이 필수다**(스펙 §5.4, K4). FE 준비도가 낮다는
감사 결과가 있으므로 3b는 FE 작업과 조율해 별도로 진행한다. 그때까지 `_deep_analysis_orchestrator_node`는
`9763eb5`의 wall-clock 바운드를 단 채 그대로 남는다 — **제거는 3b의 일이다.** 경계 고정:
`tests/workflow/test_deep_analysis_job_no_regression.py`.

**영향 — 스트림 해상도는 라운드 단위다:** `Ledger.log()`는 flush만 하고, 다른 프로세스에
보이려면 커밋이 필요하며 커밋은 `Orchestrator._checkpoint()`가 한다. `_checkpoint`는 라운드
경계와 `_finalize` 중간에 호출되므로 claim 단위 실시간성은 나오지 않는다. 3a의 AC 중 어느 것도
이를 요구하지 않는다. claim 단위 스트리밍은 3b에서 챗 SSE 프로토콜 통합과 함께 다룬다.

**영향 — 동시 실행 방지는 도입하지 않는다:** 같은 run에 대해 두 job이 동시에 도는 것을 막는
리스(lease)는 만들지 않았다. 크래시한 워커와 실행 중인 워커를 이벤트 로그만으로 구별할 수 없기
때문이다(둘 다 `job_started`에 종료 이벤트 없음). 대신 P2의 advisory lock이 원장 쓰기를
직렬화하고, 소비 회계가 DB에 있으므로 최악의 경우도 **진행 중이던 라운드 하나를 다시 도는 것**에
그친다 — 이미 원장에 기록된 지출은 어느 경로로도 두 번 청구되지 않는다. 리스가 필요해지면
`deep_analysis_runs`에 heartbeat 컬럼을 더하는 별도 결정으로 다룬다.

---

## D23. 챗은 job의 제출자다 — D18을 대체한다 (3b: 노드 제거·핸들 이벤트·리포트 영속화)

**결정:** **D18을 대체한다.** D18은 스스로를 "챗 경로의 라우팅 대상만 교체하는 첫 이동"이라
규정하고 per-claim 스트리밍의 챗 편입을 "그 다음 단계"로 예고했다 — 이 결정이 그 단계다.
`_deep_analysis_orchestrator_node`(하네스를 `asyncio.wait_for`로 완주시키던 노드)와
`_persist_deep_analysis_failure`를 **제거**하고, 라우팅 키 `"deep_analysis"`를
`_deep_analysis_dispatch_node`로 돌린다. 이 노드는 run을 만들고 job을 제출한 뒤
`neos:deep_analysis_started {run_id, events_url, assistant_message_id}` 챗 SSE 이벤트를
발행하고 **END로 단락한다**. 진행 상황과 리포트는 전용 스트림
`GET /api/v1/deep-analysis/{run_id}/events`가 전달한다 — 챗과 전용 API가 같은 계약을 쓴다.

**근거 — 캡이 사라지는 것은 퇴행이 아니다:** `9763eb5`의 `node_wall_clock_cap`이 이 결정과
함께 사라진다. D22가 정리했듯 세 예산은 프론트 `maxDuration` 60s < 노드 캡 300s < `dig`
하나의 `wall_clock_cap` 600s이고, **가장 작은 예산이 클라이언트 쪽에 있다.** 노드 캡은
"호출자가 떠난 뒤 백엔드가 자원을 붙들고 있는 것"만 막았을 뿐 사용자가 결과를 받게 하지
못했다. 실행이 요청 밖으로 나간 지금 노드가 붙들 자원 자체가 없으므로 바운드할 대상이 없다.
스펙 §5.2가 "Phase 3이 이걸 구조적으로 없앤다"고 규정한 그대로다. 회귀 고정:
`tests/workflow/test_deep_analysis_job_no_regression.py::test_blocking_chat_node_is_gone_after_phase_3b`가
`node_wall_clock_cap`의 재등장을 금지한다 — 그것이 돌아온다는 것은 블로킹 실행이 돌아왔다는 뜻이다.

**근거 — 챗 턴을 END로 단락하는 이유:** 디스패치 노드를 `RESULT_INTEGRATOR`로 합류시키면
후속 노드(fact-check·품질 검증·응답 생성)가 아직 존재하지 않는 리포트를 기다리게 된다.
A2UI의 `UI_FRAME_GENERATOR → END` 단락이 이미 같은 형태의 선례다. 회귀 고정:
`tests/workflow/test_deep_analysis_node.py::test_dispatch_node_registered_and_terminal_when_flag_on`.

**결정 — 리포트 영속화는 실행자 계층에 둔다:** `jobs.py`는 프레임워크 프리이므로
(LangChain/LangGraph/FastAPI/Celery/ChatService 미임포트) 리포트를 대화 메시지로 쓰는 일을
할 수 없다. 그대로 두면 리포트는 `job_completed` 이벤트 페이로드로만 나가고, **프론트가 그
순간 연결돼 있지 않은 run은 대화에 아무것도 남기지 않는다.** 영속화는
`neos/tasks/deep_analysis_job_task.py::_persist_assistant_message`가 맡는다(3a에서 이미
그 위치에 구현됐고, 3b는 챗 경로가 `conversation_id`/`assistant_message_id`를 실제로
채우게 만들어 이 경로를 활성화한다). 이 함수는 Celery 태스크와 inline asyncio 태스크가
**공유하는 `_execute` 본문**에 걸려 있어, 실행자별 코드 복제 없이 두 경로가 자동으로
커버된다 — 한쪽만 영속화하면 `CELERY_ENABLED` 값에 따라 리포트가 남기도 하고 안 남기도
하는 유령 버그가 된다. 콜백 주입 대신 이 위치를 고른 이유는 경계가 이미 거기 있기
때문이다: `neos/tasks/`는 정의상 통합 계층이고, 주입은 호출자마다 어댑터를 요구해 실행자
두 개가 서로 다른 어댑터를 쓸 여지를 만든다. 회귀 고정:
`tests/tasks/test_deep_analysis_report_persistence.py`.

**결정 — `conversation_id`를 `AgentState`에 명시 필드로 추가한다:** 챗은 `session_id`에
`conversation_id`를 실어 보내지만 `/api/v1/query`는 `session_id`를 진짜 세션으로 쓴다.
두 의미를 겹쳐 쓰면 대화가 아닌 run에 엉뚱한 `conversation_id`가 박혀 `add_message`가 없는
대화를 가리킨다. 대화 밖에서 시작된 run은 `conversation_id`/`assistant_message_id`가 모두
`None`이고, 리포트는 이벤트 스트림으로만 전달된다.

**이탈 — 챗 API 계약이 바뀐다(스펙 §5.4, K4):** 챗 응답이 "완성된 리포트 1건"에서
"job 핸들 + 별도 스트림"으로 바뀐다. 프론트엔드 변경이 필수다. 계약 필드는
`{run_id, events_url, assistant_message_id}`로 고정했고
`tests/api/models/test_deep_analysis_started_event.py`가 이를 못 박는다.

**영향 — AC7 무회귀는 그대로다:** `DEEP_ANALYSIS_ENABLED=false`(기본)이면 라우팅 맵에
`"deep_analysis"` 키가 없고 `WorkflowNode.DEEP_ANALYSIS_DISPATCH` 노드도 등록되지 않는다.
구조적 보장의 형태는 D18과 동일하고 노드 이름만 바뀌었다(`DEEP_ANALYSIS_ORCHESTRATOR` →
`DEEP_ANALYSIS_DISPATCH`). 회귀 고정:
`tests/workflow/test_deep_analysis_node.py::test_no_regression_deep_analysis_off_by_default_node_not_registered`.

**영향 — 스트림 해상도는 여전히 라운드 단위다:** D22가 기록했듯 `Ledger.log()`는 flush만
하고 커밋은 `Orchestrator._checkpoint()`가 라운드 경계에서 한다. 챗이 전용 스트림을 구독하게
된 지금도 claim 단위 실시간성은 나오지 않는다 — 이는 하네스의 커밋 주기 문제이지 소비
경로의 문제가 아니며, 스펙 §5의 어떤 AC도 이를 요구하지 않는다.

**영향 — D18 선결 조건 3건의 최종 상태:** (1) wall-clock 바운드 → 노드 제거로 **무의미해짐**,
(2) fail_run 내구성 → 노드 제거로 사라졌고 job 쪽 `_record_failure`가 같은 역할을 이어받음,
(3) 분류기 intent 미도달 → **D21이 해소**(질의 유형 기반 라우팅).

## D24. truncation은 D14 fail-open의 사유가 아니다 — judge 반려

**결정:** `AgenticGrader.grade`가 `TruncatedResponseError`를 받으면 **mandatory 여부와
무관하게** `Verdict(ok=False, code="E_UNSUPPORTED", detail="judge_truncated")`로 반려한다.
`JSONParseError`(비-truncation)에 대한 D14의 미심사 통과는 그대로 유지된다.

**근거:** D14는 "judge가 판정 불가한 응답을 냈다"를 전제로 한 결정이다. truncation은 다르다 —
판정이 *미완성*일 뿐 부재가 아니다. `20260802T052306Z` 표본에서 잘린 judge 응답 하나는 이미
`"label": "CONTRADICTS"`를 내뱉은 뒤 잘렸고, 파싱 실패가 D14 fail-open을 발동시켜 **거절이
승인으로 뒤집혔다.** 저가치 샘플 경로였으므로 D14의 mandatory 예외로도 막히지 않았다.

**이탈:** D14 원결정 중 `judge_unparseable`의 저가치 샘플 fail-open을, 원인이 truncation인
경우에 한해 철회한다.

**영향:** 반려된 claim은 기존 경로대로 재조사되고 `claim_retry_cap` 소진 시 `unverified`로
보고서 「한계」 절에 남는다(빈손 종료 없음). **claim funnel 수치가 이동하므로 이전 표본과
직접 비교할 수 없다** — `docs/TODO_260729.md` E1의 baseline 단절이 한 번 더 발생한다.
discard recall 재측정(C1)은 이 변경 이후 표본으로 수행해야 두 효과가 섞이지 않는다.

## D25. 마무리 floor를 중첩 계단으로 분할한다

**맥락:** floor가 단일 풀이었고 출력 토큰만 계상했다. `reserve()`는 입력+출력을 뺀다.
574 run · `synth_pass` 0건.

**결정:** `REPORT_STAGES`(assembly·grading) 전용 안쪽 tier를 두고, 두 tier 모두 입력
허용량을 포함해 사이징한다. 마무리 프롬프트는 `prompt_input_bound`로 측정해 허용량 안으로
강제한다.

**기각한 대안:** `reduce_node` 호출 수 하드 캡 — 풀 격리가 같은 일을 하며 "예산은 남았는데
못 부른다"는 새 실패 모드를 만든다.

**기각한 대안:** `conservative_input_bound` 완화 — `settle()`의 계약이 참인 상한에 의존한다.

**부수 결정:** dev `global_token_cap` 20,000 → 100,000. 기존 캡은 워커 호출 하나
(input_bound 5,542~17,723)도 담지 못했다.

**영향:** `report_floor_tokens`가 `TokenBudget`의 독립 tier로 들어가 `node_reduction`이
아무리 반복돼도 `report_assembly`·`report_grading` 몫에 닿지 못한다(회귀 고정:
`tests/workflow/deep_analysis/test_budgeter.py`). 마무리 프롬프트 클램프는
`tests/workflow/deep_analysis/test_prompt_clamp.py`가 고정한다. 측정 결과: default
프로파일 `report_floor_tokens` 110,400 / floor 합계 131,200 = cap의 43.7%, dev
34,800 / 41,040 = 새 cap(100,000)의 41.0%. **`synth_pass ≥ 1`은 이 결정으로 아직
관측되지 않는다** — 라이브 표본이 필요하며, 로드맵 §8 W1과 §2.2 S1은 이 결정만으로
충족되지 않는다.

## D26. 정지 사유는 예산 상태가 정한다. 리포트 본문의 정본은 `job_completed`다.

**결정:** 정지 사유 판정을 `_mark_stop_reason()` 하나로 접어 정상 종료 경로와 예외 종료
경로 양쪽에서 부른다. 리포트 본문은 `report_path` 컬럼을 채우는 대신 `Ledger.report_markdown()`과
`DeepAnalysisAnalyticsService.report_bodies()`로 `job_completed` 페이로드에서 읽는 조회
경로를 만든다. 강등(`degradations`) 판정 기준은 "리포트 내용을 깎았는가"로 정하고, FE
라벨 8종을 추가한다.

**근거 — G9:** 정지 사유를 판정하는 코드가 정상 경로(`orchestrator.py`의 if/elif)와
예외 경로 두 벌이었고 서로 달랐다. `TokenBudget.reserve`는 캡 소진과 floor 정지 두 사유
모두에 같은 `TokenBudgetExhausted`를 던지므로 예외 타입만으로는 구분할 수 없는데, 예외
핸들러는 구분을 시도조차 하지 않고 무조건 소진으로 기록했다. 실측 6건 중 4건이 오분류였다.

**근거 — G4, 로드맵의 전제를 정정한다:** `report_path`가 574 run 전부 NULL인 것은 사실이나,
리포트 본문이 유실된 적은 없다. `jobs.py`가 완료 이벤트(`job_completed`) 페이로드에
`report_markdown`을 싣고(AC6), `neos/` 전체에서 `orchestrator.run()`의 호출자는 `jobs.py`
하나뿐이라 모든 실행이 이 경로를 지난다. NULL인 것은 열 포인터이지 본문이 아니다. 컬럼은
채우지도 은퇴시키지도 않고 — 그것은 별도의 스키마 결정이다 — 이미 있는 본문을 향한 조회
경로만 만들었다.

**근거 — FE1:** 강등 판정 기준은 "리포트가 사용자가 받았어야 할 것보다 못한가"다.
최종 리포트 내용을 직접 깎는 3종(`report_assembly_degraded`,
`finalization_prompt_clamped{exhausted:true}`, `node_reduction_degraded`)만
`degradations`에 누적한다. `llm_truncated`는 확장 재시도가 성공하면(`truncation_handled.
action === "retried_ok"`) 최종 산출물에 영향이 없어 제외했다 — 재시도 성공/실패를 가르려면
두 이벤트를 상관시키는 상태 기계가 필요하고 이번 범위를 넘으므로, 잘못된 경고보다 과소
보고를 택했다. 단, `degradations`를 화면에 그리는 일은 이번 범위 밖이다(FE4로 추적) —
상태에는 쌓이지만 아직 아무 컴포넌트도 읽지 않고, `deep-analysis-status.tsx`는
`phase === "completed"`가 되는 순간 `lastActivity` 줄을 감춘다.

**발견:** `judge_budget_exhausted`는 독립 이벤트 kind가 아니다. 판정자가 굶었다는 사실은
`report_graded` 이벤트 payload의 **최상위** `judge` 키(`"budget_exhausted"` /
`"truncated"` / `"unparseable"`)로 남는다 — 오케스트레이터가 `{"ok": ..., "attempt":
..., **verdict.diagnostics}`로 로그하며 `diagnostics`를 spread하기 때문에
`payload.diagnostics.judge`가 아니라 `payload.judge`다. FE의 실제 결함은 라벨 누락이
아니라, `report_graded` 분기가 `payload.ok`만 보고 굶은 판정자의 통과를 실제 승인과
같은 문구로 냈다는 것이었다.

**미해결로 남는 것 (G10):** `_mark_stop_reason`은 `exhausted`와 floor 미달 두 경우만
판정한다. `TokenBudget.reserve`가 `available_for_investigation - input_bound <
min_viable`로 거절하는 세 번째 경우 — 헤드룸은 있지만 `input_bound` 때문에 거절된 예약 —
는 어느 분기에도 걸리지 않아 이벤트가 전혀 남지 않는다. `_default_split_decompose`가
이 경로에 닿을 수 있다(측정된 `worker_analysis` `input_bound` 5,542~17,723, dev
available 12,000). 세 번째 분기를 추가하는 것은 이번 결정의 범위가 아니다 — 다음
웨이브의 설계 판단으로 남긴다. 로드맵 §7 G10.

**영향:** floor 정지 오분류는 **코드상 해소**됐다 — `_mark_stop_reason()` 단일 판정이
2026-08-04 실측(6건 중 4건 오분류)이 지적한 원인을 없앴다. 다만 이것이 새 라이브
표본에서 "0건"으로 **재측정된 적은 없다** — D25가 `synth_pass`에 적용한 것과 같은
규율로, 재측정은 라이브 표본에서 한다. G3(게이트 재보정)가 표본 전체의 리포트 본문을
읽을 수 있게 됐다(`a258f36e`, 원본 `f200b26c`). FE가 실패 이벤트 8종에 라벨을 붙이고
강등 상태를 `degradations`로 누적한다(`a9dbcfe3`) — 단 그 상태를 화면에 그리는 일은
아직 없다(FE4). 로드맵 §2.2 S3이 충족됐고, S4·S6은 **부분** 충족이다(각각 G10, FE4가
남는다). S1(`synth_pass ≥ 1`)은 라이브 표본 미실행으로 여전히 ❌다.

## D27. 강등은 화면까지 간다. 새로고침 후 출처는 메시지 메타데이터다.

**맥락:** D26이 강등을 상태(`progress.degradations`)까지 밀어냈으나 소비자가 0곳이었고,
종결된 run 은 다시 구독하지 않으므로 새로고침하면 그 상태가 사라졌다. 추적해보니 더
근본적인 문제가 있었다 — 백엔드는 메시지에 `deep_analysis_run_id` 를 심는데 프론트는
`deep_analysis` 를 읽어서, 새로고침하면 **진행 카드가 통째로** 사라졌다.

**결정:** (1) `Ledger.degradations()` 로 원장에서 강등을 집계하고 `execute_run` 을 거쳐
어시스턴트 메시지 메타데이터(`deep_analysis_degradations`)에 영속화한다. (2) 프론트는
라이브 스트림에서 같은 규칙으로 누적하되 새로고침 후에는 메타데이터를 출처로 쓴다.
(3) 굶은 판정자(`report_graded.judge`)를 강등 넷째 항목으로 추가한다. (4) 표시 문구는
`web/lib/deep-analysis/degradation.ts` 순수 함수에 두고 컴포넌트는 map 만 한다.

**근거 — 굶은 판정자:** D26은 강등을 "리포트 내용을 깎았는가"로 정의했다. 판정자는
내용을 바꾸지 않지만 **보증이 부재**한다 — 리포트가 실제 심사 없이 게이트를 통과했다.
축이 다를 뿐 사용자가 알아야 하는 사실은 같다. `graders/report.py` 의 세 강등 모드가
전부 `ok=True` 로 재조립 루프를 끝내므로 `judge` 키가 달린 이벤트는 run 당 최대 1건이고
항상 최종 판정이다 — 중간 시도가 오탐으로 잡히지 않는다.

**근거 — 표시 문구를 lib 에 두는 이유:** `web/package.json` 의 `test:source` 는
`tsx --test` 라 DOM 이 없다. 표시 로직이 컴포넌트로 들어가면 회귀 가드가 0 이 된다.

**기각한 대안:** 종결된 run 도 카드를 펼치면 `after=0` 으로 이력 재생 — 규칙 중복이 0
이고 충실도가 100% 이지만 **펼치지 않으면 영영 모른다.** 접힌 카드에 경고를 띄우려면
먼저 재생해야 하고 재생하려면 펼쳐야 하는 순환이 생긴다.

**남긴 부채:** "어떤 이벤트가 강등인가" 규칙이 두 언어로 구현돼 있다
(`ledger.py._degradation_kind()` / `progress.ts.degradationKind()`). 문구는 프론트 한
곳뿐이라 중복되지 않는다. 상호 참조 주석 · 양쪽 테스트의 동일 fixture · 로드맵 §7 FE6
으로 표시했다. 갈라져도 **과소 보고** 쪽으로 기운다.

## D28. 거절은 사유를 안다. 그 사유는 예외가 운반한다.

**맥락:** D26 이 정지 사유 판정을 `_mark_stop_reason()` 하나로 접으면서 구멍을 하나
남겼고 코드가 스스로 그렇게 적었다(`orchestrator.py`, "tracked, not fixed here").
`TokenBudget.reserve` 는 `available_for_investigation - input_bound < min_viable` 일
때도 거절하는데, 그때는 헤드룸이 **남아 있어서** 두 상태 분기 모두 거짓이다. 그 정지는
원장에 아무것도 남기지 않았다. 로드맵 §7 G10.

**결정:** (1) `TokenBudgetExhausted` 가 `cause`(`tier_floor` | `input_bound`)와 거절
순간의 수치(`stage`·`model`·`input_bound`·`ceiling`·`requested`·`granted`)를 싣는다.
모든 필드가 기본값을 가져 맨손 생성이 계속 유효하다. (2) `_mark_stop_reason(exc=None)`
에 셋째 분기를 달되 **상태 분기 둘 뒤에** 둔다. (3) 새 kind
`investigation_stopped_at_input_bound` 를 쓴다 — `floor_tokens` 는 싣지 않는다.
(4) synthesizer 의 하드코딩된 강등 `reason` 두 곳이 `cause` 를 따른다.

**근거 — 왜 예외인가:** 사유를 아는 코드는 `reserve()` 하나뿐이다. 캡 소진과
`input_bound` 거절은 같은 예외 타입이고, 거절 **후**의 예산 상태는 두 번째 경우에
"헤드룸이 남은 정상 run" 과 구별되지 않는다. 사후 상태로는 복원할 수 없는 사실이므로
거절 지점에서 실어 보내는 것 외에 방법이 없다.

**근거 — 왜 상태 분기가 먼저인가:** D26 이 세운 판정("경로가 아니라 예산 상태에서")을
보존하기 위해서다. 예산이 실제로 없으면, 마지막 거절이 우연히 큰 프롬프트였다는 사실은
정지 사유가 아니다. 새 분기는 **지금 침묵이 나는 자리만** 채운다.

**근거 — 왜 별도 kind 인가:** floor 정지는 "남은 것이 마무리 몫뿐", input_bound 정지는
"여유는 있는데 이 프롬프트가 안 들어감"이다. 하나로 접으면 D26 이 없앤 실수 — 한 라벨이
두 사유를 덮는 것 — 를 그대로 반복한다. 이미 쌓인 floor 이벤트에는 분별 키가 없어 경계
전후 비교도 애매해진다.

**의도적 보존:** `tier_floor` 의 강등 `reason` 은 옛 문자열 `"token_budget_exhausted"`
그대로다. 이미 원장에 쌓인 강등 이벤트가 그 어휘를 쓰고 있어 집계가 이어져야 한다.
새 문자열 `"input_bound"` 는 지금까지 존재하지 않던 구별에만 붙는다. `test_prompt_clamp.py`
와 `test_synthesizer.py` 의 기존 단언이 **수정 없이** 통과하는 것이 그 증거다.

**범위 밖:** 거절 **전부**를 기록하는 `token_budget_refused`. 워커와 판정자가 삼키는
거절은 정지가 아니라 부분 실패이므로 stop 이벤트로 세면 S4 집계가 오염된다.

**영향:** `_mark_stop_reason` 의 어느 분기에도 안 걸리는 정지는 이제 `score_floor`
케이스 하나뿐이며, 그것은 예산 사건이 아니라 의도적 무이벤트다. **코드상 해소 —
재측정은 라이브 표본에서**, D25·D26 과 같은 규율이다. 로드맵 §2.2 S4 는 ⚠️(코드상
해소, 라이브 미측정)로 남는다. 강등 어휘를 건드리지 않았으므로 FE6(이중 구현)은 그대로다.

## D29. W1 라이브 표본 — 마무리가 출력을 냈다. 이제 게이트가 문제다.

**맥락:** D25(마무리 예산 풀 분할)와 D28(거절 사유) 이후, §10.2 의 "정확히 1회" 규칙에
따라 5+1 라이브 표본을 한 번 실행했다.
아티팩트: `artifacts/deep-analysis-funnel/20260807T164924Z` (트리 `07790085`,
2026-08-07 15:57:30~16:49:24Z, 51분 54초, exit 0, run 6건 전부 `completed`).
**재실행하지 않는다.**

**결과 — S1 충족:** `synth_pass` 18건 / 6 run (run 당 3). 574 run 동안 0 이던 값이다.
`report_assembly` stage 가 처음으로 예약을 받았다(18건). `report_assembly_degraded`
는 0건 — 템플릿 강등이 한 번도 일어나지 않았다. 리포트는 `[C:...]` 인용 마커가 실린
LLM 산문이다.

**결과 — S4 충족:** 6/6 run 이 **정확히 하나씩** 정지 이벤트를 가진다.
`investigation_stopped_at_input_bound` 5건 · `investigation_stopped_at_floor` 1건 ·
`token_budget_exhausted` 0건. **무이벤트 정지 0건.**

**D28 을 표본 전에 한 것이 이 표본을 구했다.** 새로 만든 정지 kind 가 6 run 중 5건에서
발생했다 — 이 클래스는 드문 게 아니라 **지배적 사유**였다. 하루 전 코드였다면 그 5건은
영구 침묵으로 기록됐을 것이고, 다시 셀 기회는 규칙상 없다. 같은 이유로
`node_reduction_degraded` 56건 **전부**가 `reason=input_bound` 로 기록됐다 — 옛 코드는
56건 전부에 `token_budget_exhausted` 라는 거짓 사유를 달았을 것이다.

**미달 항목의 정확한 서술:** 완료 기준 중 "`finalization_prompt_clamped` 의
`exhausted=true` 건수 0" 은 **문자 그대로 미달**이다(12건). 그러나 그 기준이 막으려던
가짜 양성 — 루트 답변만 남은 리포트가 LLM 성공처럼 보이는 것 — 은 일어나지 않았다.
어느 run 도 `dropped_primary` 가 child 수에 도달하지 않았다(6/14, 7/11, 6/14, 6/10).
**가짜 양성 `synth_pass` 는 0건**이고, 대신 4/6 run 이 child finding 의 절반가량을
조립 프롬프트에서 떨어뜨렸다. 두 사실을 뭉치지 말 것.

**드러난 다음 문제 (W3/G3):** `report_graded` 가 6/6 run 에서 3회 전부 `ok=False` 이고
`report_grading` 예약은 0건이다 — **에이전틱 리포트 판정자는 여전히 한 번도 돌지
않았다.** 결정론 게이트가 먼저 막는다. `uncited_ratio` 는 3 run 이 1.0, 3 run 이
0.29~0.50 으로 18회 시도 전부 임계값 0.20 을 넘겼다. 그런데 본문에는 인용 마커가
다수 실려 있다 — **마커가 있는데 비율이 1.0** 인 run 이 3개라는 것은 임계값이 아니라
**분자·분모 정의**를 의심하게 한다. G3 는 D-2(assertion 0건 채점 정책)를 정하기 전에
게이트가 마커를 실제로 세는지부터 확인해야 한다.

**manifest 규율 보강 (`07790085`):** 이 표본부터 `execution_receipt.verification`
(pytest 요약 + ruff), `config_fingerprint.git`(commit·branch·dirty),
`config_fingerprint.resolved_models`(역할 해석 결과)를 남긴다. §10.2 가 영수증 항목으로
적어둔 test/Ruff 가 어떤 표본에도 없었고, 모델은 네 칸 모두 `null` 이라 E3(judge =
scout) 상태를 사후에 확인할 수 없었다. 이 표본의 지문은 judge·scout 이 둘 다
`claude-sonnet-5` 임을 명시한다 — E3 는 의도적으로 유예된 채 측정됐다.
ruff 는 `exit_status: 1`(저장소 전역 370건, 전부 기존 위반)로 **정직하게** 기록됐다.

## D30. D29 의 게이트 해석 정정 — 게이트는 옳게 세고 있었다.

**정정 대상:** D29 의 마지막 문단이 "본문에는 인용 마커가 다수 실려 있다 — 마커가
있는데 비율이 1.0 인 run 이 3개라는 것은 임계값이 아니라 **분자·분모 정의**를
의심하게 한다" 고 적었다. **틀렸다.** D29 의 나머지 관측(표본 수치, S1·S4 충족)은
전부 유효하다.

**재현 방법:** 표본을 다시 돌리지 않았다 — `job_completed` 페이로드에 보존된 6개
리포트 본문(D26/G4 가 만든 조회 경로)에 `graders/report.py` 의 `_uncited_stats` 를
그대로 다시 적용했다. 새 LLM 호출 0회.

**실측:** 비율 1.0 인 세 run(`d74dcbe3`·`51fd8d7d`·`ea7e2f2e`)의 원본 `[C:]` 마커는
**0개**였다. 마커가 있는 세 run 은 6·8·60개였고 비율은 0.33·0.44·0.29 였다. 상관은
완벽하다 — **게이트는 자기가 주장하는 것을 정확히 센다.**

**진짜 사슬:** (1) LLM 이 인용을 안 한다(3/6 run 이 verified claim 을 갖고도 마커 0개)
→ (2) 결정론 게이트가 18회 전부 반려 → (3) 에이전틱 판정자는 short-circuit 으로 도달
불가 → (4) 캡 소진 시 `_finalize` 가 `last`(**렌더 전 draft**)에 부록만 붙여 반환
→ (5) 사용자가 원본 `[C:...]` 마커와 출처 없는 리포트를 받는다.

**교훈:** 저장된 본문에서 `[C:...]` 를 보고 "인용이 실렸다" 고 읽은 것이 오류의
출발이었다. 최종 산출물에 원본 마커가 남아 있다는 것은 인용의 증거가 아니라
**렌더가 산출물까지 살아남지 못했다는 증거**다. §3.2 의 "모든 실패가 성공처럼
보였다" 가 한 번 더 통했다.

**결과:** W3 를 세 갈래로 쪼갠다 — W3-a(캡 소진 경로가 렌더된 리포트를 반환한다,
정책 무관·사용자 영향 최대) · W3-b(LLM 인용 미준수) · W3-c(D-2 채점 정책).

## D31. 강등된 잎은 자기 클레임을 들고 나간다. 캡이 소진돼도 렌더된 것을 낸다.

**맥락:** 2026-08-07 표본에서 리포트 게이트가 6/6 run × 3회 = 18회 전부 반려했다.
D30 이 게이트 자체는 결백함을 확인했으므로 앞뒤를 팠고, 결함 두 개가 나왔다.

**W3-a — 캡 소진 경로가 렌더 전 draft 를 반환했다.** `_finalize` 는 `last`(조립 원본)에
부록만 붙여 내보냈다. 표본의 6개 run 전부 이 경로로 나갔으므로, 사용자가 받은 리포트에는
`[C:da8b7072]` 원본 마커가 그대로 있고 `## 출처` 절이 없었다. **결정:** 렌더에 성공한
마지막 텍스트(`last_rendered`)를 반환한다. 모든 시도가 orphan 이면 그때만 원본으로
떨어진다(§6.8 빈손 금지). 부수 효과로 원장의 `uncited_ratio` 가 **배달된 텍스트**를
서술하게 된다 -- 채점한 것과 낸 것이 같아졌다.

**W3-b — 강등된 잎이 자기 verified claim 을 버렸다.** `_degraded_summary` 는 자식 답변을
이어붙이는 fallback 인데 **잎에는 자식이 없다.** 답변이 `""` 가 되고 그 잎의 클레임은
`[C:...]` 마커가 붙은 산문이 되지 못한 채 사라졌다. 그리고 강등된 리덕션의 대부분이
잎이었다(8/10, 11/14, 8/11, 8/11, 6/8, 1/2). 강등률 67~79% 인 5개 run 은 최종 리포트에
마커를 0~8개 실었고, 18% 인 run 하나만 60개를 실었다. **인용할 것이 없으니 게이트가
반려한 것이다** -- 모델이 지시를 어긴 것이 아니다(`final_compose.md` 는 인용을 명시적으로
요구한다).

**결정:** 강등된 잎은 자기 verified claim 을 `[C:id] 텍스트` 로 결정론적으로 렌더한다.
LLM 호출 없음. 마커를 보존하므로 CitationRenderer 가 해소할 수 있고, 검증된 클레임만
쓰므로 orphan 이 날 수 없다. 프롬프트 비계(evidence 원문·신뢰도)는 **싣지 않는다** --
그것은 모델 입력이지 독자용 산문이 아니다.

**기각한 대안:** 강등 시 클레임 전문 대신 개수만 남기기 -- 마커가 사라지는 문제를
그대로 두므로 아무것도 고치지 못한다.

**계보:** 이 진단의 출발점은 D28(거절 사유)이다. `node_reduction_degraded` 가
`reason=input_bound` 를 정직하게 적게 되자 강등의 원인과 규모가 처음으로 보였고,
그 다음 질문("강등되면 무엇이 남는가")이 빈 문자열 fallback 을 드러냈다. 사유를
정직하게 적는 일이 그 자체로 진단 도구였다.

**남긴 것 (W3-c):** "assertion 0건 리포트를 어떻게 채점할 것인가"(D-2)는 **다음 표본
전에는 판단하지 않는다.** W3-a·W3-b 가 조립 입력과 산출물을 둘 다 바꿨으므로, 지금의
게이트 통계는 이미 낡았다.

## D32. 아무것도 주장하지 않는 리포트는 만점이 아니라 전용 반려다 (D-2 확정).

**맥락:** 표본 #2(`20260808T023738Z`, 트리 `5ffe4d48`)로 W3-a·W3-b 의 효과를 쟀다.
W3-a 는 확인됐다 -- 산출물의 원본 `[C:]` 마커가 3개 run(최대 60개)에서 **0개 run** 이
됐고, `[N]` 각주가 처음 나타났으며(31·16·18·84) `## 출처` 절이 4/6 에 생겼다. 정지 사유는
floor 3 / input_bound 3 / exhausted 0 으로 **무이벤트 0건이 2회 연속** 유지됐다(S4).

W3-b 는 방향은 맞으나 **인과를 주장하지 않는다** -- 마커를 실은 run 이 3→4개, 최대
60→84개로 늘었지만 강등률이 run 별로 18~86% 로 흔들리고 §10.2 가 5+1 단일 관측의 인과
주장을 금지한다.

**표본 #2 가 새로 드러낸 것.** 산출물이 바뀌자 퇴화 케이스가 보였다. 18회 채점 중
**5회가 `assertions=0` 으로 만점(0.00)** 을 받았고, 그중 `a82648e3` 의 최종 리포트는
**완전히 빈 문자열**이었다. 그것을 막은 것은 `E_REPORT_NO_LIMITS` -- "한계와 미확인
사항" 제목이 없다는 **서식** 검사다. 모델이 그 제목만 찍었다면 내용 0인 리포트가
실질 검사를 전부 통과했을 것이다.

**결정 (D-2 = 제3 판정):** `assertions == 0` 이면 `E_REPORT_EMPTY` 로 반려한다.
`_uncited_stats` 는 그대로 0.0 을 낸다 -- **바뀐 것은 판정이지 측정이 아니다.**
전용 코드를 쓰는 이유는 그 함수의 독스트링이 이미 적어둔 것과 같다: "1.00 over one
assertion is a short report, 1.00 over forty is a badly cited one, and the two call
for opposite fixes". "아무 말도 안 했다" 와 "인용을 안 했다" 도 마찬가지다.
`E_REPORT_UNCITED` 에 접으면 다음 사람이 원인을 구분할 수 없다.

특성화 테스트 `test_a_report_with_no_assertions_scores_a_perfect_zero` 를 **의도적으로
깼다** -- 그 테스트가 "바꾸려면 의도적으로 깨라"고 요구한 대로다.

**함께 고친 것 -- 빈 조립이 성공으로 세어졌다.** `assemble` 은 호출 성공 직후 무조건
`synth_pass` 를 로그하고 `response.text` 를 반환했다. `a82648e3` 은 빈 리포트를 내고도
`synth_pass` 3건을 남겼다. **S1 이 세는 바로 그 지표가 존재하지 않는 리포트를 세고
있었다.** 빈 조립은 이제 `report_assembly_degraded`(`reason="empty_assembly"`)를 남기고
결정론 템플릿으로 떨어진다(§6.8 빈손 금지).

`report_assembly_degraded` 를 재사용한 것은 의도다 -- 이미 `_DEGRADATION_KINDS`
(ledger.py)와 `degradationKind()`(progress.ts) 양쪽에 등록돼 있어 **새 어휘 없이
사용자 화면까지 도달**한다. FE6 의 이중 구현을 건드리지 않는다.

**여전히 미해결:** `report_grading` 예약이 두 표본 모두 **0건**이다. 결정론 게이트가
매번 먼저 막으므로 에이전틱 리포트 판정자(§6.8)는 아직 한 번도 돌지 않았다.

## D33. 레코드는 만들어지는 곳에서 영속화한다 (D1b).

**맥락:** 데이터셋 콜렉터의 영속화가 `graph.py` 의 `_auto_save_dataset()` **한 곳**에서만
일어났다. Celery 워커와 deep-analysis job 서비스는 그 지점을 지나가지 않는 별도
프로세스이므로 거기서 만든 레코드는 프로세스와 함께 사라졌다(로드맵 §11.1 장애물 ②).
게다가 `clear_records()` 가 주석 처리돼 있어 메모리는 무한히 자라고, `save_jsonl()` 은
매번 전량을 다시 썼다.

**기각한 대안 -- 배출구를 더 만든다.** 워커 teardown, job 완료 훅, `atexit`. 자연스러워
보이지만 §11.1 이 경고한 함정이다: **새 진입점이 생길 때마다 누군가 flush 를 기억해야
하고, 잊으면 조용히 사라진다.** 이 저장소가 반복해서 다친 실패 모드를 계측 계층에
그대로 복제하는 셈이다.

**결정:** `add_record` 자체를 영속화 지점으로 만든다(`neos/dataset/record_sink.py`).
레코드 1건 = JSONL 1줄을 `datasets/records/{날짜}/{PID}-{난수}.jsonl` 에 append 한다.
**flush 라는 개념이 사라지므로** 어느 프로세스에서 돌든 상관이 없다.

싱크 매체로 PostgreSQL 대신 파일을 고른 이유: `create_llm_call_record` 가 동기 함수라
sync 호출부에서도 불리는데, async 엔진을 sync 에서 쓰려면 다리가 필요하고 DB 가 내려가면
수집이 멈춘다. 데이터셋 용도(재학습·평가 코퍼스)는 애초에 파일·배치 지향이고 기존
저장 매체도 `datasets/*.jsonl` 이라 소비자 변경이 작다. 대신 워커가 다른 호스트면
파일이 그 호스트에 남는다 -- 다중 호스트로 갈 때 다시 볼 지점이다.

**설계 제약 넷:** (1) 동기 I/O -- sync·async 양쪽 호출부에서 동작해야 한다.
(2) 프로세스당 파일 -- 잠금 없이 동시 쓰기, 파일명의 PID 가 출처를 남긴다.
(3) 절대 던지지 않는다 -- 수집 실패는 데이터 손실이지만 예외를 올리면 그 LLM 호출이
죽는다. 계측이 본업을 막으면 안 된다. (4) 잘린 줄은 읽기에서 건너뛴다 -- 프로세스가
쓰다 죽으면 마지막 줄이 불완전하고, 그 한 줄 때문에 앞의 멀쩡한 레코드를 잃을 이유가
없다.

**검증:** 완료 기준이 "별도 프로세스에서 살아남는다"이므로 **실제 서브프로세스를 띄워**
확인한다(`test_a_separate_process_leaves_its_records_behind`). 모킹으로는 이 성질을
증명할 수 없다.

**남긴 것:** 메모리 리스트와 `_auto_save_dataset()` 은 그대로다 -- 기존 산출물과
`get_statistics()` 소비자를 깨지 않기 위해서다. 디스크가 정본이고 메모리는 이 프로세스가
본 것의 캐시다. 다음은 D1c(코딩 루프·deep_analysis 어댑터)이며, 장애물 ①(D1a)과
②(D1b)가 둘 다 치워졌으므로 이제 어댑터만 붙이면 된다.

## D34. 조립도 잘리면 한 번 더 크게 시도한다 (W3-d).

**맥락:** W3-c 이후 게이트를 재확인했는데, **라이브 표본을 다시 쓰지 않았다.** W3-c 는
순수 결정론 코드이므로 표본 #2 가 원장에 남긴 진단값에 새 규칙을 재적용하면 답이
나온다(새 LLM 호출 0회). 그 재확인이 두 가지를 알려줬다.

**① W3-c 는 라벨만 바꾼다.** 5건이 `E_REPORT_NO_LIMITS` → `E_REPORT_EMPTY` 로
정밀화됐고 통과/반려는 하나도 바뀌지 않았다. **표본을 하나 아꼈다** -- 효과를 보려고
실행했다면 아무것도 새로 배우지 못했을 것이다.

**② 인용 기준을 넘긴 시도가 처음으로 있었다.** `dd8dc763` #2 가 `uncited_ratio`
0.1538 < 0.20 으로 통과하고도 `E_REPORT_NO_LIMITS` 로 반려됐다 -- "한계와 미확인
사항" 제목이 없다는 **서식** 검사다. 프롬프트는 그 절을 필수로 명시하므로 모델이
지시를 어긴 것이 아니라 **거기까지 쓰지 못했다.**

**근본 원인:** 조립 18회가 **전부** 상한에서 잘렸고(dev 1200 / default 4000, 정확히
상한값) `report_assembly` 의 `truncation_handled` 는 **0건**이었다. 잘림 확장
재시도(A2)가 `call_json` 에만 있고 조립은 `call_llm` 을 직접 쓰기 때문이다 --
`call_llm` 은 잘림을 기록만 한다. **모든 단계 중 조립만 회복하지 못했다.**

**또 하나의 "실패가 성공처럼 보인" 사례:** 최종 리포트에 `## 출처` 는 있는데
`## 한계와 미확인 사항` 이 없는 것이 프롬프트 순서상 모순으로 보였다. 답은 `## 출처`
가 LLM 이 쓴 것이 아니라 **CitationRenderer 가 각주를 붙이며 만든 제목**이라는 것이다.
출력은 본문 중간에서 잘렸고, 렌더러가 뒤에 제목을 붙여 꼬리가 살아남은 것처럼 보이게
했다.

**결정:** `call_text` 를 신설한다(`llm.py`). `call_json` 의 확장 재시도와 같은 판단을
하되 셋이 다르다: (1) **절대 던지지 않는다** -- 파싱 단계가 없고, 잘린 리포트도
리포트이며(§6.8) 던지면 run 이 죽는다. (2) 예산이 이미 상한을 깎았으면 재시도하지
않는다 -- 정산이 `remaining` 을 줄였으므로 두 번째가 더 작아진다(`call_json` 과 같은
이유). (3) 둘 다 잘렸으면 **내용이 더 많은 쪽**을 낸다.

**기각한 대안:** `synthesis_max_tokens` 를 키우는 것. 상한 조정은 D25 가 세운 floor
사이징(비율이 `synthesis_max_tokens` 에서 유도된다)과 얽히고, 무엇보다 **얼마가
충분한지 모른다.** 확장 재시도는 자기 적응적이라 그 질문에 답하지 않아도 된다.
상한 조정이 여전히 필요한지는 다음 표본이 말해줄 것이다.

**다음 표본에서 볼 것:** `report_assembly` 의 `truncation_handled` 가 0이 아닌지,
`E_REPORT_NO_LIMITS` 가 줄어드는지. **그때가 S2 를 판정할 시점이다.**

## D35. 계측은 계층마다 어댑터 하나로 (D1c 완료).

**결정:** D-8(b안)대로 `LLMCallRecord` 를 정본으로 두고 계층마다 어댑터를 하나씩
붙였다(`neos/dataset/adapters.py`). 새 스키마를 만들지 않고 기존
`create_llm_call_record` 팩토리를 재사용한다 -- 정본이 이미 있는데 하나 더 만들면
로드맵 §11.1 이 지적한 "usage 표현이 셋"을 넷으로 늘리는 셈이다.

**배선 지점이 각 계층에 하나씩이었다.**
- deep_analysis: `llm.py` 의 `_budgeted_dispatch` -- `call_llm` 과 `call_messages` 가
  모두 지나가므로 여기 한 번이면 계층 전체가 덮인다.
- coding: `runtime.py` 의 모델 생성 지점 -- `TrackedCodingModel` 로 감싼다.

**계측을 전송 계층 밖에 둔 이유:** 프로바이더 구현(`model/anthropic.py`)을 건드리지
않으므로 D4(네이티브 SDK 전환)가 그 아래를 바꿔도 계측이 함께 무너지지 않는다.
로드맵 §11.4 의 완료 기준 "전환 중 계측 공백 0"이 이 배치에 달려 있다.

**두 어댑터가 공유하는 규율:** (1) 절대 던지지 않는다 -- 계측 실패는 데이터
손실이지만 예외를 올려보내면 그 LLM 호출이나 코딩 루프가 죽는다. (2) 토큰은 API 가 준
것만 옮긴다(§A5) -- 둘 다 있을 때만 `usage` 를 만들고, 한쪽만 받았다고 나머지를 0 으로
채우지 않는다. 그것이 곧 자체 추정이고 하류 비용 집계를 조용히 틀어놓는다(§6 ③).

**코딩 루프는 `ModelCompleted` 에서만 기록한다** -- usage 를 싣고 오는 유일한
이벤트다. 스트림이 그것 없이 끝나면(예외·중단) 레코드를 남기지 않는다. 토큰을 모르는
레코드를 남기느니 없는 편이 낫다.

**D1 전체가 닫혔다:** a(탈-LangChain `d9681104`) · b(쓰기-즉시 영속화 `29223829`) ·
c(계층 어댑터 `6632d674`/`7f4beca1`). 코딩 루프는 Celery 워커에서 도는데, D1b 덕분에
그 프로세스에서 바로 디스크에 남으므로 flush 지점을 지나갈 필요가 없다 -- 세 조각이
서로를 필요로 했던 이유다.

## D36. 게이트는 인용 가능한 것만 채점한다 (W3-e·W3-f).

**W3-e -- 필수 절은 하네스가 소유한다 (`d429403a`).** 조립 출력이 세 표본 54회 전부
상한에 정확히 붙어 잘렸고(W3-d 의 확장 재시도 이후에도), 프롬프트가 마지막에 요구하는
`## 한계와 미확인 사항` 이 매번 죽었다. 두 표본 연속으로 **인용 기준을 넘긴 유일한
시도**가 그 절이 없다는 이유로 반려됐다(`dd8dc763` #2 0.267, `a38d441a` #2 0.191).

`## 출처` 는 CitationRenderer 가 붙이므로 그 문제가 없었다 -- 하네스가 소유하기
때문이다. 한계 절만 모델에게 맡겨져 있었는데 그 내용(`caveats`)은 `_finalize` 가
`_collect_caveats()` 로 이미 들고 있다. **구조적 완전성은 하네스의 일이지 모델의
일이 아니다.** 지어내지 않는다: caveat 이 없으면 "기록된 미확인 항목 없음"이라고
명시한다.

**결과 (표본 #4):** 한계 절 1/6 → **6/6**, `E_REPORT_NO_LIMITS` 1 → **0**.
반려 사유가 `E_REPORT_UNCITED` 하나로 좁혀졌다.

**W3-f -- 그 분모를 열어보니 인용 불가능한 것이 섞여 있었다 (`c12b3f07`).**
`a38d441a` 의 "인용 없는 사실 주장" 4건 중 **진짜 사실 주장은 0건**이었다: 리포트
자신에 대한 메타 문장 둘, 제목 조각 둘.

두 가지를 고쳤다. **임계값 조정이 아니라 채점 대상의 정정이다.**
(1) 마크다운 제목은 사실 주장이 아니다 -- `_sentences` 가 줄바꿈으로 나누므로
`### 1.` 이 독립 문장이 되고 숫자 때문에 assertion 이 됐다(표본 #4 run 당 1~7건).
(2) 한계 절은 채점 대상이 아니다 -- 검증하지 못한 것들의 목록이라 구조상 뒷받침할
verified claim 이 없다. `_report_body` 가 `## 출처` 를 빼는 것과 **같은 이유**다.

**W3-e 가 W3-f 를 드러냈다.** 한계 절이 항상 존재하게 되자 그 절의 불릿이 매번
집계에 들어갔고, `cb1593f2` 가 0.353 → 0.455 로 올라가면서 보였다. 고친 뒤 그 run 은
**0.185** 로 내려간다.

**표본 #4 재적용 (새 LLM 호출 0회): 3/6 이 임계값을 통과한다** (기록 기준 0/6).
단 이 재적용은 최종 저장 리포트 기준이고 기록값은 시도별이라 1:1 이 아니다 --
**정확한 판정은 다음 표본이 한다.**

**남은 것:** `bb8a2dbb` 는 마커가 0개다. 모델이 정말로 인용하지 않는 경우가 아직
있으며 그것이 다음 과제다. `report_grading` 예약은 네 표본 모두 **0건** -- 에이전틱
판정자는 여전히 한 번도 돌지 않았다.
