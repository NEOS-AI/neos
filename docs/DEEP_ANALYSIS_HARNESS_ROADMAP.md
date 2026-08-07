# 심층분석 하네스 + 역할 기반 모델 라우팅 — 통합 로드맵

**작성일:** 2026-08-04
**작업 브랜치:** `dev` (worktree 없이 직접 작업 중)
**범위:** `neos/workflow/deep_analysis/` 하네스와 `neos/config/model_routing.py` 계열의
모델 라우팅, 그리고 두 트랙을 소비하는 프론트엔드(`web/`) — 세 트랙의 로드맵,
진행 경과, 미해결 이슈, 실행 순서, 최종 방향성

**근거 문서 (이 문서는 이들의 종합이며 대체가 아니다):**

| 문서 | 역할 |
|---|---|
| [DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md) | 설계 정본 — 5원칙·DDL·컴포넌트 명세·마일스톤 |
| [deep_analysis_task_task_resume.md](archive/deep_analysis_task_task_resume.md) | 하네스 작업 계보와 재개 절차 |
| [role_based_model_routing_task_resume.md](archive/role_based_model_routing_task_resume.md) | 라우팅 작업 결과와 잔여 이슈 |
| [TODO_260729.md](TODO_260729.md) | 미해결 백로그 원장 — A·B·C·D·E·F·G 계열 실측 수치 |
| [FE_AUDIT_260717.md](FE_AUDIT_260717.md) | 프론트엔드 감사 — §6이 job 서비스 전환 준비도를 판정 (트랙 C의 기준선) |
| `neos/workflow/deep_analysis/DECISIONS.md` | 결정 원장 D1–D25 |

> ⚠️ **진행 상황의 근거 규칙.** 플랜 문서(`docs/superpowers/plans/*`)의 체크박스는
> 43개 전부 `- [x]`가 0개다. **신뢰하지 말 것.** 실제 진행은 (1) git 커밋,
> (2) `.superpowers/sdd/<plan>/progress.md`, (3) `DECISIONS.md`의 D 번호,
> (4) `deep_analysis_events` 테이블의 실측에만 기록되어 있다.

---

## 1. 한눈에 보는 현재 상태

| 트랙 | 상태 | 다음 관문 |
|---|---|---|
| **A. 심층분석 하네스** | 🟡 코어 완성, **산출물 미달** | 마무리 예산 구조 완료(G6·G7 해소) — 남은 것은 라이브 표본으로 `synth_pass`를 확인하는 것 (W1, 아직 미실행) |
| **B. 역할 기반 모델 라우팅** | ✅ 완료 · 안정 | 유지보수 모드. 카탈로그 불변식 지키기 |
| **C. 프론트엔드** | ✅ job 마이그레이션 완료, 🟡 **가시성 갭** | 새 실패 이벤트 8종이 UI에 라벨 없이 흘러간다 (§5.2) |

**트랙 A 한 줄 요약 (2026-08-04 실측):**
사용자에게 나간 deep-analysis 리포트 중 **LLM이 작성한 것은 아직 0건이다.**
574 run · 183 `report_graded` 동안 `synth_pass`가 한 번도 기록되지 않았고,
G8 수정 후 재측정에서도 6/6 run이 전부 `Synthesizer.deterministic_report()`
템플릿을 냈다. 조사·검증 파이프라인은 동작하지만 **마무리가 굶는다.**

**트랙 B 한 줄 요약:**
플랜 6개 태스크 + 잔여 이슈 I1–I6 전부 종결. 모델 *사실*은
`neos/config/models.yaml` 단일 원천으로 모였고, 배포 *정책*(`model_routing`)과
분리돼 있다. 백엔드 2234 passed / 0 failed, 게이트웨이 5/5, 프론트 `tsc` clean.

**트랙 C 한 줄 요약 (2026-08-04 실측):**
`docs/FE_AUDIT_260717.md` §6이 "미준비"로 판정했던 job 서비스 전환 차단 요인
**5개가 전부 해소**됐다 — run 스트림 프록시·커서 재구독·active-run-store가
약 1,665줄로 구현돼 있고 `pnpm test:source` 147 passed. 남은 것은 기능이 아니라
**가시성**이다: 08-02~04에 추가한 실패 이벤트 8종에 FE 라벨이 없다.

**기본 플래그:** `deep_analysis.enabled = False` (`neos/config/schema.py:613`).
즉 세 트랙 모두 **프로덕션 기본 경로에는 아직 없다** — 프론트엔드 UI도 백엔드가
job을 dispatch해야 살아나므로 이 플래그에 함께 묶여 있다.

---

## 2. 최종 방향성 (북극성)

세부 과제를 어느 순서로 할지 헷갈릴 때 돌아올 기준이다.

### 2.1 목표 상태

> **검증형 분석(deep_analysis loop)을 NEOS의 1차 실행 모델로 승격한다.**
> 사용자가 "이 주장이 사실인가"를 물으면, 모든 문장이 검증된 클레임으로
> 역추적되는 LLM 작성 리포트가 나온다. 실패하면 조용히 degrade하지 않고
> 원장에 이유를 남긴다.

`docs/ROADMAP.md`의 「Loop 아키텍처 통합 3단계」와 같은 목표이며,
단계 2(엔진 재배치)·단계 3(Job 서비스)은 D21·D22·D23으로 **이미 완료**됐다.
남은 것은 **품질 게이트를 통과시키는 일**이다.

### 2.2 `enabled = True`로 전환하기 위한 출하 기준

아래 6개가 전부 참이 되기 전에는 기본 활성화하지 않는다.

| # | 기준 | 현재 | 측정 방법 |
|---|---|---|---|
| S1 | LLM이 조립한 리포트가 실제로 나온다 | ❌ `synth_pass` 0건 | `deep_analysis_events` `kind='synth_pass'` |
| S2 | 리포트 게이트가 알맹이 있는 리포트를 통과시킨다 | ❌ 통과 9건 중 7건이 claim 0건 | `report_graded` × run별 verified claim 수 |
| S3 | 리포트 본문이 보존된다 | ❌ `report_path` 574 run 전부 NULL | reports 테이블 |
| S4 | 정지 사유가 원장에서 정확히 구분된다 | ⚠️ 6건 중 4건 오분류 (G9) | `token_budget_exhausted` vs `investigation_stopped_at_floor` |
| S5 | 전체 스위트가 CI에서 결정론적으로 통과한다 | ⚠️ 선결 3건 (#9·#10·#11) | CI 워크플로 |
| S6 | 실패가 사용자에게도 보인다 (원장뿐 아니라 UI에서) | ❌ 실패 이벤트 8종에 FE 라벨 없음 | `progress.ts`의 `activityLabel()` 커버리지 |

> S6은 나중에 추가됐다(2026-08-04, 트랙 C 확인 중). S1~S5를 다 채워도 사용자가
> 여전히 강등을 모른다면 "조용한 실패"를 고쳤다고 할 수 없기 때문이다.

### 2.3 절대 타협하지 않는 것

설계 §1의 5원칙과 §11 금지사항은 **모든 성능·비용 논의보다 우선**한다.
특히 아래 넷은 지금까지의 모든 사고에서 방어선 역할을 했다.

- **P2 단일 작성자** — 원장 쓰기는 오케스트레이터 한 곳
- **judge ≠ worker** — 자기 승인 편향 방지 (지금 위반 중, §6 E3 참조)
- **append-only 이벤트 로그** — UPDATE/DELETE 금지 (D8)
- **매직넘버 금지** — 전부 settings. 프롬프트는 전부 파일

---

## 3. 트랙 A — 심층분석 하네스

### 3.1 설계가 약속한 파이프라인

```
루트 질문
  → decompose (3~7 서브질문)
  → [라운드 루프] Budgeter.select → Worker 병렬 조사 → 결정론 채점 → 에이전틱 채점
                  → verified/rejected 커밋 → 서브질문 심사 → should_stop?
  → Synthesizer.reduce (계층 리듀스, 충돌 해소)
  → 최종 조립 (LLM) → CitationRenderer → ReportGrader → 산출
```

이 중 **굵은 절반(라운드 루프)은 동작한다.** 문제는 마지막 줄이다.

### 3.2 진행 계보 — 무엇을 언제 지었나

```
2026-07-09~10  M0–M4 하네스 코어                      ✅ Ledger/Budgeter/Grader/Cassette/Synthesizer
      ↓
07-11          A. 프로덕션 챗 경로 편입 (D18)          ✅ → ⚠️ D23으로 대체됨
07-11          B. L5 개선 루프 (D19)                  ✅ analytics + API + Celery beat + golden gate
      ↓
07-17~19       스킬 발견 통합 / 엔진 재배치 (D21)      ✅ 복잡도 임계값 → 질의 유형
07-18~19       durable job 서비스 (D22/D23)           ✅ 제출·스트림·resume, 챗은 "제출자"
      ↓
07-19~21       운영 안정화 8종                        ✅ 토큰캡·브로커·PDF·영속화·NUL·CI격리·플래그
      ↓
07-19~25       verified claim 비율 개선 루프           ✅ 퍼널진단 → 클램프 → grounding v3 → entailment
07-25~26       entailment 실측 평가                   ✅ 결론: 비율↑는 노이즈와 구별 불가, pool은 -42%
07-28~29       discard recall 측정                    🟡 n=0으로 `inconclusive`
      ↓
08-02~04       "조용한 실패" 계열                     🟡 A1·A2·G1·G2·G8 해소, G5 부분, G6·G7 해소(D25)
```

**7월 말~8월 초 구간을 관통하는 주제 하나:**
> **이 시스템의 모든 실패가 성공처럼 보였다.** truncation fallback, 템플릿 리포트,
> 굶은 판정자 — 전부 조용히 degrade했고 원장에는 성공과 구별되지 않는 흔적만
> 남았다. 이 구간의 작업은 대부분 **고치기 전에 보이게 만드는** 일이었다.

이 원칙은 앞으로도 유지한다: **새 fallback을 추가하려면 그 fallback이 남기는
이벤트를 함께 정의한다.**

### 3.3 설계와 관측의 갭 — 가장 중요한 표

| 설계 문서의 서술 | 2026-08-04 실측 |
|---|---|
| §6.7 "최종 조립: 단일 컨텍스트가 final_compose.md로 작성" | **한 번도 실행된 적 없음.** `synth_pass` 0 / 574 run |
| §6.8 "에이전틱 판정 2개: 루트 질문에 답하는가 / 주장 강도" | **한 번도 실행된 적 없음.** `report_grading` 예약 0건 |
| §6.8 "실패 시 조립 재시도, 캡 2회" | 재조립 2회가 **결과를 바꾼 적이 한 번도 없음** (실패 52건 전부 3회 소진) |
| §6.8 결정론 게이트 "마커 없는 단정문 < 20%" | **템플릿 리포트를 채점 중.** "uncited 비율 1.0"은 LLM 실패가 아니라 템플릿에 각주가 없다는 뜻 |
| G5 §3.1 "마무리 단계는 항상 0이 아닌 예약을 받는다" | **과장이었다.** 정확히는 "조사가 마무리를 굶히지는 않는다" (2026-08-03 정정) |

> **읽는 법:** 설계 §6.7·§6.8은 **설계 의도이지 관측된 동작이 아니다.**
> 게이트 통계를 인용할 때 반드시 이 전제를 붙일 것.

### 3.4 이전 프론티어 — G6 · G7 (2026-08-04 해소, §3.5로 이동)

G5(마무리 예산 floor)는 조사가 마무리 몫을 침범하지 못하게 막는 데는 성공했다.
그런데도 조립이 예약을 못 받았다. 원인 두 가지가 **실측으로 확정**됐고, D25가
`report_floor_tokens` 안쪽 tier + 입력 통화 사이징으로 둘 다 해소했다. 아래는
당시 실측 기록이며, 해소 사실 자체는 §3.5를 볼 것.

**✅ (해소) G6 — floor가 input을 계산에 넣지 않는다**

`floor = (allowance+1) × synthesis + judge`는 **output 토큰만** 센다. 반면
`reserve()`는 `conservative_input_bound`로 프롬프트 전체(UTF-8 바이트 + 64)를
함께 부과한다. 한국어는 문자당 약 3바이트라 클레임 몇 건이면 input만으로 floor를
넘는다.

| stage | n | `input_bound` (min/중앙/max) |
|---|---:|---|
| worker_analysis | 26 | 5,542 / 10,893 / 17,723 |
| **node_reduction** | 22 | 1,225 / 1,369 / **6,480** |
| claim_entailment | 20 | 2,959 / 3,452 / 4,572 |

`node_reduction` 한 번이 최대 6,480을 input으로만 쓴다 — **dev floor 4,400 전체보다 크다.**

**✅ (해소) G7 — floor가 하나의 통합 풀이라 호출 횟수가 강제되지 않는다**

`finalization_reduction_allowance=2`는 floor의 **크기**만 정하고 실제
`reduce_node` 호출 수를 제한하지 않는다. default run `20c4798f`(floor 12,800) 추적:

| stage | 예약 | `input_bound` | `max_out` |
|---|---:|---:|---:|
| node_reduction | 7,984 | 3,984 | 4,000 |
| node_reduction | 8,324 | 4,324 | 4,000 |
| node_reduction | 10,116 | 6,480 | 3,636 |
| **report_assembly** | — | — | **예약 없음** |

세 번째 reduction이 조립 몫을 먹었다. 6 run 평균 **3.7회 vs allowance 2** — 상시 초과.

**왜 이 둘이 1순위인가.** claim recall(§C1), 게이트 임계값(§G3), 판정자 상한(§A3·A4)
전부 **리포트에 클레임이 실제로 실린 뒤에야** 의미가 있다. 지금은 그 아래에서
측정하고 있는 셈이다.

### 3.5 최근 해소된 것 (되돌리지 말 것)

| 항목 | 내용 | 커밋 |
|---|---|---|
| A2 | `stop_reason` 전파 — 잘린 응답 ≠ 파싱 실패한 쓰레기. `call_json` 1회 확장 재시도(2배) | 2026-08-02 |
| A1 | `report.py` 판정자 상한 300 → 800 | `a92fa4f9` |
| G2 | `report_graded`에 `uncited_ratio`·분자·분모·임계값 적재 | `56b28f3e` |
| G1 | "게이트 문제인가 §7 하류 증상인가" → **게이트 문제로 확정** | 2026-08-03 |
| G5 | `TokenBudget.floor_tokens` + `available_for_investigation` (부분 완료) | 2026-08-03 |
| G8 | `min_viable_output_tokens`(2,048) 미만 예약 거절 — dev run 0/5 → **5/5** | `71769b0f` |
| G7 | `REPORT_STAGES`(assembly·grading) 전용 안쪽 tier — 리덕션이 조립 몫에 닿지 못한다 | `c9a05d19` |
| G6 | floor를 입력 통화로 재사이징 — 비율 3종을 `synthesis_max_tokens`에서 유도, dev cap 20,000 → 100,000 | `5376048a` |

> G8은 **회귀 대응**이었다. floor 도입이 dev run을 100% 죽였고(25 토큰짜리 JSON
> decompose가 반드시 잘림), 그것이 하드 에러가 되어 job까지 전파됐다.
> 교훈: **예산 하한은 "1토큰이라도 남으면 진행"이 아니라 "유효한 호출 하나를
> 낼 수 있는가"로 판단해야 한다.**

---

## 4. 트랙 B — 역할 기반 모델 라우팅

### 4.1 완료된 것

| 구간 | 내용 | 커밋 |
|---|---|---|
| Task 1–6 | 중앙 라우팅 계약 · 프로바이더 카탈로그 · 역할 배정 · 재귀 플래너 · 프론트 피커 · 통합 검증 | `4f76d1ef..dd36325f` |
| I1 | `.env.template` 시크릿 전용 축소 후 커밋 | `59d98aa6` |
| I2 | 게이트웨이 시크릿 제거 + **기동 검증** (빈 키로 뜨면 빈 키 서명 토큰이 통과하므로 필수) | `e752b16c` |
| I3·I4 | `llm.model` = `None` → everyday 역할 해석 / 크로스 프로바이더 폴백을 "명시 선택 시 비활성" | `e65b765d` |
| I5 | 죽은 피커 항목(Google·xAI) 제거 — 라벨 문제가 아니라 **실행 불가**였다 | `48ad7dac` |
| I6 | `fast` 역할 **도입하지 않기로 확정**, 테스트로 고정 | `af5b83ba` |
| 후속 | 모델 카탈로그 config화 — 사실은 `models.yaml`, 정책은 `model_routing` | `783fe864..88dea3ab` |

**부수적으로 잡은 프로덕션 버그 (라우팅 작업의 실질 수확):**
- `iterative_refiner.py`가 존재하지 않는 `end_collection()` 호출 → HDR 리포트가
  **모든 정제를 마친 마지막 단계에서** `AttributeError`로 죽었다 (2026-01-11부터)
- provider를 모델명으로 추측(`"gpt" in model`) → 카탈로그 조회로 교체
- `SkillMetadataError`가 파서 예외 계층과 끊겨 있어 깨진 스킬 하나가 discovery
  전체를 중단시켰다 → 수정 후 auto-discovery **7개 → 9개**
- 테스트 fixture 재설계로 전체 스위트 **51 → 0 failed** (세션 스코프 이벤트 루프)

### 4.2 반드시 유지할 불변식

- 해석 우선순위: **user → conversation → feature override → role default**
- 역할 매핑: anthropic `everyday=claude-sonnet-5` / `powerful=claude-opus-5`,
  openai `everyday=gpt-5.6-terra` / `powerful=gpt-5.6-sol`
- `None` = 역할 기본값, 문자열 = 기능 오버라이드
  (`deep_analysis.models.*`, `coding_model.model`, `recursive_agent.planner_model`)
- 기존 대화는 저장된 모델 유지 (마이그레이션 금지)
- Claude 5는 adaptive thinking, 수동 `budget_tokens`는 `ValueError`
- 경계마다 **한 번만** 해석 (토큰 스트림 루프 안 반복 해석 금지)
- ❌ 크로스 프로바이더 폴백 **추가** 금지
- ❌ 요청마다 LLM으로 난이도 분류 금지 (지연·비용·비결정성으로 기각)
- ✅ 선택 가능한 모든 모델은 가격을 가진다 (`test_every_selectable_model_is_priced`)

### 4.3 남은 잔여 (모두 저위험)

| 항목 | 내용 |
|---|---|
| SKILL.md 누락 6개 | `cron`, `github-search`, `google-scholar`, `openalex`, `reddit`, `sec-edgar` — 이름 규칙은 충족, `SKILL.md`만 추가하면 등록됨 |
| `deep_analysis_*` 테이블 잔여물 | 과거 실행 약 1.6만 행. `cleanup_test_data`가 안 지운다. 지금 실패는 없으나 무한 누적 |
| `fast` 역할 | 도입 보류 결정 유지. 도입하려면 `WorkloadRole` Literal + `ProviderModelRolesConfig`를 **함께** 확장 (테스트가 반쪽 변경을 막는다) |

---

## 5. 트랙 C — 프론트엔드

### 5.1 job 서비스 마이그레이션은 **완료돼 있다**

`docs/FE_AUDIT_260717.md` §6은 D22/D23 계약 전환에 대한 프론트엔드 준비도를
**"낮음 (미준비)"**로 판정하고 차단 요인 5개를 지목했다. 확인 결과 **다섯 개 전부
해소됐다.**

| FE 감사 §6 차단 요인 | 현재 |
|---|---|
| 🔴 AC6 늦은 접속 시 전체 이력 재생을 받을 구조가 없다 | ✅ `lib/deep-analysis/reader.ts` + seq 커서. `after=0`이면 진행 중 run도 처음부터 재생 |
| 🔴 run_id를 담을 곳이 없다 (FE는 conversation_id 단일 키) | ✅ `lib/deep-analysis/active-run-store.ts` |
| 🔴 `maxDuration = 60`이 장시간 job 스트림과 충돌 | ✅ 전용 라우트가 `maxDuration = 300`. 끊겨도 커서로 재구독 |
| 🟡 스트림 소비가 `POST /api/chat` 응답에 강결합 | ✅ 독립 **GET 전용** 프록시 라우트로 분리 |
| 🟡 스트리밍 로직에 단위 테스트 0개 | ✅ `tests/source/deep-analysis-*.test.ts` 5개 파일 630줄 |

구현 규모는 약 1,665줄이다 (`lib/deep-analysis/` 671 + `hooks/use-deep-analysis-stream.ts`
194 + `components/deep-analysis-status.tsx` 170 + 테스트 630).

**FE↔BE 계약 일치 확인:**
`web/app/(chat)/api/deep-analysis/[runId]/events/route.ts` →
`GET /api/v1/deep-analysis/{run_id}/events?after=N`
(`neos/api/handlers/deep_analysis_handlers.py:148`). 커서 파라미터·소유자 검사(비소유
404)·SSE 헤더가 양쪽에서 일치한다.

> 📌 **설계 판단 하나가 특히 좋다.** 프록시 라우트에 **POST가 없다.** 재접속은
> 커서를 든 GET일 뿐이고, job 재제출 경로를 프론트에 두지 않는 것이 FE 감사 §4.2
> **재과금 사고**(`autoResume`가 재개가 아니라 재실행이었다)의 재발 방지책이다.
> 이 구조를 되돌리지 말 것.

**검증 상태:** `pnpm --dir web test:source` **147 passed / 0 failed** (2026-08-04 실행).
로드맵 초안과 라우팅 문서가 적은 "141/141"은 낡은 수치다.

### 5.2 🔴 남은 갭 — 새 가시성 이벤트가 UI에 도달하지 않는다

FE `lib/deep-analysis/progress.ts`의 `activityLabel()`이 라벨을 붙이는 kind는
14종이다. **2026-08-02~04에 추가된 "조용한 실패를 보이게 만드는" 이벤트는 하나도
포함돼 있지 않다.**

| 이벤트 | 추가 시점 | FE 라벨 |
|---|---|---|
| `report_assembly_degraded` | 08-03 (G5) | ❌ 없음 |
| `investigation_stopped_at_floor` | 08-03/08-04 (G5·G8) | ❌ 없음 |
| `judge_budget_exhausted` | 08-03 (G5) | ❌ 없음 |
| `llm_truncated` · `truncation_handled` | 08-02 (A2) | ❌ 없음 |
| `entailment_filter_skipped` | 08-02 (A2) | ❌ 없음 |
| `claim_discarded` | 07-27 | ❌ 없음 |
| `finalization_prompt_clamped` | 08-04 (D25/G6·G7) | ❌ 없음 |
| `node_reduction_degraded` | 08-04 (D25/G6·G7) | ❌ 없음 |

**동작은 안전하다** — 모르는 kind도 커서를 전진시키고 라벨만 `null`을 반환한다
(`progress.ts:148-153`의 명시적 설계: "모르는 이벤트 때문에 커서가 멈추면 재구독이
영원히 같은 지점을 다시 읽는다"). **깨지지 않지만 보이지 않는다.**

**왜 문제인가.** §3.2에 적은 이 구간의 주제가 "고치기 전에 보이게 만든다"였는데,
그 가시성이 **원장에서 멈춘다.** 사용자는 여전히 리포트가 템플릿으로 강등된 것을
알 수 없다 — 정확히 이 작업이 없애려던 상태다.

> ⚠️ FE는 `synth_pass`와 `report_graded`는 **이미 인식한다**(`progress.ts:133,136`).
> 즉 W1이 성공하면 그 성과는 FE에 자동으로 나타난다. 반대로 **실패 경로만 보이지
> 않는다** — 성공만 보이고 실패는 침묵하는 비대칭이다.

### 5.3 프론트엔드 잔여 (TODO §12~14 재확인)

| TODO | 원 서술 | 2026-08-04 실측 |
|---|---|---|
| #14 | `chat/route.ts`의 `maxDuration = 60` | ⚠️ **그대로 존재** (`route.ts:12`). 심층분석은 전용 라우트(300)를 쓰므로 무해하나 다른 장시간 챗 경로에는 위험 |
| #13 | `prompt-input.tsx:67` 첨부만 있는 메시지가 400 | ❓ **경로가 사라졌다.** 현재는 `components/elements/`·`components/ai-elements/`로 재구성됨. 신규 경로에서 재확인 필요 |
| #12 | `examples/document_api_example.py` 죽은 경로 | ❓ **파일이 존재하지 않는다.** 항목 자체가 무의미해졌을 가능성 — 삭제 확인 필요 |

`docs/FE_AUDIT_260717.md`의 🔴 5건은 전부 해소됐고, 남은 것은 §3.5·§4.3~4.6의
🟡 항목들이다(스트림 재연결·SSE 파서 이중화·런타임 검증 부재). **단 그 감사는
2026-07-17 기준이며 §1이 "나머지 항목은 재확인하지 않았다"고 명시한다** — 위
#12·#13처럼 이미 무의미해진 항목이 섞여 있으므로 근거로 쓰기 전에 재확인할 것.

---

## 6. 세 트랙의 접점 — 잊기 쉬운 곳

라우팅이 끝났다고 하네스와 무관한 게 아니다. 실제로 얽힌 지점이 넷 있다.

**① E3 — `judge ≠ worker` 불변식이 지금 깨져 있다 🔴**

`deep_analysis.models.judge`와 `scout`이 둘 다 `None`이라 **같은 역할(everyday)로
해석되어 `claude-sonnet-5` 하나로 수렴**한다. SCOUT 워커가 만든 클레임을 같은 모델이
심사한다 — 설계 §6.5가 명시적으로 금지한 자기 승인 편향 구조다.
(DIG는 `powerful` → `claude-opus-5`라 영향 없다.)

> **현재 결정: 바꾸지 않는다.** 모델을 바꾸면 이전 표본과 비교 불가해진다.
> 편향 방향이 **보수적**(verified 쪽으로 기울어 false-discard를 과대추정)이라
> 측정을 무효화하지는 않는다. 다만 **출하 전에는 반드시 해소**해야 한다 — §8 W4.

**② 기능 오버라이드가 라우팅의 마지막 사용처다.**
`DeepAnalysisModelsConfig`(scout/dig/synth/judge)는 전부 `str | None`이다.
라우팅 계약의 "`None` = 역할 기본값"이 하네스에서 실제로 소비되는 지점이며,
①을 고치려면 여기에 명시값을 넣는 것이 가장 작은 변경이다.

**③ 은퇴 모델과 비용 집계.**
가격 없는 모델(`gpt-5-mini-2025-08-07` 등 6개)이 은퇴한 이유는 **비용이 조용히
0으로 집계**되기 때문이다. 하네스의 예산 사다리·gain_decay가 전부 토큰/비용 숫자
위에 서 있으므로, 카탈로그에 가격 없는 모델이 다시 들어오면 하네스 예산이
조용히 틀어진다.

**④ 토큰 집계는 API `usage` 필드만 쓴다 (설계 §A5).**
자체 추정 금지. 단 C3 미해결 — `call_json`이 예외를 낼 때 그 호출의 토큰이
집계에서 샌다.

---

## 7. 미해결 이슈 통합 인벤토리

| 우선 | ID | 내용 | 트랙 |
|---|---|---|---|
| 🟡 | G9 | floor 정지가 `token_budget_exhausted`로 오분류 (6건 중 4건). 예외 핸들러가 if/elif보다 먼저 실행 | A |
| 🟡 | G4 | `report_path`가 574 run 전부 NULL — 리포트 본문이 보존된 적 없다 | A |
| 🟡 | G3 | 게이트가 뒤집혀 있다 — assertion 0건이면 비율 0.0(만점). **정책 결정 필요** | A |
| 🟡 | E3 | judge = SCOUT worker (동일 모델). 불변식 위반, 의도적 유예 중 | A×B |
| 🟡 | C1 | discard recall 재측정 — 2회 연속 n=0 | A |
| 🟡 | A3·A4 | worker/판정자 상한 재보정 (thinking 몫 실측 선행) | A |
| 🟡 | C3·C4 | `call_json` 예외 시 토큰 누락 / `entailment_filter_skipped`가 4가지 원인을 뭉갠다 | A |
| 🟡 | B2 | dev 프로파일 여유 축소 (감시 항목) | A |
| 🟡 | D1·D2 | search 0건 반환 7% / 403 잔존·429 backoff 없음 | A |
| 🟡 | P1 #8 | `_persist_assistant_message`가 예외를 삼킴 | — |
| 🧪 | CI #9 | `pytest tests/workflow/` 전체 실행 미검증 (수집 661건은 통과) | — |
| 🧪 | CI #10 | `tests/api/` 순서 의존 오염 미확인 | — |
| 🧪 | CI #11 | analytics 테스트 run 스코프 — **코드 확인상 해소**, 실행 검증 필요 | — |
| ⚠️ | F3 | `managed-sandbox-control-plane` worktree에 구식 `AgenticGrader(...)` 11곳 — 병합 시 `TypeError` | — |
| 🟡 | **FE1** | 실패 이벤트 8종에 FE 라벨 없음 — 성공만 보이고 실패는 침묵 (§5.2) | C |
| 🟡 | FE2 | `chat/route.ts`의 `maxDuration = 60` 잔존 (TODO #14) | C |
| 🟢 | FE3 | TODO #12·#13이 **존재하지 않는 파일**을 가리킨다 — 항목 재확인 또는 폐기 필요 | C |
| 🟢 | — | SKILL.md 누락 6개 / `deep_analysis_*` 테이블 1.6만 행 | B |

---

## 8. 실행 계획 — 웨이브

각 웨이브는 **측정 가능한 완료 기준**을 갖는다. 기준을 못 채우면 다음으로 넘어가지 않는다
(설계 §9 마일스톤 규율의 연장).

### W1. 마무리가 실제로 출력을 낸다 🔴 — 다음 착수 대상

**대상:** G6, G7
**목표:** 설계 §6.7 최종 조립과 §6.8 에이전틱 판정을 **처음으로 실행시킨다.**

접근 후보 (택일 또는 조합, §9에서 결정):

| 안 | 내용 | 트레이드오프 |
|---|---|---|
| **a** | floor 산식에 input 여유분을 별도 반영 (`floor += Σ 예상 input_bound`) | 산식만 고치면 되지만 input 예측이 빗나가면 floor가 과대해져 조사를 굶긴다 |
| **b** | 마무리 단계 프롬프트를 별도로 축소 (클레임 수 상한, `excerpt_max_chars` 축소) | 조사 예산 유지. 대신 리듀스 품질이 떨어질 수 있다 |
| **c** | floor를 stage별 하위 풀로 분할 + `reduce_node` 호출 수를 allowance로 **실제 강제** | G7까지 함께 해소. 재아키텍처에 가까워 범위가 크다 |

**완료 기준 (라이브 표본 5+1 실행):**
- `synth_pass` ≥ 1 (현재 0) — **S1 충족**
- `report_assembly` stage의 `token_budget_reserved` > 0 (현재 0)
- `report_assembly_degraded`가 run당 3건에서 감소
- dev run 완료율 5/5 유지 (G8 회귀 재발 없음)
- `finalization_prompt_clamped`가 `exhausted=true`이거나 `dropped_primary`가
  그 run의 child 개수와 같은 건수는 0이어야 한다 — `root_answer`는 클램프되지
  않으므로(D-6) 모든 child finding이 잘려나가도 `synth_pass`는 그대로 남는다.
  이 건수가 0이 아니면 그 `synth_pass`는 가짜 양성이다(루트 답변만 남은 리포트가
  LLM 성공처럼 보이는 것)

**2026-08-04 상태:** 코드·결정론 테스트 완료(D-1 = 2안 풀 분할, D-4 = dev cap 100,000,
D-5 = 재시도 3회분 보장, D-6 = caveats → 자식 꼬리 → 자식 수).
**완료 기준은 아직 미판정이다** — `synth_pass ≥ 1`은 라이브 표본 5+1이 필요하고,
§10.2의 "정확히 1회" 원칙상 코드가 확정된 지금 한 번만 실행해야 한다.
따라서 §2.2의 S1은 ❌로 유지한다.

### W2. 원장이 진실을 말한다

**대상:** G9, G4, **FE1**
- G9: `except TokenBudgetExhausted` 핸들러가 무조건 `_mark_token_budget_exhausted`를
  부르지 말고 `token_budget.exhausted`를 실제로 확인 → floor 정지면
  `_mark_investigation_stopped_at_floor`
- G4: 리포트 본문 영속화 (`report_path` 채우기)
- **FE1: 원장의 진실을 UI까지 밀어낸다** — `progress.ts`의 `activityLabel()`에
  실패 이벤트 8종 라벨 추가 (§5.2). 백엔드만 고치면 "원장은 정확한데 사용자는
  여전히 모른다"에서 멈춘다

**완료 기준:** 정지 사유 오분류 0건(**S4**), 신규 run의 `report_path` NULL 비율 0%(**S3**),
실패 경로가 UI에 라벨로 나타남(회귀 가드는 `tests/source/deep-analysis-progress.test.ts`).
G4는 **G3 판단의 선행 조건**이다 — 본문 없이는 게이트 임계값을 재보정할 수 없다.

> FE1을 W2에 묶은 이유: G9와 같은 결함의 서로 다른 층이다. G9는 원장이 정지 사유를
> 틀리게 적는 문제이고, FE1은 정확히 적힌 것이 화면에 도달하지 않는 문제다.
> **W1이 성공하면 그 성과(`synth_pass`)는 FE에 자동으로 뜨지만 실패는 여전히
> 침묵한다** — 이 비대칭을 남기면 "성공만 보이는 UI"가 된다.

### W3. 게이트를 다시 판단한다 — ⚠️ 정책 결정 필요

**대상:** G3
W1 이후 게이트가 채점하는 대상이 **템플릿에서 LLM 산문으로 바뀐다.** 따라서
"빈 리포트가 통과한다"는 관측을 **새 표본에서 다시 확인한 뒤** 정책을 정한다.

핵심 질문은 임계값이 아니다: **assertion이 0건인 리포트를 어떻게 채점할 것인가.**
현재 동작(`if not assertions: return 0.0` → 만점)은 특성화 테스트
`test_a_report_with_no_assertions_scores_a_perfect_zero`로 고정돼 있으므로,
바꾸려면 **의도적으로 그 테스트를 깨야 한다.**

부수 과제: `_PROPER_NOUN`이 한국어 조사가 붙은 라틴 고유명사("Act가", "OpenAI가")를
못 잡는다 — 파이썬 `\b`가 라틴-한글 경계를 만들지 않는다. 분모가 사실상
"숫자를 담은 문장"뿐이라 assertion 4개에 각주 없는 문장 하나면 0.25 ≥ 0.20.

**완료 기준:** 통과한 run의 verified claim 중앙값 > 0 (현재 0.0) — **S2 충족**

### W4. 클레임 품질과 계측 부채

**대상:** E3, C1, A3·A4, C3·C4
- **E3 해소** — `deep_analysis.models.judge`에 명시 모델을 넣어 워커와 분리.
  단 **표본 비교 단절**이 생기므로 baseline 재수립과 함께 계획할 것
- **C1 discard recall 재측정** — claim 생산량이 정상인 표본에서.
  이전 표본은 dev claim 4건 / dead_end 90건으로 비교 불가였다
- A3·A4: thinking 몫 실측 후 상한 재보정
- C3: 예외 시 토큰 누락 / C4: `entailment_filter_skipped` 원인 분리

**완료 기준:** discard 표본 n ≥ 20에서 false-discard 비율 산출

### W5. CI와 운영 위생

**대상:** CI #9·#10·#11, F3, 테이블 정리, SKILL.md 6개, **FE2·FE3**
**완료 기준:** `pytest tests/` 전체가 CI에서 3회 연속 동일 결과 — **S5 충족**

FE2·FE3은 백로그 위생 작업이다. 특히 **FE3은 항목을 고치는 게 아니라 폐기하는
쪽일 수 있다** — TODO #12의 `examples/document_api_example.py`와 #13의
`web/components/prompt-input.tsx`는 **둘 다 더 이상 존재하지 않는다.**
없는 파일을 가리키는 백로그 항목은 다음 사람에게 유령 작업을 준다.

> 주의: F3은 이 저장소 문제가 아니라 **병합 시점 폭발물**이다.
> `managed-sandbox-control-plane` worktree가 rebase되면 `AgenticGrader` 11곳이
> `TypeError`를 낸다 (`max_output_tokens`가 필수 인자가 됐다).

### W6. 승격

S1–S6 전부 충족 후 `deep_analysis.enabled` 기본값 전환을 **별도 결정으로** 다룬다.
관련 잔여 결함은 `docs/ROADMAP.md`의 R1(임계값 역전)·R2(intent 미방출)·R6(3엔진 기본 비활성).

---

## 9. 사람의 결정이 필요한 지점

아래는 코드나 측정으로 답이 나오지 않는다. **착수 전에 정해야 한다.**

| # | 결정 | 선택지 | 영향 |
|---|---|---|---|
| **D-1** | W1의 접근 (§8 W1 표) | a 산식 보정 / b 프롬프트 축소 / c 풀 분할 | ✅ 결정됨: **c(풀 분할) + 측정 클램프** — `report_floor_tokens` 안쪽 tier + `prompt_input_bound`로 마무리 프롬프트를 강제 축소(D25, `c9a05d19`/`bf4ba20a`/`30419503`). c가 근본적이나 범위가 크다는 우려는 있었으나, 산식 보정(a)은 input 예측이 빗나가면 floor가 과대해지는 문제가 있어 채택하지 않았다 |
| **D-2** | assertion 0건 리포트 채점 (G3) | 통과 / 반려 / 제3 판정(예: "내용 없음" 코드) | 사용자 영향 최대. 지금은 빈 리포트만 통과 중 |
| **D-3** | E3 judge 모델 분리 시점 | W4에서 / 출하 직전 / 즉시 | 즉시 하면 진행 중 표본과의 비교가 끊긴다 |
| **D-4** | dev floor 비율 | 현행 22%(4,400/20,000) 유지 / 축소 | ✅ 결정됨: **dev `global_token_cap` 20,000 → 100,000** — 기존 캡은 `worker_analysis` 호출 한 번(input_bound 5,542~17,723)도 담지 못했다. 새 floor 비율은 41.0%(41,040/100,000)로 default(43.7%)와 같은 수준(`4a2499cc`/`5376048a`). 논의 중 80,000으로 합의됐다가 `grading_input_ratio` 교정(4.0→5.0) 후 100,000으로 재조정됐다 — 80,000이면 경고 임계값 0.5가 상시 발동한다 |

---

## 10. 작업 규칙 — 반복해서 다친 곳

### 10.1 증거 보존 (실제로 겪은 위험)

`git worktree remove`는 **gitignore 대상 파일을 경고 없이 삭제한다.**
`artifacts/deep-analysis-funnel/<ts>/`는 "정확히 1회" 원칙 때문에 **재생성 불가**이고,
`docs/TODO_260729.md`의 수치는 그것이 유일한 근거다.

```bash
WT=.worktrees/<name>
diff <(ls "$WT/artifacts/deep-analysis-funnel" 2>/dev/null) \
     <(ls artifacts/deep-analysis-funnel 2>/dev/null)
cp -R "$WT/artifacts/deep-analysis-funnel/<ts>" artifacts/deep-analysis-funnel/
(cd "$WT/artifacts/deep-analysis-funnel/<ts>" && shasum -a 256 *) > /tmp/src.sha
(cd artifacts/deep-analysis-funnel/<ts> && shasum -a 256 -c /tmp/src.sha)
git -C "$WT" status --short && git -C "$WT" log --oneline dev..HEAD
git worktree remove "$WT" && git worktree prune
```

2026-08-04 라이브 검증 6건의 근거는 **`deep_analysis_events` 테이블뿐이다**
(수정 전 run이 실패해 아티팩트 디렉터리가 남지 않았다). 이 테이블을 지우면 재현 불가.

### 10.2 라이브 표본 실행 규칙

- ❌ 표본 **재실행** 금지 (정확히 1회 원칙, 실패해도 자동 재시도 금지)
- ❌ 실행 중 grader 임계값 / 샘플링 / 프롬프트 / 모델 / 토큰·워커·깊이·벽시계 한도 변경
- ❌ 5+1 단일 관측으로 **인과 주장** — provider·검색결과·시각 변동성 명시 필수
- ✅ `manifest.json`에 **실행 영수증**(PID, UTC start/end, exit status, test/Ruff 통과)과
  **구성 지문**(model ID, threshold, cap)을 남길 것 — `20260725T081707Z`는 exit code를
  복구할 수 없어 `unavailable`로 기록해야 했다

### 10.3 앰비언트 상태 오염 3종 (전부 실제 발생)

| 증상 | 원인 | 커밋 |
|---|---|---|
| 전역 `settings` 싱글턴이 바뀐 채 남음 | `reload_settings_for_tests()`가 모듈 전역 재바인딩 | `d3d3fd96` |
| 프로세스 env가 테스트 지정값을 이김 | litellm·crewai가 import 시 `load_dotenv()`로 `.env`를 `os.environ`에 복사 | `4b37a3fe` |
| import 시점에 고정된 플래그가 어긋남 | `neos/main.py`의 `IS_DEBUG`는 최초 import 때 확정 | `fe425578` |

> 세 번째가 가장 잡기 어렵다. **모듈 최상단에서 `os.environ[...]`으로 앱 형태를
> 제어하려는 코드를 신뢰하지 말 것.** 그런 설정은 `tests/conftest.py`에 둔다.

또한 `importlib.reload(neos.config.settings)`는 싱글턴을 새로 만들어 **기존 참조와
갈라진다.** `Settings.__init__`이 생성 시점에 읽으므로 reload는 애초에 불필요하다 (`0cd8bfda`).

**반증된 가설 (기록용):** `db_manager.close()`의 `engine.dispose(close=False)`는
버그가 아니라 **테스트별 이벤트 루프에 대한 의도적 회피책**이다. `dispose()`로
바꾸면 악화된다(8 → 17건). 이유는 `neos/database/connection.py` 주석에 못박아 뒀다.

### 10.4 검증 명령

```bash
# 백엔드 (bare pytest는 asyncio 마커 수집 실패 — .venv 경로로)
.venv/bin/python -m pytest

# deep_analysis 결정론 베이스라인 (실 LLM 없음)
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q

# 라우팅 · 카탈로그
pytest -q tests/config/test_model_catalog.py tests/config/test_model_catalog_parity.py \
         tests/config/test_model_routing.py tests/utils/test_llm_factory_defaults.py

# 게이트웨이 / 프론트 — 현재 cargo 5/5, test:source 147 passed
cd api_gateway && cargo test --offline && cargo build --offline
pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit
# 심층분석 FE 계약만 빠르게 (progress/reader/subscription/active-run-store/events)
pnpm --dir web test:source 2>&1 | grep -i "deep-analysis"

# 낡은 자동 기본값 재스캔
rg -n 'gpt-4-turbo-preview|gpt-4o|claude-sonnet-4-6|claude-opus-4-6|gpt-5-mini-2025-08-07' \
  neos config web/lib docs/CONFIGURATION.md examples
```

> 전체 스위트는 `c219531d` 이후 **결정론적**이다.
> 실패가 하나라도 보이면 **실제 회귀로 취급하라.**
> 회귀 비교 시 `grep '^FAILED tests/'`로 걸러야 한다 — `'^FAILED'`만 쓰면
> 진행 표시(`FAILED  [ 7%]`)까지 걸린다.
>
> ⚠️ **"2112~2234 passed" 기준선은 낡았다.** 이 기계에 PostgreSQL이 없던 시절의
> 수치다. 2026-08-04 기준 DB가 떠 있는 상태의 실측은 **2,386 passed / 16 skipped /
> 0 failed**다 — 이것이 현재 참 기준선이다.

### 10.5 낡은 문서 주의

- ❌ `2026-07-11-deep-analysis-chatswap.md` **재실행 금지** — D21/D22/D23이 세 번 덮어썼다.
  현재 챗 노드는 하네스를 직접 실행하지 않고 job을 제출만 한다 (`graph.py:1051–1122`)
- ✅ 대신 `DECISIONS.md`를 D18 → D21 → D22 → D23 순으로 읽을 것
- ⚠️ `role_based_model_routing_task_resume.md` §0·§6의 일부 서술은 2026-07-27
  카탈로그 config화로 낡았다 — 같은 문서 §0.1의 정정표를 먼저 볼 것

---

## 11. 참조

- 설계 정본: [DEEP_ANALYSIS_HARNESS_DESIGN.md](DEEP_ANALYSIS_HARNESS_DESIGN.md)
- 재개 문서: [deep_analysis_task_task_resume.md](archive/deep_analysis_task_task_resume.md),
  [role_based_model_routing_task_resume.md](archive/role_based_model_routing_task_resume.md),
  [coding_agent_task_resume.md](coding_agent_task_resume.md)
- 백로그 원장: [TODO_260729.md](TODO_260729.md) — G 계열 실측 수치의 원본
- 프론트엔드 감사: [FE_AUDIT_260717.md](FE_AUDIT_260717.md) — §6이 트랙 C의 기준선.
  ⚠️ 2026-07-17 시점이며 §1이 "나머지 항목은 재확인하지 않았다"고 명시한다
- 트랙 C 코드 표면: `web/lib/deep-analysis/` (reader·subscription·progress·events·
  active-run-store), `web/hooks/use-deep-analysis-stream.ts`,
  `web/components/deep-analysis-status.tsx`,
  `web/app/(chat)/api/deep-analysis/[runId]/events/route.ts` (GET 전용 프록시)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D1–D23)
- 설정·모델 정본: [CONFIGURATION.md](CONFIGURATION.md) — Model Catalog / Model Routing 절
- L5 운영: [deep_analysis_l5.md](deep_analysis_l5.md)
- 전체 로드맵: [ROADMAP.md](ROADMAP.md) — Loop 아키텍처 통합 3단계
- 평가 증거: `artifacts/deep-analysis-funnel/20260725T081707Z` (gitignore, **재생성 불가**),
  `deep_analysis_events` 테이블 (2026-08-04 라이브 6건의 유일한 근거)

---

*이 문서는 세 재개 문서와 백로그의 종합이다. 수치의 원본은 항상
`docs/TODO_260729.md`와 `deep_analysis_events`이며, 충돌하면 원본이 이긴다.*
