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

## D37. 게이트를 통과한 첫 리포트 — S2 충족 (표본 #5).

**아티팩트:** `artifacts/deep-analysis-funnel/20260808T140346Z` (트리 `c58a15bc`,
exit 0, 사전 게이트 2,456 passed). 1회만 실행.

**세 가지 최초가 한 표본에서 일어났다.**

1. **게이트를 통과한 리포트.** `71be9f89` -- 4,125자, 필수 4절 완비, `[1][2][3]`
   각주가 본문 전체에 박힌 산문, verified claim 23건. 574 run 동안 통과한 리포트는
   전부 빈 것이었고(G1), 그 뒤 네 표본 72회 시도에서 통과가 0건이었다.
   **S2 충족** -- 기준(통과 run 의 verified claim 중앙값 > 0)에 대해 23.
2. **에이전틱 판정자가 돌았다.** `report_grading` 예약 5건. 설계 §6.8 의 에이전틱
   판정은 네 표본 연속 0건이었고 §3.3 표가 "한 번도 실행된 적 없음"으로 적어둔
   항목이다. 이제 관측됐다.
3. **새 반려 사유 2종.** `E_REPORT_AGENTIC`(판정자가 실제로 반려)과
   `E_REPORT_MISSING_QUESTION`. 게이트가 인용 검사를 지나 더 깊은 층까지 도달한다.

**W3-f 가 예측대로 작동했다.** 저장된 리포트 재적용이 예측한 "3/6 이 임계값 아래"가
실행에서 정확히 3/6 으로 나왔다(0.000 · 0.062 · 0.095). 그중 1건만 통과한 것은
나머지 둘이 **인용이 아닌 다른 검사**에 걸렸기 때문이다 -- 게이트가 비로소 층층이
작동한다는 증거다.

**정직한 한계.** 통과 run 이 **1개(n=1)**다. §10.2 대로 5+1 단일 관측으로 인과를
주장하지 않는다. 이 표본이 증명한 것은 "게이트가 알맹이 있는 리포트를 통과시킬 수
있다"이지 "이제 통과한다"가 아니다 -- 통과율은 1/6 이다.

**출하 기준 현황:** S1·S2·S3·S4·S6 충족, **S5(CI 결정론)만 남았다**. S4 는 표본
5회 연속 무이벤트 정지 0건이다.

**W3 계보 정리 (전부 라이브 측정이 이끌었다):**
W3-a 렌더된 리포트 배달(`24045c7e`) → W3-b 강등된 잎이 클레임 보존(`bd724b92`) →
W3-c `E_REPORT_EMPTY` + 빈 조립 강등(`94067e11`) → W3-d 조립 확장 재시도(`b74d00bf`)
→ W3-e 하네스가 한계 절 소유(`d429403a`) → W3-f 채점 대상 정정(`c12b3f07`).
여섯 수정 중 **다섯이 표본이 드러낸 것**이고, 그중 셋은 앞선 수정이 만든 부작용이
다음 결함을 드러낸 경우다.

---

## D38. 통과율 1/6을 막던 것은 대부분 하네스였다 (2026-08-09)

**맥락.** S2가 충족된 뒤 통과율 자체(1/6)를 보기로 했다. 표본 #5의 6개 run ×
3회 시도 = 18회 채점을 전부 펼치고, 카세트에 남은 LLM 호출까지 되짚었다.

**측정.** 전체 원장 273회 채점 중 `E_REPORT_UNCITED`가 250회(91.6%)다. 다만
비율 분포가 중요하다 — 기록된 94건의 중앙값 0.500, p75 1.000. **아슬아슬하게
놓친 게 아니라 아예 인용을 안 한 것**이고, 0.20~0.30 구간은 13건뿐이다.
임계값을 올리는 것은 해법이 아니다.

**홉별 마커 생존율(표본 #5 카세트).** `final_compose` 출력 11건은 **11건 모두**
`[C:]` 마커를 달았다(100%). `node_summary.answer` 30건 중 마커를 단 것은 12건이고,
`key_claim_ids`가 비어있지 않은 것도 정확히 12건이다. **프롬프트 준수 문제가
아니라 증거 공급 문제**다. 마커 없는 요약은 "검증된 클레임과 자식 요약이 모두
비어 있어 …구성할 수 없다" 같은 부재 진술을 쓰고, 그 문장에 든 연도·고유명사가
`_DIGIT`/`_PROPER_NOUN`에 걸려 인용 없는 사실 주장으로 세어진다.

**드러난 하네스 결함 셋.**

- **W3-g (`45fbc2f4`) 번호 헤딩이 채점됐다.** `_sentences`가 `_HEADING_LINE`보다
  먼저 돌고 서수의 마침표에서 문장을 자른다. `### 2. 기준일(2026년 7월 19일)
  시점의 상태` → `['### 2.', '기준일(2026년 7월 19일) 시점의 상태']`. 뒷조각에는
  `#`이 없어 제외를 빠져나간다. W3-f가 통하는 것처럼 보인 이유는 당시 사례가
  `### 1. 배경`이라 남는 조각에 숫자도 라틴 대문자도 없었기 때문이다 — **우연히**
  분모에서 빠졌다. 카세트 재채점: 11건 중 1건이 반려→통과(0.208 → 0.116).
- **W3-h (`c72cb232`) 재시도가 맹목 재굴림이었다.** `assemble`이 매 시도 같은
  세 인자를 받았다. 세 시도는 교정이 아니라 같은 분포의 표본 셋이고, 실제로
  비율이 배회한다(`4098117c` .357→.500→.267). 이제 반려마다 힌트가 붙는다.
  `Verdict.revision_hints`는 프로세스 안에만 머문다 — 오케스트레이터는 `code`와
  `diagnostics`만 기록하므로 리포트 산문이 원장에 새지 않는다.
- **W3-i (`9344ef17`) 게이트가 작성자가 본 적 없는 문자열을 요구했다.** 조립
  블록은 `- [{question_id}] {answer}`였다. 질문 텍스트는 프롬프트에 한 번도
  들어간 적이 없는데, 게이트는 그것이 리포트에 축자로 있기를 요구한다. 발동
  시 실패율 100%(`6e65093e`, 인용 비율 0.063으로도 3/3 반려).

**부재 진술을 어떻게 다룰지 — 채점기가 아니라 프롬프트.** 선택지는 (a) 재시도
힌트로 한계 절에 보내기, (b) `_uncited_stats`에 부재 표현 패턴을 가르치기였다.
**(a)를 골랐다.** 한계 절은 `_report_body`가 이미 채점에서 빼고 있으므로 새
휴리스틱이 필요 없고, (b)는 특정 표현만 쓰면 인용을 회피할 수 있는 구멍을
모델에게 열어준다. final_compose v3가 같은 것을 상시로 지시한다.

**골든 관문 둘이 이 변경을 붙잡았고 둘 다 제 일을 했다.** 프롬프트 버전
매니페스트는 v1→v3 갱신을 강제했다. 골든 리플레이는 `global_token_cap=1000`이
경계에 정확히 붙어 있어, 프롬프트가 172자 늘자 런 전체가 열화 경로로 넘어갔다
(이분 측정: v1은 1000 통과, v2는 2500 실패 / 3000 통과). 4000으로 여유를 뒀다.
캡이 절벽 끝에 있으면 이 테스트는 조용히 "완전 해결" 대신 열화를 검사하게 된다.

**아직 열린 것.** (1) 효과는 **측정되지 않았다** — 표본 #6이 있어야 한다.
§10.2대로 이번 수정들은 그 표본 *전에* 확정돼야 하고, 실행 중에는 못 바꾼다.
(2) ~~`_best_rejected_draft` 순위 규칙은 비어 있다~~ → **W3-j 로 채웠다** (아래).
(3) 증거 공급 자체 — 검증 클레임 0인 노드가 많다는 사실은 조사 단계의 문제이지
리포트 단계의 문제가 아니다. 이번 수정 중 어느 것도 그것을 고치지 않는다.

---

## D39. W3-j 캡 소진 시 어떤 초안을 배달하는가 (2026-08-09)

**문제.** 재시도가 전부 반려되면 `_finalize` 는 **마지막** 초안을 내보냈다.
표본 #5 의 `94b0483c` 는 .140 과 .095 짜리 초안(둘 다 인용 기준 통과, 판정자가
반려)을 만들고 세 번째 .208 을 배달했다. 도착 순서 말고는 이유가 없다.
통과율은 바뀌지 않는다 — **실패한 run 이 사용자에게 무엇을 건네는지**가 바뀐다.

**정한 규칙.** 게이트 자신의 측정만 쓰는 3단 사전식:

1. `_GATE_DEPTH[verdict.code]` — 게이트를 얼마나 통과했는지. 유일하게
   **비교가 아닌 기록**인 항이다. `E_REPORT_AGENTIC` 은 결정론 검사 넷을 모두
   통과했다는 뜻이고 `E_REPORT_UNCITED` 는 두 번째에서 죽었다는 뜻이다.
2. `uncited_ratio` 오름차순 — **여기가 유일한 취향 판단이다.** 캡 소진
   리포트는 이미 "미해결" 표시를 달고 나가므로 그 문서에서 실질적 해를 끼치는
   것은 근거 없는 주장이다. 분량보다 안전을 택했다.
3. `uncited_assertions` 내림차순 — 같은 비율이면 알맹이 많은 쪽.

동점이면 **먼저 나온 초안**을 지킨다(`max` 의 first-wins). 뒤에 온 초안이 더
낫다는 증거가 있어야 자리를 빼앗는다.

**함정은 대체로 도달 불가능하다.** "주장 2개 중 0개 미인용이 40개 중 4개를
이긴다"는 우려는 성립하기 어렵다 — 비율 0.0 에 나머지 검사도 통과하는 초안은
**게이트를 통과해서 반환**되므로 `rejected` 에 들어오지 않는다. 여기 온 초안은
반드시 더 깊은 검사에서 죽었고, 그러면 1항이 먼저 거른다. 남는 좁은 경우는
짧고 완전히 인용된 초안과 길고 일부 미인용인 초안이 **같은 검사**에 걸린
때뿐이고, 그때 짧은 쪽이 이기는 것은 2항의 직접적 귀결이다.

**표본 #5 실패 5건 검산: 3건 개선, 2건 동일, 악화 0건.**

| run | 마지막 초안(구) | 이 규칙(신) |
|---|---|---|
| `94b0483c` | .208 / 48주장 / UNCITED | **.095 / 42 / AGENTIC** |
| `d8cda7c5` | .250 / 12 | **.235 / 17** |
| `6e65093e` | .133 / 15 | **.063 / 16** |
| `4098117c` | .267 / 15 | 동일 |
| `5df08a1a` | .462 / 13 | 동일 |

`diagnostics` 는 비어 있을 수 있어(고아 마커 분기는 채점을 건너뛴다) 모든
항을 **비관적 기본값**으로 읽는다. 낙관적 기본값이면 미채점 초안이 실측된
초안을 이긴다.

---

## D40. 표본 #6 — W3 가 인용 문제를 옮겼고, 판정자가 병목이 됐다 (2026-08-09)

트리 `190fa41a`, 사전 게이트 2464 passed / 16 skipped(실패 0), 아티팩트
`20260808T174238Z`. §10.2대로 한 번만 실행했고 실행 중 아무것도 바꾸지 않았다.

**맞은 것.** W3-g 는 예측대로 작동했다 — 인용없음 비율 중앙값 0.222 → 0.105,
임계값 아래가 39% → 80%. `E_REPORT_UNCITED` 는 61% → 17% 로 내려갔다.
게이트 통과 시도는 1/18 → 2/18.

**틀린 것 둘. 기록해 둔다 — 결과를 보고 이야기를 맞추지 않기 위해 기대는
실행 전에 적어뒀다.**

- **W3-h 는 단조 개선을 만들지 못했다.** "마지막 시도가 첫 시도보다 개선된
  run" 은 3/6 → **1/5** 로 오히려 줄었다. 표본 #6 에서는 첫 시도가 최선인
  경우가 흔하다(`741e94cf` .048 → .000 → .211). 반려 다수가 이제
  `E_REPORT_AGENTIC` 이고 그 힌트는 판정자의 산문 사유라, 잘 인용된 초안에서
  멀어지는 방향으로 밀었을 수 있다 -- **단일 표본이므로 인과는 주장하지
  않는다.** W3-j 가 최선 초안을 배달하므로 손해의 일부는 흡수된다.
- **W3-i 는 `E_REPORT_MISSING_QUESTION` 을 없애지 못했다** (3 → 2).
  `3106e72e` 는 비율 0.000 / 0.050 짜리 초안으로도 축자 재현에서 막혔다.
  질문 텍스트를 공급하는 것만으로는 부족하다.

**병목이 옮겨갔다.** 지배적 반려가 인용(11/18)에서 **에이전틱 판정자**
(8/18, 44%)로 바뀌었다. `741e94cf` 시도 1 은 주장 42개에 인용없음 0개,
verified 클레임 35개였고 판정자가 반려했다. 그리고 **통과 2건은 모두
`judge=budget_exhausted`** -- 판정자가 완주하지 못한 폴백 통과다(표본 #5 의
유일한 통과도 같았다). 게이트 통과 여부가 판정자의 잔여 예산에 좌우된다.

**즉시 고친 것.** `E_ORPHAN_CITE` 3건이 원장 역사상 처음 나타났고 전부 한
run(`36903adc`)이다. 카세트 재생 결과 그 run 의 초안들은 자기 run 의 verified
클레임만 인용했다(출력 29건 중 고아 마커 0건) -- 합성기 잘못이 아닌데 원인을
특정할 수 없었다. 이벤트가 `code` 만 적고 `OrphanCitationError.claim_id` 를
버렸기 때문이다. `orphan_claim_id` 를 기록하도록 고쳤다. D28 과 같은 공백이다.

**다음 과제.** 판정자가 지배적 실패 사유가 됐는데 **원장에 사유가 없다** --
`grade_agentic` 의 rationale 은 `detail` 에 담기고 오케스트레이터는 `code` 와
`diagnostics` 만 기록한다. 판정자 예산 고갈도 같은 무게로 봐야 한다: 통과가
"판정자가 승인했다" 가 아니라 "판정자가 못 돌았다" 를 뜻하는 한, S2 의 의미는
계속 약하다.

---

## D41. 판정자가 왜 반려했는지를 원장에 남긴다 (2026-08-09)

**왜 지금.** 표본 #6 에서 에이전틱 판정자가 지배적 반려 사유가 됐다
(18회 중 8회, 직전 표본 3회). 그런데 그 8건은 서로 구분되지 않는다 --
`grade_agentic` 의 rationale 은 `Verdict.detail` 에 담기고 오케스트레이터는
`code` 와 `diagnostics` 만 기록한다. D28 이 정지 사유에 대해 고친 것과 같은
공백이 이제 게이트의 지배적 실패 사유 위에 얹혀 있었다.

**무엇을 남기는가.** 산문보다 **두 불리언이 먼저다.**

- `judge_answers_question` · `judge_strength_ok` — "질문에 답하지 않았다" 와
  "근거가 약하다" 는 고치는 방법이 다른 별개의 실패다. 구조적이라 run 을
  가로질러 집계되지만, rationale 문자열은 그럴 수 없다.
- `judge_rationale` — 한 건을 읽기 위한 것. 400자로 자른다.
- `judge: "ran"` — **승인에도 붙인다.** 이것이 이번 변경의 핵심이다.

**승인 표식이 왜 핵심인가.** 승인이 아무 표식도 남기지 않으면 원장에서
"판정자가 돌아서 승인했다" 와 "판정자가 아예 못 돌았다" 가 **바이트 단위로
같다**. `graders/report.py` 의 기존 주석이 이미 그 점을 지적하면서도 강등
쪽에만 표식을 달았다. 표본 #5·#6 의 게이트 통과 3건이 **전부**
`judge=budget_exhausted` 였으므로, 이 구분이 살아남지 않으면 S2 를 제대로
읽을 수 없다 -- 통과가 "리포트가 좋다" 인지 "판정자가 예산을 못 받았다" 인지
가릴 수 없다.

**모델 산문을 페이로드에 넣는 것에 대해.** 이 채점기의 no-raw 불변식은
**가져온 원문(blob)** 에 대한 것이다. rationale 은 판정자가 렌더된 리포트에
대해 스스로 내린 평가이지 수집된 원문이 아니므로 불변식과 무관하다. 그래도
상한을 둔다(`_MAX_RATIONALE_CHARS = 400`). 프로세스 안에서 쓰는 `detail` 과
재시도 힌트는 자르지 않는다 -- 재시도는 전부 봐야 한다.

**드러난 것.** 이 변경으로 깨진 테스트가 하나도 없었다. 판정자 진단을
확인하는 테스트가 **애초에 없었다**는 뜻이고, 그래서 세 개를 새로 붙였다.

---

## D42. 판정자 몫을 조립이 못 건드리게 한다 — 세 번째 티어 (2026-08-09)

**원인.** `report_grading` 은 이미 가장 안쪽 티어(`remaining_tokens`)라 굶을
이유가 없어 보였다. 실제 원인은 **리포트 층 안에 하위 배분이 없다**는 것이다.
`report_assembly` 와 `report_grading` 이 같은 `remaining_tokens` 를 공유하고,
`_finalize` 는 매 시도 조립을 먼저 부른다 -- `call_text` 의 확장 재시도까지
치면 시도당 2회다. 마지막 시도에서 층이 마르고, 판정자가 예약에 실패하면
`ReportGrader.grade` 가 그것을 **통과**로 바꾼다.

**그래서 게이트는 실제로 배달되는 초안에서 가장 관대해진다.** 원장의 게이트
통과 3건이 전부 같은 모양이다 -- 판정자가 시도 0·1 을 반려하며 예산을 태우고
시도 2 에서 굶는다. 우연이 아니라 구조다.

**표본 #6 실측.** 조사 단계가 캡의 92~97% 를 쓰고(`floor_tokens` 는 지켜졌다 --
조사는 층에서 멈췄다), 남은 최종화 예산을 축약과 조립이 거의 다 먹는다.

| run | 남은 예산 | 판정자 프롬프트 | 여지 |
|---|---|---|---|
| `953ee89e` | 3,555 | 8,529 | **-4,974** |
| `c716f31c` | 7,822 | 8,329 | **-507** |
| `741e94cf` | 9,443 | 16,345 | **-6,902** |

**고친 것.** `GRADING_STAGES` 를 가장 안쪽 티어로 두고, `report_assembly` 의
천장을 `remaining_tokens - grading_floor_tokens` 로 낮춘다. 층은 이제 셋이
중첩한다 -- 조사 ⊃ 리포트 ⊃ 채점 (생성자가 중첩을 강제한다).

`grading_floor_tokens` 는 **한 번의 판정**만 감당하게 잡았다. 재시도 루프의
앞선 채점들은 위 티어에서 돌면 되고, 이 층이 보장하는 것은 **마지막 초안이
반드시 판정받는 것**이다. `truncation_retry_multiplier` 가 식에 들어간 이유는
판정 한 번이 실제로는 최대 두 번이기 때문이다(`call_json` 의 절단 재시도,
원장에 800 → 1600 예약으로 남는다). 그 재시도를 무시한 층은 첫 호출만
대주고 두 번째를 못 대준다.

검산: dev 13,600 / prod 41,600 이고, 표본 #6 에서 굶었던 판정자 3건이 전부
예약 가능해진다(남는 출력 5,071 · 5,271 · 25,255, `min_viable` 2,048 초과).
총 층 비율은 41.0% / 43.7% 로 `finalization_floor_warn_ratio`(0.5) 아래를
유지한다.

**대가는 실재하고 의도한 것이다.** dev 기준 최종화 층 41,040 중 13,600 을
떼면 축약+조립 몫이 27,440 이고, 표본 #6 실측(33,000~37,000) 대비 20~25%
압축된다. **조립이 더 자주 열화한다.** 판정받은 짧은 리포트가 판정 못 받은
긴 리포트보다 낫다는 판단이다.

**고치지 않고 기록만 한 것.** `report_floor_tokens` 의 `assembly` 항은
`input_bound ≈ ratio × synthesis_max_tokens` 를 가정하는데, 표본 #6 의 조립
예약 합계는 run 당 34,984~134,983 으로 층 전체(dev 34,800)를 넘는다.
`grading_floor_tokens` 처럼 보정하면 층이 경고 임계값을 넘어서고, 그것은
식의 문제가 아니라 **캡과 재시도 정책에 대한 결정**이므로 `schema.py` 주석에
남기고 여기서 멈춘다.

---

## D43. 표본 #7 — D42 는 작동했고, 병목은 리포트 층 밖으로 나갔다 (2026-08-09)

트리 `d0bc9e02`, 사전 게이트 2472 passed / 실패 0, 아티팩트 `20260808T192230Z`.
§10.2대로 한 번만 실행했다. 기대는 실행 전에 고정했다(매니페스트 영수증).

**D42 확인.** `judge=budget_exhausted` 1 → 2 → **0**, `judge=ran` **8건**.
판정자가 도달한 모든 경우에 실제로 돌았다.

**판정자가 승인한 첫 리포트.** `9e5492eb` 시도 0 — `ok=True, judge=ran`,
주장 38개, 인용없음 0.184, verified 26개. 그 전의 통과 3건은 전부 폴백이었다.

**통과 수 2 → 1 은 예측한 결과다.** 폴백 통과가 사라지고 진짜 통과가 하나
들어왔다. 후퇴가 아니라 측정 도구가 정직해진 것이다.

**청구서도 예측대로.** 조립 열화 1 → **6건**, 인용없음 중앙값 0.105 → 0.183.
열화된 조립의 초안은 0.455~0.615 로 확연히 나쁘다. 다만 **손상은 재시도 쪽에
몰린다** — 시도 0 은 .125 · .182 · .188 · .184 로 고르고, W3-j 가 최선 초안을
배달하므로 열화된 후속 초안은 대체로 사용자에게 가지 않는다. D42 를 되돌릴
근거로는 부족하다고 본다.

**D41 이 처음으로 말해준 것.** 판정자 반려 분해: `strength_ok=False` 7건 ·
`answers_question=False` 4건. rationale 이 한 방향을 가리킨다 -- 리포트가
질문이 요구한 **1차 기관 출처를 확보하지 못하고 2차 블로그성 출처에 의존**한다.
리포트 층의 문제가 아니라 **조사·증거 수집 단계**(워커, 검색, `source_tiers`)의
문제다. 다음 과제가 어디인지를 이 표본이 정했다.

**정정: `E_ORPHAN_CITE` 진단은 틀린 분기를 고쳤다.** D40 에서 이 실패를
`CitationRenderer` 가 클레임을 못 찾은 것으로 진단하고 `orphan_claim_id` 를
기록하게 했는데, 표본 #7 의 4건 모두 그 키가 없다. 실제 경로는
`grade_deterministic` 의 검사 (a) -- **렌더 후에도 raw `[C:...]` 가 남은
리포트**다.

원인은 W3-e 다. `_ensure_limits_section` 이 `caveats` 를 **렌더 이후에**
덧붙이는데, `node_summary` 프롬프트가 "모든 사실 주장에 마커를 붙이라" 고
하므로 모델이 `caveats` 에도 마커를 넣는다(표본 #7 카세트: node_summary 응답
30건 중 3건). 렌더러가 본 적 없는 텍스트라 마커가 살아남고, 게이트가 리포트
전체를 반려한다. D40 에 넣은 `orphan_claim_id` 는 해로울 것은 없으나 지금까지
관측된 어떤 실패도 설명하지 못한다.

**아직 검증되지 않은 것.** W3-i(`E_REPORT_MISSING_QUESTION`)가 0건인 것은
고쳐져서가 아니라 resolved 자식을 가진 run 이 6개 중 1개뿐이고 그 run 이
통과했기 때문이다. 세 표본 연속으로 이 검사는 사실상 공회전했다.

---

## D44. W3-k 한계 절을 렌더 전에 합친다 (2026-08-09)

**원인 (D43 의 정정에서 이어짐).** `E_ORPHAN_CITE` 는 `CitationRenderer` 가
클레임을 못 찾은 것이 아니라 **렌더 후에도 raw `[C:...]` 가 남은 리포트**였다
(`grade_deterministic` 의 검사 a). W3-e 가 `_ensure_limits_section` 을 렌더
**이후에** 부르는데, `node_summary.md` 가 "모든 사실 주장에 마커를 붙이라" 고
지시하므로 모델이 `caveats` 에도 넣는다 -- 표본 #7 의 node_summary 응답 30건
중 3건이 그랬다. 렌더러가 본 적 없는 텍스트라 마커가 최종 리포트까지 가고,
게이트가 리포트 전체를 반려한다. 표본 #6·#7 에서 6개 run 중 2개씩을 날렸다.

**관측된 모양까지 설명된다.** `03dd8ddd` 와 `ba84c409` 는 시도 0·1 에서
고아가 나고 시도 2 에서는 나지 않았다. 조립이 열화하면 템플릿이 한계 절
제목을 스스로 포함하고, `_ensure_limits_section` 이 건너뛰므로 덧붙일 마커가
없다. 결함은 **하네스가 실제로 절을 붙일 때만** 발동했다.

**고친 것.** 한계 절을 초안에 먼저 합치고 그 다음 렌더한다. 같은 패스가
본문과 한계 절의 마커를 함께 해결한다. caveat 의 마커는 지워지는 것이 아니라
각주 번호가 되므로 문장이 읽히는 채로 남는다 -- 지우면
"[C:34dac393]/[C:5be69e26]의 성능 비교는…" 이 "의 성능 비교는…" 이 된다.

**안전한가.** caveat 이 참조하는 클레임은 렌더 가능해야 한다. 표본 #6·#7 의
caveat 참조 클레임 **12개 전부 `verified`** 였다. 아닌 것이 나오면 여기서
raise 되는데, 그것이 해결 불가능한 마커를 배달하는 것보다 옳은 답이다.

**부수 효과: 절 순서가 바뀐다.** 이제 본문 → 한계 → 출처 다(전에는 본문 →
출처 → 한계). 각주 목록이 마지막에 오는 편이 낫고, `_report_body` 는 W3-f
때부터 `min(cuts)` 로 두 절 중 먼저 오는 것을 자르므로 채점은 영향이 없다 --
"모델이 내보내는 순서가 점수를 바꾸지 않는다" 는 그 주석이 여기서 값을 했다.

**D40 의 `orphan_claim_id` 는 남겨둔다.** 지금까지 관측된 실패를 하나도
설명하지 못하지만, 진짜 렌더러 고아가 났을 때 그것을 말해줄 유일한 기록이다.

---

## D45. 1차 기관 출처를 실제로 수집한다 (2026-08-09)

**왜.** D41 이 판정자 반려를 분해하자 지배적 사유가 `strength_ok=False`
7건이었고, rationale 이 한 방향을 가리켰다 -- "질문이 요구한 '공식 EU 출처' 를
전혀 사용하지 못하고 모두 2차 블로그성 출처(kla.digital, medialaws.eu 등)에
의존". 리포트를 못 쓴 것이 아니라 **근거를 못 구한 것**이다.

**측정.** 표본 #7 의 증거 URL 119건(고유 36) 중 tier1 은 **19건(16%)**.
상위 호스트에 `bbc.com`(15), `dev.to`(5), `joongang.co.kr`(5),
`tistory.com`(4), `kla.digital`(3) 이 있다.

**결함 둘.**

1. **`source_tiers` 가 수집에 아무 영향이 없었다.** 충돌 해소에서만 쓰인다 --
   *어떤 클레임이 이기는지* 는 정했지만 *무엇을 수집할지* 는 정하지 못했다.
   워커는 검색 엔진이 준 상위 `search_result_limit` 개를 **순서대로 전부**
   fetch 했다. 순위 재조정도, 티어 선호도, 필터도 없다.
2. **tier1 목록이 미국 중심이었다.** `arxiv.org`/`.gov`/`.edu`/`github.com`
   뿐이라 `eur-lex.europa.eu`, `who.int`, `birmingham.ac.uk`, `gov.uk` 가
   전부 tier2 -- `dev.to` 와 같은 등급이었다. 위 측정에서 `.ac.uk`/`.gov.uk`
   출처는 tier1 로 세지도 않은 채였다.

**고친 것.**

- tier1 을 초국가 기관(`europa.eu`, `.int`)과 영국·한국·일본·호주·캐나다·
  뉴질랜드의 정부·학술 접미사로 넓혔다. 편입 기준을 주석에 못박았다 --
  **"이 도메인의 문서가 그 사실의 원본인가"이지 "신뢰할 만한가"가 아니다.**
  언론과 기업 블로그는 신뢰할 만해도 2차이므로 들어오지 않는다.
- 워커가 `search_result_limit × source_candidate_multiplier`(3) 개를 후보로
  받아 tier 순으로 고른 뒤 앞의 `search_result_limit` 개만 fetch 한다.
  **fetch 수는 그대로**이므로 늘어나는 비용은 검색 결과 몇 줄뿐이다.

**tier 는 검색 순위를 대체하지 않는다.** `sorted` 가 안정 정렬이므로 같은
tier 안에서는 엔진의 관련도 순서가 그대로 남고, tier1 후보가 하나도 없으면
아무것도 바뀌지 않는다. 관련도를 버리고 기관 도메인을 무조건 올리는 것이
아니라, **1차 출처가 후보에 있을 때 그것을 앞세우는 것**이다.

**아직 재지 않았다.** 효과는 표본 #8 에서 본다. 기대: tier1 비율이 16% 에서
오르고, 판정자의 `strength_ok=False` 가 줄어든다. 오르지 않으면 문제는 검색
쿼리 쪽(1차 출처가 후보에 아예 안 들어온다)이고, 그때는 쿼리 증강이 다음
수순이다 -- 이 수정은 **후보에 있는 것을 고르는** 데까지만 손댔다.

---

## D46. 표본 #8 — D44·D45 확인, 그리고 커버리지 검사가 지배 사유가 됐다 (2026-08-09)

트리 `134200d4`, 사전 게이트 2477 passed / 실패 0, 아티팩트 `20260809T064216Z`.
§10.2대로 한 번만 실행했고 기대는 실행 전에 고정했다.

**수치 정정.** D45 를 만들 때 인용한 "표본 #7 tier1 16%" 는 **옛 목록**으로 잰
값이다. 목록을 넓혀 분류기가 바뀌었으므로 같은 분류기로 다시 재면 #7 은 24%,
#6 은 29% 다. 아래는 전부 새 분류기 기준이다.

**확인된 것 둘.**

- **D44**: `E_ORPHAN_CITE` 4 → **0**. 원인이 확정돼 있었고 예측대로 사라졌다.
- **D45**: 증거 tier1 24% → **57%**, 인용없음 중앙값 0.183 → **0.067(사상 최저)**.

**그런데 통과가 1 → 0 이다.** 새 지배 사유는 `E_REPORT_MISSING_QUESTION` 5건.
`da8e7ba6` 는 주장 27~30개에 인용없음 0~2개인 리포트를 3/3 이 검사로 잃었다.

**왜 지금 터졌는지가 중요하다.** resolved 자식 질문이 #7 은 6 run 에 1개,
#8 은 4개다. **D45 가 상류를 고쳐 질문이 더 많이 해결되고, 해결될 때만
발동하는 고장난 검사가 그만큼 자주 발동한다.** 앞의 결함을 고쳐야 다음
결함이 보이는, 이 프로젝트의 반복된 모양이다.

**W3-i 는 절반만 통했고 그 절반이 어디인지 측정됐다.** 합성기는 질문을
`### N. <질문>` 제목으로 실제로 옮겨 적는다(유사도 0.98, 20건 중 2건 전문
일치). 그러나 하위 질문은 *의문문 + 출처 지시문*이고 합성기는 **의문문만
옮기고 지시문 꼬리를 버린다.** 게이트는 지시문까지 축자로 요구한다.

의문문까지만 대조하는 안은 3건 중 1건만 푼다(`da8e7ba6` 213자 질문 0 → 2).
`9d17b1e6` 은 의문문(44자)조차 20건 어디에도 없어 **설명되지 않은 채로 남는다.**
클램프 가설은 반증됐다 -- #8 최종화 클램프 39건 < #7 42건, `dropped_primary` 0.

**축자 대조를 그만둬야 한다.** 검사의 목적은 "조사가 끝난 갈래를 리포트가
조용히 빠뜨리지 않는 것" 이지 "지시문을 옮겨 적는 것" 이 아니다. 다음 후보:
(a) 의문문 부분만 대조 -- 측정상 1/3 만 풀리므로 단독으로는 부족,
(b) 하네스가 커버리지를 소유 -- `## 출처`·한계 절처럼 resolved 질문마다
절을 하네스가 보장, (c) 검사 폐기. §6.8 의 정신은 (b) 쪽이다.

**새 하드 실패.** `8817a935` 는 `job_failed(deep-analysis token budget
exhausted)`, status `failed`, 리포트 없음. 원장 job_failed 15건 중 예산
고갈로 죽은 **첫 사례**다(나머지는 JSON 파싱·API·DB). §6.8 "빈손 종료 금지"
위반이다. D42 가 조립 몫을 줄인 것과 관련됐을 수 있으나 단일 관측이므로
인과는 주장하지 않는다.

---

## D47. W3-l 하네스가 질문 커버리지를 소유한다 + §6.8 위반 수정 (2026-08-09)

**W3-l — 축자 대조를 그만둔다.** 게이트는 resolved 자식 질문이 리포트에
글자 그대로 있기를 요구한다. W3-i 로 질문 텍스트를 조립 프롬프트에 넣었고
합성기는 실제로 `### N. <질문>` 제목으로 **옮겨 적는다**(표본 #8 실측 유사도
0.98, 20건 중 2건 전문 일치). 그런데 하위 질문은 *의문문 + 출처 지시문*
("…원문에서 …을 확인하라") 128~213자이고, 합성기는 **의문문만 옮기고 지시문
꼬리를 버린다.** 게이트는 지시문까지 요구한다.

표본 #8 에서 이 검사가 15회 채점 중 5회로 **지배 사유**가 됐고, `da8e7ba6` 는
주장 27~30개에 인용없음 0~2개인 리포트를 3/3 이 검사로 잃었다.

**값싼 대안은 측정이 기각했다.** 의문문 부분만 대조하는 안은 실패한 질문
3개 중 1개만 푼다(`da8e7ba6` 213자 질문 0 → 2). `9d17b1e6` 은 의문문(44자)
조차 20건 어디에도 없다.

**그래서 하네스가 소유한다** -- `## 출처`(CitationRenderer)와 한계 절(W3-e)이
이미 같은 판단을 받은 자리다. `_ensure_question_coverage` 가
`## 조사한 하위 질문` 절에 resolved 질문을 그대로 나열한다.

설계 선택 둘:

- **질문만 넣고 답은 넣지 않는다.** 본문이 이미 답을 담고 있으므로 중복은
  리포트와 인용없음 수를 부풀린다. 덕분에 이 절은 한계 절과 **같은 종류의
  텍스트** -- 사실 주장이 아니라 목록 -- 가 되고, 그래서 `graders/report.py`
  가 둘 다 인용 채점에서 뺀다. 질문에는 연도와 기관명이 들어가므로 빼지
  않으면 `_DIGIT`/`_PROPER_NOUN` 에 그대로 걸린다.
- **렌더 전에 붙인다.** D44 가 산 교훈이다 -- 하네스가 렌더 *후에* 붙이는
  것은 무엇이든 마커를 raw 로 실어 나른다.

`E_REPORT_MISSING_QUESTION` 은 남겨둔다. `E_REPORT_NO_LIMITS` 와 같은 위치가
된다 -- 하네스가 보장하므로 도달 불가능하지만, 보장이 깨지면 말해주는 방어선.

**§6.8 위반 수정.** `_finalize` 의 충돌 재조사 라운드는 `_run_round()` 로
**진짜 워커를 돌린다.** 본 조사 루프(`run`)는 `TokenBudgetExhausted` 를 정확히
이 이유로 잡는데 여기서는 아무도 잡지 않았고, 예외가 `_finalize` 를 빠져나가
`run` 의 일반 핸들러로 가면 run 이 실패한다. 표본 #8 의 `8817a935` 가
`job_failed(deep-analysis token budget exhausted)` 로 죽었고 **리포트가 없다** --
원장 job_failed 15건 중 예산 고갈은 이것이 처음이다.

재조사는 **선택적 추가 라운드**다. 굶으면 정지 사유를 기록하고 가진 요약으로
진행한다. 빈손 종료 금지는 배달물이 나빠도 지켜야 하는 계약이다.

---

## D48. 표본 #9 — W3-l·§6.8 확인, 그리고 품질 지표를 배달 기준으로 바꾼다 (2026-08-09)

트리 `0be4302a`, 사전 게이트 2480 passed / 실패 0, 아티팩트 `20260809T084208Z`.

**확인된 것 넷.**

- **W3-l**: `E_REPORT_MISSING_QUESTION` 5 → **0**. 하네스가 절을 보장하므로
  구조적으로 도달 불가능해졌다.
- **§6.8**: `job_failed` 0, **6개 run 전부 배달**(#8 은 5개였다).
- **게이트가 판정자 층 복귀**: `judge=ran` 1 → 5. #8 에서는 결정론 검사가
  먼저 막아 판정자에게 닿지도 못했다.
- **D45 는 표본 변동이 아니었다**: tier1 57% → **68%**.

**실행 전에 건 반증 조건이 걸렸다.** "인용없음 중앙값이 오르면 커버리지 절
제외가 작동하지 않은 것" 이라고 적어뒀고, 채점 이벤트 중앙값이
0.067 → 0.302 로 올랐다.

**제외는 정상이었다.** 커버리지 절을 가진 유일한 리포트 `42c838ac` 에서 절
위치 2393, 채점 본문 컷 1500 -- 절은 빠진다. 단위 테스트도 이를 지킨다.

**틀린 것은 지표다.** 채점 이벤트 집계는 **사용자에게 가지 않는 초안까지**
센다. 시도 0 은 .118 · .000 · .118 · .300 · .158 · .143 으로 고르고, 조립이
열화한 뒤의 시도 1·2 가 .222~.650 이며 (시도 1·2 의 비율·주장 수가 완전히
동일하다 -- 결정론 템플릿이 그대로 반복된다) 그것들이 중앙값을 끌어올렸다.
W3-j 가 최선 초안을 배달하므로 그 초안들은 배달되지 않는다.

**앞으로 리포트 품질은 배달된 리포트로 읽는다.**

| 표본 | 배달 | 인용없음 중앙값 | 최악값 |
|---|---|---|---|
| #7 | 6 | 0.122 | 0.455 |
| #8 | 5 | 0.000 | 1.0 |
| #9 | 6 | 0.130 | **0.30** |

#9 가 분포가 가장 촘촘하고 최악값이 가장 좋다. 채점 이벤트 집계는 **게이트가
무엇을 막았는지**를 말하지 **사용자가 무엇을 받았는지**를 말하지 않는다 --
두 질문을 한 숫자로 답하려 한 것이 실수였다.

**남은 병목.** 시도 0 이 판정자에게 반려되고(`E_REPORT_AGENTIC` 4건), 그 뒤
조립이 예산 부족으로 열화해 재시도가 교정할 수 없다. D42 의 trade-off 가
여기서 다시 보인다 -- 판정자는 항상 돌지만, 그 대가로 재시도가 쓸 조립
예산이 없다. 다음 표본은 이 지점을 겨냥해야 한다.

---

## D49. 한계 절이 원장에게 말하고 있었다 (2026-08-09)

**어떻게 발견했나.** 표본 #9 의 판정자 반려 사유를 읽었다(D41 이 없었으면
읽을 것도 없었다). 표본 #7 의 지배적 불만은 "공식 EU 출처를 전혀 사용하지
못하고 2차 블로그성 출처에 의존" 이었는데 -- D45 가 겨냥한 그것이다 -- #9 에서
불만이 옮겨갔다:

> "다수의 '미확인'·**'input_bound'** 항목이 남아 실질적 종합이 이루어지지
> 않았다" (`d2f93313`)

**`input_bound` 는 내부 강등 사유 문자열이다.** `node_reduction_degraded` 의
`reason` 이 `NodeSummary.caveats` 를 타고 `_collect_caveats` 를 지나 리포트의
한계 절까지 그대로 흘렀다. 표본 #9 의 **배달된** 리포트에서 `- input_bound`
라는 줄이 **51회** 찍혔고, 한 run 은 33줄짜리 한계 절 중 17줄이 그것이었다.

**두 가지가 동시에 잘못됐다.**

1. 독자에게 기계 토큰을 보여준다. 읽는 사람에게 아무 뜻이 없고, 판정자는
   그것을 리포트가 미완성이라는 증거로 읽는다.
2. **같은 줄이 반복된다.** 강등은 노드마다 일어나므로 한 run 에서 같은 사유가
   17~19회 쌓인다.

**고친 것.** `_collect_caveats` 가 경계다 -- 원장 어휘가 리포트 내용이 되는
지점. 거기서 사유를 문장으로 옮기고 중복을 접는다. 표본 #9 재계산:
33 → 17줄, 38 → 20줄, 35 → 26줄.

**원장 쪽 문자열은 건드리지 않는다.** D28 이 정지 사유를 기계가 읽을 수 있게
만들려고 싸운 자리이고, 경계 전후 집계도 그 어휘에 걸려 있다. 바꾸는 것은
**독자에게 보여줄 때뿐**이다 -- 같은 사실에 두 개의 표현이 필요하고, 그 둘이
서로 다른 독자를 향한다.

**남은 판정자 불만 둘(아직 미해결).**

- **"본문이 중간에 끊겼다"** -- #9 반려 4건 중 3건이 지적한다. 조립 출력
  상한 문제이고, D42 가 조립 몫을 줄인 것과 관련이 있다.
- **증거 자체의 부족** -- `e3ea0c0f` 는 "요구된 동료심사 준실험 연구를 전혀
  확보하지 못한 채 결론을 보류" 로 반려됐다. D45 는 후보에서 고르는 데까지만
  손댔고, 애초에 후보에 없는 것은 여전히 못 구한다.

---

## D50. 본문 절단 — 죽은 재시도를 접어 조립 상한을 산다 (2026-08-09)

**증상.** 표본 #9 의 판정자 반려 4건 중 **3건**이 "본문이 중간에 끊겼다" 를
사유에 포함했다.

**측정 셋.**

1. **재시도는 죽어 있었다.** `report_assembly` 예약이 run 당 `[1200, 2400]`
   뿐이다 -- 시도 0 의 최초 호출과 그 확장 재시도다. **시도 1·2 는 LLM 호출을
   한 번도 받지 못했고** 결정론 템플릿을 냈다. 그래서 두 시도의 인용 비율과
   주장 수가 run 마다 서로 완전히 동일했다.
2. **절단은 예산이 아니라 상한 때문이다.** 시도 0 의 1200 과 2400 은 **전액
   승인**됐다. `llm_truncated` 17건 중 13건이 `report_assembly` 다. 묶고 있는
   것은 `synthesis_max_tokens` 자체다.
3. **본문은 상한에 정확히 붙어 있다.** 배달된 리포트의 본문(하네스 소유 절
   제외)은 1,309~1,932자에 몰려 있고, 이는 1200토큰이 낼 수 있는 양이다.

**고친 것 — 셋이 한 방향이다.**

- `report_retry_cap` **2 → 1**. 죽은 시도를 없앤다. 이것이 값을 치른다:
  층은 `(cap + 1) × (assembly + grading)` 이므로 시도 하나를 접으면 상한을
  살 수 있다.
- dev `synthesis_max_tokens` **1200 → 2000**. 확장 재시도로 4000 까지 가므로
  1,932자 중앙값 본문을 여유 있게 담는다.
- `final_compose` **v4**: `## 출처` 를 모델의 필수 섹션에서 뺐다.
  CitationRenderer 가 항상 붙이고 모델은 URL 을 모른다 -- 모델이 쓴 출처
  절은 claim id 나열이었다(표본 #9 카세트 666자).

**층 검산.** dev 41,040 → **48,000 (48%)** 로 `finalization_floor_warn_ratio`
(0.5) 아래를 유지한다. prod 는 131,200 → **94,400 (44% → 31%)** 로 오히려
여유가 늘었다 -- 재시도를 접은 몫이 prod 에서 더 크기 때문이다.

**정직한 크기.** 프롬프트 v4 가 되찾는 출력은 전체의 2.4% 뿐이다(끝까지 간
출력에서는 30~34% 지만 대부분 그 절에 닿기 전에 잘렸다). 절단을 실제로 푸는
것은 상한이고, v4 는 리포트에서 의미 없는 claim id 덤프를 없애는 품질 정리다.

**테스트를 설정에서 읽게 바꿨다.** `assemble_calls == 3` 처럼 캡을 하드코딩한
단언이 여럿이었다. `_ATTEMPTS = report_retry_cap + 1` 로 읽게 했고, 층을
하드코딩하던 config 테스트도 `finalization_floor_tokens()` 를 부르게 했다 --
설정을 조정할 때마다 테스트가 조용히 낡던 자리다.

**아직 재지 않았다.** 효과는 표본 #10 에서 본다. 기대: `llm_truncated` 의
`report_assembly` 비중이 내려가고, 판정자 반려 사유에서 "끊겼다" 가 줄어든다.
줄지 않으면 상한이 아니라 프롬프트가 요구하는 분량이 문제라는 뜻이다.

---

## D51. 표본 #10 — 재시도가 살아나고 통과가 3건 (2026-08-09)

> **⚠️ 아래 굵은 두 결론은 틀렸다. D53(표본 #11)이 정정한다.** 시도 1 은 LLM
> 조립을 받은 적이 없다 -- `917bc008` 을 포함해 6개 run 중 5개의 시도 1 이
> `report_assembly_degraded(input_bound)` 로 강등된 결정론 템플릿이었다. 그
> 이벤트는 바로 이 구별을 위해 존재하는데 나는 그것을 읽지 않고 "시도 0 과
> 숫자가 다르다" 만으로 "재시도가 예산을 받는다" 를 추론했다. 다른 숫자가
> 나온 이유는 LLM 이 아니라 템플릿이 a0 의 산문과 다른 텍스트이기 때문이다.
> 아래 표와 나머지 관측(본문 길이, `input_bound` 누출, §6.8 유지)은 유효하다.

트리 `6150ab34`, 사전 게이트 2482 passed / 실패 0, 아티팩트 `20260809T110052Z`.

**가장 진단적이었던 기대가 확인됐다.** 실행 전에 "시도 1 이 시도 0 과 **다른**
비율·주장 수를 내야 한다" 고 적어뒀다. 표본 #9 에서는 시도 1·2 가 서로 완전히
동일했다 -- LLM 호출을 못 받아 결정론 템플릿을 냈기 때문이고, 그것이 D50 의
근거였다. #10 에서는 6개 run 전부 시도 1 이 다른 숫자를 낸다. **재시도가
예산을 받는다.**

**재시도가 처음으로 교정에 성공했다.** `917bc008` 시도 0 은
`E_REPORT_UNCITED` 0.263, 시도 1 은 **0.000 / 주장 36개로 판정자 승인**.
재시도 루프 도입 이래 재시도가 통과를 만든 첫 사례다.

| | #8 | #9 | #10 |
|---|---|---|---|
| 게이트 통과 | 0 | 1 | **3** |
| 그중 판정자 승인 | – | 1 | **2** |
| 배달 본문 중앙값 | 2,575 | 1,678 | **3,386자** |
| `- input_bound` 줄 | 29 | 51 | **0** |

**확인된 것.** D50-3(본문 두 배), D50-2(판정자의 "끊겼다" 지적 소멸),
D49(`input_bound` 누출 0), 그리고 §6.8 유지(6/6 배달).

**부분 확인.** `report_assembly` 절단은 13 → 10건으로 줄었으나 여전히 절단의
71% 다. 상한이 올라간 만큼 더 긴 본문에서 잘린다 -- 판정자가 더는 지적하지
않으므로 실무적으로 해소됐지만 없어진 것은 아니다.

**정직하게 적을 것 둘.**

- **재시도는 길지만 나쁘게 쓴다.** 시도 1 의 주장 수가 크게 늘고(19→60,
  31→46, 16→42) 인용 비율은 나빠진다(.400 · .435 · .714). W3-j 가 최선 초안을
  배달하므로 사용자에게는 가지 않는다. 다만 재시도 힌트(`_uncited_hints`)가
  "더 쓰라" 는 방향으로 읽히고 있을 가능성이 있고, 이는 다음 표본의 관찰
  대상이다.
- **`judge=budget_exhausted` 가 1건 돌아왔다**(`92701929` 시도 1). 조립 상한을
  키운 만큼 D42 의 채점 층이 빠듯해졌다. 통과 3건 중 1건이 이 폴백이므로
  **판정자 승인 통과는 2건**으로 읽어야 한다.

**남은 판정자 불만은 두 가지로 좁혀졌다** -- 출처 품질("질문이 요구한 공식
EU 출처 대신 2차 비공식 출처")과 커버리지("루트 질문의 핵심 축이 미확인").
전자는 D45 가 후보 선택까지만 손댄 부분의 나머지(쿼리 증강)이고, 후자는 조사
깊이의 문제다. 리포트 층에서 할 일은 거의 끝났다.

## D52. 후보를 재배열하는 대신 늘린다 + 재시도 힌트의 프레이밍 (2026-08-09)

D51 이 남긴 두 불만 중 손댈 수 있는 쪽과, 같은 표본이 남긴 관찰 하나를 함께
고친다. 서로 다른 층(검색 / 리포트 조립)이라 표본 하나가 각각의 기대를 따로
반증할 수 있다.

### 쿼리 증강 — D45 는 절반만 고쳤다

D45 의 `_rank_by_source_tier` 는 **엔진이 이미 돌려준 목록을 재배열**한다.
엔진이 tier1 URL 을 0건 반환하면 정렬은 항등 함수이고, `source_candidate_
multiplier=3` 으로 후보를 넓힌 것도 **같은 질의의 3배**일 뿐이다. 고쳐야 할
것은 무엇을 고르는가가 아니라 **무엇을 후보로 받는가** 였다.

워커가 1차 기관 출처를 겨냥한 2차 질의(`search_primary_augment`, 기본값
`"공식 기관 원문 official primary source"`)를 한 번 더 돌려 후보에 병합한다.

- **기저 후보를 절대 버리지 않는다.** `_merge_candidates` 는 기저 목록 뒤에
  새 URL 만 잇는다. `_rank_by_source_tier` 가 안정 정렬이므로 같은 tier
  안에서는 기저 질의가 먼저 남는다 -- 증강이 관련도를 흐리는 최악의 경우에도
  기존 후보를 밀어내지 못하고, 결과 집합은 기저 질의의 **상위집합**이다.
- **비용은 검색 호출 한 번.** fetch 수는 `search_result_limit` 슬라이스가
  정하므로 그대로다. discovery(LLM tool-calling) 경로를 타지 않고 `_search`
  를 직접 부른다 -- 증강은 같은 질문의 보조 조회지 별도 조사가 아니다.
- **`site:` 문법이 아니라 평문 키워드인 이유**: `web_search` 는 질의 문자열
  하나만 받고(`service.py:17`) 백엔드 엔진이 무엇인지 모른다. `site:` 를
  지원하지 않는 엔진에서는 0건이 돌아오고, 그러면 fetch 할 URL 이 없어 모든
  클레임이 `E_NO_EVIDENCE` 로 거절된다 -- 검색어에 brief 전문을 넣었을 때와
  같은 고장이다. 키워드는 최악의 경우에도 결과를 흐릴 뿐 없애지 않는다.
  `site:` 를 지원하는 배포는 config 로 덮어쓰면 된다.

**계측**(`WorkerResult.search_augmentation` → `pass_completed` 의 `search_*`
키): `base_tier1` / `added_tier1` / `selected_tier1`. 앞의 둘은 증강이 무엇을
**찾았는지**, 마지막은 그중 무엇이 실제로 **fetch 됐는지**를 말한다. 후보에
tier1 이 늘어도 슬라이스가 잘라내면 아무 일도 일어나지 않으므로 둘을 갈라
기록해야 한다.

**반증 조건(표본 실행 전 고정).** 표본 전체에서 `added_tier1` 합이 0 이면
평문 키워드 증강은 효과가 없고, `site:` 문법이나 다른 기전이 필요하다.
`added_tier1` 은 늘었는데 `selected_tier1` 이 그대로면 문제는 검색이 아니라
`search_result_limit` 슬라이스다.

### 재시도 힌트 — 프레이밍이 내용만큼 무겁다

D51 이 기록한 관찰: 시도 1 의 주장 수가 늘고(19→60, 31→46, 16→42) 인용 비율은
나빠진다(.400 · .435 · .714).

원인 후보를 코드에서 확인했다. **`assemble` 은 직전 초안을 받지 않는다** --
`root_summary` · `child_summaries` · `caveats` · `revision_hints` 뿐이다.
그러니 "각 문장에 [C:claimid] 마커를 붙여라" 는 지시는 문자 그대로 수행이
불가능하다. 붙일 문장이 프롬프트에 없기 때문이다. 남는 것은 출처가 밝혀지지
않은 문장 8개가 조립 프롬프트 안에 놓인 상태이고, 그 자리에서 그것들은 고칠
대상이 아니라 **넣을 재료**로 읽힌다.

두 가지를 바꿨다. 둘 다 결정론적이고 프롬프트 크기를 거의 늘리지 않는다.

1. **길이 앵커.** 힌트 머리글이 직전 초안의 실측 주장 수를 인용하고 그보다
   길게 쓰지 말라고 말한다. 재시도의 실패는 인용 커버리지지 분량이 아니고,
   더 쓰는 것은 분모만 키운다.
2. **문장의 소유권 명시.** 인용된 문장이 **직전 초안의 것**임을 밝히고 그대로
   다시 쓰지 말라고 한다. `final_compose` v5 가 같은 규칙을 프롬프트 쪽에서
   한 번 더 건다 -- 반려 사유는 고칠 대상이지 새로 쓸 재료가 아니다.

**직전 초안 전문을 프롬프트에 넣는 방법은 택하지 않았다.** 그쪽이 원인을 더
곧게 없애지만, dev 조립 입력 허용량은 `assembly_input_ratio ×
synthesis_max_tokens = 6000` 이고 표본 #7·#8 에서 이 프롬프트는 이미 39~42회
클램프됐다. `shrink_once` 는 자식 요약 블록부터 자른다 -- 인용이 나오는 바로
그 증거다. 인용 문제를 증거 문제로 바꾸는 거래다.

**반증 조건(표본 실행 전 고정).** 시도 1 의 주장 수가 시도 0 을 넘지 않아야
하고, 시도 1 의 인용 비율이 시도 0 보다 나빠지는 일이 줄어야 한다. 주장 수는
줄었는데 비율이 여전히 나빠지면 원인은 프레이밍이 아니라 조립 자체의 절단이고
(#10 에서 `report_assembly` 가 아직 절단의 71%), 그때는 초안 전문을 넣는
비용을 다시 저울질해야 한다.

### 게이트

2486 passed / 16 skipped / 0 failed (`-p no:randomly`). 신규 4건 -- 증강이
기저가 놓친 tier1 을 fetch 까지 밀어넣는지, 병합이 기저 후보를 잃지 않는지,
빈 문자열이 off 스위치인지, 힌트 머리글이 길이를 앵커하고 문장을 소유권
표시하는지.

## D53. 표본 #11 — 증강은 되고, 재시도는 존재한 적이 없다 (2026-08-09)

트리 `ef8871df` · 커밋 `d87d64fd` · 사전 게이트 2486 passed / 16 skipped /
실패 0 · 아티팩트 `20260809T125612Z` · run `f9c1a0c7 f1a9e5bc 61f31bd3
18344fdf 7aa21c7f 0907dacd`.

### A. 쿼리 증강 — 확인

| | 기저 질의만 | 실측 |
|---|---|---|
| fetch 된 tier1 (6 run 합) | 165 (반사실) | **242 (+47%)** |
| 증강만 찾은 tier1 후보 | – | **153** |

반사실은 `min(base_tier1, search_result_limit)` 의 합이다 -- 증강이 없었다면
슬라이스가 기저 후보의 tier1 중 최대 3개까지만 뽑았을 값. **A-1 확인**
(`added_tier1` 153 ≫ 0, 평문 키워드 증강은 작동한다). **A-2 확인**
(`selected_tier1` 242 > `base_tier1` 192, 그리고 반사실 대비 +47%).

가장 선명한 사례는 `61f31bd3`: 22회 pass 동안 **기저 질의의 tier1 이 0건**
이었고 증강이 8건을 넣어 그대로 fetch 됐다. D52 가 예측한 "정렬이 항등 함수가
되는" 상태가 실제로 존재한다.

### A-3 반증 — 1차 출처를 fetch 하는 것과 그것을 인용하는 것은 다르다

판정자의 출처 품질 불만은 그대로다. `strength_ok=False` 4건이 여전히 2차
출처를 지목하고, 그중 하나는 이렇게 말한다:

> 제53조·제55조의 적용 개시일(2025-08-02) 등 핵심 시행일 주장이 EUR-Lex 나
> AI Act 본문(제113조)이 아닌 KISDI·PIPC·Prighter·Mayer Brown 등 비공식 출처에
> 의존하고 있어 …

같은 run 의 배달 리포트 첫 줄은 `Regulation (EU) 2024/1689` 와 EUR-Lex 공식
문서(32024R1689)를 인용한다. **EUR-Lex 는 fetch 됐다.** 그런데 핵심 사실은
2차 출처에서 왔다. `evidence_context_chars=2000` 이 fetch 한 문서를 앞
2,000자로 자르는데, 제113조 단계적 적용일은 100쪽짜리 규정 깊숙이 있다 --
워커는 표지를 보고 아무것도 못 얻은 뒤 그것을 요약한 블로그로 돌아간다.
가설이며, 다음 표본 전에 증거 URL 과 클레임 인용을 대조해 확인해야 한다.

### B. 재시도 힌트 — 측정 무효, 그리고 D51 정정

**시도 1 은 LLM 조립을 받은 적이 없다.** 6개 run 전부
`report_assembly_degraded`(`input_bound` 5 · `token_budget_exhausted` 1)로
강등돼 `deterministic_report()` 템플릿이 나왔다. 내가 B-1/B-2 로 잰
"시도 1 의 주장 수 44~96, 비율 악화"는 프레이밍의 결과가 아니라 템플릿이 자식
요약을 통째로 덤프한 결과다. **힌트 프레이밍은 시도 1 의 프롬프트에 도달한
적이 없으므로 이 표본은 그것을 재지 못했다.**

D48 과 같은 종류의 실수다 -- 사전 등록한 지표가 재려던 것을 재지 않았다.

그리고 같은 이벤트를 표본 #10 에서 다시 읽으니 **D51 이 틀렸다.**

| #10 run | 시도 1 | D51 의 서술 | 실제 |
|---|---|---|---|
| `917bc008` | DEGRADED(input_bound) | "재시도가 통과를 만든 첫 사례" | 강등 템플릿이 승인받았다 |
| `92701929` | DEGRADED(token_budget) | 통과 | 템플릿 + `judge=budget_exhausted` |
| `e5091e5d` | (없음, a0 통과) | 통과 | **유일한 진짜 판정자 승인** |

#10 의 "통과 3건 중 판정자 승인 2건" 은 **LLM 이 쓴 리포트에 대한 승인 1건**
으로 읽어야 한다. D50-4 판정("시도 1 이 다른 숫자를 내니 재시도가 예산을
받는다")도 추론이 틀렸다 -- `report_assembly_degraded` 는 정확히 이 구별을
위해 존재하는 이벤트인데 읽지 않았다.

### 진짜 병목 — clamp 이 자식 요약을 전부 버리고도 못 맞춘다

12건의 조립 clamp 이 **12/12 exhausted** 다. 자식 블록 6~7개 **전부**,
caveats 25~42개 **전부** 버리고도 `bound_after` 는 7,839~14,231 인데 허용량은
dev 6,000 / default 12,000 이다. `shrink_once` 가 건드리지 않는 것은
`root_answer` 하나뿐이므로(문서화된 정책: "root answer is never dropped"),
**루트 요약 혼자 허용량을 1.3~2.4배 초과한다.**

결과가 둘이다.

1. 조립 프롬프트는 매번 자식 요약을 전부 잃는다 -- **인용할 클레임이 프롬프트에
   없는 채로** 리포트를 쓴다. 이것이 uncited 비율의 상류 원인일 수 있다.
2. 시도 0 은 예산이 남아 통과하지만 시도 1 은 `input_bound` 로 거절된다.
   **재시도 루프는 도입 이래 한 번도 존재한 적이 없다.** D50 이 캡을 2→1 로
   줄여 산 것은 조립 상한이었지 재시도가 아니었다.

표본 #10 과 #11 의 clamp 수치가 사실상 같으므로(before 중앙값 23,996 vs
23,064) 이것은 증강의 부작용이 아니라 **원래 있던 상태**다.

### 무변 기대 -- 하나 깨짐

`job_failed` 0, 배달 6/6, `MISSING_QUESTION` 0 은 유지. **게이트 통과는
3 → 0.** 다만 위 정정을 반영하면 LLM 작성 리포트의 판정자 승인은 **1 → 0** 이고,
표본 하나에서 1→0 은 증강 탓이라 말할 수 없다(§10.2). a0 의 uncited 비율은
오히려 #11 이 낫다(0.000 · 0.143 · 0.161 · 0.029 vs #10 의 0.158 · 0.263 ·
0.039 · 0.161). 반려는 전부 판정자 쪽에서 났다.

### 다음

`root_answer` 를 clamp 대상에 넣는 것이 지금 가장 큰 한 수다. 그것이 재시도
루프를 처음으로 실재하게 만들고, 조립 프롬프트가 자식 요약을 잃지 않게 한다.
B-1/B-2 는 그 뒤에야 측정 가능하다.

## D54. 강등 요약의 무한 이어붙이기, 그리고 clamp 밖의 루트 요약 (2026-08-09)

D53 이 찾은 병목을 고친다. 두 층이고, 앞의 것이 원인 뒤의 것이 방어다.

### 원인 — `_degraded_summary` 의 join 이 무계였다

`reduce_node` 의 출력은 `synthesis_max_tokens`(dev 2,000)로 묶인다. 그런데
표본 #11 의 조립 프롬프트에서 루트 요약은 혼자 **5,800~12,200 입력 토큰**
이었다. 빈 조립 프롬프트가 2,019 이고 clamp 이 자식·caveats 를 전부 버린 뒤
`bound_after` 가 7,839~14,231 이었으니 나머지가 전부 루트 요약이다.

LLM 이 쓴 답이 그럴 수 없다. 강등 경로가 원인이다:

```python
answer = " ".join(c.answer for c in child_summaries if c.answer.strip())
```

**강등된 부모가 강등된 자식을 이어붙인다.** 자식의 답 자체가 그런 join 이므로
텍스트가 트리를 타고 누적된다. `7aa21c7f` 은 리덕션 12건이 강등됐고 그중
중간 노드 3개가 각각 children=4, 그리고 **마지막 강등이 루트**(children=7)
였다 -- 루트의 답이 사실상 서브트리 전체가 됐다.

`_bound_degraded_answer` 가 이 join 을 `synthesis_max_tokens` 로 자른다.
실제 답이 지키는 것과 같은 천장이고, `prompt_input_bound` -- `reserve()` 가
청구하는 그 자 -- 로 잰다. 자르는 방식은 반토막이다: 척도 무관이고 O(log n)
에 수렴하며 자/토큰 상수가 필요 없다(한국어와 라틴 문자가 3배 차이라 어떤
상수를 골라도 한쪽이 틀린다). 잘린 자리는 공백 경계로 당기고, 잘려나간
`[C:` 조각을 지운다 -- 반쪽 마커는 `_RAW_MARKER` 도 렌더러도 못 알아보므로
인용이 있어야 할 자리에 문자 그대로 남는다.

`node_reduction_degraded` 가 `answer_chars` 와 `answer_truncated` 를 싣는다.
없으면 강등된 루트가 400자 join 이었는지 40,000자였는지 원장에서 구별되지
않고, 조립을 망가뜨리는 것은 후자다.

### 방어 — 루트 요약을 clamp 대상에 넣는다

`shrink_once` 의 정책(D-6)은 "루트 요약은 절대 떨어뜨리지 않는다" 였고, 그
말이 실제로는 **"무한해도 된다"** 로 읽히고 있었다. 무계 앵커의 값은 나머지
전부가 치른다.

정책을 고친다: secondary 를 다 쓴 뒤 **primary 와 anchor 중 가장 긴 것**을
반토막 낸다. 앵커는 여전히 떨어뜨리지 않고 반토막만 낸다 -- 루트 요약이 없는
리포트는 짧은 리포트보다 나쁘다. 그리고 앵커가 정상 크기면 정책은 예전
그대로다: 가장 긴 것이 앵커가 되는 때는 앵커가 안 맞는 바로 그때뿐이다.

`ClampResult` 가 `anchor_chars_before/after` 를 싣고 원장 이벤트로 나간다.
반토막은 `dropped_primary` 에 아무 흔적을 남기지 않으므로, 없으면 "루트
요약을 5분의 1로 잘라 자식을 전부 지킨 프롬프트" 와 "클램프가 필요 없던
프롬프트" 가 같아 보인다.

### 재현 측정

표본 #11 규모(자식 7 + caveats 42, dev 허용량 6,000)를 그대로 재구성하고
인용 마커를 자식 본문 전체에 퍼뜨렸다.

| | exhausted | 조립 프롬프트에 살아남은 인용 마커 |
|---|---|---|
| 이전(앵커 clamp 밖, 무계 join 9,000자) | **True** | **0 / 70** |
| D54(join 유계 + 앵커 clamp) | False | **21 / 70** |

이전 행이 표본 #11 의 실측과 일치한다 -- `dropped_primary` 가 자식 전부,
`exhausted=True`, 그러고도 허용량 초과. **리포트는 인용할 클레임이 프롬프트에
하나도 없는 채로 쓰이고 있었다.**

정직하게: 21/70 이지 70/70 이 아니다. 자식 블록은 여전히 반토막이 나고 그
과정에서 마커가 준다. 바뀐 것은 **자식이 아예 없던 상태에서 전부 표현되는
상태로** 옮겼다는 것이다.

### 표본 실행 전 고정할 기대

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| C-1 | 조립 clamp 의 `exhausted` 비율이 12/12 에서 크게 내려간다 | 안 내려가면 남은 초과분은 앵커가 아니다 |
| C-2 | `dropped_primary` 중앙값이 7 에서 내려간다 | 자식이 여전히 전부 버려지면 허용량 자체가 작다 |
| C-3 | **`report_assembly_degraded` 가 준다 = 시도 1 이 처음으로 LLM 조립을 받는다** | 안 주면 재시도를 막는 것은 입력 크기가 아니라 예산 계층이다 |
| C-4 | `node_reduction_degraded` 의 `answer_truncated=True` 가 관측된다 | 0 이면 join 은 애초에 유계였고 D54 의 원인 진단이 틀렸다 |
| B-1/B-2 | C-3 이 참일 때만 측정 가능하다 | — |

게이트: **2491 passed / 16 skipped / 0 failed** (신규 5건).

## D55. 표본 #12 — 원인 진단이 맞았고, 재시도를 막는 것이 바뀌었다 (2026-08-10)

트리 `10a6d87f` · 커밋 `cee7f560` · 사전 게이트 2491 passed / 16 skipped /
실패 0 · 아티팩트 `20260809T160315Z` · run `01eadc5b f9bba141 efd168e2
61ac0f23 b6147760 53682849`.

### C-4 확인 — 원인 진단이 맞았다

`node_reduction_degraded` 32건 중 6건이 `answer_truncated=True`. 이분법이
선명하다:

| | 강등 join 원본 크기 |
|---|---|
| 잘린 6건 | 3,483 ~ **7,379자** (중앙값 3,978) |
| 안 잘린 26건 | 중앙값 **172자** |

리프 강등은 작고, 트리를 타고 누적된 소수가 거대하다 -- D54 가 예측한 모양
그대로다. 이 값이 0 이었다면 원인 진단이 틀린 것이었다.

### C-1 · C-2 · C-5 확인 (강함)

| | #10 | #11 | #12 |
|---|---|---|---|
| 조립 clamp `exhausted` | 10/11 | 12/12 | **0/11** |
| `dropped_primary` 중앙값 | 6 | 7 | **0** |
| `bound_after` 중앙값 | 9,644 | 9,716 | **5,880** (허용 6,000) |
| 앵커 반토막 | – | – | **11/11** |

**자식 요약이 더는 버려지지 않는다.** 앵커는 856→107, 626→78 처럼 최대 8분의
1까지 줄지만 한 번도 사라지지 않았고, 그 대가로 자식 블록이 전부 남는다.
D54 의 거래가 의도대로 성립했다.

### C-3 부분 확인 — 그리고 막는 것이 바뀌었다

`report_assembly_degraded` 6 → **4**, `synth_pass` 6 → **7**.
`b6147760` 에서 **재시도가 처음으로 진짜 LLM 조립을 받았다.**

남은 4건은 여전히 `input_bound` 인데, **원인이 달라졌다.** 클램프는 이제
성공한다(`bound_after` 5,880 < 허용 6,000). 예약 로그가 답을 준다:

```
reserved  input_bound=5926 max_out=2000 total=7926   <- 시도 0
reserved  input_bound=5926 max_out=4000 total=9926   <- 절단 후 2배 재시도
DEGRADED  reason=input_bound                          <- 시도 1 은 자리가 없다
```

`call_text` 는 잘린 조립에 **출력 상한을 2배로 준 한 번 더**를 준다. 그래서
절단된 시도 0 은 조립 예산의 `1× + 2×` 를 쓴다. `report_assembly` 절단은
#11 7건 → #12 **9건**으로 오히려 늘었고, run 당 조립 예약 횟수는 6개 run 중
5개가 2회, 1개가 3회다.

D50 의 바닥 공식 `report_floor_tokens = (report_retry_cap + 1) × (assembly +
grading)` 는 조립 **2회분**을 잡는다. 절단이 있으면 한 시도가 3회분을 쓰므로
2회분으로는 시도 1 이 들어갈 자리가 없다. **입력 크기는 더 이상 병목이
아니고, 이제 예산 계층이 병목이다** -- C-3 의 반증 조항이 예고한 바로 그
갈림이다.

### B-1 · B-2 — 여전히 측정 불가 (n=1)

측정 가능한 재시도가 `b6147760` 하나뿐이다. 그 하나에서 B-1 은 성립했고
(주장 8 → **6**, 재시도가 처음으로 늘지 않았다) B-2 는 실패했다
(.625 → 1.0). **n=1 로는 아무것도 말할 수 없다**(§10.2).

### 무변 — 유지, 그리고 통과 1건

`job_failed` 0 · 배달 6/6 · `MISSING_QUESTION` 0 유지. 쿼리 증강도 그대로다.
게이트 통과 **0 → 1**(`53682849` 시도 0, `judge=ran`) -- LLM 이 쓴 리포트에
대한 진짜 판정자 승인이고, 정정된 #10 의 실질 통과 수와 같다.

### 정직하게 적을 것 — LLM 작성 리포트의 각주가 줄었다

배달된 리포트를 **어느 시도의 것인지** 갈라서 봐야 한다. 결정론 템플릿은
자식 요약을 통째로 덤프하므로 각주가 많고 본문이 길다 -- 집계에 섞으면
개선처럼 보인다.

| | LLM 작성 배달 | 본문 중앙값 | 각주 중앙값 |
|---|---|---|---|
| #10 | 4/6 | 3,884자 | **12** |
| #11 | 5/6 | 2,990자 | **7** |
| #12 | **3/6** | 3,105자 | **2** |

템플릿이 `_best_rejected_draft` 순위에서 더 자주 이겨(3/6) 집계 중앙값
(본문 5,643자 · 각주 13)은 올랐지만, **LLM 이 쓴 리포트만 보면 각주가
줄었다.** 표본 하나로 D54 탓이라 말할 수 없고 n=3 이다. 다음 표본의 1차
관찰 대상으로 못 박는다.

### 다음

`call_text` 의 절단 확장이 조립 예산의 3배를 쓰는데 바닥은 2배만 잡는다.
바닥 공식이 그 확장을 알아야 한다 -- 그것이 남은 4건의 강등을 없애고,
B-1/B-2 를 처음으로 측정 가능하게 만든다.

## D56. 바닥이 절단 확장을 세게 한다 (2026-08-10)

D55 가 찾은 병목을 고친다. `report_floor_tokens` 의 조립항이 `call_text` 의
절단 확장을 세지 않았다.

### 무엇이 틀렸나

`call_text` 는 잘린 응답에 **같은 프롬프트를 `truncation_retry_multiplier`
배 출력 상한으로** 다시 보낸다(llm.py:464-474). 프롬프트가 같으므로 입력이
두 번 청구되고 출력은 `1 + m` 배가 된다. 옛 조립항은 `input + output` 한
번분만 잡았다.

표본 #12 가 그 쌍을 그대로 남겼다:

```
reserved  input_bound=5926 max_out=2000 total=7926   <- 시도
reserved  input_bound=5926 max_out=4000 total=9926   <- 확장
DEGRADED  reason=input_bound                          <- 시도 1 은 자리가 없다
```

17,852 대 조립항 8,000. 6개 run 중 5개가 `report_assembly` 를 두 번, 1개가
세 번 예약했다. **옛 공식은 시도 2회분을 잡았는데 절단된 시도 하나가 3회분을
쓴다.** 그래서 `_finalize` 의 재시도가 6개 중 4개에서 예약을 거절당했고,
재시도 루프가 도입 이래 실재한 적이 없었다(D53 · D55).

### 고친 것

```python
assembly = int(
    m * assembly_input_ratio * synthesis_max_tokens
    + (1 + m) * synthesis_max_tokens
)
```

`grading_floor_tokens` 가 판정자에 대해 이미 하던 것과 같은 교정이다. dev
조립항 8,000 → **18,000**(실측 17,852 를 덮는다), default 16,000 → 36,000.

`grading` 은 `m * (input + output)` 인 채로 둔다. 정확한 형태와 정확히
`report_judge_max_output_tokens`(800) 만큼 차이 나는데 항 자체가 10,800 이라
8% 미만이고, 그것을 가리키는 측정이 없다. **조립항만 고치는 이유는 표본이
그것이 물리는 것을 쟀기 때문이다.**

### 값을 치른 곳 -- dev cap 100,000 → 140,000

교정이 dev 의 최종 바닥을 48,000 → 68,000 으로 올린다. 옛 cap 에서 그것은
68% 이고 `finalization_floor_warn_ratio` 를 넘는다 -- **기본값이 경고를 켠
채로 출하된다는 뜻이고**, 그 경고는 코너로 몰린 프로파일용 백스톱이지 늘
켜두는 것이 아니다. 게다가 조사 예산이 52,000 → 32,000 으로 줄어드는데
`f9bba141` 은 이미 50,318 을 쓰고 바닥에서 멈췄다.

140,000 에서 바닥은 49%, 조사 예산은 72,000 이다. default 프로파일은 손대지
않는다 -- 같은 교정이 31% → 45% 라 여유가 있다.

**실제 토큰을 더 쓴다. 다만 바닥에 닿는 run 에서만이다** -- 표본 #11·#12 각각
dev 5개 중 1개였고, 나머지 넷은 23,000~39,000 으로 어느 cap 에도 닿지 않았다.

### 검산

조립 계층 = `report_floor - grading_floor` = 57,600 - 21,600 = **36,000**.
모든 시도가 절단되는 최악의 경우 = 2 × (7,926 + 9,926) = 35,704. 덮는다.
중첩 불변(grading ⊆ report ⊆ floor)도 두 프로파일에서 유지된다.

### 표본 #13 실행 전 고정할 기대

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| E-1 | `report_assembly_degraded` 가 #12 의 4건에서 크게 준다 | 안 주면 남은 원인은 예약 계층이 아니다 |
| E-2 | `synth_pass` > run 수 = 재시도가 여러 run 에서 LLM 조립을 받는다 | 여전히 n=1 이면 B-1/B-2 를 또 못 잰다 |
| **B-1** | 시도 1 의 `uncited_assertions` 가 시도 0 을 넘지 않는다 | E-2 가 참일 때만 판정한다 |
| **B-2** | 시도 1 의 `uncited_ratio` 악화가 준다 | 위와 같다 |
| E-3 | **LLM 작성 배달 리포트의 각주 중앙값이 #12 의 2 에서 회복된다** | D55 가 못 박은 관찰 대상. 안 오르면 D54 의 앵커 반토막을 다시 봐야 한다 |
| 무변 | `job_failed` 0 · 배달 6/6 · clamp `exhausted` 0 · 쿼리 증강 유지 | — |

게이트: **2493 passed / 16 skipped / 0 failed** (신규 2건).

## D57. 표본 #13 — 재시도 루프가 처음으로 실재한다 (2026-08-10)

트리 `789cf25b` · 커밋 `156abc21` · 사전 게이트 2493 passed / 16 skipped /
실패 0 · 아티팩트 `20260810T110354Z` · run `8bd975a7 0846458b 5bd08713
84cdde80 ca1f02e5 6a3271b6`.

### E-1 · E-2 확인 — 그리고 이 프로젝트가 여덟 표본 동안 못 하던 일

| | #11 | #12 | #13 |
|---|---|---|---|
| `synth_pass` (LLM 조립 횟수) | 6 | 7 | **12** |
| `report_assembly_degraded` | 6 | 4 | **0** |
| run 당 조립 예약 횟수 | {1:2, 2:4} | {2:5, 3:1} | **{4:6}** |
| 조립 clamp `exhausted` | 12/12 | 0/11 | **0/12** |

`synth_pass` 12 = 6 run × 2 시도. **6개 run 전부 시도 0 과 시도 1 이 진짜
LLM 조립을 받았다.** 강등은 0 건이다. 예약 횟수 {4:6} 은 run 마다 2 시도 ×
(본체 + 절단 확장) 을 다 받았다는 뜻이고, D56 의 조립항이 정확히 그 모양으로
사이징됐다.

**재시도 루프가 도입 이래 처음으로 완전히 실재한다.** D53 이 "한 번도 존재한
적이 없다" 고 적은 것이 여기서 끝난다.

### B-1 확인 (5/6) — 힌트의 길이 앵커가 통한다

표본 #10 에서는 측정된 재시도 3건이 **전부** 주장 수를 키웠다(19→60, 31→46,
16→42). #13 은 6건 중 5건이 키우지 않았다.

| run | 주장 | 비율 |
|---|---|---|
| `8bd975a7` | 19 → **7** | .526 → 1.000 |
| `0846458b` | 17 → 34 | .059 → .529 |
| `5bd08713` | 8 → **6** | .375 → 1.000 |
| `84cdde80` | 17 → **6** | .706 → **.500** |
| `ca1f02e5` | 12 → **7** | .833 → 1.000 |
| `6a3271b6` | 31 → **28** | .032 → .036 |

### B-2 반증 (1/6) — 그리고 실패의 모양이 바뀌었다

재시도는 여전히 인용을 나쁘게 쓴다. 다만 **짧아지면서 나빠진다** -- 세 건이
주장 수를 3분의 1로 줄이면서 비율 1.000 에 도달했다. 길이 앵커가 "짧게
써라" 로는 통했고, 짧아진 결과가 **인용 없는 요약 문장만 남은 본문**이다.
모델이 분량을 줄이면서 버리는 것이 인용 가능한 문장 쪽이다.

이것은 #10 의 실패(길고 나쁨)와 다른 실패다. 힌트를 더 밀어붙이는 방향이
아니라, 무엇을 남기라고 말하는지가 문제다.

### E-3 반증 — 각주는 회복되지 않았다

배달 리포트를 **어느 시도가 썼는지** 갈라서 센다(D55 의 방법).

| | LLM 작성 배달 | 본문 중앙값 | 각주 중앙값 |
|---|---|---|---|
| #10 | 4/6 | 3,884자 | 12 |
| #11 | 5/6 | 2,990자 | 7 |
| #12 | 3/6 | 3,105자 | **2** |
| #13 | **6/6** | 3,494자 | **2** |

**배달은 개선됐다** -- 6개 전부 LLM 이 쓴 리포트다(#12 는 3/6 이 결정론
템플릿이었다). **각주는 회복되지 않았다.** E-3 의 반증 조항이 앵커 반토막을
가리켰으므로 거기를 봤다.

### 원인을 확정하지 못했고, 그 이유가 관측 구멍이다

| | 앵커 | dropped_primary | bound |
|---|---|---|---|
| #13 | 682 → 304자 (50% 잔존) | **0** | 17,812 → **5,883** |

앵커 절삭은 절반이고 자식 블록은 **하나도 버려지지 않았다.** 그런데 프롬프트는
3분의 1로 줄었다. 답은 하나뿐이다 -- `shrink_once` 가 가장 긴 primary 를
반토막 내고 있고, **그것은 `dropped_primary` 에 아무 흔적을 남기지 않는다.**
항목 수만 세기 때문이다.

D54 가 앵커에 대해 고친 것과 **정확히 같은 종류의 구멍**이다. 그때
`anchor_chars_before/after` 를 넣은 이유가 "반토막은 dropped 카운트에 흔적을
남기지 않는다" 였는데, primary 에는 같은 조치를 하지 않았다.

그래서 각주 감소의 원인 후보 둘을 **가를 수 없다**:

- (a) 자식 블록 반토막으로 `[C:...]` 마커가 프롬프트에서 사라진다
- (b) 무계 강등 join 이 사실상 마커 운반체였고 D54 가 그것을 잘랐다

(b) 는 그럴듯하다 -- #11 에서 자식이 전부 버려졌는데도(`dropped_primary` 7)
각주가 4~14개 나왔다면 그 마커는 앵커에서 왔을 수밖에 없다. 하지만 두 후보
모두 지금 원장으로는 확인이 안 된다.

**다음 수는 고치는 것이 아니라 재는 것이다** -- clamp 이벤트에
`primary_chars_before/after` 를 넣는다. 원인을 모르는 채 고치면 D40(잘못된
가지를 고치고 D43 에서 정정) 과 D51(읽지 않은 이벤트로 추론) 을 반복한다.

### 무변 — 전부 유지

`job_failed` 0 · 배달 6/6 · `MISSING_QUESTION` 0 · clamp `exhausted` 0/12 ·
쿼리 증강 유지(`added_tier1` 184, `selected_tier1` 239 > `base_tier1` 202).

게이트 통과는 1 → 0 이다. 실행 전에 **이번 표본의 1차 지표가 아니라고**
적어뒀다 -- D56 은 예약 계층을 고치는 변경이고 통과율은 그 하류다. 판정자는
`6a3271b6` 의 두 시도를 다 보고 둘 다 반려했다(비율 .032 / .036 으로
인용은 충분했다).

D56 의 비용도 예고대로다: `8bd975a7` 이 71,129 를 쓰고 바닥에서 멈췄다
(cap 140,000). #12 는 50,318 / 100,000 이었다.

## D58. 반토막을 볼 수 있게 한다 -- 고치기 전에 잰다 (2026-08-10)

D57 이 각주 감소(12 → 7 → 2 → 2)의 원인을 **가르지 못한 채** 끝났다. 후보는
둘이었고 원장은 둘 다에 침묵했다. 이번 변경은 고치는 것이 아니라 **재는
것**이다.

### 왜 안 보였나

`shrink_once` 는 **버리기 전에 반토막부터 낸다.** `dropped_primary` 는 항목
수만 세므로, 자식 블록 일곱 개를 전부 유지하면서 각각을 8분의 1로 자른
클램프가 `dropped_primary=0` 으로 기록된다 -- 손대지 않은 것처럼 보인다.

표본 #13 이 정확히 그 모양이다:

| 앵커 | dropped_primary | bound |
|---|---|---|
| 682 → 304자 (절반) | **0** | 17,812 → **5,883** |

앵커는 절반만 줄고 자식은 하나도 안 버려졌는데 프롬프트는 3분의 1이 됐다.
그 토큰이 어디로 갔는지 원장에 답이 없었다. **D54 가 앵커에 대해 고친 것과
정확히 같은 구멍이고, 그때 primary 에는 같은 조치를 하지 않았다.**

### 두 층으로 잰다

**크기 (`prompt_clamp`).** `ClampResult` 에 `primary_chars_before/after`.
클램프는 크기만 안다 -- 그것이 클램프가 아는 전부다.

**인용 (`synthesizer`).** 그 글자들이 `[C:xxxxxxxx]` 주소를 나른다는 것은
호출자만 안다. `_log_clamp` 가 `claim_markers_before/after` 를 싣는다.
**프롬프트에 살아남은 마커 수가 리포트가 가질 수 있는 인용의 상한**이고,
D57 은 마커가 작성자에게 도달하기는 했는지조차 답하지 못했다.

`markers_before` 는 자식 블록과 **앵커를 함께** 센다. 강등된 루트 답은 자식
답들의 join 이라 그 마커를 그대로 나르므로, 손실을 귀속하려면 두 출처가 다
"before" 에 들어가야 한다. `node_reduction` 도 같이 잰다 -- 여기서 잃은
마커는 조립에 도달한 적이 없으므로, 리포트 층 탓으로 돌리려면 이 층을 먼저
배제해야 한다.

### 도구가 실제로 가르는지 확인했다

표본 #13 규모를 재구성하고 두 시나리오를 돌렸다. **둘 다
`dropped_primary=0` 이다** -- 옛 계측으로는 구별 불가다.

| | 마커 생존 | primary 잔존 | anchor 잔존 |
|---|---|---|---|
| (a) 마커가 자식에 | 70 → 21 (30%) | 25% | 25% |
| (b) 마커가 앵커(강등 join)에 | 70 → **3 (4%)** | 29% | **3%** |

새 필드가 갈라준다: (b) 는 앵커가 3% 로 무너지는데 primary 는 29% 를 지키고,
마커 생존이 함께 붕괴한다. 표본 #14 가 실측을 어느 쪽에 놓을지 말해준다.

### 표본 #14 실행 전 고정할 기대

이 표본은 **가설을 세우기 위한 관측**이지 수정의 검증이 아니다. 기대는
"어떤 값이 나와야 한다" 가 아니라 **"어떤 값이 나오면 무엇을 고친다"** 이다.

| 관측 | 읽는 법 |
|---|---|
| `claim_markers_after` 가 `before` 대비 크게 낮다 | 마커가 작성자에게 도달하지 못한다 -- 절삭 정책이 문제다 |
| `anchor_chars_after/before` 가 `primary` 것보다 훨씬 낮다 | (b) -- 강등 join 이 마커 운반체였고 D54 가 그것을 잘랐다 |
| 둘이 비슷하고 마커 생존도 비례한다 | (a) -- 자식 반토막이 원인이다. 허용량이나 절삭 정책을 손댄다 |
| `claim_markers_after` 는 높은데 배달 각주는 낮다 | 절삭이 아니라 **작성자가 있는 마커를 안 쓴다** -- 프롬프트 문제다 |
| `node_reduction` 의 마커 손실이 크다 | 리포트 층이 아니라 리덕션 층이 먼저다 |

마지막 줄이 중요하다. 그 경우 지금까지의 진단이 전부 한 층 아래를 봤어야
했다는 뜻이다.

게이트: **2495 passed / 16 skipped / 0 failed** (신규 2건).

## D59. 표본 #14 — 병목은 순수하게 절삭이다, 그리고 내 계측이 반쯤 틀렸다 (2026-08-11)

트리 `518cc78b` · 커밋 `f5817ddd` · 사전 게이트 2495 passed / 16 skipped /
실패 0 · 아티팩트 `20260810T154952Z` · run `8a7241d7 d01a5dba 270860c5
a31419fa a3239c48 aa2c98dd`. **관측 표본이지 수정의 검증이 아니다**(D58).

### 불변이 완전히 일치한다

`synth_pass` 12 · 조립 강등 0 · clamp `exhausted` 0/12 · 배달 6/6 ·
`job_failed` 0 · `MISSING_QUESTION` 0 · 게이트 통과 0 -- **표본 #13 과 모든
항목이 같다.** 동작 변경이 없었으니 그래야 맞고, 덤으로 이 지표들의 표본 간
변동이 작다는 것을 처음으로 확인했다(지금까지 표본 하나로 판정해 왔다).

### R-3 반증 (강함) — 작성자는 받은 마커를 거의 다 쓴다

| run | 프롬프트에 살아남은 마커 | 배달 리포트 각주 |
|---|---|---|
| `8a7241d7` | 7 | 5 |
| `d01a5dba` | 2 | 2 |
| `270860c5` | 2 | 2 |
| `a31419fa` | 4 | 4 |
| `a3239c48` | 1 | 0 |
| `aa2c98dd` | 21 | 17 |

**거의 1:1 이다.** 각주가 적은 이유는 작성자가 마커를 안 써서가 아니라
**프롬프트에 마커가 없어서**다. 병목은 순수하게 절삭이고, `final_compose`
프롬프트를 손댈 자리가 아니다. D57 이 못 하던 귀속이 여기서 끝난다.

### 후보 (b) 배제 — 앵커가 마커 운반체는 아니었다

| | 잔존 중앙값 |
|---|---|
| primary (자식 블록) | **36%** |
| anchor (루트 요약) | **50%** |

(b) 가 맞다면 앵커가 더 심하게 잘려야 하는데 **반대**다. D54 가 강등 join 을
자른 것이 각주 감소의 주원인이라는 가설은 지지받지 못한다.

### (a) 는 부분 지지, 그러나 설명이 부족하다

자식 블록이 잘리는 것은 맞다(36% 잔존). 그런데 **마커 생존율은 9%** 다
(314 → 57). 균등 분포라면 36% 자에서 마커도 ~36% 가 남아야 한다.

두 기전을 코드로 시험했고 **둘 다 이 격차를 설명하지 못한다**:

- **질문 텍스트가 앞을 먹는다?** `shrink_once` 는 `block[:len//2]` 로 앞을
  남기고, W3-i 가 질문을 블록 앞에 붙였다. 그러나 실측 블록에서 질문 헤더는
  11% 지점에서 끝난다 -- 지배적이지 않다. 앞/뒤 절반 보존을 비교하면 25%
  자 지점에서 마커 12% 대 25% 로, 차이는 있으나 9% 를 만들지 못한다.
- **긴 블록이 마커도 많고 `shrink_once` 가 가장 긴 것을 친다?** 마커 수가
  블록 길이에 비례하는 6개 자식으로 36% 까지 줄여봤다. 마커 생존 **34%** --
  비례한다.

**즉 마커가 블록 안에서 균등 분포가 아니고, 어디에 몰려 있는지 모른다.**
실측은 5,065자당 마커 22개(230자/마커)로 시뮬레이션(65자/마커)보다 3.5배
희박하다. 여기서 더 나가는 것은 추측이다.

### 내 계측의 결함 둘 — 정직하게

**(1) `node_reduction` 의 `markers_before` 가 불완전하다.** `claim_lines`
만 세는데 렌더된 프롬프트에는 `child_lines`(자식 답, 마커 포함)도 들어간다.
그래서 합계가 **35 → 90 으로 after 가 before 보다 크다.** 비교가 성립하지
않으므로 **R-4 는 판정 불가**다 -- 리덕션 층이 마커를 잃는지 여전히 모른다.

**(2) 개수는 중복을 센다.** `len(findall(...))` 는 출현 횟수이고 각주는
**고유 클레임** 수다. 같은 클레임이 자식 블록과 루트 요약에 함께 나오면
`markers_before` 가 이중으로 센다. 위 1:1 대응은 방향으로는 옳지만 정확한
비율로 읽으면 안 된다.

D58 이 "고치기 전에 잰다" 를 내세웠는데, **그 자를 두 군데 잘못 만들었다.**
다음 표본 전에 고쳐야 할 것이 수정이 아니라 계측이다.

### 다음

1. `node_reduction` 의 `markers_before` 에 `child_lines` 를 포함한다.
   R-4 는 그 뒤에야 판정 가능하고, R-4 가 참이면 D54·D56·D58 이 전부 한 층
   위를 손댄 것이 된다.
2. 마커를 **고유 클레임 id 집합**으로 센다.
3. 그러고도 (a) 의 격차가 남으면, 블록 안 마커 분포를 재는 것이 다음이다 --
   절삭 정책을 마커 인지형으로 바꾸는 것은 원인을 확정한 뒤다.

## D60. 자를 고친다 (2026-08-11)

D59 가 D58 의 계측에서 결함 둘을 찾았다. 수정이 아니라 **자를 고치는** 변경이다.

### 셋을 고쳤다 (둘이 아니라)

**(1) `node_reduction` 의 `before` 가 `child_lines` 를 빠뜨렸다.**
`render_node` 가 프롬프트에 넣는 절반인데 세지 않았다. 표본 #14 합계가
35 → 90 으로 `after` 가 `before` 보다 컸고, 그 한 가지 사실이 리덕션 층
계측 전체를 무효로 만들었다.

**(2) 출현 횟수를 셌다.** `CitationRenderer` 는 몇 번 인용되든 클레임당
각주 하나를 준다. 그리고 같은 클레임이 자식 블록과 **그것을 요약한 루트
답**에 함께 나오는 것은 예외가 아니라 상례라, 사실상 전부 이중으로 셌다.
이제 고유 id 집합이다.

**(3) 조립의 `before` 가 `caveats` 를 빠뜨렸다** -- D59 가 못 본 세 번째다.
`caveats` 는 clamp 의 secondary 이자 프롬프트의 일부이고, 노드 요약은 자기
caveat 에도 마커를 단다(D44 가 표본 #7 의 30건 중 3건에서 관측했고, 그것이
raw 마커가 최종 텍스트에 새던 경로였다). (1) 과 정확히 같은 결함이 조립
쪽에 남아 있었다.

### 이름을 바꿨다

`claim_markers_*` → `distinct_claims_*`. 제자리에서 고치지 않은 이유는
**의미가 달라졌기 때문**이다. 키를 유지하면 표본 #14 의 출현-횟수 값과 이후의
고유-클레임 값이 조용히 한 통에 섞인다 -- D48 이 표본 하나를 치르고 배운
바로 그 실수다.

### 테스트를 두 번 고쳤다

처음 쓴 것은 `after <= before` 불변식이었다. **버그를 되살려도 통과했다.**
두 번 다시 만들고서야 이유를 알았다:

- 절삭이 너무 세면 양쪽이 0 이 되어 부등식이 공허하게 성립한다.
- `reduce_node` 에서 `child_lines` 는 **secondary** 이므로 `shrink_once` 가
  가장 먼저 버린다. 자식 마커가 `after` 에 남지 못하니, 빠뜨린 `before`
  로도 부등식이 성립한다.

그래서 부등식 대신 **의도를 직접 주장한다**: 리덕션의 `before` 는 2(노드
클레임 1 + 자식 줄 1), 조립의 `before` 는 3(자식 1 + 루트 1 + caveat 1).
결함 (1) 은 1 을, 결함 (3) 은 2 를 낸다. 되살려 확인했고 둘 다 잡힌다
(`assert 1 == 2`, `assert 2 == 3`). 부등식도 함께 주장하되 **그것이 이
결함들을 잡지 못한다는 사실을 테스트 안에 적어뒀다.**

계측기를 만들 때 "동작하는지 확인" 은 통과를 보는 것이 아니라 **실패해야 할
때 실패하는지 보는 것**이다. D58 은 앞만 했다.

### 표본 #15 는 다시 관측이다

D59 의 R-1 · R-2 · R-5 는 표본 #14 로 이미 좁혀졌고(R-3 반증, 후보 (b)
배제), 남은 것은 **R-4 판정**과 (a) 의 설명되지 않은 격차다.

| 관측 | 읽는 법 |
|---|---|
| `node_reduction` 의 `after/before` 가 낮다 | **R-4** -- 리덕션 층이 먼저다. D54·D56·D58 이 한 층 위를 손댄 것이 된다 |
| 리덕션은 높은데 조립이 낮다 | 리포트 층이 맞다. (a) 의 격차를 마커 분포로 파고든다 |
| 조립의 `distinct_claims_after` 가 배달 각주와 여전히 1:1 | R-3 반증이 고유 기준으로도 유지된다 |

게이트: **2497 passed / 16 skipped / 0 failed** (신규 2건).

## D61. 표본 #15 — 리포트 층이 맞다, 그리고 작성자는 받은 것을 전부 쓴다 (2026-08-11)

트리 `93e2e14b` · 사전 게이트 2497 passed / 16 skipped / 실패 0 · 아티팩트
`20260811T103154Z` · run `c1aad077 b0d073f5 a1027074 68af4c21 2a41679a
7211f24e`. **관측 표본이다**(D60).

**영수증 커밋이 사전 등록과 다르다.** 등록은 `4f7a4828`, 영수증은
`1014bc40` -- 실행 중 다른 트랙(coding agent track E)의 문서 커밋 4개가
`dev` 에 올라왔다. `git diff 4f7a4828 1014bc40 -- neos/ tests/ config/
scripts/ pyproject.toml` 는 **비어 있다**(바뀐 것은
`docs/superpowers/` 아래 두 파일뿐). 측정 대상 코드는 등록한 그대로이므로
표본은 유효하다. 그래도 §10.2 가 요구하는 것은 영수증이 진실을 말하는
것이므로 여기 적어둔다.

### 불변 -- 세 표본 연속 완전 일치

`synth_pass` 12 · 조립 강등 0 · clamp `exhausted` 0/12 · 배달 6/6 ·
`job_failed` 0 · `MISSING_QUESTION` 0 · 통과 0. **#13 · #14 · #15 가 모든
항목에서 같다.** 위생 조건(`after > before` 0건)도 통과했다 -- D59 를
무효로 만든 그 신호가 이번엔 없다.

### R-4 반증 — 리덕션 층이 주범이 아니다

| 층 | 고유 클레임 생존율 (중앙값) | 합계 |
|---|---|---|
| `node_reduction` | **100%** | 184 → 101 |
| `report_assembly` | **15%** | 208 → 78 |

**리포트 층이 맞다.** D54 · D56 · D58 이 올바른 무대를 손댔다는 것이 처음으로
확인됐다 -- R-4 가 참이었다면 그 셋이 전부 한 층 위를 손댄 것이 됐다.

### R-3 재확인 — 고유 기준으로 더 깨끗하다

| run | 조립 프롬프트에 살아남은 고유 클레임 | 배달 각주 |
|---|---|---|
| `c1aad077` | 2 | **2** |
| `b0d073f5` | 4 | **4** |
| `a1027074` | 1 | **1** |
| `68af4c21` | 3 | **3** |
| `2a41679a` | 0 | **0** |
| `7211f24e` | 34 | 29 |

**다섯 건이 정확히 일치한다.** 표본 #14 는 출현 횟수로 "거의 1:1" 을 봤는데,
고유 기준에서는 오차가 사라진다 -- 그 대응은 계수 방식의 산물이 아니었다.

**작성자는 받은 클레임을 전부 쓴다. 각주 수는 절삭이 남긴 것과 같다.**
이것으로 프롬프트 층(`final_compose`)은 완전히 배제된다.

### 남은 격차 — 고유 기준으로도 재현된다

조립에서 `primary` 는 33% 가 남는데 고유 클레임은 15% 만 산다. 표본 #14 의
36% 대 9% 와 같은 비례 이탈이고, 계수 방식을 바꿔도 사라지지 않았다.
**절삭이 글자보다 클레임을 빠르게 없앤다**는 것은 이제 두 표본에서 관측된
사실이다.

### 새 관측 — 리덕션의 전부-아니면-전무

`node_reduction` 19건 중 **12건이 100% 유지, 4건이 0%** 다. 잃은 건들은
(22→0), (7→0), (20→0), (44→16) -- 큰 것이 통째로 날아간다. `reduce_node`
에서 `child_lines` 는 **secondary** 이고 `shrink_once` 는 secondary 를 항목째
가장 먼저 버리므로, 손실이 부분적이지 않고 전부-아니면-전무가 된다.

중앙값 100% 뒤에 이것이 숨어 있으므로, 합계(55% 생존)와 중앙값(100%)을 함께
읽어야 한다. R-4 의 답은 바뀌지 않는다 -- 조립의 15% 가 여전히 훨씬 나쁘다.

### 다음

원인은 세부 기전까지 확정되지 않았지만(마커가 블록 안 어디에 몰리는지),
**고치는 방법은 그것과 무관하게 같다**: 절삭이 마커를 인지하게 만들면 어떤
분포에서도 클레임 생존이 오른다. D40 이 관측된 실패를 설명하지 못하는 가지를
고친 것과 다르다 -- 여기서 겨냥하는 것은 관측된 실패 그 자체다(절삭이 클레임을
없애고, 각주는 정확히 남은 만큼이다).

## D62. 마커 인지형 절삭 (2026-08-11)

D61 이 무대를 확정했다 -- 리포트 층 절삭이 병목이고, 작성자는 받은 클레임을
전부 쓴다. 이제 그 절삭이 무엇을 남기는지 바꾼다.

### 무엇이 틀렸나

`halve` 는 문자 오프셋에서 자르고 그 뒤를 통째로 버린다. 마커가 어디 있는지
모르므로 인용이 글자보다 빠르게 사라진다 -- 두 표본에서 관측됐다:

| | primary 글자 잔존 | 고유 클레임 생존 |
|---|---|---|
| 표본 #14 | 36% | **9%** |
| 표본 #15 | 33% | **15%** |

그리고 이 손실은 산문 손실과 성격이 다르다. **작성자에게 도달하지 못한
클레임은 인용될 수 없다** -- 표본 #15 는 배달 각주가 잔존 클레임과 6건 중
5건에서 **정확히** 일치했다.

### 고친 것

`compact_keeping_claims` 가 문장 단위로 쪼개, **마커를 가진 세그먼트를 먼저**
담고 남은 예산을 나머지로 채운다. 글자 예산은 `halve` 와 같은 절반이므로
**클램프의 수렴은 그대로이고 바뀌는 것은 어느 글자를 남기는가뿐이다.**

책임 분리는 D58 과 같다: `prompt_clamp` 는 크기만 알고, 마커를 아는 층
(`synthesizer`)이 압축기를 주입한다. `shrink_once`/`clamp_prompt` 에
`compact` 인자가 생겼고 기본값은 `halve` 다.

### 수렴을 정책의 선의에 걸지 않는다

정책이 주입 가능해지면 종료 보장이 약해진다. `_progress` 가 한 걸음마다
"실제로 줄었는가" 를 검사하고 아니면 `halve` 로 되돌린다. 반복 상한이 여전히
잡기는 하지만, 그때 `exhausted` 로 보고되는 프롬프트는 **줄일 수 있었는데 안
줄인** 것이다. 되돌리는 쪽이 품질만 잃고 종료는 지킨다.

### 효과 -- 표본 #15 규모 재구성

고유 클레임 42개, primary 4,631자, 압박을 허용량으로 바꿔가며:

| 허용량 | `halve` 클레임 | 글자 | D62 클레임 | 글자 |
|---|---|---|---|---|
| 9,000 | 21 (50%) | 50% | **42 (100%)** | 52% |
| 7,000 | 18 (43%) | 39% | **42 (100%)** | 44% |
| **6,000** (dev 실제) | 16 (38%) | 32% | **38 (90%)** | 37% |
| 5,000 | 14 (33%) | 25% | **32 (76%)** | 26% |
| 4,000 | 10 (24%) | 18% | **28 (67%)** | 19% |

**글자 잔존은 사실상 같은데 클레임은 2~3배 남는다.** 압박이 셀수록 격차가
커진다.

### 테스트가 실패해야 할 때 실패하는지 확인했다

D60 에서 배운 것을 그대로 적용했다. 통합 테스트에서 `compact` 전달을 빼자
`assert 18 > 18` 로 실패한다 -- 단위 테스트는 압축기가 옳다는 것만 보이고,
이 테스트는 `assemble` 이 그것을 **실제로 넘긴다**는 것을 본다. 넘기지 않으면
기본값 `halve` 로 조용히 돌아간다.

### 표본 #16 실행 전 고정할 기대

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| F-1 | 조립의 고유 클레임 생존율이 #15 의 15% 에서 크게 오른다 | 실제 마커 분포가 재구성과 다르다 -- 분포를 재야 한다 |
| F-2 | 배달 리포트의 각주가 오른다 (#15 중앙값 2) | F-1 이 참인데 F-2 가 거짓이면 R-3 이 깨진 것이고, 작성자 쪽을 다시 봐야 한다 |
| F-3 | `primary_chars` 잔존은 거의 그대로다 | 크게 달라지면 압축기가 예산을 바꾼 것이고 수렴 특성이 변했다 |
| 무변 | `synth_pass` 12 · 조립 강등 0 · `exhausted` 0/N · 배달 6/6 · `job_failed` 0 | #13·#14·#15 가 세 번 연속 일치한 항목이다 |

게이트: **2502 passed / 16 skipped / 0 failed** (신규 5건).

## D63. 표본 #16 — D62 확인, 그리고 판정자의 불만이 옮겨갔다 (2026-08-12)

트리 `974909cb` · 사전 게이트 2502 passed / 16 skipped / 실패 0 · 아티팩트
`20260811T152942Z` · run `50fd36f1 4af2ffd4 ca8fd65c ea3357e8 73c172a0
d7d602ca`. 영수증 커밋은 `6031fe00` -- 표본 #15 와 같은 사유(다른 트랙 문서
커밋)이고 `neos/ tests/ config/ scripts/ pyproject.toml` diff 는 비어 있다.

### F-1 · F-2 · F-3 전부 확인

| | #15 | #16 |
|---|---|---|
| 조립 고유 클레임 생존 (중앙값) | 15% | **56%** |
| 조립 `primary_chars` 잔존 | 33% | **34%** |
| 배달 각주 (중앙값) | 2 | **8** |
| 배달 각주 (합) | 39 | **68** |
| 게이트 통과 | 0 | **1** |

**F-3 이 F-1·F-2 를 해석 가능하게 만든다.** 글자 잔존이 33% → 34% 로 사실상
같으므로, 클레임과 각주의 상승은 **압축기가 예산을 더 쓴 결과가 아니라 같은
예산에서 다른 글자를 남긴 결과**다. D62 가 주장한 그대로다.

각주는 6개 사례 **전부** 올랐다: 2→4, 4→11, 1→8, 3→9, 0→5, 29→31.

### R-3 은 깨지지 않았다

F-2 를 F-1 과 갈라 적은 이유가 이것이었다 -- 프롬프트에 클레임이 늘어도
작성자가 안 쓰면 소용없다.

| run | 조립 잔존 고유 클레임 | 배달 각주 |
|---|---|---|
| `4af2ffd4` | 11 | **11** |
| `ca8fd65c` | 8 | **8** |
| `73c172a0` | 5 | **5** |
| `d7d602ca` | 31 | **31** |
| `50fd36f1` | 5 | 4 |
| `ea3357e8` | 11 | 9 |

**네 건이 정확히 일치한다.** 작성자는 여전히 받은 클레임을 전부 쓴다.

### 게이트 통과 -- 진짜 판정자 승인

`4af2ffd4` 가 시도 0 에서 통과했다: `uncited_ratio` 0.0714, 주장 14개,
`judge=ran`. 폴백도 템플릿도 아니다.

### 판정자의 불만이 인용에서 커버리지로 옮겨갔다

이번 표본에서 가장 중요한 관측이다. `ca8fd65c` 의 시도 1 은
**`uncited_ratio` 0.0** -- 인용이 완벽한데 판정자가 반려했다:

> 루트 질문의 핵심 요소들을 다루지 않은 채 결론을 보류했고 …

`d7d602ca` 는 인용 품질을 **칭찬하면서** 반려했다:

> 제시된 개별 주장들은 출처로 적절히 뒷받침되고 과장 없이 한계를 투명하게
> 명시했다 … 랭킹 제어 비교와 벤치마크 방법론 평가 등 루트 질문의 핵심 요소가
> 미결로 남아 실질적 답변이 되지 못하지만

D51 이 남긴 두 불만은 "출처 품질" 과 "커버리지" 였다. **인용 층이 해결되면서
커버리지가 단독 지배 불만이 됐다.** 리포트 층에서 할 일은 이제 정말로 거의
없고, 남은 것은 조사 깊이다.

### 대가와 잡음 -- 정직하게

**본문이 짧아졌다.** LLM 작성 배달 본문 중앙값 3,964 → **3,106자**. 압축기가
산문을 먼저 버리니 프롬프트에 산문이 줄고 리포트도 짧아진다. 각주가 늘고
본문이 짧아진 거래이며, 판정자가 그것을 문제 삼지 않았다는 것이 지금까지의
증거다. 계속 볼 항목이다.

**`node_reduction` 클레임 생존이 100% → 89%(합 101 → 77)로 내렸다.** 압축기는
리덕션에도 배선돼 있으므로 무관하지 않을 수 있으나, 리덕션의 주 손실 기전은
secondary 항목 드롭이고(D61 의 전부-아니면-전무) 압축기는 거기 관여하지
않는다. 표본 간 변동일 가능성이 높지만 **확정하지 않는다.**

**`synth_pass` 가 12 → 11 이다.** 무변 위반이 아니다 -- `4af2ffd4` 가 시도
0 에서 통과해 재시도가 필요 없었다. 나머지 무변(조립 강등 0 · `exhausted`
0/11 · 배달 6/6 · `job_failed` 0 · `MISSING_QUESTION` 0 · 위생 0건)은 유지.

### 다음

리포트 층의 인용 문제는 닫혔다고 본다. 남은 판정자 불만은 **커버리지 하나**
이고, 그것은 조사 깊이 -- `max_depth` · `parallel_workers` · 하위 질문 채택
정책의 문제이지 조립의 문제가 아니다. S5(CI 결정론)도 여전히 미충족이다.

## D64. S5 착수 — CI 는 스위트의 47% 만 돌고 있었다 (2026-08-12)

### 먼저 정정: `-p no:randomly` 는 무동작이었다

표본 #10~#16 의 영수증에 이렇게 적었다:

> `-p no:randomly` 로 고정 순서 실행. S5(CI 결정론) 미충족이라 무작위 순서
> 동일성은 검증되지 않았다.

**`pytest-randomly` 는 이 프로젝트에 설치돼 있지 않다.** 설치된 pytest 플러그인은
`pytest-asyncio` 와 `pytest-cov` 뿐이고, `-p no:X` 는 없는 플러그인에 대해
조용히 아무 일도 하지 않는다.

결론("고정 순서로 돌았다")은 우연히 참이다 -- 무작위화 플러그인이 없으므로
pytest 는 수집 순서대로 돈다. 그러나 **내가 적은 기전은 존재하지 않았고**,
"무작위 순서 동일성은 검증되지 않았다" 는 문장은 검증할 무작위 순서 자체가
없다는 사실을 가렸다. 일곱 표본의 방법 기술이 그만큼 틀렸다.

측정 자체에는 영향이 없다(순서는 실제로 고정이었다). 기록만 정정한다.

### CI 는 2,518건 중 1,192건만 돌았다

| 영역 | 테스트 수 | CI |
|---|---|---|
| `tests/workflow` | 835 | ✅ |
| `tests/api` | 357 | ✅ |
| `tests/` 최상위 `*.py` | 492 | ❌ |
| `tests/coding` | 473 | ❌ |
| `tests/config` | 178 | ❌ (1 파일만) |
| `tests/unit` 외 9개 디렉터리 | 183 | ❌ |

**1,326건(53%)이 CI 에서 한 번도 돈 적이 없다.** S5 의 지배적 격차는 순서
의존이 아니라 **범위**였다.

### 그중 3건은 CI 에서 반드시 깨졌다

`.env` 를 숨기고 CI 환경 변수로 돌려 확인했다. 둘 다 **테스트가 환경을 정하지
않고 읽는** 문제다.

**`test_vision_factory_auto_selection`** 은 `create(AUTO)` 의 결과가 GPT4o 나
Claude 이기를 단언했다. 그것은 코드가 아니라 **그 기계에 어떤 키가 있는가**를
검사한다 -- OPENAI/ANTHROPIC 키가 없으면 팩토리는 옳게 `GeminiVision` 을
낸다. 이제 세 테스트로 갈라 각각 환경을 **설정하고** 검사한다.

**정제 테스트 2건**은 `create_tracked_llm` 을 패치했는데, 호출 지점이 전부
`create_tracked_llm(llm=create_llm(...))` 이라 **인자가 먼저 평가된다.** 그
패치는 실제 프로바이더 생성을 막은 적이 없고, 실제 `ANTHROPIC_API_KEY` 가
막고 있었다. 키가 없으면 `create_llm` 이 던지고 refiner 가 경고로 삼켜서
**엉뚱한 단언이 실패한다**(`call_count` 2 가 아니라 1). autouse 픽스처로 파일
전체에 걸었다 -- 다음 테스트가 같은 함정을 피하는 길이 작성자의 주의력뿐이면
안 된다.

### 가드를 두 번 썼다

`rest-tests` 잡을 더하고, `test_ci_workflow_covers_every_test_file` 이 세 잡의
합집합 = 디스크의 모든 테스트 파일임을 강제한다. **새 최상위 디렉터리 + 워크플로
수정 누락**이 정확히 이 53% 격차가 생긴 경로이기 때문이다.

첫 판은 워크플로 텍스트를 평탄화해 `pytest` 를 찾았고, **YAML 주석의 산문이
인자로 딸려 들어왔다** -- 내가 방금 쓴 한국어 주석의 `tests/` 한 토큰이 모든
파일을 "커버됨" 으로 만들었다. `rest-tests` 를 통째로 지워도 통과했다. YAML
파서가 주석을 지우게 고치니 154개 파일을 적발한다.

D58 · D60 · D62 에서 반복한 것과 같은 교훈이고, 이번에는 **가드를 쓴 그 자리에서**
음성 테스트를 먼저 돌렸다면 한 번에 끝났을 일이다.

### 결정론 -- 로컬 3회 연속 동일

```
run 1  2507 passed, 16 skipped in 260.13s
run 2  2507 passed, 16 skipped in 278.36s
run 3  2507 passed, 16 skipped in 263.73s
```

S5 의 완료 기준은 "**CI 에서** 3회 연속 동일" 이므로 이것으로 S5 를 충족했다고
적지 않는다. 로컬 3회는 필요조건이고, CI 에서의 확인은 워크플로가 실제로 도는
것을 봐야 한다. **범위는 이제 맞고**(가드가 강제한다), 남은 것은 CI 실행 관측
이다.

### 남은 것

- **순서 무작위화는 여전히 미검증**이다. 플러그인이 없으므로 순서는 결정론적
  이지만, 그것은 "순서에 의존하지 않는다" 와 다르다. `asyncio_default_test_
  loop_scope = session`(pytest.ini)은 순서 의존의 고전적 원천이고 아직 시험한
  적이 없다. 로드맵 CI #10 이 가리키던 것이 이것이다.
- CI #9(`tests/workflow` 전체 실행 미검증)는 **낡았다** -- 워크플로가 이미
  `pytest tests/workflow -q` 를 돈다.

## D65. 워커의 하위 질문 제안을 트리에 채택한다 (2026-08-13)

D11 이 M3 로, D13 이 M4+ 로 연기한 §6.3.2 채택을 구현한다.

### 왜 지금인가 -- 판정자 불만의 구조적 원인이다

표본 #16 에서 판정자 불만이 인용에서 **커버리지**로 옮겨갔다(D63). 그 커버리지
격차의 원인이 여기 있었다:

```python
for subq in result.proposed_subquestions:  # M3 연기: 로깅만
```

**고유 제안 161건이 버려졌고 실제 조사된 질문은 82건**이다. 그리고 버려진
것들이 판정자가 지적한 바로 그 축이다 -- `ca8fd65c` 는 "**PostgreSQL 코어
전문검색** … 을 다루지 않은 채" 로 반려됐는데, 같은 표본이 "PostgreSQL 17
공식 문서(Chapter 12. **Full Text Search**)" 를 제안해 두고 버렸다.

`d7d602ca`(default, `max_depth`=4)는 59건을 제안하고도 **깊이 1 에서 멈췄다.**
트리가 자라는 유일한 경로인 `_do_split` 은 워커의 제안을 보지 않고 LLM 에
처음부터 다시 묻는다 -- 실제로 수집한 증거에 근거한 제안을 버리고 재유도한다.

`subq_adopt_threshold` 는 config 에 정의만 되어 있고 **코드 어디에서도 쓰이지
않는 죽은 노브**였다.

### 원 설계에서의 이탈

§6.3.2 는 중복 병합과 상대 value 산정을 **독립 LLM 심사자**에게 맡긴다. 그
심사자가 D11·D13 두 번의 연기 사유였다(별도 프롬프트·검증·테스트 하네스).

여기서는 그것을 쓰지 않는다:

- **value_est 는 워커가 스스로 매긴다**(`worker_brief` v4). 자기 채점은 독립
  심사자보다 공정하지 않다. 대신 공짜다.
- **중복 제거는 결정론적**이다(`_normalize_question`: 공백 접기 + 소문자 +
  끝 문장부호). 의미 중복은 못 잡는다. 같은 질문을 글자만 바꿔 다시 조사하는
  것만 막는 값싼 하한이다.

이 이탈을 적어두는 이유는, 커버리지가 여전히 부족하면 **다음 후보가 원 설계의
심사자**이기 때문이다.

### 정책

| 축 | 값 | 근거 |
|---|---|---|
| 임계값 | `subq_adopt_threshold`(0.3) | 죽은 노브를 살린다 |
| 상한 | `_ADOPT_CAP`=4 | `_do_split` 과 같은 수. 넓이는 예산을 나눈다 |
| 깊이 | `max_depth` 준수 | — |
| 예산 | 부모 잔여 / (n+1) | 부모가 **계속 조사**하므로 자기 몫을 남긴다 |
| 부모 상태 | 건드리지 않는다 | — |

마지막 줄이 가장 중요하다. `record_split` 은 부모를 `split` 으로 전이시켜
**부모의 조사를 끝낸다.** 채택은 부모가 살아 있는 채로 가지를 더하는 일이므로
그것을 부르면 안 된다. `ledger.children()` 이 `parent_id` 로 조회하므로
`open_question` 만으로 트리는 성립한다. 테스트가 이것을 직접 주장한다.

### 표본 #17 실행 전 고정할 기대

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| G-1 | `subq_adopted` 이벤트가 발생하고 질문 수가 82건에서 오른다 | 워커가 임계값을 넘는 값을 안 매긴다 -- 프롬프트 문제 |
| G-2 | 깊이 2 이상이 나타난다(특히 default 프로파일) | 채택이 깊이를 못 만든다 |
| G-3 | 판정자의 "핵심 축 미확인" 반려가 준다 | 커버리지 격차의 원인이 제안 폐기가 아니었다 |
| **부작용 감시** | 자식이 늘면 조립 프롬프트가 커진다 -- clamp `exhausted`, `distinct_claims` 생존율, 배달 각주(중앙값 8)를 함께 본다 | D62 가 산 것을 채택이 도로 먹을 수 있다 |

마지막 줄이 이번 변경의 진짜 위험이다. 자식 수는 조립 입력의 1차 항이고,
D54~D62 가 그 압박과 싸운 기록이다.

게이트: **2517 passed / 16 skipped / 0 failed** (무작위 순서, 신규 10건).

## D66. 테스트 DB 부트스트랩이 `db/*.sql` 을 적용한다 (2026-08-14)

D64 가 CI 범위를 넓히자 세 건이 깨졌다(`create_conversation ... does not
exist`). 그때 그 **저장 함수 하나만** 떼어 만들었더니 다음 CI 는 한 층 아래에서
죽었다 -- `relation "conversations" does not exist`. 그것을 고치니 또 한 층
아래였다 -- `column "visibility" does not exist`(마이그레이션 008).

세 번의 실패가 같은 하나를 가리킨다. **`db_manager.initialize()` 는
`Base.metadata.create_all` 로 ORM 모델만 만들고, 테스트 부트스트랩은 `db/` 의
SQL 을 한 번도 적용한 적이 없다.** 채팅 스키마는 ORM 모델이 아니다.

### 왜 이제껏 초록이었나 -- 두 겹의 은폐

1. **정리 픽스처가 삼켰다.** conftest 의 `except Exception: print(...)` 안에서
   `DELETE FROM conversations` 가 CI 매 테스트마다 조용히 실패하고 있었다.
2. **개발 기계에는 손으로 적용해 둔 스키마가 있었다.** `db/README.md` 가 psql
   명령을 적어 두고 사람이 실행하는 방식이다.

즉 이 격차는 **CI 범위를 넓히기 전까지 관측될 수 없었다.** `.env` 의 실제 API
키를 읽던 테스트들과 같은 부류다 -- 테스트가 환경을 **정하지 않고 읽는다**.

### 결정

| 대상 | 조치 |
|---|---|
| `tests/conftest.py` | `chat_system.sql` + `db/migrations/*.sql` 를 세션당 한 번 적용. **스키마 적용 실패는 삼키지 않는다**(DELETE 만 관용) |
| `db/chat_system.sql` | 인덱스 28개 → `IF NOT EXISTS`, 트리거 6개 → `OR REPLACE`. 파일의 나머지는 처음부터 멱등했다 |
| `neos/database/connection.py` | `create_all` 직전에 `neos.database.models` 임포트 |
| CI 워크플로 | `CREATE EXTENSION vector` 인라인 3벌 → `scripts/enable_db_extensions.py`(`db/init.sql` 에서 읽는다). `pg_trgm` 이 빠져 있었다 |
| `tests/test_database_schema_bootstrap.py` | 신규 3건 |

`create_all` 앞의 임포트가 별건처럼 보이지만 아니다. `Base.metadata` 는 **모델
모듈이 임포트된 만큼만** 채워져 있어서, 신선한 DB 로 이 테스트들만 돌리면
테이블이 하나도 안 만들어지고 **조용히 성공한다**. 지금까지 안 터진 이유는 다른
코드가 우연히 먼저 임포트했기 때문이고 그건 보장이 아니다.

### 가드가 검사하는 것

`test_every_table_the_cleanup_fixture_deletes_from_exists` 는 정리 픽스처의 SQL
을 **conftest 소스에서 읽어** 그 테이블이 전부 있는지 본다. 목록을 손으로 들면
CI 커버리지 가드·Ruff 파일 목록과 똑같이 낡는다. 대소문자로 구분한다 -- SQL 은
`FROM`, 파이썬 임포트는 `from`.

### 범위 -- 반쯤 고치고 다 고쳤다고 하지 않는다

이것은 **배포 스키마의 재현이 아니다.** 신선한 DB 에 마이그레이션 44개를 순서대로
적용하면 7개가 실패한다:

| 사유 | 건수 |
|---|---|
| 다른 `db/*.sql` 이 만드는 테이블에 기댄다 (`hyper_research_reports`·`message_embeddings`) | 4 |
| pgvector 가 3072차원에 hnsw 인덱스를 못 만든다 | 1 |
| 스크립트 하나가 곧 암묵적 트랜잭션이라 `CONCURRENTLY`·자체 `BEGIN` 을 못 쓴다 | 2 |

그 7개는 테스트가 건드리지 않으므로 건너뛰고 `skipped_migrations` 에 남겨
출력한다. **배포 스키마 전체가 신선한 DB 에서 재현되지 않는다는 것은 별개의
실제 문제**이고 로드맵 §5.2.25 에 적었다.

검증: 빈 DB 를 만들어 CI 상태를 재현하고(`neos_ci_repro`) 확장 → 부트스트랩 →
대상 테스트 7건 통과를 확인했다. 중간 단계 두 번의 실패(`users`, `visibility`)도
같은 방법으로 관측한 것이다.

### 후속 — 부트스트랩이 켜지자 드러난 것 셋 (같은 날)

CI 를 다시 돌리니 `rest-tests` 는 통과하고 **초록이던 두 잡이 붉어졌다.** 셋 다
"마이그레이션이 적용된 적 없어서 안 보이던 것"이다.

**(1) `deep_analysis_runs` 를 지울 수 없다.** events 로 가는 FK 는 `ON DELETE
CASCADE` 인데 events 에는 UPDATE/DELETE 거부 트리거가 걸려 있다(036). 겹치면
**이벤트가 하나라도 있는 run 은 삭제 불가**다. `test_funnel_sample_runner_
integration` 의 정리가 여기 걸렸다 -- 트리거 없는 DB 에서만 통과하던 것이다.

원장이 append-only 인 것은 의도이므로 트리거를 손대지 않는다. 대신 **삭제 순간
에만** 끈다. 그냥 두면 안 되는 이유는 `deep_analysis_events` 가 로드맵 §5.2 수치
의 증거 테이블이기 때문이다 -- 테스트가 만든 가짜 run 이 남으면 증거가 오염된다.

> 스키마의 이 모순(cascade + 거부 트리거)은 테스트만의 문제가 아니다.
> **프로덕션에서도 run 은 삭제할 수 없다.** 대화 삭제·보존기한 요구가 생기면
> 여기서 걸린다. 이번 범위에서 고치지 않고 적어 둔다.

**(2) DB 없는 잡에서 스키마 적용이 터졌다.** 엔진 객체는 `create_all` 이 실패하기
**전에** 만들어진다. 그래서 초기화 실패 후 다음 호출이 `engine is None` 을
거짓으로 보고 초기화를 건너뛴 채 스키마 적용으로 직행했다. 실패 시 엔진을
`None` 으로 되돌린다. 아울러 `tests/config/test_test_environment_policy.py` 는
파일만 읽으므로 `no_db` 로 표시했다 -- `quality` 잡에는 postgres 서비스가 없다.

**(3) 건너뛰는 마이그레이션 집합은 기계마다 다르다.** 신선한 DB 는 7개(의존·
차원·트랜잭션), 이미 데이터가 있는 개발 DB 는 8개이고 사유가 다르다(대부분
"already exists", 036 은 기존 데이터의 FK 위반). **그래서 이 집합을 고정값으로
핀 박지 않는다** -- 그렇게 하면 기계에 따라 깨지는 테스트가 된다. 대신 결과를
검사한다(`test_database_schema_bootstrap.py`).

개발 DB 에 마이그레이션을 매 세션 적용하는 것이 안전한가 -- 확인했다.
`db/migrations/*.sql` 에 `DROP TABLE`·`DELETE FROM`·`TRUNCATE` 는 **없다**.

### 결과 — CI 네 잡이 처음으로 전부 초록 (`761f80d4`)

quality · workflow-tests · api-tests · rest-tests. **S5 는 1/3 이다** -- 기준이
"CI 에서 3회 연속"이므로 한 번으로 충족을 선언하지 않는다. `pytest-randomly`
때문에 남은 두 번은 같은 순서의 반복이 아니라 **서로 다른 순서**이고, 그것이
이 기준이 원래 재려던 것이다.

## D67. 표본 #17 판정 — 채택은 작동한다, 그러나 병목은 옮겨갔을 뿐이다 (2026-08-14)

아티팩트 `20260814T132904Z` · 트리 `6b27a711`(클린) · 사전 게이트 **2520 passed /
16 skipped**(시드 3532160910, 라이브 프로바이더 호출 0회) · run `f87ff15e
75e6fb01 cbf7e0c3 fa8cff42 9d9daa8b 07d83a6b`.

> **비교 가능성 주의.** #16 과 #17 은 dev 5건이 같지만 **default 프로파일의
> 사례가 다르다**(#16 `tech-hybrid-search`, #17 `tech-free-threading`) -- 러너가
> dominant stage 로 고른다. 그래서 합계(82 → 229)는 like-for-like 가 아니다.
> 아래는 **dev 5건만** 비교하고, default 는 따로 적는다.

### 사전 등록 대비

| # | 기대 | 판정 | 근거 (dev 5건) |
|---|---|---|---|
| G-1 | `subq_adopted` 발생 + 질문 수 상승 | ✅ **확인** | 채택 88건, 질문 **74 → 155** |
| G-2 | 깊이 2 이상 출현(특히 default) | ✅ **확인**, 단 기대가 부정확했다 | default 는 **깊이 1 → 4**. dev 는 2 → 2 인데 **그것이 dev 의 상한**이다(`dev_profile.max_depth=2`). #16 에도 깊이 2 는 이미 36건 있었으므로 "깊이 2 이상 출현"은 애초에 갈라내는 기대가 아니었다 |
| G-3 | "핵심 축 미확인" 반려 감소 | ❌ **반증** | 통과는 여전히 11건 중 1건. 에이전틱 반려 전부 `judge_answers_question=false` |
| 부작용 | clamp `exhausted` · 클레임 생존 · 각주 | ✅ **악화 없음** | `exhausted` 0 유지, 조립 클레임 생존 **0.575 → 0.730**, 배달 각주 중앙값 8.5 유지 |

부작용 감시가 이번 변경의 진짜 위험이었는데, **일어나지 않았다.** 자식이 두 배로
늘었는데도 조립 클램프는 더 많이 살렸다.

### G-3 이 말하는 것 -- 불만의 문구가 바뀌었다

| 표본 | 판정자의 말 |
|---|---|
| #16 | "…핵심 요소들을 **다루지 않은 채** 결론을 보류했고" |
| #17 | "…핵심 요구사항이 대부분 **'미확인'으로 남아** 루트 질문에 실질적으로 답하지 못하지만" |

**묻지 않아서 못 답하던 것이, 물었는데 확립하지 못하는 것으로 바뀌었다.**
dev 5건에서 질문은 2.1배가 됐는데 `resolved` 는 1 → 2 (0.9%)이고 `open` 이
74% → 86% 로 올랐다. 새로 생긴 `abandoned` 15건도 같은 방향이다. 그리고
**`claim_verified` 는 129 → 116 으로 오히려 줄었다**(6건 합계).

가설(단일 5+1 이므로 인과 주장 아님): 부모 잔여를 `n+1` 로 나누는 예산 정책이
넓이를 사는 대신 **자식 하나하나의 조사 깊이를 판다.** 넓이는 판정자가 세는
축이 아니다 -- 판정자는 축마다 **확립된 근거**를 요구한다.

### 새 실패 모드 -- run `9d9daa8b`

배달 리포트에 각주 0개, **원본 마커 `[C:...]` 32개**가 그대로 실렸다. W3-a 가
고쳤던 실패가 1/6 에서 돌아왔다. 경로는 명확하다: `E_ORPHAN_CITE`
(`orphan_claim_id=66cd381e`)로 시도 0·1 이 모두 반려 → 캡 소진 → `_finalize` 가
**렌더 전 draft** 를 반환.

그 클레임 id 는 **DB 어디에도 없다**(그 run 의 클레임 13건 중에도, 다른 run 에도).
조립기가 id 를 지어냈다. 채택이 이것을 더 흔하게 만드는지는 **이 관측으로 알 수
없다** -- #16 에는 없던 코드가 #17 에 나타났다는 사실만 기록한다.

### 다음

커버리지는 열렸고 **근거 확립이 새 병목**이다. 후보 둘:

1. **채택된 자식의 예산** -- `n+1` 균등 분할이 맞는가. 값(`value_est`)에 비례
   배분하거나, 채택 상한 `_ADOPT_CAP`=4 를 낮춰 깊이에 쓰는 쪽
2. **원 설계 §6.3.2 의 독립 심사자** -- D65 가 미룬 것. 자기 채점이 넓이를
   과대평가하고 있다면 여기가 값을 매기는 자리다

`E_ORPHAN_CITE` 는 별개로 봐야 한다 -- 조립기가 존재하지 않는 id 를 인용하는
것은 예산 문제가 아니다.

## D68. 채택 자식의 예산 정책과 §6.3.2 독립 심사자 — 손잡이 둘을 따로 단다 (2026-08-15)

표본 #17(D67)이 둘 다의 근거다. dev 5건에서 질문이 **74 -> 155** 로 늘었는데
`claim_verified` 는 **129 -> 116** 으로 줄었고, 채택 88건 중 `resolved` 는 2건,
새로 생긴 `abandoned` 가 15건이다. **넓이는 늘고 근거는 줄었다.**

판정자의 문구도 그 방향이다 -- "다루지 않은 채"(#16)에서 "'미확인'으로
남아"(#17)로 바뀌었다. 묻지 않아서 못 답하던 것이 **물었는데 확립하지 못하는
것**이 됐다.

### 왜 둘을 한꺼번에 켜지 않는가

§10.2 는 표본 하나가 변경 하나만 재게 한다. 그런데 이 둘은 **같은 수를 움직인다**
-- 심사자가 값을 다시 매기면 `value_weighted` 분배가 따라 바뀌고, 상한이 줄면
심사자가 병합할 대상도 줄어든다. 한 표본에 같이 넣으면 귀속이 불가능하다.

그래서 코드는 둘 다 넣되 **기본값을 표본 #17 이 측정한 동작 그대로** 둔다.
다음 표본들은 코드 변경 없이 노브만 돌려 하나씩 잰다.

| 노브 | 기본 | 무엇을 묻는가 |
|---|---|---|
| `subq_budget_policy` | `uniform` | 균등 분할이 깊이를 팔았는가 |
| `subq_adopt_cap` | 4 | 넓이 자체가 과한가 |
| `subq_reviewer_enabled` | `False` | 자기 채점이 넓이를 과대평가하는가 |

### 예산 분배 (`adopted_child_caps`)

순수 함수로 뺐다 -- 원장 없이 테스트할 수 있어야 이 정책을 실제로 비교할 수 있다.

두 정책 다 **부모 몫 하나를 먼저 뗀다**(`n + 1`). `_do_split` 이 `n` 으로
나누는 것은 거기서 부모가 `split` 로 끝나기 때문이고, 채택된 부모는 계속
조사한다 -- D65 가 정한 것이며 여기서 바꾸지 않는다.

`value_weighted` 는 자식 몫 총합(`share * n`)은 그대로 두고 **비율만** 바꾼다.
부모 몫을 건드리지 않는 것이 중요하다. 값이 전부 0 이면(옛 형태의 문자열 제안)
균등으로 떨어진다 -- 0 나눗셈을 피하려는 것이 아니라 그 경우 "값에 비례" 가
아무 의미도 없기 때문이다. 최소 1 토큰을 보장한다.

`_ADOPT_CAP` 상수는 **지웠다.** config 노브와 상수를 둘 다 두면 config 를
낮춰도 테스트는 옛 수를 계속 주장한다 -- CI 커버리지 목록·Ruff 파일 목록과
같은 실패 방식이다.

### 심사자 (`_review_subquestions` + `subq_review` v1)

D11 -> D13 -> D65 가 세 번 미룬 자리다. 워커와 다른 점은 **한 번에 전부 본다**는
것이다. 워커는 제안 하나하나에 절대값을 매기지만 예산은 상대적으로 갈린다.

두 가지를 설계에 박았다:

- **심사자는 인덱스로 말한다.** 텍스트를 되받아 적게 하면 그것이 곧 재작성이고,
  워커가 실제 증거에서 뽑은 문장이 심사 과정에서 조용히 바뀐다. 응답에 없는
  인덱스는 버려진 것으로 처리한다(의미 중복 병합의 결과).
- **실패는 삼킨다.** 심사자는 조사를 돕는 장치이지 관문이 아니다. 여기서 터져
  제안이 사라지면 D65 가 고친 손실이 그대로 되돌아온다. 대신
  `subq_review_failed` 를 남긴다 -- 조용히 원래 값으로 돌아가면 심사자가 도는지
  아닌지 알 수 없다.

`subq_reviewed` 는 `value_before`/`value_after` 평균을 함께 남긴다. **"심사자가
값을 올리기만 하는가"** 를 나중에 실측으로 물을 수 있어야 하기 때문이다 -- 값을
전부 올리는 심사자는 아무것도 심사하지 않은 것과 같다.

### 다음 표본에서 잴 것 (실행 전 고정하지 않았다)

이 커밋은 **기본 동작을 바꾸지 않으므로 표본을 소비하지 않는다.** 노브를 켤 때
그 표본의 사전 등록을 따로 쓴다. 순서 권고: `value_weighted` 먼저(코드 경로가
결정론적이고 호출이 늘지 않는다), 그다음 심사자(호출이 하나 늘어난다).

### 곁가지 — 게이트를 흔들던 간헐 실패의 진범 (같은 날)

D68 의 게이트를 돌리다 2026-08-14 의 간헐 실패가 **시드 3510494599 로 재현됐다.**
`tests/api/handlers/test_coding_ws_handlers.py` 의 2건이다.

원인은 전역 상태 오염이다:

```
test_production_requires_redis_and_selects_redis_adapters
  -> initialize_coding_transport(redis_client=object(), production=True)
  -> 모듈 전역 `coding_transport` 에 Redis 어댑터가 남는다
  -> 뒤의 웹소켓 테스트가 그것을 읽고 'object' has no attribute 'pubsub'
  -> 핸들러가 소켓을 닫으므로 증상은 anyio.EndOfStream
```

**간헐적이었던 이유가 정확히 설명된다.** 같은 파일의 뒤 테스트
(`test_development_explicitly_selects_in_memory_adapters`)가 전역을 in-memory 로
되돌려 놓는다. 무작위화가 production 테스트를 그 파일의 **마지막**에 놓을 때만
오염이 탈출한다. 파일 단독 실행으로는 영원히 보이지 않는다.

> **내 이전 가설은 틀렸다.** 표본 #17 영수증에 "폴루터는 아마
> `tests/test_multimodal_api.py`" 라고 적었다(루프 결함 때문에 죽은 루프에 묶인
> 엔진을 남긴다는 기전). 그 파일은 이미 고쳤는데도 실패가 났으므로 그 가설은
> 반증됐다. 영수증에 "재현하지 못한 실패를 고쳤다고 적지 않는다" 고 쓴 것이
> 이 정정을 가능하게 했다.

수정은 그 파일의 autouse 픽스처가 전역과 dispatcher publisher 를 되돌리는
것이다. 검증은 **고친 것을 증명하는 순서로** 했다:

| 실행 | 수정 전 | 수정 후 |
|---|---|---|
| 오염 테스트 1건 + 웹소켓 파일 | 2 failed | 12 passed |
| 전체 스위트, 시드 3510494599 | 2 failed | **2533 passed** |
| 전체 스위트, 새 시드 469283760 | — | 2533 passed |

S5 에 직접 걸린다 -- 이것이 `pytest-randomly` 도입(D64)이 **실제로 잡은 첫 결함**
이고, 3회 연속 초록을 세기 전에 나온 것이 다행이다.

## D69. 표본 #18 사전 등록 — `value_weighted` 예산 분배 (2026-08-15, 실행 전)

**이 항목은 표본을 돌리기 전에 커밋된다.** 판정은 여기 적힌 것에 대해서만 한다.

### 무엇을 바꾸는가 -- 하나만

`subq_budget_policy` 기본값을 `uniform` -> `value_weighted`. 그 외에는 아무것도
바꾸지 않는다. `subq_adopt_cap` 은 4 그대로, `subq_reviewer_enabled` 는 꺼진 채다
(그것은 다음 표본이다).

지문(`manifest.json`)에 `subquestions` 절을 더했다. 표본 #17 은 채택 정책이
지문에 없어서 **영수증만으로는 어떤 정책으로 돌았는지 알 수 없었다.**

### 왜 이것을 먼저 재는가

표본 #17(D67)의 진단은 "넓이는 늘고 근거는 줄었다"였다 -- dev 5건에서 질문
74 -> 155, `claim_verified` 129 -> 116, `resolved` 0.9%, 새 `abandoned` 15건.

`uniform` 은 잔여를 자식 수로 균등하게 나눈다. 그래서 워커가 "핵심 축" 이라고
0.9 를 매긴 질문과 곁가지라고 0.35 를 매긴 질문이 **같은 예산**을 받는다.
`value_weighted` 는 자식 몫 총합을 그대로 두고 비율만 바꾼다 -- 부모 몫은
건드리지 않으므로 트리의 모양이 아니라 **예산의 배분만** 달라진다.

심사자보다 먼저인 이유는 LLM 호출이 늘지 않기 때문이다. 결과를 예산 분배
하나에 귀속시킬 수 있다.

### 기대 (실행 전 고정)

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| **H-1** | `claim_verified` 가 표본 #17 의 dev 5건 116건에서 **오른다** <br>⚠️ *정정(D70): 116 은 dev 5건이 아니라 **6건 전체**의 수다. dev 5건은 **82** 다. 이 착오는 판정을 바꾸지 않는다 -- #18 은 두 기준 모두에서 내려갔다(65 / 99).* | 예산 배분이 병목이 아니다. 균등 분할이 깊이를 팔았다는 D67 의 가설이 틀렸다는 뜻이고, 그러면 되돌리고 심사자로 간다 |
| **H-2** | 값이 높은 가지가 실제로 더 깊이 판다 -- `subq_adopted` 의 `cap_tokens` 가 `value_est` 와 같은 방향으로 흩어진다(#17 은 형제끼리 전부 같은 값이었다) | 배선이 안 먹었거나 워커가 값을 고르게 매겨 비율이 균등과 같아진다. 후자면 **심사자가 정확히 그 문제**다 |
| **H-3** | `resolved` 비율이 0.9% 에서 오른다 | 예산을 몰아줘도 질문이 닫히지 않는다 -- 병목이 예산이 아니라 증거 수집·판정 쪽이다 |

**부작용 감시.** 예산을 몰아주면 낮은 값 가지는 굶는다. 최소 1 토큰은 보장되지만
그것은 "열리자마자 바닥" 이다.

- `investigation_stopped_at_floor` / `_at_input_bound` 가 늘어나는가 (#17: 2 / 4)
- `abandoned` 가 15건에서 더 느는가
- 조립 클레임 생존율(#17: 0.730)과 배달 각주 중앙값(#17: 8.5)이 내려가는가

굶은 가지가 늘면 H-1 이 참이어도 **순이득이 아닐 수 있다.** 셋을 함께 본다.

### 귀속 규칙

5+1 단일 관측이므로 인과를 주장하지 않는다. provider·검색결과·시각 변동성을
명시한다. 그리고 **default 프로파일 사례는 러너가 dominant stage 로 고르므로
표본마다 다를 수 있다** -- #17 에서 그것 때문에 합계 비교가 like-for-like 가
아니었다. 판정은 dev 5건으로 한다.

## D70. 표본 #18 판정 — `value_weighted` 반증, `uniform` 으로 되돌린다 (2026-08-15)

아티팩트 `20260814T173905Z` · 트리 `b6e5c74f`(클린) · 사전 게이트 **2533 passed /
16 skipped**(시드 2489483068, 라이브 호출 0회) · run `cafb9e75 284cf184 5f3ba328
531670d5 86a35b94 157a9365`(default=`157a9365`, fact-aspartame).

지문에 `subquestions: {budget_policy: "value_weighted", ...}` 가 남았다 -- D69 가
막은 구멍이며, 이제 영수증만으로 두 표본을 구분할 수 있다.

### 사전 등록 대비 (dev 5건)

| # | 기대 | 판정 | 근거 |
|---|---|---|---|
| **H-1** | `claim_verified` 상승 | ❌ **반증** | **82 -> 65** (6건 전체로도 116 -> 99) |
| **H-2** | 예산이 값에 따라 흩어진다 | ✅ **확인** | 형제 예산이 흩어진 그룹 **0/23 -> 21/22** |
| **H-3** | `resolved` 비율 상승 | ❌ **반증** | 1.29% -> 1.41% (2/155 -> 2/142). 절대 수가 같다 -- 노이즈다 |
| **굶주림** | 늘어나면 순이득이 아니다 | 🔴 **발동** | `abandoned` **15 -> 30** (두 배) |

### H-2 가 이 판정을 반박 불가능하게 만든다

보통 "안 좋아졌다" 는 두 가지로 갈린다 -- 기전이 안 먹었거나, 먹었는데 틀렸거나.
**H-2 가 그 갈림길을 닫았다.** 표본 #17 에서는 형제 23그룹 전부가 같은 예산을
받았고(`uniform`), #18 에서는 22그룹 중 21그룹이 서로 다른 예산을 받았다. 배선은
확실히 작동했고, 그 상태에서 결과가 나빠졌다.

### 무엇이 반증됐는가 -- 정확히

D67 의 가설은 "균등 분할이 넓이를 사면서 자식마다의 깊이를 팔았다" 였다. #18 은
그 반대편을 시험했고 **더 나빠졌다.** 따라서:

**워커의 `value_est` 는 어느 가지가 증거를 낼지 예측하지 못한다.** 값이 낮다고
예산을 덜 준 가지가 굶어 죽었고(`abandoned` 두 배), 값이 높은 가지에 몰아준
깊이는 검증된 클레임으로 돌아오지 않았다.

여기서 조심할 것이 있다. **워커가 값을 고르게 매긴 것이 아니다** -- 두 표본 모두
형제 그룹의 거의 전부에서 `value_est` 가 서로 달랐다(23/23, 21/22). 값은 흩어져
있었고, 다만 **그 흩어짐이 증거 수확과 상관이 없었다.**

### 부작용 상세

| 지표 | #17 | #18 |
|---|---|---|
| `abandoned` (dev) | 15 | **30** |
| 미해결 `open` (dev) | 125 | 97 |
| `_at_input_bound` / `_at_floor` | 3 / 2 | 4 / 1 |
| 조립 클레임 생존 | 0.730 | 0.797 |
| 리덕션 클레임 생존 | 0.753 | 0.708 |
| 배달 각주 중앙값 | 8.5 | **6.5** |

조립 생존율만 올랐는데 이것은 이득으로 읽지 않는다 -- 클레임이 애초에 적으면
클램프가 버릴 것도 적다. 배달 각주가 8.5 -> 6.5 로 내려간 것이 같은 사실의
사용자 쪽 얼굴이다.

**`E_ORPHAN_CITE` 는 재발하지 않았다**(raw marker 0/6). 표본 #17 의 1/6 이
이번에 안 나왔다는 것뿐이고, 고쳐졌다는 뜻이 아니다 -- 아무것도 고치지 않았다.

### 조치

사전 등록대로 **`uniform` 으로 되돌린다.** 되돌리는 것이 예정된 결과 중 하나였고,
그래서 이 표본은 낭비가 아니다 -- "예산 배분이 병목이 아니다" 를 알았다.

### 다음 -- 심사자의 질문이 바뀐다

D68-B 를 켤 때 재려던 것은 "자기 채점이 넓이를 과대평가하는가" 였다. #18 이 그
질문을 좁혔다:

- 값의 **흩어짐**은 이미 있다. 심사자가 만들 필요가 없다.
- 값을 **예산**에 쓰는 것은 반증됐다. 그러니 심사자를 켜도 예산 정책은
  `uniform` 이다.
- 남는 자리는 **채택 선별** 하나다 -- 임계값을 넘는지, 의미 중복인지. 심사자가
  값을 다시 매기는 효과는 "어느 질문이 트리에 들어오는가" 로만 나타난다.

그리고 #18 은 별개의 신호를 하나 줬다: `abandoned` 30건은 **연 질문의 21%** 다.
채택 상한(`subq_adopt_cap`=4)을 낮추는 쪽이 심사자보다 값싼 다음 후보일 수 있다.

## D71. 표본 #19 사전 등록 — 채택 상한 4 → 2 (2026-08-16, 실행 전)

**이 항목은 표본을 돌리기 전에 커밋된다.** 판정은 여기 적힌 것에 대해서만 한다.

### 무엇을 바꾸는가 -- 하나만

`subq_adopt_cap` 4 → 2. `subq_budget_policy` 는 `uniform` 그대로(D70 이 되돌린
값), `subq_reviewer_enabled` 는 꺼진 채다.

### 왜 이것인가

표본 #18 dev 5건에서 형제 그룹 22개 중 **20개가 정확히 4**였다. 상한이 거의
항상 구속하고 있다 -- 즉 이 노브는 현재 트리 넓이를 실제로 결정하는 값이다.

그리고 #18 이 남긴 신호가 넓이 쪽을 가리킨다: `abandoned` 가 연 질문의 21%
(#17 15건, #18 30건)다. 예산을 **어떻게 나누는가**(D70, 반증됨)가 아니라
**몇 갈래로 나누는가**를 이번에 잰다.

4 → 3 이 아니라 2 인 이유는 20개 그룹이 4에 걸려 있어 3 으로는 25% 밖에
줄지 않기 때문이다. 반토막이어야 판정이 선다.

### 비교 기준 -- #18 이 아니라 #17 이다

#18 은 `value_weighted` 였고 그것이 반증됐다(D70). #19 는 `uniform` + cap 2 이므로
**정책이 같은 #17(uniform + cap 4)** 과 비교해야 변경 하나만 남는다.

| 지표 | #17 (dev 5건) |
|---|---|
| `claim_verified` | 82 |
| `abandoned` | 15 |
| 질문 수 | 155 |
| `resolved` | 2 (1.29%) |
| 배달 각주 중앙값 | 8.5 (6건) |

### 기대 (실행 전 고정)

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| **I-1** | `claim_verified` 가 82 에서 **오른다** | 넓이를 줄여도 증거가 늘지 않는다 -- 병목이 채택 정책 전체가 아니라는 뜻이고, 그러면 남은 후보는 심사자(선별의 *질*)뿐이다 |
| **I-2** | `abandoned` 가 15 에서 **준다** | 굶는 가지가 상한 때문이 아니다 |
| **I-3** | 형제 그룹의 채택 수가 2 에 몰린다(#18 은 4에 20/22) | 배선이 안 먹었다 -- I-1·I-2 를 판정할 수 없다 |

I-3 이 D70 의 H-2 와 같은 역할이다: **기전이 먹었는데 나빠진 것**과 **기전이
안 먹은 것**을 갈라 놓는다. 이것 없이는 반증을 해석할 수 없다.

### 부작용 감시 -- 이번 변경의 진짜 위험

**커버리지가 되돌아올 수 있다.** D65 가 채택을 넣은 이유가 판정자의 "핵심 축을
다루지 않았다" 였고, 상한을 반토막 내는 것은 그 수정을 부분적으로 되돌리는
일이다. 함께 본다:

- 판정자 반려 사유에 "핵심 축 미확인" 계열이 **늘어나는가**
- 질문 수가 155 에서 얼마나 내려가는가 (절반이면 채택 이전 82 에 가까워진다)
- 배달 각주 중앙값(8.5)과 조립 클레임 생존율

I-1 이 참이어도 커버리지 불만이 늘면 **순이득이 아니다.** D65 와 D71 은 서로
반대 방향으로 당기는 노브이고, 이 표본은 그 사이 어디가 나은지를 묻는다.

### 귀속 규칙

5+1 단일 관측이므로 인과를 주장하지 않는다. default 프로파일 사례는 러너가
dominant stage 로 고르므로 표본마다 다를 수 있고, 판정은 dev 5건으로 한다.

## D72. 표본 #19 판정 — 넓이 축소도 반증, 되돌린다 (2026-08-17)

아티팩트 `20260816T103413Z` · 트리 `2eb2b43c`(클린) · 사전 게이트 **2938 passed /
23 skipped**(시드 3728141226, Redis 도달 불가 = CI 조건) · run `f56141a6 a8a1004e
c0ee282d b92fbac6 32b48966 b142481e`(default=`b142481e`).

### 사전 등록 대비 (dev 5건, 기준 #17)

| # | 기대 | 판정 | 근거 |
|---|---|---|---|
| **I-3** | 채택 수가 2 에 몰린다 | ✅ **확인** | 형제 그룹 **21개 전부 2** (#17 은 4에 19개, 3에 4개) |
| **I-1** | `claim_verified` 상승 | ❌ **반증** | **82 -> 74** |
| **I-2** | `abandoned` 감소 | ✅ 확인 | **15 -> 11** |
| **커버리지 감시** | 늘면 순이득 아님 | 🔴 **강하게 발동** | 통과 **1 -> 0**, 에이전틱 반려 **4 -> 6**(전부 `answers_question=false`), 배달 각주 중앙값 **8.5 -> 4.0** |

I-3 이 다시 갈림길을 닫았다 -- 기전은 완벽하게 작동했고 그 상태에서 나빠졌다.

### 세 표본이 같은 것을 말한다

| 표본 | 변경 | dev 질문 | `claim_verified` | 질문당 |
|---|---|---|---|---|
| #17 | 채택 도입(cap 4, uniform) | 155 | 82 | 0.53 |
| #18 | 예산을 값에 비례 | 142 | 65 | 0.46 |
| #19 | 넓이 반토막(cap 2) | 99 | 74 | **0.75** |

**넓이가 증거를 산다.** 넓이를 깊이와 바꾸려는 시도가 두 번 다 총 증거를 잃었다
(#18 예산 집중, #19 가지 축소).

다만 #19 는 한 가지를 새로 알려준다: **질문당 생산성은 0.53 -> 0.75 로 올랐다.**
자식이 둘이면 `n+1` 분할에서 각자 1.67배를 받고, 그만큼 더 캐낸다. 그런데
총합은 줄었다 -- 질문 수가 155 -> 99 로 더 크게 줄었기 때문이다.

즉 **효율과 총량이 반대로 움직인다.** 판정자가 세는 것은 총량 쪽이다("핵심 축을
다뤘는가"), 그래서 효율이 올라도 반려가 늘었다.

### 조치

사전 등록대로 **`subq_adopt_cap` 을 4 로 되돌린다.** 되돌림은 예정된 결과 중
하나였고, 이 표본은 "넓이 축소는 답이 아니다" 를 확정했다.

### 남은 후보가 하나로 좁혀졌다

D68-B 의 심사자다. 다만 **질문이 다시 바뀐다.** #18·#19 가 배제한 것:

- 값을 예산에 쓰는 것 (#18)
- 가지 수를 줄이는 것 (#19)

남은 것은 **같은 수의 가지를 더 잘 고르는 것**이다. 심사자를 켜되 `cap` 은 4,
`budget_policy` 는 `uniform` 그대로 두고, 심사자가 바꾸는 것은 오직 "어느 4개가
들어오는가" 여야 한다.

반대 방향(cap 을 4에서 **올리는** 것)도 이 세 표본과 모순되지 않는다 -- 넓이가
증거를 산다면 더 넓히면 더 살 수 있다. 다만 조립 프롬프트 압박(D54~D62)이
그 반대편에 있으므로 별도 사전 등록이 필요하다.
