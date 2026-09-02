# DECISIONS — 심층 분석 하네스 (NEOS 이식)

원 설계 [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../../docs/DEEP_ANALYSIS_HARNESS_DESIGN.md)와 충돌하거나
그 문서가 명시적으로 위임한 판단을 기록한다. 원 설계 §655 지시("구현 중 이 문서와 충돌하는 판단이
필요하면 §1의 5원칙으로 결정하고, 결정 내용을 코드 주석이 아니라 별도 DECISIONS.md에 기록") 및
부록 A6의 "DECISIONS.md 1번 항목" 요구를 이행한다.

각 결정은 **결정 / 근거 / 원 설계 대비 이탈 / 영향** 순으로 기술한다.

이 문서는 **두 파일로 나뉘어 있다.**

- **이 파일** — 지금 유효한 결정의 전문, 대체된 결정의 스텁, 그리고 표본·튜닝 이력의 요약.
- [`DECISIONS_ARCHIVE_2026-08.md`](DECISIONS_ARCHIVE_2026-08.md) — 요약된 항목의 **원문 그대로**. 한 항목의 원문은
  정확히 한 파일에만 있다(두 파일이 갈라지지 않게 하기 위해서다).

요약 항목은 제목 아래에 `📦` 표시와 원문 링크를 단다. 요약이 보존하는 것은
**사전 등록 가설 기호 · 확인/반증 판정 · 설정 수치 · 커밋 해시 · 표본 번호**다 —
표본 판정의 정본이자 백테스트 정답키로 쓰이는 값들이기 때문이다. 서사와 중간 추론은
아카이브에만 있다.

## 색인

| D | 제목 | 날짜 | 상태 |
|---|------|------|------|
| [**D1**](#d1) | aging 상태는 인메모리 (원 설계 A6이 요구한 1번 항목) |  | ✅ 유효 |
| [**D2**](#d2) | SQLite → PostgreSQL 이식, 단일 작성자(P2)는 앱 레벨 + advisory lock |  | ✅ 유효 |
| [**D3**](#d3) | claims UNIQUE는 `(run_id, hash)`로 스코프 (교차 오염 방지) |  | ✅ 유효 |
| [**D4**](#d4) | blobs — 파일시스템 → 테이블 (content-addressed) |  | ✅ 유효 |
| [**D5**](#d5) | 순수 LLM 콜러가 원 설계 llm.py를 대체 (LangChain 미사용) |  | ✅ 유효 |
| [**D6**](#d6) | fetch.py 신설 (link_follower 재사용 대신) |  | ✅ 유효 |
| [**D7**](#d7) | 실행 모델 — M1 인라인 SSE, Celery는 나중 (마이그레이션 리스크 2건 사전 기록) |  | ⛔ 대체됨 → [D22](#d22) |
| [**D8**](#d8) | events append-only를 Postgres DB 강제 불변식으로 승격 |  | ✅ 유효 |
| [**D9**](#d9) | blob도 워커 제안으로 반환하고 Ledger가 저장 |  | ✅ 유효 |
| [**D10**](#d10) | M1에서도 orphan 인용은 숨기지 않고 실패 |  | ✅ 유효 |
| [**D11**](#d11) | §6.3.2 서브질문 채택은 M3로 연기, M2는 로깅만 |  | ⛔ 대체됨 → [D65](#d65) |
| [**D12**](#d12) | SPLIT decompose는 주입 가능 함수로 분리 |  | ✅ 유효 |
| [**D13**](#d13) | §6.3.2 서브질문 채택은 M3에서도 재연기 — `subq_proposed` 로깅만 유지 |  | ⛔ 대체됨 → [D65](#d65) |
| [**D14**](#d14) | AgenticGrader — 판정 불가 시 "보류" 대신 미심사 통과(label=None) |  | ✅ 유효 |
| [**D15**](#d15) | 무진전 안전밸브 — 질문별 연속 무진전 라운드 상한 도달 시 강제 SPLIT/abandon |  | ✅ 유효 |
| [**D16**](#d16) | 충돌 "양론 병기"는 LLM 재요약이 아니라 결정론적 문구 삽입 |  | ✅ 유효 |
| [**D17**](#d17) | 계층 리듀스는 순차 후위 순회 — 같은 깊이 병렬은 후속 최적화로 연기 |  | ✅ 유효 |
| [**D18**](#d18) | 챗 편입 — 하네스는 단일 workflow 노드로 완주, per-claim SSE는 전용 엔드포인트 유지 |  | ⛔ 대체됨 → [D23](#d23) |
| [**D19**](#d19) | L5 개선 루프 — 관측/신호 + golden 게이트만, auto-mutation 없음 |  | ✅ 유효 |
| [**D20**](#d20) | 정지 판단(should_stop)은 aging 제외 base_score로 한다 |  | ✅ 유효 |
| [**D21**](#d21) | deep 엔진 라우팅은 complexity 임계값이 아니라 질의 유형으로 가른다 (R1 해소, D18 선결 조건 #3 해소) |  | ✅ 유효 |
| [**D22**](#d22) | durable job 서비스로 전환 — D7의 "나중"이 왔다 (3a: 제출·스트림·resume) |  | ✅ 유효 |
| [**D23**](#d23) | 챗은 job의 제출자다 — D18을 대체한다 (3b: 노드 제거·핸들 이벤트·리포트 영속화) |  | ✅ 유효 |
| [**D24**](#d24) | truncation은 D14 fail-open의 사유가 아니다 — judge 반려 |  | ✅ 유효 |
| [**D25**](#d25) | 마무리 floor를 중첩 계단으로 분할한다 |  | ✅ 유효 |
| [**D26**](#d26) | 정지 사유는 예산 상태가 정한다. 리포트 본문의 정본은 `job_completed`다. |  | ✅ 유효 |
| [**D27**](#d27) | 강등은 화면까지 간다. 새로고침 후 출처는 메시지 메타데이터다. |  | ✅ 유효 |
| [**D28**](#d28) | 거절은 사유를 안다. 그 사유는 예외가 운반한다. |  | ✅ 유효 |
| [**D29**](#d29) | W1 라이브 표본 — 마무리가 출력을 냈다. 이제 게이트가 문제다. |  | 📦 이력 · D30이 게이트 해석 정정 |
| [**D30**](#d30) | D29 의 게이트 해석 정정 — 게이트는 옳게 세고 있었다. |  | 📦 이력 |
| [**D31**](#d31) | 강등된 잎은 자기 클레임을 들고 나간다. 캡이 소진돼도 렌더된 것을 낸다. |  | 📦 이력 |
| [**D32**](#d32) | 아무것도 주장하지 않는 리포트는 만점이 아니라 전용 반려다 (D-2 확정). |  | 📦 이력 |
| [**D33**](#d33) | 레코드는 만들어지는 곳에서 영속화한다 (D1b). |  | 📦 이력 |
| [**D34**](#d34) | 조립도 잘리면 한 번 더 크게 시도한다 (W3-d). |  | 📦 이력 |
| [**D35**](#d35) | 계측은 계층마다 어댑터 하나로 (D1c 완료). |  | 📦 이력 |
| [**D36**](#d36) | 게이트는 인용 가능한 것만 채점한다 (W3-e·W3-f). |  | 📦 이력 |
| [**D37**](#d37) | 게이트를 통과한 첫 리포트 — S2 충족 (표본 #5). |  | 📦 이력 |
| [**D38**](#d38) | 통과율 1/6을 막던 것은 대부분 하네스였다 | 08-09 | 📦 이력 |
| [**D39**](#d39) | W3-j 캡 소진 시 어떤 초안을 배달하는가 | 08-09 | 📦 이력 |
| [**D40**](#d40) | 표본 #6 — W3 가 인용 문제를 옮겼고, 판정자가 병목이 됐다 | 08-09 | 📦 이력 · D43·D44가 진단 정정 |
| [**D41**](#d41) | 판정자가 왜 반려했는지를 원장에 남긴다 | 08-09 | 📦 이력 |
| [**D42**](#d42) | 판정자 몫을 조립이 못 건드리게 한다 — 세 번째 티어 | 08-09 | 📦 이력 |
| [**D43**](#d43) | 표본 #7 — D42 는 작동했고, 병목은 리포트 층 밖으로 나갔다 | 08-09 | 📦 이력 |
| [**D44**](#d44) | W3-k 한계 절을 렌더 전에 합친다 | 08-09 | 📦 이력 |
| [**D45**](#d45) | 1차 기관 출처를 실제로 수집한다 | 08-09 | 📦 이력 · D46이 수치 정정 |
| [**D46**](#d46) | 표본 #8 — D44·D45 확인, 그리고 커버리지 검사가 지배 사유가 됐다 | 08-09 | 📦 이력 |
| [**D47**](#d47) | W3-l 하네스가 질문 커버리지를 소유한다 + §6.8 위반 수정 | 08-09 | 📦 이력 |
| [**D48**](#d48) | 표본 #9 — W3-l·§6.8 확인, 그리고 품질 지표를 배달 기준으로 바꾼다 | 08-09 | 📦 이력 |
| [**D49**](#d49) | 한계 절이 원장에게 말하고 있었다 | 08-09 | 📦 이력 |
| [**D50**](#d50) | 본문 절단 — 죽은 재시도를 접어 조립 상한을 산다 | 08-09 | 📦 이력 |
| [**D51**](#d51) | 표본 #10 — 재시도가 살아나고 통과가 3건 | 08-09 | 📦 이력 · D53이 결론 정정 |
| [**D52**](#d52) | 후보를 재배열하는 대신 늘린다 + 재시도 힌트의 프레이밍 | 08-09 | 📦 이력 |
| [**D53**](#d53) | 표본 #11 — 증강은 되고, 재시도는 존재한 적이 없다 | 08-09 | 📦 이력 |
| [**D54**](#d54) | 강등 요약의 무한 이어붙이기, 그리고 clamp 밖의 루트 요약 | 08-09 | 📦 이력 |
| [**D55**](#d55) | 표본 #12 — 원인 진단이 맞았고, 재시도를 막는 것이 바뀌었다 | 08-10 | 📦 이력 |
| [**D56**](#d56) | 바닥이 절단 확장을 세게 한다 | 08-10 | 📦 이력 |
| [**D57**](#d57) | 표본 #13 — 재시도 루프가 처음으로 실재한다 | 08-10 | 📦 이력 |
| [**D58**](#d58) | 반토막을 볼 수 있게 한다 -- 고치기 전에 잰다 | 08-10 | 📦 이력 |
| [**D59**](#d59) | 표본 #14 — 병목은 순수하게 절삭이다, 그리고 내 계측이 반쯤 틀렸다 | 08-11 | 📦 이력 |
| [**D60**](#d60) | 자를 고친다 | 08-11 | 📦 이력 |
| [**D61**](#d61) | 표본 #15 — 리포트 층이 맞다, 그리고 작성자는 받은 것을 전부 쓴다 | 08-11 | 📦 이력 |
| [**D62**](#d62) | 마커 인지형 절삭 | 08-11 | 📦 이력 |
| [**D63**](#d63) | 표본 #16 — D62 확인, 그리고 판정자의 불만이 옮겨갔다 | 08-12 | 📦 이력 |
| [**D64**](#d64) | S5 착수 — CI 는 스위트의 47% 만 돌고 있었다 | 08-12 | 📦 이력 |
| [**D65**](#d65) | 워커의 하위 질문 제안을 트리에 채택한다 | 08-13 | 📦 이력 |
| [**D66**](#d66) | 테스트 DB 부트스트랩이 `db/*.sql` 을 적용한다 | 08-14 | 📦 이력 |
| [**D67**](#d67) | 표본 #17 판정 — 채택은 작동한다, 그러나 병목은 옮겨갔을 뿐이다 | 08-14 | 📦 이력 |
| [**D68**](#d68) | 채택 자식의 예산 정책과 §6.3.2 독립 심사자 — 손잡이 둘을 따로 단다 | 08-15 | 📦 이력 |
| [**D69**](#d69) | 표본 #18 사전 등록 — `value_weighted` 예산 분배 | 08-15 (실행 전) | 📦 이력 · D70이 기준 수치 정정 |
| [**D70**](#d70) | 표본 #18 판정 — `value_weighted` 반증, `uniform` 으로 되돌린다 | 08-15 | 📦 이력 |
| [**D71**](#d71) | 표본 #19 사전 등록 — 채택 상한 4 → 2 | 08-16 (실행 전) | 📦 이력 |
| [**D72**](#d72) | 표본 #19 판정 — 넓이 축소도 반증, 되돌린다 | 08-17 | 📦 이력 |
| [**D73**](#d73) | 해결 게이트를 워커에게 알려준다 + 그 수를 원장에 남긴다 | 08-18 | 📦 이력 |
| [**D74**](#d74) | 표본 #20 판정 — 그리고 세 표본이 실패한 진짜 이유 | 08-18 | 📦 이력 · D75가 원인 지목 정정 |
| [**D75**](#d75) | D74 의 원인 지목을 정정한다 -- 굶기는 것은 캡이 아니라 전역 예산이다 | 08-18 | 📦 이력 · D77이 수치 정정 |
| [**D76**](#d76) | S5 판정 -- CI 결정론은 닫혔다, 그리고 출하 기준이 6/6이 됐다 | 08-18 | 📦 이력 |
| [**D77**](#d77) | D75 의 곁가지 둘을 검정한다 -- 과대 예약은 병목이 아니다, 병목은 마무리 floor 다 | 08-18 | 📦 이력 |
| [**D78**](#d78) | D-11 결정 -- 마무리 floor 를 낮춘다. 예약 보증을 의도적으로 포기한다 | 08-19 | ✅ 유효 |
| [**D79**](#d79) | F1 판정 — 진단자는 미달이다. 그런데 미달의 절반은 계측이다 | 08-21 | 📦 이력 · D83이 헤드라인 정정 |
| [**D80**](#d80) | D79 를 정정한다 -- `questions.open`/`questions.resolved` 는 고칠 이름이 아니라 존재한 적 없는 필드였다 | 08-21 | 📦 이력 |
| [**D81**](#d81) | F1 재실행 — 계측을 채웠더니 더 나빠졌다. 그리고 그렇게 만든 것은 내 프롬프트다 | 08-22 | 📦 이력 |
| [**D82**](#d82) | F1 세 번째 측정 사전 등록 — 표본 창을 #6~#16으로 넓힌다 | 08-22 (실행 전) | 📦 이력 |
| [**D83**](#d83) | F1 판정 — 진단자는 표본을 읽지 않는다. F1 을 닫는다 | 08-22 | 📦 이력 |
| [**D84**](#d84) | H1 구성 매니페스트 -- 원장이 런의 구성을 답한다 | 08-22 | ✅ 유효 |
| [**D85**](#d85) | 표본 #21 실행 전 재확인 -- 사전 등록은 D78 그대로, 감시 항목 하나를 더한다 | 08-29 (실행 전) | ✅ 유효 |
| [**D86**](#d86) | 표본 #21 판정 -- L-1 확인. 확보한 토큰이 오차 0.08% 로 조사에 도달했다 | 08-29 | ✅ 유효 |
| [**D87**](#d87) | G3-m1 은 표본 경계가 아니었다 (백테스트) + 표본 #22 사전 등록 | 08-29 (실행 전) | ✅ 유효 |
| [**D88**](#d88) | D87 사전 등록 개정 -- 판정자를 `claude-opus-4-8` 로 | 08-30 (실행 전) | ✅ 유효 |
| [**D89**](#d89) | 표본 #22 판정 -- E3 배선은 확인됐고, M-1 의 임계값은 내가 잘못 설계했다 | 08-30 | ✅ 유효 |
| [**D90**](#d90) | 인용 생산 비율 -- 조립기가 가용 증거의 절반 이하만 쓴다 (백테스트) | 08-30 | ✅ 유효 |
| [**D91**](#d91) | 인용 생산 비율을 세 링크로 쪼갠다 -- 새는 곳은 `final_compose` 가 아니다 (백테스트) | 08-30 | ✅ 유효 |
| [**D92**](#d92) | CITE1 계측 -- 그리고 D91 의 원인 지목을 좁혀 다시 적는다 | 08-30 | ✅ 유효 |
| [**D93**](#d93) | 표본 #23 사전 등록 -- CITE1 후보 셋을 가른다 | 08-30 (실행 전) | ✅ 유효 |
| [**D94**](#d94) | D93 §7 개정 -- preflight 는 존재를 봤지 작동을 안 봤다 | 08-30 (실행 전) | ✅ 유효 |
| [**D95**](#d95) | Anthropic 클라이언트를 한 곳으로 -- identity-linked 키가 드러낸 사본 아홉 개 | 09-01 | ✅ 유효 |

---

<a id="d1"></a>

## D1. aging 상태는 인메모리 (원 설계 A6이 요구한 1번 항목)

**결정:** 점수 함수 `aging(q)`의 "마지막 선택 라운드"는 DDL/스키마에 저장하지 않고 Budgeter의 인메모리
상태(라운드 카운터 + `{qid: last_selected_round}` dict)로 구현.
**근거:** 원 설계 A6. aging은 기아 방지용 소프트 신호라 크래시 리셋이 무해.
**이탈:** 없음(원 설계가 명시 지시).
**영향:** Budgeter는 상태를 가지므로 M2에서 인스턴스 수명을 run 단위로 관리. (M1은 Budgeter 스텁이라 무영향.)

---

<a id="d2"></a>

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

<a id="d3"></a>

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

<a id="d4"></a>

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

<a id="d5"></a>

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

<a id="d6"></a>

## D6. fetch.py 신설 (link_follower 재사용 대신)

**결정:** 탐색(discovery)은 NEOS `web_search` 재사용, 검색(retrieval)은 신규 `fetch.py`.
**근거:** NEOS `link_follower`는 링크 추출용이라 A2/A3가 요구하는 HTML→텍스트(NFC)→blob+메타를
만족하지 못함. A3(대조 기준 텍스트 통일: 저장 원문 = 발췌 기준)를 지키려면 fetch 직후 변환을 1회
수행하고 그 텍스트를 blob에 저장해야 함.
**이탈:** 배관 소폭 중복(의도된 비용).
**영향:** `normalize_for_hash()`와 `normalize_for_match()`를 A3대로 다른 함수로 분리 유지.

---

<a id="d7"></a>

## D7. 실행 모델 — M1 인라인 SSE, Celery는 나중 (마이그레이션 리스크 2건 사전 기록)

> 📦 **요약** — 원문은 [아카이브 D7](DECISIONS_ARCHIVE_2026-08.md#d7)에 그대로 있다.

**대체됨 — D22가 갱신했다.** M1 수직 슬라이스를 요청 태스크 내 인라인 asyncio + SSE로 실행하고
Celery 이전을 "나중"으로 미룬 결정. D22에서 그 "나중"이 왔고, 실행은 durable job 서비스로 옮겨갔다.
D7이 사전 기록한 마이그레이션 리스크 2건의 최종 현황도 D22가 이어받는다 — 단일 작성자는 D2의
advisory lock으로 선제 해소, **Celery 하드 킬 시 partial 클레임 유실은 미해소**(손실 경계가
"라운드 하나"로 줄었을 뿐이다). 부수 리스크였던 nginx `proxy_read_timeout`은 D22에서 해소됐다.

---

<a id="d8"></a>

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

<a id="d9"></a>

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

<a id="d10"></a>

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

<a id="d11"></a>

## D11. §6.3.2 서브질문 채택은 M3로 연기, M2는 로깅만

> 📦 **요약** — 원문은 [아카이브 D11](DECISIONS_ARCHIVE_2026-08.md#d11)에 그대로 있다.

**대체됨 — D65가 뒤집었다.** 워커의 `proposed_subquestions`를 M2에서 채택하지 않고
`subq_proposed` 이벤트로 로깅만 하기로 한 연기 결정. D13이 M3에서 한 번 더 연장했고,
D65(2026-08-13)가 §6.3.2 채택을 실제로 켰다 — 표본 #16에서 판정자의 불만이 커버리지로 옮겨간 것이
그 계기다. 채택 정책의 정본은 D65이고, 그 위에서 예산 분배(D69·D70)와 넓이(D71·D72)를 잰 뒤
둘 다 반증돼 `uniform` + cap 4로 되돌아왔다.

---

<a id="d12"></a>

## D12. SPLIT decompose는 주입 가능 함수로 분리

**결정:** `_do_split`의 자식 생성 decompose를 `self._split_decompose(text, verified_summaries, dead_ends)` 시임으로 분리한다(기본=`_default_split_decompose`, LLM 호출). FakeWorker 계약 테스트는 이 속성을 sync/async 스텁으로 오버라이드해 LLM 없이 SPLIT 경로를 검증한다. `_ensure_root`/`_do_split` 두 decompose 호출부는 `_maybe_await`로 감싸 sync/async 스텁을 모두 허용한다.
**근거:** 원 설계 §10 "M2 AC 전부 FakeWorker로 재현". SPLIT은 LLM decompose를 호출하므로 주입점이 없으면 계약 테스트가 불가능. §6.3.1대로 decompose 입력에 verified 요약 + dead_ends를 포함한다.
**이탈:** 없음(테스트 가능성 위한 구조적 분리 + §6.3.1 충실).
**영향:** 프로덕션에서는 `_default_split_decompose`(LLM)가 쓰인다.

---

<a id="d13"></a>

## D13. §6.3.2 서브질문 채택은 M3에서도 재연기 — `subq_proposed` 로깅만 유지

> 📦 **요약** — 원문은 [아카이브 D13](DECISIONS_ARCHIVE_2026-08.md#d13)에 그대로 있다.

**대체됨 — D65가 뒤집었다.** D11의 연기를 M3에서 한 마일스톤 더 연장한 결정(M3의 세 AC 중
어느 것도 서브질문 채택을 요구하지 않는다는 근거). 채택은 D65에서 구현됐다.

---

<a id="d14"></a>

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

<a id="d15"></a>

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

<a id="d16"></a>

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

<a id="d17"></a>

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

<a id="d18"></a>

## D18. 챗 편입 — 하네스는 단일 workflow 노드로 완주, per-claim SSE는 전용 엔드포인트 유지

> 📦 **요약** — 원문은 [아카이브 D18](DECISIONS_ARCHIVE_2026-08.md#d18)에 그대로 있다.

**대체됨 — D23이 대체했다.** 하네스를 LangGraph 챗 워크플로우의 **단일 조건부 노드**로 편입해
`orch.run()`을 완주시키고 리포트만 상위로 반환하던 통합 방식. D23이 그 노드를 제거하고 챗을
job의 제출자로 바꿨다(디스패치 후 END 단락 + 전용 이벤트 스트림).

D18이 "프로덕션 활성화 전 선결 조건"으로 남긴 3건의 최종 상태:
(1) **wall-clock 바운드** → 노드 제거로 무의미해짐(D23), (2) **fail_run 내구성** → 코드리뷰 #5에서
해소된 뒤 노드와 함께 사라졌고 job 쪽 `_record_failure`가 역할을 이어받음, (3) **분류기 intent
미도달** → D21이 해소(질의 유형 기반 라우팅).

> 챗 편입의 변천을 따라 읽으려면 **D18 → D21 → D22 → D23** 순서다.

---

<a id="d19"></a>

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

<a id="d20"></a>

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

<a id="d21"></a>

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

<a id="d22"></a>

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

<a id="d23"></a>

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

<a id="d24"></a>

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

<a id="d25"></a>

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

<a id="d26"></a>

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

<a id="d27"></a>

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

<a id="d28"></a>

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

<a id="d29"></a>

## D29. W1 라이브 표본 — 마무리가 출력을 냈다. 이제 게이트가 문제다.

> 📦 **요약** — 원문은 [아카이브 D29](DECISIONS_ARCHIVE_2026-08.md#d29)에 그대로 있다.

- **표본 #1 (W1 라이브).** D25(마무리 예산 풀 분할)와 D28(거절 사유) 이후 처음 돌린 라이브 표본.
- **S1 충족:** `synth_pass` 18건 / 6 run(run당 3). 그 앞 574 run 동안 0이던 값이다.
  **S4 충족:** 6/6 run이 정지 이벤트를 **정확히 하나씩** 가진다. 가짜 양성 `synth_pass`는 0건.
- **미달:** `finalization_prompt_clamped` 관련 완료 기준 하나. 4/6 run이 child finding의 절반가량을 잃었다.
- **드러난 문제(W3/G3):** `report_graded`가 6/6 run에서 3회 전부 `ok=False`이고 `report_grading`
  예약은 0건 — **에이전틱 리포트 판정자가 한 번도 돌지 않았다.**
- **부수:** 이 표본부터 `execution_receipt.verification`으로 manifest 규율을 보강했다(`07790085`).
- ⚠️ **이 항목의 마지막 문단(게이트 해석)은 D30이 정정한다.**

---

<a id="d30"></a>

## D30. D29 의 게이트 해석 정정 — 게이트는 옳게 세고 있었다.

> 📦 **요약** — 원문은 [아카이브 D30](DECISIONS_ARCHIVE_2026-08.md#d30)에 그대로 있다.

- **정정 대상:** D29가 "본문에는 인용 마커가 다수 실려 있다"고 읽은 것. **게이트는 옳게 세고 있었다.**
- **재현:** 표본을 다시 돌리지 않고 `job_completed` 페이로드에 보존된 6개 리포트를 재분석했다.
- **실측:** 인용없음 비율 1.0인 세 run(`d74dcbe3`·`51fd8d7d`·`ea7e2f2e`)의 원본 `[C:]` 마커는 **0개**였다.
  마커가 있는 세 run은 6·8·60개였고 비율은 0.33·0.44·0.29.
- **진짜 사슬:** (1) LLM이 인용을 안 한다(3/6 run이 verified claim을 갖고도 마커 0개) →
  (2) 결정론 게이트가 18회 전부 반려 → (3) 에이전틱 판정자는 short-circuit으로 도달조차 못 한다.
- **교훈:** 저장된 본문에서 `[C:...]`를 보고 "인용이 실렸다"고 읽은 것이 오류였다. 렌더가 산출물까지
  살아남지 못했다는 증거다. **결과:** W3를 W3-a·W3-b… 갈래로 쪼갰다.

---

<a id="d31"></a>

## D31. 강등된 잎은 자기 클레임을 들고 나간다. 캡이 소진돼도 렌더된 것을 낸다.

> 📦 **요약** — 원문은 [아카이브 D31](DECISIONS_ARCHIVE_2026-08.md#d31)에 그대로 있다.

- **W3-a:** 캡 소진 경로가 렌더 **전** draft를 반환했다 → 렌더된 것을 반환하게 고쳤다.
- **W3-b:** `_degraded_summary`가 강등된 잎의 verified claim을 버렸다 → 강등된 잎이 자기 verified
  claim을 `[C:id] 텍스트`로 **결정론적으로 렌더**한다.
- **기각한 대안:** 강등 시 클레임 전문 대신 개수만 남기기 — 마커가 사라지는 문제를 그대로 둔다.
- **계보:** 이 진단의 출발점은 D28(거절 사유)이다.
- **남긴 것(W3-c):** "assertion 0건 리포트를 어떻게 채점할 것인가"(D-2) → D32에서 확정.

---

<a id="d32"></a>

## D32. 아무것도 주장하지 않는 리포트는 만점이 아니라 전용 반려다 (D-2 확정).

> 📦 **요약** — 원문은 [아카이브 D32](DECISIONS_ARCHIVE_2026-08.md#d32)에 그대로 있다.

- **표본 #2**(`20260808T023738Z`, 트리 `5ffe4d48`)로 W3-a·W3-b를 쟀다. **W3-a 확인** — 원본 `[C:]`
  마커가 0개인 run이 사라졌다.
- **새로 드러난 퇴화:** 18회 채점 중 **5회가 `assertions=0`으로 만점(0.00)** 을 받았고, 그중
  `a82648e3`의 최종 리포트는 **완전히 빈 문자열**이었다. 그것을 막은 것은 `E_REPORT_NO_LIMITS`였다.
- **결정(D-2 = 제3 판정):** `assertions == 0`이면 `E_REPORT_EMPTY`로 반려한다. `_uncited_stats`는
  그대로 0.0을 낸다 — **바뀐 것은 판정이지 측정이 아니다.**
- **함께 고친 것:** 빈 조립이 성공으로 세어지고 있었다.
- **미해결:** `report_grading` 예약이 두 표본 모두 0건. 판정자는 여전히 한 번도 돌지 않았다.

---

<a id="d33"></a>

## D33. 레코드는 만들어지는 곳에서 영속화한다 (D1b).

> 📦 **요약** — 원문은 [아카이브 D33](DECISIONS_ARCHIVE_2026-08.md#d33)에 그대로 있다.

- **문제(D1b):** 데이터셋 콜렉터의 영속화가 `graph.py`의 `_auto_save_dataset()` **한 곳**에서만 일어났다.
- **결정:** `add_record` 자체를 영속화 지점으로 만든다(`neos/dataset/record_sink.py`).
  **flush라는 개념이 사라지므로** 어느 프로세스에서 돌든 상관이 없다.
- **기각한 대안:** 배출구를 더 만드는 것(워커 teardown · job 완료 훅 · `atexit`).
- **검증:** 완료 기준이 "별도 프로세스에서 살아남는다"이므로 **실제 서브프로세스를 띄워** 확인했다
  (`test_a_separate_process_leaves_its_records_behind`). 모킹으로는 이 성질을 잴 수 없다.
- **남긴 것:** 메모리 리스트와 `_auto_save_dataset()`은 그대로 둔다.

---

<a id="d34"></a>

## D34. 조립도 잘리면 한 번 더 크게 시도한다 (W3-d).

> 📦 **요약** — 원문은 [아카이브 D34](DECISIONS_ARCHIVE_2026-08.md#d34)에 그대로 있다.

- **라이브 표본을 쓰지 않고**(저장된 리포트 재적용, 새 LLM 호출 0회) 게이트를 재확인했다.
  ① W3-c는 **라벨만 바꾼다**(5건이 `E_REPORT_NO_LIMITS` → `E_REPORT_EMPTY`).
  ② **인용 기준을 넘긴 시도가 처음으로 있었다** — `dd8dc763` #2가 `uncited_ratio` 0.1538 < 0.20으로
  통과하고도 `E_REPORT_NO_LIMITS`로 반려됐다.
- **근본 원인:** 조립 18회가 **전부** 상한에서 잘렸다(dev 1200 / default 4000).
- **결정(W3-d):** `call_text`를 신설한다(`llm.py`) — `call_json`의 확장 재시도와 같은 판단을 텍스트 경로에.
- **기각한 대안:** `synthesis_max_tokens` 상향 — D25가 세운 floor 계산을 침범한다.
- **다음 표본에서 볼 것:** `truncation_handled`가 0이 아닌지, `E_REPORT_NO_LIMITS`가 줄어드는지.
  **그때가 S2를 판정할 시점이다.**

---

<a id="d35"></a>

## D35. 계측은 계층마다 어댑터 하나로 (D1c 완료).

> 📦 **요약** — 원문은 [아카이브 D35](DECISIONS_ARCHIVE_2026-08.md#d35)에 그대로 있다.

- **결정(D-8 b안, D1c 완료):** `LLMCallRecord`를 정본으로 두고 **계층마다 어댑터를 하나씩** 둔다.
  배선 지점이 각 계층에 하나뿐이다.
- **계측을 전송 계층 밖에 둔 이유:** 프로바이더 구현(`model/anthropic.py`)을 건드리지 않기 위해서다.
- **두 어댑터가 공유하는 규율:** 절대 던지지 않는다 — 계측 실패는 데이터 문제이지 실행 실패가 아니다.
- **코딩 루프는 `ModelCompleted`에서만 기록한다** — usage를 싣고 오는 유일한 지점이다.
- **D1 전체가 닫혔다:** a(탈-LangChain `d9681104`) · b(쓰기-즉시 영속화 `29223829`) · c(이 결정).

---

<a id="d36"></a>

## D36. 게이트는 인용 가능한 것만 채점한다 (W3-e·W3-f).

> 📦 **요약** — 원문은 [아카이브 D36](DECISIONS_ARCHIVE_2026-08.md#d36)에 그대로 있다.

- **W3-e — 필수 절은 하네스가 소유한다(`d429403a`).** 조립 출력이 세 표본 54회 전부
  `## 한계와 미확인 사항`을 잃고 있었다. 하네스가 그 절을 직접 붙인다. **지어내지 않는다** —
  caveat이 없으면 "기록된 미확인 항목 없음"이라고 적는다. **결과(표본 #4):** 한계 절 1/6 → **6/6**,
  `E_REPORT_NO_LIMITS` 1 → **0**.
- **W3-f — 그 분모를 열어보니 인용 불가능한 것이 섞여 있었다(`c12b3f07`).** 두 가지를 고쳤다.
  **임계값 조정이 아니라 채점 대상의 정정이다.** 인용없음 중앙값이 **0.185**로 내려간다.
- **W3-e가 W3-f를 드러냈다** — 한계 절이 항상 존재하게 되자 그 절의 불릿이 매번 분모에 들어왔다.
- **표본 #4 재적용(새 LLM 호출 0회): 3/6이 임계값을 통과한다**(기록 기준 0/6).
  **정확한 판정은 다음 표본이 한다.**
- **남은 것:** `bb8a2dbb`는 마커가 0개다. 판정자는 여전히 한 번도 돌지 않았다.

---

<a id="d37"></a>

## D37. 게이트를 통과한 첫 리포트 — S2 충족 (표본 #5).

> 📦 **요약** — 원문은 [아카이브 D37](DECISIONS_ARCHIVE_2026-08.md#d37)에 그대로 있다.

- **아티팩트:** `artifacts/deep-analysis-funnel/20260808T140346Z`(트리 `c58a15bc`). **표본 #5.**
- **세 가지 최초가 한 표본에서 일어났다.** ① 게이트를 통과한 첫 리포트, ② **에이전틱 판정자가
  돌았다**(`report_grading` 예약 5건 — 네 표본 연속 0건이었다), ③ 새 반려 사유 2종
  (`E_REPORT_AGENTIC` = 판정자가 실제로 반려).
- **W3-f가 예측대로 작동했다** — 저장된 리포트 재적용이 예측한 "3/6이 임계값 아래"가 그대로 나왔다.
- **정직한 한계:** 통과 run이 **1개(n=1)** 다. 단일 관측으로 인과를 주장하지 않는다.
- **출하 기준:** S1·S2·S3·S4·S6 충족, **S5(CI 결정론)만 남았다** → D64·D76.

---

<a id="d38"></a>

## D38. 통과율 1/6을 막던 것은 대부분 하네스였다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D38](DECISIONS_ARCHIVE_2026-08.md#d38)에 그대로 있다.

- **맥락:** S2 충족 뒤 통과율 자체(1/6)를 봤다.
- **측정:** 전체 원장 273회 채점 중 `E_REPORT_UNCITED`가 **250회(91.6%)** 다. 표본 #5 카세트로
  홉별 마커 생존율도 쟀다.
- **드러난 하네스 결함 셋.** 통과율을 막던 것은 모델이 아니라 대부분 하네스였다.
- **부재 진술을 어떻게 다룰지 — 채점기가 아니라 프롬프트.** (a)안을 골랐다. 한계 절은 `_report_body`가
  이미 채점에서 빼고 있으므로 새 예외를 만들지 않는다.
- **골든 관문 둘이 이 변경을 붙잡았고 둘 다 제 일을 했다**(프롬프트 버전 bump).
- **아직 열린 것:** 효과는 **측정되지 않았다** — 표본 #6이 있어야 한다.

---

<a id="d39"></a>

## D39. W3-j 캡 소진 시 어떤 초안을 배달하는가 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D39](DECISIONS_ARCHIVE_2026-08.md#d39)에 그대로 있다.

- **문제:** 재시도가 전부 반려되면 `_finalize`는 **마지막** 초안을 내보냈다. 표본 #5의 `94b0483c`는
  더 나은 초안을 갖고도 그것을 버렸다.
- **정한 규칙(W3-j):** 게이트 자신의 측정만 쓰는 **3단 사전식**으로 배달 초안을 고른다.
- **함정은 대체로 도달 불가능하다** — 게이트를 통과한 초안은 반환되므로 `rejected`에 들어오지 않는다.
- **표본 #5 실패 5건 검산: 3건 개선, 2건 동일, 악화 0건.**
  예) `94b0483c` .208/48주장 → **.095/42**, `d8cda7c5` .250/12 → **.235/17**.

---

<a id="d40"></a>

## D40. 표본 #6 — W3 가 인용 문제를 옮겼고, 판정자가 병목이 됐다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D40](DECISIONS_ARCHIVE_2026-08.md#d40)에 그대로 있다.

- **맞은 것:** W3-g는 예측대로 작동했다 — 인용없음 비율 중앙값 **0.222 → 0.105**.
- **틀린 것 둘을 기록해 둔다** — 결과를 보고 이야기를 맞추지 않기 위해 기대를 실행 전에 고정했다.
- **병목이 옮겨갔다.** 지배적 반려가 인용(11/18)에서 **에이전틱 판정자**로 이동했다. 그리고
  **통과 2건은 모두 `judge=budget_exhausted`** — 판정자가 완주하지 못한 폴백 통과다(표본 #5의
  유일한 통과도 같았다). **게이트 통과 여부가 판정자의 잔여 예산에 좌우된다.**
- **즉시 고친 것:** `E_ORPHAN_CITE` 3건이 원장 역사상 처음 나타났다.
  ⚠️ 이때의 진단은 **틀린 분기를 고쳤고 D43이 정정한다**(진짜 원인은 D44).
- **다음 과제:** 판정자가 지배적 실패 사유가 됐는데 **원장에 사유가 없다** → D41.

---

<a id="d41"></a>

## D41. 판정자가 왜 반려했는지를 원장에 남긴다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D41](DECISIONS_ARCHIVE_2026-08.md#d41)에 그대로 있다.

- **왜 지금:** 표본 #6에서 에이전틱 판정자가 지배적 반려 사유가 됐다(D40).
- **무엇을 남기는가:** 산문보다 **두 불리언이 먼저다**(`strength_ok`·`answers_question`) + **승인 표식**.
- **승인 표식이 핵심인 이유:** 승인이 아무 표식도 남기지 않으면 원장에서 "판정자가 돌아서 승인했다"와
  "판정자가 아예 못 돌았다"가 **바이트 단위로 구별되지 않는다.** 통과가 "리포트가 좋다"인지
  "판정자가 예산을 못 받았다"인지 읽을 수 없다.
- **모델 산문을 페이로드에 넣는 것:** 이 채점기의 no-raw 불변식은 **가져온 원문(blob)** 에 대한
  것이므로, 렌더된 리포트에 대한 판정자 rationale은 허용된다.
- **드러난 것:** 이 변경으로 깨진 테스트가 **하나도 없었다** — 판정자 진단을 확인하는 테스트가
  애초에 없었다는 뜻이고, 그래서 세 개를 새로 붙였다.

---

<a id="d42"></a>

## D42. 판정자 몫을 조립이 못 건드리게 한다 — 세 번째 티어 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D42](DECISIONS_ARCHIVE_2026-08.md#d42)에 그대로 있다.

- **원인:** `report_grading`이 이미 가장 안쪽 티어인데도 조립 재시도가 그 층을 말렸다. 그래서
  **게이트는 실제로 배달되는 초안에서 가장 관대해진다** — 판정자가 시도 0·1을 반려하며 예산을 태우고
  마지막 시도에서 굶는다. 원장의 게이트 통과 3건이 전부 같은 모양이었다.
- **표본 #6 실측:** 남은 예산 < 판정자 프롬프트. `953ee89e` 3,555 vs 8,529 · `c716f31c` 7,822 vs 8,329 ·
  `741e94cf` 9,443 vs 16,345.
- **고친 것:** `GRADING_STAGES`를 **가장 안쪽 티어**로 두고, `grading_floor_tokens`는 **한 번의 판정**만
  감당하게 잡았다(`truncation_retry_multiplier`가 식에 들어간 이유는 판정 한 번이 실제로는 최대 두
  번이기 때문이다). 검산: **dev 13,600 / prod 41,600**.
- **대가는 실재하고 의도한 것이다.** dev 최종화 층 41,040 중 13,600을 판정자가 가져가므로
  **조립이 더 자주 열화한다.** 판정받은 짧은 리포트가 판정 못 받은 긴 리포트보다 낫다는 거래다.

---

<a id="d43"></a>

## D43. 표본 #7 — D42 는 작동했고, 병목은 리포트 층 밖으로 나갔다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D43](DECISIONS_ARCHIVE_2026-08.md#d43)에 그대로 있다.

- **D42 확인:** `judge=budget_exhausted` 1 → 2 → **0**, `judge=ran` **8건**. 판정자가 도달한 모든
  경우에 실제로 돌았다. **판정자가 승인한 첫 리포트**(`9e5492eb` 시도 0, `ok=True, judge=ran`).
- **통과 수 2 → 1은 예측한 결과다** — 폴백 통과가 사라지고 진짜 통과가 하나 남았다.
- **청구서도 예측대로:** 조립 열화 1 → **6건**, 인용없음 중앙값 0.105 → 0.183.
- **D41이 처음으로 말해준 것:** 판정자 반려 분해에서 `strength_ok=False` **7건** → D45의 계기.
- **정정:** D40의 `E_ORPHAN_CITE` 진단은 **틀린 분기를 고쳤다** → 진짜 원인과 수정은 D44.

---

<a id="d44"></a>

## D44. W3-k 한계 절을 렌더 전에 합친다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D44](DECISIONS_ARCHIVE_2026-08.md#d44)에 그대로 있다.

- **원인(D43의 정정에서 이어짐):** 한계 절을 `CitationRenderer` **이후에** 합치는데 `node_summary.md`가
  "모든 사실 주장에 마커를 붙이라"고 지시하므로, 그 절의 마커가 렌더되지 않은 채 남아
  `E_ORPHAN_CITE`가 났다. `03dd8ddd`·`ba84c409`의 관측된 모양까지 설명된다.
- **고친 것(W3-k):** 한계 절을 초안에 **먼저 합치고 그 다음 렌더한다.**
- **안전한가:** caveat이 참조하는 클레임은 렌더 가능해야 한다 — 표본 #6·#7로 확인했다.
- **부수 효과:** 절 순서가 **본문 → 한계 → 출처**로 바뀐다.
- **D40의 `orphan_claim_id`는 남겨둔다** — 지금까지 관측된 실패를 하나도 못 보게 되는 것은 아니다.

---

<a id="d45"></a>

## D45. 1차 기관 출처를 실제로 수집한다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D45](DECISIONS_ARCHIVE_2026-08.md#d45)에 그대로 있다.

- **왜:** D41이 판정자 반려를 분해하자 지배적 사유가 `strength_ok=False`(2차 비공식 출처)였다.
- **측정:** 표본 #7의 증거 URL 119건(고유 36) 중 tier1은 **19건(16%)**.
  ⚠️ 이 16%는 **옛 목록으로 잰 값**이며 D46이 정정한다.
- **결함 둘을 고쳤다.** **tier는 검색 순위를 대체하지 않는다** — `sorted`가 안정 정렬이므로 같은
  tier 안에서는 검색 순위가 그대로 유지된다.
- **아직 재지 않았다.** 효과는 표본 #8에서 본다. 기대: tier1 비율 상승 + `strength_ok=False` 감소.
  오르지 않으면 문제는 검색 쪽이다.

---

<a id="d46"></a>

## D46. 표본 #8 — D44·D45 확인, 그리고 커버리지 검사가 지배 사유가 됐다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D46](DECISIONS_ARCHIVE_2026-08.md#d46)에 그대로 있다.

- **수치 정정:** D45의 "표본 #7 tier1 16%"는 **옛 목록**으로 잰 값이었다.
- **확인된 것 둘**(D44·D45). **그런데 통과가 1 → 0이다.**
- **새 지배 사유:** `E_REPORT_MISSING_QUESTION` **5건**. 왜 지금 터졌는지가 중요하다 — resolved 자식
  질문이 #7은 6 run에 1개뿐이라 검사가 사실상 비활성이었다.
- **W3-i는 절반만 통했고 그 절반이 어디인지 측정됐다** — 합성기는 질문의 의문문만 옮긴다.
- **클램프 가설은 반증됐다** — #8 최종화 클램프 39건 < #7 42건, `dropped_primary` 0.
- **결론: 축자 대조를 그만둬야 한다** → D47. **새 하드 실패:** `8817a935`(token budget).

---

<a id="d47"></a>

## D47. W3-l 하네스가 질문 커버리지를 소유한다 + §6.8 위반 수정 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D47](DECISIONS_ARCHIVE_2026-08.md#d47)에 그대로 있다.

- **W3-l — 축자 대조를 그만둔다.** 질문 텍스트는 128~213자짜리 지시문("…원문에서 …을 확인하라")인데
  합성기는 **의문문만 옮기고 지시문은 버린다.** 축자 대조는 이 격차를 실패로 읽는다.
- **값싼 대안은 측정이 기각했다** — 의문문 부분만 대조하는 안은 실패한 질문까지 통과시킨다.
- **그래서 하네스가 소유한다** — `## 출처`(CitationRenderer)와 한계 절(W3-e)이 이미 그런 것처럼,
  질문 커버리지 절도 하네스가 직접 만든다.
- **§6.8 위반 수정:** `_finalize`의 충돌 재조사 라운드가 `_run_round()`로 **진짜 워커를 돌린다.**

---

<a id="d48"></a>

## D48. 표본 #9 — W3-l·§6.8 확인, 그리고 품질 지표를 배달 기준으로 바꾼다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D48](DECISIONS_ARCHIVE_2026-08.md#d48)에 그대로 있다.

- **확인된 것 넷.** 그중 **게이트가 판정자 층으로 복귀**: `judge=ran` 1 → 5(#8에서는 결정론 검사가
  먼저 막아 판정자에게 닿지도 못했다).
- **실행 전에 건 반증 조건이 걸렸다** — "인용없음 중앙값이 오르면 커버리지 절이 분모를 키운 것".
  **제외는 정상이었다**(커버리지 절을 가진 유일한 리포트에서 절이 분모에서 빠진 것을 확인).
- **틀린 것은 지표다.** 채점 이벤트 집계는 **사용자에게 가지 않는 초안까지** 센다.
- **결정: 앞으로 리포트 품질은 배달된 리포트로 읽는다.**
  #7 배달 6 · 중앙값 0.122(최악 0.455) / #8 5 · 0.000(1.0) / #9 6 · 0.130(**0.30**).
- **남은 병목:** 시도 0이 판정자에게 반려되고(`E_REPORT_AGENTIC` 4건), 그 뒤 재시도가 쓸 조립 예산이 없다.

---

<a id="d49"></a>

## D49. 한계 절이 원장에게 말하고 있었다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D49](DECISIONS_ARCHIVE_2026-08.md#d49)에 그대로 있다.

- **어떻게 발견했나:** 표본 #9의 판정자 반려 사유를 읽었다(D41이 없었으면 불가능했다).
  > "다수의 '미확인'·**'input_bound'** 항목이 남아 실질적 종합이 이루어지지 …"
- **`input_bound`는 내부 강등 사유 문자열이다** — `node_reduction_degraded`의 것이 리포트 본문으로 샜다.
- **두 가지가 동시에 잘못됐다.** ① 독자에게 기계 토큰을 보여준다, ② 판정자가 그것을 근거로 반려한다.
- **고친 것:** `_collect_caveats`가 경계다 — 원장 어휘가 리포트 내용이 되는 지점에서 번역한다.
- **원장 쪽 문자열은 건드리지 않는다.** D28이 정지 사유를 기계가 읽을 수 있게 만든 것을 유지하고,
  바꾸는 것은 **독자에게 보여줄 때뿐**이다.

---

<a id="d50"></a>

## D50. 본문 절단 — 죽은 재시도를 접어 조립 상한을 산다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D50](DECISIONS_ARCHIVE_2026-08.md#d50)에 그대로 있다.

- **증상:** 표본 #9의 판정자 반려 4건 중 **3건**이 "본문이 중간에 끊겼다"였다.
- **측정 셋 → 고친 것 셋이 한 방향이다**(죽은 재시도를 접어 조립 상한을 산다).
- **층 검산:** dev 41,040 → **48,000(48%)**, `finalization_floor_warn_ratio` 조정.
- **정직한 크기:** 프롬프트 v4가 되찾는 출력은 전체의 **2.4%** 뿐이다.
- **테스트를 설정에서 읽게 바꿨다** — `assemble_calls == 3`처럼 캡을 하드코딩하던 것을 걷어냈다.
- **아직 재지 않았다.** 효과는 표본 #10에서 본다.

---

<a id="d51"></a>

## D51. 표본 #10 — 재시도가 살아나고 통과가 3건 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D51](DECISIONS_ARCHIVE_2026-08.md#d51)에 그대로 있다.

> ⚠️ **아래 굵은 두 결론은 틀렸다. D53(표본 #11)이 정정한다** — 시도 1은 LLM 조립을 받은 적이 없다.

- **가장 진단적이었던 기대가 확인됐다**(실행 전에 "시도 1이 시도 0과 **다른** 숫자를 낸다"로 고정).
- **재시도가 처음으로 교정에 성공했다(→ 정정됨).** `917bc008` 시도 0 `E_REPORT_UNCITED` 0.263 →
  시도 1 **0.000 / 주장 36개로 판정자 승인**. D53이 이것을 **강등 템플릿의 승인**으로 정정한다.
- **지표:** 게이트 통과 #8 0 → #9 1 → **#10 3**, 배달 본문 중앙값 1,678 → **3,386자**,
  `- input_bound` 줄 51 → **0**.
- **확인된 것:** D50-3(본문 두 배), D50-2(판정자의 "끊겼다" 지적 소멸).
- **부분 확인:** `report_assembly` 절단 13 → 10건, 여전히 절단의 71%.
- **남은 판정자 불만 둘:** 출처 품질(공식 EU 출처 대신 2차 비공식)과 커버리지(루트 질문의 핵심 축 미확인).

---

<a id="d52"></a>

## D52. 후보를 재배열하는 대신 늘린다 + 재시도 힌트의 프레이밍 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D52](DECISIONS_ARCHIVE_2026-08.md#d52)에 그대로 있다.

- **쿼리 증강 — D45는 절반만 고쳤다.** 후보를 재배열하는 대신 **늘린다**. 계측:
  `WorkerResult.search_augmentation` → `pass_completed`의 `search_*`(무엇을 찾았는지 / 그중 무엇을
  실제로 fetch했는지).
  **반증 조건(실행 전 고정):** 표본 전체에서 `added_tier1` 합이 0이면 평문 키워드 증강은 작동하지 않는다.
- **재시도 힌트 — 프레이밍이 내용만큼 무겁다.** 코드에서 확인한 원인 후보: **`assemble`은 직전
  초안을 받지 않는다.** 직전 초안 전문을 프롬프트에 넣는 방법은 **택하지 않았다**.
  **반증 조건(실행 전 고정):** 시도 1의 주장 수가 시도 0을 넘지 않아야 한다.

---

<a id="d53"></a>

## D53. 표본 #11 — 증강은 되고, 재시도는 존재한 적이 없다 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D53](DECISIONS_ARCHIVE_2026-08.md#d53)에 그대로 있다.

- **A. 쿼리 증강 — 확인.** fetch된 tier1이 반사실 165 → **242(+47%)**, 증강만 찾은 tier1 후보 **153**.
  **A-1·A-2 확인**(평문 키워드 증강은 작동한다).
- **A-3 반증 — 1차 출처를 fetch하는 것과 그것을 인용하는 것은 다르다.** 판정자의 출처 품질 불만은
  그대로다(`strength_ok=False` 4건).
- **B. 재시도 힌트 — 측정 무효, 그리고 D51 정정.** **시도 1은 LLM 조립을 받은 적이 없다** —
  6개 run 전부 강등 템플릿이었다. `917bc008`의 "재시도가 통과를 만든 첫 사례"는 **강등 템플릿이
  승인받은 것**이고, #10의 "통과 3건 중 판정자 승인 2건"은 **LLM 작성 리포트에 대한 승인 1건**으로
  읽어야 한다.
- **진짜 병목:** clamp이 자식 요약을 전부 버리고도 허용량을 못 맞춘다 —
  **루트 요약 혼자 허용량을 1.3~2.4배 초과한다** → D54.

---

<a id="d54"></a>

## D54. 강등 요약의 무한 이어붙이기, 그리고 clamp 밖의 루트 요약 (2026-08-09)

> 📦 **요약** — 원문은 [아카이브 D54](DECISIONS_ARCHIVE_2026-08.md#d54)에 그대로 있다.

- **원인:** `_degraded_summary`의 join이 **무계**였다. 강등된 부모가 강등된 자식을 이어붙이고,
  자식의 답 자체가 또 그런 join이라 크기가 누적된다.
- **방어:** join을 유계로 만들고, **루트 요약(앵커)을 clamp 대상에 넣는다**(그동안 clamp 밖에 있었다).
- **재현 측정:** 이전 `exhausted=True` / 조립 프롬프트 생존 마커 **0 / 70** →
  D54 후 `exhausted=False` / **21 / 70**.
- **표본 #12 사전 등록:** C-1 조립 clamp `exhausted` 비율 하락 · C-2 `dropped_primary` 중앙값 하락 ·
  **C-3 `report_assembly_degraded` 감소 = 시도 1이 처음으로 LLM 조립을 받는다**(반증 시: 재시도를
  막는 것은 입력 크기가 아니라 예산 계층) · C-4 `answer_truncated=True` 관측(0이면 원인 진단이 틀렸다).

---

<a id="d55"></a>

## D55. 표본 #12 — 원인 진단이 맞았고, 재시도를 막는 것이 바뀌었다 (2026-08-10)

> 📦 **요약** — 원문은 [아카이브 D55](DECISIONS_ARCHIVE_2026-08.md#d55)에 그대로 있다.

- **C-4 확인 — 원인 진단이 맞았다.** 잘린 6건의 강등 join 원본은 3,483~**7,379자**(중앙값 3,978),
  안 잘린 26건은 중앙값 **172자**.
- **C-1·C-2·C-5 확인(강함).** 조립 clamp `exhausted` #11 12/12 → **0/11**, `dropped_primary` 중앙값
  7 → **0**, `bound_after` 중앙값 9,716 → **5,880**(허용 6,000), 앵커 반토막 11/11.
  **자식 요약이 더는 버려지지 않는다.**
- **C-3 부분 확인 — 그리고 막는 것이 바뀌었다.** 재시도를 막는 것은 이제 입력 크기가 아니라
  **예산 계층**이다(C-3의 반증 조항이 예고한 그대로) → D56.
- **B-1·B-2 여전히 측정 불가(n=1).** 통과 1건(진짜 판정자 승인).
- **정직하게:** LLM 작성 배달이 #10 4/6 → #11 5/6 → **#12 3/6**, 각주 중앙값 12 → 7 → **2**.

---

<a id="d56"></a>

## D56. 바닥이 절단 확장을 세게 한다 (2026-08-10)

> 📦 **요약** — 원문은 [아카이브 D56](DECISIONS_ARCHIVE_2026-08.md#d56)에 그대로 있다.

- **무엇이 틀렸나:** 마무리 바닥(floor)이 절단 확장 재시도를 세게 막고 있었다.
- **고친 것:** `grading_floor_tokens`가 판정자에 대해 이미 하던 것과 **같은 교정을 조립에** 적용한다.
- **값을 치른 곳:** dev `global_token_cap` **100,000 → 140,000**. 실제 토큰을 더 쓰지만
  **바닥에 닿는 run에서만이다.**
- **표본 #13 사전 등록:** E-1 `report_assembly_degraded`가 #12의 4건에서 크게 감소 ·
  **E-2 `synth_pass` > run 수**(= 재시도가 여러 run에서 LLM 조립을 받는다) ·
  B-1 시도 1의 `uncited_assertions`가 시도 0을 넘지 않음 · B-2 `uncited_ratio` 악화 감소 ·
  **E-3 LLM 작성 배달 리포트의 각주 중앙값이 #12의 2에서 회복** · 무변(`job_failed` 0 · 배달 6/6 ·
  clamp `exhausted` 0 · 쿼리 증강 유지).

---

<a id="d57"></a>

## D57. 표본 #13 — 재시도 루프가 처음으로 실재한다 (2026-08-10)

> 📦 **요약** — 원문은 [아카이브 D57](DECISIONS_ARCHIVE_2026-08.md#d57)에 그대로 있다.

- **E-1·E-2 확인 — 이 프로젝트가 여덟 표본 동안 못 하던 일.** `synth_pass` #11 6 → #12 7 → **#13 12**,
  `report_assembly_degraded` 6 → 4 → **0**, run당 조립 예약 **{4:6}**, clamp `exhausted` **0/12**.
  **재시도 루프가 도입 이래 처음으로 완전히 실재한다**(D53이 "한 번도 존재한 적 없다"고 적은 그것).
- **B-1 확인(5/6) — 힌트의 길이 앵커가 통한다.** 예) `8bd975a7` 19 → **7**, `ca1f02e5` 12 → **7**.
- **B-2 반증(1/6)** — 그리고 실패의 모양이 바뀌었다.
- **E-3 반증 — 각주는 회복되지 않았다.** LLM 작성 배달은 **6/6**(#12는 3/6이 결정론 템플릿)으로
  개선됐지만 각주 중앙값은 **2 그대로**.
- **원인을 확정하지 못했고, 그 이유가 관측 구멍이다** — 앵커 682 → 304자(50% 잔존)인데
  `dropped_primary` 0. **다음 수는 고치는 것이 아니라 재는 것이다** → D58.

---

<a id="d58"></a>

## D58. 반토막을 볼 수 있게 한다 -- 고치기 전에 잰다 (2026-08-10)

> 📦 **요약** — 원문은 [아카이브 D58](DECISIONS_ARCHIVE_2026-08.md#d58)에 그대로 있다.

- **왜 안 보였나:** 지금 계측으로는 "반토막"이 어디서 일어나는지 가를 수 없다.
- **두 층으로 잰다.** **크기** — `ClampResult`에 `primary_chars_before/after`.
  **인용** — 합성기에서 `[C:xxxxxxxx]` 마커 수. **프롬프트에 살아남은 마커 수가 리포트가 가질 수 있는
  인용의 상한**이다.
- **도구가 실제로 가르는지 확인했다.** (a) 마커가 자식에 있을 때 70 → 21(30%) · anchor 잔존 25%,
  (b) 마커가 앵커(강등 join)에 있을 때 70 → **3(4%)** · anchor 잔존 **3%**. 두 가설이 다른 값을 낸다.
- **표본 #14 읽는 법(사전 등록):** `claim_markers_after`가 낮다 → 절삭 정책 /
  anchor 잔존이 primary보다 훨씬 낮다 → (b) /
  마커는 높은데 각주가 낮다 → **작성자 프롬프트 문제(R-3)** /
  `node_reduction` 손실이 크다 → **리덕션 층이 먼저다(R-4)**.

---

<a id="d59"></a>

## D59. 표본 #14 — 병목은 순수하게 절삭이다, 그리고 내 계측이 반쯤 틀렸다 (2026-08-11)

> 📦 **요약** — 원문은 [아카이브 D59](DECISIONS_ARCHIVE_2026-08.md#d59)에 그대로 있다.

- **불변이 완전히 일치한다** — 표본 간 변동이 작다는 것을 처음으로 확인했다(그전까지는 표본 하나로 판정해 왔다).
- **R-3 반증(강함) — 작성자는 받은 마커를 거의 다 쓴다.** 프롬프트 잔존 마커 → 배달 각주:
  7→5 · 2→2 · 2→2 · 4→4 · 1→0 · 21→17. **거의 1:1이다.** 각주가 적은 이유는 작성자가 안 써서가
  아니라 **프롬프트에 마커가 없어서**다. 병목은 순수하게 절삭이다.
- **후보 (b) 배제 — 앵커가 마커 운반체는 아니었다.** 잔존 중앙값 primary **36%** vs anchor **50%**.
- **(a)는 부분 지지, 그러나 설명이 부족하다** — 마커가 블록 안에서 균등 분포가 아니고, 어디에 몰려
  있는지 모른다.
- **내 계측의 결함 둘(정직하게):** ① `node_reduction`의 `markers_before`가 불완전해 **R-4는 판정
  불가**다, ② `len(findall(...))`는 **출현 횟수**이고 각주는 **고유 클레임** 수다 → D60.

---

<a id="d60"></a>

## D60. 자를 고친다 (2026-08-11)

> 📦 **요약** — 원문은 [아카이브 D60](DECISIONS_ARCHIVE_2026-08.md#d60)에 그대로 있다.

- **셋을 고쳤다(둘이 아니라).** ① `node_reduction`의 `before`가 `child_lines`를 빠뜨렸다,
  ② 출현 횟수를 셌다(`CitationRenderer`는 몇 번 인용되든 클레임당 각주 하나다),
  ③ **조립의 `before`가 `caveats`를 빠뜨렸다** — D59가 못 본 세 번째다.
- **이름을 바꿨다.** 의미가 달라졌으므로 키를 유지하면 표본 #14의 출현-횟수 값과 이후 값이 섞인다.
- **테스트를 두 번 고쳤다.** 계측기를 만들 때 "동작하는지 확인"은 통과를 보는 것이 아니라
  **실패해야 할 때 실패하는지**를 보는 것이다 — 결함을 되살려 둘 다 잡히는 것을 확인했다.
- **표본 #15는 다시 관측이다:** `node_reduction`의 `after/before`가 낮다 → **R-4**(리덕션 층이 먼저) /
  리덕션은 높은데 조립이 낮다 → 리포트 층이 맞다 / 조립의 `distinct_claims_after`가 각주와 1:1 →
  R-3 반증이 고유 기준으로도 유지.

---

<a id="d61"></a>

## D61. 표본 #15 — 리포트 층이 맞다, 그리고 작성자는 받은 것을 전부 쓴다 (2026-08-11)

> 📦 **요약** — 원문은 [아카이브 D61](DECISIONS_ARCHIVE_2026-08.md#d61)에 그대로 있다.

- **영수증 커밋이 사전 등록과 다르다**(등록 `4f7a4828`) — 기록해 둔다.
- **불변 — 세 표본 연속 완전 일치.**
- **R-4 반증 — 리덕션 층이 주범이 아니다.** 고유 클레임 생존율 중앙값:
  `node_reduction` **100%**(184 → 101) vs `report_assembly` **15%**(208 → 78).
  **리포트 층이 맞다** — D54·D56·D58이 올바른 무대를 손댔다는 것이 처음으로 확인됐다.
- **R-3 재확인 — 고유 기준으로 더 깨끗하다.** 조립 프롬프트 잔존 고유 클레임 → 배달 각주가
  **다섯 건 정확히 일치**(2→2 · 4→4 · 1→1 · 3→3 · 0→0, 34→29).
  **작성자는 받은 클레임을 전부 쓴다. 각주 수는 절삭이 남긴 것과 같다.**
- **남은 격차:** **절삭이 글자보다 클레임을 빠르게 없앤다**(두 표본에서 관측). **새 관측:** 리덕션의
  전부-아니면-전무. → 고치는 방법은 원인과 무관하게 같다: **절삭이 마커를 인지하게 만든다**(D62).

---

<a id="d62"></a>

## D62. 마커 인지형 절삭 (2026-08-11)

> 📦 **요약** — 원문은 [아카이브 D62](DECISIONS_ARCHIVE_2026-08.md#d62)에 그대로 있다.

- **무엇이 틀렸나:** primary 글자 잔존 대비 고유 클레임 생존이 훨씬 낮다 —
  표본 #14 36% vs **9%**, 표본 #15 33% vs **15%**.
- **고친 것:** **마커 인지형 절삭.** 클램프의 수렴 특성은 그대로이고 **바뀌는 것은 어느 글자를
  남기는가뿐이다.** 수렴을 정책의 선의에 걸지 않도록 구조로 보장했다.
- **효과(표본 #15 규모 재구성).** 허용량 6,000(dev 실제)에서 `halve` 16클레임(38%)/글자 32% →
  **D62 38클레임(90%)/글자 37%**. 9,000에서는 21(50%) → **42(100%)**.
  **글자 잔존은 사실상 같은데 클레임은 2~3배 남는다.** 압박이 셀수록 격차가 커진다.
- **테스트가 실패해야 할 때 실패하는지 확인했다.**
- **표본 #16 사전 등록:** F-1 조립 고유 클레임 생존율이 15%에서 크게 상승 · F-2 배달 각주 상승
  (#15 중앙값 2) · F-3 `primary_chars` 잔존은 거의 그대로 · 무변(`synth_pass` 12 · 조립 강등 0 ·
  `exhausted` 0/N · 배달 6/6 · `job_failed` 0).

---

<a id="d63"></a>

## D63. 표본 #16 — D62 확인, 그리고 판정자의 불만이 옮겨갔다 (2026-08-12)

> 📦 **요약** — 원문은 [아카이브 D63](DECISIONS_ARCHIVE_2026-08.md#d63)에 그대로 있다.

- **F-1·F-2·F-3 전부 확인.** 조립 고유 클레임 생존 중앙값 15% → **56%**,
  `primary_chars` 잔존 33% → **34%**, 배달 각주 중앙값 2 → **8**(합 39 → 68), 게이트 통과 0 → **1**.
  **F-3이 F-1·F-2를 해석 가능하게 만든다** — 글자 잔존이 사실상 그대로이므로 이득은 압축기가 예산을
  더 쓴 것이 아니라 **어느 글자를 남겼는가**에서 나왔다.
- **R-3은 깨지지 않았다** — 네 건이 정확히 일치(11→11 · 8→8 · 5→5 · 31→31).
- **판정자의 불만이 인용에서 커버리지로 옮겨갔다** — `uncited_ratio` **0.0**인데 판정자가 반려했다.
- **대가와 잡음(정직하게):** LLM 작성 배달 본문 중앙값 3,964 → **3,106자**,
  `node_reduction` 클레임 생존 100% → **89%**, `synth_pass` 12 → 11(무변 위반은 아니다).
- **결론: 리포트 층의 인용 문제는 닫혔다.** 남은 판정자 불만은 **커버리지 하나** → D65.

---

<a id="d64"></a>

## D64. S5 착수 — CI 는 스위트의 47% 만 돌고 있었다 (2026-08-12)

> 📦 **요약** — 원문은 [아카이브 D64](DECISIONS_ARCHIVE_2026-08.md#d64)에 그대로 있다.

- **먼저 정정:** `-p no:randomly`는 **무동작**이었다 — `pytest-randomly`가 이 프로젝트에 설치돼 있지
  않다. 측정 자체에는 영향이 없다(순서는 실제로 고정이었다).
- **CI는 2,518건 중 1,192건만 돌았다.** 도는 것: `tests/workflow` 835 · `tests/api` 357.
  안 도는 것: `tests/` 최상위 492 · `tests/coding` 473 · `tests/config` 178 · 그 외 183.
  **1,326건(53%)이 CI에서 한 번도 돈 적이 없다** — S5의 지배적 격차는 순서가 아니라 범위였다.
- **그중 3건은 CI에서 반드시 깨졌다.** `.env`를 숨기고 CI 환경 변수로 확인 —
  **테스트가 환경을 정하지 않는** 부류(`test_vision_factory_auto_selection`)와, `create_tracked_llm`을
  **엉뚱한 지점에 패치**한 정제 테스트 2건.
- **가드를 두 번 썼다.** **결정론:** 로컬 3회 연속 동일(필요조건이며, CI 확인은 D76이 한다).

---

<a id="d65"></a>

## D65. 워커의 하위 질문 제안을 트리에 채택한다 (2026-08-13)

> 📦 **요약** — 원문은 [아카이브 D65](DECISIONS_ARCHIVE_2026-08.md#d65)에 그대로 있다.

- **왜 지금인가 — 판정자 불만의 구조적 원인이다.** 표본 #16에서 불만이 커버리지로 옮겨갔고(D63),
  원장을 보니 **고유 제안 161건이 버려졌고 실제 조사된 질문은 82건**이다. 버려진 것들이 판정자가
  지적한 바로 그 축이었다(`ca8fd65c`의 "PostgreSQL 코어…").
- **원 설계에서의 이탈:** D11·D13이 M2·M3에서 두 번 연기했던 §6.3.2 채택을 켠다.
- **정책:** 임계값 `subq_adopt_threshold`(0.3, 죽은 노브를 살린다) · 상한 `_ADOPT_CAP`=4
  (`_do_split`과 같은 수) · `max_depth` 준수 · 예산 **부모 잔여/(n+1)**(부모가 계속 조사하므로 자기
  몫을 남긴다) · 부모 상태는 건드리지 않는다.
- **표본 #17 사전 등록:** G-1 `subq_adopted` 발생 + 질문 수가 82건에서 상승 · G-2 깊이 2 이상 출현 ·
  G-3 판정자의 "핵심 축 미확인" 반려 감소 ·
  **부작용 감시** 자식이 늘면 조립 프롬프트가 커진다(clamp `exhausted` · 클레임 생존율 · 배달 각주
  중앙값 8) — **D62가 산 것을 채택이 도로 먹을 수 있다.**

---

<a id="d66"></a>

## D66. 테스트 DB 부트스트랩이 `db/*.sql` 을 적용한다 (2026-08-14)

> 📦 **요약** — 원문은 [아카이브 D66](DECISIONS_ARCHIVE_2026-08.md#d66)에 그대로 있다.

- **왜 이제껏 초록이었나 — 두 겹의 은폐**가 스키마 미적용을 가리고 있었다.
- **결정:** `tests/conftest.py`가 `chat_system.sql` + `db/migrations/*.sql`을 세션당 한 번 적용하고
  **스키마 적용 실패는 삼키지 않는다**(DELETE만 관용). `db/chat_system.sql`은 인덱스 28개
  `IF NOT EXISTS` · 트리거 6개 `OR REPLACE`로 멱등화. `connection.py`는 `create_all` 직전에
  `neos.database.models`를 임포트. CI 워크플로의 `CREATE EXTENSION` 인라인 3벌을
  `scripts/enable_db_extensions.py`로 통일(**`pg_trgm`이 빠져 있었다**). 가드 3건 신설.
- **범위 — 반쯤 고치고 다 고쳤다고 하지 않는다.** 제외 7건: 다른 `db/*.sql` 의존 4 ·
  pgvector가 3072차원 hnsw 불가 1 · 스크립트가 암묵적 트랜잭션이라 `CONCURRENTLY` 불가 2.
- **부트스트랩이 켜지자 드러난 것 셋(같은 날):** ① `deep_analysis_runs`를 지울 수 없다(events FK) —
  **이벤트가 하나라도 있는 run은 삭제 불가**, ② DB 없는 잡에서 스키마 적용이 터진다(엔진 객체가
  `create_all` 실패 **전에** 만들어진다), ③ 건너뛰는 마이그레이션 집합이 기계마다 다르다.
- **결과: CI 네 잡이 처음으로 전부 초록(`761f80d4`).**

---

<a id="d67"></a>

## D67. 표본 #17 판정 — 채택은 작동한다, 그러나 병목은 옮겨갔을 뿐이다 (2026-08-14)

> 📦 **요약** — 원문은 [아카이브 D67](DECISIONS_ARCHIVE_2026-08.md#d67)에 그대로 있다.

- **사전 등록 대비(dev 5건).** **G-1 ✅** 채택 88건, 질문 **74 → 155**.
  **G-2 ✅**(단 기대가 부정확했다 — dev는 2 → 2이고 그것이 `dev_profile.max_depth=2`의 상한이다.
  default는 깊이 1 → 4). **G-3 ❌ 반증** — 통과는 여전히 11건 중 1건, 에이전틱 반려 전부
  `judge_answers_question=false`. **부작용 ✅ 악화 없음** — `exhausted` 0 유지, 조립 클레임 생존
  0.575 → **0.730**, 배달 각주 중앙값 8.5 유지.
- **G-3이 말하는 것 — 불만의 문구가 바뀌었다.** #16 "핵심 요소들을 **다루지 않은 채**" →
  #17 "핵심 요구사항이 대부분 **'미확인'으로 남아**".
  **묻지 않아서 못 답하던 것이, 물었는데 확립하지 못하는 것으로 바뀌었다.**
- **`claim_verified`는 129 → 116으로 오히려 줄었다.** 넓이는 판정자가 세는 축이 아니다 —
  판정자는 축마다 **확립된 근거**를 요구한다.
- **새 실패 모드:** run `9d9daa8b`가 렌더 전 draft를 반환.

---

<a id="d68"></a>

## D68. 채택 자식의 예산 정책과 §6.3.2 독립 심사자 — 손잡이 둘을 따로 단다 (2026-08-15)

> 📦 **요약** — 원문은 [아카이브 D68](DECISIONS_ARCHIVE_2026-08.md#d68)에 그대로 있다.

- **손잡이 셋을 따로 단다:** `subq_budget_policy`(기본 `uniform` — 균등 분할이 깊이를 팔았는가) ·
  `subq_adopt_cap`(4 — 넓이 자체가 과한가) · `subq_reviewer_enabled`(`False` — 자기 채점이 넓이를
  과대평가하는가).
- **왜 한꺼번에 켜지 않는가:** 무엇이 원인인지 가를 수 없게 되기 때문이다.
- **구현:** 예산 분배 `adopted_child_caps`, §6.3.2 독립 심사자 `_review_subquestions` + `subq_review` v1.
- **곁가지 — 게이트를 흔들던 간헐 실패의 진범(같은 날).** 테스트 오염이었다. 앞선 진단은 **반증됐고**,
  영수증에 "재현하지 못한 실패를 고쳤다고 적지 않는다"고 써 둔 것이 그 정정을 가능하게 했다.
  수정 후 전체 스위트가 시드 두 개에서 **2533 passed**.

---

<a id="d69"></a>

## D69. 표본 #18 사전 등록 — `value_weighted` 예산 분배 (2026-08-15, 실행 전)

> 📦 **요약** — 원문은 [아카이브 D69](DECISIONS_ARCHIVE_2026-08.md#d69)에 그대로 있다.

> **이 항목은 표본을 돌리기 전에 커밋됐다.** 판정은 여기 적힌 것에 대해서만 한다.

- **변경은 하나:** `subq_budget_policy` = `value_weighted`.
- **기대(실행 전 고정):** **H-1** `claim_verified` 상승 · **H-2** 형제 예산이 `value_est`와 같은
  방향으로 흩어진다(#17은 형제끼리 전부 같은 값이었다) · **H-3** `resolved` 비율 상승.
- **부작용 감시:** 예산을 몰아주면 낮은 값 가지가 굶는다.
- **판정은 dev 5건으로 한다.**
- ⚠️ **정정(D70):** H-1의 기준 수치 116은 dev 5건이 아니라 **6건 전체**의 수이고 dev 5건은 **82**다.
  이 착오는 판정을 바꾸지 않는다 — #18은 두 기준 모두에서 내려갔다.

---

<a id="d70"></a>

## D70. 표본 #18 판정 — `value_weighted` 반증, `uniform` 으로 되돌린다 (2026-08-15)

> 📦 **요약** — 원문은 [아카이브 D70](DECISIONS_ARCHIVE_2026-08.md#d70)에 그대로 있다.

- **사전 등록 대비(dev 5건).** **H-1 ❌ 반증** — `claim_verified` **82 → 65**(6건 전체 116 → 99).
  **H-2 ✅ 확인** — 형제 예산이 흩어진 그룹 **0/23 → 21/22**.
  **H-3 ❌ 반증** — 1.29% → 1.41%(2/155 → 2/142, 절대 수가 같다 · 노이즈).
  **굶주림 🔴 발동** — `abandoned` **15 → 30**(두 배).
- **H-2가 이 판정을 반박 불가능하게 만든다** — 배선이 안 먹은 것이 아니라 먹은 채로 나빠졌다.
- **정확히 무엇이 반증됐나:** **워커의 `value_est`는 어느 가지가 증거를 낼지 예측하지 못한다.**
- **부수 지표:** 조립 클레임 생존 0.730 → 0.797, 리덕션 0.753 → 0.708,
  배달 각주 중앙값 8.5 → **6.5**. `E_ORPHAN_CITE`는 재발하지 않았다(raw marker 0/6).
- **조치: `uniform`으로 되돌린다.** 값을 **예산**에 쓰는 것은 반증됐다.

---

<a id="d71"></a>

## D71. 표본 #19 사전 등록 — 채택 상한 4 → 2 (2026-08-16, 실행 전)

> 📦 **요약** — 원문은 [아카이브 D71](DECISIONS_ARCHIVE_2026-08.md#d71)에 그대로 있다.

> **이 항목은 표본을 돌리기 전에 커밋됐다.** 판정은 여기 적힌 것에 대해서만 한다.

- **변경은 하나:** `subq_adopt_cap` 4 → **2**. 예산을 **어떻게 나누는가**(D70, 반증됨)가 아니라
  **몇 갈래로 나누는가**를 잰다. 반토막이어야 판정이 선다.
- **비교 기준은 #18이 아니라 #17이다** — #18은 반증된 `value_weighted`였으므로, 같은 `uniform`인
  #17(cap 4)과 비교해야 변경 하나만 남는다. #17 기준선(dev 5건): `claim_verified` 82 ·
  `abandoned` 15 · 질문 155 · `resolved` 2(1.29%) · 배달 각주 중앙값 8.5.
- **기대(실행 전 고정):** **I-1** `claim_verified` 상승 · **I-2** `abandoned` 감소 ·
  **I-3** 형제 그룹의 채택 수가 2에 몰린다(배선 확인 — 이것 없이는 반증을 해석할 수 없다).
- **부작용 감시 — 이번 변경의 진짜 위험:** **커버리지가 되돌아올 수 있다**(D65가 채택을 넣은 이유가
  판정자의 "핵심 축" 불만이었다).

---

<a id="d72"></a>

## D72. 표본 #19 판정 — 넓이 축소도 반증, 되돌린다 (2026-08-17)

> 📦 **요약** — 원문은 [아카이브 D72](DECISIONS_ARCHIVE_2026-08.md#d72)에 그대로 있다.

- **사전 등록 대비(dev 5건, 기준 #17).** **I-3 ✅ 확인** — 형제 그룹 **21개 전부 2**.
  **I-1 ❌ 반증** — `claim_verified` **82 → 74**. **I-2 ✅ 확인** — `abandoned` **15 → 11**.
  **커버리지 감시 🔴 강하게 발동** — 통과 **1 → 0**, 에이전틱 반려 **4 → 6**(전부
  `answers_question=false`), 배달 각주 중앙값 **8.5 → 4.0**.
- **세 표본이 같은 것을 말한다.** 질문당 `claim_verified`: #17 155문/82건 **0.53** ·
  #18 142/65 **0.46** · #19 99/74 **0.75**. **넓이가 증거를 산다** — 넓이를 깊이와 바꾸려는 시도가
  두 번 다 총 증거를 잃었다. **효율과 총량이 반대로 움직이고, 판정자가 세는 것은 총량 쪽이다.**
- **조치: cap 4로 되돌린다.** 남은 후보가 하나로 좁혀졌다 → D73.

---

<a id="d73"></a>

## D73. 해결 게이트를 워커에게 알려준다 + 그 수를 원장에 남긴다 (2026-08-18)

> 📦 **요약** — 원문은 [아카이브 D73](DECISIONS_ARCHIVE_2026-08.md#d73)에 그대로 있다.

- **먼저 D72의 다음 후보 판단을 정정한다.** 앞선 진단(`confidence_cap` 0.6이 0.7 문턱을 막는다)은 틀렸다.
- **실측(표본 #16~#19):** 0.7 문턱을 넘은 질문 **645건 중 9건(1.4%)** · `question.confidence`가
  0.3~0.55에 몰림(최대 0.75) · **워커는 과신하지 않는다**(약 600 패스 중 신뢰도 클램프 1~2회) ·
  프롬프트가 `self_assessment`를 **설명하지 않는다**(JSON 예시에 `0.8` 한 번) · **원장에 안 남는다**.
- **이번에 넣는 것 셋:** ① `pass_completed`에 `self_assessment`·`question_confidence`·
  `resolve_threshold`·`resolved_gate`(**계측** — 동작 불변) ② `worker_brief` v5의 `self_assessment`
  규칙(이번 표본이 재는 변경) ③ 미치환 플레이스홀더 fail-closed(`llm.py`, **모델에 보내는 지점**에
  둔다 — 부분 렌더가 설계이기 때문이다).
- **표본 #20 사전 등록:** **J-1** `self_assessment` 0.7 이상 패스가 나타난다 · **J-2** `resolved`가
  645건 중 9건 수준에서 상승 · **J-3** "핵심 축 미확인" 반려 감소.
- **부작용 감시 — 근거 없는 자신감:** 지금 워커는 정직하게 낮게 매기고 있을 수 있다.
  `judge_strength_ok=false`가 느는지 함께 본다. **J-2가 참이어도 그것이 나빠지면 순이득이 아니다.**

---

<a id="d74"></a>

## D74. 표본 #20 판정 — 그리고 세 표본이 실패한 진짜 이유 (2026-08-18)

> 📦 **요약** — 원문은 [아카이브 D74](DECISIONS_ARCHIVE_2026-08.md#d74)에 그대로 있다.

- **사전 등록 대비(dev 5건, 기준 #17).** **J-1 ⚪ 판정불가** — 나타나긴 했다(2건, 최대 0.9)
  그러나 **이전 표본은 이 값을 기록한 적이 없어 비교 기준이 없다.** 나타난 것과 늘어난 것은 다르다.
  **J-2 ❌ 반증** — `resolved` 2 → 2. **J-3 ⚪ 판정불가**(n이 작고 방향이 엇갈린다).
  **부작용 ✅ 발생하지 않음** — `resolved`가 안 늘었으므로 근거 없이 닫힌 질문도 없다.
- **그런데 계측이 상위 원인을 드러냈다 — 내가 고친 것은 8.6%였다.** 해결 게이트 분포:
  `no_verified_claim` **202건(83.1%)** · `below_threshold` 21(8.6%) · `failed_status` 18(7.4%) ·
  `resolved` 2(0.8%).
- **그 202건은 "찾지 못한" 것이 아니라 돌지 않은 것이다.** 클레임 0건 패스 220건 중 **208건이 토큰 0**,
  completed 0건. 클레임이 있는 23건은 토큰 0이 하나도 없고 평균 8,473.
- **그리고 이것은 다섯 표본 내내 그랬다.** 토큰 0 비율 #16 78.0% · #17 87.7% · #18 87.0% ·
  #19 82.7% · #20 85.6%이고, **클레임을 낸 패스는 매번 22~25건으로 일정하다.**
- ⚠️ **원인 지목(깊이 2 질문의 캡이 한 패스 값에 못 미친다)은 D75가 정정한다.**

---

<a id="d75"></a>

## D75. D74 의 원인 지목을 정정한다 -- 굶기는 것은 캡이 아니라 전역 예산이다 (2026-08-18)

> 📦 **요약** — 원문은 [아카이브 D75](DECISIONS_ARCHIVE_2026-08.md#d75)에 그대로 있다.

- **D74의 무엇이 틀렸나:** 캡은 **판별 요인이 아니다.** 깊이 2에서 돈 질문 14개의 캡 평균 3,412 vs
  **못 돈 질문 78개의 3,310** — 사실상 같다. 깊이 1도 22,063 vs 21,515.
- **진짜 구속:** 런 정산이 dev 5건 **101,688~103,666** — **전역 예산이 먼저 마른다.**
- **자연 실험이 이미 데이터 안에 있었다.** dev(140k): 런당 생산적 패스 **7** · 검증 클레임 13.6 ·
  정산 102,625(캡의 73%). default(300k): **22** · 26 · 225,779(75%).
  **예산 2.2배 → 생산적 패스 3.1배 → 검증 클레임 1.9배.**
- **그래서 표본 #17~#20이 무엇을 재고 있었나:** 넷 다 판정을 dev 5건으로 했고, dev는 런당 생산적
  패스 7개짜리 구성이다. **우리는 조사할 여력이 없는 구성을 네 번 튜닝했다.**
- **이것은 사람이 정할 문제다**(D-11로 올림) → D77이 곁가지를 검정하고 D78이 결정한다.

---

<a id="d76"></a>

## D76. S5 판정 -- CI 결정론은 닫혔다, 그리고 출하 기준이 6/6이 됐다 (2026-08-18)

> 📦 **요약** — 원문은 [아카이브 D76](DECISIONS_ARCHIVE_2026-08.md#d76)에 그대로 있다.

- **표본을 쓰지 않았다.** GitHub Actions의 기록된 결과만으로 판정했다.
- **판정 근거:** `31939071284`(08-16) · `32016595849`(08-17) · `32134907317`(08-18) 세 런의
  quality · workflow-tests · api-tests · rest-tests **네 잡이 전부 초록**.
- **"3회 연속 동일 결과"의 동일성은 순서가 다른 채로 성립한다**(D64의 랜덤화 위에서).
  08-18 두 런의 카운트가 잡별로 동일: workflow 1112 · api 357 · rest 1469 passed / 23 skipped · quality 3.
- **범위 100%를 카운트의 등식으로 확인했다** — 그전까지는 단언으로만 보장됐다.
- **로그 보존 한계를 정직하게 적는다** — 옛 런은 빈 출력을 내므로 그 둘에 대해 확인한 것은
  **잡 단위 결론**이고, 시드와 카운트를 직접 확인한 것은 08-18의 두 런이다.
- **이 판정의 진짜 결과:** 남은 것은 CI가 아니다 — **통과율(표본 #17 기준 11건 중 1건)과
  판정자의 커버리지 불만**이다. 출하 기준이 6/6이 됐다.

---

<a id="d77"></a>

## D77. D75 의 곁가지 둘을 검정한다 -- 과대 예약은 병목이 아니다, 병목은 마무리 floor 다 (2026-08-18)

> 📦 **요약** — 원문은 [아카이브 D77](DECISIONS_ARCHIVE_2026-08.md#d77)에 그대로 있다.

- **표본을 쓰지 않았다.** 표본 #16~#20이 원장에 남긴 것만 읽었다(dev 25 run).
- **먼저 D75의 수치 하나를 정정한다.** 조사 가용은 dev **72,000** / default **165,600**이고
  마무리 floor가 각각 49% · 45%를 차지한다. 정정은 D75의 결론을 **강화한다.**
- **곁가지 (a) — 정산의 나머지 절반은 어디로 가나.** `worker_analysis` 44.6% ·
  `report_assembly` 18.6% · `node_reduction` 10.4% · `claim_grading` 10.0% · `claim_entailment` 8.3% ·
  `report_grading` 3.1%. **워커가 아닌 조사 지출의 정체는 채점이다.**
- **곁가지 (b) — 반증됐다.** 조사 가용 소진율 dev **96%** · default **99%**. 예약 사이징을 완벽하게
  고쳐도 되찾을 수 있는 것은 **워커 패스 0.5회분 미만**이다. 풀은 어차피 다 쓰이므로 총량이 바뀌지 않는다.
- **그래서 진짜 여유가 어디 있는지가 드러났다 — 마무리 floor.** 실제 사용 중앙값이 floor의
  **48%(dev) · 53%(default)**, **관측 최대**도 61% · 57%. dev 기준 여유 **26,423 토큰 = 워커 4.4 패스분**.
  **D-11이 바뀐다** → D78.
- **정직하게:** floor를 줄이는 것은 공짜가 아니다 — 마무리 굶주림 감시 항목을 함께 건다.

---

<a id="d78"></a>

## D78. D-11 결정 -- 마무리 floor 를 낮춘다. 예약 보증을 의도적으로 포기한다 (2026-08-19)

D75 가 사람에게 넘긴 질문(**라이브 표본이 무엇을 재야 하는가**)에 답한다.
표본을 쓰지 않고 결정했고, **선택은 사람이 했다.**

### 왜 결정이 필요했나

표본 #17~#20 은 넷 다 **dev 5건**으로 판정했다. 그런데 dev 는 런당 패스를 47회
시도해 **41회가 한 토큰도 쓰기 전에 거절**되고 생산적 패스가 **6개**뿐인 구성이다.
채택 노브 셋(#17 채택 도입 · #18 값 비례 · #19 넓이 축소)은 그 6개를 **어느 질문에
쓸지**만 바꿨고, 총 검증 클레임은 65~82 밴드를 벗어난 적이 없다.

### 먼저 D77 을 두 번 정정한다

**정정 1 -- floor 를 정산과 비교했다.** floor 가 덮어야 하는 것은 정산이 아니라
**예약**이다(`reserve()` 가 예약 시점에 검사한다). 옳은 양은 "정산 누적 + 그 순간의
예약" 의 최대치다:

| | dev | default |
|---|---|---|
| `report_floor` | 57,600 | 113,600 |
| 실제 점유 최대 | **38,170 (66%)** | 64,684 (57%) |
| 여유 | 19,430 | 48,916 |

**정정 2 -- 여유를 패스로 환산한 것이 과대였다.** D77 은 워커 패스 단가(5,967)로
나눠 "4.4 패스분" 이라 적었다. 그러나 생산적 패스 하나는 자기 몫의 채점·entailment·
분해를 함께 끌고 온다 -- **조사 지출 69,255 / 생산적 패스 6 = 11,542** 가 진짜
단가다. 여유 19,430 은 **1.7 패스분**이지 3.3 도 4.4 도 아니다.

### 줄일 수 있는 항은 하나뿐이다

**판정 항은 절감이 0 이다.** `report_floor` 의 grading 기여
`(report_retry_cap+1) x grading` 은 dev 21,600 / default 41,600 으로
**`grading_floor_tokens` 와 정확히 같다.** "판정 2 라운드" 와 "판정 1회 + 그 절단
확장" 이 같은 수이고, 원장의 `report_grading` 예약은 run 당 1회다. 1x 로 줄이면
이 tier 가 자기 안쪽 tier 보다 작아진다.

**남는 것은 조립 항이고, 거기에는 명시적 보증이 걸려 있었다:**

    assembly_tier = report_floor - grading_floor = 36,000
    최악(모든 시도 절단 + 각 호출이 예약을 100% 사용) = 2 x 17,852 = 35,704
    여유 296

`test_config_defaults.py` 가 이것을 고정하며 주석이 이유를 적었다: **"바닥은 예약
보증이지 기대값이 아니다."** 그 보증은 D53·D55 가 "시도 1 이 6 run 중 4건에서
`input_bound` 로 거절됐다 -- 재시도 루프가 실재한 적이 없다" 를 실측하고 세운 것이다.

### 채택 -- `report_floor_funded_attempts` 1.2

**사람이 이 보증을 낮추는 쪽을 택했다.** 권고는 D-11 의 A(dev 예산 상향)였고,
근거는 아래 "잴 수 없다" 였다. 그 판단은 기록만 남기고 따르지 않는다.

| | 전 | 후 |
|---|---|---|
| dev `report_floor` | 57,600 | **43,200** |
| dev 총 floor (cap 대비) | 68,000 (49%) | **53,600 (38%)** |
| dev 조사 가용 | 72,000 | **86,400 (+20%)** |
| default `report_floor` | 113,600 | **84,800** |
| default 조사 가용 | 165,600 | **194,400 (+17%)** |

조립 tier 는 dev 21,600 으로 **한 라운드(최악 17,852)를 21% 여유로 덮고 두 라운드는
덮지 않는다.** report_floor 43,200 은 30 run 관측 최대 38,170 의 **1.13배**다
(default 는 1.31배). `finalization_floor_warn_ratio`(0.5)는 건드리지 않는다.

**포기한 것을 정확히 적는다:** 조립이 두 라운드 모두 절단되고 각 호출이 예약을
100% 쓰는 run 은 둘째 라운드를 `input_bound` 로 잃는다 -- D53·D55 가 고친 바로 그
실패다. 30 run 에서 그런 run 은 없었다. **30 은 많지 않다. 이것은 증명이 아니라
측정에 건 내기다.**

`test_the_assembly_tier_funds_every_attempt_including_its_truncation_retry` 는
지우지 않고 **새 계약을 양방향으로** 고정하도록 다시 썼다: 한 라운드는 반드시
덮고(`>= one_round`), 모든 라운드를 덮으면 실패한다(`< attempts * one_round`).
누가 1.2 를 되돌리면 테스트가 그것을 의도적 변경으로 드러낸다.

### 표본 #21 사전 등록 (실행 전에 고정한다)

**변경은 하나다:** `report_floor_funded_attempts` = 1.2.

> 🔴 **이 표본은 패스 수로 판정할 수 없다. 실행 전에 그렇게 적어둔다.**
> 확보한 것은 dev 14,400 토큰이고 생산적 패스 단가는 11,542 이므로 기대 효과는
> **+1.2 패스**인데, 생산적 패스의 run 간 **표준편차가 2.19**(범위 4~12)다.
> n=5 의 표준오차가 0.98 이라 +1.2 는 잡음과 갈리지 않는다. 그래서 1차 지표를
> **조사 지출**로 옮긴다 -- 조사 가용이 96% 소진되므로(D77) 그 값은 거의
> 결정론적이고(25 run 에서 66,848~70,788), floor 감소분이 그대로 나타나야 한다.

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| **L-1** (1차) | dev 조사 단계 정산이 **69,255 -> 83,000 이상**으로 오른다 | 안 오르면 확보한 토큰이 조사에 도달하지 않은 것이다. floor 를 낮춘 만큼 `node_reduction` 이 먹었을 수 있다(`available_for_reduction` = remaining - report_floor 이므로 리덕션도 함께 풀린다) -- 그때는 리덕션 정산을 같이 읽는다 |
| **L-2** (2차) | 생산적 패스와 `claim_verified` 가 **오르는 방향** | **판정 기준이 아니다.** 효과가 잡음보다 작으므로 방향만 기록하고, #16~#21 을 풀링해 토큰 -> 패스 -> 클레임 환산율을 좁히는 데 쓴다 |
| **부작용** (기각 조건) | **마무리가 굶지 않는다**: `report_assembly_degraded` 0 유지 · clamp `exhausted` 0 유지 · 배달 각주 중앙값 8.5 밴드 유지 · `E_REPORT_*` 반려 구성 불변 | 하나라도 깨지면 **되돌린다.** 이것이 D53·D55 가 고친 실패의 재발이고, 조사 여력 +20% 는 그 대가로 살 것이 못 된다 |
| 무변 | `job_failed` 0 · 배달 6/6 · `MISSING_QUESTION` 0 | |

**판정은 dev 5건으로 한다.** default 도 같은 방향으로 바뀌므로(조사 가용 +17%)
이번 표본에는 손대지 않은 기준선이 없다 -- 그 사실을 판정 시 명시할 것.

⚠️ **비교 가능성:** #17~#20 과 조사 가용이 달라졌으므로 절대값 비교는 끊긴다.
L-1 은 그 단절 자체를 재는 지표다.

### 게이트 영수증 (표본 #21 실행 전)

    HOME=/tmp/neos-test-home .venv/bin/python -m pytest -q
    2938 passed, 23 skipped, 0 failed  in 111.79s
    시드 786136292 (pytest-randomly 기본 활성, D64)

S5 판정(D76)의 기준선과 **같은 수**다 -- 이 변경은 고정값 세 곳
(`test_config_defaults.py` 의 두 프로파일 floor · `test_service.py` 의 두 tier)을
갱신하고 보증 테스트 하나를 다시 썼을 뿐, 테스트를 늘리거나 줄이지 않았다.

> 이 영수증은 **최종 트리에서 다시 돌린 것**이다. 앞선 실행(시드 4202898336)은
> 같은 결과를 냈으나 실행 중에 `report_floor_tokens` 의 docstring 을 고쳤다 --
> 주석이라 결과가 달라질 수 없지만, 영수증이 트리와 어긋난 채로 남으면 그것이
> 다음 판정의 근거가 된다.

검산:

| | dev | default |
|---|---|---|
| `grading_floor` | 21,600 | 41,600 |
| `report_floor` | **43,200** | **84,800** |
| 총 floor (cap 대비) | **53,600 (38%)** | **105,600 (35%)** |
| 조사 가용 | **86,400** | **194,400** |
| 조립 tier | 21,600 | 43,200 |
| 한 라운드(17,852) 대비 | **1.21배** | 2.42배 |
| 두 라운드(35,704) 대비 | **0.60배** (의도) | 1.21배 |
| 30 run 관측 최대 대비 | **1.13배** | 1.31배 |

불변식 `grading_floor <= report_floor <= floor` 는 두 프로파일 모두 성립한다.

> ⚠️ **default 프로파일도 함께 바뀐다.** 이 노브는 프로파일별이 아니라 공용
> 산식에 걸리므로 default 조사 가용도 165,600 -> 194,400 이 된다. 그래서 표본
> #21 에는 **손대지 않은 기준선 런이 없다** -- 판정 시 명시할 것.

<a id="d79"></a>

## D79. F1 판정 — 진단자는 미달이다. 그런데 미달의 절반은 계측이다 (2026-08-21)

> 📦 **요약** — 원문은 [아카이브 D79](DECISIONS_ARCHIVE_2026-08.md#d79)에 그대로 있다.

- **판정: 미달.** `mean_recall` **0.500** < `constant_best` **0.833**(아무것도 안 읽는 최선의 고정 예측),
  근거 유효율 1.000. 관문은 `mean_recall >= constant_best` AND 유효율 >= 0.9다.
- **표본별:** #13 **1.00** · #11 0.67 · #14 0.67 · #15 0.67 · #12 **0.00** · #16 **0.00**.
- **#13이 이 백테스트의 수확이다** — 당시의 사람이 가르지 못한 원인을 진단자가 `truth`로 맞혔다.
- **#16은 진단자의 실패가 아니다** — 정답의 신호 셋이 **요약에 존재하지 않았다**(`build_summary`).
  **#12는 진짜 에이전트 실패다.**
- **그래서 다음은 진단자가 아니라 집계다** → D80. 라이브 표본을 쓰지 않으므로 곧바로 재실행된다.
- **곁가지:** 스모크 1회가 18회를 구했다 — 거짓 신호를 모델이 실제로 근거로 삼고 있었다.
- ⚠️ **이 항목의 헤드라인("미달의 절반은 계측")은 D83이 정정한다.**

---

<a id="d80"></a>

## D80. D79 를 정정한다 -- `questions.open`/`questions.resolved` 는 고칠 이름이 아니라 존재한 적 없는 필드였다 (2026-08-21)

> 📦 **요약** — 원문은 [아카이브 D80](DECISIONS_ARCHIVE_2026-08.md#d80)에 그대로 있다.

- **고친 것:** `diagnose_bottleneck.md` 규칙 6의 "키가 없으면 0"을 실제 이벤트 의미에 맞게 정정하고,
  **신호 지도의 모든 경로가 실제로 존재하는지 확인하는 검증**을 추가했다.
- **라이브 표본 #16으로 확인했고, 시간차 하나를 찾았다** — `resolved_gate`가 그 창에 존재하지 않았다
  (`status: "partial"`만 있다). 즉 **#16은 애초에 판정 가능한 표본이 아니었다.**
- **#16을 빼면 판정이 뒤집히는가 — 아니다.** 6개 전부 0.500 vs 0.833(미달),
  **#16 제외 0.600 vs 0.900(여전히 미달)** — 빼면 고정 예측이 덮어야 할 다양성도 함께 줄기 때문이다.

---

<a id="d81"></a>

## D81. F1 재실행 — 계측을 채웠더니 더 나빠졌다. 그리고 그렇게 만든 것은 내 프롬프트다 (2026-08-22)

> 📦 **요약** — 원문은 [아카이브 D81](DECISIONS_ARCHIVE_2026-08.md#d81)에 그대로 있다.

- **결과: 더 나빠졌다.** `mean_recall` **0.500 → 0.361**.
  #13 1.00 → **0.33**, #14 0.67 → **0.33**, #11 0.67 → 0.83.
- **D79의 읽기가 반증됐다.** 계측 구멍을 메우자 진단자는 그 축을 "확인할 수 없다"로 읽었고,
  **그렇게 읽으라고 시킨 것이 내가 쓴 규칙 7이다.**
- **여기서 멈춘다 — 프롬프트를 정답키에 맞춰 고치지 않는다.** 점수를 보고 프롬프트를 고쳐 다시
  재는 것이 **정확히 스펙 §2가 막는 오염**이다.
- **대신:** ① 기대와 반증 조건을 **실행 전에** 사전 등록하고 ② 가능하면 **다른 표본 창**(#6~#16)에서
  판정한다 — 같은 여섯 개로 세 번째 측정을 하지 않는다 → D82.

---

<a id="d82"></a>

## D82. F1 세 번째 측정 사전 등록 — 표본 창을 #6~#16으로 넓힌다 (2026-08-22, 실행 전)

> 📦 **요약** — 원문은 [아카이브 D82](DECISIONS_ARCHIVE_2026-08.md#d82)에 그대로 있다.

> **이 항목은 실행 전에 커밋됐다.**

- **바뀐 것은 창 하나뿐이다:** 표본 창 #11~#16 → **#6~#16**.
- **창을 넓힌 것이 실제로 바꾼 것:** 표본 6 → **11**, `constant_best` 0.833 → **0.545**,
  최대 달성 조합 1개(유일) → **15개(동률)**, truth/contemporaneous가 갈리는 판별 표본
  1개(#13) → **3개(#9·#10·#13)**.
- **사전 등록:** **M-1(관문)** `mean_recall >= 0.5455` **그리고** 유효율 >= 0.9 —
  미달이면 두 창·세 번의 측정에서 전부 미달이다. **M-2(판별)** #9·#10·#13 중 최소 하나에서 `truth`
  적중 — 셋 다 `contemporaneous`를 재현하면 부족한 것은 에이전트가 아니라 계측이다.
  **M-3(알려진 편향)** `instrumentation` 선택 비율이 직전 두 실행(9.3% · 7.4%)보다 크게 오르지 않는다.

---

<a id="d83"></a>

## D83. F1 판정 — 진단자는 표본을 읽지 않는다. F1 을 닫는다 (2026-08-22)

> 📦 **요약** — 원문은 [아카이브 D83](DECISIONS_ARCHIVE_2026-08.md#d83)에 그대로 있다.

- **사전 등록 대비.** **M-1 ❌ 미달** — `mean_recall` **0.3636** vs 0.5455(유효율 1.000 ✅).
  **M-2 ✅ 확인** — #10 1.00 · #13 1.00 · #9 0.00. **M-3 ✅ 확인** — **7.1%**(직전 9.3% · 7.4%).
  무변 `provider_error` 0 ✅.
- **M-2는 확인됐지만, 확인된 방식이 그것을 무효로 만든다.** 맞힌 것이 **전부 `assembly_clamp`** 이다
  (#10 · #13 · #15 1.00, #11 0.67, #14 0.33). 다른 정답의 표본은 전부 0.00.
  **진단자는 표본을 읽지 않는다. 하나의 이야기를 갖고 매번 그것을 말한다 — 멈춘 시계다.**
- **그래서 D79의 헤드라인을 정정한다** — "미달의 절반은 계측"이 아니었다.
- **판정: F1을 닫는다.**
- **그럼에도 F1이 값을 한 것 / 남기는 것:** 요약 통계로 판정하고 원자료를 보지 않은 것이 이 세션의
  가장 비싼 실수였고, 그 교훈은 **앞으로의 모든 표본 판정에 적용된다.**

---

<a id="d84"></a>

## D84. H1 구성 매니페스트 -- 원장이 런의 구성을 답한다 (2026-08-22)

트랙 H(로드맵 §15) 첫 단계. 런 하나가 무엇으로 조립됐는지를 `run_manifest`
이벤트 하나에 못 박는다. 스펙:
`docs/superpowers/specs/2026-08-22-deep-analysis-run-manifest-design.md`.
표본을 한 건도 쓰지 않고(§15.3 H1의 관문 정의 그대로) 과거 아티팩트만으로
검증했다.

    commits  4fc2165b(역할 테이블) -> abd9c75c(호출 지점 9곳 이전)
             -> e8a909c0+bcde20fb(매니페스트 빌더) -> bcdb7715(발행)
             -> 6e3851d2(FE 라벨) -> 8d02e73b+ea30fd59(아티팩트 층이 원장을 읽는다)
             -> 87b42194+596a1efd(표본 경계 게이트) -> d4e79d1d+5b6df3e5(백테스트)

### H-1 -- 새 이벤트 kind, 컬럼이 아니다

매니페스트는 `deep_analysis_runs`에 컬럼을 더하는 대신 **새 이벤트 kind**
`run_manifest`로 둔다(로드맵 §15.5 H-1).

- **마이그레이션 0건.** `DAEvent.kind`는 `String(40)`
  (`neos/database/deep_analysis_models.py:203`)이고 `"run_manifest"`는
  12자다. 이것이 급한 이유는 취향이 아니라 **SCHEMA1**이다 -- 로드맵 §7이
  적었듯 마이그레이션 44개를 신선한 DB에 순서대로 적용하면 **7개가 실패한다.**
  마이그레이션이 필요한 설계는 이미 나쁜 기반 위에 하나를 더 얹는 것이다.
- **append-only(D8)와 맞다.** 컬럼은 UPDATE를 요구하지만 이벤트는 그렇지
  않다. §15.2 ㉯("쓰고 나서 제거한다"와 append-only 원장의 충돌)의 해소가
  "제거도 이벤트다"였는데, 매니페스트를 컬럼으로 뒀으면 그 해소 자체가
  성립하지 않았다.
- **컬럼이었다면 SCHEMA2(§7, run 삭제 관련 보존기한 요구)가 걸린다.** 이벤트가
  하나라도 있는 run은 지워지지 않으므로, run 레코드를 넓히는 쪽이 나중에
  보존기한 요구가 생겼을 때 더 아프다.

### 거부 지점은 표본 경계뿐이다

`scripts/deep_analysis_funnel_sample.py`의 `_gate_and_read_manifests`가
`write_artifacts` 직전에 표본의 모든 run_id에 대해 매니페스트 존재를
검사하고, 하나라도 없으면 아티팩트를 쓰지 않는다(`MissingManifestError`,
commits 87b42194·596a1efd). **`Orchestrator.run()`은 건드리지 않는다.**
그 안에 게이트를 넣으면 Orchestrator를 직접 짓는 골든·통합 테스트 수십 건이
깨지고, 로드맵 §15.4 금지 3번의 문구가 금지하는 것은 "런"이 아니라
**"표본"**이다.

### 로드맵의 "그래프 토폴로지 해시" 항은 컴포넌트 배선 지문으로 바뀐다

§15.3 H1이 원래 적은 항목은 "그래프 토폴로지 해시"였다. 구현하지 않았다 --
**심층분석 런은 LangGraph 그래프를 타지 않는다.** 자체 오케스트레이터
루프다. 대신 `components` 칸에 부품 배선을 적는다: grader·agentic_grader·
report_grader·synthesizer·citation_renderer·search_fn·fetch_fn·cassette
각각을 `type(obj).__module__:type(obj).__qualname__`(`neos.workflow.deep_analysis.`
접두어는 뗀다)로 지문 낸다. 소스 파일 해시는 넣지 않는다 -- 클래스 이름이
같고 내용만 바뀐 경우(D58·D60·D62의 절삭기 교체가 정확히 그랬다)는 아티팩트
층이 이미 붙이는 `git` 항(commit + dirty)이 답하고, 파일 해시는 그것과
중복이면서 런마다 파일 읽기를 추가한다.

### 프롬프트는 8개다, 9개가 아니다

`prompts/` 디렉터리에는 9개 파일이 있지만 매니페스트가 싣는 것은 런 경로가
실제로 로드하는 **8개**뿐이다: `decompose`·`worker_brief`·`subq_review`
(orchestrator.py) · `final_compose`·`node_summary`(synthesizer.py) ·
`claim_entailment`(worker.py) · `judge`(graders/agentic.py) ·
`report_judge`(graders/report.py). **`diagnose_bottleneck`은 뺀다** --
그것은 F1 진단자(D79~D83, 표본을 사후에 *읽는* 쪽) 전용이고
`scripts/deep_analysis_diagnostician.py:33`만 로드한다. 런의 구성이 아니다.
넣으면 그 파일을 고칠 때마다 **실제로 동일한 두 런이 서로 달라 보인다** --
매니페스트가 재는 것은 "저장소에 무엇이 있나"가 아니라 "이 런이 무엇을
썼나"다.

### 실측 근거 -- 표본 #20이 지금도 틀린 캡을 적고 있다

매니페스트가 없던 시절 아티팩트가 실제로 무엇을 놓쳤는지 표본 #20으로
확인했다:

    artifacts/deep-analysis-funnel/20260818T111321Z/manifest.json
      config_fingerprint.global_token_cap : 300000   (기본 프로파일 값)
      dev_runs                            : 5개 런 -- 실제로는 140000 캡의 dev 프로파일

    dev available_for_investigation = 140000 - 53600 = 86400

**86,400은 D78이 D75 -> D77 -> D78 세 번의 정정 끝에 도달한 바로 그
숫자다.** 매니페스트가 있었다면 이 값은 표본 #17이 돌기 전에 이미 원장에
있었을 것이다 -- D75 -> D77 -> D78의 세 번은 이 한 줄의 뺄셈을 손으로 다시
계산한 것이었다.

### 백테스트 관문 결과

`scripts/manifest_backtest.py`로 표본 #16~#20(모두 이 기능 이전 아티팩트)을
검사했다(`docs/superpowers/plans/artifacts/2026-08-22-manifest-backtest.md`).

| 표본 | profile | models | budget | prompts | skills | components | config |
|---|---|---|---|---|---|---|---|
| #16~#20 (5건 전부) | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

**옛 지문(`config_fingerprint`)에서 부분 복원되는 것은 `models`·`budget`·
`config` 뿐이고, `profile`·`prompts`·`skills`·`components`는 다섯 표본
어디에도 없다.** 이 넷은 옛 아티팩트의 구조적 한계이지 백테스트 도구의
결함이 아니다 -- 이 기능 도입 후 기록된 아티팩트는 같은 도구로 전부 ✅다
(`test_new_artifact_recovers_every_field`).

**더 날카로운 발견 -- `budget`은 ✅인데 그 값이 틀리다.** 표본 #20의
`global_token_cap`은 300000 하나만 적혀 있지만 6런 중 5런은 dev 프로파일
140000 캡으로 돌았고 실제 `tokens_spent`는 36,620~59,380이다. `budget` 칸이
✅인 것은 지문에 값이 "있다"는 뜻일 뿐 **그 값이 모든 런에 대해 옳다**는
뜻이 아니다. 즉 `profile` 칸의 부재는 정보 하나를 잃는 데 그치지 않고
**남아 있는 `budget` 칸을 오독하게 만든다.**

### 구현 중 결정한 이탈 -- `judge_equals_scout`을 최상위로

스펙 초안(§3.3)은 `judge_equals_scout`을 `models` 안에 그렸다. 구현 리뷰에서
`models`의 다른 모든 값은 해석 결과 dict인데 이것만 bool이라
`models.items()`를 도는 소비자가 깨진다는 지적이 나왔고(fix round 1,
commit bcde20fb), **최상위 키로 옮기는 쪽을 채택했다.** 지금 그 값을 도는
소비자가 없어(T6 reader는 kind로만 필터, 백테스트는 `field in sample`, FE는
`profile`만 읽는다) 옮기는 비용이 0이지만, `manifest_version: 1`이 표본에
실리고 나면 같은 이동이 버전 범프를 요구한다 -- **지금이 공짜로 고칠 수
있는 유일한 시점**이었다. 스펙 문서도 같은 커밋 대(Task 9)에서 정정했다
(정정 상자 포함, 원문은 지우지 않음).

### 남기는 것

- **H-2** -- 동적 합성이 라이브 표본 경로에 들어오는 시점. §15.2 ㉰(같은
  사전 등록 아래 런마다 도구가 다르면 비교 불가)이 통계 문제라 설계로
  닫히지 않는다. 이 설계는 답하지 않는다.
- **H-3** -- 플러그인 버전 고정 정책. `skills[].version`을 매니페스트에
  싣지만 **고정하지는 않는다.**
- **갈림 감지 정책(`divergent_manifest_fields`)은 의도적으로 미구현이다**
  (R2 재정). 표본 하나 안에서 run마다 매니페스트가 다를 때 중단할지, 기록만
  하고 진행할지, 항목별로 나눌지는 §4가 사람의 판단으로 남긴 자리다. 함수
  시그니처와 판단 재료(§4)는 스펙에 있으나 `_main()`에 배선하지 않았다 --
  호출자 없는 함수를 만들면 죽은 코드이고, 이 지점은 소유자가 채운다.
- **`skills`는 선언만 되고 채워지지 않는 칸이다 (2026-08-23 최종 리뷰 정정).**
  스키마에는 칸이 있지만 `build_orchestrator`에 `skill_registry`를 넘기는
  호출자가 지금 하나도 없다 -- 그 kwarg 사용처를 찾으면 `service.py` 자신뿐이다.
  즉 프로덕션의 모든 런에서 `skills`는 항상 `null`이다. 레지스트리를 배선하는
  것은 이 결정의 범위 밖이다 -- 별도의 미해결 질문과 얽혀 있다. `docs/superpowers/plans/artifacts/2026-08-22-manifest-backtest.md`도
  같은 정정을 받았다 -- 그 문서의 "전부 ✅"는 체커가 값이 아니라 키의 존재를
  채점한다는 뜻이었다.

---

<a id="d85"></a>

## D85. 표본 #21 실행 전 재확인 -- 사전 등록은 D78 그대로, 감시 항목 하나를 더한다 (2026-08-29, 실행 전)

D78 이 사전 등록을 쓴 것은 2026-08-19 이고 그 사이 열흘이 지났다. **D78 의 기대·기각
조건은 한 글자도 바꾸지 않는다.** 이 항목이 하는 일은 셋이다 -- 그 수치가 지금 트리에서도
같은지 검산하고, 그 사이 생긴 두 표본 경계가 1차 지표를 오염시키는지 판정하고, 그 판정에서
나온 감시 항목 하나를 **실행 전에** 못박는다.

> 📌 **이것은 사전 등록의 수정이 아니라 추가다.** §13.5 가 금지한 것은 *판정자가 자기
> 사전 등록을 고치는 경로* 이고, 여기서 더하는 것은 기대도 기각 조건도 아닌 **감시
> 항목**이다. 판정을 느슨하게 만들 수 없는 방향으로만 움직인다.

### 1. 설정 검산 -- D78 검산표와 8/8 일치

| | dev | default |
|---|---:|---:|
| `global_token_cap` | 140,000 | 300,000 |
| `grading_floor` | 21,600 | 41,600 |
| `report_floor` | 43,200 | 84,800 |
| 총 floor (cap 대비) | 53,600 (38.3%) | 105,600 (35.2%) |
| 조립 tier | 21,600 | 43,200 |
| 조사 가용 | 86,400 | 194,400 |

`report_floor_funded_attempts = 1.2` · 불변식 `grading <= report <= floor` 두 프로파일 모두
성립 · `tests/workflow/deep_analysis/test_config_defaults.py` 17 passed (양방향 보증 단언
포함 -- 한 라운드는 덮고 두 라운드는 덮지 않는다).

### 2. 🔴 두 표본 경계가 L-1 을 오염시키는가 -- 오염시키지 않는다

D78 의 L-1 기준선 **69,255 는 C3(`59e34624`)·C3-m1(`43303acd`) 보다 열흘 앞선 수**다.
두 커밋 모두 `DAQuestion.spent_tokens` 를 올리고, 로드맵 §7.2 는 그것이 "조사를 조금 일찍
멈추게 한다" 고 적었다. 사실이라면 **L-1 의 반증이 해석 불가**가 된다 -- "floor 축소가
조사에 도달하지 않았다"(L-1 이 정의한 반증)인지 "회계 수정이 그만큼 먹었다"인지 가를 수
없기 때문이다.

**가른 결과: 오염되지 않는다.** `Budgeter.should_stop()` 에 정지 조건이 둘이고 두 커밋은
그중 하나만 건드린다.

| 조건 | 읽는 수 | dev 발동 지점 | C3·C3-m1 |
|---|---|---:|---|
| ① `available_for_investigation < min_viable_output_tokens` | `TokenBudget` (예약·정산) | 소비+예약 > **84,352** | 영향 없음 |
| ② `total_spent() >= global_token_cap` | `SUM(DAQuestion.spent_tokens)` | 140,000 | 영향 있음 |

①이 ②보다 훨씬 먼저 묶는다(84,352 vs 140,000). 그리고 결정적으로 **`TokenBudget.abandon()`
은 실패한 예약을 삭제하지 않고 전액 그대로 붙든다** -- `remaining_tokens = cap - consumed -
reserved` 에서 계속 빠진다. 즉 C3 가 이제 질문에 청구하는 실패 호출 토큰은 ①이 **이미, 더
보수적으로**(실제 소모분이 아니라 예약 전액으로) 세고 있었다. 판정자 토큰(C3-m1)은 원래부터
정상 정산되어 ①에 들어 있었다.

따라서 1차 지표(조사 단계 정산 = `token_budget_settled` 의 조사 스테이지 합)는 두 경계를
가로지르지 않으며 **69,255 는 비교 가능하다.**

### 3. 그래서 더하는 감시 항목 하나

⚠️ **위 판정은 코드 추론이지 측정이 아니다.** §8.1.2 가 이 루프의 교훈으로 적은 것이
정확히 "계측을 먼저 의심한다" 이고, 자가 지표는 이미 세 번 틀렸다.

| 감시 | 기대 | 깨지면 |
|---|---|---|
| **W-1** | `token_budget_exhausted` = **0 유지** | 조건 ②가 묶기 시작한 것이다. 그 순간 L-1 은 floor 축소가 아니라 회계 경계를 재고 있으므로 **L-1 판정을 보류하고** 조건 ①·② 중 어느 것이 정지시켰는지부터 가른다 |

이것은 기각 조건이 아니라 **해석 게이트**다. 0 이면 L-1 을 D78 그대로 읽고, 0 이 아니면
L-1 을 읽기 전에 정지 사유부터 읽는다.

### 4. 경계와 게이트 영수증

두 경계가 모두 HEAD 의 조상이고 워킹트리는 clean 이다. 그 뒤 올라온 두 커밋
(`72e7c56e` 락파일 · `1816096f` CI)은 `deep_analysis` 를 0건 건드린다.

    HEAD 1816096f
    .venv/bin/python -m pytest tests/ -q --randomly-seed=12345
    3316 passed, 63 skipped, 0 failed  in 124.73s (2:04)

D78 이 세운 규율대로 **최종 트리에서 다시 돌린 것**이다 -- 앞선 실행(시드 1·2·3·7)은
그 사이 커밋이 올라와 트리와 어긋나므로 영수증으로 쓰지 않는다.

> ⚠️ 이 기준선 수(3,316)를 회귀 판정에 그대로 쓰지 말 것. 로드맵 §10.4 가 적은 대로
> 절대 수는 커밋마다 움직이고, 쓸 수 있는 것은 `--collect-only` 증분이다.

---

<a id="d86"></a>

## D86. 표본 #21 판정 -- L-1 확인. 확보한 토큰이 오차 0.08% 로 조사에 도달했다 (2026-08-29)

아티팩트 `artifacts/deep-analysis-funnel/20260829T104802Z` · dev 5 + default 1 · 6/6 완주 ·
실패 0. 사전 등록은 D78(기대·기각 조건)과 D85(재확인·감시 항목 W-1)이고 둘 다 **실행 전에
커밋**돼 있다(`3414c40a`).

### 0. W-1 (해석 게이트) -- 통과

`token_budget_exhausted` = **0 / 6 run**. `should_stop()` 의 조건 ②
(`total_spent() >= global_token_cap`)는 한 번도 묶지 않았다. D85 가 코드에서 추론한
"C3·C3-m1 은 L-1 을 오염시키지 않는다" 가 실측으로 확인됐고, 따라서 **L-1 을 D78 원문
그대로 읽는다.**

### 1. L-1 (1차 판정 지표) -- ✅ 확인

**#20 을 같은 방법으로 재계산해 비교 가능성을 확보했다** -- 조사 단계 정산은
`token_budget_settled.actual_tokens` 를 `token_budget_reserved.stage` 로 조인해
`FINALIZATION_STAGES` 밖만 합산한 값이다.

| | #20 (dev) | #21 (dev) |
|---|---:|---:|
| run 별 | 68,247 · 68,440 · 68,879 · 69,197 · 70,510 | 76,555 · 82,718 · **83,667** · 84,034 · 84,901 |
| **중앙값** | 68,879 | **83,667** |
| 조사 가용(86,400) 대비 | -- | **96.8%** |

기대는 "69,255 -> **83,000 이상**" 이었다(69,255 는 D77 이 25 run 에서 낸 중앙값).

🔴 **증가분이 예측과 거의 정확히 같다.** floor 를 57,600 -> 43,200 으로 낮춰 확보한 것은
**14,400** 이고, 중앙값 증가는 D78 기준선 대비 **+14,412**(오차 12 토큰, 0.08%),
#20 재계산값 대비 **+14,788** 이다.

**이것이 D78 이 적어둔 반증 해석 하나를 직접 배제한다.** D78 은 "안 오르면 확보한 토큰이
조사에 도달하지 않은 것이다 -- floor 를 낮춘 만큼 `node_reduction` 이 먹었을 수 있다
(`available_for_reduction` = remaining - report_floor 이므로 리덕션도 함께 풀린다)" 고
썼다. 리덕션이 먹었다면 증가분이 14,400 에 미치지 못했어야 한다. 미달이 아니라 **일치**다.

### 2. 기각 조건 (부작용) -- 셋 통과, 넷째는 판단이다

| 조건 | 기대 | #20 dev | #21 dev | |
|---|---|---|---|---|
| `report_assembly_degraded` | 0 유지 | 0 | **0** | ✅ |
| clamp `exhausted` | 0 유지 | 0 | **0** | ✅ |
| 배달 각주 중앙값 | 8.5 밴드 유지 | 4 (0·2·4·5·8) | **9** (6·6·9·9·11) | ✅ |
| `E_REPORT_*` 반려 구성 | **불변** | ORPHAN 2 · AGENTIC 2 · UNCITED 5 · PASS 1 | ORPHAN **0** · AGENTIC **5** · UNCITED 5 · PASS **0** | ⚠️ |

🔴 **넷째는 문자 그대로는 미달이다. 그것을 먼저 적는다.**

되돌리지 않기로 판단했고 근거는 이렇다. 이 조건이 막으려던 것은 **마무리 굶주림**이고,
굶주림의 직접 신호 셋은 전부 통과했다. 그리고 구성 변화의 **방향이 굶주림과 반대다** --
각주가 4 -> 9 로 늘었고 `E_ORPHAN_CITE` 가 2 -> 0 으로 사라졌다. **굶은 마무리는 각주를
잃지 늘리지 않는다.** `E_REPORT_AGENTIC` 2 -> 5 는 판정자가 더 자주 실제로 돌았다는
뜻이고(검증 클레임 68 -> 91), 그것은 #16 이 "판정자의 불만이 인용에서 커버리지로
옮겨갔다" 고 적은 그 병목이지 예산 부족이 아니다.

⚠️ **이것은 사전 등록의 재해석이므로 판정문에 드러내 둔다.** 다음 사람이 "기각 조건 하나가
깨졌는데 통과시켰다" 를 발견하고 근거를 찾지 못하면, 그것이 §13.5 가 금지한 사후 합리화와
구별되지 않는다. 사용자에게 명시적으로 제시하고 승인받았다.

### 3. L-2 (2차, 방향만) -- 기대보다 강하다

| | #20 dev | #21 dev |
|---|---|---|
| 검증 클레임 총계 | 68 | **91** (+34%) |
| run 별 분포 | 7 · 12 · 16 · 16 · 17 | **16 · 17 · 18 · 19 · 21** |

D78 이 "총 검증 클레임은 **65~82 밴드**를 벗어난 적이 없다" 고 적었는데 **91 은 그 밴드
위**이고, 분포가 통째로 올라갔다(최솟값 7 -> 16).

**그래도 판정 기준이 아니다.** D78 이 "효과가 잡음보다 작으므로 방향만 기록" 이라 못박았고,
5+1 단일 관측으로 인과를 주장하지 않는다(§10.2). 그리고 **손대지 않은 기준선 런이 없다** --
이 노브는 공용 산식이라 default 도 조사 가용이 165,600 -> 194,400 으로 함께 바뀌었다
(실측 정산 191,576 = 가용의 98.5%).

### 4. 정직하게 함께 적는 것

- 🔴 **통과 0 건.** #20 의 1 건이 사라졌다. D78 이 통과를 기준으로 삼지 않았고 #19 도
  1 -> 0 을 겪었지만, **조사가 21% 늘고 클레임이 34% 늘었는데 게이트를 통과한 리포트는
  오히려 줄었다.** 이것이 다음 병목의 위치를 말한다 -- 재료가 아니라 리포트 층이거나,
  판정자의 커버리지 기준이다.
- ⚠️ **`pass_completed`(34~81)를 D75 의 "생산적 패스 7 개" 와 비교하지 말 것.**
  `commit_pass` 마다 나오는 이벤트라 비생산 패스도 센다. 정의가 다른 두 수를 같은 이름으로
  읽는 것은 D48 이 표본 하나를 치르고 배운 실패다 -- 그래서 비교하지 않았다.
- ✅ **ORPHAN2 감시 결과.** default run 에서 `E_ORPHAN_CITE` 2 건이 재발했으나 **각주
  16 개가 함께 배달**됐다. 로드맵이 적어둔 감시 조건("반려 건수는 그대로이되 그때 배달되는
  각주 수가 0 이 아니어야 한다")을 **충족** -- ORPHAN1 의 구조 수정(`render_best_effort`)이
  실물에서 확인됐다. dev 에서는 아예 0 건이었다.
- **정지 사유는 여전히 `input_bound` 가 지배적이다** -- dev 5 건 중 4 건이
  `investigation_stopped_at_input_bound`, 1 건이 `investigation_stopped_at_floor`.
  무이벤트 정지 0 건(S4 유지).

### 5. 판정

**`report_floor_funded_attempts` = 1.2 를 유지한다.** D78 이 "되돌리는 조건" 으로 건
마무리 굶주림은 발생하지 않았고, 1 차 지표는 예측과 오차 0.08% 로 일치했다.

**D78 이 포기한 보증은 그대로 포기된 상태다** -- 조립 두 라운드가 모두 절단되고 각 호출이
예약을 100% 쓰는 run 은 둘째를 잃는다. 이번 6 run 에서도 그런 run 은 없었다.
**누적 36 run 에서 0 건이다. 36 도 많지 않다.**

다음 병목은 예산이 아니다. 조사 재료는 늘었는데 통과가 0 이므로, 다음 표본은 **리포트 층
또는 판정자 기준**을 겨눠야 한다.

---

<a id="d87"></a>

## D87. G3-m1 은 표본 경계가 아니었다 (백테스트) + 표본 #22 사전 등록 (2026-08-29, 실행 전)

### 1. 백테스트 -- 라이브 표본을 쓰지 않고 경계 하나를 지웠다

`6ec71567`(G3-m1)을 커밋하며 **"인용 게이트의 분모가 커지므로 표본 경계"** 라고 적었다.
표본 #21 의 배달 본문 5건(16,610자)에 옛/새 정규식으로 결정론 채점기를 다시 돌려
그 주장을 검정했다 -- D30·D38·D75 가 쓴 기법이고 라이브 표본을 한 건도 쓰지 않는다.

| run | 주장 (옛 → 새) | 인용없음 | 비율 |
|---|---|---|---|
| `e1e461e9` | 11 → **11** | 1 → 1 | 0.091 → 0.091 |
| `3abaf523` | 15 → **15** | 2 → 2 | 0.133 → 0.133 |
| `643ddd46` | 17 → **17** | 4 → 4 | 0.235 → 0.235 |
| `ca288b93` | 18 → **18** | 0 → 0 | 0.000 → 0.000 |
| `de15f297` | 15 → **15** | 2 → 2 | 0.133 → 0.133 |

**하나도 바뀌지 않았다.** 비율 중앙값 0.133 → 0.133, 임계값 초과 1/5 → 1/5.

**기전.** 129 문장 중 새 정규식만 잡는 문장이 **14개**다 -- 수정 자체는 작동한다.
그러나 `assertions` 는 문장 단위 **`_DIGIT` OR `_PROPER_NOUN`** 이고, **그 14개가
전부 이미 숫자를 담고 있다.** 분모가 늘려면 "조사 붙은 라틴 고유명사 + 숫자 없음"
문장이 있어야 하는데 이 말뭉치에는 **0개**다.

🔴 **따라서 `6ec71567` 의 커밋 메시지와 로드맵의 "표본 경계" 서술은 과장이었다.**
정정한다: G3-m1 은 **이 증거 위에서 무효과**다. 경계는 넷이 아니라 **셋**이다.

⚠️ **"무효과" 를 "무의미" 로 읽지 말 것.** 고친 것은 여전히 옳다(휴리스틱의 절반이
한국어에서 죽어 있었다). 다만 그것이 분모를 키우지 못하는 이유는 **이 코퍼스의
사실 주장 문장이 거의 다 숫자를 동반하기 때문**(날짜·임계값·수량)이고, 그것은
질문 다섯 개의 성질이다. 숫자가 드문 주제에서는 달라질 수 있다. n=5·129문장.

📌 **그리고 이것이 로드맵의 오래된 진단 하나를 정정한다.** §7 G3-m1 항목은 "분모가
사실상 숫자를 담은 문장뿐" 이라고 적었고 그것은 **참**이지만, 뒤따르던 함의
("작은 분모가 임계값 0.20 을 쉽게 넘게 만든다 → 고치면 완화된다")는 **거짓**이다.
고유명사 문장이 숫자 문장에 거의 포섭되므로 분모는 그대로다. **임계값이 쉽게
넘기는 원인은 다른 데 있다.**

### 2. 그래서 표본 #22 는 E3 만 잰다

경계 넷 중 하나가 지워졌고, C3·C3-m1 은 #21 이 이미 그 이후에서 떴다. 남은 것은
**E3(판정자 모델 교체) 하나**이므로 #22 는 §13.5 의 "한 표본에 변경 하나" 를 지킨다.

**변경:** `deep_analysis.models.judge` = `claude-sonnet-5`(역할 기본값) → `gpt-5.6-sol`.

> 🔴 **이 표본은 가설 검정이 아니라 기준선 재수립이다. 실행 전에 그렇게 적어둔다.**
> E3 는 성능 변경이 아니라 **불변식 복원**이다(§2.3 `judge != worker`). 승인률이
> 오를지 내릴지는 예측하지 않는다 -- 다른 모델 가족이 채점하므로 D86 이 적은 대로
> **예측 불가**이고, 방향을 사전 등록하면 어느 쪽이 나와도 사후에 설명할 수 있는
> 이야기가 되어 판정이 아니라 합리화가 된다.

| # | 기대 | 반증이 뜻하는 것 |
|---|---|---|
| **M-1** (1차, 유일한 검정) | **판정자가 실제로 돈다** -- `report_graded` 의 `judge=ran` 이 #21 과 같은 수준(10건 중 5건 이상), 그리고 `judge` 가 `budget_exhausted`/`truncated`/`unparseable` 인 건수 **0** | 크로스 프로바이더 배선이 깨진 것이다. **E3 의 진짜 위험은 편향이 아니라 이것**이다 -- 판정자가 못 돌면 `ok=true` 폴백으로 조용히 통과하고(§8.1.1) 우리는 편향을 없앤 줄 알면서 심사 자체를 잃는다 |
| **기준선** (판정 아님, 기록) | `agentic_passed/attempted` · `E_REPORT_*` 구성 · 통과 수 · 배달 각주 중앙값 | #23 이후가 이 수를 기준선으로 쓴다. **#1~#21 의 채점 수치와 나란히 놓지 않는다** |
| **참고** (방향만) | 클레임 승인률 vs #21 의 91/99 = **91.9%** | 새 판정자가 더 엄격한지 느슨한지의 *관측*이다. 어느 쪽도 성공/실패가 아니다 |
| **기각 조건** | `job_failed` 0 · 배달 5/5 · 조사 지출 중앙값이 #21 의 83,667 에서 ±10% 이내 | 셋째가 깨지면 판정자 토큰 회계가 예산을 흔든 것이다(판정자가 다른 프로바이더가 되면서 `judge_tokens` 의 크기가 달라질 수 있다) -- 그때는 M-1 을 읽기 전에 그것부터 가른다 |

**판정은 dev 5건으로 한다.** default 는 같은 판정자를 쓰므로 손대지 않은 기준선이
이번에도 없다 -- 판정 시 명시할 것.

### 3. 그 다음(#23)이 겨눌 것

#21 이 "재료가 병목이 아니다" 를 보였고(조사 +21%, 클레임 68 → 91, 통과 1 → 0),
#22 가 새 판정자 아래 기준선을 세운다. **#23 이 리포트 층 또는 판정자 기준을
겨눈다** -- 그 설계는 #22 의 `E_REPORT_*` 구성을 보고 정한다. 지금 정하면
낡은 판정자의 반려 분포 위에서 정하는 셈이다.

---

<a id="d88"></a>

## D88. D87 사전 등록 개정 -- 판정자를 `claude-opus-4-8` 로 (2026-08-30, 실행 전)

**개정이지 판정이 아니다.** 표본 #22 는 아직 돌지 않았고, §13.5 가 금지한 것은
*판정자가 자기 사전 등록을 고치는 경로* 다. 이것은 실행 **전**의 변경이며,
D87 을 덮어쓰지 않고 이 항목으로 남겨 무엇이 왜 바뀌었는지 대조 가능하게 한다.

### 무엇이 바뀌었나

D87 은 판정자를 `gpt-5.6-sol` 로 적었다. **사전 점검에서 `OPENAI_API_KEY` 가
401 이었다** -- 배선은 옳았고(정적 해석·클라이언트 선택·카탈로그 가격 전부 통과)
자격증명이 죽어 있었다. 판정자를 `claude-opus-4-8` 로 바꾼다(`b3abefaa`).

**판정자가 안 도는 것은 편향보다 나쁘다.** §8.1.1 이 적은 대로 못 돈 판정자는
통과처럼 보이고, 우리는 편향을 없앤 줄 알면서 심사 자체를 잃는다.

**대가를 정확히:** opus-4.8 은 워커 셋(sonnet-5·opus-5·opus-5) 모두와 다르지만
**같은 모델 가족**이다. 가족은 실패 모드를 공유하므로 자기 승인 편향 분리가
크로스 프로바이더보다 **약하다.** E3 의 불변식(`judge != worker`)은 지켜지되
그 불변식이 겨눈 편향은 부분적으로만 줄어든다. 유효한 OpenAI 키가 생기면
다시 정한다.

### 사전 점검에서 확인한 것 (표본을 쓰지 않고)

| 확인 | 결과 |
|---|---|
| 역할 해석 | `judge=claude-opus-4-8` provider=anthropic source=feature_override |
| 워커와의 분리 | scout/dig/synth 셋 모두와 다름 |
| 카탈로그 가격 | 있음 (⚠️ **미검증** -- 아래) |
| thinking 계약 | **실측**: `temperature` → 400 "deprecated for this model" · `adaptive` → 정상 |
| 하네스 경로 | `call_json` 이 `{'label': 'SUPPORTS'}` 파싱, in=33 out=21 |

⚠️ **가격은 미검증이다.** 저장소의 유일한 출처가 `codex/anthropic-caching-advisor`
브랜치이고 그 값이 opus-5 와 정확히 같다. 같은 브랜치의 haiku 가격은 카탈로그와
어긋났다. **등재돼 있으므로 `neos_llm_unpriced_calls_total` 은 울리지 않는다** --
틀려도 조용하다. 표본 #22 의 비용 집계를 근거로 쓰지 말 것.

### M-1 은 그대로 유효하다 -- 오히려 이번 일이 그 이유를 보였다

D87 의 M-1(**판정자가 실제로 도는가**)은 바꾸지 않는다. 401 은 정확히 그 위험이
실현된 것이고, **사전 점검이 없었다면 70분과 실비용을 태운 뒤 판정자가 전멸한
표본을 얻었을 것**이다 -- §10.2 때문에 다시 뜰 기회 없이.

📌 **그리고 남길 교훈 하나:** `preflight` 는 `ANTHROPIC_API_KEY` 와
`TAVILY_API_KEY` 만 검사한다. E3 가 새 프로바이더 의존성을 만들었는데 preflight 가
따라오지 않았다. 지금은 판정자가 다시 Anthropic 이라 구멍이 닫혔지만, **판정자를
다른 프로바이더로 옮기는 다음 사람은 preflight 도 함께 옮겨야 한다.**

---

<a id="d89"></a>

## D89. 표본 #22 판정 -- E3 배선은 확인됐고, M-1 의 임계값은 내가 잘못 설계했다 (2026-08-30)

아티팩트 `artifacts/deep-analysis-funnel/20260829T184100Z` · dev 5 + default 1 ·
6/6 완주 · 실패 0. 사전 등록은 D87 과 **D88**(개정)이고 둘 다 실행 전 커밋돼 있다.

### 1. M-1 (1차, 유일한 검정) -- 절반 충족

| M-1 구성 | 기대 | 실측 | |
|---|---|---|---|
| (a) `judge=ran` 건수 | ≥5 | **3** | ❌ |
| (b) `budget_exhausted`/`truncated`/`unparseable` | 0 | **0** | ✅ |

**판정자는 도달할 때마다 100% 정상 작동했다.** 3건 전부 `ran` 이고 실패 종류는
하나도 없다. (a)가 미달한 이유는 판정자 고장이 아니라 **결정론 게이트가 먼저
막았기 때문**이다 -- dev 9건 중 6건(`E_REPORT_UNCITED` 4 + `E_ORPHAN_CITE` 2)이
agentic tier 에 도달조차 못 했다.

🔴 **그러므로 (a)는 내가 잘못 설계한 지표다.** "≥5" 는 *판정자가 작동하는가* 와
*판정자에게 도달하는가* 를 한 수에 묶었는데, 후자는 **E3 가 통제하지 않는 상류
게이트**가 정한다. E3 의 배선을 재는 데는 (b)만으로 충분했다.

⚠️ **그래도 "사실은 통과" 로 고쳐 적지 않는다.** 문자 그대로는 미달이고, 그 이유가
지표 설계에 있다는 것이 판정이다 -- 사전 등록을 결과에 맞춰 다시 쓰는 것과
설계 결함을 인정하는 것은 다르다(§13.5).

**교훈:** 배선을 재는 지표는 **비율이나 절대 건수가 아니라 조건부**여야 한다 --
"도달했을 때 실패한 비율" 이 옳은 모양이고, 그것은 이번에 0/3 이다.

### 2. 기각 조건 -- 셋 다 통과

| 조건 | 기대 | 실측 | |
|---|---|---|---|
| `job_failed` | 0 | 0 | ✅ |
| 배달 | 5/5 | 5/5 | ✅ |
| 조사 지출 중앙값 | 83,667 ±10% | **84,245** (+0.7%) | ✅ |

판정자 프로바이더가 바뀌어도 예산은 흔들리지 않았다 -- D87 이 걸어둔 우려는
발생하지 않았다.

### 3. 새 기준선 (판정 아님, 기록)

| | #21 (판정자 sonnet-5) | **#22 (판정자 opus-4.8)** |
|---|---|---|
| agentic 승인률 | 91.9% (91/99) | **88.1%** (74/84) |
| `report_graded` 코드 | AGENTIC 5 · UNCITED 5 | **PASS 1** · UNCITED 4 · AGENTIC 2 · ORPHAN 2 |
| 게이트 통과 | 0 | **1** (`judge=ran`, 각주 14) |
| 검증 클레임 | 91 | 74 |
| 각주 중앙값 | 9 | 5 |
| 조사 정산 중앙값 | 83,667 | 84,245 |

⚠️ **이 표를 "나빠졌다" 로 읽지 말 것.** D86·D87 이 못박은 대로 판정자가 바뀌었으므로
**채점 계열은 #21 과 비교 불가**다. verified 수는 판정자가 정하고, 제안 클레임
자체도 99 → 85 로 줄었다(조사 지출은 같은데). 이것은 새 기준선이지 비교 결과가 아니다.

📌 **통과가 0 → 1 로 돌아왔고 그것이 `judge=ran` 인 진짜 승인**(`950c948a`, 각주 14)
이라는 사실은 기록할 가치가 있다. **n=1 이고 5+1 단일 관측이라 인과는 주장하지
않는다**(§10.2). #21 의 0 과 #22 의 1 은 다른 판정자가 낸 수라 차이 자체가
비교 대상이 아니다.

### 4. 🔴 ORPHAN2 -- 감시 조건은 미달, 그런데 원인이 다른 것이었다

`6252da9e`(london-ulez)가 `E_ORPHAN_CITE` ×2 에 **각주 0** 이다. 로드맵의 감시
조건("반려 건수는 그대로이되 배달 각주가 0 이 아니어야 한다")은 문자 그대로 미달이다.
원인을 가르면:

- 배달 본문의 원본 마커: **6회 출현, 고유 1개**(`0ab00fdc`) -- **그 하나가 orphan**
- 이 run 의 verified 클레임: **7개**

**ORPHAN1 회귀가 아니다.** 렌더할 유효 인용이 애초에 없었으므로 각주 0 이 옳고,
`render_best_effort` 는 계약대로 orphan 마커를 남기고 강등을 기록했다.

**대신 드러난 것은 다른 결함이다: 조립기가 verified 클레임 7개를 두고 딱 하나만
인용했고, 그 하나를 지어냈다.** 인용 *손실* 이 아니라 인용 *생산* 의 문제다.
ORPHAN2 의 감시 조건은 "손실" 을 겨눠 쓰였고 이 사례를 서술하지 못한다 -- 조건을
고쳐야 한다(아래).

### 5. #23 의 대상이 이 결과로 바뀌었다

D87 은 "#22 의 `E_REPORT_*` 구성을 보고 #23 을 정한다" 고 적었다. 구성은 이렇다:
**`E_REPORT_UNCITED` 4 / `E_ORPHAN_CITE` 2 / `E_REPORT_AGENTIC` 2 / PASS 1.**

지배적 반려가 **인용 계열(UNCITED + ORPHAN = 6/9)로 돌아왔다.** #16 이 "판정자의
불만이 인용에서 커버리지로 옮겨갔다" 고 적은 뒤 처음이다. 그리고 §4 가 보인 대로
그 인용 문제는 **작성자가 마커를 못 받는 것**(#14·#15 가 확인한 옛 원인)이 아니라
**조립기가 있는 클레임을 안 쓰고 없는 id 를 지어내는 것**이다.

**따라서 #23 은 조립 프롬프트/입력이 아니라 `final_compose` 의 인용 생산을 겨눈다.**
구체 설계와 사전 등록은 별도 항목으로 쓴다 -- 지금 정하면 n=1 위에서 정하는 셈이다.
먼저 값싼 것부터: **#22 의 저장된 본문 5건에서 "가용 verified 클레임 수 vs 실제
인용한 고유 클레임 수" 를 세는 백테스트**다. 라이브 표본을 쓰지 않는다.

---

<a id="d90"></a>

## D90. 인용 생산 비율 -- 조립기가 가용 증거의 절반 이하만 쓴다 (2026-08-30, 백테스트)

D89 §5 가 예고한 값싼 백테스트다. **라이브 표본을 쓰지 않았다** -- #21·#22 의 저장된
배달 본문에서 세기만 했다.

**정의 (이 이름은 새것이다).** `인용 생산 비율` =
`배달 본문이 인용한 고유 클레임 수 / 그 run 의 verified 클레임 수`.
분자는 렌더된 각주 번호와 남은 원본 `[C:...]` 마커의 고유 수를 합한다 -- orphan 도
"인용하려 한 것" 이므로 분자에 든다(조립기의 *의도*를 재는 지표다).

| run | verified | 인용한 고유 | 비율 |
|---|---:|---:|---:|
| #21 `e1e461e9` | 18 | 6 | 0.33 |
| #21 `3abaf523` | 19 | 9 | 0.47 |
| #21 `643ddd46` | 17 | 11 | 0.65 |
| #21 `ca288b93` | 21 | 9 | 0.43 |
| #21 `de15f297` | 16 | 6 | 0.38 |
| **#21 중앙값** | | | **0.43** |
| #22 `e0c1a998` | 15 | 4 | 0.27 |
| #22 `950c948a` | 19 | 14 | **0.74** |
| #22 `c44ee6ee` | 18 | 5 | 0.28 |
| #22 `7b899de3` | 15 | 6 | 0.40 |
| #22 `6252da9e` | 7 | 1 | **0.14** |
| **#22 중앙값** | | | **0.28** |

### 무엇을 말하는가

**조사가 확보한 증거의 절반 이상이 리포트에 도달하지 않는다.** #21 에서 57%,
#22 에서 72% 가 인용되지 않았다. 이것은 #22 에서 새로 생긴 것이 아니라
**이제까지 재지 않았던 상시 격차**다.

📌 **그리고 이것이 #21 의 수수께끼를 설명한다.** #21 은 조사 지출 +21%, 검증 클레임
68 → 91 인데 통과가 1 → 0 이었고, D86 은 "재료가 병목이 아니다" 로 판정했다.
**맞다 -- 재료는 늘었는데 그 재료가 리포트에 안 실린다.**

📌 **두 표본 모두에서 통과한 run 이 비율 최고다.** #22 의 유일한 통과
(`950c948a`, 0.74)가 그 표본의 최댓값이고, 최저(`6252da9e`, 0.14)가 orphan 으로
죽은 run 이다. ⚠️ **n=5 의 상관이고 인과가 아니다**(§10.2) -- 인용을 많이 한
리포트가 통과한 것인지, 통과할 만한 리포트가 인용도 많이 한 것인지 이 데이터는
가르지 못한다.

### ⚠️ #16 의 "조립 클레임 생존 56%" 와 같은 수로 읽지 말 것

D63 이 잰 것은 **조립 프롬프트 안에서의 생존**이고 이것은 **배달된 본문의 인용**이다.
측정 지점이 다르다 -- 사이에 작성자의 선택이 한 겹 더 있다. D48 이 표본 하나를
치르고 배운 규칙("지표 정의가 바뀌면 키 이름을 바꾼다")에 따라 **다른 이름**을 쓴다.

그리고 §8.1.1 의 "작성자는 받은 클레임을 전부 쓴다"(#14·#15)와도 모순되지 않는다:
그것은 *프롬프트에 실린 마커* 의 생존율이고, 이 지표는 *원장의 verified 클레임* 이
애초에 마커가 되는 비율이다. **두 링크 중 앞쪽이 새는 것이다.**

### #23 의 대상

**`final_compose` 로 가는 클레임 선택/절삭**이다. 조립 프롬프트가 verified 클레임의
절반 이하만 싣는지, 아니면 다 싣는데 작성자가 안 쓰는지를 먼저 갈라야 한다 --
그것도 **라이브 표본 없이** 잴 수 있다(`node_summary`·`finalization_prompt_clamped`
의 `claims_before`/`claims_after` 를 배달 인용과 조인). 그 백테스트가 먼저다.

---

<a id="d91"></a>

## D91. 인용 생산 비율을 세 링크로 쪼갠다 -- 새는 곳은 `final_compose` 가 아니다 (2026-08-30, 백테스트)

D90 이 "그 백테스트가 먼저다" 로 남긴 것이다. **라이브 표본을 쓰지 않았다** --
#21·#22 의 원장에 이미 있는 것만 읽었다. 도구는
`scripts/deep_analysis_citation_production.py` 이고 재실행 가능하다.

### 0. 재현 게이트를 먼저 통과시켰다

새 지표를 내기 전에 **D90 의 `cited/verified` 열 열 개를 그대로 재현**하는 것을
도구의 실행 조건으로 걸었다(`--verify-d90`, 기본 켜짐). 재현하지 못하면 판정을
내지 않고 종료한다. §8.1.2 의 "계측을 먼저 의심한다" 를 도구 안에 넣은 것이다 --
파싱이 D90 과 어긋난 채 새 결론을 내면 그 결론은 D90 과 비교 불가해진다.
**열 런 전부 일치했다.**

### 1. 세 링크

D90 의 한 비율 사이에 원장이 이미 갖고 있던 두 지점을 끼웠다.

```
verified ──selection──▶ prompt_before ──clamp──▶ prompt_after ──writer──▶ cited
```

| 링크 | 무엇 | #21 중앙값 | #22 중앙값 |
|---|---|---:|---:|
| selection | 조립 프롬프트가 **절삭 전에** 실은 비율 | 0.63 | **0.56** |
| clamp | 절삭이 살린 비율 | 0.77 | 0.70 |
| writer | 작성자가 실제로 인용한 비율 | **1.00** | **1.00** |
| = production (D90) | | 0.43 | 0.28 |

### 2. 🔴 D89 §5 가 지목한 대상이 틀렸다

D89 는 "#23 은 조립 프롬프트가 아니라 `final_compose` 의 인용 생산을 겨눈다" 고
적었다. **반대다.** `final_compose` 의 작성자는 받은 것을 **전부** 쓴다 --
열 런 중 여덟이 정확히 1.00 이고, 나머지 둘(`ca288b93`·`7b899de3`)은 `cited` 가
어느 시도의 `after` 와도 일치하지 않아 애초에 비율을 낼 수 없는 런이라 중앙값에서
뺐다(표시는 한다). 손실은 **작성자에게 닿기 전에** 이미 일어나 있다.

이것은 §8.1.1 의 "작성자는 받은 클레임을 전부 쓴다"(#14·#15)를 **세 번째로,
새 측정 지점에서** 확인한 것이기도 하다.

### 3. selection 링크의 자리를 좁혔다 -- 절삭이 아니라 리덕션 LLM 이다

두 가지가 함께 나온다.

**(a) 절삭의 무죄.** 비루트 `node_reduction` 절삭 **27건 중 클레임을 실제로 자른
것은 1건**(`e0c1a998` 의 5→1)이다. `_log_clamp` 는 실제로 자를 때만 기록하므로
**로그에 없는 리덕션은 자르지 않은 것**이고, 따라서 이 표본에서 절삭은 중앙값
37~44% 의 손실을 설명할 수 없다.

**(b) 루트 리덕션 항등식.** 열 런 전부에서 루트 질문의 **자체 verified 클레임이
0개**다(루트는 직접 조사되지 않는다). 그러므로 루트 리덕션의
`distinct_claims_before` 는 곧 **자식들의 `NodeSummary.answer` 가 실어 올린 마커
수**다. 그리고 그 수가 **10/10 런에서 조립의 `prompt_before` 와 정확히 같다.**
두 소비자가 같은 집합을 받는다.

**따라서 손실은 `reduce_node` 의 출력에 있다.** 워커가 검증한 클레임의 마커가
그 노드의 요약 산문에 실리지 못하고, 실리지 못한 것은 위로 올라갈 수 없다.
자르는 것은 절삭기가 아니라 **요약을 쓰는 LLM** 이다.

### 4. D61(#15)과 모순되지 않는다 -- 그 판정이 잰 것은 절삭이었다

D61 은 "`node_reduction` 생존 100% vs `report_assembly` 15% → 리포트 층이 맞다"
로 적었다. 그 100% 는 **절삭 생존율**이고 위 (a)가 그것을 다시 확인한다.
어긋나는 것이 아니라 **그 지표가 볼 수 없던 손실**이 여기 있는 것이다 --
절삭은 자기가 받은 것만 세고, `reduce_node` 의 LLM 이 애초에 안 실은 마커는
절삭기의 `before` 에도 안 들어온다. 층 귀속이 틀린 것이 아니라 **불완전했다.**

### 5. 다음 -- 그리고 지금 라이브 표본을 뜨지 않는 이유

한 링크가 더 남아 있고 **그것은 지금 원장에 없다**: 노드 하나의
`claim_lines` 마커 수 대 그 노드 `NodeSummary.answer` 의 마커 수. `answer` 는
어디에도 영속화되지 않고(`deep_analysis_blobs` 는 가져온 웹 문서다) 이벤트도
싣지 않는다. **저장된 데이터로는 여기까지가 끝이다.**

그러므로 순서는: **계측 먼저, 표본은 그 다음.** `reduce_node` 가 자기 출력의
고유 마커 수를 남기게 하는 것은 LLM 호출도 예산도 건드리지 않으므로
**표본 경계가 아니다**(§7.2 의 넷과 성질이 다르다). 그 계측 없이 `node_summary`
프롬프트를 손대면 D40·D51 의 실패 -- **원인을 모르는 채 고치기** -- 를 반복한다.

⚠️ **n=10 이고 두 표본의 판정자가 다르다.** selection 중앙값 0.63 vs 0.56 을
표본 간 차이로 읽지 말 것(D89 §3). 이 판정이 기대는 것은 그 차이가 아니라
**writer 링크가 열 런 전부에서 1.00 근처**라는 것과 **절삭 27건 중 1건**이라는
두 사실이고, 둘 다 판정자 교체와 무관하다.

---

<a id="d92"></a>

## D92. CITE1 계측 — 그리고 D91 의 원인 지목을 좁혀 다시 적는다 (2026-08-30)

D91 이 남긴 CITE1 을 구현했다. **구현 중에 D91 §3 의 마지막 문장이 너무 좁다는
것이 드러났고, 그것을 먼저 적는다.**

### 1. 🔴 D91 의 "자르는 것은 요약을 쓰는 LLM 이다" 는 근거를 넘어선 문장이었다

D91 은 손실을 `reduce_node` 의 **출력**으로 좁혔다. 그 부분은 유효하다 — 절삭의
무죄(27건 중 1건)와 루트 리덕션 항등식(10/10)은 그대로다. 틀린 것은 그다음
한 걸음이다: **`reduce_node` 의 출력이 곧 LLM 의 출력이라고 가정했다.**

실측하면 아니다. #21·#22 열 런에서

| | 건수 |
|---|---:|
| `node_summary` (LLM 이 실제로 요약을 썼다) | **79** |
| `node_reduction_degraded` (LLM 이 돌지 않았다) | **152** |

**리덕션의 3분의 2는 LLM 을 호출하지도 못했다.** 그리고 강등 사유는
**152건 전부 `input_bound`** 다 — 단일 원인이다.

강등 경로(`_degraded_summary`)는 LLM 이 아니라 결정론적 join 이고, 마커를
잃는 자리가 **둘 더** 있다.

- **(가) 자기 클레임 침묵 폐기.** `if not answer and pairs` — 자식 답이 하나라도
  비어 있지 않으면 이 노드의 **자기 verified 클레임은 join 에 들어가지 않는다.**
  자식 답만 올라가고 자기 마커는 거기서 끝난다.
- **(나) 절단.** `_bound_degraded_answer` 가 상한에 맞을 때까지 **반씩 자른다**
  (D54 가 의도한 동작이다). 자르면 그 구간의 마커가 함께 간다. 열 런에서
  `answer_truncated=true` 가 15건이다.

**따라서 후보는 하나가 아니라 셋이다:** LLM 미탑재 · (가) · (나). D91 은 첫째만
이름 붙였고 나머지 둘은 전체 리덕션의 3분의 2가 지나는 경로에 있다.

### 2. 그 셋을 저장된 데이터로 가를 수 없다 — 그리고 시도하다 한 번 틀렸다

가르려고 백테스트를 밀어붙였고 **잘못된 추론을 하나 냈다.** `answer_chars > 0`
이면 자식 join 을 탄 것이라고 읽었는데, 그 키는 **분기보다 뒤에서** 기록된다
(`synthesizer.py`) — 자기 클레임 join 도 `answer_chars > 0` 이다. 두 분기가
같은 값을 낸다.

그 오류를 안고 계산한 "자기 클레임 유실" 상한은 스스로 반증됐다: `643ddd46` 은
유실 후보가 **17개로 그 런의 verified 전량**인데 실제로는 마커 **14개가 조립에
도달**했다. 상한이 참이기는 하나 쓸모없이 헐겁다.

📌 **이것이 CITE1 의 근거를 바꾼다.** D91 은 "마지막 링크 하나가 없다" 로 적었다.
정확히는 **분기 자체가 원장에 없다** — 어느 경로로 답을 만들었는지 모르면 남은
수치를 해석할 방법이 없다.

### 3. 구현

`answer_source` 하나가 이 항목의 핵심이다. 나머지는 그것이 있어야 읽힌다.

| 이벤트 | 새 키 | 무엇을 답하는가 |
|---|---|---|
| `node_summary` | `distinct_claims_prompt` · `distinct_claims_answer` | LLM 이 **보여준 것 중 몇 개를** 산문에 실었나 |
| `node_reduction_degraded` | `answer_source` (`children_join`/`own_claims`/`empty`) | 어느 분기가 답을 만들었나 |
| | `own_claims_available` | **쓸 수 있었던** 자기 클레임 수 — (가)를 세는 수 |
| | `distinct_claims_before_bound` · `distinct_claims_after_bound` | 절단이 가져간 마커 — (나) |

분모를 `claim_lines` 가 아니라 **실제로 보낸 프롬프트**로 잡았다. 모델은 자식
답의 마커를 포함해 **보여준 것 아무거나** 인용할 수 있고, 이 정의는 절삭기의
`distinct_claims_after` 와 같아서 **절삭된 리덕션은 같은 수를 두 계측기가 각각
보고한다**(서로 검증한다). 절삭되지 않은 리덕션은 이제 처음으로 그 수를 갖는다.

**표본 경계가 아니다.** 원장 쓰기만 늘었고 LLM 호출·예산·프롬프트는 그대로다.

### 4. 테스트가 실패해야 할 때 실패하는지

§8.1.2 의 규율("계측기가 도는지 보는 것은 통과를 보는 게 아니다")에 따라 넷 다
**차이를 주장한다**: 프롬프트에 마커 2개를 넣고 답에 1개만 실어 `2 vs 1` 을
확인하고, 강등 분기 둘을 **서로 다른 값**으로 각각 고정하고, 절단 테스트는
`after < before` 를 주장한다 — `<=` 로 쓰면 절단이 아무것도 안 가져가도
통과하고 그것이 D60 이 고친 공허한 불변식이다.

기존 `test_a_degraded_reduction_leaves_a_trace` 는 페이로드를 **정확 일치**로
고정하고 있었다. 부분 일치로 **느슨하게 바꾸지 않고** 새 키를 적어 넣었다 —
그 정확 일치가 의도치 않은 페이로드 추가를 잡는 장치이고, 지금 그것이 실제로
내 변경을 잡았다.

### 5. 다음

`answer_source` 없이는 무엇도 판정하지 않는다. 다음 라이브 표본이 이 넷을
싣고 돌면 **셋 중 어느 것이 지배적인지**가 한 번에 갈린다. 지금 `node_summary`
프롬프트를 손대는 것은 여전히 D40·D51 의 반복이다.

⚠️ **그리고 `input_bound` 152/152 자체가 별도 항목이다.** 리덕션의 3분의 2가
LLM 에 닿지 못하는 것은 인용 문제 이전에 **예산 문제**이고, D-11(마무리 floor)
계열이 이미 그 근처를 다룬 적이 있다. 인용 생산과 같은 표본에 섞지 말 것 —
§13.5 가 "여러 변경을 한 표본에" 를 금지한다.

---

<a id="d93"></a>

## D93. 표본 #23 사전 등록 -- CITE1 후보 셋을 가른다 (2026-08-30, 실행 전)

로드맵 §9 **D-13** 이 다음 라이브 표본을 CITE1 에 배정했다. 이것이 그 표본의
사전 등록이다. D92 가 계측을 닫았으므로 **이 표본은 아무것도 바꾸지 않는다.**

### 1. 🔴 변경 없는 순수 관측이라 "기각 조건" 의 모양이 다르다

표본 #1~#22 는 전부 무언가를 바꾸고 그 효과를 쟀고, 그래서 사전 등록마다
**기각 조건**(= 되돌릴 조건)이 있었다. #23 에는 되돌릴 것이 없다 -- 코드는
`49b4bdcc` 그대로다.

대신 **판정이 판정 불가로 끝나는 조건**을 미리 적는다. 그것이 이 표본에서
사후 합리화를 막는 유일한 장치다: 셋 중 하나를 고르는 것이 이 표본의 목적이면,
"고르지 않는다" 가 언제인지를 표본을 보기 전에 못박아야 한다.

### 2. 1차 지표 -- 세 버킷의 절대 손실 수

| 버킷 | 산식 | D92 의 후보 |
|---|---|---|
| `llm_drop` | Σ `node_summary`: `distinct_claims_prompt − distinct_claims_answer` | LLM 미탑재 -- 보여준 마커를 산문에 안 싣는다 |
| `own_claims_dropped` | Σ `node_reduction_degraded` where `answer_source == "children_join"`: `own_claims_available` | (가) 자기 클레임 침묵 폐기 |
| `truncation_drop` | Σ `node_reduction_degraded`: `before_bound − after_bound` | (나) `_bound_degraded_answer` 의 반절 자르기 |

셋은 **마커 단위로 서로소**다 -- 한 노드에서 잃은 마커는 그 위 노드의 프롬프트에
애초에 안 들어오므로 두 번 세어지지 않는다. 합이 의미를 갖는 근거가 이것이고,
§5 의 W-2 가 이 근거 자체를 검정한다.

**판독기:** `scripts/deep_analysis_reduction_attribution.py`.
**표본을 뜨기 전에 짓고 테스트 14개로 고정했다** -- §8.1.2 의 "계측을 먼저
의심한다" 를 권고가 아니라 순서로 지킨 것이다. 자가 지표는 이미 세 번 틀렸고
(#14 두 번 · #15 한 번), 그때마다 표본을 한 건씩 태웠다.

**미계측은 0 이 아니라 거부다.** #21·#22 의 페이로드에는 이 키가 하나도 없고,
없는 키를 0 으로 읽으면 판독기는 **세 후보가 전부 무죄라고 보고한다**. 이벤트가
하나라도 미계측이면 그 런을 판정에 넣지 않는다. 지금 #21·#22 에 돌리면
`not_instrumented` 가 나오는 것을 확인했다.

### 3. 판별 규칙 -- 표본을 보기 전에 고정한다

| 상수 | 값 | 왜 이 값인가 |
|---|---:|---|
| `DOMINANCE_SHARE` | 0.50 | 지배적이라 부르려면 합산 몫이 과반이어야 한다 |
| `DOMINANCE_MARGIN` | 2.0 | 0.50 하나만 걸면 0.51 대 0.49 도 "지배적" 이 된다. 그 둘은 사실상 같은 관측이다 |
| `MIN_MEDIAN_TOTAL_DROP` | 3 | 런별 총 손실 중앙값이 이보다 작으면 이 층에서 가를 것이 없다 |

**임계값 3 의 교정 근거 (실측).** #21·#22 열 런의 `selection` 격차
(`verified − 조립 프롬프트 최대치`) 중앙값은 **5.5** 다(#21 3 · #22 6).
세 버킷이 그 격차를 설명하면 3 을 넘고, 절반도 설명하지 못하면 못 넘는다.
⚠️ 이 격차는 시도별 **최댓값**으로 잰 것이라 D91 의 `selection` 비율
(0.56~0.63, 배달된 시도 기준)과 **같은 수가 아니다.** 나란히 놓지 말 것.

**판정은 합산과 런별 중앙값이 같은 버킷을 가리킬 때만 난다.** 합산만 보면
손실이 큰 한 런이 표본을 대표하고, 중앙값만 보면 작은 런이 큰 런과 같은
무게를 갖는다. 둘을 다 요구하는 것이 #18·#19 가 단일 지표로 튜닝했다가
총 증거를 잃은 데 대한 대가다.

**판정 코드 다섯. 순서가 규칙의 일부다** -- 앞의 셋을 뒤로 미루면 판정할 수
없는 표본에서도 버킷 이름이 나오고, 그 이름이 근거 없이 CE2 의 소재지를 정한다.

| 코드 | 조건 | 다음 수 |
|---|---|---|
| `not_instrumented` | 미계측 런이 하나라도 있다 | 판정하지 않는다. 남은 런으로 판정하는 것은 사후에 표본을 고르는 것이다 |
| `unattributed_gap` | 총 손실 중앙값 < 3 인데 selection 격차 중앙값 ≥ 3 | **넷째 기전이 있다.** D91 의 층 귀속은 살아 있고 후보 목록이 불완전하다 |
| `immaterial_loss` | 총 손실도 격차도 < 3 | **반증되는 것은 후보가 아니라 층 귀속이다.** 다음 수는 프롬프트가 아니라 층을 다시 찾는 것 |
| `no_single_dominant` | 위 규칙을 통과하는 버킷이 없다 | 억지로 최대값을 고르지 않는다. CE2 의 소재지는 미정으로 남는다 |
| `dominant` | 합산·중앙값이 같은 버킷 | 그 버킷이 CE2 의 소재지다 |

`unattributed_gap` 과 `immaterial_loss` 를 가른 이유를 적어 둔다: 둘은 **같은
관측**(총 손실이 작다)이지만 **다음 수가 정반대**다. 판정 시점에 사람이 가르면
그것이 사후 합리화이므로 코드로 갈랐다.

### 4. 사전 예상 -- 그리고 그것을 적는 이유

**예상: `own_claims_dropped`(가) 가 지배적이다.** 근거는 하나뿐이다 -- 강등이
152 건이고 잎이 아닌 노드는 자식 답이 있어 `children_join` 을 타므로, 그 노드에
자기 verified 클레임이 있으면 전부 침묵 폐기된다.

⚠️ **이 예상은 근거가 얇고, 적는 이유는 틀렸을 때 내가 알아보게 하려는 것이다.**
이 루프에서 사전 예상은 자주 틀렸다 -- #17 G-3 · #18 H-1 · #19 I-1 이 전부
반증이었다. 예상을 안 적으면 어느 결과가 나와도 "그럴 줄 알았다" 로 읽힌다.

### 5. 부작용 감시 (§13.4 -- 매번 같은 자리에서)

| 감시 | 기대 | 깨지면 |
|---|---|---|
| **W-1** | `invented` = 0 | 리덕션 층에도 마커 환각이 있다. ORPHAN2 의 자리가 조립 층 하나가 아니게 되고, 그것은 별도 항목이다 |
| **W-2** | `unattributed` 중앙값의 절댓값 ≤ 2 | **큰 양수**면 넷째 기전이 있다. **음수**면 §2 의 서로소 논거가 틀린 것이다 -- 버킷이 겹치면 합이 의미를 잃고 판정 전체를 다시 세워야 한다 |
| **W-3** | `node_summary` 대 `node_reduction_degraded` 비가 79:152 근처 | 크게 벗어나면 BUDGET2 의 압력이 움직인 것이고 #21·#22 와 나란히 읽을 수 없다 |
| **W-4** | 강등 사유 100% `input_bound` | 다른 사유가 섞이면 `_degraded_summary` 에 들어온 경로가 하나가 아니고, 세 후보의 모집단이 달라진다 |

W-1~W-4 는 기각 조건이 아니라 **해석 게이트**다. 깨지면 판정을 버리는 것이
아니라 판정을 읽기 전에 그것부터 읽는다.

### 6. 경계 -- 넷 중 어느 것도 가로지르지 않는다

| # | 커밋 | 상태 |
|---|---|---|
| 1 | `59e34624` (C3) | HEAD 의 조상 |
| 2 | `43303acd` (C3-m1) | HEAD 의 조상 |
| 3 | `e11953ad` → `b3abefaa` (E3, 판정자 `claude-opus-4-8`) | HEAD 의 조상 |
| 4 | `6ec71567` (G3-m1) | HEAD 의 조상. **D87 이 백테스트로 무효 경계임을 확인했다** |

**#22 와는 채점 계열이 이어진다**(판정자가 같다). **#21 이전과는 이어지지
않는다.** 그리고 이 표본의 1차 지표(세 버킷)는 #22 에도 없으므로 **계보가 없는
첫 관측**이다 -- 비교 대상이 아니라 기준선을 세우는 표본이다.

D92 가 적은 대로 CITE1 계측 자체는 **표본 경계가 아니다**(원장 쓰기만 늘었다).

### 7. 실행 조건

- **사전 등록 커밋이 표본보다 먼저**다 (§13.3 F2)
- `--verify-d92` 게이트가 서는 것 -- 지금 확인했다(79 · 152 · 152 · 15 재현)
- `preflight` 를 먼저 돌린다. D88 이 배운 것: 자격증명이 죽어 있으면 판정자가
  안 돌고, **못 돈 판정자는 통과처럼 보인다**
- dev 5 + default 1, **정확히 1회**. 실패해도 재시도하지 않는다 (§10.2)
- 매니페스트 없는 런이 있으면 아티팩트를 쓰지 않는다 (§15.4 금지 3번, 기계가 거부)

### 8. 이 표본이 하지 않는 것

- **CE1~CE3** -- 프롬프트를 한 글자도 안 바꾼다. §16.2 가 적은 대로 원인을
  모르는 채 프롬프트를 고치는 것이 D40·D51 이다
- **BUDGET2** -- `input_bound` 152/152 는 예산 항목이고 별도 표본이다.
  같은 표본에 얹는 것은 §13.5 정면 위반이다
- **C1 (discard recall)** -- 누적 설계가 선행이고, 얹으면 귀속이 불가능해진다

---

<a id="d94"></a>

## D94. D93 §7 개정 -- preflight 는 존재를 봤지 작동을 안 봤다 (2026-08-30, 실행 전)

D93 §7 이 실행 조건으로 "preflight 를 먼저 돌린다" 고 적었다. 돌렸고, **통과했고,
그 상태로 표본을 떴다면 6 런이 전멸했을 것이다.**

> 📌 **이것은 사전 등록의 수정이 아니라 조이기다.** D85 와 같은 논거다 -- §13.5 가
> 금지한 것은 판정을 **느슨하게** 만드는 방향이고, 여기서 더하는 것은 실행 조건을
> 통과하기 **더 어렵게** 만든다.

### 1. 실측 -- preflight 통과, 세 역할 전부 401

| 역할 | 모델 | 프로브 |
|---|---|---|
| scout | `claude-sonnet-5` | ❌ 401 `authentication_error` |
| dig · synth | `claude-opus-5` | ❌ 401 |
| judge | `claude-opus-4-8` | ❌ 401 |

키는 형태가 정상이고(`sk-ant-api03-` 접두사 · 108자 · 공백 없음) `/v1/models` 에
직접 쳐도 401 이라 **클라이언트나 요청 정규화가 아니라 키 자체가 무효**다.
`preflight` 는 그 키가 **빈 문자열이 아닌지**만 봤다.

### 2. 🔴 D88 의 교훈이 문서에만 있고 코드에 없었다

D88 은 정확히 이 고장을 겪었다 -- `OPENAI_API_KEY` 가 존재했고 401 이었고,
로드맵 §7.2 E3 행에 "배선은 옳았고 자격증명이 죽어 있었다" 로 적혀 있다.
그런데 그 판정이 만든 것은 **문장 하나**였고 `preflight` 는 그대로였다.

교훈을 적는 것과 교훈을 기계에 넣는 것은 다르다. §13.3 F2 가 사전 등록 게이트를
**"지침이 아니라 기계가 거부한다"** 로 쓴 것과 같은 구별이고, 이번에는 그
구별의 잘못된 쪽에 있었다.

**그리고 이번 것이 D88 보다 나쁘다:** D88 은 판정자 하나였고 이번은 워커까지다.
판정자만 죽으면 `judge=budget_exhausted` 계열의 가짜 통과가 나오지만, 워커까지
죽으면 표본에 남는 것이 없다.

### 3. 한 일 (`ac81037b`)

`preflight` 가 하네스 역할 넷이 해석하는 **고유 모델 집합**(실측 셋 --
dig·synth 가 같은 opus-5 다)에 최소 호출을 하나씩 보낸다. 인증과 **모델 서빙
가능 여부**를 함께 잡는다 -- 후자는 E3 가 `claude-opus-4-8` 을 카탈로그에
넣은 뒤로 미검증이었다(로드맵 §7.2 E3 행이 "가격은 미검증" 이라 적은 것의 이웃).

셋을 의도적으로 그렇게 뒀다.

| 선택 | 왜 |
|---|---|
| **빈 모델 집합은 실패** | 잴 것이 없는 것은 통과가 아니다. 역할 해석이 깨졌다는 뜻이고, 통과로 읽으면 이 변경이 없애려는 침묵이 **검사가 있다는 믿음과 함께** 돌아온다 |
| **실패한 모델을 전부 보고** | 하나씩 알려주면 사람이 그 왕복을 모델 수만큼 반복한다 |
| **시크릿만 지우고 문구는 남긴다** | P1 #8 이 접속 문자열 누출을 치렀다. 그러나 D88 의 진단을 가른 것은 **"401" 이라는 단어 자체**였다 |

프로브는 런 **밖**에서 돈다. `active_token_budget()` 이 없어 `reserve()` 를
거치지 않으므로 어느 런의 floor 산식도 움직이지 않는다 -- 그 토큰은 표본 회계
밖에 있고 그것이 의도다. **표본 경계가 아니다**(하네스 실행 경로 무변경).

### 4. ⚠️ 검증하지 못한 것

`PROBE_MAX_TOKENS = 64` 가 adaptive thinking 모델에 충분한지 **확인하지 못했다** --
작동하는 키가 없었다. 모자라면 프로브가 실패하고 preflight 가 거부한다.
거짓 경보는 되돌릴 수 있고 거짓 통과는 표본을 태우므로 방향은 옳으나,
**새 키가 들어오면 가장 먼저 확인할 것이 이것이다.**

### 5. 표본 #23 의 상태

🔴 **뜰 수 없다.** D93 은 그대로 유효하고 판독기도 서 있으나, 실행 조건이
자격증명에서 막혀 있다. **새 `ANTHROPIC_API_KEY` 가 선행이다.**

⚠️ **막힌 동안 프롬프트를 손대지 않는다.** §16.2 가 CE1~CE3 을 CITE1 판정 전
착수 금지로 묶었고, 표본이 지연된다는 것이 그 금지를 푸는 사유가 아니다 --
오히려 "기다리는 동안 뭐라도 하자" 가 D40·D51 이 시작된 자리다.

---

<a id="d95"></a>

## D95. Anthropic 클라이언트를 한 곳으로 -- identity-linked 키가 드러낸 사본 아홉 개 (2026-09-01)

D94 가 preflight 를 조인 뒤 새 키로 다시 돌렸더니 401 이 400 으로 바뀌었다.
**진전이지만 통과는 아니다** -- 새 키는 identity-linked 라 요청마다
`anthropic-workspace-id` 를 요구하고, 저장소는 그 헤더를 보내지 않았다.

### 1. 고쳐야 할 자리가 아홉 곳이었다

`AsyncAnthropic(...)` 를 각자 짓는 지점이 아홉이다 -- deep_analysis 콜러 ·
코딩 런타임 · 챗 서비스 둘 · 아티팩트 서비스 · 문서 파이프라인 · 비전
파이프라인 · LangChain 프로바이더.

**헤더를 아홉 번 적는 것이 답이 아닌 이유는 §7 CA12 가 이미 적어 뒀다.**
그 항목이 추적하는 것은 "카탈로그가 안 갖는 새 사실 범주" 가 여러 파일에
하드코딩되는 것이고, 워크스페이스 ID 는 정확히 그 범주다 -- 모델 사실도
가격도 아닌 **계정 사실**이며, 사본이 아홉이면 다음 사람이 여덟 곳만 고친다.

그래서 팩토리(`neos/utils/anthropic_client.py`)를 먼저 두고 아홉이 그것을
부른다. **열 번째 사본이 생기면 빨개지는 테스트**를 함께 넣었다 -- 이런
드리프트는 누가 결정해서 자라는 것이 아니라 조용한 추가로 자란다.

### 2. "워크스페이스가 없으면 지금과 같다" 를 좁게 주장한다

`default_headers` 를 **아예 넘기지 않는다**. 빈 매핑을 넘기는 것과 다르다 --
빈 헤더는 identity 가 아닌 키에 **새 실패**를 만들 수 있고, 그러면 이 변경이
멀쩡한 배포를 깬다. 무해하다는 주장 전부가 그 한 가지에 걸려 있어서
테스트가 그것을 직접 단언한다(빈 문자열·공백만 있는 값 포함).

명시 `api_key` 는 설정을 이긴다. `neos/coding/runtime.py` 는 관리형 샌드박스의
시크릿 원천에서 키를 가져오므로, 팩토리가 전역 키를 강제하면 그 경로가
**조용히 틀린 자격증명으로** 돈다.

### 3. `ANTHROPIC_WORKSPACE_ID` 는 YAML 이 아니라 `.env` 다

시크릿은 아니다. 그러나 **키와 짝**이다 -- 짝이 어긋나면 요청 시점에 실패하고,
키를 갈면 워크스페이스가 바뀔 수 있다. 정책이 아니라 배포 신원이므로 정책이
있는 곳이 아니라 키가 있는 곳에 둔다. `SecretsConfig` · `SECRET_ENV_KEYS` ·
`.env.template` · `docs/CONFIGURATION.md` · `docs/CONFIG_INVENTORY.md`.

### 4. 🔴 전체 스위트에서 13건이 빨개졌고 그것이 옳은 신호였다

테스트 네 모듈이 **각자의 호출 지점 이름**을 패치하고 있었다
(`runtime_module.AsyncAnthropic`, `chat_llm_service.anthropic.AsyncAnthropic` …).
생성을 한 곳으로 모으면 이음매도 한 곳이 된다.

단언을 느슨하게 푸는 대신 **새 이음매를 가리키게** 고쳤다 -- 대역이 옛 이름을
계속 잡게 하려고 프로덕션에 죽은 별칭을 남기는 것은 D92 가 "부분 일치로
느슨하게 바꾸지 않았다" 로 거절한 것과 같은 종류의 타협이다.

실측: **3,405 passed / 0 failed** · 수집 증분 10 = 신규 테스트 10.

### 5. 남은 것 -- 그리고 이것으로도 안 될 수 있다

`ANTHROPIC_WORKSPACE_ID` 값이 아직 없다. 넣으면 preflight 부터 다시 잇는다.

⚠️ **헤더가 붙어도 실패가 남아 있을 수 있다:** 그 키가 판정자
`claude-opus-4-8` 과 워커 `claude-opus-5`·`claude-sonnet-5` 셋 **모두**에
접근 권한을 갖는지는 미지수다. preflight 가 셋을 각각 부르므로 그 경우
**어느 모델이 막혔는지까지 한 번에** 나온다 -- D94 가 그렇게 설계된 이유다.

**표본 #23 과 D93 은 그대로다.** 이 변경은 전송 계층이고 프롬프트·모델·
임계값·캡을 건드리지 않는다. **표본 경계가 아니다.**

## D96. 표본이 막힌 동안 코드 인벤토리를 비운다 -- 그리고 그 대가로 경계가 둘 늘었다 (2026-09-01)

D95 가 `ANTHROPIC_WORKSPACE_ID` 값 하나에 표본 #23 을 걸어 두었다. 값이 오기를
기다리는 동안 **라이브 표본을 쓰지 않는 항목**만 골라 여섯을 닫았다.

이 결정의 값어치는 여섯이 아니라 **마지막 절**에 있다. 배칭이 무엇을 부쉈는지를
적지 않으면 다음 사람이 D93 을 그대로 집어 든다.

### 1. 닫은 여섯

| 항목 | 무엇이었나 | 표본 경계 |
|---|---|---|
| **BUDGET2** | 클램프가 예산을 몰랐다 (아래 §2) | 🔴 **예** |
| **D2** | `fetch_url` 에 재시도가 한 줄도 없었다 | 🔴 **예** |
| **PREFLIGHT2** | D94 의 고침이 둘째 호출부에 안 갔다 (아래 §3) | 아니오 |
| **CA12** | 둘째 모델 사실 테이블 → 카탈로그 | 아니오 |
| **§14.4** | `writes` 기계 검증 5/30 → **18/31** | 아니오 |
| **C1 누적** | n≥35 를 여러 세션으로 모으는 설계 | 아니오 |

### 2. BUDGET2 -- 152건은 분포가 아니라 한 줄의 산술이었다

D92 는 `node_summary` 79 대 `node_reduction_degraded` 152 를 재고 **152 전부가
`reason=input_bound`** 라는 것까지 확인했다. 사유 하나가 전부를 덮는 것은
원인이 여럿이라는 신호가 아니라 **기전이 하나**라는 서명이고, 그 기전은 코드에서
읽힌다:

- `reduce_node` 의 클램프는 `reduction_input_allowance`
  (= `reduction_input_ratio × synthesis_max_tokens`) 를 겨눈다 -- **런 내내 상수**다.
- `reserve()` 는 `available_for_reduction` 으로 채점한다 -- 리덕션이 하나씩 돌수록
  **줄어든다**.

두 수가 교차하는 순간부터 클램프는 "맞는다" 고 판정하고 예산은 거절한다.
**클램프가 예산을 몰랐다.**

`effective_reduction_allowance()` 가 둘 중 작은 것을 쓴다.
`min_viable_output_tokens` 를 빼는 이유는 G8 이 출력 쪽에서 배운 것과 같다 --
예약은 *맞는* 프롬프트가 아니라 **답할 자리가 남는** 프롬프트에 나온다.

🔴 **가드 하나를 함께 뒀고, 그것이 이 변경에서 유일한 정책 선택이다.**
예산에 맞춰 조이는 것은 옳지만 **마커를 전부 잘라낸 프롬프트**를 만드는 지점까지
가면 그 뒤는 다르다: 모델은 여전히 유창한 산문을 쓰고 **인용할 수 있는 것은 하나도
없다.** 강등 join 은 같은 클레임을 `[C:...]` 를 달고 결정론적으로 잇는다. 예약을
태워 인용 가능한 텍스트를 인용 **불가능한** 텍스트로 바꾸는 것은 §3.2 가 이
저장소의 관통 주제로 적은 조용한 실패라, 그 경우 모델을 부르지 않고
`reason=reduction_allowance_below_claim_floor` 로 강등한다.

발동 조건을 좁게 걸었다 -- **입력에 마커가 있었는데** 클램프된 프롬프트에 없을
때만이다. 애초에 마커가 없는 노드는 그대로 모델로 간다. 안 그러면 가드가 자기
조건과 무관한 노드를 삼키고 `reason` 어휘가 거짓을 말하기 시작한다.

**`assemble` 은 일부러 두었다.** 같은 산술 격차가 거기에도 있으나 그 티어는 지금
이 방식으로 실패하고 있지 않다(표본 #21: clamp `exhausted` **0**). 멀쩡한 티어를
건드리면 아무도 묻지 않은 질문에 답하려고 표본 경계를 하나 더 사는 셈이다.

### 3. PREFLIGHT2 -- 고침은 한 호출부에만 도착했다

D94 가 `funnel_sample_runner.preflight` 에 실제 호출을 넣었다. **둘째 호출부**인
`scripts/deep_analysis_discard_recall.py` 는 존재만 보는 사본을 그대로 들고 있었고,
그 독스트링은 `"Mirrors the shape of funnel_sample_runner.preflight"` 라고 적고
있었다 -- **한때 참이었기 때문에 아무도 다시 열지 않았다.**

🔴 **이쪽이 더 조용하다.** 이 스크립트는 discard 클레임 **하나하나에** 판정자를
부르는데, 죽은 키는 `grade_fn` 의 `except` 에 claim 단위로 삼켜져 `grade_errors`
로 세어지고 각각 **not verified** 로 계산된다. 즉 패스는 완주하고 아티팩트는
정상적으로 쓰이며, 거기 실린 false-discard 비율은 **정전이 만든 수**다. D88 이
"못 돈 판정자는 통과처럼 보인다" 로 적은 것의 더 나쁜 판본이다 -- 그때는 통과가
가짜였고 여기서는 **측정값 자체**가 가짜다.

공유 preflight 에 `models`·`credentials` 를 열고 이 스크립트가 그것을 부른다.
판정자만 프로브한다: 결정론 채점기는 LLM 을 쓰지 않고, 워커 모델은
`judge != worker` 검사를 위해 **지문에 실릴 뿐** 이 경로에서 불리지 않는다.
넷을 다 프로브하면 이 측정이 갖지 않는 의존성을 증명하느라 토큰을 쓰고, 무관한
워커 장애가 성공했을 채점을 막는다.

빈 자격증명 집합은 **실패**다 -- 빈 모델 집합이 이미 그런 것과 같은 이유다.

🔍 곁가지: 이 파일이 `model_roles.py` 가 없애려던 역할 리터럴의 **열한 번째 사본**을
들고 있었다(그 모듈 독스트링은 열까지 센다). `provider="anthropic"` 을 무조건
넘겨 `_provider_for` 가 고친 거짓 보고를 재현하고 있었고, 그 값은 재생성 불가능한
아티팩트의 지문에 실린다.

### 4. 🔴 배칭의 대가 -- 경계가 둘 늘었고 **D93 이 무효가 됐다**

| # | 무엇이 바뀌었나 | 무엇을 비교할 수 없나 |
|---|---|---|
| 5 | BUDGET2 | 리덕션 층 전부 -- `node_summary` 대 강등 비, `input_bound` 건수, 그 아래로 흐르는 조립 입력 |
| 6 | D2 | 확보한 증거의 양 -- tier1 비율, verified 클레임 수, 거기 매달린 모든 하류 수치 |

D92 재현 게이트(79·152·152·15)는 **살아 있다.** 그것은 #21·#22 의 저장된 원장을
읽으므로 새 코드가 닿지 않는다. 판독기와 테스트 14개도 그대로 쓴다.

**무효가 된 것은 D93 의 사전 등록이다.** D93 은 `input_bound` 가 아직 열린
후보이던 코드를 전제로 판별 규칙을 못박았는데, **BUDGET2 가 정확히 그 후보를
겨눈다.** 지금 표본을 뜨면 한 런이 *"원인이 무엇이었나"* 와 *"고친 것이 들었나"* 를
동시에 묻게 되고, 그것이 §13.5 가 금지한 "여러 변경을 한 표본에" 다.

### 5. 그래서 D-14 를 신설한다 (§9)

**질문:** BUDGET2 의 효과와 CITE1 의 원인 판별을 같은 표본에서 잴 것인가.

**권고: 분리(A).** 근거는 §8.1.2 의 두 문장을 나란히 놓으면 나온다 --
원인을 모르는 채 고치면 D40·D51 이고, **고친 뒤에 원인을 물으면 무엇을 쟀는지
모른다.** 되돌리는 선택지(C)는 권하지 않는다: 기전이 코드에서 확정됐고
되돌리는 것은 알면서 두는 것이다.

⚠️ **분리해도 D2 는 같은 표본에 있다.** 다른 층(retrieval)이라 리덕션 지표와
귀속이 섞이지는 않으나 `verified` 클레임 수가 움직이면 **분모가 바뀐다.**
다음 사전 등록은 `fetch_*` 를 부작용 감시로 함께 봐야 한다.

### 6. CA12 가 드러낸 것 -- `claude-opus-5` 는 세대 사실이 없다

표를 옮기면서 둘이 나왔다.

**(a) 두 표가 서로 다른 접두사 어휘를 쓰고 있었다.** `claude-opus-4-5` ·
`claude-mythos-preview` · `claude-3-5-haiku` 는 캐시 표에만 있고 advisor 표에는
없다. 지우지 않고 `family` 생략으로 표현했다.

**(b) 🔴 `claude-opus-5` 는 어느 표에도 없다.** 하네스의 `powerful` 워커
(dig·synth)이고 피커의 `powerful` 티어인데 접두사표는 opus-4.5~4.8 만 알고
**5 세대를 배운 적이 없다.** advisor 를 켜면 `unknown_executor_model` 로 조용히
미주입되고, 캐시 하한은 미검증 기본값 1024 다.

**값을 지어내지 않았다** -- §4.3 의 "확인 못 한 모델은 추측하지 않는다" 다.
`tests/config/test_anthropic_model_families.py` 의 `_UNCOVERED` 가 공백을 이름으로
들고 **양방향으로** 고정한다(메워져도 실패한다).

### 7. §14.4 -- 낡은 면제 13개가 한꺼번에 드러났다

`state_keys_written` 이 **반환 위치의 위임만** 따라간다. `reads` 처럼 전부
따라가지 않는 이유는 두 필드의 위험 방향이 반대이기 때문이다 -- `reads` 는
선언이 적으면 위험하고 `writes` 는 **많으면** 위험하다(`_guaranteed_keys` 가
그것을 믿는다). 중간에서 받아 다른 dict 에 담는 위임까지 쫓으면 추출기가 상태로
나가지 않는 키를 "확인" 해 주고 검증기가 깨진 토폴로지를 승인한다.

🔴 **그 개선 하나로 `writes_hand_curated=True` 13개가 동시에 거짓이 됐는데
아무것도 빨개지지 않았다.** 면제 플래그는 "기계가 못 본다" 는 **주장**이고, 참인
동안 가드는 그 노드를 건너뛴다 -- 낡은 면제는 **조용히 꺼진 가드**이고, §7 이
유령 백로그라 부른 것의 플래그 판본이다. 반대 방향 단언을 새로 걸었다.

### 8. 실측

시드 **3·7·12345** 전부 **3,472 passed / 63 skipped / 0 failed**, 각각 1:59·2:00·2:03.
시드 7 은 §7.4 가 10시간 46분 멈췄던 그 시드다. 수집 증분 **+67 = 추가한 테스트 수**.

🔴 **그 과정에서 내가 측정을 한 번 망쳤고, 기록해 둔다.** 시드 7 실행이 도는 도중에
수집 수를 재려고 `git stash` 를 걸어서 그 실행이 **스테이시된 트리**를 채점했다
(3,405 + 63 = 3,468 = 변경 전 수집 수). 초록이었고 개수도 평소 범위라 그럴듯해
보였으며 **합이 안 맞는 것으로만** 잡혔다. §10.2 가 라이브 표본에 대해 적은
규칙이 스위트에도 그대로 걸린다: **측정이 도는 동안 대상을 바꾸지 말 것.**

### 9. D95 §5 의 마지막 줄을 정정한다

D95 는 *"표본 #23 과 D93 은 그대로다"* 로 끝난다. 그 문장은 D95 자신에 대해서는
지금도 참이다(전송 계층이다). 그러나 **이 결정 이후로 D93 은 그대로가 아니다** --
위 §4 를 함께 읽어야 한다.

### 10. 🔴 기대값을 **지금** 적는다 -- 표본 설계보다 먼저

§13.1 이 "사전 등록이 표본보다 먼저다" 로 적은 것의 가장 약한 지점이 여기다.
BUDGET2·D2 는 **다음에 측정될 코드**이고, D-14 가 열려 있어 표본 설계는 아직
없다. 설계를 기다렸다가 기대값을 적으면 그 사이에 내가 코드를 더 읽게 되고,
그때 적는 것은 기대가 아니라 **아는 것의 재진술**이다.

그래서 표본이 어떻게 설계되든 무관한 **반증 가능한 문장**만 지금 못박는다.
D-14 가 어느 쪽으로 결정되든 이 표는 그대로 쓰인다.

**BUDGET2**

| # | 기대 | 반증 |
|---|---|---|
| **P-1** | `node_reduction_degraded` 중 `reason=input_bound` 의 **비율**이 내려간다 (#21·#22 는 152/152 = 100%) | 비율이 90% 이상으로 남는다 → 기전 지목이 틀렸다. 그 경우 클램프가 아니라 **티어 자체가 비어 있는 것**(`cause=tier_floor`)이고 고칠 곳은 floor 산식이다 |
| **P-2** | `node_summary` 대 `node_reduction_degraded` 비가 79:152 보다 올라간다 | 안 오르면 P-1 이 참이어도 리덕션이 다른 사유로 막힌 것이다 |
| **P-3** | 새 사유 `reduction_allowance_below_claim_floor` 가 **0 이 아니되 소수**다 | 그것이 강등의 과반이면 티어가 너무 좁아 가드만 계속 발동하는 것이고, BUDGET2 는 문제를 **옮겼을 뿐**이다 |

⚠️ **인용 생산 비율(D90)의 개선은 기대하지 않는다.** 리덕션이 LLM 에 더 닿는
것과 그 LLM 이 마커를 싣는 것은 다른 문장이고, 후자는 D92 의 나머지 두 후보가
답한다. **여기서 인용 비율이 올랐다고 "고쳤다" 고 읽으면 D51 의 반복이다** --
읽지 않은 이벤트로 추론하는 것.

**D2**

| # | 기대 | 반증 |
|---|---|---|
| **Q-1** | `fetch_retrying` > 0 · `fetch_exhausted` < `fetch_retrying` | `exhausted` 가 `retrying` 과 같으면 재시도가 한 번도 성공하지 못한 것이고, 429 창이 이 fetch 보다 길다는 뜻이다 → `fetch_max_attempts` 가 아니라 다른 접근이 필요하다 |
| **Q-2** | `fetch_refused_403` 이 **관측된다** (0 이 아니거나, 0 이라는 것이 처음으로 확인된다) | — 이것은 기대가 아니라 **D2 가 원래 답하려던 질문**이다. "403 잔존" 은 세지 않아서 답이 없었다 |
| **Q-3** | verified 클레임 수가 #22 의 74 에서 **내려가지 않는다** | 내려가면 재시도가 벽시계를 태워 조사 패스를 줄인 것이다 (§7 A3·A4 계열) |

⚠️ **Q-3 이 부작용 감시다.** D2 는 증거를 더 확보하려는 변경이지만 재시도는
시간을 쓰고, 조사는 벽시계 상한을 갖는다. **더 얻으려다 덜 얻는 것**이 이
변경의 고유 위험이고, 그것을 안 보면 순증으로 오독한다.

**표본이 답하지 않는 것.** 위 여섯 중 어느 것도 "게이트 통과율이 오르는가" 를
묻지 않는다. #21 이 이미 그 연결을 끊었고(재료 +21%, 통과 1 → 0), 여기서
다시 통과를 1차 지표로 쓰면 §8.1.1 이 분리해 낸 사실을 도로 뭉갠다.
