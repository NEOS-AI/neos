# 구성 매니페스트 (트랙 H의 H1) — 설계

**작성일:** 2026-08-22
**트랙:** H — 플러그인 런타임과 동적 합성 (`docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §15)
**선행 조건:** 없음. §15.3이 **트랙 A와 병행 가능한 유일한 단계**로 지정한 것이다 —
이벤트 발행일 뿐 LLM 호출 경로를 건드리지 않으므로 §10.2의 "측정 중 변경"에 걸리지 않는다.

> ⚠️ **이 문서가 말하는 "매니페스트"는 두 가지 중 하나다.** 아티팩트 디렉터리에 이미
> `manifest.json`이 있고(`funnel_sample_runner.py:320`) 그 안에 `config_fingerprint`가
> 있다. 이 설계가 만드는 것은 **원장 이벤트** `run_manifest`이고, 기존 아티팩트
> `manifest.json`은 그 이벤트를 **읽어서** 싣도록 바뀐다. 둘을 뭉치지 말 것 — §3.2가
> 어느 쪽이 정본인지 못 박는다.

---

## 1. 목적과 관문

**목적:** 런 하나의 유효 구성을 이벤트 하나로 못 박아, 아티팩트만으로 그 런이
무엇으로 조립됐는지 복원할 수 있게 한다.

**관문 (§15.3):** 표본 #16~#20의 아티팩트만 주고 매니페스트를 재구성한 뒤
`DECISIONS.md`의 기록과 대조한다. **라이브 표본을 한 건도 쓰지 않는다.**

**이것이 왜 지금 급한가 — 이미 대가를 치렀고, 그 증거가 디스크에 있다.**

§9 D-11이 두 번 정정됐다(D75 → D77 → D78). D75가 원인 지목을 뒤집었고, D77이
D75의 조사 가용 82,400을 72,000으로 정정했으며, D78이 D77의 floor 여유 계산을
다시 고쳤다. 그 사이에 표본이 넷(#17~#20) 돌았고, 셋은 새 측정이 아니라 *이미 돌린
런의 구성을 뒤늦게 계산한 것*이다.

그 정정들이 만진 숫자가 지금 아티팩트에 **없거나 틀리다.** 실측:

```
artifacts/deep-analysis-funnel/20260818T111321Z/manifest.json   (표본 #20)
  config_fingerprint.global_token_cap : 300000
  dev_runs                            : 5
```

`_fingerprint()`(`scripts/deep_analysis_funnel_sample.py:181`)는
`settings.config.deep_analysis.global_token_cap`을 읽는다 — **기본 프로파일 값**이다.
그런데 표본 6런 중 5런은 dev 프로파일이고 dev는
`config.dev_profile.global_token_cap`으로 돈다. **아티팩트가 5/6 런에 대해 틀린
캡을 적어놨다.** 그리고 `finalization_floor_tokens`·`report_floor_tokens`·
`grading_floor_tokens`·`synthesis_max_tokens`·`available_for_investigation`·
`report_floor_funded_attempts`는 **칸 자체가 없다** — D25·D69·D71·D78이 전부 그
없는 칸들을 만진 결정이다.

**즉 지문은 있었는데 못 막았다. 못 막은 이유는 지문이 유도값을 몰랐기 때문이고,
이 설계의 절반은 그 구조적 원인을 없애는 것이다** (§3.1).

## 2. 이 설계가 방어하는 것 — 매니페스트가 거짓말하는 것

매니페스트의 실패 모드는 "없다"가 아니라 **"있는데 틀리다"**다. 없으면 사람이
알지만, 틀리면 D75~D78처럼 **틀린 채로 네 표본이 지나간다.** 거짓말이 들어오는
경로가 둘 실재하고, 설계가 둘 다 **구조로** 막는다.

### 2.1 유도값을 다시 계산하면 어긋난다

`_fingerprint()`가 틀린 캡을 적은 것은 버그가 아니라 **재계산**이다. 같은 값을
두 곳에서 유도하면 두 곳이 갈라진다.

**막는 방법:** `build_manifest()`는 **계산 능력을 갖지 않는다.** `settings`를
import하지 않고, `config.finalization_floor_tokens()`를 부르지 않고, 프로파일
분기를 하지 않는다. `build_orchestrator`가 Orchestrator에 넘긴 **바로 그 값**을
인자로 받아 적기만 한다. 불변식을 검사하는 대신 **"매니페스트가 실제와 다르다"는
상태를 표현 불가능하게** 만든다.

### 2.2 역할을 추측하면 재생성 불가능한 아티팩트에 거짓말이 실린다

이건 추정이 아니다. `_resolved_models()`의 docstring이 직접 적어놨다:

> "The roles mirror the call sites exactly and must stay in step with them:
> `service.py` (judge), `worker.py` (scout/dig), `synthesizer.py` and
> `orchestrator.py` (synth/dig). **A role guessed here would put a lie in the
> one artifact that cannot be regenerated.**"

실측: `resolve_model` 호출 지점은 **9곳**이고 역할 리터럴(`"everyday"`/`"powerful"`)이
9번 하드코딩돼 있다.

| 파일 | 줄 | 역할 |
|---|---|---|
| `worker.py` | 320 | scout / dig (effort 분기) |
| `synthesizer.py` | 272 · 328 · 496 · 627 | synth |
| `orchestrator.py` | 706 · 730 | dig |
| `orchestrator.py` | 903 | judge |
| `service.py` | 61 | judge |

`scripts/deep_analysis_funnel_sample.py:118`의 `_resolved_models()`가 **열 번째
사본**이다. 사본이 열 개면 매니페스트는 "열 번째 사본이 뭐라고 했는지"를 적을 뿐
**"무엇이 돌았는지"를 적지 못한다.**

**막는 방법:** 역할 테이블을 한 곳으로 모으고 9개 호출 지점이 그것을 읽는다
(§3.1의 `model_roles.py`). 이것은 리팩터링이 아니라 **H1의 정확성 요건**이다.

## 3. 구성 요소

### 3.1 새 모듈 둘

**`neos/workflow/deep_analysis/model_roles.py`**

```python
HARNESS_ROLES: dict[str, WorkloadRole] = {
    "scout": "everyday",
    "dig":   "powerful",
    "synth": "powerful",
    "judge": "everyday",
}

def resolve_harness_model(name: str) -> ModelResolution: ...
```

- 하네스 안에서 `resolve_model`을 부르는 **유일한 곳**이 된다.
- 프로바이더는 `"anthropic"` 고정 — 현재 9개 호출 지점 전부가 그렇다. 이 설계는
  그 사실을 바꾸지 않고 **한 곳으로 옮기기만** 한다. 프로바이더를 설정으로 여는
  것은 §4.2 라우팅 불변식에 닿으므로 H1의 범위 밖이다.
- `feature_override`는 테이블이 아니라 `settings.config.deep_analysis.models.<name>`
  에서 읽는다 — 그것이 라우팅 계약의 소비 지점이고(§6 ②) 바꾸지 않는다.

**`neos/workflow/deep_analysis/manifest.py`**

```python
MANIFEST_KIND = "run_manifest"
MANIFEST_VERSION = 1

def build_manifest(*, profile, models, budget, prompts, skills,
                   components, config) -> dict: ...
```

순수 함수. I/O 없음, `settings` 접근 없음, 계산 없음. 인자를 받아 §3.3의 모양으로
정렬해 돌려주기만 한다.

### 3.2 발행 지점 — `service.build_orchestrator`

`build_orchestrator`가 **양쪽 경로의 유일한 관문**이다:

- 프로덕션 job: `jobs.py:132`가 `build_orchestrator_fn=build_orchestrator`
- 표본: `scripts/deep_analysis_funnel_sample.py:287`가 `functools.partial`로 감싼다

그리고 **프로파일과 유도값을 아는 유일한 곳**이다 — Orchestrator는 floor를
주입받을 뿐 프로파일을 모른다(`orchestrator.py:374-388` 주석이 그 이유를 적는다:
골든 테스트가 캡 1,000으로 이 클래스를 짓는다).

```python
manifest = build_manifest(profile=profile, budget={...지역변수 그대로...}, ...)
await ledger.log(MANIFEST_KIND, None, manifest)
```

`return Orchestrator(...)` **직전**에 넣는다. `Ledger.log`는 `db.flush()`까지만
하므로 커밋은 호출자 트랜잭션을 따른다 — 기존 이벤트와 같다.

> **왜 Orchestrator 안이 아닌가.** `Orchestrator.run()`에서 발행하면 프로파일과
> 유도값을 알 수 없어 §2.1이 막으려는 재계산이 되살아난다. 그리고 §15.4 금지
> 1번(플러그인은 원장의 작성자가 아니다)의 정신대로, 매니페스트는 **조립한 쪽**이
> 적는 것이 맞다.

### 3.3 스키마 v1

```json
{
  "manifest_version": 1,
  "profile": "dev",
  "models": {
    "scout": {"role": "everyday", "model": "claude-sonnet-5",
              "source": "role_default", "override": null},
    "dig":   {"role": "powerful", "model": "claude-opus-5",  "source": "role_default", "override": null},
    "synth": {"role": "powerful", "model": "claude-opus-5",  "source": "role_default", "override": null},
    "judge": {"role": "everyday", "model": "claude-sonnet-5","source": "role_default", "override": null}
  },
  "judge_equals_scout": true,
  "budget": {
    "global_token_cap": 140000,
    "synthesis_max_tokens": 2000,
    "finalization_floor_tokens": 53600,
    "report_floor_tokens": 43200,
    "grading_floor_tokens": 21600,
    "min_viable_output_tokens": 2048,
    "available_for_investigation": 86400,
    "report_floor_funded_attempts": 1.2
  },
  "prompts": {"final_compose": "sha256:…", "…": "런 경로 8개"},
  "skills": [{"name": "…", "version": "…"}],
  "components": {
    "grader": "graders.deterministic:DeterministicGrader",
    "agentic_grader": "graders.agentic:AgenticGrader",
    "report_grader": "graders.report:ReportGrader",
    "synthesizer": "synthesizer:Synthesizer",
    "citation_renderer": "citation:CitationRenderer",
    "search_fn": "service:web_search",
    "fetch_fn": null,
    "cassette": false
  },
  "config": {
    "max_depth": 2, "parallel_workers": 2,
    "quote_match_threshold": 0.92, "agentic_threshold": 0.35,
    "agentic_sample_rate": 0.3, "claim_retry_cap": 2,
    "decompose_max_tokens": 3200, "judge_max_output_tokens": 800,
    "entailment_max_output_tokens": 3000,
    "subquestions": {"adopt_threshold": 0.3, "adopt_cap": 4,
                     "budget_policy": "uniform", "reviewer_enabled": false},
    "effort": {"scout": {…}, "dig": {…}, "synth": {…}}
  }
}
```

**위 숫자는 예시가 아니라 2026-08-22 dev 프로파일의 실측값이다** (`…`로 줄인
세 칸 제외). 재현:

```
dev  global_token_cap 140000 · synthesis_max_tokens 2000
     finalization_floor 53600 · report_floor 43200 · grading_floor 21600
     available_for_investigation = 140000 − 53600 = 86400
```

> 🔴 **86,400이 D78이 도달한 바로 그 숫자다.** 로드맵 §1이 D-11 결정을 "dev 조사
> 가용 72,000 → 86,400"으로 적는다. **매니페스트가 있었다면 그 값은 표본 #17
> 시점에 이미 원장에 있었다** — D75 → D77 → D78 세 번의 정정은 이 한 줄의
> 뺄셈을 손으로 다시 한 것이다. 설계의 정당화가 논증이 아니라 산술로 닫힌다.

**설계 판단 넷:**

1. **`available_for_investigation`은 파생값인데 일부러 싣는다.**
   `cap − finalization_floor_tokens`(`token_budget.py:170,177`)이고 런 시작
   시점엔 remaining = cap이다. 중복이지만, **세 번 틀린 것이 정확히 이 뺄셈**이다
   (D75의 82,400 → D77의 72,000 → D78의 86,400). 읽는 사람이 계산하게 두면 네 번째가 온다.

2. **`judge_equals_scout`을 계산해서 싣는다 — `models` 안이 아니라 최상위에.**
   E3(§6 ①)은 "둘 다 `None`이라 같은
   역할로 해석"돼 생겼고, 지금도 깨져 있다. 매니페스트가 그것을 **자백하게** 만든다.
   §15.4 금지 4번("judge 플러그인과 worker 플러그인은 같은 인스턴스일 수 없다")이
   플러그인 층에서 세우려는 방어선을, 모델 층에서 먼저 관측 가능하게 만드는 것이다.
   ⚠️ **이 필드는 관측이지 강제가 아니다** — E3는 §8 W4가 해소하며 이 설계는
   모델 선택을 바꾸지 않는다(바꾸면 이전 표본과 비교 불가해진다, §6 ①).

   > 📌 **2026-08-22 정정 (구현 중, 룰링 R4).** 이 문서는 처음에 이 필드를 `models`
   > **안에** 그렸다. `models`의 다른 값은 전부 해석 dict인데 하나만 bool이 되어,
   > `models.items()`를 도는 소비자가 깨진다. 지금은 그것을 도는 소비자가 없어서
   > 옮기는 값이 0이고 — `manifest_version: 1`이 표본에 실리고 나면 같은 이동이
   > 버전 범프를 요구한다. 그래서 **지금** 최상위로 옮겼다.

3. **`models.*.override`를 해석 결과와 나란히 싣는다.** `config`(무엇을 골랐나)와
   `resolution`(무엇이 돌았나)은 다른 사실이고, 기존 지문이 둘을 모두 보존한
   이유가 그것이다(`_fingerprint` 주석 214-217행). 그 판단을 물려받는다.

4. **`components`가 "그래프 토폴로지 해시"를 대체한다.** §15.3이 매니페스트 항목으로
   그것을 적었으나 **심층분석 런은 LangGraph 그래프를 타지 않는다** — 자체
   오케스트레이터 루프다. 이 하네스에서 "무엇이 조립됐나"에 해당하는 것은 부품
   배선이고, §15.1이 "이 저장소는 이미 하네스를 플러그인처럼 다뤄왔다"고 적은 그
   부품들이다. 값은 `type(obj).__module__ + ":" + type(obj).__qualname__`에서
   `neos.workflow.deep_analysis.` 접두어를 뗀 것.

   ⚠️ **소스 해시는 넣지 않는다.** 클래스 이름이 같고 내용이 바뀐 경우(D58·D60·D62
   절삭기 교체가 정확히 그랬다)는 `git` 항의 commit + dirty가 답한다. 파일 해시는
   그것과 중복이고 런마다 파일 읽기가 들어간다.

5. **`prompts`는 `prompts/` 디렉터리 전부가 아니라 런 경로가 쓰는 8개다.**
   디렉터리에는 9개가 있는데 `diagnose_bottleneck.md`는 **런의 구성이 아니다** —
   F1 진단자(표본을 *읽는* 쪽) 전용이고 `scripts/deep_analysis_diagnostician.py:33`
   만 로드한다. 넣으면 그 파일을 고칠 때마다 **실제로 동일한 두 런이 서로 달라
   보인다.** 매니페스트가 재는 것은 "저장소에 무엇이 있나"가 아니라 "이 런이 무엇을
   썼나"다.

   | 프롬프트 | 로더 |
   |---|---|
   | `decompose` · `worker_brief` · `subq_review` | `orchestrator.py` |
   | `final_compose` · `node_summary` | `synthesizer.py` |
   | `claim_entailment` | `worker.py` |
   | `judge` | `graders/agentic.py` |
   | `report_judge` | `graders/report.py` |

**`git` 항은 스키마에 없다** — `_git_identity()`가 계속 아티팩트 층에서 붙인다.
저장소 상태는 런의 구성이 아니라 표본의 구성이고, 한 표본의 6런이 같은 커밋을
공유하므로 런마다 6번 적을 이유가 없다.

### 3.4 재개 의미론 (§15.2 ㉯ 해소)

append-only(D8). 재개하면 `run_manifest`가 **두 번째로 붙는다.** 지우지도
UPDATE하지도 않는다.

**판독 규칙:** 이벤트 seq *N*을 해석할 때 유효 구성은 **seq < N인 마지막
`run_manifest`**다.

이건 감수하는 비용이 아니라 소득이다. 크래시와 재개 사이에 설정이 바뀌면 지금은
그 사실이 어디에도 안 남는다. 두 매니페스트가 다르면 원장이 그것을 말한다.

`Ledger.token_budget_state()`는 kind로 필터하므로 새 kind의 영향을 받지 않는다.

### 3.5 표본 경계 게이트 (§15.4 금지 3번)

거부는 **표본 경계에서만** 한다. `Orchestrator.run()`은 건드리지 않는다 — 그러면
Orchestrator를 직접 짓는 골든·통합 테스트 수십 건이 깨지고, §15.4의 문구가 금지하는
것은 "런"이 아니라 **"표본"**이다.

`scripts/deep_analysis_funnel_sample.py`가 `write_artifacts` **직전에**:

1. 표본의 모든 run_id에 대해 `run_manifest`를 조회한다.
2. 하나라도 없으면 아티팩트를 쓰지 않고 비-0으로 종료한다.
3. 있는데 **서로 다르면** — §4의 정책 판단.

### 3.6 아티팩트 층의 변화

`_fingerprint()`와 `_resolved_models()`를 **삭제**하고, 아티팩트
`manifest.json`의 `config_fingerprint`를 원장에서 읽은 매니페스트로 채운다.

**하위 호환:** 키 이름 `config_fingerprint`는 유지한다. `scripts/deep_analysis_diagnostician.py:495`와
`scripts/deep_analysis_discard_recall.py`가 그 키를 읽고, F1의 채점기·기준선
계산은 D83이 "재사용 가능하게 남긴다"고 정한 자산이다. 안의 모양은 바뀌지만
`_scrub_config()`(`deep_analysis_diagnostician.py:107`)가 계속 통과해야 한다.

**표본이 6런이므로 값이 6개다.** `config_fingerprint`는 이제 단수가 아니라
`{run_id: manifest}` 맵이 되고, 이전 표본과 모양이 달라진다 —
`manifest_version`이 그 경계를 표시한다.

## 4. 사람이 판단할 자리 — 구성이 갈렸을 때

§3.5의 3번이다. dev 5 + default 1이므로 `profile`과 `budget` 항은 **당연히 다르다.**
그런데 `models`나 `prompts` 해시가 갈리면 그건 "한 표본 안에서 구성이 바뀐 것"이고,
§15.2 ㉰이 경고한 귀속 불가 상황이다.

정책 선택지: 중단할 것인가, 기록하고 진행할 것인가, 갈린 항목의 종류에 따라 나눌
것인가. 구현 단계에서 함수 시그니처와 주변 맥락을 깔아두고 **사용자가 결정**한다.

## 5. 테스트 (TDD)

| # | 무엇을 고정하나 |
|---|---|
| 1 | `build_manifest`는 순수하다 — 같은 입력 → 같은 출력, `settings` 미접근 |
| 2 | `build_orchestrator`가 Orchestrator에 넘긴 floor 3종·cap == 매니페스트의 그 값. **§2.1의 재계산 사고를 기계가 막는다** |
| 3 | dev 프로파일 런의 매니페스트 `global_token_cap`이 `dev_profile` 값이다 (**지금 아티팩트가 틀린 그 항목**) |
| 4 | `available_for_investigation == cap − finalization_floor_tokens` |
| 5 | 역할 테이블이 이전(移轉) **전** 9개 호출 지점의 역할과 같다 — `{scout: everyday, dig: powerful, synth: powerful, judge: everyday}`를 회귀 고정. 이전이 조용히 역할을 바꾸는 것을 막는 유일한 장치다 |
| 6 | `deep_analysis/*.py`에서 `model_roles.py` 밖의 `resolve_model` 직접 호출이 0건 (**사본 재발을 기계가 막는다**) |
| 7 | judge와 scout이 같은 모델로 해석되면 `judge_equals_scout: true` |
| 8 | 재개 시 `run_manifest` 2건, 둘 다 보존 |
| 9 | 표본 게이트: 매니페스트 없는 run이 하나라도 있으면 `write_artifacts` 미호출 |
| 10 | 프롬프트 해시가 **런 경로 8개**와 정확히 일치한다 — `diagnose_bottleneck` 미포함, 그리고 런 경로에 프롬프트가 추가되면 실패한다 (누락을 기계가 잡는다) |
| 11 | FE: `activityLabel("run_manifest")`가 `null`이 아니고, `degradationKind()`는 `null`이다 |

## 6. FE 라벨 (§15.3의 명시적 경고)

> "새 kind이므로 §3.2 규칙이 걸린다 — FE 라벨을 같은 변경에 넣는다.
> **FE1이 이벤트 8종에서 정확히 이것을 빠뜨려 §5.2를 치렀다.**"

`web/lib/deep-analysis/progress.ts`의 `activityLabel()`에 `run_manifest`를 추가한다.
**`degradationKind()`에는 넣지 않는다** — 강등이 아니다.

모르는 kind도 커서를 전진시키므로(`progress.ts:148-153`) 라벨 부재가 스트림을 막지는
않는다. 그래도 넣는 이유는 §5.2가 산 교훈이다: 가시성이 원장에서 멈추면 그것을
아무도 모른다.

## 7. 백테스트 관문

표본 #16~#20의 아티팩트(전부 `artifacts/deep-analysis-funnel/`에 있다)로 매니페스트를
재구성하고 `DECISIONS.md`와 대조한다.

| 표본 | 아티팩트 |
|---|---|
| #16 | `20260811T152942Z` |
| #17 | `20260814T132904Z` |
| #18 | `20260814T173905Z` |
| #19 | `20260816T103413Z` |
| #20 | `20260818T111321Z` |

**통과 조건:** 다섯 표본의 아티팩트만으로 §3.3 스키마의 모든 칸을 채울 수 있다.
채울 수 없는 칸이 있으면 그 칸이 곧 "지금 복원 불가능한 것"의 목록이고, H1의
산출물에 그것이 기록돼야 한다.

**예상되는 결과 — 관문은 부분 통과할 것이다.** 과거 아티팩트에는 프롬프트 해시도
스킬 목록도 `components`도 없다. 그것들은 git commit으로만 간접 복원된다.
**그 사실 자체가 H1의 근거**이므로, 백테스트의 산출물은 "통과/실패"가 아니라
**칸별 복원 가능 여부 표**다.

**라이브 표본은 한 건도 쓰지 않는다.**

## 8. 하지 않는 것

- **모델 선택을 바꾸지 않는다.** E3는 관측만 하고 해소는 §8 W4다. 바꾸면 이전
  표본과 비교 불가해진다(§6 ①).
- **`Orchestrator.run()`에 게이트를 걸지 않는다** (§3.5).
- **마이그레이션을 쓰지 않는다.** `DAEvent.kind`는 `String(40)` 자유 문자열이고
  (`neos/database/deep_analysis_models.py:203`) `"run_manifest"`는 12자다.
  H-1 결정(2026-08-22)이 이 경로를 택한 이유가 이것이며, SCHEMA1(마이그레이션 44개
  중 7개 실패)을 악화시키지 않는다.
- **프로바이더를 설정으로 열지 않는다** (§3.1).
- **소스 파일 해시를 넣지 않는다** (§3.3 판단 4).
- **H3(시간적 합성)에 손대지 않는다.** H1의 후속이고 관문이 G2-b라 별도 작업이다.

## 9. 미결로 남기는 것

| ID | 내용 |
|---|---|
| **H-2** | 동적 합성이 라이브 표본 경로에 들어오는 시점 — §9 D-12. 이 설계는 답하지 않는다 |
| **H-3** | 플러그인 버전 고정 정책. `skills[].version`을 싣지만 **고정하지는 않는다** |
| **H1-m1** | `config_fingerprint`가 단수 → `{run_id: manifest}` 맵이 되어 이전 표본과 모양이 다르다. `manifest_version`이 경계를 표시하지만, 이전 표본을 읽는 코드는 두 모양을 다 다뤄야 한다 |

## 10. 참조

- 로드맵: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §15 (트랙 H), §2.3 (플러그인 층 방어선),
  §15.4 (금지 4종)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` — D25·D69·D71·D75·D77·D78
  (이 설계가 갚는 측정 부채), D8 (append-only)
- 코드 표면: `neos/workflow/deep_analysis/service.py`(발행 지점) ·
  `token_budget.py:170`(유도값) · `scripts/deep_analysis_funnel_sample.py:118,181`(삭제 대상) ·
  `neos/config/model_routing.py`(`ModelResolution`) ·
  `neos/skills/manager/skill_registry.py:14`(`SkillInfo`) ·
  `web/lib/deep-analysis/progress.ts:100`(`activityLabel`)
- 실측 증거: `artifacts/deep-analysis-funnel/20260818T111321Z/manifest.json`
