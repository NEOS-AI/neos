# 구성 매니페스트 (트랙 H의 H1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 심층분석 런 하나의 유효 구성을 `run_manifest` 이벤트 하나로 못 박아, 표본 아티팩트만으로 그 런이 무엇으로 조립됐는지 복원할 수 있게 한다.

**Architecture:** 역할 테이블을 `model_roles.py` 한 곳으로 모아 9개 `resolve_model` 호출 지점을 이전한다. `manifest.py`의 순수 함수 `build_manifest()`가 **계산 없이** 인자를 받아 매니페스트 dict를 만들고, `service.build_orchestrator`가 Orchestrator에 넘긴 **바로 그 값**으로 그것을 불러 `ledger.log("run_manifest", ...)`로 발행한다. 표본 스크립트는 자체 지문 계산을 버리고 원장에서 읽는다.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (async) · pytest / pytest-randomly · TypeScript (Next.js, `web/`)

**Spec:** `docs/superpowers/specs/2026-08-22-deep-analysis-run-manifest-design.md`

## Global Constraints

- **매직넘버 금지.** 전부 `settings`. 프롬프트는 전부 파일 (설계 §11 / 로드맵 §2.3)
- **append-only 원장.** `deep_analysis_events`에 UPDATE/DELETE 금지 (D8)
- **P2 단일 작성자.** 원장 쓰기는 오케스트레이터·`build_orchestrator` 계열만
- **마이그레이션 금지.** `DAEvent.kind`는 `String(40)`, `"run_manifest"`는 12자
- **모델 선택을 바꾸지 않는다.** E3는 관측만 한다. 바꾸면 이전 표본과 비교 불가
- **`Orchestrator.run()`에 게이트를 걸지 않는다.** 거부는 표본 경계에서만
- **커밋 메시지에 `Co-Authored-By` 트레일러 금지** (사용자 지침)
- **한 번에 하나씩 도구 실행** (CLAUDE.md)
- 작업 브랜치: `dev` (worktree 없이 직접)
- 검증 명령: `python -m pytest tests/workflow/deep_analysis -q` · `python -m ruff check .` · `cd web && pnpm test:source`

## 스펙에서 이 플랜이 정제한 것 하나

스펙 §3.6은 아티팩트의 `config_fingerprint`를 `{run_id: manifest}` 맵으로 바꾼다고
적었다. 그대로 하면 **`git` 항의 자리가 사라진다** — 지금 `git`은
`config_fingerprint` 안에 있고 `scripts/deep_analysis_diagnostician.py:107`의
`_scrub_config()`가 거기서 `git.commit`을 떼어낸다. 스펙 §3.3은 `git`을 아티팩트
층에 남긴다고 했으므로, 이 플랜은 한 겹을 더 둔다:

```json
"config_fingerprint": {
  "manifest_version": 1,
  "git": { "commit": "…", "branch": "…", "dirty": false, "dirty_paths": [] },
  "runs": { "<run_id>": { …매니페스트… } }
}
```

`_scrub_config()`가 계속 `git`을 찾고, `config_fingerprint is not None`을 단언하는
기존 테스트 둘이 계속 통과하며, 런별 구성은 `runs` 아래로 들어간다.

---

### Task 1: 역할 테이블 — `model_roles.py`

하네스 안에서 `resolve_model`을 부르는 유일한 지점을 만든다. 아직 호출 지점은
옮기지 않는다 — 이 태스크는 **이전 전의 역할을 회귀 고정**하는 것이 목적이다.

**Files:**
- Create: `neos/workflow/deep_analysis/model_roles.py`
- Test: `tests/workflow/deep_analysis/test_model_roles.py`

**Interfaces:**
- Consumes: `neos.config.model_routing.resolve_model`, `ModelResolution`
- Produces:
  - `HARNESS_ROLES: dict[str, str]` — `{"scout","dig","synth","judge"} -> {"everyday","powerful"}`
  - `resolve_harness_model(name: str) -> ModelResolution`
  - `resolve_all() -> dict[str, ModelResolution]` — 네 이름 전부

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_model_roles.py`:

```python
import pytest

from neos.workflow.deep_analysis.model_roles import (
    HARNESS_ROLES,
    resolve_all,
    resolve_harness_model,
)


def test_role_table_matches_pre_migration_call_sites():
    """이전 전 9개 호출 지점의 역할을 회귀 고정한다.

    worker.py:316 (scout=everyday / dig=powerful) ·
    synthesizer.py:272,328,496,627 (synth=powerful) ·
    orchestrator.py:706,730 (dig=powerful) · orchestrator.py:903 (judge=everyday) ·
    service.py:61 (judge=everyday).

    이 단언이 없으면 Task 2 의 이전이 역할을 조용히 바꿔도 아무것도 실패하지
    않는다 -- 그리고 그 거짓말은 재생성 불가능한 아티팩트에 실린다.
    """
    assert HARNESS_ROLES == {
        "scout": "everyday",
        "dig": "powerful",
        "synth": "powerful",
        "judge": "everyday",
    }


def test_resolve_harness_model_returns_resolution_with_role():
    resolution = resolve_harness_model("dig")

    assert resolution.role == "powerful"
    assert resolution.provider == "anthropic"
    assert isinstance(resolution.model, str) and resolution.model


def test_resolve_harness_model_rejects_unknown_name():
    with pytest.raises(KeyError):
        resolve_harness_model("scribe")


def test_resolve_all_covers_every_role():
    resolved = resolve_all()

    assert set(resolved) == set(HARNESS_ROLES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_model_roles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.model_roles'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/deep_analysis/model_roles.py`:

```python
"""하네스의 모델 역할 배정 -- `resolve_model` 을 부르는 유일한 지점.

이 파일이 생기기 전에는 역할 리터럴(`"everyday"`/`"powerful"`)이 9개 호출
지점에 하드코딩돼 있었고, 표본 스크립트의 `_resolved_models()` 가 열 번째
사본이었다. 그 함수의 docstring 이 위험을 직접 적어놨다 -- "A role guessed
here would put a lie in the one artifact that cannot be regenerated."

매니페스트(H1)가 "실제로 돈 모델"을 적으려면 사본이 하나여야 한다.
"""

from __future__ import annotations

from neos.config.model_routing import ModelResolution, resolve_model
from neos.config.settings import settings

# 프로바이더는 `"anthropic"` 고정이다 -- 이전 전 9개 호출 지점 전부가 그랬다.
# 이것을 설정으로 여는 것은 로드맵 §4.2 라우팅 불변식에 닿으므로 H1 범위 밖이다.
_PROVIDER = "anthropic"

HARNESS_ROLES: dict[str, str] = {
    "scout": "everyday",
    "dig": "powerful",
    "synth": "powerful",
    "judge": "everyday",
}


def resolve_harness_model(name: str) -> ModelResolution:
    """`name` 역할이 실제로 해석되는 모델.

    `feature_override` 는 테이블이 아니라 설정에서 읽는다 -- `None` = 역할
    기본값이라는 라우팅 계약의 소비 지점이 거기이고(로드맵 §6 ②),
    이 설계는 그것을 바꾸지 않는다.
    """
    role = HARNESS_ROLES[name]
    override = getattr(settings.config.deep_analysis.models, name)
    return resolve_model(
        config=settings.config.model_routing,
        provider=_PROVIDER,
        role=role,
        feature_override=override,
    )


def resolve_all() -> dict[str, ModelResolution]:
    return {name: resolve_harness_model(name) for name in HARNESS_ROLES}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_model_roles.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/model_roles.py tests/workflow/deep_analysis/test_model_roles.py
git commit -m "feat(deep-analysis): 하네스 모델 역할 테이블을 한 곳으로 모은다

H1 매니페스트가 '실제로 돈 모델'을 적으려면 역할 사본이 하나여야 한다.
지금은 9개 호출 지점 + 표본 스크립트에 10개 사본이 있다. 이 커밋은
테이블만 만들고 이전 전 역할을 회귀 고정한다 -- 호출 지점 이전은 다음
커밋이고, 이 단언이 그 이전이 역할을 조용히 바꾸는 것을 막는다."
```

---

### Task 2: 9개 호출 지점 이전 + 직접 호출 금지

**Files:**
- Modify: `neos/workflow/deep_analysis/worker.py:316-324`
- Modify: `neos/workflow/deep_analysis/synthesizer.py:272-277`, `:328-333`, `:496-501`, `:627-632`
- Modify: `neos/workflow/deep_analysis/orchestrator.py:706-711`, `:730-735`, `:903-908`
- Modify: `neos/workflow/deep_analysis/service.py:61-66`
- Test: `tests/workflow/deep_analysis/test_model_roles.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `resolve_harness_model`
- Produces: 없음 (내부 이전). 이후 태스크는 하네스에 `resolve_model` 직접 호출이 0건임을 전제한다

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_model_roles.py`에 추가:

```python
from pathlib import Path

_HARNESS_DIR = (
    Path(__file__).resolve().parents[3]
    / "neos" / "workflow" / "deep_analysis"
)


def test_no_direct_resolve_model_call_in_harness():
    """`model_roles.py` 밖에서 `resolve_model` 을 직접 부르지 않는다.

    사본이 다시 생기는 것을 기계가 막는다. 이 테스트가 없으면 다음 사람이
    호출 지점 하나를 추가하면서 역할을 손으로 적고, 매니페스트는 그것을
    모른 채 다른 값을 적는다.
    """
    offenders = []
    for path in sorted(_HARNESS_DIR.rglob("*.py")):
        if path.name == "model_roles.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "resolve_model(" in source:
            offenders.append(str(path.relative_to(_HARNESS_DIR)))

    assert offenders == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_model_roles.py::test_no_direct_resolve_model_call_in_harness -q`
Expected: FAIL — offenders에 `worker.py`, `synthesizer.py`, `orchestrator.py`, `service.py` 넷이 들어 있다

- [ ] **Step 3: Write minimal implementation**

네 파일에서 `from neos.config.model_routing import resolve_model` import를 지우고
`from .model_roles import resolve_harness_model`을 넣는다. 그리고 9개 호출을 바꾼다.

`worker.py` — 유일하게 역할이 동적인 곳이다. 이전 전:

```python
        config = settings.config.deep_analysis
        role = "everyday" if effort == Effort.SCOUT else "powerful"
        feature_override = (
            config.models.scout if effort == Effort.SCOUT else config.models.dig
        )
        self._model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role=role,
            feature_override=feature_override,
        ).model
```

이전 후:

```python
        config = settings.config.deep_analysis
        self._model = resolve_harness_model(
            "scout" if effort == Effort.SCOUT else "dig"
        ).model
```

`synthesizer.py` 네 곳 — 전부 같은 모양이다. 이전 전:

```python
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
```

(`:496`과 `:627`은 `feature_override=settings.config.deep_analysis.models.synth`로
적혀 있으나 같은 값이다.) 네 곳 전부 이전 후:

```python
        synth_model = resolve_harness_model("synth").model
```

`orchestrator.py:706`·`:730` 이전 후:

```python
        dig_model = resolve_harness_model("dig").model
```

`orchestrator.py:903` 이전 후 (`try:` 블록 안이라 들여쓰기가 한 단 깊다):

```python
            judge_model = resolve_harness_model("judge").model
```

`service.py:61` 이전 후:

```python
    judge_model = resolve_harness_model("judge").model
```

⚠️ `config = settings.config.deep_analysis` 지역변수는 **지우지 말 것** — 네 파일
모두 그 아래에서 다른 설정 값에 계속 쓴다. `worker.py`는 `config.effort[...]`,
`synthesizer.py:328` 근처는 다른 용도, `orchestrator.py:898`은
`config.subq_reviewer_enabled`. 안 쓰게 된 곳만 ruff가 잡는다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_model_roles.py -q && python -m pytest tests/workflow/deep_analysis -q && python -m ruff check neos/workflow/deep_analysis`
Expected: 전부 PASS. 기존 스위트에 회귀 0건 — 해석 결과가 동일하므로 어떤 테스트도 값이 바뀌지 않는다

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis tests/workflow/deep_analysis/test_model_roles.py
git commit -m "refactor(deep-analysis): resolve_model 호출 9곳을 역할 테이블로 이전

worker 1 · synthesizer 4 · orchestrator 3 · service 1. 해석 결과는
동일하므로 동작 변화가 없다. 사본 재발은 테스트가 막는다 --
model_roles.py 밖에서 resolve_model 을 부르면 실패한다."
```

---

### Task 3: `manifest.py` — 순수 함수 `build_manifest`

**Files:**
- Create: `neos/workflow/deep_analysis/manifest.py`
- Test: `tests/workflow/deep_analysis/test_manifest.py`

**Interfaces:**
- Consumes: Task 1의 `HARNESS_ROLES`; `neos.config.model_routing.ModelResolution`
- Produces:
  - `MANIFEST_KIND: str = "run_manifest"`
  - `MANIFEST_VERSION: int = 1`
  - `RUN_PROMPTS: tuple[str, ...]` — 런 경로가 쓰는 8개
  - `prompt_hashes() -> dict[str, str]`
  - `component_id(obj: object | None) -> str | None`
  - `build_manifest(*, profile, models, budget, prompts, skills, components, config) -> dict`
    - `models: dict[str, ModelResolution]`
    - `budget: dict[str, int | float]`
    - `prompts: dict[str, str]`
    - `skills: list[dict[str, str]] | None`
    - `components: dict[str, str | bool | None]`
    - `config: dict[str, object]`

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_manifest.py`:

```python
import inspect

from neos.config.model_routing import ModelResolution, ResolutionSource
from neos.workflow.deep_analysis.manifest import (
    MANIFEST_KIND,
    MANIFEST_VERSION,
    RUN_PROMPTS,
    build_manifest,
    component_id,
    prompt_hashes,
)


def _resolution(model: str, role: str) -> ModelResolution:
    return ModelResolution(
        model=model,
        provider="anthropic",
        role=role,
        source=ResolutionSource.ROLE_DEFAULT,
    )


_MODELS = {
    "scout": _resolution("claude-sonnet-5", "everyday"),
    "dig": _resolution("claude-opus-5", "powerful"),
    "synth": _resolution("claude-opus-5", "powerful"),
    "judge": _resolution("claude-sonnet-5", "everyday"),
}
_BUDGET = {
    "global_token_cap": 140000,
    "synthesis_max_tokens": 2000,
    "finalization_floor_tokens": 53600,
    "report_floor_tokens": 43200,
    "grading_floor_tokens": 21600,
    "min_viable_output_tokens": 2048,
    "available_for_investigation": 86400,
    "report_floor_funded_attempts": 1.2,
}


def _build(**overrides):
    kwargs = {
        "profile": "dev",
        "models": _MODELS,
        "budget": _BUDGET,
        "prompts": {"decompose": "sha256:abc"},
        "skills": [{"name": "web-search", "version": "1.0.0"}],
        "components": {"grader": "graders.deterministic:DeterministicGrader"},
        "config": {"max_depth": 2},
    }
    kwargs.update(overrides)
    return build_manifest(**kwargs)


def test_build_manifest_does_not_read_settings():
    """계산 능력이 없어야 매니페스트가 실제와 어긋날 수 없다.

    기존 지문(`scripts/deep_analysis_funnel_sample.py:181`)이 dev 런에
    기본 프로파일 캡 300000 을 적은 것은 버그가 아니라 재계산이다.
    같은 값을 두 곳에서 유도하면 두 곳이 갈라진다.
    """
    source = inspect.getsource(build_manifest)

    assert "settings" not in source
    assert "floor_tokens(" not in source


def test_build_manifest_is_pure():
    assert _build() == _build()


def test_build_manifest_records_version_and_profile():
    manifest = _build()

    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["profile"] == "dev"


def test_build_manifest_writes_resolution_not_config():
    manifest = _build()

    assert manifest["models"]["dig"] == {
        "role": "powerful",
        "model": "claude-opus-5",
        "source": "role_default",
    }


def test_build_manifest_confesses_judge_equals_scout():
    """E3 를 매니페스트가 자백한다.

    judge 와 scout 이 둘 다 `None` 이라 같은 역할로 해석되는 것이 E3
    (로드맵 §6 ①)이고 지금도 깨져 있다. 관측이지 강제가 아니다 --
    모델을 바꾸면 이전 표본과 비교 불가해진다.
    """
    assert _build()["models"]["judge_equals_scout"] is True


def test_build_manifest_reports_distinct_judge_and_scout():
    models = dict(_MODELS)
    models["judge"] = _resolution("claude-opus-5", "powerful")

    assert _build(models=models)["models"]["judge_equals_scout"] is False


def test_build_manifest_carries_budget_values_unchanged():
    assert _build()["budget"] == _BUDGET


def test_skills_none_is_not_empty_list():
    """0 과 '계측 없음' 을 구별한다 (F1-m1 의 교훈).

    레지스트리가 없는 것과 레지스트리에 스킬이 0개인 것은 다른 사실이다.
    """
    assert _build(skills=None)["skills"] is None
    assert _build(skills=[])["skills"] == []


def test_run_prompts_excludes_the_diagnostician_prompt():
    """`diagnose_bottleneck` 은 런의 구성이 아니다.

    F1 진단자(표본을 *읽는* 쪽) 전용이고
    `scripts/deep_analysis_diagnostician.py:33` 만 로드한다. 넣으면 그
    파일을 고칠 때마다 실제로 동일한 두 런이 서로 달라 보인다.
    """
    assert "diagnose_bottleneck" not in RUN_PROMPTS
    assert set(RUN_PROMPTS) == {
        "decompose",
        "worker_brief",
        "subq_review",
        "final_compose",
        "node_summary",
        "claim_entailment",
        "judge",
        "report_judge",
    }


def test_prompt_hashes_covers_every_run_prompt():
    hashes = prompt_hashes()

    assert set(hashes) == set(RUN_PROMPTS)
    assert all(value.startswith("sha256:") for value in hashes.values())


def test_component_id_strips_the_harness_package_prefix():
    from neos.workflow.deep_analysis.graders.deterministic import (
        DeterministicGrader,
    )

    # `quote_threshold`/`confidence_cap` 은 필수 키워드다
    # (`graders/deterministic.py:10-16`). `component_id` 는 인스턴스의
    # 타입만 보므로 값은 무엇이든 무방하다.
    grader = DeterministicGrader(
        None, quote_threshold=0.9, confidence_cap={}
    )

    assert component_id(grader) == "graders.deterministic:DeterministicGrader"
    assert component_id(None) is None


def test_manifest_kind_fits_the_event_column():
    """`DAEvent.kind` 는 String(40) 이다 -- 마이그레이션 없이 들어가야 한다."""
    assert len(MANIFEST_KIND) <= 40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.manifest'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/deep_analysis/manifest.py`:

```python
"""런의 유효 구성을 이벤트 하나로 못 박는다 (트랙 H의 H1).

`build_manifest` 는 **계산하지 않는다.** `settings` 를 import 하지 않고,
floor 를 유도하지 않고, 프로파일로 분기하지 않는다. 호출자가 이미 가진 값을
받아 적기만 한다.

그 규율이 이 모듈의 전부다. 기존 지문(`scripts/deep_analysis_funnel_sample.py`)
은 같은 값을 다시 계산했고, 그래서 표본 #20 의 아티팩트가 6런 중 5런에
대해 틀린 캡(300000)을 적었다. 불변식을 검사하는 대신 **어긋난 상태를
표현할 수 없게** 만든다.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from neos.config.model_routing import ModelResolution

MANIFEST_KIND = "run_manifest"
MANIFEST_VERSION = 1

# 런 경로가 쓰는 프롬프트만. `prompts/` 에는 9개가 있으나
# `diagnose_bottleneck` 은 F1 진단자 전용이라 런의 구성이 아니다 --
# 넣으면 그 파일을 고칠 때마다 동일한 두 런이 달라 보인다.
RUN_PROMPTS: tuple[str, ...] = (
    "claim_entailment",   # worker.py
    "decompose",          # orchestrator.py
    "final_compose",      # synthesizer.py
    "judge",              # graders/agentic.py
    "node_summary",       # synthesizer.py
    "report_judge",       # graders/report.py
    "subq_review",        # orchestrator.py
    "worker_brief",       # orchestrator.py
)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_PACKAGE_PREFIX = "neos.workflow.deep_analysis."


@lru_cache(maxsize=1)
def prompt_hashes() -> dict[str, str]:
    """런 경로 프롬프트 8개의 내용 해시.

    캐시하는 이유는 `load_prompt` 와 같다 -- 파일은 프로세스 수명 동안
    바뀌지 않는다.
    """
    digests = {}
    for name in RUN_PROMPTS:
        raw = (_PROMPT_DIR / f"{name}.md").read_bytes()
        digests[name] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return digests


def component_id(obj: object | None) -> str | None:
    """이 런이 조립한 부품의 식별자.

    설계 §15.3 은 매니페스트 항목으로 "그래프 토폴로지 해시" 를 적었으나
    심층분석 런은 LangGraph 그래프를 타지 않는다. 이 하네스에서 "무엇이
    조립됐나" 에 해당하는 것은 부품 배선이다.

    소스 해시는 넣지 않는다 -- 클래스 이름이 같고 내용이 바뀐 경우는
    아티팩트의 `git` 항(commit + dirty)이 답한다.
    """
    if obj is None:
        return None
    cls = type(obj)
    module = cls.__module__
    if module.startswith(_PACKAGE_PREFIX):
        module = module[len(_PACKAGE_PREFIX):]
    return f"{module}:{cls.__qualname__}"


def build_manifest(
    *,
    profile: str,
    models: dict[str, ModelResolution],
    budget: dict[str, int | float],
    prompts: dict[str, str],
    skills: list[dict[str, str]] | None,
    components: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """호출자가 이미 가진 값을 매니페스트 모양으로 정렬한다. 계산 없음."""
    resolved = {
        name: {
            "role": resolution.role,
            "model": resolution.model,
            "source": resolution.source.value,
        }
        for name, resolution in sorted(models.items())
    }
    # E3 를 자백한다. 관측이지 강제가 아니다 -- 해소는 로드맵 §8 W4 다.
    judge = models.get("judge")
    scout = models.get("scout")
    resolved["judge_equals_scout"] = (
        judge is not None and scout is not None and judge.model == scout.model
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "profile": profile,
        "models": resolved,
        "budget": dict(budget),
        "prompts": dict(prompts),
        "skills": None if skills is None else list(skills),
        "components": dict(components),
        "config": dict(config),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest.py -q`
Expected: PASS (13 passed)

`component_id` 테스트가 `DeterministicGrader(ledger=None)`로 실패하면 그 클래스의
실제 생성자 시그니처(`graders/deterministic.py`)를 확인해 인자를 맞춘다 —
`component_id`는 인스턴스의 타입만 보므로 어떤 인자든 무방하다.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/manifest.py tests/workflow/deep_analysis/test_manifest.py
git commit -m "feat(deep-analysis): run_manifest 빌더 -- 계산하지 않는 순수 함수

build_manifest 가 settings 를 import 하지 않는다는 것을 테스트가 소스에서
직접 단언한다. 기존 지문이 dev 런에 기본 프로파일 캡을 적은 것은 버그가
아니라 재계산이었고, 계산 능력을 없애면 그 상태를 표현할 수 없다.

프롬프트는 런 경로 8개만. diagnose_bottleneck 은 F1 진단자 전용이라
넣으면 동일한 두 런이 달라 보인다."
```

---

### Task 4: 발행 — `service.build_orchestrator`

**Files:**
- Modify: `neos/workflow/deep_analysis/service.py:46-156`
- Test: `tests/workflow/deep_analysis/test_service_manifest.py`

**Interfaces:**
- Consumes: Task 1 `resolve_all`, Task 3 `MANIFEST_KIND`·`build_manifest`·`component_id`·`prompt_hashes`
- Produces: 런 시작 시 `deep_analysis_events`에 `kind="run_manifest"` 이벤트 1건. 이후 태스크(6·7·8)가 그것을 읽는다

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_service_manifest.py`:

```python
import json

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.manifest import MANIFEST_KIND
from neos.workflow.deep_analysis.service import build_orchestrator


class _FakeLedger:
    def __init__(self):
        self.events = []

    async def log(self, kind, qid, payload):
        # 직렬화 가능성까지 확인한다 -- 실제 `Ledger.log` 는
        # `json.dumps(payload, ensure_ascii=False)` 를 통과시킨다.
        json.dumps(payload, ensure_ascii=False)
        self.events.append((kind, qid, payload))


@pytest.fixture
def fake_ledger(monkeypatch):
    ledger = _FakeLedger()
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.service.Ledger",
        lambda session, run_id: ledger,
    )
    return ledger


def _manifest(ledger):
    kinds = [kind for kind, _, _ in ledger.events]
    assert kinds.count(MANIFEST_KIND) == 1
    return next(p for k, _, p in ledger.events if k == MANIFEST_KIND)


@pytest.mark.asyncio
async def test_build_orchestrator_emits_one_manifest(fake_ledger):
    await build_orchestrator(object(), "run0001", profile="dev")

    assert _manifest(fake_ledger)["manifest_version"] == 1


@pytest.mark.asyncio
async def test_manifest_budget_matches_what_the_orchestrator_received(
    fake_ledger,
):
    """§2.1 의 재계산 사고를 기계가 막는다.

    매니페스트의 예산 값과 Orchestrator 가 실제로 받은 값이 같은 표현에서
    나왔는지 확인한다. 갈라지면 매니페스트가 조용히 거짓말한다.
    """
    orchestrator = await build_orchestrator(object(), "run0002", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert budget["global_token_cap"] == orchestrator.global_token_cap
    assert (
        budget["finalization_floor_tokens"]
        == orchestrator.finalization_floor_tokens
    )
    assert budget["report_floor_tokens"] == orchestrator.report_floor_tokens
    assert budget["grading_floor_tokens"] == orchestrator.grading_floor_tokens
    assert (
        budget["min_viable_output_tokens"]
        == orchestrator.min_viable_output_tokens
    )


@pytest.mark.asyncio
async def test_dev_profile_manifest_records_the_dev_cap(fake_ledger):
    """기존 아티팩트가 틀린 바로 그 칸.

    표본 #20 의 manifest.json 은 dev 런 5건에 대해 global_token_cap 300000
    (기본 프로파일)을 적었다. dev 는 dev_profile.global_token_cap 으로 돈다.
    """
    await build_orchestrator(object(), "run0003", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert (
        budget["global_token_cap"]
        == settings.config.deep_analysis.dev_profile.global_token_cap
    )
    assert (
        budget["global_token_cap"]
        != settings.config.deep_analysis.global_token_cap
    )


@pytest.mark.asyncio
async def test_available_for_investigation_is_cap_minus_floor(fake_ledger):
    """D75 -> D77 -> D78 이 세 번 다시 한 뺄셈."""
    await build_orchestrator(object(), "run0004", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert budget["available_for_investigation"] == (
        budget["global_token_cap"] - budget["finalization_floor_tokens"]
    )


@pytest.mark.asyncio
async def test_manifest_records_wired_components(fake_ledger):
    await build_orchestrator(object(), "run0005", profile="dev")
    components = _manifest(fake_ledger)["components"]

    assert components["grader"] == (
        "graders.deterministic:DeterministicGrader"
    )
    assert components["report_grader"] == "graders.report:ReportGrader"
    assert components["cassette"] is False


@pytest.mark.asyncio
async def test_manifest_skills_is_none_without_a_registry(fake_ledger):
    await build_orchestrator(object(), "run0006", profile="dev")

    assert _manifest(fake_ledger)["skills"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_service_manifest.py -q`
Expected: FAIL — `StopIteration` / `AssertionError`: `run_manifest` 이벤트가 발행되지 않는다

- [ ] **Step 3: Write minimal implementation**

`service.py` 상단 import에 추가:

```python
from .manifest import MANIFEST_KIND, build_manifest, component_id, prompt_hashes
from .model_roles import resolve_all
```

`return Orchestrator(...)` **직전**에 삽입:

```python
    # 매니페스트는 여기서 낸다. `build_orchestrator` 는 프로파일과 유도값을
    # 아는 유일한 곳이고, Orchestrator 는 floor 를 주입받을 뿐 프로파일을
    # 모른다(위 주석 참조 -- 골든 테스트가 캡 1000 으로 그것을 짓는다).
    # Orchestrator 안에서 내면 §2.1 이 막으려는 재계산이 되살아난다.
    manifest = build_manifest(
        profile=profile,
        models=resolve_all(),
        budget={
            "global_token_cap": global_token_cap,
            "synthesis_max_tokens": synthesis_max_tokens,
            "finalization_floor_tokens": finalization_floor_tokens,
            "report_floor_tokens": report_floor_tokens,
            "grading_floor_tokens": grading_floor_tokens,
            "min_viable_output_tokens": config.min_viable_output_tokens,
            # 파생값이지만 일부러 싣는다 -- D75 -> D77 -> D78 이 세 번
            # 틀린 것이 정확히 이 뺄셈이다.
            "available_for_investigation": max(
                0, global_token_cap - finalization_floor_tokens
            ),
            "report_floor_funded_attempts": config.report_floor_funded_attempts,
        },
        prompts=prompt_hashes(),
        skills=(
            None
            if skill_registry is None
            else sorted(
                (
                    {"name": info.name, "version": info.version}
                    for info in skill_registry.list_skills()
                ),
                key=lambda item: item["name"],
            )
        ),
        components={
            "grader": component_id(grader),
            "agentic_grader": component_id(agentic_grader),
            "report_grader": component_id(report_grader),
            "synthesizer": None,
            "citation_renderer": None,
            "search_fn": getattr(search_fn, "__qualname__", None),
            "fetch_fn": getattr(fetch_fn, "__qualname__", None),
            "cassette": cassette is not None,
        },
        config={
            "max_depth": max_depth,
            "parallel_workers": parallel_workers,
            "quote_match_threshold": config.quote_match_threshold,
            "confidence_cap": config.confidence_cap,
            "agentic_threshold": config.agentic_threshold,
            "agentic_sample_rate": config.agentic_sample_rate,
            "claim_retry_cap": config.claim_retry_cap,
            "decompose_max_tokens": config.decompose_max_tokens,
            "judge_max_output_tokens": config.judge_max_output_tokens,
            "entailment_max_output_tokens": config.entailment_max_output_tokens,
            "subquestions": {
                "adopt_threshold": config.subq_adopt_threshold,
                "adopt_cap": config.subq_adopt_cap,
                "budget_policy": config.subq_budget_policy,
                "reviewer_enabled": config.subq_reviewer_enabled,
            },
            "effort": {
                name: {
                    "token_cap": effort.token_cap,
                    "wall_clock_cap": effort.wall_clock_cap,
                }
                for name, effort in config.effort.items()
            },
        },
    )
    await ledger.log(MANIFEST_KIND, None, manifest)
```

`synthesizer`와 `citation_renderer`가 `None`인 이유: `build_orchestrator`는 그 둘을
만들지 않고 Orchestrator 생성자가 기본값으로 짓는다(`orchestrator.py:355-363`).
`None`은 "기본 부품이 쓰였다"는 뜻이며, H3에서 주입 경로가 생기면 그때 채운다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_service_manifest.py -q && python -m pytest tests/workflow/deep_analysis -q`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_service_manifest.py
git commit -m "feat(deep-analysis): build_orchestrator 가 run_manifest 를 발행한다

프로덕션 job(jobs.py:132)과 표본 스크립트 양쪽의 유일한 관문이고,
프로파일과 유도값을 아는 유일한 곳이다. Orchestrator 에 넘긴 바로 그
값으로 매니페스트를 만들므로 둘이 어긋날 수 없다 -- 테스트가 네 칸
전부를 대조한다.

dev 런의 캡이 dev_profile 값이라는 것을 단언한다. 기존 아티팩트가
6런 중 5런에 대해 틀리게 적어온 그 칸이다."
```

---

### Task 5: FE 라벨

§15.3의 명시적 경고를 갚는다 — "새 kind이므로 FE 라벨을 같은 변경에 넣는다.
FE1이 이벤트 8종에서 정확히 이것을 빠뜨려 §5.2를 치렀다."

**Files:**
- Modify: `web/lib/deep-analysis/progress.ts:142-145`
- Test: `web/tests/source/deep-analysis-progress.test.ts` (기존 파일 끝에 추가)

**Interfaces:**
- Consumes: Task 4가 발행하는 `kind: "run_manifest"`
- Produces: 없음

- [ ] **Step 1: Write the failing test**

⚠️ 이 파일은 vitest/jest가 아니라 **`node:test` + `node:assert/strict`**를 쓴다.
기존 헬퍼 `event(seq, kind, payload)`와 `applyAll(events)`가 파일 상단(9-17행)에
이미 있으므로 그대로 쓴다. 파일 끝에 추가:

```typescript
test("run_manifest에 라벨이 붙는다 (FE1 재발 방지)", () => {
  const state = applyAll([
    event(1, "job_started"),
    event(2, "run_manifest", { profile: "dev" }),
  ]);
  assert.equal(state.lastActivity, "구성 확정 · dev 프로파일");
  assert.equal(state.cursor, 2);
});

test("프로파일이 없어도 run_manifest 라벨은 null이 아니다", () => {
  const state = applyAll([event(1, "run_manifest", {})]);
  assert.equal(state.lastActivity, "구성 확정");
});

test("run_manifest는 강등이 아니다", () => {
  const state = applyAll([event(1, "run_manifest", { profile: "dev" })]);
  assert.deepEqual(state.degradations, []);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && pnpm test:source`
Expected: 첫 테스트 FAIL — `lastActivity`가 `null`이다 (`activityLabel`이 `null` 반환)

- [ ] **Step 3: Write minimal implementation**

`web/lib/deep-analysis/progress.ts`의 `activityLabel()` 안, `"recovered"` 분기 뒤에:

```typescript
  if (kind === "run_manifest") {
    const profile = asString(payload.profile);
    return profile ? `구성 확정 · ${profile} 프로파일` : "구성 확정";
  }
```

`degradationKind()`는 **건드리지 않는다** — 강등이 아니다.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && pnpm test:source && pnpm exec tsc --noEmit`
Expected: 전부 PASS, tsc clean

- [ ] **Step 5: Commit**

```bash
git add web/lib/deep-analysis
git commit -m "feat(web): run_manifest 활동 라벨

로드맵 §15.3 이 H1 에 대해 명시적으로 건 조건이다 -- 새 kind 는 FE 라벨을
같은 변경에 넣는다. FE1 이 이벤트 8종에서 이것을 빠뜨려 §5.2 를 치렀다.
강등이 아니므로 degradationKind() 에는 넣지 않는다."
```

---

### Task 6: 아티팩트 층 전환

표본 스크립트가 자체 지문 계산을 버리고 원장에서 읽는다.

**Files:**
- Modify: `scripts/deep_analysis_funnel_sample.py` — `_resolved_models()`(105-137)·`_fingerprint()`(181-227) 삭제, `_main()`(271-341) 재배치
- Create: `neos/workflow/deep_analysis/manifest_reader.py`
- Test: `tests/workflow/deep_analysis/test_manifest_reader.py`
- Modify: `tests/workflow/deep_analysis/test_funnel_sample_runner.py:200-216`, `:400-414`

**Interfaces:**
- Consumes: Task 3 `MANIFEST_KIND`
- Produces:
  - `async def manifests_for(session, run_ids: Sequence[str]) -> dict[str, dict]`
    — run_id → 그 런의 **마지막** 매니페스트. 없는 run은 키가 없다
  - `async def runs_without_manifest(session, run_ids) -> list[str]`

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_manifest_reader.py`.

⚠️ 이 저장소에는 `db_session` 픽스처가 **없다.** `test_ledger_degradations.py`의
관례를 그대로 따른다 — 실제 DB에 쓰고 **각 테스트 끝에서 명시적으로 롤백**한다.
남는 쓰기가 있으면 안 된다.

```python
"""매니페스트 판독 -- 재개하면 둘이 되고, 마지막 것이 유효 구성이다."""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.manifest import MANIFEST_KIND
from neos.workflow.deep_analysis.manifest_reader import (
    manifests_for,
    runs_without_manifest,
)


@pytest.mark.asyncio
async def test_manifests_for_returns_the_payload():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "dev"}
        )

        found = await manifests_for(s, [run_id])

        assert found[run_id]["profile"] == "dev"
        await s.rollback()


@pytest.mark.asyncio
async def test_resume_keeps_both_manifests_and_the_reader_takes_the_last():
    """append-only (D8). 재개는 두 번째 매니페스트를 append 한다.

    지우지도 UPDATE 하지도 않는다. 크래시와 재개 사이에 설정이 바뀌면
    원장이 그것을 말한다 -- 지금은 어디에도 안 남는다.
    """
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "dev"}
        )
        await ledger.log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "default"}
        )

        found = await manifests_for(s, [run_id])

        assert found[run_id]["profile"] == "default"
        await s.rollback()


@pytest.mark.asyncio
async def test_runs_without_manifest_names_the_gap():
    async with await db_manager.get_session() as s:
        with_manifest = await create_run(s, "질문 A", "dev")
        await Ledger(s, with_manifest).log(
            MANIFEST_KIND, None, {"manifest_version": 1}
        )
        without = await create_run(s, "질문 B", "dev")

        missing = await runs_without_manifest(s, [with_manifest, without])

        assert missing == [without]
        await s.rollback()


@pytest.mark.asyncio
async def test_empty_run_list_is_not_a_gap():
    async with await db_manager.get_session() as s:
        assert await runs_without_manifest(s, []) == []
        await s.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: ... manifest_reader`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/deep_analysis/manifest_reader.py`:

```python
"""원장에서 런 구성을 되읽는다.

판독 규칙(설계 §3.4): 재개하면 `run_manifest` 가 두 번째로 append 되므로,
런 전체의 "유효 구성" 을 물으면 **마지막** 매니페스트를 준다. 특정 이벤트
seq 시점의 구성이 필요해지면 그때 seq 인자를 받는 함수를 따로 만든다 --
지금 필요한 것은 표본 게이트와 아티팩트 층뿐이고 둘 다 런 단위다.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from neos.database.deep_analysis_models import DAEvent

from .manifest import MANIFEST_KIND


async def manifests_for(
    session, run_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not run_ids:
        return {}
    result = await session.execute(
        select(DAEvent.run_id, DAEvent.payload)
        .where(
            DAEvent.run_id.in_(list(run_ids)),
            DAEvent.kind == MANIFEST_KIND,
        )
        .order_by(DAEvent.seq)
    )
    found: dict[str, dict[str, Any]] = {}
    for run_id, payload in result.all():
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            # seq 오름차순이므로 마지막 것이 남는다.
            found[run_id] = parsed
    return found


async def runs_without_manifest(
    session, run_ids: Sequence[str]
) -> list[str]:
    found = await manifests_for(session, run_ids)
    return [run_id for run_id in run_ids if run_id not in found]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest_reader.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 표본 스크립트를 원장 읽기로 바꾼다**

`scripts/deep_analysis_funnel_sample.py`:

1. `_resolved_models()`(105-137)와 `_fingerprint()`(181-227) 삭제. 이제 안 쓰는
   import(`resolve_model`)도 지운다 — ruff가 잡는다.
2. `_git_identity()`는 **남긴다.**
3. 새 헬퍼:

```python
def _fingerprint(manifests: dict[str, dict]) -> dict:
    """이 표본의 런별 구성. 계산하지 않는다 -- 원장이 답한다.

    이전에는 이 함수가 설정을 다시 읽어 지문을 만들었고, 그래서 dev 런
    5건에 기본 프로파일 캡을 적었다(표본 #20). 이제 값의 출처는
    `build_orchestrator` 가 발행한 이벤트 하나뿐이다.

    `git` 이 `runs` 밖에 있는 이유: 저장소 상태는 런의 구성이 아니라
    표본의 구성이고, `deep_analysis_diagnostician.py` 의 `_scrub_config()`
    가 이 자리에서 `git.commit` 을 떼어낸다.
    """
    return {
        "manifest_version": MANIFEST_VERSION,
        "git": _git_identity(),
        "runs": manifests,
    }
```

4. `_main()`의 성공 경로(321-338)를 재배치한다 — `run_ids`를 `write_artifacts`
   **전에** 계산하고, 게이트(Task 7)가 들어갈 자리를 만든다:

```python
        run_ids = [
            item["run_id"]
            for item in result["dev_runs"]
            if item.get("run_id")
        ]
        default_run = result.get("default_run")
        if default_run and default_run.get("run_id"):
            run_ids.append(default_run["run_id"])

        async with get_session_ctx() as session:
            manifests = await manifests_for(session, run_ids)

        artifact_dir = write_artifacts(
            result,
            output_root,
            receipt=_receipt(
                started_at, finished_at, 0, verification=verification
            ),
            fingerprint=_fingerprint(manifests),
        )
        _finalize_cassette(cassette, artifact_dir)
        return artifact_dir, run_ids
```

5. 실패 경로(305-312)는 `fingerprint=_fingerprint({})`로 바꾼다. **런이 없을 수도
   있으므로 게이트를 걸지 않는다** — §10.1 증거 보존이 영수증을 지키는 것보다
   우선한다. 매니페스트가 없다는 사실은 `runs: {}`가 말한다.

6. `_main` 상단 import에 `from neos.workflow.deep_analysis.manifest import MANIFEST_VERSION`,
   `from neos.workflow.deep_analysis.manifest_reader import manifests_for` 추가.

- [ ] **Step 6: 기존 테스트 둘을 새 모양으로 고친다**

`tests/workflow/deep_analysis/test_funnel_sample_runner.py`:

- 200행 근처 `fingerprint={"global_token_cap": 20000, "quote_threshold": 0.85}`와
  207행 단언 → `write_artifacts`는 지문을 **그대로 싣기만** 하므로 이 테스트는
  지문의 모양을 모른다. 값만 새 모양으로 바꾼다:

```python
        fingerprint={
            "manifest_version": 1,
            "git": {"commit": "abc123"},
            "runs": {"run0001": {"budget": {"global_token_cap": 20000}}},
        },
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())

    assert manifest["execution_receipt"]["pid"] == 4242
    assert manifest["execution_receipt"]["exit_status"] == 0
    assert (
        manifest["config_fingerprint"]["runs"]["run0001"]["budget"][
            "global_token_cap"
        ]
        == 20000
    )
```

- 410-414행(실패 경로 통합 테스트)의 `global_token_cap` 단언을 지우고, 지문이
  실리되 런이 없다는 것을 단언한다:

```python
    assert manifest["config_fingerprint"] is not None
    assert manifest["config_fingerprint"]["runs"] == {}
```

- [ ] **Step 7: 전체 회귀 확인**

Run: `python -m pytest tests/workflow/deep_analysis -q && python -m ruff check .`
Expected: 전부 PASS. `scripts/deep_analysis_discard_recall.py`의 자체 `_fingerprint()`는
**건드리지 않는다** — 다른 아티팩트 루트(`artifacts/deep-analysis-discard-recall/`)를
쓰는 별개 측정 경로다.

- [ ] **Step 8: Commit**

```bash
git add scripts/deep_analysis_funnel_sample.py neos/workflow/deep_analysis/manifest_reader.py tests/workflow/deep_analysis
git commit -m "feat(deep-analysis): 표본 아티팩트가 원장에서 구성을 읽는다

_fingerprint()/_resolved_models() 삭제. 값의 출처가 설정 재계산에서
build_orchestrator 가 발행한 이벤트로 바뀐다 -- 표본 #20 이 dev 런 5건에
기본 프로파일 캡을 적은 사고의 구조적 원인이 사라진다.

config_fingerprint 는 {manifest_version, git, runs} 로 바뀐다. git 을
runs 밖에 두는 것은 diagnostician 의 _scrub_config() 가 거기서
git.commit 을 떼어내기 때문이다.

실패 경로에는 게이트를 걸지 않는다 -- 런이 없을 수 있고, §10.1 증거
보존이 영수증을 지키는 것보다 우선한다."
```

---

### Task 7: 표본 경계 게이트 (§15.4 금지 3번)

**"매니페스트 없는 런은 표본이 아니다 — 지침이 아니라 기계가 거부한다."**

**Files:**
- Modify: `scripts/deep_analysis_funnel_sample.py` — `_main()` 성공 경로
- Test: `tests/workflow/deep_analysis/test_funnel_sample_gate.py`

**Interfaces:**
- Consumes: Task 6 `runs_without_manifest`, `manifests_for`
- Produces:
  - `class MissingManifestError(RuntimeError)`
  - `def divergent_manifest_fields(manifests: dict[str, dict]) -> list[str]`
    — 표본 안에서 갈린 항목의 이름들. **본문은 사용자가 쓴다**

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_funnel_sample_gate.py`:

```python
import pytest

from scripts.deep_analysis_funnel_sample import (
    MissingManifestError,
    divergent_manifest_fields,
)

_BASE = {
    "manifest_version": 1,
    "profile": "dev",
    "models": {"judge": {"model": "claude-sonnet-5"}},
    "prompts": {"final_compose": "sha256:aaa"},
    "budget": {"global_token_cap": 140000},
}


def _with(**overrides):
    merged = {**_BASE, **overrides}
    return merged


def test_identical_manifests_do_not_diverge():
    manifests = {"r1": _BASE, "r2": dict(_BASE)}

    assert divergent_manifest_fields(manifests) == []


def test_profile_and_budget_are_allowed_to_differ():
    """표본은 dev 5 + default 1 이다. 이 둘은 당연히 다르다."""
    manifests = {
        "r1": _BASE,
        "r2": _with(profile="default", budget={"global_token_cap": 300000}),
    }

    assert divergent_manifest_fields(manifests) == []


def test_divergent_models_are_reported():
    manifests = {
        "r1": _BASE,
        "r2": _with(models={"judge": {"model": "claude-opus-5"}}),
    }

    assert divergent_manifest_fields(manifests) == ["models"]


def test_divergent_prompts_are_reported():
    manifests = {
        "r1": _BASE,
        "r2": _with(prompts={"final_compose": "sha256:bbb"}),
    }

    assert divergent_manifest_fields(manifests) == ["prompts"]


def test_empty_sample_does_not_diverge():
    assert divergent_manifest_fields({}) == []


def test_missing_manifest_error_names_the_runs():
    error = MissingManifestError(["r7", "r9"])

    assert "r7" in str(error) and "r9" in str(error)
```

그리고 게이트가 **실제로 아티팩트를 막는지**를 단언한다. 이것이 §15.4 금지 3번의
"기계가 거부한다"이고, 예외 클래스가 있다는 것만으로는 증명되지 않는다:

```python
import inspect

import pytest

import scripts.deep_analysis_funnel_sample as sample


@pytest.mark.asyncio
async def test_gate_raises_before_reading_manifests(monkeypatch):
    """매니페스트 없는 런이 하나라도 있으면 거부한다.

    로드맵 §15.4 금지 3번은 지침이 아니라 기계다. 아티팩트가 써지고 나면
    §10.2 의 "정확히 1회" 규칙 때문에 다시 낼 기회가 없다.

    `manifests_for` 가 불리지 않았다는 것까지 단언한다 -- 게이트가 통과
    경로와 섞이면 "거부했는데 아티팩트는 써졌다" 가 가능해진다.
    """
    read = []

    async def _spy_manifests_for(*_args, **_kwargs):
        read.append("called")
        return {}

    monkeypatch.setattr(sample, "runs_without_manifest", _async_return(["r2"]))
    monkeypatch.setattr(sample, "manifests_for", _spy_manifests_for)

    with pytest.raises(MissingManifestError) as caught:
        await sample._gate_and_read_manifests(object(), ["r1", "r2"])

    assert caught.value.run_ids == ["r2"]
    assert read == []


def test_gate_is_called_before_write_artifacts_in_main():
    """소스 순서로 확인한다 -- 게이트가 아티팩트 쓰기보다 앞이어야 한다.

    함수 단위 테스트는 게이트가 *존재* 함만 보인다. 그것이 `_main()` 의
    성공 경로에서 `write_artifacts` 앞에 있는지는 별개 사실이고,
    순서가 뒤집히면 거부해도 아티팩트는 이미 써진다.
    """
    source = inspect.getsource(sample._main)
    gate = source.index("_gate_and_read_manifests")
    write = source.index("write_artifacts(\n            result")

    assert gate < write


@pytest.mark.asyncio
async def test_gate_returns_manifests_when_every_run_has_one(monkeypatch):
    monkeypatch.setattr(sample, "runs_without_manifest", _async_return([]))
    monkeypatch.setattr(
        sample, "manifests_for", _async_return({"r1": _BASE})
    )

    found = await sample._gate_and_read_manifests(object(), ["r1"])

    assert found == {"r1": _BASE}


def _async_return(value):
    async def _fn(*_args, **_kwargs):
        return value

    return _fn
```

⚠️ 이 테스트가 `_gate_and_read_manifests(session, run_ids)`를 부른다 — 게이트를
`_main()` 안에 인라인으로 두면 테스트할 수 없으므로 **함수로 뽑는다.** Step 3의
구현이 그 모양을 따른다.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_funnel_sample_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'MissingManifestError'`

- [ ] **Step 3: 스캐폴딩을 놓고 사용자에게 넘긴다**

`scripts/deep_analysis_funnel_sample.py`에 추가:

```python
class MissingManifestError(RuntimeError):
    """매니페스트 없는 런이 표본에 있다 (로드맵 §15.4 금지 3번).

    지침이 아니라 기계가 거부한다. 이 예외가 나면 아티팩트를 쓰지 않는다 --
    무엇으로 조립됐는지 모르는 런은 나중에 판독할 수 없고, 판독할 수 없는
    표본은 §10.2 의 "정확히 1회" 규칙 때문에 다시 낼 기회가 없다.
    """

    def __init__(self, run_ids: list[str]) -> None:
        super().__init__(
            "매니페스트 없는 런: " + ", ".join(run_ids) + " -- 표본이 아니다"
        )
        self.run_ids = run_ids


# 표본 안에서 달라도 되는 항목. dev 5 + default 1 이므로 프로파일과 그것에서
# 유도되는 예산은 당연히 다르다.
_PER_PROFILE_FIELDS = frozenset({"profile", "budget"})


def divergent_manifest_fields(manifests: dict[str, dict]) -> list[str]:
    """이 표본 안에서 런마다 갈린 매니페스트 항목의 이름.

    갈렸다는 것은 한 사전 등록 아래에서 구성이 바뀌었다는 뜻이고, 로드맵
    §15.2 ㉰ 가 경고한 귀속 불가 상황이다 -- 표본 #11 이 존재한 적 없는
    기전을 쟀고(D53), #18·#19 가 두 번 다 총 증거를 잃었다. 이 루프는
    구성이 흔들릴 때 자신이 무엇을 쟀는지 이미 세 번 틀렸다.

    `_PER_PROFILE_FIELDS` 는 제외한다 -- 표본은 dev 5 + default 1 이라
    그 둘은 설계상 다르다.

    Args:
        manifests: run_id -> 매니페스트. 비어 있을 수 있다.

    Returns:
        갈린 항목 이름을 정렬해서. 갈린 것이 없으면 빈 목록.
    """
    # TODO(사용자): 여기를 구현한다.
    raise NotImplementedError
```

게이트는 **함수로 뽑는다** — `_main()` 안에 인라인으로 두면 테스트할 수 없다:

```python
async def _gate_and_read_manifests(session, run_ids: list[str]) -> dict:
    """모든 런이 매니페스트를 가졌는지 확인하고 그것들을 돌려준다.

    로드맵 §15.4 금지 3번의 집행 지점. 거부는 여기 한 곳뿐이며
    `Orchestrator.run()` 은 건드리지 않는다 -- 금지가 겨누는 것은 '런' 이
    아니라 '표본' 이고, 오케스트레이터에 걸면 그것을 직접 짓는 골든·통합
    테스트 수십 건이 깨진다.
    """
    missing = await runs_without_manifest(session, run_ids)
    if missing:
        raise MissingManifestError(missing)
    return await manifests_for(session, run_ids)
```

그리고 Task 6이 만든 `_main()` 성공 경로의 세션 블록을 이것으로 바꾼다:

```python
        async with get_session_ctx() as session:
            manifests = await _gate_and_read_manifests(session, run_ids)
```

- [ ] **Step 4: 사용자에게 정책 판단을 요청한다**

`divergent_manifest_fields`가 **무엇을 갈렸다고 볼지**는 진짜 판단이다:

- 얕은 비교(`!=`)로 충분한가, 아니면 `models`는 `judge_equals_scout`만 봐야 하나?
- `skills` 목록의 순서 차이는 갈린 것인가?
- 갈렸을 때 **중단할 것인가, 기록하고 진행할 것인가?** 중단하면 6런짜리 라이브
  표본이 통째로 버려진다(비싸다). 진행하면 §15.2 ㉰의 귀속 불가를 아티팩트에
  기록만 하고 넘어간다.

사용자가 위 함수 본문(5~10줄)과 `_main()`의 갈림 처리 정책을 정한다.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_funnel_sample_gate.py -q`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_gate.py
git commit -m "feat(deep-analysis): 표본 경계 매니페스트 게이트

로드맵 §15.4 금지 3번 -- 매니페스트 없는 런은 표본이 아니고, 지침이
아니라 기계가 거부한다. 거부는 표본 경계에서만 한다. Orchestrator.run()
은 건드리지 않는다 -- 그것을 직접 짓는 골든·통합 테스트가 깨지고,
금지가 겨누는 것은 '런' 이 아니라 '표본' 이다.

실패 경로에는 게이트가 없다 (§10.1 증거 보존)."
```

---

### Task 8: 백테스트 — 칸별 복원 가능 여부 표

**Files:**
- Create: `scripts/manifest_backtest.py`
- Create: `docs/superpowers/plans/artifacts/2026-08-22-manifest-backtest.md` (산출물)
- Test: `tests/workflow/deep_analysis/test_manifest_backtest.py`

**Interfaces:**
- Consumes: 없음 — Task 3의 스키마를 **이름으로만** 안다(아래 `MANIFEST_FIELDS`가
  §3.3 스키마의 최상위 칸을 다시 적는다). 과거 아티팩트를 읽는 것이 목적이므로
  런타임 코드에 의존하면 옛 모양을 못 읽는다
- Produces:
  - `MANIFEST_FIELDS: tuple[str, ...]`
  - `def recoverable_fields(artifact_manifest: dict) -> dict[str, bool]`

- [ ] **Step 1: Write the failing test**

`tests/workflow/deep_analysis/test_manifest_backtest.py`:

```python
from scripts.manifest_backtest import MANIFEST_FIELDS, recoverable_fields


def test_legacy_artifact_recovers_only_what_it_recorded():
    """표본 #16~#20 의 실제 모양.

    옛 지문에는 models·resolved_models·global_token_cap 등이 있으나
    프롬프트 해시도 스킬 목록도 components 도 없다.
    """
    legacy = {
        "config_fingerprint": {
            "global_token_cap": 300000,
            "max_depth": 2,
            "models": {"judge": None},
            "resolved_models": {"judge": {"model": "claude-sonnet-5"}},
            "git": {"commit": "abc"},
        }
    }

    recovered = recoverable_fields(legacy)

    assert recovered["models"] is True
    assert recovered["prompts"] is False
    assert recovered["skills"] is False
    assert recovered["components"] is False
    assert recovered["profile"] is False


def test_new_artifact_recovers_every_field():
    new = {
        "config_fingerprint": {
            "manifest_version": 1,
            "git": {"commit": "abc"},
            "runs": {
                "r1": {
                    "manifest_version": 1,
                    "profile": "dev",
                    "models": {"judge": {"model": "claude-sonnet-5"}},
                    "budget": {"global_token_cap": 140000},
                    "prompts": {"final_compose": "sha256:a"},
                    "skills": [],
                    "components": {"grader": "x:Y"},
                    "config": {"max_depth": 2},
                }
            },
        }
    }

    recovered = recoverable_fields(new)

    assert all(recovered[field] for field in MANIFEST_FIELDS)


def test_every_manifest_field_is_judged():
    legacy = {"config_fingerprint": {}}

    assert set(recoverable_fields(legacy)) == set(MANIFEST_FIELDS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest_backtest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.manifest_backtest'`

- [ ] **Step 3: Write minimal implementation**

`scripts/manifest_backtest.py`:

```python
"""표본 아티팩트만으로 런 구성을 복원할 수 있는지 칸별로 판정한다 (H1 관문).

라이브 표본을 한 건도 쓰지 않는다 -- 디스크에 이미 있는 아티팩트만 읽는다.
로드맵 §13.3 F1 과 같은 값싼 백테스트다.

관문의 산출물은 "통과/실패" 가 아니라 **칸별 복원 가능 여부 표**다.
과거 아티팩트에 프롬프트 해시도 스킬 목록도 components 도 없다는 것은
예상된 결과이고, 그 사실 자체가 H1 의 근거다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST_FIELDS = (
    "profile",
    "models",
    "budget",
    "prompts",
    "skills",
    "components",
    "config",
)

# 옛 지문에서 새 매니페스트의 칸을 (부분적으로라도) 복원할 수 있는 키.
_LEGACY_SOURCES = {
    "models": ("resolved_models", "models"),
    "budget": ("global_token_cap",),
    "config": ("max_depth", "quote_match_threshold"),
}


def recoverable_fields(artifact_manifest: dict) -> dict[str, bool]:
    fingerprint = artifact_manifest.get("config_fingerprint") or {}
    runs = fingerprint.get("runs")
    if isinstance(runs, dict) and runs:
        sample = next(iter(runs.values()))
        return {field: field in sample for field in MANIFEST_FIELDS}
    return {
        field: any(key in fingerprint for key in _LEGACY_SOURCES.get(field, ()))
        for field in MANIFEST_FIELDS
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    print("| 표본 | " + " | ".join(MANIFEST_FIELDS) + " |")
    print("|---" * (len(MANIFEST_FIELDS) + 1) + "|")
    for directory in args.artifact_dirs:
        data = json.loads((directory / "manifest.json").read_text())
        recovered = recoverable_fields(data)
        cells = " | ".join(
            "✅" if recovered[field] else "❌" for field in MANIFEST_FIELDS
        )
        print(f"| {directory.name} | {cells} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/workflow/deep_analysis/test_manifest_backtest.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 관문을 실제로 돌린다**

```bash
python -m scripts.manifest_backtest \
  artifacts/deep-analysis-funnel/20260811T152942Z \
  artifacts/deep-analysis-funnel/20260814T132904Z \
  artifacts/deep-analysis-funnel/20260814T173905Z \
  artifacts/deep-analysis-funnel/20260816T103413Z \
  artifacts/deep-analysis-funnel/20260818T111321Z
```

출력 표를 `docs/superpowers/plans/artifacts/2026-08-22-manifest-backtest.md`에
저장하고, 표본 번호(#16~#20)와 `DECISIONS.md`의 해당 D 번호를 붙인다.
❌가 나온 칸이 "지금 복원 불가능한 것"의 목록이며 이것이 H1의 산출물이다.

- [ ] **Step 6: Commit**

```bash
git add scripts/manifest_backtest.py tests/workflow/deep_analysis/test_manifest_backtest.py docs/superpowers/plans/artifacts/2026-08-22-manifest-backtest.md
git commit -m "test(deep-analysis): H1 관문 -- 표본 #16~#20 칸별 복원 가능 여부

라이브 표본을 한 건도 쓰지 않는다. 관문의 산출물은 통과/실패가 아니라
칸별 표다 -- 과거 아티팩트에 프롬프트 해시도 스킬 목록도 components 도
없다는 사실 자체가 H1 의 근거다."
```

---

### Task 9: 원장·로드맵 갱신

**Files:**
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D84 추가)
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` — §1 트랙 H 행, §15.3 H1 행, §15.5 H-1

**Interfaces:** 없음 (문서)

- [ ] **Step 1: D84를 쓴다**

`DECISIONS.md` 끝에 `## D84. H1 구성 매니페스트 — 원장이 런의 구성을 답한다 (2026-08-22)`.
담을 것: H-1 결정(새 이벤트 kind, 마이그레이션 0건) · 거부 지점(표본 경계) ·
토폴로지 항 대체(컴포넌트 배선) · 프롬프트 8 vs 9 · 실측 근거(표본 #20의
`global_token_cap` 300000 vs dev 5런, `available_for_investigation` 86,400이
D78의 숫자와 일치) · Task 8 백테스트 결과 표 · 남긴 미결(H-2·H-3·H1-m1).

- [ ] **Step 2: 로드맵 세 곳을 고친다**

- §1 트랙 H 행: `⚪ 계획만` → `🟢 H1 완료`. 다음 관문은 H3(선행 H1 충족)이나
  그 관문이 G2-b임을 적는다.
- §15.3 표의 H1 행에 완료 표시와 D84 참조.
- §15.5 H-1 행에 결정(이벤트 kind)과 근거(`DAEvent.kind`가 String(40), SCHEMA1 악화 없음).

⚠️ 로드맵의 기존 서술을 지우지 말고 **정정 상자로 덧붙인다** — 이 문서의 관례다
(§1의 "여섯 트랙" 정정 상자, §12의 해소 상자).

- [ ] **Step 3: 전체 검증**

Run: `python -m pytest tests/workflow/deep_analysis -q && python -m ruff check . && cd web && pnpm test:source`
Expected: 전부 PASS

- [ ] **Step 4: Commit**

```bash
git add neos/workflow/deep_analysis/DECISIONS.md docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md
git commit -m "docs(track-h): D84 -- H1 완료. 원장이 런의 구성을 답한다"
```

---

## 실행 순서와 의존

```
Task 1 (역할 테이블)
  └→ Task 2 (호출 지점 9곳 이전)
       └→ Task 3 (manifest.py)          ← Task 1 의 HARNESS_ROLES 도 쓴다
            └→ Task 4 (발행)
                 ├→ Task 5 (FE 라벨)     ← Task 4 와 병렬 가능
                 └→ Task 6 (아티팩트 층)
                      └→ Task 7 (표본 게이트)  ← 사용자 기여 지점
Task 8 (백테스트)  ← Task 3 의 MANIFEST_FIELDS 만 쓴다. 언제든 가능
Task 9 (원장·로드맵) ← 전부 끝난 뒤
```

**트랙 A와의 관계:** 이 플랜은 LLM 호출 경로를 바꾸지 않는다(Task 2는 해석 결과가
동일한 이전이다). §10.2의 "측정 중 변경"에 해당하지 않으므로 표본 #21과 병행 가능하다.
단 **Task 4 이후에 돌린 표본은 매니페스트를 갖고, 이전 표본은 갖지 않는다** —
`manifest_version`이 그 경계다.
