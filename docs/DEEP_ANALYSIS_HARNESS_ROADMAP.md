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
| **A. 심층분석 하네스** | 🟢 **W1 완료 — LLM 리포트가 나온다** (2026-08-07 표본) | **W3(G3) 게이트 재판단.** 리포트는 나오는데 게이트가 6/6 run을 3회 전부 반려한다. `report_grading` 예약은 아직 0건 |
| **B. 역할 기반 모델 라우팅** | ✅ 완료 · 안정 | 유지보수 모드. 카탈로그 불변식 지키기 |
| **C. 프론트엔드** | ✅ job 마이그레이션 완료, ✅ 가시성 갭 해소(FE1·FE4) | §5.3의 저위험 잔여(FE2·FE3)와 신규 FE5·FE6·FE7 |
| **D. 프레임워크 이탈·계측 통일** | 🟡 **D3a·D1a·D1b 완료** | **D1c** — 이제 `neos/coding/`·`deep_analysis/`에 어댑터를 붙이면 된다. 장애물 ①②가 둘 다 치워졌다 |

**트랙 A 한 줄 요약 (2026-08-07 라이브 표본 `20260807T164924Z`로 갱신):**
**마무리가 처음으로 출력을 냈다.** 574 run 동안 0건이던 `synth_pass`가 6 run에서
18건(run당 3) 기록됐고, `report_assembly` stage가 처음으로 예약을 받았다(18건).
리포트는 템플릿이 아니라 진짜 LLM 산문이다.
남은 문제는 **게이트 이후**다 — `report_graded`가 6/6 run에서 3회 전부 `ok=False`이고
`report_grading` 예약은 여전히 0건이라 **에이전틱 판정자는 아직 한 번도 돌지 않았다.**
그리고 캡이 소진되면 `_finalize`가 **렌더 전 draft**를 반환하므로, 사용자가 받는
리포트에는 `[C:da8b7072]` 원본 마커가 그대로 있고 `## 출처` 절이 없다 → W3-a.

> ⚠️ 이 자리에 처음 적었던 "`[C:...]` 인용 마커가 실린 LLM 산문"은 그 마커를 **성과로
> 오독한 것**이다. 최종 산출물에 원본 마커가 남아 있다는 것은 인용이 됐다는 뜻이 아니라
> **CitationRenderer가 산출물까지 살아남지 못했다는 증거**다. §5.2 W3 참조.

> 이전 요약(2026-08-04, "LLM이 작성한 것은 아직 0건")은 이 표본으로 무효가 됐다.

**트랙 B 한 줄 요약:**
플랜 6개 태스크 + 잔여 이슈 I1–I6 전부 종결. 모델 *사실*은
`neos/config/models.yaml` 단일 원천으로 모였고, 배포 *정책*(`model_routing`)과
분리돼 있다. 백엔드 2234 passed / 0 failed, 게이트웨이 5/5, 프론트 `tsc` clean.

**트랙 C 한 줄 요약 (2026-08-04 실측, 가시성 갭은 2026-08-07 W2·FE4로 해소):**
`docs/FE_AUDIT_260717.md` §6이 "미준비"로 판정했던 job 서비스 전환 차단 요인
**5개가 전부 해소**됐다 — run 스트림 프록시·커서 재구독·active-run-store가
약 1,665줄로 구현돼 있고 `pnpm test:source` 147 passed. 당시 남았던 갭 — 08-02~04에 추가한 실패 이벤트 8종에 FE 라벨이 없던 것(FE1) — 은
W2가 **상태 계층**을(`a9dbcfe3`), FE4가 **화면 계층**을 해소했다: 강등 경고 블록 +
새로고침 복원(백엔드 메타데이터 경유) + 굶은 판정자를 강등 넷째로 추가. 그 과정에서
원래부터 있던 키 이름 불일치도 잡았다 — 백엔드는 `deep_analysis_run_id`를, 프론트는
`deep_analysis`를 읽어서 **새로고침하면 진행 카드가 통째로 사라졌다.**

**트랙 D 한 줄 요약 (2026-08-07 신설):**
데이터셋 콜렉터 확장 · 멀티홉/citation 스킬화 · langgraph·crewai 삭제 ·
네이티브 SDK 전환 — 네 과제가 하나의 의존 사슬로 묶여 있다. 핵심은
**콜렉터의 유일한 자동 계측 지점(`TrackedLLM`)이 LangChain 타입에 묶여 있어서
SDK 전환이 계측을 파괴한다**는 것이다. 순서를 틀리면 §3.2가 경고한
"조용한 실패"가 계측 계층에서 재현된다. 전체 설계는 **§11**.

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
| S1 | LLM이 조립한 리포트가 실제로 나온다 | ✅ (표본 #1 `20260807T164924Z` 18건, 본문 935~3,489자로 전부 실체가 있었다) | `deep_analysis_events` `kind='synth_pass'` — ⚠️ **`94067e11` 이전의 집계는 부풀려져 있다**: 빈 조립도 `synth_pass`를 남겼다(표본 #2 `a82648e3` 3건). 경계 이후 수치만 비교할 것 |
| S2 | 리포트 게이트가 알맹이 있는 리포트를 통과시킨다 | ❌ 통과 9건 중 7건이 claim 0건 | `report_graded` × run별 verified claim 수 |
| S3 | 리포트 본문이 보존된다 | ✅ (2026-08-07, W2 — 전제 정정: 본문은 유실된 적이 없었다) | `job_completed` 페이로드에 `report_markdown`이 실린 비율 |
| S4 | 정지 사유가 원장에서 정확히 구분된다 | ✅ (2026-08-07 라이브 표본 — 6/6 run이 정확히 1개의 정지 이벤트, 무이벤트 0건) | `token_budget_exhausted` vs `investigation_stopped_at_floor` vs `investigation_stopped_at_input_bound` — 세 kind 밖의 무이벤트 정지는 `score_floor` 케이스뿐이어야 한다 |
| S5 | 전체 스위트가 CI에서 결정론적으로 통과한다 | ⚠️ 선결 3건 (#9·#10·#11) | CI 워크플로 |
| S6 | 실패가 사용자에게도 보인다 (원장뿐 아니라 UI에서) | ✅ (2026-08-07, FE4) | `progress.ts`의 `activityLabel()` 커버리지 **그리고** `degradations`를 실제로 그리는 화면 컴포넌트의 존재 |

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

| 설계 문서의 서술 | 2026-08-04 실측 | 2026-08-07 라이브 표본 (`20260807T164924Z`) |
|---|---|---|
| §6.7 "최종 조립: 단일 컨텍스트가 final_compose.md로 작성" | **한 번도 실행된 적 없음.** `synth_pass` 0 / 574 run | ✅ **실행된다.** `synth_pass` 18 / 6 run (run당 3) |
| §6.8 "에이전틱 판정 2개: 루트 질문에 답하는가 / 주장 강도" | **한 번도 실행된 적 없음.** `report_grading` 예약 0건 | ❌ **여전히 0건.** 결정론 게이트가 먼저 막아 에이전틱 tier에 도달하지 못한다 |
| §6.8 "실패 시 조립 재시도, 캡 2회" | 재조립 2회가 **결과를 바꾼 적이 한 번도 없음** (실패 52건 전부 3회 소진) | ❌ **그대로.** 6/6 run이 3회 전부 `ok=False`로 캡 소진 |
| §6.8 결정론 게이트 "마커 없는 단정문 < 20%" | **템플릿 리포트를 채점 중.** "uncited 비율 1.0"은 LLM 실패가 아니라 템플릿에 각주가 없다는 뜻 | 🔴 **전제가 무효가 됐고 관측은 남았다.** 이제 LLM 산문을 채점하는데도 3 run이 `uncited_ratio` 1.0, 3 run이 0.29~0.50 — 전부 임계값 0.20 초과. 그런데 본문에는 `[C:...]` 마커가 다수 실려 있다 → **게이트의 분자·분모 정의를 의심할 근거.** W3(G3)의 1순위 재료 |
| G5 §3.1 "마무리 단계는 항상 0이 아닌 예약을 받는다" | **과장이었다.** 정확히는 "조사가 마무리를 굶히지는 않는다" (2026-08-03 정정) | ✅ `report_assembly` 예약 18건 / 6 run |

> **읽는 법:** 셋째 칸이 생기기 전까지 설계 §6.7·§6.8은 **설계 의도이지 관측된
> 동작이 아니었다.** 이제 §6.7은 관측됐고 §6.8은 아직 아니다 — 둘을 같이 인용하지 말 것.

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
| G10 | `_mark_stop_reason`이 놓치던 `input_bound` 거절 클래스가 이름을 얻었다 — `TokenBudgetExhausted`가 `cause`를 싣고, 상태 분기 **뒤에** 셋째 분기가 붙는다(G9 판정 보존). 새 kind `investigation_stopped_at_input_bound`. 부수로 synthesizer의 하드코딩된 강등 `reason` 두 곳이 예외 타입 대신 실제 사유를 적는다. **2026-08-07 라이브 표본에서 재측정 완료 — 아래 상자 참조** (D28) | `e28e0d23`·`0d5991d9`·`cc6c4365`·`a3112650` |
| G9 | 정지 사유 판정을 `_mark_stop_reason()` 하나로 접음 — 정상/예외 두 경로가 이제 같은 판정을 냄. 실측 6건 중 4건 오분류의 원인을 **코드상 해소** — 재측정은 라이브 표본에서(D25가 `synth_pass`에 적용한 것과 같은 규율). 당시 남았던 `input_bound` 거절 클래스는 위 G10이 해소했다 | `7318a840` |
| G4 | **전제 정정**: `report_path` NULL은 사실이나 본문 유실은 없었다(`jobs.py`가 `job_completed` 페이로드에 실음, AC6). `Ledger.report_markdown()` / `report_bodies()` 조회 경로 신설 | `a258f36e`(원본 `f200b26c`) |
| FE1 | `activityLabel()`에 실패 이벤트 8종 라벨 추가 + `report_graded`가 굶은 판정자를 승인과 구별 + `degradations` 누적 상태 신설 (렌더링은 이후 FE4가 해소) | `a9dbcfe3` |
| A2 | `stop_reason` 전파 — 잘린 응답 ≠ 파싱 실패한 쓰레기. `call_json` 1회 확장 재시도(2배) | 2026-08-02 |
| A1 | `report.py` 판정자 상한 300 → 800 | `a92fa4f9` |
| G2 | `report_graded`에 `uncited_ratio`·분자·분모·임계값 적재 | `56b28f3e` |
| G1 | "게이트 문제인가 §7 하류 증상인가" → **게이트 문제로 확정** | 2026-08-03 |
| G5 | `TokenBudget.floor_tokens` + `available_for_investigation` (부분 완료) | 2026-08-03 |
| G8 | `min_viable_output_tokens`(2,048) 미만 예약 거절 — dev run 0/5 → **5/5** | `71769b0f` |
| G7 | `REPORT_STAGES`(assembly·grading) 전용 안쪽 tier — 리덕션이 조립 몫에 닿지 못한다 | `c9a05d19` |
| G6 | floor를 입력 통화로 재사이징 — 비율 3종을 `synthesis_max_tokens`에서 유도, dev cap 20,000 → 100,000 | `5376048a` |

> 🔴 **G10을 표본 *전에* 고친 것이 이 표본 전체를 구했다 (2026-08-07 실측).**
> `investigation_stopped_at_input_bound`가 **6 run 중 5건**에서 발생했다 — 이 정지
> 클래스는 드문 게 아니라 **지배적 사유**였다. `investigation_stopped_at_floor`는 1건,
> `token_budget_exhausted`는 0건이다. 즉 6/6 run이 **정확히 하나씩** 정지 이벤트를
> 가지며 무이벤트 정지는 0건이다(S4 라이브 충족).
> 하루 전 코드로 이 표본을 냈다면 그 5건은 **영구히 침묵으로 기록**됐을 것이다 —
> §10.2의 "정확히 1회" 규칙 때문에 다시 셀 기회가 없다.
> 같은 이유로 `node_reduction_degraded` **56건 전부**가 `reason=input_bound`로
> 기록됐다. Task 3 이전 코드였다면 56건 전부 `token_budget_exhausted`라는
> **거짓 사유**를 달았을 것이다.

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

### 5.2 ✅ 해소된 갭 — 새 가시성 이벤트가 이제 UI에 도달한다 (2026-08-07, W2·FE4)

FE `lib/deep-analysis/progress.ts`의 `activityLabel()`이 라벨을 붙이는 kind는
14종이다. **2026-08-02~04에 추가된 "조용한 실패를 보이게 만드는" 이벤트는 하나도
포함돼 있지 않다.**

이벤트 8종(라벨이 없던 것) + 기존 kind `report_graded`(분기가 `ok`만 보던 것):

| 이벤트 | 추가 시점 | FE 라벨 |
|---|---|---|
| `report_assembly_degraded` | 08-03 (G5) | ✅ (2026-08-07, W2) |
| `investigation_stopped_at_floor` | 08-03/08-04 (G5·G8) | ✅ (2026-08-07, W2) |
| `llm_truncated` | 08-02 (A2) | ✅ (2026-08-07, W2) |
| `truncation_handled` | 08-02 (A2) | ✅ (2026-08-07, W2) |
| `entailment_filter_skipped` | 08-02 (A2) | ✅ (2026-08-07, W2) |
| `claim_discarded` | 07-27 | ✅ (2026-08-07, W2) |
| `finalization_prompt_clamped` | 08-04 (D25/G6·G7) | ✅ (2026-08-07, W2) |
| `node_reduction_degraded` | 08-04 (D25/G6·G7) | ✅ (2026-08-07, W2) |

> ⚠️ `judge_budget_exhausted`는 이 8종에 들지 않는다 — **이벤트 kind가 아니다.** 판정자가
> 굶었다는 사실은 기존 kind `report_graded`의 payload에 **최상위** `judge` 키
> (`"budget_exhausted"`/`"truncated"`/`"unparseable"`)로 남는다 — 오케스트레이터가
> `{"ok": ..., "attempt": ..., **verdict.diagnostics}`로 로그하며 `diagnostics`를
> spread하므로 `payload.diagnostics.judge`가 아니라 `payload.judge`다. 위 8종은 라벨이
> 없어서 고친 것이고, `report_graded`는 라벨은 있었으나 `payload.ok`만 보고 굶은 판정자의
> 통과와 실제 승인을 같은 문구로 내던 **기존 분기의 수정**이다 — 신규 kind로 세지 않는다.

**상태 계층은 W2가, 화면 계층은 FE4가 해소(둘 다 2026-08-07 — W2 `a9dbcfe3`)** — 위 표는 갭이 있던 시점의 스냅샷으로 남긴다.
당시 동작은 안전했다 — 모르는 kind도 커서를 전진시키고 라벨만 `null`을 반환했다
(`progress.ts:148-153`의 명시적 설계: "모르는 이벤트 때문에 커서가 멈추면 재구독이
영원히 같은 지점을 다시 읽는다"). **깨지지는 않았지만 보이지 않았다.** ✅ 표시는
`activityLabel()`이 문자열을 낸다는 뜻이었고, 그 문자열이 화면에 그려지는
문제는 FE4가 해소했다 — `degradations`는 이제 `deep-analysis-status.tsx`의 앰버 경고
블록으로 그려지고, 강등이 있으면 카드가 펼쳐진 채로 열린다.

**당시 왜 문제였는가.** §3.2에 적은 이 구간의 주제가 "고치기 전에 보이게 만든다"였는데,
그 가시성이 **원장에서 멈췄다.** 사용자는 리포트가 템플릿으로 강등된 것을 알 수 없었다
— 정확히 이 작업이 없애려던 상태다. `judge_budget_exhausted`의 경우 실제 결함은 라벨
누락이 아니라 **라벨이 거짓말을 하는 것**이었다 — `report_graded` 분기가
`payload.ok === true`만 보아 굶은 판정자의 통과와 실제 승인이 같은 문구로 나왔다.
W2는 이 문구 문제를 고쳤지만, 강등을 **화면에 그리는 문제**는 당시 남아 있었다 —
FE4가 이후 해소했다.

> ⚠️ FE는 `synth_pass`와 `report_graded`는 **이미 인식했다**(`progress.ts:133,136`).
> 즉 W1이 성공하면 그 성과는 FE에 자동으로 나타난다. W2 이전에는 **실패 경로만
> 보이지 않았다** — 성공만 보이고 실패는 침묵하는 비대칭이었다. W2가 `degradations`
> 상태를, FE4가 그 렌더와 새로고침 복원을 붙여 비대칭이 사라졌다.

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
(트랙 D가 라우팅과 얽히는 지점은 여기가 아니라 **§11.4**에 있다 — 네이티브 SDK
전환이 §4.2 불변식을 되돌릴 수 있다.)

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
| 🟡 | G3 | 게이트가 뒤집혀 있다 — assertion 0건이면 비율 0.0(만점). **정책 결정 필요** | A |
| 🟡 | E3 | judge = SCOUT worker (동일 모델). 불변식 위반, 의도적 유예 중 | A×B |
| 🟡 | C1 | discard recall 재측정 — 2회 연속 n=0 | A |
| 🟡 | A3·A4 | worker/판정자 상한 재보정 (thinking 몫 실측 선행) | A |
| 🟡 | C3·C4 | `call_json` 예외 시 토큰 누락 / `entailment_filter_skipped`가 4가지 원인을 뭉갠다 | A |
| 🟡 | B2 | dev 프로파일 여유 축소 (감시 항목) | A |
| 🟡 | D1·D2 | search 0건 반환 7% / 403 잔존·429 backoff 없음 | A |
| 🟡 | P1 #8 | `_persist_assistant_message`가 예외를 삼킴 — FE4 이후 **강등 요약이 이 경로에만 있으므로** 삼킴의 대가가 커졌다. 로그에 `degradations_lost` 건수는 남긴다 | — |
| 🧪 | CI #9 | `pytest tests/workflow/` 전체 실행 미검증 (수집 661건은 통과) | — |
| 🧪 | CI #10 | `tests/api/` 순서 의존 오염 미확인 | — |
| 🧪 | CI #11 | analytics 테스트 run 스코프 — **코드 확인상 해소**, 실행 검증 필요 | — |
| ⚠️ | F3 | `managed-sandbox-control-plane` worktree에 구식 `AgenticGrader(...)` 11곳 — 병합 시 `TypeError` | — |
| 🟡 | FE2 | `chat/route.ts`의 `maxDuration = 60` 잔존 (TODO #14) | C |
| 🟢 | FE3 | TODO #12·#13이 **존재하지 않는 파일**을 가리킨다 — 항목 재확인 또는 폐기 필요 | C |
| 🟢 | **FE5** | 실패한 run의 강등은 메시지에 남지 않는다 — `_persist_assistant_message`가 완료 시에만 호출되므로 실패 run은 메시지 자체가 없다. `job_failed` 경로에 같은 영속화를 붙일지 미결 | C |
| 🟢 | **FE6** | 강등 판정 규칙이 두 언어로 구현돼 있다 (`ledger.py._degradation_kind()` / `progress.ts.degradationKind()`). 문구는 FE 한 곳뿐이라 중복 없음. 갈라지면 과소 보고 쪽으로 기운다. 통합하려면 BE가 어휘를 API로 노출하거나 공유 스키마가 필요 — 별도 판단 | C×A |
| 🟢 | **FE7** | 복원 경로는 kind별 유일성을 백엔드의 불변식에 기댈 뿐 스스로 강제하지 않는다 — `metadata.ts`의 `asDegradations()`가 dedupe하지 않는다. 지금은 `Ledger.degradations()`(`ledger.py`)가 유일한 작성자이고 kind를 키로 한 `counts` dict로 집계해 넘기므로 중복이 나올 수 없지만, 그 경로를 우회하는 새 작성자가 생기면 React key가 겹친다. 라이브 경로는 `withDegradation`이 합치므로 안전하다 | C |
| 🟢 | — | SKILL.md 누락 6개 / `deep_analysis_*` 테이블 1.6만 행 | B |
| 🟢 | W1-m1 | `node_summary.prompt_chars`가 이제 **클램프된** 프롬프트를 잰다 — 이 경계 전후로 비교 불가. 비교하려면 `finalization_prompt_clamped`와 조인해야 한다 | A |
| 🟢 | W1-m2 | `Synthesizer.assembly_input_allowance`는 외부에서 만든 Synthesizer를 주입하면 **전역** `synthesis_max_tokens`로 떨어진다(프로파일 값이 아니라). 프로덕션 경로는 일관되지만 주석은 이 경우를 부정한다 | A |
| 🟢 | W1-m3 | `tests/workflow/deep_analysis/test_synthesizer.py`의 docstring이 옛 dev 프로파일(15x / 20,000)을 서술한다. 단언은 의존하지 않는다 | A |
| 🟡 | **D1c** | 콜렉터가 `neos/coding/`·`deep_analysis/`를 계측하지 않는다 (각 0곳). 선행 둘은 해소됐다 — D1a 탈-LangChain `d9681104` · D1b 쓰기-즉시 영속화 `29223829` | D |
| 🟢 | **D2** | 멀티홉 2,468줄이 스킬 계약 밖에 있다 / citation 렌더 경로가 3곳에 흩어져 있다 (§11.2) | D |
| 🔴 | **D3b** | langgraph 제거는 "삭제"가 아니라 **런타임 교체 + 체크포인트 자체 구현**이다 — `graph.py` 2,259줄 + 체크포인터 991줄 (§11.3) | D |
| 🟡 | **D4** | `ModelProviderBase.create_llm()`이 `BaseLanguageModel`을 반환해 LangChain을 저장소 전체에 고정한다. 전환 시 §4.2 라우팅 불변식과 충돌 위험 (§11.4) | D×B |
| 🟢 | W1-m4 | §8 W1의 접근 후보 표에서 **c**가 "`reduce_node` 호출 수를 실제 강제"라고 적혀 있으나 구현은 의도적으로 강제하지 않았다(풀 격리로 대체). §9 D-1 칸이 이를 정정한다 | A |

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

**2026-08-07 라이브 표본 실행 — `artifacts/deep-analysis-funnel/20260807T164924Z`**
(트리 `07790085`, 15:57:30~16:49:24Z, 51분 54초, exit 0, run 6건 전부 `completed`).
§10.2에 따라 **1회만 실행했고 재실행하지 않는다.**

| 완료 기준 | 실측 | 판정 |
|---|---|---|
| `synth_pass` ≥ 1 | **18** (run당 3) | ✅ **S1 충족** |
| `report_assembly`의 `token_budget_reserved` > 0 | **18** (6/6 run) | ✅ |
| `report_assembly_degraded`가 run당 3건에서 감소 | **0건** | ✅ |
| dev run 완료율 5/5 (G8 회귀 없음) | **6/6** (dev 5 + default 1) | ✅ |
| `finalization_prompt_clamped`의 `exhausted=true` 또는 `dropped_primary` = child 수 인 건수 = 0 | `exhausted=true` **12건** / `dropped_primary` 6~7 vs child 10~14 | ⚠️ **아래 참조** |

**마지막 기준에 대한 정확한 서술.** 문자 그대로는 **미달**이다(`exhausted=true` 12건,
목표 0). 그러나 이 기준이 막으려던 것 — *"루트 답변만 남은 리포트가 LLM 성공처럼
보이는 것"* — 은 **일어나지 않았다.** 어느 run도 `dropped_primary`가 child 수에
도달하지 않았다(6/14, 7/11, 6/14, 6/10). 즉 **가짜 양성 `synth_pass`는 0건**이고,
대신 4/6 run이 child finding의 절반가량을 조립 프롬프트에서 떨어뜨렸다 —
**실재하는 내용 손실이되 리포트는 child 재료를 실었다.** 두 사실을 뭉치지 말 것:
S1은 충족됐고, 조립 입력 허용량은 별도 과제로 남는다.

**부수 관측 (W3의 재료).** `report_graded`가 6/6 run에서 3회 전부 `ok=False`이고
`report_grading` 예약은 0건이다 — 에이전틱 판정자는 여전히 돌지 않았다. §3.3 표의
셋째 칸이 이 관측을 담는다.

### W2. 원장이 진실을 말한다

**대상:** G9, G4, **FE1**
- G9: `except TokenBudgetExhausted` 핸들러가 무조건 `_mark_token_budget_exhausted`를
  부르지 말고 `token_budget.exhausted`를 실제로 확인 → floor 정지면
  `_mark_investigation_stopped_at_floor`
- G4: 리포트 본문 영속화 (`report_path` 채우기)
- **FE1: 원장의 진실을 UI까지 밀어낸다** — `progress.ts`의 `activityLabel()`에
  실패 이벤트 8종 라벨 추가 (§5.2). 백엔드만 고치면 "원장은 정확한데 사용자는
  여전히 모른다"에서 멈춘다

**완료 기준:** 정지 사유 오분류 0건(**S4**), `job_completed`에 `report_markdown`이
실린 비율(**S3**), 실패 경로가 UI에 라벨로 나타남(회귀 가드는
`tests/source/deep-analysis-progress.test.ts`). G4는 **G3 판단의 선행 조건**이다 —
본문 없이는 게이트 임계값을 재보정할 수 없다.

> FE1을 W2에 묶은 이유: G9와 같은 결함의 서로 다른 층이다. G9는 원장이 정지 사유를
> 틀리게 적는 문제이고, FE1은 정확히 적힌 것이 화면에 도달하지 않는 문제다.
> **W1이 성공하면 그 성과(`synth_pass`)는 FE에 자동으로 뜨지만 실패는 여전히
> 침묵한다** — 이 비대칭을 남기면 "성공만 보이는 UI"가 된다.

**2026-08-07 코드 완료, 출하 기준은 부분 충족.** G9는 `_mark_stop_reason()` 단일
판정으로 두 경로의 불일치를 없앴다(당시 `input_bound` 거절 클래스는 G10으로 남았고,
2026-08-08 D28이 해소했다 — 아래 문단 참조). FE1은 라벨 8종 + `report_graded` 분기 수정 + `degradations` 누적
상태로 **원장→상태** 구간을 해소했다. **상태→화면** 구간(강등을 실제로 그리는
컴포넌트)은 이번 웨이브 범위 밖으로 남았고 FE4로 추적한다 — S6은 ⚠️ 부분.

**G4는 전제가 틀려 있었다** — `report_path`가 NULL인 것은 사실이나 리포트 본문은
`job_completed` 페이로드에 계속 보존돼 있었다(`jobs.py`, AC6). 컬럼을 채우는 대신
`Ledger.report_markdown()`과 `DeepAnalysisAnalyticsService.report_bodies()`를 만들어
G3가 표본 전체의 본문을 읽을 수 있게 했다. §2.2 S3의 측정법도 이에 맞춰 정정했다.
S3는 이 웨이브에서 유일하게 완전히 충족된 기준이다.

**G9의 "6건 중 4건 → 0건"에 대한 정확한 서술:** 2026-08-04 실측 6건 중 4건 오분류는
실제 관측이다. `_mark_stop_reason()`으로의 통합이 그 오분류 원인을 코드상 없앴다는
것도 참이다. 하지만 "0건"은 **이 브랜치에서 라이브 run을 다시 실행해 관측한 값이
아니다** — 추론이다. D25가 `synth_pass`에 적용한 것과 같은 규율을 따른다: **코드상
해소 — 재측정은 라이브 표본에서.** 그러니 재측정 전까지 "오분류 0건"을 사실처럼
인용하지 않는다.

> 📌 이 문단이 W2 시점에 덧붙였던 경고 — "G10이 가리키는 클래스는 다시 세면
> 무이벤트로 기록될 것이다" — 는 **2026-08-08 D28로 무효가 됐다.** 그 클래스는 이제
> `investigation_stopped_at_input_bound`로 기록된다. G10을 표본 전에 고친 이유가
> 정확히 이것이다: §10.2의 "정확히 1회" 규칙 때문에, 세는 눈을 먼저 고치지 않으면
> 그 침묵이 영구 기록이 된다.

D26이 이 웨이브의 결정을 기록한다(`neos/workflow/deep_analysis/DECISIONS.md`).
관련 커밋: G9 `7318a840` · G4 `a258f36e`(원본 `f200b26c`) · FE1 `a9dbcfe3`.

### W3. 게이트를 다시 판단한다 — ⚠️ 정책 결정 필요

**대상:** G3
W1 이후 게이트가 채점하는 대상이 **템플릿에서 LLM 산문으로 바뀐다.** 따라서
"빈 리포트가 통과한다"는 관측을 **새 표본에서 다시 확인한 뒤** 정책을 정한다.

**2026-08-07 표본이 준 재료 (이제 다시 확인됐다).** 관측이 뒤집혔다 —
게이트는 이제 **아무것도 통과시키지 않는다.**

| run | `uncited_ratio` (3회 시도) | verified claims |
|---|---|---:|
| `d74dcbe3` | 1.0 / 1.0 / 1.0 | 9 |
| `eee6a87a` | 0.333 / 0.417 / 0.333 | 13 |
| `51fd8d7d` | 1.0 / 1.0 / 1.0 | 6 |
| `9915491a` | 0.417 / 0.500 / 0.444 | 16 |
| `ea7e2f2e` | 1.0 / 1.0 / 1.0 | 16 |
| `c369d7c7` | 0.382 / 0.344 / 0.290 | 46 |

임계값은 0.20이므로 **18회 시도 전부 반려**다.

> ⚠️ **정정 (2026-08-08).** 이 자리에 처음 적었던 "마커가 있는데 `uncited_ratio`가
> 1.0인 run이 3개 → 분자·분모 정의 문제"는 **틀렸다.** 저장된 본문에 채점기를 그대로
> 다시 돌려 확인한 결과 상관관계는 완벽했다 — 비율 1.0인 세 run(`d74dcbe3`·
> `51fd8d7d`·`ea7e2f2e`)은 `[C:...]` 마커를 **0개** 냈다. **게이트는 자기가 주장하는
> 것을 정확히 세고 있다.** 결함은 게이트가 아니라 그 앞뒤에 있다(아래).

**재현으로 확정한 근본 원인 사슬.** `_finalize`는 `assemble → render → grade` 순서이고
채점기는 **렌더된** 리포트를 본다(`orchestrator.py`) — 따라서 `_FOOTNOTE_REF`(`\[\d+\]`)는
그 자리에서 옳은 정규식이다.

| # | 사실 | 근거 |
|---|---|---|
| 1 | **LLM이 인용을 안 한다.** 6 run 중 3건이 verified claim 9·6·16건을 갖고도 마커 0개. 인용하는 run도 사실문의 60~70%만 단다 | 원본 `[C:]` 개수 0·0·0 / 6·8·60 |
| 2 | 결정론 게이트가 18회 전부 반려 | `report_graded` `ok=False` × 18 |
| 3 | 에이전틱 판정자는 short-circuit으로 **도달 불가** | `report_grading` 예약 0건 |
| 4 | 캡 소진 시 `_finalize`가 `last`(**렌더 전 draft**)에 부록만 붙여 반환 | `orchestrator.py` 캡 소진 분기 |
| 5 | **사용자가 받는 리포트에 원본 `[C:da8b7072]` 마커가 그대로 있고 `## 출처` 절이 없다** | 6/6 run에서 `[N]` 각주 0개, `## 출처` 없음 |
| 6 | 조립 출력이 상한에 부딪혀 문장 중간에서 잘린다 | `synth_pass.output_tokens` = 4000(정확히 상한) |

**따라서 W3는 게이트 임계값 조정이 아니다.** 최소 세 갈래로 나뉜다:

- **W3-a ✅ 완료** (`24045c7e`): 캡 소진 경로가 `last_rendered`를 반환한다. 그 텍스트는
  채점기가 실제로 판정한 것과 같으므로, 원장의 `uncited_ratio`가 이제 **배달된 것**을
  서술한다
- **W3-b ✅ 완료** (`bd724b92`): 원인은 프롬프트가 아니었다 — 프롬프트는 인용을 명시적으로
  요구한다(`final_compose.md`). **강등된 잎 노드가 자기 클레임을 버리고 있었다** (아래)
- **W3-c ✅ 완료** (`94067e11`): D-2를 **제3 판정**으로 확정 — `E_REPORT_EMPTY`.
  근거는 표본 #2다(아래)

**W3-b의 근본 원인 — 또 하나의 조용한 실패.** `_degraded_summary`는 자식 답변을
이어붙이는데 **잎에는 자식이 없다.** 따라서 강등된 잎의 답변은 `""`가 되고, 그 잎의
verified claim은 `[C:...]` 마커가 붙은 산문이 되지 못한 채 사라졌다. 그리고 강등된
리덕션의 대부분이 잎이었다.

| run | 리덕션 강등률 | 그중 잎 | 최종 리포트의 `[C:]` 마커 |
|---|---:|---:|---:|
| `d74dcbe3` | 67% | 8/10 | 0 |
| `51fd8d7d` | 70% | 11/14 | 0 |
| `ea7e2f2e` | 73% | 8/11 | 0 |
| `eee6a87a` | 79% | 8/11 | 6 |
| `9915491a` | 67% | 6/8 | 8 |
| **`c369d7c7`** | **18%** | 1/2 | **60** |

강등률과 마커 수가 뚜렷한 역상관이다. 수정: 강등된 잎이 자기 verified claim을
`[C:id] 텍스트` 형태로 결정론적으로 렌더한다 — 마커가 보존되므로 CitationRenderer가
해소할 수 있고(검증된 클레임이므로 orphan 불가), 프롬프트 비계(evidence 원문·신뢰도)는
싣지 않는다.

> 이 사슬의 출발점은 G10이 드러낸 **바로 그 `input_bound` 거절**이다. 강등 사유를
> 정직하게 적게 만든 것(D28)이 곧바로 이 진단을 가능하게 했다.

### 5.2.1 표본 #2 — W3-a·W3-b의 효과 측정 (2026-08-08)

`artifacts/deep-analysis-funnel/20260808T023738Z` (트리 `5ffe4d48`, exit 0,
사전 게이트 2,432 passed). 표본 #1과 같은 질문 세트, **1회만 실행**.

| 지표 | 표본 #1 (전) | 표본 #2 (후) | 판정 |
|---|---|---|---|
| 산출물의 원본 `[C:]` 마커 | 3개 run (최대 60) | **0개 run** | ✅ W3-a |
| 산출물의 `[N]` 각주 | **6/6에서 0** | 31·16·18·84 (4개 run) | ✅ W3-a |
| `## 출처` 절 | **0/6** | **4/6** | ✅ W3-a |
| 정지 사유 (floor / input_bound / exhausted) | 1 / 5 / 0 | 3 / 3 / 0 | ✅ 무이벤트 0건 **2회 연속** |
| 게이트 통과 | 0/18 | 0/18 | ⬜ 변화 없음 |
| `report_grading` 예약 | 0 | **0** | ⬜ 에이전틱 판정자 여전히 미실행 |

**W3-a는 확인됐다.** 사용자가 받는 리포트가 이제 렌더된 것이다.

**W3-b는 인과를 주장하지 않는다.** 마커를 실은 run이 3→4개, 최대 60→84개로 늘었으나
§10.2가 금지한 대로 **5+1 단일 관측으로 인과 주장을 하지 않는다** — 강등률 자체가
run별로 18~86%로 크게 흔들리고, 검색 결과·모델 변동성이 통제되지 않았다.

**표본 #2가 새로 드러낸 것 — D-2가 실물로 나타났다.** W3-a·W3-b가 산출물을 바꾸자
퇴화 케이스가 보였다. 18회 채점 중 **5회가 `assertions=0`으로 만점(0.00)**을 받았고,
그중 `a82648e3`의 최종 리포트는 **완전히 빈 문자열**이었다(`"\n\n## 부록: 미해결 사유\n조립/채점 재시도 캡 소진."`).
그것을 막은 것은 실질 검사가 아니라 `E_REPORT_NO_LIMITS` — "한계와 미확인 사항"
제목이 없다는 **서식** 검사였다. 모델이 그 제목만 찍었다면 내용 0인 리포트가
실질 검사를 전부 통과했을 것이다.

**부수로 드러난 것:** `a82648e3`은 빈 리포트를 내고도 `synth_pass`를 3건 남겼다.
`assemble`이 호출 성공 직후 무조건 로그하고 `response.text`를 그대로 반환했기 때문이다.
**따라서 §2.2 S1의 집계는 두 표본 모두 부풀려져 있었다** — 나온 적 없는 리포트가
성공으로 세어졌다. `94067e11`이 빈 조립을 `report_assembly_degraded`
(`reason="empty_assembly"`)로 돌려 S1이 다시 참을 세게 만들었다.

> `report_assembly_degraded`를 재사용한 것은 의도다 — 이미 `_DEGRADATION_KINDS`와
> `degradationKind()` 양쪽에 등록된 kind라 **새 어휘 없이 사용자 화면까지 도달**한다.
> FE6의 이중 구현을 건드리지 않는다.

부수 과제로 적어둔 `_PROPER_NOUN`의 한글 조사 경계 결함은 여전히 유효하나,
이번 표본의 반려 원인은 아니다.

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

**대상:** CI #9·#10·#11, F3, 테이블 정리, SKILL.md 6개, **FE2·FE3**, **D3a(crewai 삭제)**
**완료 기준:** `pytest tests/` 전체가 CI에서 3회 연속 동일 결과 — **S5 충족**

FE2·FE3은 백로그 위생 작업이다. 특히 **FE3은 항목을 고치는 게 아니라 폐기하는
쪽일 수 있다** — TODO #12의 `examples/document_api_example.py`와 #13의
`web/components/prompt-input.tsx`는 **둘 다 더 이상 존재하지 않는다.**
없는 파일을 가리키는 백로그 항목은 다음 사람에게 유령 작업을 준다.

D3a(crewai 삭제)를 여기에 넣은 이유: 죽은 코드 제거이므로 호출 경로를 건드리지
않아 라이브 표본과 충돌하지 않고, §10.3 오염원 하나를 없애 **W5의 목표(CI 결정론)를
직접 돕는다.** 트랙 D의 나머지 셋과 달리 W6을 기다릴 이유가 없다 (§11.3 D3a).

> 주의: F3은 이 저장소 문제가 아니라 **병합 시점 폭발물**이다.
> `managed-sandbox-control-plane` worktree가 rebase되면 `AgenticGrader` 11곳이
> `TypeError`를 낸다 (`max_output_tokens`가 필수 인자가 됐다).

### W6. 승격

S1–S6 전부 충족 후 `deep_analysis.enabled` 기본값 전환을 **별도 결정으로** 다룬다.
관련 잔여 결함은 `docs/ROADMAP.md`의 R1(임계값 역전)·R2(intent 미방출)·R6(3엔진 기본 비활성).

---

**여기서 트랙 D가 시작된다.** W7~W10은 §11의 네 과제이며, W6 이후에 두는 이유는
§11.0의 상호배타 규칙이다: D1·D2·D4는 LLM 호출 계층을 바꾸므로 §10.2가 금지한
"측정 중 변경"에 해당한다. **W1~W4의 라이브 표본이 끝나기 전에는 착수하지 않는다.**

### W7. 계측이 모든 실행 경로를 덮는다

**대상:** D1 (§11.1)
**순서:** 콜렉터 탈-LangChain → 저장소 경유 영속화 → 코딩 루프·deep_analysis 확장.
**세 단계를 뒤집지 말 것** — 지금 상태로 확장하면 워커 프로세스의 레코드가 flush
지점을 못 만나 조용히 사라진다.

**완료 기준:**
- `neos/coding/`·`neos/workflow/deep_analysis/` 호출이 `LLMCallRecord`로 남는다
- `rg 'langchain' neos/utils/llm_wrapper.py` 0건 — **W9의 선행 조건**
- 별도 프로세스(Celery 워커·job 서비스)에서 만든 레코드의 유실률 0%

### W8. 멀티홉이 스킬 계약 안으로 들어온다

**대상:** D2 (§11.2)
**완료 기준:**
- auto-discovery 카운트 9 → 10 (멀티홉 등록)
- 멀티홉을 discovery 소스로 쓴 run의 `E_QUOTE_MISMATCH` 비율이 기존 소스와 동등
  — **P3(검증 사슬)이 유지됐다는 증거다**
- citation 렌더 경로 3개 → 1개 (§9 **D-6**이 "통합"으로 결정된 경우)

> W7보다 뒤에 두는 이유는 하나뿐이다: 새 스킬이 만드는 LLM 호출도 계측 대상이므로
> 계측 계약이 먼저 확정돼야 두 번 고치지 않는다. 급하면 순서를 바꿔도 되지만
> **그 경우 W7에서 멀티홉 스킬 계측을 다시 붙여야 한다.**

### W9. 프로바이더 계층이 LangChain을 벗는다

**대상:** D4 (§11.4)
**완료 기준:**
- `ModelProviderBase.create_llm()`이 LangChain 타입을 반환하지 않는다
- 라우팅 테스트 전량 통과 — **§4.2 불변식 6종이 그대로**
- 전환 중 계측 공백 0 (W7의 회귀 가드가 이것을 잡는다)

> 🔴 이 웨이브가 트랙 B를 되돌릴 수 있는 유일한 지점이다. §9 **D-7**(SDK 채택 범위)을
> 착수 전에 확정할 것. "전송만" 이외의 답을 고르면 §4.2의 "경계마다 한 번만 해석"이
> SDK 내부 재시도와 충돌한다.

### W10. langgraph 런타임 교체

**대상:** D3b (§11.3)
**완료 기준:** `rg langgraph neos/` 0건 · 대화 재개 의미론이 체크포인터 교체 후에도
동일 (기존 세션 재개 회귀 테스트 통과)

> ⚠️ **가장 큰 웨이브다.** `graph.py` 2,259줄 + 체크포인터 991줄이며, "삭제"가 아니라
> **런타임 교체 + 체크포인트 영속화 자체 구현**이다. 착수 전에 이 웨이브만 별도
> 설계 문서로 분리하는 것을 권한다 — 나머지 아홉 웨이브를 합친 것과 규모가 비슷하다.

---

## 9. 사람의 결정이 필요한 지점

아래는 코드나 측정으로 답이 나오지 않는다. **착수 전에 정해야 한다.**

| # | 결정 | 선택지 | 영향 |
|---|---|---|---|
| **D-1** | W1의 접근 (§8 W1 표) | a 산식 보정 / b 프롬프트 축소 / c 풀 분할 | ✅ 결정됨: **c(풀 분할) + 측정 클램프** — `report_floor_tokens` 안쪽 tier + `prompt_input_bound`로 마무리 프롬프트를 강제 축소(D25, `c9a05d19`/`bf4ba20a`/`30419503`). c가 근본적이나 범위가 크다는 우려는 있었으나, 산식 보정(a)은 input 예측이 빗나가면 floor가 과대해지는 문제가 있어 채택하지 않았다 |
| **D-2** | assertion 0건 리포트 채점 (G3) | 통과 / 반려 / **제3 판정** | ✅ 결정됨 (2026-08-08): **제3 판정 `E_REPORT_EMPTY`** (`94067e11`). 근거는 표본 #2 — 18회 채점 중 5회가 `assertions=0`으로 만점을 받았고 그중 하나(`a82648e3`)는 리포트가 빈 문자열이었다. 막은 것은 서식 검사(`E_REPORT_NO_LIMITS`)뿐이었다. 전용 코드를 쓰는 이유는 `_uncited_stats` 독스트링이 이미 적어둔 것과 같다 — "빈 리포트"와 "인용 안 한 리포트"는 정반대의 수정을 요구한다 |
| **D-3** | E3 judge 모델 분리 시점 | W4에서 / 출하 직전 / 즉시 | 즉시 하면 진행 중 표본과의 비교가 끊긴다 |
| **D-4** | dev floor 비율 | 현행 22%(4,400/20,000) 유지 / 축소 | ✅ 결정됨: **dev `global_token_cap` 20,000 → 100,000** — 기존 캡은 `worker_analysis` 호출 한 번(input_bound 5,542~17,723)도 담지 못했다. 새 floor 비율은 41.0%(41,040/100,000)로 default(43.7%)와 같은 수준(`4a2499cc`/`5376048a`). 논의 중 80,000으로 합의됐다가 `grading_input_ratio` 교정(4.0→5.0) 후 100,000으로 재조정됐다 — 80,000이면 경고 임계값 0.5가 상시 발동한다 |
| **D-5** | 트랙 D 착수 시점 (§11.0) | W6 이후 / W1 직후 / 트랙 A와 병행 | 권고: **W6 이후**, 단 D3a(crewai)만 W5로 앞당김. 병행하면 §10.2의 "측정 중 변경 금지"를 어겨 W1~W4 표본이 무효가 된다 |
| **D-6** | citation을 스킬로 만들 것인가 (§11.2) | 스킬화 / **공용 렌더러로 통합** / 현행 유지 | 권고: **통합**. 스킬 계약은 `execute → SkillResult`(외부 데이터 가져오기) 모양이고 citation은 검증된 클레임을 표시하는 일이라 계약이 맞지 않는다. 요청 원문("고유 스킬화")과 다른 결론이므로 명시적 승인이 필요하다 |
| **D-7** | 네이티브 SDK 채택 범위 (§11.4) | **전송(transport)만** / 에이전트 루프까지 / 전면 위임 | 권고: **전송만**. 루프까지 위임하면 모델 선택·재시도가 SDK 내부로 들어가 §4.2의 "경계마다 한 번만 해석"·"크로스 프로바이더 폴백 금지"가 깨진다 — 트랙 B의 I1–I6을 되돌리는 셈이다 |
| **D-8** | 콜렉터 정본 스키마 (§11.1) | `LLMCallRecord` 확장 / 계층별 어댑터 3종 유지 / OTel span 대체 | 권고: **`LLMCallRecord` 정본 + 계층 어댑터**. span 대체는 관찰가능성엔 맞지만 데이터셋 용도(재학습·평가 코퍼스)에는 부적합하다 |
| **D-9** | langgraph 교체를 이 문서에서 다룰 것인가 (§11.3 D3b) | **별도 설계 문서로 분리** / W10으로 유지 | 권고: **분리**. `graph.py` 2,259줄 + 체크포인터 991줄로, 나머지 아홉 웨이브를 합친 것과 규모가 비슷하다 |

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
| 프로세스 env가 테스트 지정값을 이김 | ~~litellm·crewai~~ → **litellm만 남음** (2026-08-08, D3a가 crewai import를 제거). import 시 `load_dotenv()`로 `.env`를 `os.environ`에 복사 | `4b37a3fe` · `b5e03802` |
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

# 게이트웨이 / 프론트 — 현재 cargo 5/5, test:source 174 passed
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

## 11. 트랙 D — 프레임워크 이탈과 계측 통일 (2026-08-07 신설)

네 과제(D1 콜렉터 확장 · D2 스킬화 · D3 langgraph/crewai 삭제 · D4 네이티브 SDK 전환)는
**출하 기준 S1–S6에 직접 걸려 있지 않다.** 그러나 서로 강하게 얽혀 있고, 특히 D4는
D1의 유일한 자동 계측 지점을 파괴한다. 하나의 트랙으로 다루는 이유가 그것이다.

### 11.0 의존 그래프와 착수 순서

```
D3a crewai 삭제 ────(독립·즉시 가능)───────────────────────────> 완료
D1 콜렉터 탈-LangChain ──> D1 루프·코딩 확장 ──┐
D2 스킬화 ────────────────────────────────────┼──> D4 네이티브 전환 ──> D3b langgraph 제거
                                              ┘
```

**D3b는 D4의 선행이 아니라 결과다.** langgraph를 먼저 지우면 대체 런타임이 없다.

> ⚠️ **트랙 D는 라이브 표본 측정 구간과 상호배타다.** §10.2가 "실행 중 프롬프트·모델
> 변경 금지"를 못박고 있는데, D1·D4는 정확히 LLM 호출 계층을 바꾼다. W1의 5+1 표본이
> 아직 미실행이므로(§8 W1), **트랙 D의 D1·D2·D4는 W1~W4의 측정이 끝난 뒤에 착수한다.**
> D3a(crewai)만 예외다 — 죽은 코드 삭제라 호출 경로를 건드리지 않는다.

### 11.1 D1 — 데이터셋 콜렉터를 루프·코딩 에이전트로 확장

**현재 계측 범위 (2026-08-07 실측):**

| 경로 | 자동 계측 | 근거 |
|---|---|---|
| LangChain 계열 에이전트 (21개 파일) | ✅ `create_tracked_llm` 약 70곳 | `neos/utils/llm_wrapper.py:312` |
| `neos/coding/` (코딩 에이전트 루프) | ❌ **0곳** | `rg 'dataset' neos/coding/` 무결과 |
| `neos/workflow/deep_analysis/` | ❌ **0곳** | 자체 `llm.py`가 usage를 따로 센다 |

**장애물 ① — 콜렉터가 LangChain 타입에 묶여 있다.**
`TrackedLLM`은 `BaseLanguageModel`·`BaseMessage`·`LLMResult`를 직접 임포트한다
(`llm_wrapper.py:10-12`). 반면 코딩 루프는 `CanonicalMessage`/`ModelUsage`
(`neos/coding/model/base.py`)를, deep_analysis는 `LLMResponse`(`llm.py:36`)를 쓴다.
**서로 다른 usage 표현이 셋 있고 콜렉터는 그중 하나만 안다.**

**✅ D1b 해소 (2026-08-08, `29223829`) — 배출구를 늘리지 않고 없앴다.**
워커 teardown·job 완료·`atexit`에 flush를 더 다는 길은 택하지 않았다. 새 진입점이
생길 때마다 누군가 flush를 기억해야 하고, 잊으면 조용히 사라진다 — 이 저장소가
반복해서 다친 그 실패 모드다. 대신 `add_record`가 곧 영속화 지점이 되도록 바꿨다
(`neos/dataset/record_sink.py`). 레코드 1건 = JSONL 1줄을 `datasets/records/{날짜}/
{PID}-{난수}.jsonl`에 append한다.

| 제약 | 이유 |
|---|---|
| 동기 파일 I/O | `create_llm_call_record`가 동기 함수다 — sync 호출부(`invoke`)에서도 불린다 |
| 프로세스당 파일 | 잠금 없이 워커 N개가 동시에 쓴다. 파일명이 PID를 담아 출처도 남는다 |
| 절대 던지지 않는다 | 수집 실패는 데이터 손실이지만, 예외를 올리면 그 LLM 호출 자체가 죽는다 |
| 잘린 줄은 건너뛴다 | 프로세스가 쓰다 죽으면 마지막 줄이 불완전하다. 그 한 줄 때문에 앞의 것을 잃지 않는다 |

완료 기준 검증은 **실제 서브프로세스를 띄워** 한다
(`tests/dataset/test_record_sink.py::test_a_separate_process_leaves_its_records_behind`)
— 모킹으로는 "별도 프로세스에서 살아남는다"를 증명할 수 없다.

메모리 리스트와 `_auto_save_dataset()`은 그대로 뒀다. 기존 `datasets/*.jsonl` 산출물과
`get_statistics()` 소비자를 깨지 않기 위해서다. **디스크가 정본이고 메모리는 이 프로세스가
본 것의 캐시다.**

**장애물 ② — 콜렉터가 프로세스 메모리 싱글턴이다.**
`LLMCallCollector`는 `_records: List[...]`를 클래스 변수로 들고 있고(`collector.py:19-29`),
영속화는 `graph.py:2056`을 지나갈 때만 일어난다. 코딩 에이전트는 Celery 워커에서,
deep_analysis는 job 서비스에서 돈다 — **둘 다 그 flush 지점을 지나가지 않는 별도
프로세스다.** 지금 구조로는 확장해도 레코드가 워커와 함께 사라진다.

| 안 | 내용 | 트레이드오프 |
|---|---|---|
| a | `TrackedLLM`을 두고 코딩·deep_analysis용 별도 어댑터 추가 | 가장 작다. 대신 usage 표현 3개가 그대로 굳는다 |
| **b** | `LLMCallRecord`를 정본 스키마로 두고 각 계층이 어댑터로 변환 **(권장)** | D4 이후에도 살아남는 유일한 안 — 레코드가 LangChain을 모르게 된다 |
| c | 콜렉터 폐기 후 OTel span으로 대체 | 관찰가능성 스택과 합쳐지지만, 데이터셋 용도(재학습·평가 코퍼스)에는 span이 부적합하다 |

**완료 기준:**
- `neos/coding/`·`neos/workflow/deep_analysis/`의 LLM 호출이 `LLMCallRecord`로 남는다 — ⬜ D1c
- 워커 프로세스에서 생성된 레코드가 `graph.py` flush 지점 없이 영속화된다 — ✅ **D1b 완료** (`29223829`)
- `TrackedLLM`이 `langchain_core` 임포트 없이 동작한다 — ✅ **D1a 완료** (`d9681104`)
- 계측 확장이 §6 ④(토큰 집계는 API `usage`만 사용)를 위반하지 않는다: 자체 추정 금지 — ✅ 회귀 가드 있음

**D1a 결과 (2026-08-08).** 조사해 보니 §11.1이 적은 장애물 ①은 예상보다 얕았다 —
`LLMCallRecord`는 **이미 프레임워크 중립**이었고(`input_messages: List[Dict]`·
`output_text: str`·평범한 int), LangChain에 묶여 있던 것은 정본 스키마가 아니라
`TrackedLLM`의 **어댑터**뿐이었다. `isinstance(BaseMessage)`·`isinstance(LLMResult)`
두 곳과 타입 주석 다섯 곳을 형태 판정(`.content`·`.llm_output`·`.generations`)으로
바꾸니 `rg langchain neos/utils/llm_wrapper.py`가 **0건**이 됐다.
`create_tracked_llm` 호출부 79곳은 **한 줄도 바뀌지 않았다.**

회귀 가드는 `tests/utils/test_llm_wrapper_decoupling.py`다. 모듈이 langchain을
import하지 않는다는 것 자체를 단언하고, 역할 없는 메시지(`CanonicalMessage` 모양)와
LangChain 모양이 같은 필드를 내는지, usage가 없을 때 0을 지어내지 않고 `None`을
내는지(§6 ④)를 고정한다.

### 11.2 D2 — 멀티홉 검색·citation 고유 스킬화

**대상 규모 (실측):**
- 멀티홉: `neos/agents/search_agents/multi_hop/` 5개 모듈 2,087줄 +
  `multi_hop_search.py` 381줄. LLM 호출 7곳(decomposer 3 / integrator 2 / extractor 2)
- citation: `deep_analysis/citation.py` 55줄 + `neos/utils/citations.py` 105줄 +
  exporters 3개 — **한 곳에 모여 있지 않다**

스킬 계약은 `BaseSkill`(`neos/skills/base/skill.py:15`) + `SKILL.md` frontmatter,
자동 발견은 `neos/skills/manager/auto_discovery.py`다.

**🔴 가장 중요한 제약 — 스킬화가 설계 P3를 깰 수 있다.**
`skills_adapter.py`는 스킬을 **discovery 전용**으로만 소비한다:
`(skill, query) → [{url, title, snippet}]`. 검색(retrieval)은 `fetch.py` 독점이고
스킬이 준 URL은 반드시 fetch를 거쳐 원문 대조로 검증된다
(`skills_adapter.py:3-6`에 명시). **멀티홉 스킬이 답변을 반환하면 검증 사슬을
우회한다** — 검증되지 않은 문장이 리포트에 실린다는 뜻이다.

citation은 더 근본적으로 맞지 않는다. 스킬 계약은 `execute(params) → SkillResult`,
즉 **외부 데이터를 가져오는** 모양이다. citation 렌더링은 가져오는 일이 아니라
**이미 검증된 클레임을 표시하는** 일이다. 스킬 슬롯에 끼우면 discovery 파이프라인에
렌더러가 섞인다.

| 대상 | 안 | 평가 |
|---|---|---|
| 멀티홉 | **discovery 전용 스킬** — 홉마다 URL만 반환, 답변 조립은 하네스가 | ✅ P3 유지. 대신 `answer_extractor`·`result_integrator`는 스킬 밖에 남는다 |
| 멀티홉 | 완결형 스킬 — 답변까지 반환 | ❌ P3 위반 |
| citation | 스킬화 | ❌ 계약 불일치 (가져오기 ≠ 표시하기) |
| citation | **공용 렌더러로 통합** — 3곳을 `neos/utils/citations.py`로 수렴 | ✅ 실제 문제는 "스킬이 아니라 흩어져 있는 것"이다 |

> **권고:** citation은 스킬이 아니라 **통합 대상**으로 재정의한다. 요청 원문은
> "고유 스킬화"였으나 스킬 계약이 discovery 모양이라 citation은 들어갈 자리가 없다.
> 목적(중복 제거·단일 렌더 경로)은 모듈 통합으로 더 잘 달성된다 — §9 **D-6**에서 확정.

**완료 기준:**
- 멀티홉이 `SKILL.md` + `BaseSkill`로 등록되고 auto-discovery 카운트 9 → 10
- 멀티홉 스킬을 discovery 소스로 쓴 run의 `E_QUOTE_MISMATCH` 비율이 기존 소스와 동등
- citation 렌더 경로가 3개 → 1개

### 11.3 D3 — langgraph·crewai 코드 삭제

**두 개를 같은 항목으로 묶으면 안 된다. 위험도가 두 자릿수 다르다.**

#### D3a. crewai — ✅ **완료** (2026-08-08, `963730ee`)

삭제한 것: `neos/agents/base.py`의 import 1줄 · `_create_agent()` · `create_task()` ·
`run_crew()` · `self.agent` 필드 · `pyproject.toml`의 `crewai>=0.175.0`.
전체 스위트 **2,422 passed / 0 failed** — 호출자가 정말 0곳이었음이 확인됐다.
§10.3 오염원 2번에서 crewai가 빠졌고 **litellm만 남는다** — 회피책(`4b37a3fe`)은
그대로 둔다.

아래는 착수 전 실측 기록이다.

#### (기록) crewai는 이미 죽은 코드였다 (2026-08-07 실측)

| 심볼 | 외부 호출자 |
|---|---|
| `BaseAgent.run_crew` | **0곳** |
| `BaseAgent.create_task` | **0곳** (동명의 `service.create_task`는 무관) |
| `self.agent` (crewai `Agent`) | **0곳** |

즉 현재 상태는 **모든 BaseAgent 인스턴스가 생성 시 `crewai.Agent`를 하나씩 만들고
아무도 쓰지 않는 것**이다(`base.py:31,34-44`). 삭제 대상은 import 1줄 + 메서드 2개
+ 필드 1개 + `pyproject.toml` 의존성 1줄이다.

> **부수 효과가 본체보다 크다.** §10.3 오염원 2번("litellm·crewai가 import 시
> `load_dotenv()`로 `.env`를 `os.environ`에 복사", `4b37a3fe`)에서 crewai가 빠진다.
> 회피책을 고치는 게 아니라 **원인 하나를 제거**하는 것이다.

#### D3b. langgraph — 살아 있는 실행 엔진이다

| 파일 | 줄 |
|---|---:|
| `neos/workflow/graph.py` | 2,259 |
| `neos/workflow/checkpointer.py` | 588 |
| `neos/workflow/distributed_graph.py` | 438 |
| `neos/workflow/checkpointers/hybrid_checkpointer.py` | 403 |
| `neos/workflow/builder/workflow_executor.py` | 304 |
| 그 외 | `observability/` 3개, `recursive/graph.py`, `api/services/research_session_service.py` |

`graph.py`는 프로덕션 챗 경로 본체이고, D23 이후 deep_analysis job 제출도 여기서 한다
(`graph.py:1051–1122`). 그리고 교체 대상은 StateGraph만이 아니라 **체크포인터 991줄**이다
— LangGraph 체크포인터를 걷어내면 대화 재개 의미론을 직접 구현해야 한다.

> ⚠️ **이 항목을 "삭제"로 적으면 다음 사람이 규모를 오해한다.** 정확한 서술은
> **"오케스트레이션 런타임 교체 + 체크포인트 영속화 자체 구현"**이다.
> §5.3의 FE3(없는 파일을 가리키는 백로그)과 같은 종류의 사고를 예방하는 표기다.

**완료 기준 (분리):**
- **D3a:** `pyproject.toml`에서 `crewai>=0.175.0` 제거 · 전체 스위트 2,386 passed 유지 ·
  §10.3 오염원 표에서 crewai 항목 삭제
- **D3b:** `rg langgraph neos/` 0건 — **D4 완료 이후에만 성립 가능**

### 11.4 D4 — 네이티브 SDK 전환 (claude-agent-sdk / openai-agents)

📌 **이 저장소에는 네이티브 구현이 이미 두 개 있다.** 새로 설계하는 문제가 아니라
**어느 것을 정본으로 삼을지** 고르는 문제다.

| 구현 | 위치 | 성격 |
|---|---|---|
| 코딩 루프 | `neos/coding/model/base.py`(`CodingModel` 프로토콜·`CanonicalMessage`·`ModelRequest`·`ModelUsage`) + `model/anthropic.py`(raw `anthropic` 스트리밍) | 스트리밍·툴콜·usage 완비. **LangChain 참조 0** |
| deep_analysis | `deep_analysis/llm.py`(`LLMResponse`·`call_json`) | 단발 JSON 호출 특화. 예산·카세트와 결합 |
| (변환 대상) | `neos/providers/` — `base.py`·`anthropic.py`·`openai.py`·`gemini.py`·`ollama.py` | 전부 `BaseLanguageModel` 반환. OpenClaw 레지스트리의 계약면 |

**전체 범위를 정하는 결정 하나: `ModelProviderBase.create_llm()`의 반환 타입.**
지금은 `BaseLanguageModel`이며(`providers/base.py:19`), 이것이 LangChain을 저장소
전체에 고정하는 못이다. 이 계약을 바꾸면 `create_tracked_llm` 약 70곳이 전부 영향을 받는다.

| 안 | 내용 | 트레이드오프 |
|---|---|---|
| **a** | `neos/coding/model/`의 `CodingModel` 프로토콜을 저장소 공용으로 승격 **(권장)** | 이미 프로덕션에서 도는 코드다. 이름이 coding에 묶여 있어 이동·개명이 필요 |
| b | `claude-agent-sdk`/`openai-agents`를 프로바이더로 직접 채택 | 에이전트 루프·툴 실행을 SDK에 위임 → 코드 감소. 대신 **두 SDK의 루프 의미론이 다르다**(툴 승인·중단·재개) |
| c | 프로바이더 계층은 자체 프로토콜(a) + 에이전트 루프만 SDK(b) | 범위가 가장 크지만 각 층이 제 역할을 한다 |

**🔴 라우팅 불변식과의 충돌 (§4.2).**
"경계마다 한 번만 해석", "크로스 프로바이더 폴백 추가 금지"는 **NEOS가 모델 선택을
소유한다**는 전제 위에 있다. 반면 `claude-agent-sdk`와 `openai-agents`는 각자 루프
안에서 모델·재시도를 관리한다. **SDK에 루프를 위임하면 라우팅 결정이 SDK 내부로
새어 들어간다.** 트랙 B가 태스크 6개와 잔여 이슈 I1–I6으로 세운 계약을 되돌리지
않으려면, SDK 채택 범위를 "루프"가 아니라 **"전송(transport)"으로 한정**하는 것이
안전하다 — §9 **D-7**에서 확정.

**완료 기준:**
- `ModelProviderBase.create_llm()`이 LangChain 타입을 반환하지 않는다
- `pyproject.toml`에서 `langchain*` 5종(`langchain`·`-anthropic`·`-community`·
  `-openai`·`langgraph`) 제거
- 라우팅 테스트 전량 통과(`test_model_catalog*`·`test_model_routing`·
  `test_llm_factory_defaults`) — **해석 우선순위 4단계가 그대로여야 한다**
- **전환 중 계측 공백 0** — D1의 콜렉터가 전환 후에도 레코드를 남긴다

---

## 12. 참조

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
