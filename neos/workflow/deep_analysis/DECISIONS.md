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
2. **fail_run 내구성:** 하네스 실행이 실패하는 경로에서 노드의 `except` 블록이 `async with`
   세션을 커밋 없이 종료해, `fail_run()`이 기록한 상태 업데이트가 롤백될 수 있다. 반복되면
   `status="running"`으로 멈춘 고아 run 행이 누적된다. 활성화 전 실패 경로에서 run 상태를
   확실히 커밋하도록(별도 짧은 세션 또는 노드 레벨 명시적 commit) 고칠 것.
3. **분류기 intent 미도달:** `IntentType.DEEP_ANALYSIS`를 방출하는 쿼리 분류기가 아직 없어,
   현재는 복잡도 기반 분기만 라이브이고 intent 기반 라우팅 분기는 도달 불가능한 죽은 코드다.
   활성화 시점에 분류기에 해당 intent를 추가하거나, 미도달 분기를 정리할 것.
