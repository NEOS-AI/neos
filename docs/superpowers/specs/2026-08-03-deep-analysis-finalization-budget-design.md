# 마무리 단계 예산 확보 설계 (G5)

**작성일:** 2026-08-03
**대상:** `neos/workflow/deep_analysis/`
**근거:** `docs/TODO_260729.md` G5
**선행 작업:** `56b28f3e`(G2 게이트 관측), `847a2369`(G1), `6cfbf4cc`(G5 발견)

---

## 1. 문제 — 사용자는 LLM이 쓴 심층분석 리포트를 받은 적이 없다

이벤트 로그 전수 집계다. 추정이 아니라 실측이다.

| stage | 예약 건수 | 허용 상한 |
|---|---:|---|
| `claim_grading` | 1,070 | 중앙값 300 |
| `worker_analysis` | 721 | 중앙값 2,000, **최소 2** |
| `node_reduction` | 26 | 중앙값 748, **최소 10** |
| **`report_assembly`** | **0** | — |
| **`report_grading`** | **0** | — |

그리고 **`synth_pass` 이벤트가 0건**이다(165회 리포트 채점에 걸쳐). 이 이벤트는
LLM 조립 경로에서만 기록되므로, **LLM 리포트 조립이 한 번도 실행된 적이 없다**는
뜻이다. `token_budget_exhausted`는 53건 기록됐다.

### 1.1 왜 이렇게 되는가

조사 루프의 종료 조건이 **예산 고갈 그 자체**다:

```python
async def should_stop(self, ledger) -> bool:
    if self.token_budget is not None and self.token_budget.exhausted:
        return True
```
(`budgeter.py:116-118`)

그래서 모든 run이 예산을 다 쓴 상태로 마무리 단계에 도착한다. run 종료 시점 소진율은
통과한 run 중앙값 96.8%(9/9가 ≥95%), 막힌 run 96.7%(48/52가 ≥95%)다.

그다음 세 단계가 **각자 조용히 퇴화한다**:

1. `node_reduction` — 부스러기로 돈다(허용 상한 최소 10토큰)
2. `report_assembly` — `TokenBudgetExhausted` → `synthesizer.py:150`이 잡아
   `deterministic_report()`로 **템플릿 조립**으로 떨어진다
3. `report_grading` — `TokenBudgetExhausted` → `report.py`가 잡아 결정론적 판정으로
   되돌린다

세 fallback 각각은 합리적이다. **문제는 셋이 겹쳐 완전한 예산 고갈을 보이지 않게
만든다는 것이다.** 템플릿 리포트의 한계 절은 실제로
`"전체 심층분석 토큰 상한에 도달했습니다."`라고 적고 있었다 — 시스템은 내내 말하고
있었고 아무도 증상으로 읽지 않았다.

### 1.2 G3과의 관계

이것이 G3(「빈 리포트가 통과하고 알맹이 있는 리포트가 막힌다」)도 설명한다.
게이트는 합성된 산문이 아니라 **템플릿**을 채점하고 있었다. claim이 없는 run은
숫자 없는 템플릿을 만들어 assertion 0건 → 통과. claim이 있는 run은 그것들을 각주
없이 나열한 템플릿을 만들어 `E_REPORT_UNCITED`. 게이트 휴리스틱의 결함이 아니라
템플릿의 모양이었다.

**G3은 이 작업 이후에 다시 판단해야 한다.** 판단 대상이 달라지기 때문이다.

---

## 2. 범위

### 2.1 포함

마무리 3단계(`node_reduction` · `report_assembly` · `report_grading`)를 위한 예산
floor 확보, dev 프로파일의 합성 상한 분리, 두 fallback의 기록.

### 2.2 제외 (명시적)

| 항목 | 사유 |
|---|---|
| G3 — assertion 0건 리포트 채점 | 이 작업이 판단 근거를 바꾼다. 이후 재판단 |
| G4 — 리포트 본문 보존 | 별도 작업 |
| dev `global_token_cap` 상향 | 운영자 결정. 이 설계는 상한을 바꾸지 않는다 |
| A3 · A4 — worker 상한 재보정 | thinking 몫 측정이 선행 |
| C1 — discard recall 재측정 | 독립 과제 |

---

## 3. 아키텍처 — 두 겹의 방어

```
global_token_cap
├─────────────────── 조사 몫 ───────────────────┤├── floor ──┤
                                                 ↑
              TokenBudget.reserve()가 이 선을 지킨다  ← 보장
              - 조사 stage 요청은 이 선 아래로 못 간다
              - 마무리 stage만 내려간다
                                                 ↑
              Budgeter.should_stop()도 같은 선을 본다  ← 낭비 방지
              - available_for_investigation <= 0이면 조사 종료
```

**두 겹이 모두 필요하다.** hard floor만 두면 워커들이 계속 예약을 시도해 거절당하고
`investigate()`가 `flush_partial`로 받아내며 라운드를 헛돈다. 조기 정지만 두면 병렬
워커가 정지 판단 사이로 비집고 들어와 floor를 침범한다 — `parallel_workers`가 1보다
크므로 실제로 가능하다. floor는 **보장**이고 조기 정지는 **낭비 방지**다.

### 3.1 floor가 보장하는 것과 하지 않는 것

`reserve()`는 `input_bound + output_tokens`를 함께 잡는다. assembly 프롬프트는 claim을
전부 싣기 때문에 input이 크다. 따라서 floor가 12,800이어도 assembly가 출력 4,000을
온전히 받는다는 보장은 없다.

**정직한 보장은 이것이다: 마무리 단계는 항상 0이 아닌 예약을 받는다.**

현재는 `reserve()`가 `TokenBudgetExhausted`를 던져 세 단계가 통째로 건너뛰어진다.
"clamp되어 작게 돌았다"와 "아예 안 돌았다"는 다른 실패이고, 이 설계가 닫는 것은
후자다. 전자는 §6의 신호로 드러낸다.

---

## 4. 컴포넌트

### 4.1 `TokenBudget`이 stage를 구분한다

`neos/workflow/deep_analysis/token_budget.py`:

```python
FINALIZATION_STAGES = frozenset({
    "node_reduction",
    "report_assembly",
    "report_grading",
})
```

`TokenBudget.__init__`에 `floor_tokens: int = 0`을 더하고, 프로퍼티를 하나 둔다:

```python
@property
def available_for_investigation(self) -> int:
    return max(0, self.remaining_tokens - self.floor_tokens)
```

`reserve()`는 stage에 따라 서로 다른 천장을 쓴다:

```python
ceiling = (
    self.remaining_tokens
    if stage in FINALIZATION_STAGES
    else self.available_for_investigation
)
output_tokens = min(max_output_tokens, ceiling - input_bound)
if output_tokens < 1:
    raise TokenBudgetExhausted("deep-analysis token budget exhausted")
```

기본값 `floor_tokens=0`이면 동작이 현행과 완전히 같다 — 기존 호출부와 테스트가
그대로 통과한다.

⚠️ **의도적 결합:** 예산 계층이 stage 이름을 알게 된다. 대안은 `is_finalization`
플래그를 `call_llm`/`call_json`/`call_messages`/`_budgeted_dispatch`까지 배관으로
내리는 것인데 호출부를 전부 건드려야 한다. 상수 하나가 명시적이고 한 곳에 모이며
테스트 가능하다.

### 4.2 floor 계산

```python
floor = (
    (finalization_reduction_allowance + 1) * synthesis_max_tokens
    + report_judge_max_output_tokens
)
```

`+1`이 assembly 몫이다. 계산은 `service.py`에서 프로파일 해석과 함께 한 번 한다.

| 프로파일 | allowance | synthesis | judge | floor |
|---|---:|---:|---:|---:|
| `default` | 2 | 4,000 | 800 | **12,800** |
| `dev` | 2 | 1,200 | 800 | **4,400** |

### 4.3 설정값 2개 추가

**(a) `finalization_reduction_allowance: int = 2`** (`DeepAnalysisConfig`)

실측 중앙값이다 — `node_reduction` 호출 수는 run당 중앙값 2, 최대 9. 노드가 더 많은
run은 마지막 몇 reduction이 clamp되지만 **assembly와 judge는 살아남는다.** 그것이
이 값의 목적이다. 최댓값 9로 잡으면 floor가 40,800이 되어 default에서도 부담이 크고
dev에서는 cap의 두 배가 된다.

**(b) `DeepAnalysisDevProfileConfig.synthesis_max_tokens: int = 1200`**

이것이 이 설계의 핵심 수정이다. §5를 볼 것.

### 4.4 `Budgeter.should_stop`

```python
if self.token_budget is not None:
    if self.token_budget.available_for_investigation <= 0:
        return True
```

`token_budget`이 `None`인 경로(주입 없는 테스트)에서는 기존 `spent >= global_token_cap`
검사를 그대로 둔다. floor 산식이 두 곳에 흩어지지 않도록 Budgeter는 floor를 직접
계산하지 않고 `TokenBudget`의 프로퍼티만 읽는다.

### 4.5 `Synthesizer`가 상한을 주입받는다

현재 `synthesizer.py`의 세 곳(`85`, `145`, `230`)이
`settings.config.deep_analysis.synthesis_max_tokens`를 직접 읽는다. 프로파일을 모르기
때문이다. 생성자 인자 `synthesis_max_tokens: int | None = None`을 더하고 `None`이면
현행 설정값을 쓴다. `service.py`가 프로파일 해석 결과를 넘긴다.

---

## 5. dev 프로파일 — floor가 큰 게 아니라 dev의 합성 상한이 컸다

`service.py:104-116`은 dev가 `global_token_cap` · `parallel_workers` · `max_depth`를
덮어쓰게 한다. 그런데 `synthesis_max_tokens`는 덮어쓰지 않는다.

**즉 dev는 예산을 15배 줄이면서(300,000 → 20,000) 합성 상한은 큰 프로파일용 4,000을
그대로 물려받았다.** floor가 dev에 안 맞는 진짜 이유가 이것이다.

| | cap | synthesis | floor | 조사 몫 |
|---|---:|---:|---:|---:|
| `default` | 300,000 | 4,000 | 12,800 | 287,200 (**95.7%**) |
| `dev` — 상한을 그대로 두면 | 20,000 | 4,000 | 12,800 | 7,200 (36%) |
| **`dev` — 이 설계** | 20,000 | **1,200** | **4,400** | **15,600 (78%)** |

**1,200의 근거는 실측이다.** `node_reduction`의 실제 소비량은 run당 중앙값 1,109토큰
(**input 포함**), 그때 허용 상한의 중앙값은 748이었다. 1,200 출력 상한은 관측된
사용량 대비 넉넉하다.

**이것이 dev가 이 결함을 드러내지 못한 이유이기도 하다.** dev는 마무리 경로를 한 번도
실행해 본 적이 없다. 파이프라인을 싸게 훑는 것이 임무인 프로파일이 마지막 3분의 1을
통째로 건너뛰고 있었고, 그래서 `synth_pass = 0`이 오래 눈에 띄지 않았다.

### 5.1 설정 검증 — 백스톱

`floor >= cap × 0.5`이면 설정 로드 시점에 경고한다. 두 숫자와 해법(cap 상향 또는
allowance/synthesis 하향)을 함께 찍는다.

**하드 실패가 아닌 이유:** 위 표대로면 기본 설정에서는 이 경고가 **발생하지 않는다.**
잘못 튜닝된 프로파일을 잡기 위한 백스톱이지 정상 운영에서 보일 신호가 아니다.
정상적으로는 아무도 못 볼 경고를 치명적으로 만들 이유가 없다. 저장소에
`warn_yaml_only_feature_flag_env`라는 같은 모양의 선례가 있다.

---

## 6. 조용한 실패를 남기지 않는다

floor가 있어도 clamp는 일어날 수 있고, floor가 깨지면 예전 침묵이 그대로 돌아온다.
지금 두 fallback은 **아무 기록도 남기지 않는다.**

| 지점 | 현재 | 변경 후 |
|---|---|---|
| `synthesizer.py:150` `except TokenBudgetExhausted` → `deterministic_report()` | 무음 | ledger에 `report_assembly_degraded` 기록 (`{"reason": "token_budget_exhausted"}`) |
| `graders/report.py` `except TokenBudgetExhausted` → `deterministic` | 무음 | `detail="judge_budget_exhausted"` 표시 |

**작성자 자격:** Synthesizer는 이미 `synth_pass`를 ledger에 쓰므로 P2 위반이 아니다.
`ReportGrader`는 P2 읽기 전용이므로 직접 쓰지 않고 `Verdict.detail`에 표시만 하며,
오케스트레이터의 `report_graded`가 이미 `verdict.diagnostics`를 싣는 경로로 흘러간다
(`56b28f3e`).

`synth_pass = 0`을 알아채는 데 세션 하나가 통째로 걸렸다. 그 침묵을 닫는 것이 floor
자체만큼 중요하다.

---

## 7. 테스트

실 LLM/네트워크 금지 — fake 주입만.

| 층 | 검증 |
|---|---|
| `reserve()` floor | 조사 stage는 floor 아래로 못 내려간다 / 마무리 stage는 내려간다 |
| 경계 | `available_for_investigation == 1`에서 조사 예약 성공, `== 0`에서 `TokenBudgetExhausted` |
| 하위호환 | `floor_tokens=0`(기본값)이면 동작이 현행과 동일하다 |
| `should_stop` | `available_for_investigation <= 0`에서 정지 — 거절 루프를 돌지 않는다 |
| floor 산식 | `(finalization_reduction_allowance+1)×synthesis + judge`와 일치, 두 프로파일 각각 |
| `Synthesizer` 주입 | 넘긴 상한이 세 호출 모두에 쓰인다 / `None`이면 설정값 |
| 설정 경고 | 기본값에서는 **발생하지 않는다**. `floor >= cap×0.5`인 설정에서만 발생 |
| §6 신호 2종 | 각 fallback이 기록을 남긴다 |
| 회귀 | `synth_pass`가 실제로 기록되는 경로가 생겼는지 (현재 0건) |

⚠️ **기존 테스트 회귀 위험:** dev 프로파일이 전체 cap을 조사에 쓴다고 가정한 테스트가
있으면 조정이 필요하다. 구현 시 `tests/workflow/deep_analysis/`에서
`global_token_cap` · `dev_profile`을 참조하는 테스트를 먼저 확인할 것.

**테스트 명령:**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

bare `pytest`는 asyncio 마커 수집에 실패한다. Ruff도 통과해야 한다.

---

## 8. 성공 기준

1. 마무리 3단계가 **0이 아닌 예약**을 받는다 — `TokenBudgetExhausted`로 통째로
   건너뛰어지지 않는다.
2. 조사 stage가 floor 아래로 예약할 수 없다 (병렬 워커 포함).
3. `should_stop`이 floor에서 멈춘다 — 거절만 반복하는 라운드가 없다.
4. dev 프로파일이 조사 예산의 78%를 유지하면서 마무리 체인을 실행한다.
5. **`synth_pass` 이벤트가 실제로 기록된다** — 현재 0건인 것이 이 작업의 최종 지표다.
6. 두 fallback이 발동하면 흔적이 남는다.
7. `floor_tokens=0`에서 기존 동작이 완전히 보존된다.
8. deep_analysis 테스트 전량과 Ruff가 통과한다.

---

## 9. 참조

- 잔여 과제 정본: `docs/TODO_260729.md` G1~G5
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D8 append-only, P2 단일 작성자)
- 설계 원본: `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md`
- 직전 작업: `docs/superpowers/specs/2026-08-02-deep-analysis-truncation-propagation-design.md`
