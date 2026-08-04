# Deep Analysis — entailment discard의 claim recall 손실 측정 설계

**작성일:** 2026-07-27
**상태:** 설계 승인됨, 구현 플랜 미작성
**선행 작업:** `2026-07-25-deep-analysis-claim-entailment.md` (구현),
entailment 실측 평가 (`bc4e0656`, 병합 `ad19cf26`)
**관련 문서:** `docs/TODO_260729.md` §7, `docs/archive/deep_analysis_task_task_resume.md` §5

---

## 1. 배경 — 왜 이 측정이 필요한가

claim entailment 도입 후 실측에서 dev 합계 verified 비율은 `19/38`(50.0%) →
`14/22`(63.6%)로 올랐다. 그러나:

- 이 차이는 **Fisher exact p≈0.42**로 표본오차와 구별되지 않는다
  (Wilson 95% CI: [34.8%, 65.2%] vs [43.0%, 80.3%], 크게 겹침).
- 반면 **claim pool 축소는 크고 명확하다**: graded 38→22 (**-42.1%**),
  verified 절대수 19→14 (**-26.3%**).

즉 이번 표본에서 통계적으로 확실한 것은 "비율이 올랐다"가 아니라 **"claim이 훨씬
적게 남았다"**이다. entailment는 grading **이전에** claim을 discard하므로, 비율
상승이 실질적 품질 개선인지 아니면 단순히 분모를 깎은 결과인지 현재 데이터로는
판별할 수 없다.

**이걸 모르는 상태에서 threshold·prompt·model을 건드리면 잘못된 방향으로
최적화된다.** 그래서 다음 우선순위는 파라미터 조정이 아니라 discard의 정당성
측정이다.

### 1.1 현재 discard는 흔적을 남기지 않는다

`apply_entailment_results`는 discard된 claim을 조용히 버린다:

```python
# neos/workflow/deep_analysis/claim_entailment.py:61-62
if action == "discard":
    continue
```

이벤트도, 로그도, 카운터도 없다. `WorkerResult`에 남는 것은 살아남은 claim뿐이다.
따라서 **과거 run의 discard는 복구 불가능**하며, 기존 아티팩트
`20260725T081707Z`로는 이 측정을 할 수 없다. cassette도 없다
(`funnel_sample_runner.py`는 cassette를 넘기지 않으며 디스크에 기록된 cassette도
없다). 신규 계측 + 신규 run이 불가피하다.

---

## 2. 측정 정의

### 2.1 판정 기준 — 기존 grader

discard된 claim을 **기존 파이프라인의 grader에 통과시켜** 몇 개가 verified 판정을
받는지 센다.

**false-discard 비율 = (discard된 claim 중 verified 판정 수) / (distinct discard 수)**

**분모의 단위는 이벤트가 아니라 distinct claim이다.** 질문이 `open`으로 되돌아가
재조사되면 entailment가 다시 돌고 같은 claim이 또 discard되어 `claim_discarded`
이벤트가 하나 더 쌓인다. 이벤트 단위로 세면 (a) 그 claim이 복제 수만큼 가중되고,
(b) 독립이 아닌 관측으로 n이 부풀어 Wilson 구간이 좁아진다. 그래서 phase 2는
채점 전에 두 번 접는다:

1. `claim_hash(text)`로 병합한다 — ledger가 커밋 claim을 병합하는 것과 **같은**
   run 스코프 동일성이다 (`ledger._upsert_claim`).
2. 해당 run의 `deep_analysis_claims`에 존재하는 hash는 제외한다. 다른 pass에서
   entailment가 살렸다는 뜻이므로 recall 손실이 아니다.

`raw_events` / `distinct_claims` / `kept_elsewhere`를 모두 아티팩트에 남겨 이
축약 과정을 감사 가능하게 한다.

여기서 "verified"는 파이프라인과 동일한 정의다: DeterministicGrader를 통과하고
이어서 AgenticGrader도 통과한 claim. 어느 단계에서 거부되든 verified가 아니다.
Wilson 95% 신뢰구간을 함께 보고한다.

**기존 파이프라인과의 유일한 의도적 차이는 agentic 샘플링 게이트를 우회한다는
점이다**(§4.4). 정상 run에서는 `should_grade()`가 낮은 `value_est × confidence`
claim을 샘플링으로 건너뛰지만, 여기서는 분모를 흐리지 않기 위해 전수 채점한다.
이 차이는 측정을 **보수적으로** 만든다 — 평소 미심사 통과했을 claim도 실제로
심사받기 때문이다.

이 방식을 택한 이유:

- **새로운 판정 권위를 도입하지 않는다.** 프로젝트가 이미 "verified"로 인정하는
  기준을 그대로 쓴다.
- `judge ≠ worker` 불변식이 자동으로 유지된다 (agentic grader는 별도 judge 모델).
- 사람 라벨링 대비 재현 가능하고, 별도 LLM judge 대비 순환 논증을 피한다
  (entailment 판단을 또 다른 entailment 판단으로 검증하면 불일치 시 누가 옳은지
  결정할 수 없다).

### 2.2 ⚠️ 이 측정이 답하지 못하는 것

**grader는 ground truth가 아니다.** 실측에서 grader는 도달한 claim의 상당수를
거부했고 그 87.5%가 overclaim이었다. 따라서:

| 이 측정이 답하는 질문 | 답하지 못하는 질문 |
|---|---|
| entailment가 **파이프라인이 받아들였을 산출물**을 제거했는가? | entailment의 판단이 **의미적으로 옳은가**? |

grader도 거부했을 claim은 "entailment와 grader가 일치했다"만 말해줄 뿐, 둘 중
어느 쪽이 옳았는지는 말해주지 않는다. 그러므로 **측정된 false-discard 비율은 실제
recall 손실의 하한(lower bound)이다.**

이 한계를 감수하는 이유는 실제 의사결정이 "entailment가 출하 가능한 claim을
파괴하고 있는가"이기 때문이다. 그 질문에는 이 측정으로 충분하다.

**추가 한계 — SCOUT effort claim은 그 claim을 작성한 모델이 스스로 판정한다.**
judge는 `role="everyday"`로 해석되어 `claude-sonnet-5`를 쓰고
(`service.py:61-66`), SCOUT effort의 worker도 같은 `role="everyday"`로
해석되어 동일 모델을 쓴다(`worker.py:179`). 즉 SCOUT effort로 생성된
claim에 한해 `judge ≠ worker` 불변식이 깨지며, 그 claim을 쓴 모델이 그
claim을 채점한다. 자기 산출물에 관대한 자기 확인 편향(self-verification
bias)이 일반적이므로 이 편향은 **verified 쪽으로** 기울 개연성이 있고, 그
결과 측정된 false-discard 비율은 실제보다 **과대평가**될 수 있다. 이는
"entailment가 안전하다"는 결론 방향으로는 **보수적**이다 — 비율이
부풀려질수록 §2.3의 안전 임계값(상한 < 10%)은 더 어렵게 통과되므로, 이
편향이 `safe` 판정을 거짓으로 만들 위험은 낮고 오히려 `over_discarding`
쪽으로 오판할 위험만 남긴다. DIG effort는 `role="powerful"`로 해석되어
`claude-opus-5`를 쓰므로(`worker.py:180`, `config.models.dig`) 이 문제에서
자유롭다. **사용자 결정: judge 모델은 바꾸지 않는다** — 바꾸면 이전
prompt-v3·entailment 표본과의 judge 동일성이 깨져 비교 가능성이
사라진다.

### 2.3 사전 등록된 중단 규칙 (pre-registered stopping rule)

**데이터를 보기 전에 확정한다.** 지난 평가에서 p≈0.42 결과를 발견으로 읽을 뻔한
실수를 반복하지 않기 위함이다.

| 조건 | 결론 |
|---|---|
| Wilson 95% CI 상한 **< 10%** | entailment는 안전. verified 비율 상승은 실질적. **중단.** |
| Wilson 95% CI 하한 **> 40%** | entailment가 과도하게 버린다. `narrow` 쪽으로 완화. **중단.** |
| 그 외 (구간이 위 둘 중 어디에도 안 들어감) | **미결. 표본 확대.** 결론 내리지 않는다. |

10%/40%는 판단값이다. 구현 전에 조정할 수 있으나 **데이터를 본 뒤에는 조정하지
않는다.**

#### 2.3.1 ⚠️ `safe`는 계획된 표본 크기로는 도달 불가능하다

verified가 0일 때 Wilson 상한은 `z² / (n + z²)`이다. `z=1.96`에서 이 값이 10%
미만이 되려면 **distinct discard n ≥ 35**가 필요하다 (n=34 → 0.1015, n=35 →
0.0989). 그런데 §5의 `mixed-v1` 5+1 **1회** run에서 기대되는 discard는 대략
16건이고, 그때 달성 가능한 최선의 상한은 ~0.194다.

따라서 계획된 1회 run으로는 **`safe` 판정이 원리적으로 나올 수 없다.**
`over_discarding` 또는 `inconclusive` 둘 중 하나만 반환된다. entailment를
"안전"으로 정리하려면 §5의 단계적 확대가 **pooled distinct discard 35건 이상 +
verified 0건**에 도달해야 한다.

이는 사전 등록된 규칙의 문서화된 성질이지 결함이 아니다. **임계값을 낮춰
해결하지 않는다** — 그것이 바로 §2.3이 금지하는 사후 조정이다. 첫 run이
`inconclusive`로 끝나는 것은 실패가 아니라 예상된 결과다. 같은 내용이
`neos/config/schema.py`의 `DeepAnalysisDiscardRecallConfig` docstring에도 있다.

---

## 3. 아키텍처

2단계로 나눈다. 핵심 이유는 **측정이 측정 대상을 오염시키지 않게** 하기 위함이다.
deep analysis는 하드 토큰 상한이 있어서, run 도중에 discard된 claim까지 채점하면
예산이 조기 소진되어 run 동작 자체가 바뀐다.

```
PHASE 1 — 포착 (run 중, 추가 토큰 0)
  worker._refine_claims()
    ├─ keep / narrow  → WorkerResult.claims            (기존과 동일)
    └─ discard        → WorkerResult.discarded_claims  ← 신규
  orchestrator
    ├─ commit_blobs(result.blobs)                      (기존과 동일)
    └─ claim_discarded 이벤트 기록                      ← 신규 (append-only)

PHASE 2 — 채점 (오프라인, 별도 스크립트, judge 토큰만 소모)
  run_id로 claim_discarded 이벤트 조회
    → ProposedClaim 재구성 (evidence blob은 ledger에 이미 있음)
    → DeterministicGrader  (네트워크 없음, 무료)
    → AgenticGrader        (judge 모델, 전수 채점)
    → 아티팩트: false-discard 비율 + Wilson CI
```

### 3.1 Phase 2가 오프라인으로 가능한 근거

두 가지를 코드에서 확인했다:

1. **DeterministicGrader는 네트워크 I/O를 하지 않는다.**
   모듈 docstring이 명시하며, evidence 검증은
   `await self.ledger.get_blob(evidence.raw_ref)`로 ledger에서 읽는다.
2. **discard된 claim의 evidence blob도 ledger에 커밋된다.**
   `self._blobs`는 evidence 수집 단계에서 채워지고 `_refine_claims`와 무관하다.
   `WorkerResult.blobs`는 discard 여부와 상관없이 전체 blob을 싣고,
   orchestrator는 `commit_blobs`(`orchestrator.py:656`)를 claim 순회
   (`:661`)보다 **먼저** 실행한다.

따라서 discard된 claim의 evidence는 run 종료 후에도 ledger에 남아 있으며 재채점이
가능하다.

---

## 4. 컴포넌트

| 변경 | 파일 | 비고 |
|---|---|---|
| discard를 버리지 말고 반환 | `claim_entailment.py:61-62` | 순수 함수 유지 |
| discard를 위로 전달 | `models.py:59` `WorkerResult` | `confidence_clamped_count` 선례와 동일 패턴 |
| 이벤트 기록 | `orchestrator.py:647-656` | 신규 kind `claim_discarded` |
| 채점 스크립트 | `scripts/deep_analysis_discard_recall.py` (신규) | 두 grader 재사용 |

### 4.1 `apply_entailment_results` 반환 타입 변경

현재 시그니처는 `list[ProposedClaim] | None`이고, `None`은 **검증 실패 → 원본
batch로 fail-open**을 의미한다. 이 의미론은 반드시 보존한다.

반환값을 작은 결과 객체로 바꾼다:

```python
@dataclass
class EntailmentOutcome:
    refined: list[ProposedClaim]
    discarded: list[ProposedClaim]
```

- 검증 실패 시 여전히 `None` 반환 → 호출부는 원본 claims를 그대로 쓰고
  **discard 기록도 남기지 않는다** (버려진 게 없으므로).
- `narrow`는 discard가 아니다. `discarded`에 넣지 않는다.

### 4.2 `claim_discarded` 이벤트 payload

`Ledger.log(kind, qid, payload)`를 그대로 쓴다. append-only 불변식(D8 §11.3)은
이벤트를 **추가만** 하므로 유지된다.

```json
{
  "text": "<discard된 claim 원문>",
  "confidence": 0.7,
  "value_est": 1.0,
  "evidence": [
    {"source_url": "...", "excerpt": "...", "raw_ref": "..."}
  ]
}
```

- `value_est`를 payload에 넣는 이유: `AgenticGrader.grade(claim, value_est)`가
  이를 요구하는데, phase 2 시점에 질문을 다시 조회하는 것보다 기록 시점에
  남기는 편이 견고하다. orchestrator는 `value_est = question.value_est`를
  `commit_blobs` 직전(`:647`)에 이미 갖고 있다.
- `qid`는 payload가 아니라 `Ledger.log`의 인자로 전달한다 (기존 이벤트와 동일).
- evidence 3개 필드는 `ProposedEvidence`(`models.py:37-40`)와 1:1이라 phase 2에서
  `ProposedClaim`을 손실 없이 재구성할 수 있다.

### 4.3 기록은 플래그 게이팅하지 않는다

이벤트 쓰기 1건이고 토큰을 쓰지 않는다. 상시 기록하면 이후 모든 run이 스스로
계측된다. 이번 사태의 근본 원인이 **증거 소실**이었으므로, 기본값을 켜두는 것이
같은 실수의 재발을 막는다. (`deep_analysis.enabled` 자체가 프로덕션에서 기본
비활성이므로 추가 노출 위험도 없다.)

### 4.4 Phase 2 스크립트

```
scripts/deep_analysis_discard_recall.py --run-id <id> [--run-id <id> ...]
```

- 채점 전에 `preflight()`가 크리덴셜 존재(boolean만, 값은 절대 출력하지
  않는다)와 DB 연결을 확인한다. `ANTHROPIC_API_KEY`가 없으면 judge 토큰을
  전혀 쓰지 않고 즉시 실패한다.
- 채점 도중 개별 claim에서 발생하는 오류(예: 일시적 `LLMProviderError`)는
  전체 exhaustive pass를 중단시키지 않고 `grade_errors` 카운터로만 집계한다.
  **오류가 난 claim은 절대 verified로 세지 않는다** — 샘플링 게이트·
  `_judge_failed`에서 이미 두 번 고친 것과 같은 fail-open 함정이므로 예외도
  fail-closed로 처리한다.
- 중복된 `--run-id`는 순서를 유지한 채 한 번으로 합친다(중복 세는 문제
  방지). run마다 raw_events 등을 개별 집계해 `manifest.json`의 `per_run`에
  남기므로, 존재하지 않거나 이벤트가 0건인 run도 조용히 묻히지 않고
  `raw_events: 0` 행으로 드러난다.
- `claim_discarded` 이벤트를 run 스코프로 조회 → `ProposedClaim` 재구성
- §2.1의 두 축약(hash 병합 + kept-elsewhere 제외)을 채점 **전에** 적용한다
- `DeterministicGrader` → 통과분만 `AgenticGrader`
- **전수 채점한다.** `AgenticGrader.should_grade()`의 샘플링 게이트를 **우회**하고
  (`sample_rate=1.0`) 모든 discard claim에 `grade()`를 직접 호출한다. 샘플링을
  적용하면 분모가 흐려져 비율 자체가 오염된다.
- **verified 판정은 `Verdict.ok`만으로 인정하지 않는다.** `_judge_failed`는
  비필수(non-mandatory) claim에 대해 fail-open하여 `ok=True, label=None`을
  돌려준다(`agentic.py:61-69`). discard된 claim은 confidence가 낮아 비필수로
  분류되는 비중이 높으므로, `ok`만 보면 이 경로가 측정 대상 모집단에 편중되어
  터지면서 `over_discarding` 쪽으로 편향된다. 따라서 `ok and label == "SUPPORTS"`
  를 요구하고, `ok=True, label=None`은 `judge_failed` 버킷으로 따로 보고한다.
- 아티팩트: `artifacts/deep-analysis-discard-recall/<UTC timestamp>/`
  (`manifest.json`, `recall.json`, `report.md`, `claims.json`) — gitignore
  대상, 커밋 금지
- `manifest.json`에는 실행 영수증(PID·UTC start/end)과 구성 지문(judge 모델,
  **resolve된** worker 모델, `agentic_threshold`, `quote_match_threshold`,
  `confidence_cap`, `agentic_sample_rate_override`)을 남긴다. 이것이 없으면 이
  숫자를 사후 재현할 수 없고 `judge ≠ worker`도 확인할 수 없다. 요청된
  `--run-id`마다 raw_events·distinct_claims·verified 등을 개별 집계하는
  `per_run` 배열도 여기 남긴다 — 중복 run-id는 값이 아니라 순서만 유지한 채
  한 번으로 합치고(§4.4), 존재하지 않거나 이벤트가 없는 run은 `raw_events: 0`
  행으로 드러나 조용히 묻히지 않는다.
- `claims.json`은 §2.2가 요구하는 사람 판정을 위한 claim 단위 명세다.
  채점된 discard claim마다 원문, deterministic 통과 여부, agentic label,
  최종 verified 판정, (있다면) 채점 오류 여부를 담는다. 집계만 있는
  `recall.json`을 부풀리지 않도록 별도 파일로 둔다.
- 크리덴셜 값은 출력·영속화하지 않는다 (boolean 유무만). 모델 ID와 threshold는
  구성이지 비밀이 아니다.

---

## 5. 측정 run 운영

- 범위: `mixed-v1` 5+1 **1회** (기존 표본과 동일 구성)
- **cassette 기록은 착수·완료됐다.** `scripts/deep_analysis_funnel_sample.py`가
  record 모드 `Cassette`를 임시 디렉터리에 만들고,
  `functools.partial(build_orchestrator, cassette=cassette)`를
  `functools.partial(execute_run, build_orchestrator_fn=...)`로 감싸
  `run_sample(execute_fn=...)`에 주입한다. `execute_run`은 이미
  `build_orchestrator_fn` 파라미터를 받고(`jobs.py:132`) `build_orchestrator`는
  이미 `cassette` 파라미터를 받으므로(`service.py:51`), 이 partial 적용
  하나로 `jobs.py`도 그 테스트 fake도 손대지 않고 cassette를 관통시킬 수
  있었다. 초안이 "`execute_run`이 cassette를 받지 않는다"고 판단해 미착수로
  분류했던 것 자체가 틀린 전제였다.
  - run 종료(성공/실패 모두) 후 `cassette.save()`로 디스크에 flush하고
    `write_artifacts`가 만든 아티팩트 디렉터리로 옮긴다(`cassette.json`).
    `Cassette.save()`는 명시적으로 호출하지 않으면 아무것도 쓰지 않으므로
    (`cassette.py:46-60`), 이 flush를 빠뜨리면 "기록됐지만 실제로는 아무것도
    담기지 않은" 최악의 상태가 된다 — 그래서 flush 자체를 회귀 테스트로
    고정했다.
  - **여전히 사실인 것 — 근거는 그대로 유효하다.** cassette는 프롬프트의
    SHA-256으로 키잉되고(`cassette.py:29-36`), discard된 claim은 run 중에
    **한 번도 judge에 들어가지 않는다**. 따라서 run cassette에는 phase 2의
    judge 프롬프트에 대응하는 엔트리가 아예 없고, 재채점이 무료가 되지 않는다
    — phase 2는 어차피 judge 토큰을 쓴다.
  - **실제 가치는 run 자체의 재현성**이다: 같은 worker/decompose/synth 호출을
    재생해 동일한 discard 집합을 다시 만들어낼 수 있고, 그래야 phase 1 계측을
    토큰 없이 회귀 검증할 수 있다. phase 2 비용 절감과는 무관하다.
- 단계적 확대: §2.3 중단 규칙에 따라 미결이면 그때 표본을 늘린다. 미리 3회를
  돌리지 않는다. **§2.3.1 참고 — `safe` 판정에는 pooled distinct discard 35건이
  필요하므로 확대 계획은 이 수치를 전제로 세운다.**
- 실행 영수증(PID·UTC start/end·exit status·통과 boolean)과 구성 지문(model ID,
  threshold, cap)을 `manifest.json`에 남긴다 — 지난 평가에서 도출된 계측 부채다.

---

## 6. 테스트

기존 불변식을 따른다: **테스트에서 실 LLM·네트워크 금지** (cassette 재생 또는
fake 주입).

- `apply_entailment_results`의 discard 수집 — 순수 함수라 직접 단위 테스트
  - keep/narrow/discard 혼합 시 `refined`와 `discarded` 분할이 정확한가
  - **검증 실패 경로가 여전히 `None`을 반환하고 discard를 만들지 않는가** (회귀)
  - `narrow`가 `discarded`에 섞이지 않는가
- orchestrator가 discard 1건당 `claim_discarded` 1건을 기록하는가
- entailment가 fail-open했을 때 이벤트가 **하나도** 생기지 않는가
- phase 2 스크립트: fixture ledger + fake grader로 비율·CI 계산 검증
- **회귀:** `WorkerResult.claims`의 동작이 현재와 완전히 동일한가

---

## 7. 비목표 (Non-goals)

- entailment 동작 자체의 변경 — 이번 작업은 **측정만** 한다
- grader·threshold·sampling·discovery·prompt·model·cap 변경
- 과거 run의 discard 복구 (불가능)
- auto-mutation (D19 유지: 신호는 사람 검토용)

---

## 8. 열린 항목

- §2.3의 10%/40% 임계값은 구현 착수 전 조정 가능. 착수 후에는 고정.
