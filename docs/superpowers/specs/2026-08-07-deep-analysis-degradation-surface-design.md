# 강등을 화면에 그리고 새로고침에도 남긴다 — 설계

**작성일:** 2026-08-07
**대상:** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7 **FE4** (+ 신규 FE5·FE6)
**브랜치:** `dev`
**선행:** W2 — [2026-08-07-deep-analysis-ledger-truth-design.md](2026-08-07-deep-analysis-ledger-truth-design.md)
(커밋 `7318a840..c245805e`)

---

## 1. 배경

W2는 원장의 진실을 **상태**까지 밀어냈다. `progress.degradations`가 리포트를 깎은
사건을 누적하고, 라벨 8종이 붙었다. 그리고 W2 설계 §7 W2-6이 명시적으로 남긴 것이
있다:

> UI 컴포넌트 렌더링은 범위 밖. 상태가 먼저. 시각 디자인은 별도 판단

그 "별도 판단"이 이 문서다. 예약된 다음 차례이며, 로드맵 §2.2의 **S6**을
⚠️ 부분에서 ✅로 올리는 유일한 작업이다.

### 1.1 실측 — 소비자가 0곳이다

```
$ rg degradations web/lib web/hooks web/components web/tests
web/lib/deep-analysis/progress.ts   (정의·생성·누적)
web/tests/source/deep-analysis-progress.test.ts  (테스트)
```

컴포넌트·훅 어디에도 없다. 상태는 정확히 쌓이고 **아무도 읽지 않는다.**

### 1.2 범위 확대 — 새로고침도 포함한다

초안은 새로고침 한계를 범위 밖으로 두려 했다. 사용자 지시로 범위에 넣었고, 넣고
보니 **초안이 서술한 한계가 실제보다 가벼웠다.** 경로를 끝까지 추적한 결과:

| 단계 | 실측 |
|---|---|
| BE가 메시지에 심는 메타데이터 | `{"deep_analysis_run_id": …, "research_status": "completed"}` (`deep_analysis_job_task.py:75-78`) |
| FE 이력 로드가 통과시키는 것 | 임의 키를 그대로 통과 (`utils.ts:132-138`) → `metadata.deep_analysis_run_id` |
| FE 컴포넌트가 읽는 키 | `message.metadata.deep_analysis` = `{run_id, status}` (`message.tsx:400`) |

**두 키 모양이 다르다.** 새로고침하면 `deep_analysis`가 `undefined`라
`DeepAnalysisStatus`가 **아예 렌더되지 않는다** — 강등 경고만 사라지는 게 아니라
카드가 통째로 사라진다. `sessionStorage`의 run 포인터도 종결 시
`forgetActiveRun()`으로 지워지므로(`message.tsx:117`) 그 경로로도 복구되지 않는다.

> 이것은 W2가 만든 결함이 아니라 **원래부터 있던 이름 불일치**다. 지금까지 비용이
> 없었던 이유는 새로고침 후 보여줄 값이 리포트 본문뿐이었고 그건 메시지 본문으로
> 이미 남기 때문이다. FE4가 "완료 후에도 남아야 하는 상태"를 처음 도입하면서 이
> 갭이 비로소 비용을 갖는다. 로드맵 §5.3 FE3(존재하지 않는 파일을 가리키는 백로그)와
> 같은 종류의 사고다 — **키 이름은 계약인데 양쪽이 다른 이름을 썼다.**

---

## 2. 제약이 아키텍처를 정한다

`web/package.json:12`:

```
"test:source": "tsx --test tests/source/**/*.test.ts"
```

**jsdom도 testing-library도 없다.** React 컴포넌트를 렌더해 단언할 수 없다. 따라서
표시 로직을 컴포넌트에 넣으면 회귀 가드가 0이 된다.

| 안 | 평가 |
|---|---|
| **a. `lib/`의 순수 함수 + 얇은 컴포넌트** | ✅ **채택.** 기존 테스트 630줄이 전부 이 패턴 |
| b. 컴포넌트에 라벨 맵 | ❌ 테스트 불가 |
| c. 상태에 문구를 저장 | ❌ `progress.ts:62-64`가 금지 — 재생된 옛 이벤트가 옛 문구를 고착시킨다 |

c를 금지한 주석이 이 설계를 미리 정해뒀다:

> `kind`는 원장의 어휘 그대로 싣고 사람이 읽는 문구는 렌더 시점에 만든다.

---

## 3. 강등 어휘 — 양쪽이 같은 문자열을 만든다

| 원장 이벤트 | 조건 | kind |
|---|---|---|
| `report_assembly_degraded` | 무조건 | 그대로 |
| `node_reduction_degraded` | 무조건 | 그대로 |
| `finalization_prompt_clamped` | `payload.exhausted === true` | 그대로 |
| `report_graded` | `payload.judge`가 있으면 | `judge_unreviewed:<judge>` |

### 3.1 굶은 판정자를 강등에 넣는 이유

W2 설계 §7 W2-3은 강등을 "리포트 **내용**을 깎았는가"로 정의하고 3종만 넣었다.
이번에 판정자를 넷째로 추가한다. 축이 다르기 때문이다 — 내용이 아니라 **보증의
부재**다. 리포트가 실제 심사 없이 게이트를 통과했다는 사실은 로드맵 §2.2 S6이
요구하는 "실패가 사용자에게도 보인다"에 정확히 해당한다.

`graders/report.py:180-232` 확인 결과 세 가지 강등 모드(`budget_exhausted` ·
`truncated` · `unparseable`)가 **전부 `ok=True`를 반환**한다. 즉 재조립 루프를
종료시킨다. 따라서 `judge` 키가 달린 `report_graded`는 **run당 최대 1건이고 항상
최종 판정**이다 — 중간 시도가 오탐으로 잡힐 위험이 없다.

### 3.2 합성 kind를 쓰는 이유

`report_graded`는 kind 자체가 강등이 아니라 **payload가 강등을 결정**한다. 그래서
`degradedReport(): boolean`을 `degradationKind(): string | null`로 바꾸고
`judge_unreviewed:budget_exhausted` 같은 합성 문자열을 만든다.

`withDegradation()`이 kind를 불투명한 문자열 하나로만 다루므로 **머지 로직을 전혀
건드리지 않는다.** 원장의 어휘(`budget_exhausted`)는 접두사 뒤에 그대로 보존된다.

### 3.3 🟡 알려진 중복 — 이 설계가 감수하는 유일한 부채

위 규칙이 **두 곳에 구현된다.**

| 위치 | 언어 | 소비 |
|---|---|---|
| `web/lib/deep-analysis/progress.ts` `degradationKind()` | TS | 라이브 스트림 |
| `neos/workflow/deep_analysis/ledger.py` `degradations()` | Python | 새로고침 후 복원 |

문구(`degradationLabel()`)는 FE 한 곳에만 두어 중복을 막았으나, **"어떤 이벤트가
강등인가"는 갈라진다.** 완화책:

1. 양쪽 구현부에 **상호 참조 주석**을 단다 (파일·함수명 명시)
2. 양쪽 테스트가 **동일한 fixture 목록**을 쓰고, 그 목록이 정본임을 주석에 적는다
3. 로드맵 §7에 **FE6**으로 등록해 다음 사람이 통합을 검토할 수 있게 한다

> **왜 지금 통합하지 않는가.** 통합하려면 (a) BE가 FE 어휘를 API로 노출하거나
> (b) FE가 원장 이벤트를 새로고침 후에도 재생하거나 (c) 규칙을 공유 스키마 파일로
> 빼야 한다. (b)는 §4.3에서 기각했고, (a)·(c)는 이 작업보다 큰 계약 변경이다.
> **부채를 지되 보이게 진다** — 로드맵 §3.2의 "고치기 전에 보이게 만든다"와 같은 규율.

---

## 4. 새로고침 복원 — 백엔드가 요약을 싣는다

### 4.1 검토한 안

| 안 | 평가 |
|---|---|
| **B. run 종료 시 원장에서 집계해 메시지 메타데이터에 영속화** | ✅ **채택.** 재생 비용 0. 렌더 시점에 이미 값이 있어 접힘 여부를 즉시 정할 수 있다 |
| A. 종결된 run도 카드를 펼치면 `after=0` 재생 | 규칙 중복 0·충실도 100%. 그러나 **펼치지 않으면 영영 모른다** — S6의 취지를 정면으로 배반 |
| C. B + A 둘 다 | 옛 메시지까지 덮지만 범위가 가장 크다 |

A를 기각한 이유가 핵심이다. 접힌 카드에 "⚠️"를 띄우려면 먼저 재생해야 하는데,
재생하려면 펼쳐야 한다 — **닭과 달걀**이다. B는 값이 메타데이터에 이미 있으므로 이
순환이 없다.

### 4.2 데이터 흐름

```
orchestrator.run() 완료
  → jobs.py: Ledger.degradations() 로 집계          (읽기만 — P2 유지)
  → execute_run 반환 dict에 실음
  → deep_analysis_job_task.py: _persist_assistant_message 가
     metadata["deep_analysis_degradations"] 로 영속화
  → (새로고침) convertBackendMessagesToUI 가 통과
  → deepAnalysisFromMessageMetadata() 가 DeepAnalysisMetadata 로 변환
  → DeepAnalysisStatus 가 렌더
```

`Ledger.degradations()`는 W2가 만든 `Ledger.report_markdown()`(`ledger.py:891`)의
바로 옆에 같은 모양으로 붙는다 — **이름 있는 조회 경로**라는 W2의 선례를 따른다.

### 4.3 출처 선택

```ts
const entries = progress.degradations.length > 0
  ? progress.degradations
  : (deepAnalysis.degradations ?? []);
```

라이브가 이긴다. 근거: 라이브 세션에서는 `progress`가 자라는 중인 정본이고,
새로고침 후에는 `alreadySettled`라 구독하지 않으므로 `progress.degradations`가
항상 비어 있다. **둘 다 값을 가지는 경우는 발생하지 않으므로** 이 삼항식은 우선순위
판단이 아니라 "둘 중 채워진 쪽을 고른다"는 뜻이다 — 그렇게 주석에 적는다.

---

## 5. 프론트엔드 변경

### 5.1 파일

| 파일 | 상태 | 역할 |
|---|---|---|
| `web/lib/deep-analysis/degradation.ts` | 신규 | 상태 → 사람이 읽는 경고 (`degradationLabel` · `degradationNotices`) |
| `web/lib/deep-analysis/metadata.ts` | 신규 | BE 메시지 메타데이터 → `DeepAnalysisMetadata` 브리지 |
| `web/lib/deep-analysis/progress.ts` | 수정 | `degradedReport()` → `degradationKind()` |
| `web/lib/types.ts` | 수정 | 스키마에 `degradations` 추가 |
| `web/lib/utils.ts` | 수정 | `convertBackendMessagesToUI`가 브리지 호출 |
| `web/components/deep-analysis-status.tsx` | 수정 | 렌더 + `defaultOpen` |

`degradation.ts`와 `metadata.ts`를 `progress.ts`에 합치지 않는 이유: `progress.ts`의
일은 *원장 → 상태*이고, 두 신규 파일의 일은 각각 *상태 → 문구*와 *메시지 → 상태*다.
생애주기가 다르다.

### 5.2 미지의 kind는 버리지 않는다

`degradationLabel()`이 모르는 kind를 만나면 폴백 문구로 kind 자체를 싣는다. 조용히
떨구면 이 작업이 없애려던 바로 그 죄를 반복한다 — `progress.ts:148-153`이 커서에
대해 내린 것과 같은 판단이다.

### 5.3 접힌 카드 — 공용 컴포넌트를 건드리지 않는다

완료된 run은 카드가 접힌다(`defaultOpen={phase === "running" || phase === "pending"}`).
공용 `ToolHeader`(`components/elements/tool.tsx:76`)에 배지 prop을 추가하는 대신:

```tsx
defaultOpen={phase === "running" || phase === "pending" || entries.length > 0}
```

**강등된 리포트는 펼쳐진 채로 도착한다.** 공용 API를 넓히지 않고, "⚠️ 2" 같은
숫자가 아니라 실제 문구를 보여준다.

### 5.4 `lastActivity` 게이트는 유지한다

`deep-analysis-status.tsx:139`의 `phase !== "completed"`를 그대로 둔다. 로드맵 §7
FE4는 이 게이트를 결함으로 적었으나, 그 서술은 **강등을 보여주는 채널이
`lastActivity`뿐이었을 때** 참이었다. 강등이 영구 블록으로 분리되면 활동 줄은 "지금
무슨 일이 일어나는가"라는 본래 역할만 하면 되고, 완료 후엔 의미가 없다. 게이트를
없애면 같은 사실이 두 줄로 중복된다.

---

## 6. 이 설계가 덮지 않는 것 (명시)

| 항목 | 이유 | 추적 |
|---|---|---|
| 실패한 run의 강등 | `_persist_assistant_message`는 완료 시에만 호출된다. 실패 run은 메시지 자체가 없다 | FE5 |
| 기존 메시지 소급 적용 | 신규 run부터 | — |
| `_persist_assistant_message`가 예외를 삼킨다 | 로드맵 §7 **P1 #8**과 같은 지점. 강등 영속화가 그 결함의 새 피해자가 된다 | P1 #8에 주석 추가 |
| 강등 규칙 이중 구현 | §3.3 | FE6 |

---

## 7. 테스트

| # | 대상 |
|---|---|
| F1 | `degradationLabel()` — 알려진 kind 4계열이 각각 고유 문구를 낸다 |
| F2 | `degradationLabel()` — 미지의 kind가 폴백 문구로 **남는다** (누락 금지) |
| F3 | `degradationNotices()` — `count > 1`이면 횟수가 문구에 실린다 |
| F4 | `degradationKind()` — `judge` 키가 있는 `report_graded`가 강등으로 잡힌다 |
| F5 | `degradationKind()` — `judge` 키가 없는 `report_graded`는 강등이 아니다 |
| F6 | 재생 멱등성 — 같은 이벤트를 두 번 넣어도 `count`가 1 |
| F7 | `deepAnalysisFromMessageMetadata()` — BE 키를 FE 모양으로 옮긴다 |
| F8 | `deepAnalysisFromMessageMetadata()` — `deep_analysis_run_id`가 없으면 `undefined` |
| F9 | `deepAnalysisFromMessageMetadata()` — 깨진 `degradations` 값에 던지지 않는다 |
| B1 | `Ledger.degradations()` — 4계열 집계와 `exhausted=false` 제외 |
| B2 | `Ledger.degradations()` — 이벤트가 없으면 빈 리스트 |
| B3 | `execute_run` 결과 dict에 `degradations`가 실린다 |
| B4 | `_persist_assistant_message`가 메타데이터에 적재한다 |
| X1 | **교차 어휘 고정** — F4·B1이 같은 fixture 목록을 쓴다 (§3.3 완화책 2) |

검증 명령 (로드맵 §10.4):

```bash
pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q
```

---

## 8. 결정 기록

| # | 결정 | 근거 |
|---|---|---|
| FE4-1 | 표시 로직은 `lib/`의 순수 함수 | `test:source`에 DOM이 없다. 컴포넌트에 넣으면 회귀 가드 0 |
| FE4-2 | 굶은 판정자를 강등 넷째로 추가 | 내용이 아니라 **보증의 부재**. `ok=True`로 종료되므로 run당 1건 보장 |
| FE4-3 | 합성 kind `judge_unreviewed:<judge>` | payload가 강등을 결정하는 유일한 케이스. 머지 로직 무변경 |
| FE4-4 | 새로고침 복원은 BE 메타데이터(B안) | A안은 "펼쳐야 보인다 ↔ 보려면 펼쳐야" 순환. S6 취지 배반 |
| FE4-5 | 강등이 있으면 카드를 펼친 채로 연다 | 공용 `ToolHeader` API를 넓히지 않고 숫자 대신 문구를 보여준다 |
| FE4-6 | `lastActivity` 게이트 유지 | 강등이 영구 블록으로 분리되면 게이트는 결함이 아니다. 없애면 중복 |
| FE4-7 | 규칙 이중 구현을 **감수하고 표시**한다 | 통합은 이 작업보다 큰 계약 변경. 주석·테스트·백로그 3중으로 남긴다 |
| FE4-8 | 미지의 kind를 버리지 않는다 | 조용한 누락은 이 작업이 없애려는 바로 그 죄 |

`Ledger.degradations()`가 원장에 조회 경로를 하나 더 추가하므로 이 결정들을
`neos/workflow/deep_analysis/DECISIONS.md`에 **D27**로 기록한다 (D26 = W2).

---

## 9. 리스크

| 리스크 | 완화 |
|---|---|
| 🟡 FE·BE 강등 규칙이 나중에 갈라진다 | §3.3 3중 완화책. 갈라져도 **과소 보고**로 기운다(BE가 덜 세면 경고가 덜 뜬다) — 거짓 경고보다 낫다 |
| 메타데이터 브리지가 기존 메시지 로드를 깨뜨린다 | `deep_analysis_run_id`가 없으면 `undefined` 반환(F8). 기존 경로는 그대로 |
| `execute_run` 반환 애너테이션 `dict[str, str]` 확대가 호출부를 깬다 | 호출부는 `_execute` 하나. `dict[str, object]`로 넓히고 타입 검사로 확인 |
| `_persist_assistant_message`의 예외 삼킴이 강등을 조용히 날린다 | 이번 범위 밖(§6). 다만 로그 문구에 강등 건수를 포함해 흔적을 남긴다 |
| 강등 카드가 항상 펼쳐져 대화가 시끄러워진다 | 강등이 있을 때만. 조용한 강등을 없애는 것이 목적이므로 의도된 소음 |

---

## 10. 참조

- 로드맵: [DEEP_ANALYSIS_HARNESS_ROADMAP.md](../../DEEP_ANALYSIS_HARNESS_ROADMAP.md) §2.2 S6 · §5.2 · §7 FE4
- W2 설계: [2026-08-07-deep-analysis-ledger-truth-design.md](2026-08-07-deep-analysis-ledger-truth-design.md)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D26이 W2)
- FE 감사: [FE_AUDIT_260717.md](../../FE_AUDIT_260717.md) — ⚠️ 2026-07-17 기준
