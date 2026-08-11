# 마무리 예산 floor 분할 — 설계

**작성일:** 2026-08-04
**대상:** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §8 **W1** (이슈 G6 · G7)
**브랜치:** `dev`
**선행 문서:** [2026-08-03-deep-analysis-finalization-budget-design.md](2026-08-03-deep-analysis-finalization-budget-design.md)
(G5 — 이 설계는 그 floor를 **대체하지 않고 분할**한다)

---

## 1. 문제

로드맵 §1 실측: 사용자에게 나간 deep-analysis 리포트 중 **LLM이 작성한 것은 0건**이다.
574 run · 183 `report_graded` 동안 `synth_pass`가 한 번도 기록되지 않았다. 조사·검증
파이프라인은 동작하지만 마무리가 굶는다.

G5가 도입한 `floor_tokens`는 조사가 마무리 몫을 침범하는 것은 막았으나, 조립은 여전히
예약을 받지 못한다. 원인 두 가지가 실측으로 확정돼 있다.

### 1.1 G6 — floor와 `reserve()`의 통화가 다르다

`DeepAnalysisConfig.finalization_floor_tokens`(`neos/config/schema.py:894`)는

```
floor = (allowance + 1) × synthesis_max_tokens + report_judge_max_output_tokens
```

로 **출력 토큰만** 계상한다. 반면 `TokenBudget.reserve`(`neos/workflow/deep_analysis/token_budget.py:158`)는

```
reserved_tokens = input_bound + output_tokens
```

로 입력까지 같은 풀에서 차감한다. 예산을 출력으로 적립하고 입력+출력으로 인출한다.

실측 `input_bound` (로드맵 §3.4):

| stage | n | min / 중앙 / max |
|---|---:|---|
| worker_analysis | 26 | 5,542 / 10,893 / 17,723 |
| node_reduction | 22 | 1,225 / 1,369 / **6,480** |
| claim_entailment | 20 | 2,959 / 3,452 / 4,572 |

`node_reduction` 한 번이 최대 6,480을 입력으로만 쓴다 — 기존 dev floor 4,400 전체보다 크다.

#### 1.1.1 더 깊은 원인 — `conservative_input_bound`는 바이트를 센다

`conservative_input_bound`(`token_budget.py:50`)는 JSON 직렬화한 request의 **UTF-8 바이트 수 + 64**를
반환하고, 그 값이 토큰 수로 쓰인다. 한국어는 문자당 3바이트이므로 실제 입력 토큰의
**약 3~4배**를 부과한다.

**이 함수는 고치지 않는다.** `settle()`은 `actual_tokens > reserved`이면
`TokenBudgetContractError`를 낸다(`token_budget.py:183`). 즉 bound는 입력 토큰의 **참인
상한**이어야 한다. UTF-8에서 `토큰 수 ≤ 바이트 수`는 항상 참이지만, `≤ 바이트 ÷ 2`는
순수 ASCII(1문자 = 1토큰 = 1바이트)에서 깨진다. 이 비관성은 하드 캡 보장의 대가다.

따라서 **floor도 같은 바이트 통화로 사이징해야 한다.** G6의 "input을 안 센다"는 표층이고,
진짜 제약은 이것이다.

### 1.2 G7 — floor가 단일 풀이라 순서만으로 조립이 굶는다

`FINALIZATION_STAGES`(`token_budget.py:25`)는 `node_reduction` · `report_assembly` ·
`report_grading` 3종이며 **같은 풀을 선착순으로** 쓴다. `finalization_reduction_allowance=2`는
floor의 *크기*만 정하고 `reduce_node` 호출 수를 제한하지 않는다.

`Synthesizer.reduce_tree`(`synthesizer.py:321`)는 abandoned가 아닌 **노드마다 한 번씩**
`reduce_node`를 부른다. 상한이 없다. default run `20c4798f`(floor 12,800) 추적:

| stage | 예약 | `input_bound` | `max_out` |
|---|---:|---:|---:|
| node_reduction | 7,984 | 3,984 | 4,000 |
| node_reduction | 8,324 | 4,324 | 4,000 |
| node_reduction | 10,116 | 6,480 | 3,636 |
| **report_assembly** | — | — | **예약 없음** |

6 run 평균 **3.7회 vs allowance 2** — 상시 초과다.

### 1.3 이번 조사에서 추가로 확인한 것 (로드맵 미기재)

1. **충돌 재조사가 발동하면 리덕션이 두 배 돈다.** `_finalize`가 `_reduce_and_resolve`를
   두 번 호출한다(`orchestrator.py:850`, `881`). 최악 `2N`회.
2. **재시도 루프는 조립·판정을 각각 최대 3회 쓴다.** `_finalize`는 `report_retry_cap + 1 = 3`회
   돌고, 회차마다 `assemble` 1회 + (결정론 게이트 통과 시) 판정자 1회다
   (`orchestrator.py:898`). floor는 각 1회분만 계상한다.
3. **`call_json`은 잘림 시 한 번 더 예약한다.** 상한을 2배로 확장해 재호출하므로
   (`llm.py:393-448`) `node_reduction` 한 번이 예약 2건이 될 수 있다.
4. **`report_grading` 예약 0건은 예산 문제가 아니다.** `ReportGrader.grade`는 결정론
   게이트를 통과해야 agentic으로 간다(`graders/report.py:204`). 85%가
   `E_REPORT_UNCITED`에서 걸리므로 판정자에 애초에 도달하지 못한다. 이는 **G3(W3)** 소관이며
   이 설계의 범위가 아니다.
5. **비대칭 강등.** `reduce_node`는 `TokenBudgetExhausted`를 잡아 자식 답변을 이어붙여
   조용히 계속하고(`synthesizer.py:254`), `assemble`은 같은 예외에서 템플릿으로 강등된다
   (`synthesizer.py:160`). 즉 **덜 중요한 단계가 예산을 먼저 가져가고 가장 중요한 단계가
   굶는다.**

---

## 2. 목표와 비목표

### 목표

- `report_assembly`가 리덕션 호출 수와 무관하게 유효한 예약을 받는다 (G7).
- floor가 `reserve()`가 실제로 차감하는 통화(입력 + 출력)로 사이징된다 (G6).
- 마무리 프롬프트의 입력 크기가 **추정이 아니라 강제**된다.
- 리덕션 강등이 원장에 남아 "조립이 살았는가"를 사후에 판정할 수 있다.

### 비목표 (명시적으로 하지 않는 것)

| 항목 | 이유 |
|---|---|
| `conservative_input_bound` 수정 | §1.1.1 — 하드 캡 보장이 이 비관성에 의존한다 |
| `report_grading` 도달률 개선 | G3 / W3. 결정론 게이트가 선행 원인이다 |
| `report_uncited_ratio_max` 조정 | G3 / W3. 정책 결정(D-2)이 선행한다 |
| FE 라벨 6종 추가 | FE1 / W2 |
| `reduce_node` 호출 수 하드 캡 | 풀 격리가 같은 일을 하며, 캡은 "예산은 남았는데 못 부른다"는 새 실패 모드를 만든다 |
| 라이브 표본 실행 | §10.2 "정확히 1회" 원칙 — 코드 확정 후 사용자가 1회 실행 |

---

## 3. 설계

### 3.1 floor를 중첩 계단으로

단일 풀을 **중첩된 계단**으로 바꾼다.

```
cap
├── report_floor_tokens   ← report_assembly · report_grading 만 접근
├── (reduction 몫)        ← + node_reduction 도 접근
└── (나머지)              ← + 조사 단계도 접근
```

`TokenBudget.reserve`의 ceiling 결정:

| stage | ceiling |
|---|---|
| `report_assembly`, `report_grading` | `remaining_tokens` |
| `node_reduction` | `remaining_tokens − report_floor_tokens` |
| 그 외 (조사) | `remaining_tokens − floor_tokens` (= 기존 `available_for_investigation`) |

**의도적 최소 변경.** `floor_tokens`(총합)와 `available_for_investigation`의 의미를 그대로
유지하고 안쪽 계단 `report_floor_tokens` 하나만 추가한다. 따라서
`Budgeter.should_stop`(`budgeter.py:128`)과 `Orchestrator.run`의 floor 정지 판정
(`orchestrator.py:977`)은 **손대지 않는다.**

`TokenBudget.__init__`이 불변식 `0 ≤ report_floor_tokens ≤ floor_tokens`를 강제한다
(위반 시 `ValueError`).

**호출 수를 세지 않고 G7을 해소하는 이유:** 리덕션이 몇 번 돌든 `report_floor_tokens`에
물리적으로 닿지 못한다. allowance를 넘는 리덕션은 기존 graceful degrade 경로로 흘러가고,
조립은 자기 몫을 그대로 받는다.

### 3.2 사이징 — 입력 허용량을 `synthesis_max_tokens`에서 유도

프로파일마다 노브를 3개씩 늘리지 않기 위해, 입력 허용량을 이미 프로파일별로 존재하는
`synthesis_max_tokens`의 비율로 유도한다.

```
assembly_unit   = (assembly_input_ratio  + 1) × synth
grading_unit    =  grading_input_ratio   × synth + report_judge_max_output_tokens
attempt_unit    = assembly_unit + grading_unit
report_floor    = (report_retry_cap + 1) × attempt_unit
reduction_unit  = (reduction_input_ratio + 1) × synth
reduction_floor = finalization_reduction_allowance × reduction_unit
floor_tokens    = report_floor + reduction_floor
```

새 설정 3개 (`DeepAnalysisConfig`, 전역 정책이므로 프로파일별 아님):

| 설정 | 값 | 근거 |
|---|---:|---|
| `reduction_input_ratio` | 1.6 | **실측**: `node_reduction` `input_bound` 최대 6,480 ÷ synth 4,000 = 1.62 |
| `assembly_input_ratio` | 3.0 | **정책 클램프** — §3.3이 프롬프트를 이 안에 강제로 밀어 넣는다 |
| `grading_input_ratio` | 5.0 | **유도값** — 아래 |

`assembly_input_ratio`는 추정이 아니라 **선택한 상한**이다. §3.3의 클램프가 프롬프트를 그
안에 밀어 넣으므로 추정 오차가 발생할 여지가 없다.

`grading_input_ratio`는 다르다. `ReportGrader.grade_agentic`에는 클램프를 넣지 않는다 —
판정자에게 잘린 리포트를 주면 판정 대상이 바뀌어 판정 자체가 무의미해진다. 대신 **유도**한다:

> 판정자의 입력은 리포트 본문이고, 리포트 본문은 조립의 출력이며, 조립의 출력은
> `synthesis_max_tokens`로 이미 유계다. 남는 것은 토큰 → UTF-8 바이트 환산뿐이다.
> 한국어는 문자당 3바이트이고 한 음절이 대체로 1토큰이므로 토큰당 약 3바이트, 드문
> 4바이트 문자와 JSON 이스케이프를 얹어 **토큰당 4.5바이트**를 상한으로 잡는다. 여기에
> `report_judge.md` 템플릿(~600바이트)을 더해 5.0 × synth로 반올림한다.

즉 `assembly`는 강제된 상한, `grading`은 다른 상한에서 **유도된** 상한이며, 어느 쪽도
자유 추정이 아니다.

**`report_floor`가 재시도 3회분을 담는 이유:** 사용자 결정(§7 D-5). 로드맵 §3.3은 재조립
2회가 결과를 바꾼 적이 없다고 기록하지만, 그 관측은 **템플릿 리포트에 대한 것**이다.
W1 이후 재조립 대상이 LLM 산문으로 바뀌므로 이전 관측은 그대로 이월되지 않는다.

#### 결과 수치

| 프로파일 | synth | cap | reduction_floor | report_floor | floor | 비율 | 조사 몫 |
|---|---:|---:|---:|---:|---:|---:|---:|
| default | 4,000 | 300,000 | 20,800 | 110,400 | 131,200 | **43.7%** | 168,800 |
| dev | 1,200 | **100,000** | 6,240 | 34,800 | 41,040 | **41.0%** | 58,960 |

두 프로파일 모두 `finalization_floor_warn_ratio = 0.5` 아래다. `synthesis_max_tokens`나
`report_retry_cap`을 올리면 경고가 발동한다 — 의도된 동작이다.

#### dev `global_token_cap`을 20,000 → 100,000으로 올린다

현행 20,000은 **`worker_analysis` 호출 한 번(input_bound 5,542~17,723)도 확실히 담지
못한다.** dev 프로파일은 입력이 과금되기 전에 사이징됐고, dev run이 병리적인 이유가
여기 있다.

> ⚠️ **이 값은 논의 중 80,000으로 합의됐다가 100,000으로 올렸다.** 당시 계산은
> `grading_input_ratio = 4.0`을 전제했고, 그 값은 §3.2에서 5.0으로 유도 교정됐다.
> 80,000을 유지하면 floor 비율이 **51.3%**가 되어 `finalization_floor_warn_ratio = 0.5`
> 경고가 상시 발동한다. 100,000이면 41.0%로 default(43.7%)와 같은 수준에 놓인다.
> 80,000을 고수하려면 `report_retry_cap`을 dev에서 1로 낮추는 편이 낫다(floor 29,440 = 36.8%).

비용: dev run 1회의 상한이 5배가 된다.

### 3.3 클램프 — 추정하지 않고 강제한다

프롬프트를 렌더한 뒤 **예산이 쓰는 것과 똑같은 자**로 재고, allowance를 넘으면 줄여서
다시 렌더한다.

`llm.py`에 헬퍼를 추가한다. `_budgeted_dispatch`가 `reserve()`에 넘기는 request와 **동일한
모양**을 만들어야 같은 자가 되므로 그 코드 옆에 둔다:

```python
def prompt_input_bound(model: str, prompt: str) -> int:
    """call_llm 이 reserve() 에 넘기는 것과 동일한 request 로 잰 input bound."""
    return conservative_input_bound(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "tools": None}
    )
```

`Synthesizer.assemble`과 `Synthesizer.reduce_node`가 **렌더 → 측정 → (초과 시) 축소 →
재렌더**를 유한 횟수 반복한다. 루프와 축소 정책은 별도 모듈 `prompt_clamp.py`에 두어
LLM·DB 없이 테스트되게 한다. allowance는 `Synthesizer`의 프로퍼티로 계산한다 —
`synthesis_max_tokens`가 이미 프로파일 해석된 값으로 들어와 있고 비율은 전역이므로,
생성자 파라미터를 늘리면 같은 수에 원천이 둘 생긴다.

| 호출부 | allowance |
|---|---|
| `Synthesizer.assemble` | `assembly_input_ratio × synthesis_max_tokens` |
| `Synthesizer.reduce_node` | `reduction_input_ratio × synthesis_max_tokens` |
| `ReportGrader.grade_agentic` | 없음 — 클램프하지 않는다 (§3.2) |

축소 정책은 두 슬롯(`primary` · `secondary`)에 대한 단일 함수이며, 호출부가 자기 재료를
매핑한다 — `assemble`은 (자식 요약 블록, caveats), `reduce_node`는 (verified 클레임 줄,
자식 요약 줄). 루트 답변과 질문 텍스트는 이 함수에 넘어가지 않으므로 결코 잘리지 않는다.

`Synthesizer.reduce`(M1 단일 레이어 경로, `synthesizer.py:40`)는 클램프하지 않는다.
`_finalize`가 쓰지 않는 하위 호환 경로이며 마무리 floor를 소비하지 않는다.

#### 축소 우선순위 (사용자 결정, §7 D-6)

`assemble`의 입력 세 조각에 대해 **caveats → 자식 요약 꼬리 → 자식 개수** 순으로 버린다.
루트 요약은 절대 건드리지 않는다 — 본문 커버리지를 최우선으로 지킨다.

1. `caveats`를 뒤에서부터 제거
2. 그래도 초과하면 각 자식 요약(`child_blocks`)을 끝에서 잘라냄
3. 그래도 초과하면 자식 개수를 줄임 (뒤에서부터)

`reduce_node`도 같은 원리를 적용한다(조각은 `claim_lines` · `child_lines`).

#### 종료 보장

모든 가변 조각을 비운 뒤에도 템플릿 자체가 allowance를 넘으면 축소 루프는 더 줄일 것이
없다. 이 경우 클램프를 포기하고 그대로 진행한다 — `reserve()`가 판단하게 두고,
`finalization_prompt_clamped`에 `exhausted: true`로 남긴다. 무한 루프를 만들지 않는다.

### 3.4 새 이벤트 2종

로드맵 §3.2의 규칙("새 fallback을 추가하려면 그 fallback이 남기는 이벤트를 함께
정의한다")에 따른다. 두 이벤트 모두 **개수와 식별자만** 싣는다 — 응답 텍스트는 싣지 않는다
(기존 `llm_truncated` 규약과 동일).

| 이벤트 | 언제 | 페이로드 |
|---|---|---|
| `finalization_prompt_clamped` | 클램프가 실제로 잘랐을 때 | `stage`, `bound_before`, `bound_after`, `allowance`, `dropped_primary`, `dropped_secondary`, `exhausted` |
| `node_reduction_degraded` | `reduce_node`가 예산 소진/파싱 실패로 강등 | `question_id`, `child_count`, `reason` |

`node_reduction_degraded`는 **W1 검증에 필수**다. 현재 강등(`synthesizer.py:254`)은 원장에
아무 흔적을 남기지 않아, "리덕션이 강등됐지만 조립은 살았다"(= 설계 의도대로)와
"리덕션이 다 성공했다"를 구분할 수 없다.

`reason`은 기존 `caveats` 문자열과 같은 값을 쓴다: `token_budget_exhausted` |
`node_summary_unparseable`.

---

## 4. 변경 대상

| 파일 | 변경 |
|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | `report_floor_tokens` 파라미터 · 불변식 검증 · stage별 ceiling 계단 · `REPORT_STAGES` 상수 · `record_prompt_clamped` / `record_node_reduction_degraded` |
| `neos/config/schema.py` | `assembly_input_ratio` · `grading_input_ratio` · `reduction_input_ratio` 추가; `finalization_floor_tokens` 산식 교체 + `report_floor_tokens()` 신설; `DeepAnalysisDevProfileConfig.global_token_cap` 20,000 → 100,000 |
| `neos/workflow/deep_analysis/llm.py` | `prompt_input_bound()` 헬퍼 |
| `neos/workflow/deep_analysis/synthesizer.py` | `assemble` · `reduce_node`에 클램프 루프; 강등 이벤트 기록; allowance 주입 |
| `neos/workflow/deep_analysis/orchestrator.py` | `report_floor_tokens`를 `TokenBudget`에 전달 |
| `neos/workflow/deep_analysis/service.py` | 두 floor를 config에서 계산해 주입; 클램프 allowance 주입 |
| `neos/config/loader.py` | `warn_finalization_floor_ratio`가 새 산식을 쓰도록 (공유 메서드라 자동) |

---

## 5. 테스트 (전부 결정론적, 실 LLM 없음)

| # | 고정하는 것 | 위치 |
|---|---|---|
| T1 | `node_reduction`은 `report_floor_tokens`에 닿지 못하고 `report_assembly`는 닿는다 | `tests/workflow/deep_analysis/test_budgeter.py` |
| T2 | `report_floor_tokens > floor_tokens`이면 `__init__`이 `ValueError` | 동일 |
| T3 | `finalization_floor_tokens`가 입력 비율을 포함하고 `report_floor + reduction_floor == floor_tokens` | `tests/workflow/deep_analysis/test_config_defaults.py` |
| T4 | **G7 재발 가드** — 리덕션이 allowance를 초과해 N회 돌아도 `report_assembly` 예약이 성공하고 `synth_pass`가 원장에 남는다 | `tests/workflow/deep_analysis/test_orchestrator_token_budget.py` |
| T5 | **클램프** — 거대한 자식 요약을 준 `assemble`의 `prompt_input_bound`가 allowance 이하다. 축소 순서가 caveats → 자식 꼬리 → 자식 수다 | 신규 `test_finalization_clamp.py` |
| T6 | **G8 재발 가드** — `min_viable_output_tokens` 거절이 그대로 동작한다 | 기존 `test_budgeter.py` 유지 |
| T7 | 두 신규 이벤트가 기대 페이로드로 원장에 적재된다 | 신규 `test_finalization_clamp.py` |

T5는 `prompt_input_bound`를 **테스트에서도 프로덕션과 같은 함수로** 호출한다 — 자를 두 벌
두면 클램프의 유일한 보장이 깨진다.

### 갱신이 필요한 기존 테스트

`tests/workflow/deep_analysis/test_budgeter.py`의 floor 테스트들이 새 계단 구조에서 의미를
유지하도록 갱신한다. `test_config_defaults.py`의 dev cap 기대값(20,000)도 바뀐다.

---

## 6. 완료 기준

- T1–T7 통과
- `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q` 통과
- `.venv/bin/python -m pytest` 전체 회귀 0 (기준선 2,234 passed / 0 failed)
- `ruff` clean

**미판정으로 남기는 것:** 로드맵 W1의 `synth_pass ≥ 1`(S1)은 라이브 표본이 필요하다.
§10.2의 "정확히 1회" 원칙상 코드가 확정된 뒤 사용자가 1회 실행한다. 그 전까지 W1은
**미판정**이며, 로드맵 §2.2의 S1은 ❌로 유지한다.

---

## 7. 결정 기록

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| D-1 | W1 접근 (로드맵 §9) | **풀 2분할 + 측정 클램프** | 산식을 더 정교하게 추정하는 대신 추정이 필요 없게 만든다 |
| D-4 | dev floor 비율 (로드맵 §9) | **dev cap 20,000 → 100,000** | 현행 캡은 워커 호출 하나도 담지 못한다. 논의 시점의 80,000은 `grading_input_ratio` 교정(4.0 → 5.0) 전 수치이며, 유지 시 warn 경고가 상시 발동한다 (§3.2) |
| D-5 | 재시도 루프 예산 보장 | **`report_retry_cap + 1` 회차분 전부 보장** | 재조립 무용 관측은 템플릿 리포트에 대한 것이라 W1 이후로 이월되지 않는다 |
| D-6 | 클램프 축소 우선순위 | **caveats → 자식 꼬리 → 자식 수** | 루트 요약과 본문 커버리지를 최우선 보존 |
| — | `reduce_node` 호출 수 하드 캡 | **도입하지 않음** | 풀 격리가 같은 일을 하고, 캡은 새 실패 모드를 만든다 |
| — | `conservative_input_bound` 완화 | **하지 않음** | `settle()`의 계약이 참인 상한에 의존한다 |

---

## 8. 리스크

| 리스크 | 완화 |
|---|---|
| floor가 캡의 41~44%를 차지 | 재시도 3회분 보장(D-5)의 직접 비용이다. `warn_ratio` 0.5가 남은 여유를 감시하며, 발동하면 `report_retry_cap`을 재검토하라는 신호다 |
| 조사 예산이 줄어 verified claim 수가 감소 | dev cap을 5배로 올려 절대량은 오히려 증가(20,000 → 58,960) |
| 클램프가 리포트 품질을 떨어뜨림 | `finalization_prompt_clamped`가 실제 발동 여부와 삭감량을 남긴다. 발동이 잦으면 비율을 올린다 |
| 새 표본이 이전 표본과 비교 불가 | dev cap 변경으로 이미 단절된다. 로드맵 §8 W1의 라이브 표본이 새 baseline이 된다 |
| 기존 floor 테스트 갱신 중 의도 손실 | 갱신이 아니라 **추가**를 우선한다. 기존 단언이 새 구조에서 무의미해진 경우에만 수정하고 이유를 주석으로 남긴다 |

---

## 9. 참조

- 로드맵: [DEEP_ANALYSIS_HARNESS_ROADMAP.md](../../DEEP_ANALYSIS_HARNESS_ROADMAP.md) §3.4 · §8 W1 · §9
- 설계 정본: [DEEP_ANALYSIS_HARNESS_DESIGN.md](../../DEEP_ANALYSIS_HARNESS_DESIGN.md) §6.7 · §6.8
- 백로그 원장: [TODO_260729.md](../../TODO_260729.md) — G 계열 실측 수치의 원본
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md`
- 선행 설계(G5): [2026-08-03-deep-analysis-finalization-budget-design.md](2026-08-03-deep-analysis-finalization-budget-design.md)
