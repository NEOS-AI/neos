# 모델별 effort 기본값 · 사용자 설정 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영자가 모델별 effort 기본값을 설정 파일로 정하고, 사용자가 피커 옆에서 모델별 effort 를 고르며, 그 선택이 백엔드 DB 에 저장되어 모든 채팅 턴에 서버 쪽에서 적용되게 한다.

**Architecture:** 카탈로그(`models.yaml`)가 모델이 받는 레벨(사실)을, `config/neos.*.yaml` 의 `model_routing.effort.models` 가 모델별 기본값(정책)을, 새 테이블 `user_model_preferences` 가 사용자 선택을 갖는다. 채팅 턴은 `_resolve_turn` 한 곳에서 기존 `resolve_effort` 사슬(user → conversation → feature → **model default** → role)로 effort 를 정하고, `effort_request_fields` 한 곳에서 프로바이더 필드(Anthropic `output_config.effort`, OpenAI `reasoning_effort`)로 번역한다. 프론트는 Next 라우트 핸들러로 선호를 읽고 쓰기만 하고 채팅 요청은 바꾸지 않는다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async(`db_manager`), PostgreSQL, LangChain(`ChatAnthropic`/`ChatOpenAI`), Anthropic SDK 0.122, OpenAI SDK, Next.js 16 + React 19, `node:test` + tsx.

**Spec:** `docs/MODEL_EFFORT_PREFERENCES_DESIGN.md` (커밋 `3b79df62`)

## Global Constraints

- 어휘는 SDK 에서 온다: Anthropic `low, medium, high, xhigh, max` / OpenAI `none, minimal, low, medium, high, xhigh, max`. 손으로 쓴 목록은 테스트가 SDK Literal 과 맞대 놓는다.
- 확인하지 않은 `effort_levels` 는 적지 않는다. 비면 "모른다" = 보내지 않는다.
- `effort is None` 이면 요청에 키를 **넣지 않는다** (`null` 도 금지).
- 우선순위: user×모델 (DB) → 대화 → 기능 오버라이드 → 모델별 기본값 → 역할 기본값 → 안 보냄.
- 설정 `effort.models` 의 모르는 핀 · 미지원 레벨은 **부팅 실패**다.
- DB 조회 실패는 채팅 턴을 실패시키지 않는다 (경고 후 사용자 설정 없음으로 진행).
- 프로바이더가 effort 를 400 으로 거절하면 숨기지 않는다 (재전송 없음).
- 채팅 진입점 넷은 모두 `_resolve_turn` 을 거친다. 해석과 번역은 각각 한 곳에만 있다.
- 첨부 없는 턴은 소유자 조회(`ChatRepository.get_conversation`)를 하지 않는다 (`tests/services/test_chat_llm_owner_lazy_resolution.py`, Fix round 2 Item 2). 선호 조회는 `conversation_id` 로 조인한 **쿼리 한 번**이고 소유자 조회를 부르지 않는다.
- 커밋 메시지에 Co-Authored-By 트레일러를 넣지 않는다.
- 문서는 한국어 (`docs/CONFIGURATION.md` 는 영어 문서이므로 영어).

## Review Focus

1. **gateway id 로 들어온 PUT** (`anthropic/claude-opus-5.5`) — 경로의 `/` 때문에 404 가 나기 쉽다. 사용자는 저장되길 기대한다 → Task 7 에 테스트.
2. **은퇴한 핀으로 들어온 PUT** (`claude-opus-5`) — 후계 핀(`claude-opus-5-5`)으로 저장되길 기대한다 → Task 7 에 테스트.
3. **저장 후 모델이 그 레벨을 잃음** — 채팅은 계속되고 다음 칸으로 넘어가길 기대한다 → Task 6 에 테스트.
4. **tool 경로가 비-Anthropic 모델에서 `generate_response_stream` 으로 위임** — effort 가 두 번 해석되거나 사라지지 않길 기대한다 → Task 6 에 테스트.
5. **effort 선택기가 레벨 없는 모델(Gemini·레거시)에서** — 보이지 않길 기대한다 → Task 9 에 테스트.

---

## 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `neos/config/model_config.py` | 프로바이더별 어휘, `ModelSpec.effort_levels` 검증 | 수정 |
| `neos/config/models.yaml` | 모델별 `effort_levels` (사실) | 수정 |
| `scripts/probe_anthropic_effort.py` | models API 로 Anthropic 레벨 확인 (일회성 도구) | 생성 |
| `neos/config/schema.py` | `RoleEffortConfig.models`, 교차 검증 | 수정 |
| `neos/config/model_routing.py` | `resolve_effort` 에 `model_default` 칸, `ResolutionSource.MODEL_DEFAULT` | 수정 |
| `neos/providers/effort.py` | `effort_request_fields(provider, effort)` | 생성 |
| `neos/providers/anthropic.py`, `openai.py` | `create_llm(effort=)` 배선, thinking 끄기 번역 | 수정 |
| `db/migrations/063_add_user_model_preferences.sql` | 테이블 | 생성 |
| `neos/database/repositories/model_preference_repository.py` | 조회 · upsert · 삭제 · 목록 | 생성 |
| `neos/services/chat_effort.py` | `resolve_chat_effort(model, conversation_id)` | 생성 |
| `neos/services/chat_llm_service.py` | `_resolve_turn` 과 네 진입점 배선 | 수정 |
| `neos/api/handlers/model_preference_handlers.py` | GET/PUT/DELETE | 생성 |
| `neos/main.py` | 라우터 등록 | 수정 |
| `neos/config/model_identity.py`, `neos/api/models/catalog_models.py`, `scripts/generate_catalog_fallback.py` | 피커 페이로드 필드 | 수정 |
| `web/lib/ai/models.ts`, `web/lib/ai/effort.ts` | 타입, 순수 로직 | 수정 / 생성 |
| `web/app/(chat)/api/model-preferences/route.ts`, `[model]/route.ts` | 프록시 | 생성 |
| `web/hooks/use-model-effort.ts`, `web/components/effort-selector.tsx`, `web/components/multimodal-input.tsx` | 훅, 선택기, 배치 | 생성 / 수정 |
| `config/neos.default.yaml`, `docs/CONFIGURATION.md` | 기본값, 운영 문서 | 수정 |

---

### Task 1: 프로바이더별 effort 어휘

**Files:**
- Modify: `neos/config/model_config.py:98-106` (EFFORT_LEVELS), `:166-181` (`_effort_levels_known`)
- Modify: `neos/config/model_routing.py:166-175` (`_gate_effort` 의 어휘 검사)
- Test: `tests/config/test_model_effort.py`

**Interfaces:**
- Produces:
  - `EFFORT_VOCABULARY: dict[str, tuple[str, ...]]` — 키 `"anthropic"`, `"openai"`
  - `ALL_EFFORT_LEVELS: tuple[str, ...]` — 두 어휘의 순서 있는 합집합 `("none","minimal","low","medium","high","xhigh","max")`
  - `EFFORT_LEVELS` 는 `EFFORT_VOCABULARY["anthropic"]` 의 별칭으로 남긴다 (기존 독자 호환)
  - `ModelSpec` 은 `effort_levels` 가 `EFFORT_VOCABULARY.get(provider, ())` 의 부분집합이 아니면 `ValueError("... effort ...")`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/config/test_model_effort.py` 의 `SDK_EFFORT_LEVELS` 아래에 추가한다.

```python
def _literal_levels(annotation) -> set[str]:
    from typing import get_args

    literal = next(arg for arg in get_args(annotation) if get_args(arg))
    return set(get_args(literal))


def test_openai_levels_come_from_the_installed_sdk() -> None:
    from typing import get_args

    from openai.types.shared.reasoning_effort import ReasoningEffort

    from neos.config.model_config import EFFORT_VOCABULARY

    # ReasoningEffort = Optional[Literal[...]]
    literal = next(arg for arg in get_args(ReasoningEffort) if get_args(arg))
    levels = set(get_args(literal))
    assert len(levels) >= 7
    assert set(EFFORT_VOCABULARY["openai"]) == levels


def test_the_union_is_ordered_low_to_high() -> None:
    from neos.config.model_config import ALL_EFFORT_LEVELS, EFFORT_VOCABULARY

    assert ALL_EFFORT_LEVELS == (
        "none", "minimal", "low", "medium", "high", "xhigh", "max",
    )
    for vocab in EFFORT_VOCABULARY.values():
        assert set(vocab) <= set(ALL_EFFORT_LEVELS)


def test_an_openai_level_is_refused_on_an_anthropic_model() -> None:
    from neos.config.model_config import ModelSpec

    with pytest.raises(ValueError, match="effort"):
        ModelSpec(provider="anthropic", effort_levels=["none"])


def test_an_openai_model_takes_openai_levels() -> None:
    from neos.config.model_config import ModelSpec

    spec = ModelSpec(provider="openai", effort_levels=["high", "none", "low"])
    assert spec.effort_levels == ["none", "low", "high"]


def test_a_provider_without_a_vocabulary_takes_no_levels() -> None:
    from neos.config.model_config import ModelSpec

    with pytest.raises(ValueError, match="effort"):
        ModelSpec(provider="gemini", effort_levels=["low"])
```

그리고 `test_the_levels_come_from_the_installed_sdk` 의 마지막 두 단언을 다음으로 바꾼다.

```python
    from neos.config.model_config import EFFORT_VOCABULARY

    assert set(EFFORT_VOCABULARY["anthropic"]) == levels
    assert set(EFFORT_LEVELS) == set(SDK_EFFORT_LEVELS)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/config/test_model_effort.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'EFFORT_VOCABULARY'`

- [ ] **Step 3: 구현한다** — `neos/config/model_config.py` 의 `EFFORT_LEVELS` 정의를 다음으로 바꾼다.

```python
#: 모델 사고량 레벨. **SDK 가 정한 어휘이고 순서가 있다** (none < … < max).
#:
#: 프로바이더마다 어휘가 다르다 -- Anthropic `OutputConfigParam.effort`,
#: OpenAI `ReasoningEffort`. 둘 다 `tests/config/test_model_effort.py` 가
#: SDK 의 Literal 과 맞대 놓는다. 프로바이더가 정한 어휘는 프로바이더에게 묻는다.
EFFORT_VOCABULARY: dict[str, tuple[str, ...]] = {
    "anthropic": ("low", "medium", "high", "xhigh", "max"),
    "openai": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
}

#: 두 어휘의 순서 있는 합집합. 정렬과 "알려진 레벨인가" 검사에 쓴다.
ALL_EFFORT_LEVELS: tuple[str, ...] = (
    "none", "minimal", "low", "medium", "high", "xhigh", "max",
)

#: 하위 호환 별칭 -- Anthropic 어휘. 새 코드는 EFFORT_VOCABULARY 를 쓴다.
EFFORT_LEVELS: tuple[str, ...] = EFFORT_VOCABULARY["anthropic"]
```

`_effort_levels_known` field validator 를 지우고, `ModelSpec` 안에 다음 model validator 를 둔다 (`model_validator` 는 파일 상단 pydantic import 에 이미 없으면 더한다).

```python
    @model_validator(mode="after")
    def _effort_levels_in_provider_vocabulary(self) -> "ModelSpec":
        """프로바이더 어휘 밖의 레벨은 설정 검증에서 멈춘다.

        오타가 배포까지 가면 그 모델의 **매 요청이 400** 이다. 순서는 사고량
        순서로 정렬한다 -- "가장 낮은 레벨" 같은 질문이 틀린 답을 얻지 않게.
        """
        vocab = EFFORT_VOCABULARY.get(self.provider, ())
        unknown = sorted(set(self.effort_levels) - set(vocab))
        if unknown:
            raise ValueError(
                f"unknown effort levels {unknown} for provider "
                f"{self.provider!r}; the SDK defines {list(vocab)}"
            )
        self.effort_levels = sorted(
            set(self.effort_levels), key=ALL_EFFORT_LEVELS.index
        )
        return self
```

`neos/config/model_routing.py` 의 `_gate_effort` 에서 import 와 어휘 검사를 합집합으로 바꾼다.

```python
    from neos.config.model_config import ALL_EFFORT_LEVELS

    if value not in ALL_EFFORT_LEVELS:
        return EffortResolution(
            effort=None,
            source=source,
            refused="unknown_level",
            detail=f"{value!r} is not one of {list(ALL_EFFORT_LEVELS)}",
        )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/config/test_model_effort.py tests/config/test_effort_routing.py tests/config/test_harness_effort.py -q -p no:cacheprovider`
Expected: PASS (기존 `test_the_declaration_keeps_the_sdk_order` 포함)

- [ ] **Step 5: 커밋한다**

```bash
git add neos/config/model_config.py neos/config/model_routing.py tests/config/test_model_effort.py
git commit -m "feat(effort): split the effort vocabulary by provider and pin both to their SDKs"
```

---

### Task 2: 모델별 `effort_levels` 를 확인해 채운다

**Files:**
- Create: `scripts/probe_anthropic_effort.py`
- Modify: `neos/config/models.yaml` (claude-sonnet-5, claude-opus-5-5, claude-haiku-4-5-20251001, claude-fable-5-1, claude-opus-4-8, gpt-6-sol, gpt-6-luna)
- Test: `tests/config/test_model_effort.py` (`test_no_catalog_model_claims_effort_support_yet` 교체)

**Interfaces:**
- Consumes: Task 1 의 `ModelSpec` 검증
- Produces: 카탈로그의 `effort_levels` 값. 이후 Task 3·4·8 이 읽는다.

- [ ] **Step 1: 확인 도구를 쓴다** — `scripts/probe_anthropic_effort.py`

```python
"""Anthropic models API 로 모델별 effort 레벨을 읽는다 (일회성 확인 도구).

카탈로그의 `effort_levels` 는 이 출력으로만 채운다. 추측하지 않는다.

    python scripts/probe_anthropic_effort.py claude-sonnet-5 claude-opus-5-5
"""

from __future__ import annotations

import sys

import anthropic

LEVELS = ("low", "medium", "high", "xhigh", "max")


def levels_for(client: anthropic.Anthropic, model: str) -> list[str]:
    info = client.models.retrieve(model)
    effort = info.capabilities.effort
    if not effort.supported:
        return []
    found = []
    for level in LEVELS:
        support = getattr(effort, level, None)
        if support is not None and support.supported:
            found.append(level)
    return found


def main(models: list[str]) -> None:
    client = anthropic.Anthropic()
    for model in models:
        print(f"{model}: {levels_for(client, model)}")


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 2: 실호출로 확인한다**

Run: `python scripts/probe_anthropic_effort.py claude-sonnet-5 claude-opus-5-5 claude-haiku-4-5-20251001 claude-fable-5-1 claude-opus-4-8`
Expected: 모델마다 한 줄. 출력을 그대로 기록해 둔다 (Step 4 의 주석과 테스트에 쓴다). 키가 실패하면 **여기서 멈추고** 사람에게 알린다 — 값을 추측해 채우지 않는다.

- [ ] **Step 3: 테스트를 확인된 값으로 바꾼다** — `test_no_catalog_model_claims_effort_support_yet` 를 지우고 다음을 둔다. `ANTHROPIC_PROBED` 의 값은 Step 2 출력 그대로다 (아래는 형태 예시가 아니라, 출력으로 바꿔 쓸 자리다 — 출력과 다르면 출력이 이긴다).

```python
#: 2026-09-24 `scripts/probe_anthropic_effort.py` 실호출 출력.
#: 바꾸려면 다시 재고 출력을 여기에 붙인다.
ANTHROPIC_PROBED: dict[str, list[str]] = {
    # Step 2 출력을 한 줄씩 옮긴다. 빈 목록인 모델은 적지 않는다.
}

#: OpenAI 공식 models 문서 (developers.openai.com/api/docs/models, 2026-09-24):
#: "Supports none, low, medium, high, xhigh, and max levels"
OPENAI_DOCUMENTED: dict[str, list[str]] = {
    "gpt-6-sol": ["none", "low", "medium", "high", "xhigh", "max"],
    "gpt-6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
}


def test_catalog_effort_levels_are_exactly_what_was_measured() -> None:
    """채운 값은 전부 근거가 있다 -- 이 표 밖의 선언은 추측이다."""
    from neos.config.model_config import model_config

    claimed = {
        name: spec.effort_levels
        for name, spec in model_config.catalog.models.items()
        if spec.effort_levels
    }
    assert claimed == {**ANTHROPIC_PROBED, **OPENAI_DOCUMENTED}
```

- [ ] **Step 4: 실패를 확인한다**

Run: `python -m pytest tests/config/test_model_effort.py::test_catalog_effort_levels_are_exactly_what_was_measured -q -p no:cacheprovider`
Expected: FAIL — `claimed == {}` 이 기대값과 다르다.

- [ ] **Step 5: 카탈로그를 채운다** — `neos/config/models.yaml` 에서 Step 2 출력이 있는 각 Anthropic 모델과 두 OpenAI 모델에 `effort_levels:` 를 더한다. 예 (gpt-6-sol):

```yaml
    # OpenAI 공식 models 문서 (2026-09-24). tests/config/test_model_effort.py
    # 의 OPENAI_DOCUMENTED 와 같아야 한다.
    effort_levels: [none, low, medium, high, xhigh, max]
```

Anthropic 모델은 같은 형태에 주석을 `# models API 실호출 (2026-09-24, scripts/probe_anthropic_effort.py)` 로 둔다. 상단 필드 설명의 `effort_levels` 문단 끝에 "프로바이더별 어휘 안에서만 (EFFORT_VOCABULARY)" 한 줄을 더한다.

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest tests/config -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 7: 커밋한다**

```bash
git add scripts/probe_anthropic_effort.py neos/config/models.yaml tests/config/test_model_effort.py
git commit -m "feat(effort): declare measured effort levels for current Claude and GPT-6 models"
```

---

### Task 3: 설정의 모델별 기본값과 사슬의 새 칸

**Files:**
- Modify: `neos/config/schema.py:147-159` (`RoleEffortConfig`), `AppConfig` 에 validator 추가
- Modify: `neos/config/model_routing.py:15-20` (`ResolutionSource`), `:120-160` (`resolve_effort`)
- Test: `tests/config/test_effort_routing.py`, `tests/config/test_effort_model_defaults.py` (생성)

**Interfaces:**
- Consumes: Task 2 의 카탈로그 `effort_levels`, `effort_levels_for(model) -> tuple[str, ...]`
- Produces:
  - `RoleEffortConfig.models: dict[str, str]` (기본 `{}`)
  - `ResolutionSource.MODEL_DEFAULT = "model_default"`
  - `resolve_effort(*, model, role, supported_levels, user_effort=None, conversation_effort=None, feature_override=None, model_default=None, role_default=None) -> EffortResolution`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/config/test_effort_routing.py` 끝에 추가한다.

```python
def test_the_model_default_wins_over_the_role_default() -> None:
    resolution = _resolve(model_default="medium", role_default="high")

    assert resolution.effort == "medium"
    assert resolution.source is ResolutionSource.MODEL_DEFAULT


def test_the_feature_override_wins_over_the_model_default() -> None:
    resolution = _resolve(feature_override="high", model_default="low")

    assert resolution.effort == "high"
    assert resolution.source is ResolutionSource.FEATURE_OVERRIDE


def test_an_openai_level_passes_the_gate_when_the_model_takes_it() -> None:
    resolution = _resolve(
        model="gpt-6-sol",
        user_effort="none",
        supported_levels=("none", "low", "high"),
    )

    assert resolution.effort == "none"
```

`tests/config/test_effort_model_defaults.py` 를 만든다.

```python
"""설정 `model_routing.effort.models` 는 부팅 때 카탈로그와 맞대 본다."""

from __future__ import annotations

import pytest

from neos.config.model_config import effort_levels_for
from neos.config.schema import AppConfig

pytestmark = pytest.mark.no_db


def _a_model_with_levels() -> tuple[str, str]:
    for name in ("claude-opus-5-5", "gpt-6-sol"):
        levels = effort_levels_for(name)
        if levels:
            return name, levels[0]
    pytest.skip("no catalog model declares effort levels")


def test_models_default_is_empty() -> None:
    assert AppConfig().model_routing.effort.models == {}


def test_a_known_pin_and_level_is_accepted() -> None:
    name, level = _a_model_with_levels()
    config = AppConfig.model_validate(
        {"model_routing": {"effort": {"models": {name: level}}}}
    )
    assert config.model_routing.effort.models == {name: level}


def test_an_unknown_pin_stops_boot() -> None:
    with pytest.raises(ValueError, match="not a catalog model"):
        AppConfig.model_validate(
            {"model_routing": {"effort": {"models": {"claude-nope": "low"}}}}
        )


def test_a_level_the_model_does_not_take_stops_boot() -> None:
    name, _ = _a_model_with_levels()
    with pytest.raises(ValueError, match="does not take"):
        AppConfig.model_validate(
            {"model_routing": {"effort": {"models": {name: "bogus"}}}}
        )
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/config/test_effort_routing.py tests/config/test_effort_model_defaults.py -q -p no:cacheprovider`
Expected: FAIL — `unexpected keyword argument 'model_default'`, `AttributeError: MODEL_DEFAULT`, `models` 필드 없음

- [ ] **Step 3: 구현한다**

`neos/config/model_routing.py` 의 `ResolutionSource` 에 한 줄을 더한다.

```python
class ResolutionSource(str, Enum):
    USER = "user"
    CONVERSATION = "conversation"
    FEATURE_OVERRIDE = "feature_override"
    MODEL_DEFAULT = "model_default"
    ROLE_DEFAULT = "role_default"
```

`resolve_effort` 시그니처에 `model_default: str | None = None,` 을 `feature_override` 와 `role_default` 사이에 더하고, 순회 튜플을 바꾼다.

```python
    for value, source in (
        (user_effort, ResolutionSource.USER),
        (conversation_effort, ResolutionSource.CONVERSATION),
        (feature_override, ResolutionSource.FEATURE_OVERRIDE),
        (model_default, ResolutionSource.MODEL_DEFAULT),
        (role_default, ResolutionSource.ROLE_DEFAULT),
    ):
```

`neos/config/schema.py` 의 `RoleEffortConfig` 에 필드를 더한다.

```python
    everyday: str | None = None
    powerful: str | None = None
    # 모델별 기본값 {카탈로그 핀: 레벨}. 역할 기본값보다 구체적이므로 사슬에서
    # 그 위다. 키와 레벨은 AppConfig.validate_effort_model_defaults 가 부팅 때
    # 카탈로그와 맞대 본다 -- 오타는 부팅 실패다.
    models: dict[str, str] = Field(default_factory=dict)
```

`AppConfig` 에 validator 를 더한다 (`validate_coding_model_policy` 옆).

```python
    @model_validator(mode="after")
    def validate_effort_model_defaults(self) -> "AppConfig":
        defaults = self.model_routing.effort.models
        if not defaults:
            return self
        from neos.config.model_config import effort_levels_for, model_config

        for pin, level in defaults.items():
            if pin not in model_config.catalog.models:
                raise ValueError(
                    f"model_routing.effort.models: {pin!r} is not a catalog model"
                )
            levels = effort_levels_for(pin)
            if level not in levels:
                raise ValueError(
                    f"model_routing.effort.models: {pin!r} does not take "
                    f"{level!r}; it takes {list(levels)}"
                )
        return self
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/config -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/config/model_routing.py neos/config/schema.py tests/config/test_effort_routing.py tests/config/test_effort_model_defaults.py
git commit -m "feat(effort): per-model effort defaults in config, checked against the catalog at boot"
```

---

### Task 4: 요청 번역과 LangChain 배선, thinking 끄기 번역

**Files:**
- Create: `neos/providers/effort.py`
- Modify: `neos/providers/anthropic.py` (`create_llm`, `_translate_thinking_off`), `neos/providers/openai.py` (`create_llm`)
- Test: `tests/providers/test_effort_request_fields.py` (생성), `tests/providers/test_anthropic_thinking_always_on.py`

**Interfaces:**
- Consumes: `effort_levels_for(model)` (Task 2)
- Produces:
  - `effort_request_fields(provider: str, effort: str | None) -> dict[str, Any]`
  - `AnthropicProvider.create_llm(..., effort: str | None = None)` / `OpenAIProvider.create_llm(..., effort: str | None = None)` — kwargs 로 받는다
  - `normalize_anthropic_request(model, params, *, thinking_enabled)` 의 always-on 번역: `params` 에 `output_config.effort` 가 이미 있으면 건드리지 않는다

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/providers/test_effort_request_fields.py`

```python
import pytest

from neos.providers.effort import effort_request_fields

pytestmark = pytest.mark.no_db


def test_anthropic_goes_to_output_config() -> None:
    assert effort_request_fields("anthropic", "high") == {
        "output_config": {"effort": "high"}
    }


def test_openai_goes_to_reasoning_effort() -> None:
    assert effort_request_fields("openai", "none") == {"reasoning_effort": "none"}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_nothing_resolved_means_no_key_at_all(provider: str) -> None:
    assert effort_request_fields(provider, None) == {}


def test_a_provider_without_effort_refuses_a_value() -> None:
    with pytest.raises(ValueError, match="gemini"):
        effort_request_fields("gemini", "low")


def test_anthropic_create_llm_carries_effort(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "k")
    llm = mod.AnthropicProvider().create_llm(
        "claude-sonnet-5", 0.1, 1000, effort="high"
    )
    assert llm.output_config == {"effort": "high"}


def test_anthropic_create_llm_without_effort_sends_no_output_config(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "k")
    llm = mod.AnthropicProvider().create_llm("claude-sonnet-5", 0.1, 1000)
    assert not llm.output_config


def test_openai_create_llm_carries_reasoning_effort(monkeypatch) -> None:
    from neos.providers import openai as mod

    monkeypatch.setattr(mod.settings, "OPENAI_API_KEY", "k")
    llm = mod.OpenAIProvider().create_llm("gpt-6-sol", 0.1, 1000, effort="low")
    assert llm.reasoning_effort == "low"
```

`tests/providers/test_anthropic_thinking_always_on.py` 끝에 추가한다.

```python
def test_thinking_off_becomes_low_effort_when_the_model_takes_low(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod, "effort_levels_for", lambda model: ("low", "high"))
    params = normalize_anthropic_request(
        "claude-opus-5-5", {"model": "claude-opus-5-5"}, thinking_enabled=False
    )
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "low"}


def test_thinking_off_leaves_effort_alone_when_low_is_not_declared(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod, "effort_levels_for", lambda model: ())
    params = normalize_anthropic_request(
        "claude-opus-5-5", {"model": "claude-opus-5-5"}, thinking_enabled=False
    )
    assert "output_config" not in params


def test_an_explicit_effort_wins_over_thinking_off(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod, "effort_levels_for", lambda model: ("low", "high"))
    params = normalize_anthropic_request(
        "claude-opus-5-5",
        {"model": "claude-opus-5-5", "output_config": {"effort": "high"}},
        thinking_enabled=False,
    )
    assert params["output_config"] == {"effort": "high"}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/providers/test_effort_request_fields.py tests/providers/test_anthropic_thinking_always_on.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: neos.providers.effort`, `effort_levels_for` 속성 없음

- [ ] **Step 3: 구현한다** — `neos/providers/effort.py`

```python
"""해석된 사고량(effort)을 프로바이더 요청 필드로 번역한다.

번역은 여기 한 곳에만 있다. LangChain 경로(create_llm)와 Anthropic SDK 경로
(chat 의 tool 경로)가 모두 이것을 부른다 -- 두 곳에 있으면 한쪽만 고쳐진다.

effort 가 None 이면 **키를 넣지 않는다.** `{"effort": None}` 은 SDK 에 따라
null 로 나가고, 그것은 "보내지 않음" 과 같은 뜻이라는 보장이 없다.
"""

from __future__ import annotations

from typing import Any


def effort_request_fields(provider: str, effort: str | None) -> dict[str, Any]:
    if effort is None:
        return {}
    if provider == "anthropic":
        return {"output_config": {"effort": effort}}
    if provider == "openai":
        return {"reasoning_effort": effort}
    raise ValueError(f"provider {provider!r} takes no effort, got {effort!r}")
```

`neos/providers/anthropic.py`:
- import 에 `effort_levels_for` 를 더한다: `from neos.config.model_config import (ThinkingContract, effort_levels_for, get_model_spec, models_for_provider, thinking_contract,)`
- `from .effort import effort_request_fields` 를 더한다.
- `create_llm` 에서 `params.update(kwargs)` 바로 다음에:

```python
        effort = params.pop("effort", None)
        params.update(effort_request_fields("anthropic", effort))
```

- `_translate_thinking_off` 본문(TODO 포함)을 다음으로 바꾼다.

```python
    params["thinking"] = {"type": "adaptive"}
    # 명시적으로 정해진 effort(사용자·설정)가 이긴다.
    if (params.get("output_config") or {}).get("effort"):
        return params
    # 레퍼런스의 권고는 effort `low`. 이 모델이 `low` 를 받는다고 **확인된**
    # 경우에만 보낸다 -- 확인 안 된 effort 는 400 일 수 있다.
    if "low" in effort_levels_for(model):
        params["output_config"] = {
            **(params.get("output_config") or {}),
            "effort": "low",
        }
    return params
```

독스트링의 마지막 문단("이 경로(ChatAnthropic)는 지금 effort 를 어디서도 보내지 않으며 …")을 지우고 "끄기 요청은 thinking 을 켠 채 `effort: low` 로 번역한다 (모델이 low 를 받을 때만)." 로 바꾼다.

`neos/providers/openai.py` 의 `create_llm` 에서 `params.update(kwargs)` 다음에:

```python
        effort = params.pop("effort", None)
        params.update(effort_request_fields("openai", effort))
```

(import: `from .effort import effort_request_fields`)

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/providers -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/providers/effort.py neos/providers/anthropic.py neos/providers/openai.py tests/providers/test_effort_request_fields.py tests/providers/test_anthropic_thinking_always_on.py
git commit -m "feat(effort): translate effort to provider fields in one place, and turn 'thinking off' into low effort"
```

---

### Task 5: 테이블과 저장소

**Files:**
- Create: `db/migrations/063_add_user_model_preferences.sql`
- Create: `neos/database/repositories/model_preference_repository.py`
- Test: `tests/db/test_user_model_preferences_sql.py` (생성), `tests/database/test_model_preference_repository.py` (생성)

**Interfaces:**
- Produces (`ModelPreferenceRepository`, 모두 `@staticmethod async`):
  - `get_effort(user_id: str, model_pin: str) -> str | None`
  - `get_effort_for_conversation(conversation_id: str, model_pin: str) -> str | None` — `conversations` 와 조인한 쿼리 한 번 (채팅 턴 전용)
  - `list_for_user(user_id: str) -> list[ModelPreference]` — `ModelPreference(model_pin: str, effort: str, updated_at: datetime)` dataclass
  - `upsert_effort(user_id: str, model_pin: str, effort: str) -> ModelPreference`
  - `delete(user_id: str, model_pin: str) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/db/test_user_model_preferences_sql.py`

```python
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "db" / "migrations" / "063_add_user_model_preferences.sql"


def test_migration_creates_the_table_idempotently() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS user_model_preferences" in sql
    assert "PRIMARY KEY (user_id, model_pin)" in sql
    assert "REFERENCES users(user_id) ON DELETE CASCADE" in sql


def test_bootstrap_order_includes_063() -> None:
    from scripts.verify_schema_bootstrap import bootstrap_order

    order = bootstrap_order()
    assert "db/migrations/063_add_user_model_preferences.sql" in order
```

`tests/database/test_model_preference_repository.py` (디렉터리가 없으면 `tests/database/__init__.py` 없이 만든다 — 기존 `tests/db` 처럼)

```python
from datetime import datetime, timezone

import pytest

from neos.database.repositories import model_preference_repository as mod

pytestmark = pytest.mark.no_db


class FakeDB:
    def __init__(self, one=None, many=None):
        self.one, self.many, self.calls = one, many or [], []

    async def fetch_one(self, query, *params):
        self.calls.append((query, params))
        return self.one

    async def fetch_all(self, query, *params):
        self.calls.append((query, params))
        return self.many


@pytest.mark.asyncio
async def test_get_effort_reads_one_row(monkeypatch) -> None:
    db = FakeDB(one=("high",))
    monkeypatch.setattr(mod, "db_manager", db)

    assert await mod.ModelPreferenceRepository.get_effort("u1", "m1") == "high"
    assert db.calls[0][1] == ("u1", "m1")


@pytest.mark.asyncio
async def test_get_effort_is_none_without_a_row(monkeypatch) -> None:
    monkeypatch.setattr(mod, "db_manager", FakeDB(one=None))
    assert await mod.ModelPreferenceRepository.get_effort("u1", "m1") is None


@pytest.mark.asyncio
async def test_effort_for_conversation_is_one_joined_query(monkeypatch) -> None:
    db = FakeDB(one=("low",))
    monkeypatch.setattr(mod, "db_manager", db)

    got = await mod.ModelPreferenceRepository.get_effort_for_conversation("c1", "m1")

    assert got == "low"
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "JOIN user_model_preferences" in query
    assert params == ("c1", "m1")


@pytest.mark.asyncio
async def test_upsert_returns_the_stored_row(monkeypatch) -> None:
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    db = FakeDB(one=("m1", "low", now))
    monkeypatch.setattr(mod, "db_manager", db)

    pref = await mod.ModelPreferenceRepository.upsert_effort("u1", "m1", "low")

    assert pref == mod.ModelPreference(model_pin="m1", effort="low", updated_at=now)
    assert "ON CONFLICT (user_id, model_pin) DO UPDATE" in db.calls[0][0]


@pytest.mark.asyncio
async def test_delete_reports_whether_a_row_went(monkeypatch) -> None:
    monkeypatch.setattr(mod, "db_manager", FakeDB(one=("m1",)))
    assert await mod.ModelPreferenceRepository.delete("u1", "m1") is True
    monkeypatch.setattr(mod, "db_manager", FakeDB(one=None))
    assert await mod.ModelPreferenceRepository.delete("u1", "m1") is False
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/db/test_user_model_preferences_sql.py tests/database/test_model_preference_repository.py -q -p no:cacheprovider`
Expected: FAIL — 파일·모듈 없음

- [ ] **Step 3: 구현한다** — `db/migrations/063_add_user_model_preferences.sql`

```sql
-- User × model preferences (effort). 2026-09-24.
-- Design: docs/MODEL_EFFORT_PREFERENCES_DESIGN.md §4.4
-- model_pin is the canonical catalog pin (normalized before insert).
-- effort has no DB constraint: the resolver's gate refuses a level a model
-- no longer takes; the API validates on write.

CREATE TABLE IF NOT EXISTS user_model_preferences (
    user_id    VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    model_pin  VARCHAR(100) NOT NULL,
    effort     VARCHAR(20)  NOT NULL,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, model_pin)
);
```

`neos/database/repositories/model_preference_repository.py`

```python
"""user_model_preferences 저장소 (사용자 × 모델 effort)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from neos.database.connection import db_manager


@dataclass(frozen=True, slots=True)
class ModelPreference:
    model_pin: str
    effort: str
    updated_at: datetime


class ModelPreferenceRepository:
    @staticmethod
    async def get_effort(user_id: str, model_pin: str) -> str | None:
        row = await db_manager.fetch_one(
            "SELECT effort FROM user_model_preferences "
            "WHERE user_id = $1 AND model_pin = $2",
            user_id,
            model_pin,
        )
        return row[0] if row else None

    @staticmethod
    async def get_effort_for_conversation(
        conversation_id: str, model_pin: str
    ) -> str | None:
        """채팅 턴 전용. 소유자 조회를 따로 하지 않도록 조인 한 번으로 끝낸다.

        첨부 없는 턴이 `ChatRepository.get_conversation` 을 부르지 않는다는
        보장(Fix round 2 Item 2)을 지키기 위해서다.
        """
        row = await db_manager.fetch_one(
            """
            SELECT p.effort
            FROM conversations c
            JOIN user_model_preferences p
              ON p.user_id = c.user_id AND p.model_pin = $2
            WHERE c.conversation_id = $1 AND c.deleted_at IS NULL
            """,
            conversation_id,
            model_pin,
        )
        return row[0] if row else None

    @staticmethod
    async def list_for_user(user_id: str) -> list[ModelPreference]:
        rows = await db_manager.fetch_all(
            "SELECT model_pin, effort, updated_at FROM user_model_preferences "
            "WHERE user_id = $1 ORDER BY model_pin",
            user_id,
        )
        return [ModelPreference(r[0], r[1], r[2]) for r in rows]

    @staticmethod
    async def upsert_effort(
        user_id: str, model_pin: str, effort: str
    ) -> ModelPreference:
        row = await db_manager.fetch_one(
            """
            INSERT INTO user_model_preferences (user_id, model_pin, effort)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, model_pin) DO UPDATE
                SET effort = EXCLUDED.effort, updated_at = now()
            RETURNING model_pin, effort, updated_at
            """,
            user_id,
            model_pin,
            effort,
        )
        return ModelPreference(row[0], row[1], row[2])

    @staticmethod
    async def delete(user_id: str, model_pin: str) -> bool:
        row = await db_manager.fetch_one(
            "DELETE FROM user_model_preferences "
            "WHERE user_id = $1 AND model_pin = $2 RETURNING model_pin",
            user_id,
            model_pin,
        )
        return row is not None
```

⚠️ `db_manager.fetch_one` 은 SELECT 가 아닌 쿼리를 커밋하지 않을 수 있다 (`connection.py:238-270` — `create_` 를 포함한 SELECT 만 커밋한다). Step 4 전에 `connection.py` 의 `fetch_one` 을 읽고, INSERT/DELETE … RETURNING 이 커밋되지 않으면 `upsert_effort`·`delete` 를 `db_manager.execute_in_transaction` 로 바꾼다 (그 함수의 반환값 형태를 읽고 맞춘다). 통합 확인은 Step 5.

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/db/test_user_model_preferences_sql.py tests/database/test_model_preference_repository.py -q -p no:cacheprovider && python scripts/verify_schema_bootstrap.py --check-list-only`
Expected: PASS, "선언·이름·가드 검사 통과"

- [ ] **Step 5: 실제 DB 로 커밋 여부를 확인한다** (부트스트랩된 로컬 DB 가 있을 때 — 메모리 `local-integration-tests-need-bootstrapped-db`)

```bash
python - <<'EOF'
import asyncio
from neos.database.connection import db_manager
from neos.database.repositories.model_preference_repository import ModelPreferenceRepository as R

async def main():
    await db_manager.initialize()
    uid = (await db_manager.fetch_one("SELECT user_id FROM users LIMIT 1"))[0]
    await R.upsert_effort(uid, "claude-opus-5-5", "high")
    print(await R.get_effort(uid, "claude-opus-5-5"))
    print(await R.delete(uid, "claude-opus-5-5"))
    print(await R.get_effort(uid, "claude-opus-5-5"))

asyncio.run(main())
EOF
```

Expected: `high`, `True`, `None`. DB 가 없으면 이 단계를 건너뛰었다고 보고한다.

- [ ] **Step 6: 커밋한다**

```bash
git add db/migrations/063_add_user_model_preferences.sql neos/database/repositories/model_preference_repository.py tests/db/test_user_model_preferences_sql.py tests/database/test_model_preference_repository.py
git commit -m "feat(effort): user_model_preferences table and repository"
```

---

### Task 6: 채팅 턴의 effort 해석과 네 진입점 배선

**Files:**
- Create: `neos/services/chat_effort.py`
- Modify: `neos/services/chat_llm_service.py` (네 진입점: `generate_response:244`, `generate_response_stream:383`, `generate_response_stream_with_tools:588`, `generate_response_stream_with_tool_search:804`)
- Modify: `neos/observability/metrics.py` (`chat_effort_resolved_total`)
- Test: `tests/services/test_chat_effort.py` (생성), `tests/services/test_chat_llm_effort_paths.py` (생성), `tests/services/test_chat_llm_owner_lazy_resolution.py` (그대로 초록이어야 한다)

**Interfaces:**
- Consumes: `ModelPreferenceRepository.get_effort_for_conversation` (Task 5), `resolve_effort(..., model_default=)` (Task 3), `effort_levels_for` (Task 2), `effort_request_fields` (Task 4)
- Produces:
  - `async def resolve_chat_effort(model: str, conversation_id: str | None) -> EffortResolution`
  - 메트릭 `neos_chat_effort_resolved_total{source}` — source 는 `user|conversation|feature_override|model_default|role_default|none`
  - `ChatLLMService._resolve_turn(self, model_name: str | None, conversation_id: str) -> TurnModel` — `TurnModel(model: str, provider: str, effort: str | None)`
  - 네 진입점은 kwarg `effort_resolved: str | None = None` 을 받는다 — 위임 시 두 번 해석하지 않게 (Review Focus 4)

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/services/test_chat_effort.py`

```python
import pytest

from neos.config.model_routing import ResolutionSource
from neos.services import chat_effort

pytestmark = pytest.mark.no_db

MODEL = "claude-opus-5-5"


@pytest.fixture
def levels(monkeypatch):
    monkeypatch.setattr(chat_effort, "effort_levels_for", lambda m: ("low", "medium", "high"))


def _stub_db(monkeypatch, value=None, raises=False):
    async def get_effort_for_conversation(conversation_id, model_pin):
        if raises:
            raise RuntimeError("db down")
        return value

    monkeypatch.setattr(
        chat_effort.ModelPreferenceRepository,
        "get_effort_for_conversation",
        get_effort_for_conversation,
    )


def _config(monkeypatch, models=None, everyday=None, powerful=None):
    effort = chat_effort.settings.config.model_routing.effort
    monkeypatch.setattr(effort, "models", models or {})
    monkeypatch.setattr(effort, "everyday", everyday)
    monkeypatch.setattr(effort, "powerful", powerful)


@pytest.mark.asyncio
async def test_the_user_preference_wins(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, "low")
    _config(monkeypatch, models={MODEL: "high"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert (r.effort, r.source) == ("low", ResolutionSource.USER)


@pytest.mark.asyncio
async def test_the_model_default_applies_without_a_preference(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, None)
    _config(monkeypatch, models={MODEL: "high"}, everyday="low")

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert (r.effort, r.source) == ("high", ResolutionSource.MODEL_DEFAULT)


@pytest.mark.asyncio
async def test_a_stale_stored_level_falls_through(monkeypatch, levels) -> None:
    """Review Focus 3: 저장 후 모델이 그 레벨을 잃어도 턴은 계속된다."""
    _stub_db(monkeypatch, "max")
    _config(monkeypatch, models={MODEL: "high"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert r.effort == "high"
    assert r.source is ResolutionSource.MODEL_DEFAULT


@pytest.mark.asyncio
async def test_a_db_failure_does_not_fail_the_turn(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, raises=True)
    _config(monkeypatch, models={MODEL: "medium"})

    r = await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert r.effort == "medium"


@pytest.mark.asyncio
async def test_no_conversation_no_config_sends_nothing(monkeypatch, levels) -> None:
    _stub_db(monkeypatch, "high")
    _config(monkeypatch)

    r = await chat_effort.resolve_chat_effort(MODEL, None)

    assert r.effort is None


@pytest.mark.asyncio
async def test_the_source_is_counted(monkeypatch, levels) -> None:
    from neos.observability.metrics import get_metrics_collector

    _stub_db(monkeypatch, None)
    _config(monkeypatch, models={MODEL: "high"})
    counter = get_metrics_collector().chat_effort_resolved_total
    before = counter.labels(source="model_default")._value.get()

    await chat_effort.resolve_chat_effort(MODEL, "c1")

    assert counter.labels(source="model_default")._value.get() == before + 1
```

`tests/services/test_chat_llm_effort_paths.py` — `test_chat_llm_attachment_paths.py` 의 하네스를 따른다.

```python
"""네 진입점 모두에서 effort 가 나가는 요청에 도착한다.

진입점은 이름으로 센다 -- 개수는 누가 빠졌는지 말하지 않는다.
"""

import pytest

from neos.services import chat_llm_service
from neos.services.attachment_blocks import AttachmentPlan

pytestmark = pytest.mark.no_db


async def _no_attachments(messages, *, model, owner_user_id=None):
    return AttachmentPlan(by_index={}, notices=[])


async def _owner(conversation_id):
    return "u1"


def _stub(monkeypatch, effort):
    async def fake_effort(model, conversation_id):
        from neos.config.model_routing import EffortResolution

        return EffortResolution(effort=effort)

    monkeypatch.setattr(chat_llm_service, "resolve_chat_effort", fake_effort)
    monkeypatch.setattr(chat_llm_service, "resolve_attachments", _no_attachments)
    monkeypatch.setattr(chat_llm_service, "_resolve_owner_user_id", _owner)


def _capture_create_llm(monkeypatch, captured):
    def fake_create_llm(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop-after-create")

    monkeypatch.setattr(chat_llm_service, "create_llm", fake_create_llm)


def _capture_sdk(monkeypatch, captured):
    real = chat_llm_service.normalize_anthropic_request

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        out = real(model, kwargs, thinking_enabled=thinking_enabled)
        captured.update(out)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)


async def _drain(agen):
    try:
        async for _ in agen:
            pass
    except RuntimeError:
        pass


MSGS = [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["claude-sonnet-5", "gpt-6-sol"])
async def test_generate_response_stream_passes_effort(monkeypatch, model) -> None:
    captured: dict = {}
    _stub(monkeypatch, "high")
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream(
        conversation_id="c", message_id="m", conversation_messages=MSGS, model_name=model,
    ))

    assert captured["effort"] == "high"


@pytest.mark.asyncio
async def test_generate_response_passes_effort(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "low")
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    try:
        await service.generate_response(
            conversation_id="c", message_id="m", conversation_messages=MSGS,
            model_name="claude-sonnet-5",
        )
    except RuntimeError:
        pass

    assert captured["effort"] == "low"


@pytest.mark.asyncio
async def test_tool_path_puts_effort_in_output_config(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "high")
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tools(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        tools=[], model_name="claude-sonnet-5",
    ))

    assert captured["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_tool_search_path_puts_effort_in_output_config(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "medium")
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tool_search(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        core_tools=[], search_handler=object(), model_name="claude-sonnet-5",
    ))

    assert captured["output_config"] == {"effort": "medium"}


@pytest.mark.asyncio
async def test_no_effort_means_no_key_on_the_sdk_path(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, None)
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tools(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        tools=[], model_name="claude-sonnet-5",
    ))

    assert "output_config" not in captured


@pytest.mark.asyncio
async def test_non_anthropic_tool_path_resolves_effort_once(monkeypatch) -> None:
    """Review Focus 4: 위임해도 한 번만 해석하고 값이 사라지지 않는다."""
    calls: list = []
    captured: dict = {}

    async def fake_effort(model, conversation_id):
        from neos.config.model_routing import EffortResolution

        calls.append(model)
        return EffortResolution(effort="low")

    monkeypatch.setattr(chat_llm_service, "resolve_chat_effort", fake_effort)
    monkeypatch.setattr(chat_llm_service, "resolve_attachments", _no_attachments)
    monkeypatch.setattr(chat_llm_service, "_resolve_owner_user_id", _owner)
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tools(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        tools=[], model_name="gpt-6-sol",
    ))

    assert calls == ["gpt-6-sol"]
    assert captured["effort"] == "low"
```


- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/services/test_chat_effort.py tests/services/test_chat_llm_effort_paths.py -q -p no:cacheprovider`
Expected: FAIL — `neos.services.chat_effort` 없음, `resolve_chat_effort` 속성 없음

- [ ] **Step 3: 해석기를 구현한다** — `neos/services/chat_effort.py`

```python
"""채팅 턴의 사고량(effort) 해석 -- 여기 한 곳.

DB 의 사용자 선호를 user 칸에, 설정의 모델별 기본값과 역할 기본값을 아래
칸에 넣고 기존 `resolve_effort` 사슬을 탄다. 두 번째 사슬을 만들지 않는다.

사용자 선호는 `conversation_id` 로 조인해 한 번에 읽는다 -- 소유자 조회를
따로 하면 첨부 없는 턴이 conversations 를 두 번 읽는다 (Fix round 2 Item 2).
"""

from __future__ import annotations

from neos.config.model_config import effort_levels_for
from neos.config.model_routing import EffortResolution, resolve_effort
from neos.config.settings import settings
from neos.database.repositories.model_preference_repository import (
    ModelPreferenceRepository,
)
from neos.utils.logger import get_logger

logger = get_logger(__name__)


async def resolve_chat_effort(
    model: str, conversation_id: str | None
) -> EffortResolution:
    user_effort: str | None = None
    if conversation_id and effort_levels_for(model):
        try:
            user_effort = await ModelPreferenceRepository.get_effort_for_conversation(
                conversation_id, model
            )
        except Exception as exc:  # 선호 조회 실패가 턴을 멈추지 않는다
            logger.warning(
                "effort preference lookup failed; continuing without it "
                "(error_type=%s)", type(exc).__name__,
            )

    config = settings.config.model_routing.effort
    resolution = _gate_through(model, user_effort, config)
    if resolution.effort is None and resolution.refused:
        logger.warning(
            "effort refused source=%s reason=%s detail=%s",
            resolution.source.value if resolution.source else None,
            resolution.refused,
            resolution.detail,
        )
        # 거절된 칸은 비우고 다음 칸으로 (Review Focus 3).
        resolution = _gate_through(model, None, config)

    source = resolution.source.value if resolution.effort and resolution.source else "none"
    _count(source)
    logger.info("chat effort model=%s effort=%s source=%s", model, resolution.effort, source)
    return resolution


def _gate_through(model, user_effort, config) -> EffortResolution:
    return resolve_effort(
        model=model,
        role="everyday",
        supported_levels=effort_levels_for(model),
        user_effort=user_effort,
        model_default=config.models.get(model),
        role_default=config.everyday,
    )


def _count(source: str) -> None:
    """라벨은 출처만 -- 모델 id 를 라벨에 싣지 않는다 (카디널리티)."""
    try:
        from neos.observability.metrics import get_metrics_collector

        get_metrics_collector().chat_effort_resolved_total.labels(source=source).inc()
    except Exception:
        return
```

`effort_levels_for(model)` 이 비면 DB 를 부르지 않는다 -- 어차피 게이트가 거절할 값을 읽느라 턴마다 쿼리를 치르지 않는다 (Gemini·레거시·레벨 미선언 모델).

`neos/observability/metrics.py` 의 `catalog_resolve_total` 정의 아래에 더한다.

```python
        # Chat effort source per turn. Label is the source only, never a model id.
        self.chat_effort_resolved_total = Counter(
            "neos_chat_effort_resolved_total",
            "Chat turns by where their effort came from",
            ["source"],
            registry=self.registry,
        )
```



- [ ] **Step 4: 네 진입점을 배선한다** — `neos/services/chat_llm_service.py`

상단 import 에 더한다.

```python
from dataclasses import dataclass

from neos.providers.effort import effort_request_fields
from neos.services.chat_effort import resolve_chat_effort
```

클래스 밖에 둔다.

```python
@dataclass(frozen=True, slots=True)
class TurnModel:
    model: str
    provider: str
    effort: str | None
```

`ChatLLMService` 에 메서드를 더한다.

```python
    async def _resolve_turn(
        self,
        model_name: str | None,
        conversation_id: str,
        *,
        effort_resolved: str | None = None,
        effort_known: bool = False,
    ) -> TurnModel:
        """모델 · 프로바이더 · effort 를 한 번에. 네 진입점이 모두 이것을 부른다."""
        model = resolve_conversation_chat_model(model_name)
        provider = self._extract_provider_from_model(model)
        if effort_known:
            return TurnModel(model, provider, effort_resolved)
        # 소유자 조회를 부르지 않는다 -- 선호 조회가 conversation_id 로 조인한다.
        resolution = await resolve_chat_effort(model, conversation_id)
        return TurnModel(model, provider, resolution.effort)
```

각 진입점에서:
1. 시그니처에 `effort_resolved: str | None = None, effort_known: bool = False,` 를 더한다.
2. `model = resolve_conversation_chat_model(model_name)` 과 `provider = self._extract_provider_from_model(model)` 두 줄을 다음으로 바꾼다.

```python
        turn = await self._resolve_turn(
            model_name, conversation_id,
            effort_resolved=effort_resolved, effort_known=effort_known,
        )
        model, provider = turn.model, turn.provider
```

3. `generate_response` · `generate_response_stream` 의 `llm_params` 에 `if turn.effort is not None: llm_params["effort"] = turn.effort` 를 더한다.
4. 두 tool 경로의 비-Anthropic 위임(`async for event in self.generate_response_stream(...)`)에 `effort_resolved=turn.effort, effort_known=True,` 를 더한다.
5. 두 tool 경로의 `stream_kwargs = normalize_anthropic_request(model, {...}, thinking_enabled=True)` 에서 dict 리터럴에 `**effort_request_fields(provider, turn.effort),` 를 더한다 (normalize 전에 들어가야 한다 — 번역이 명시적 effort 를 보도록).

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/services -q -p no:cacheprovider`
Expected: PASS. 특히 `test_chat_llm_owner_lazy_resolution.py` 의 "첨부 없으면 conversation 조회를 건너뛴다" 테스트 넷이 **수정 없이** 초록이어야 한다 — 그 테스트를 고쳐서 초록으로 만들면 Global Constraint 위반이다. 기존 테스트가 실제 `db_manager` 에 닿아 느려지거나 실패하면, 그 파일들에 `resolve_chat_effort` 를 `EffortResolution(effort=None)` 을 돌려주는 가짜로 바꾸는 픽스처만 더한다 (단언은 건드리지 않는다).

- [ ] **Step 6: 커밋한다**

```bash
git add neos/services/chat_effort.py neos/services/chat_llm_service.py neos/observability/metrics.py tests/services/test_chat_effort.py tests/services/test_chat_llm_effort_paths.py tests/services/test_chat_llm_attachment_paths.py
git commit -m "feat(effort): resolve effort per chat turn in one place and carry it through all four entry points"
```

---

### Task 7: 선호 API

**Files:**
- Create: `neos/api/handlers/model_preference_handlers.py`
- Modify: `neos/main.py` (import 와 `_include_router_for_runtime` 한 줄 — `autonomy_router` 옆 `:39`, `:615`)
- Test: `tests/api/test_model_preference_api.py` (생성)

**Interfaces:**
- Consumes: `ModelPreferenceRepository` (Task 5), `canonicalize` (`neos/config/model_identity.py`), `effort_levels_for` (Task 2), `get_current_user`
- Produces (prefix `/users/me/model-preferences`, `settings.API_V1_PREFIX` 아래):
  - `GET ""` → `list[ModelPreferenceOut]` — `{model: str, effort: str, updated_at: datetime}`
  - `PUT "/{model:path}"` body `{effort: str}` → `ModelPreferenceOut`
  - `DELETE "/{model:path}"` → 204

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/api/test_model_preference_api.py`

```python
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.model_preference_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.database.repositories.model_preference_repository import ModelPreference

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class FakeRepo:
    def __init__(self):
        self.rows: dict[tuple[str, str], str] = {}

    async def list_for_user(self, user_id):
        return [ModelPreference(m, e, NOW) for (u, m), e in self.rows.items() if u == user_id]

    async def upsert_effort(self, user_id, model_pin, effort):
        self.rows[(user_id, model_pin)] = effort
        return ModelPreference(model_pin, effort, NOW)

    async def delete(self, user_id, model_pin):
        return self.rows.pop((user_id, model_pin), None) is not None


@pytest.fixture
def client(monkeypatch):
    repo = FakeRepo()
    for name in ("list_for_user", "upsert_effort", "delete"):
        monkeypatch.setattr(mod.ModelPreferenceRepository, name, getattr(repo, name))
    monkeypatch.setattr(
        mod, "effort_levels_for",
        lambda m: ("low", "high") if m in {"claude-opus-5-5", "gpt-6-sol"} else (),
    )
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="u1")
    return TestClient(app), repo


def test_put_then_get(client) -> None:
    http, _ = client
    assert http.put("/users/me/model-preferences/claude-opus-5-5", json={"effort": "high"}).status_code == 200
    body = http.get("/users/me/model-preferences").json()
    assert [(r["model"], r["effort"]) for r in body] == [("claude-opus-5-5", "high")]


def test_put_by_gateway_id_stores_the_pin(client) -> None:
    """Review Focus 1: 경로에 `/` 가 있어도 404 가 아니다."""
    http, repo = client
    r = http.put("/users/me/model-preferences/anthropic/claude-opus-5.5", json={"effort": "low"})
    assert r.status_code == 200
    assert repo.rows == {("u1", "claude-opus-5-5"): "low"}


def test_put_by_retired_pin_stores_the_successor(client) -> None:
    """Review Focus 2."""
    http, repo = client
    r = http.put("/users/me/model-preferences/claude-opus-5", json={"effort": "high"})
    assert r.status_code == 200
    assert repo.rows == {("u1", "claude-opus-5-5"): "high"}


def test_unknown_model_is_404(client) -> None:
    http, _ = client
    assert http.put("/users/me/model-preferences/claude-nope", json={"effort": "low"}).status_code == 404


def test_unsupported_level_is_422_with_the_allowed_list(client) -> None:
    http, repo = client
    r = http.put("/users/me/model-preferences/claude-opus-5-5", json={"effort": "max"})
    assert r.status_code == 422
    assert r.json()["detail"]["allowed"] == ["low", "high"]
    assert repo.rows == {}


def test_model_without_levels_is_422(client) -> None:
    http, _ = client
    r = http.put("/users/me/model-preferences/claude-sonnet-5", json={"effort": "low"})
    assert r.status_code == 422


def test_delete_returns_to_default(client) -> None:
    http, repo = client
    http.put("/users/me/model-preferences/gpt-6-sol", json={"effort": "low"})
    assert http.delete("/users/me/model-preferences/gpt-6-sol").status_code == 204
    assert repo.rows == {}


def test_unauthenticated_is_rejected() -> None:
    app = FastAPI()
    app.include_router(mod.router)
    assert TestClient(app).get("/users/me/model-preferences").status_code in {401, 403}


def test_router_is_registered() -> None:
    from neos.main import app

    paths = {route.path for route in app.routes}
    assert any(p.endswith("/users/me/model-preferences") for p in paths)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/api/test_model_preference_api.py -q -p no:cacheprovider`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현한다** — `neos/api/handlers/model_preference_handlers.py`

```python
"""사용자 × 모델 선호 API (effort). 설계: docs/MODEL_EFFORT_PREFERENCES_DESIGN.md §6."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.config.model_config import effort_levels_for, model_config
from neos.config.model_identity import canonicalize
from neos.database.models import User
from neos.database.repositories.model_preference_repository import (
    ModelPreferenceRepository,
)

router = APIRouter(prefix="/users/me/model-preferences", tags=["Model Preferences"])


class ModelPreferenceOut(BaseModel):
    model: str
    effort: str
    updated_at: datetime


class EffortIn(BaseModel):
    effort: str


def _pin(raw: str) -> str:
    """gateway id · 은퇴한 핀 · 별칭을 카탈로그 핀으로. 모르면 404."""
    ident = canonicalize(raw, catalog=model_config.catalog, apply_remap=True)
    if ident is None:
        raise HTTPException(status_code=404, detail=f"unknown model {raw!r}")
    return ident.catalog_id


@router.get("", response_model=list[ModelPreferenceOut])
async def list_model_preferences(
    current_user: User = Depends(get_current_user),
) -> list[ModelPreferenceOut]:
    rows = await ModelPreferenceRepository.list_for_user(current_user.user_id)
    return [ModelPreferenceOut(model=r.model_pin, effort=r.effort, updated_at=r.updated_at) for r in rows]


@router.put("/{model:path}", response_model=ModelPreferenceOut)
async def put_model_preference(
    model: str,
    body: EffortIn,
    current_user: User = Depends(get_current_user),
) -> ModelPreferenceOut:
    pin = _pin(model)
    allowed = list(effort_levels_for(pin))
    if body.effort not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": f"{pin} does not take {body.effort!r}", "allowed": allowed},
        )
    row = await ModelPreferenceRepository.upsert_effort(current_user.user_id, pin, body.effort)
    return ModelPreferenceOut(model=row.model_pin, effort=row.effort, updated_at=row.updated_at)


@router.delete("/{model:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_preference(
    model: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    await ModelPreferenceRepository.delete(current_user.user_id, _pin(model))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

`neos/main.py` — `autonomy_router` import 아래와 include 아래에 한 줄씩:

```python
from neos.api.handlers.model_preference_handlers import router as model_preference_router
```

```python
_include_router_for_runtime(model_preference_router, prefix=settings.API_V1_PREFIX, tags=["Model Preferences"])
```

⚠️ `canonicalize` 는 `retired:` 를 `apply_remap` 과 무관하게 적용한다 (커밋 `b9b72752`). `test_put_by_retired_pin_stores_the_successor` 가 그것을 고정한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/api/test_model_preference_api.py tests/api -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/api/handlers/model_preference_handlers.py neos/main.py tests/api/test_model_preference_api.py
git commit -m "feat(effort): model preference API, normalizing gateway ids and retired pins"
```

---

### Task 8: 피커 페이로드에 effort 필드

**Files:**
- Modify: `neos/config/model_identity.py:119-130` (`PickerModel`), `:272-360` (`to_picker_payload`, `_picker_row`)
- Modify: `neos/api/models/catalog_models.py` (`CatalogModelOut`)
- Modify: `scripts/generate_catalog_fallback.py` (행과 타입)
- Modify: `web/lib/ai/models.ts` (`CatalogModelOut` 타입), regenerate `web/lib/ai/catalog.generated.ts`
- Test: `tests/config/test_model_identity.py`, `tests/api/test_catalog_api.py`, `web/tests/source/ai-models.test.ts`

**Interfaces:**
- Consumes: 카탈로그 `effort_levels` (Task 2), `ModelRoutingConfig.effort.models` (Task 3)
- Produces: `PickerModel.effort_levels: tuple[str, ...]`, `PickerModel.effort_default: str | None`; TS `CatalogModelOut.effort_levels: string[]`, `effort_default: string | null`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/config/test_model_identity.py` 끝에:

```python
def test_picker_rows_carry_effort_levels_and_the_model_default() -> None:
    from neos.config.model_config import effort_levels_for

    routing = ModelRoutingConfig()
    pin = next(
        name for name in ("claude-opus-5-5", "gpt-6-sol") if effort_levels_for(name)
    )
    level = effort_levels_for(pin)[0]
    routing.effort.models = {pin: level}

    payload = to_picker_payload(model_config.catalog, routing)
    row = next(r for r in payload.models if r.catalog_id == pin)

    assert row.effort_levels == effort_levels_for(pin)
    assert row.effort_default == level
    others = [r for r in payload.models if r.catalog_id != pin]
    assert all(r.effort_default is None for r in others)
```

`tests/api/test_catalog_api.py` 의 `test_flag_on_returns_seven_picker_rows_and_gateway_remaps` 끝에:

```python
    assert all("effort_levels" in row and "effort_default" in row for row in payload["models"])
```

`web/tests/source/ai-models.test.ts` 에 (파일의 기존 import 를 따른다):

```ts
test("generated rows carry effort fields", () => {
  for (const row of generatedModels) {
    assert.ok(Array.isArray(row.effort_levels));
    assert.ok(row.effort_default === null || typeof row.effort_default === "string");
  }
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/config/test_model_identity.py tests/api/test_catalog_api.py -q -p no:cacheprovider`
Expected: FAIL — `PickerModel` 에 `effort_levels` 없음

- [ ] **Step 3: 구현한다**

`PickerModel` 에 필드 두 개를 끝에 더한다.

```python
    effort_levels: tuple[str, ...] = ()
    effort_default: str | None = None
```

`_picker_row` 에 `effort_default: str | None` 인자를 더하고 `PickerModel(...)` 에 `effort_levels=tuple(spec.effort_levels), effort_default=effort_default,` 를 넘긴다. `to_picker_payload` 의 두 `_picker_row(...)` 호출에 `effort_default=routing.effort.models.get(name),` 를 더한다.

`CatalogModelOut` 에:

```python
    effort_levels: list[str] = []
    effort_default: str | None = None
```

`scripts/generate_catalog_fallback.py` — 행 블록의 `default:` 줄 다음에:

```python
            f"    effort_levels: {json.dumps(list(row.effort_levels))},\n"
            f"    effort_default: {'null' if row.effort_default is None else _ts_string(row.effort_default)},\n"
```

타입 블록의 `"  default: boolean;\n"` 다음에:

```python
        "  effort_levels: string[];\n"
        "  effort_default: string | null;\n"
```

`web/lib/ai/models.ts` 의 `CatalogModelOut` 에 `effort_levels: string[]; effort_default: string | null;` 을 더한다.

- [ ] **Step 4: 재생성하고 통과를 확인한다**

Run: `python scripts/generate_catalog_fallback.py && python -m pytest tests/config tests/api -q -p no:cacheprovider && (cd web && pnpm test:source)`
Expected: 전부 PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/config/model_identity.py neos/api/models/catalog_models.py scripts/generate_catalog_fallback.py web/lib/ai/models.ts web/lib/ai/catalog.generated.ts tests/config/test_model_identity.py tests/api/test_catalog_api.py web/tests/source/ai-models.test.ts
git commit -m "feat(effort): picker rows carry each model's effort levels and configured default"
```

---

### Task 9: 프론트엔드 — 프록시, 훅, 선택기

**Files:**
- Create: `web/lib/ai/effort.ts` (순수 로직)
- Create: `web/app/(chat)/api/model-preferences/route.ts`, `web/app/(chat)/api/model-preferences/[...model]/route.ts`
- Create: `web/hooks/use-model-effort.ts`, `web/components/effort-selector.tsx`
- Modify: `web/components/multimodal-input.tsx:378-382`
- Test: `web/tests/source/model-effort.test.ts` (생성)

**Interfaces:**
- Consumes: TS `CatalogModelOut.effort_levels`, `effort_default` (Task 8); 백엔드 API (Task 7)
- Produces:
  - `effortOptions(model: CatalogModelOut): EffortOption[]` — `EffortOption = { value: string | null; label: string }`, 첫 항목은 `{ value: null, label: "Default (x)" }` 또는 `"Default"`
  - `shouldShowEffort(model: CatalogModelOut | undefined): boolean`
  - `effortRequest(modelCatalogId: string, effort: string | null): { url: string; init: RequestInit }` — null 이면 DELETE
  - `useModelEffort(): { efforts: Record<string, string>; setEffort(catalogId: string, effort: string | null): Promise<void> }`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/model-effort.test.ts`

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { effortOptions, effortRequest, shouldShowEffort } from "@/lib/ai/effort";
import type { CatalogModelOut } from "@/lib/ai/models";

const base: CatalogModelOut = {
  id: "anthropic/claude-opus-5.5",
  catalog_id: "claude-opus-5-5",
  name: "Claude Opus 5.5",
  provider: "anthropic",
  description: "",
  thinking: "adaptive",
  vision: true,
  role_alias: null,
  default: false,
  effort_levels: ["low", "medium", "high"],
  effort_default: "high",
};

test("a model without levels hides the selector", () => {
  // Review Focus 5
  assert.equal(shouldShowEffort({ ...base, effort_levels: [] }), false);
  assert.equal(shouldShowEffort(undefined), false);
  assert.equal(shouldShowEffort(base), true);
});

test("options start with the default and keep API labels", () => {
  assert.deepEqual(effortOptions(base), [
    { value: null, label: "Default (high)" },
    { value: "low", label: "low" },
    { value: "medium", label: "medium" },
    { value: "high", label: "high" },
  ]);
  assert.equal(effortOptions({ ...base, effort_default: null })[0].label, "Default");
});

test("choosing default deletes, choosing a level puts", () => {
  const del = effortRequest("claude-opus-5-5", null);
  assert.equal(del.url, "/api/model-preferences/claude-opus-5-5");
  assert.equal(del.init.method, "DELETE");

  const put = effortRequest("claude-opus-5-5", "low");
  assert.equal(put.init.method, "PUT");
  assert.equal(put.init.body, JSON.stringify({ effort: "low" }));
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/model-effort.test.ts`
Expected: FAIL — `Cannot find module '@/lib/ai/effort'`

- [ ] **Step 3: 순수 로직을 구현한다** — `web/lib/ai/effort.ts`

```ts
import type { CatalogModelOut } from "./models";

export type EffortOption = { value: string | null; label: string };

/** 레벨을 선언하지 않은 모델(Gemini·레거시)은 선택기를 숨긴다. */
export function shouldShowEffort(model: CatalogModelOut | undefined): boolean {
  return Boolean(model && model.effort_levels && model.effort_levels.length > 0);
}

/** 라벨은 API 어휘를 그대로 쓴다 — 번역층은 드리프트의 새 원천이다. */
export function effortOptions(model: CatalogModelOut): EffortOption[] {
  const head: EffortOption = {
    value: null,
    label: model.effort_default ? `Default (${model.effort_default})` : "Default",
  };
  return [head, ...model.effort_levels.map((level) => ({ value: level, label: level }))];
}

export function effortRequest(
  catalogId: string,
  effort: string | null
): { url: string; init: RequestInit } {
  const url = `/api/model-preferences/${catalogId}`;
  if (effort === null) {
    return { url, init: { method: "DELETE" } };
  }
  return {
    url,
    init: {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ effort }),
    },
  };
}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/model-effort.test.ts`
Expected: PASS

- [ ] **Step 5: 프록시를 만든다** — `web/app/(chat)/api/model-preferences/route.ts` (`autonomy-preference` 패턴)

```ts
import { NextResponse } from "next/server";
import { callBackendAPI } from "@/lib/backend-api";

export async function GET() {
  try {
    const response = await callBackendAPI("/api/v1/users/me/model-preferences");
    if (!response.ok) {
      return NextResponse.json([], { status: 200 });
    }
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json([], { status: 200 });
  }
}
```

`web/app/(chat)/api/model-preferences/[...model]/route.ts`

```ts
import { NextResponse } from "next/server";
import { callBackendAPI } from "@/lib/backend-api";

type Params = { params: Promise<{ model: string[] }> };

async function forward(method: "PUT" | "DELETE", params: Params["params"], body?: string) {
  const { model } = await params;
  const path = model.map(encodeURIComponent).join("/");
  try {
    const response = await callBackendAPI(
      `/api/v1/users/me/model-preferences/${path}`,
      { method, body }
    );
    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ error: "Update failed" }, { status: 502 });
  }
}

export async function PUT(request: Request, { params }: Params) {
  return forward("PUT", params, await request.text());
}

export async function DELETE(_request: Request, { params }: Params) {
  return forward("DELETE", params);
}
```

(`params` 는 Promise 다 — `web/app/(chat)/api/deep-analysis/[runId]/events/route.ts:49` 와 같은 형태.)

- [ ] **Step 6: 훅과 선택기를 만든다** — `web/hooks/use-model-effort.ts`

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { effortRequest } from "@/lib/ai/effort";

type Row = { model: string; effort: string };

export function useModelEffort() {
  const [efforts, setEfforts] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch("/api/model-preferences")
      .then((r) => r.json())
      .then((rows: Row[]) => {
        if (Array.isArray(rows)) {
          setEfforts(Object.fromEntries(rows.map((row) => [row.model, row.effort])));
        }
      })
      .catch(() => {
        // 선호를 못 읽으면 모든 모델이 기본값으로 보인다. 채팅은 영향 없다.
      });
  }, []);

  const setEffort = useCallback(async (catalogId: string, effort: string | null) => {
    const previous = efforts;
    const next = { ...efforts };
    if (effort === null) {
      delete next[catalogId];
    } else {
      next[catalogId] = effort;
    }
    setEfforts(next);
    const { url, init } = effortRequest(catalogId, effort);
    const response = await fetch(url, init).catch(() => null);
    if (!response || !response.ok) {
      setEfforts(previous);
      toast.error("Failed to save effort setting");
    }
  }, [efforts]);

  return { efforts, setEffort };
}
```

`web/components/effort-selector.tsx` — 네이티브 `<select>` 로 시작한다 (첫 판은 동작이 목적이다; 스타일 통일은 별도 작업).

```tsx
"use client";

import { memo } from "react";
import { effortOptions, shouldShowEffort } from "@/lib/ai/effort";
import type { CatalogModelOut } from "@/lib/ai/models";
import { useModelEffort } from "@/hooks/use-model-effort";

function PureEffortSelector({ model }: { model: CatalogModelOut | undefined }) {
  const { efforts, setEffort } = useModelEffort();
  if (!model || !shouldShowEffort(model)) {
    return null;
  }
  const current = efforts[model.catalog_id] ?? null;
  return (
    <select
      aria-label="Effort"
      className="h-8 rounded-md bg-transparent px-2 text-xs"
      data-testid="effort-selector"
      onChange={(event) => {
        const value = event.target.value;
        void setEffort(model.catalog_id, value === "" ? null : value);
      }}
      value={current ?? ""}
    >
      {effortOptions(model).map((option) => (
        <option key={option.value ?? "default"} value={option.value ?? ""}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export const EffortSelector = memo(PureEffortSelector);
```

`web/components/multimodal-input.tsx` — `<ModelSelectorCompact …/>` 다음에:

```tsx
            <EffortSelector
              model={
                catalog.models.find((m) => m.id === selectedModelId) ??
                catalog.models.find((m) => m.id === catalog.default_id)
              }
            />
```

(import: `import { EffortSelector } from "./effort-selector";`)

- [ ] **Step 7: 타입과 전체 테스트를 확인한다**

Run: `cd web && pnpm exec tsc --noEmit -p . && pnpm test:source`
Expected: 타입 오류 없음, 전부 PASS

- [ ] **Step 8: 커밋한다**

```bash
git add web/lib/ai/effort.ts "web/app/(chat)/api/model-preferences" web/hooks/use-model-effort.ts web/components/effort-selector.tsx web/components/multimodal-input.tsx web/tests/source/model-effort.test.ts
git commit -m "feat(web): effort selector next to the model picker, saved per model through the backend"
```

---

### Task 10: 기본값 설정, 운영 문서, 실호출 확인

**Files:**
- Modify: `config/neos.default.yaml` (`model_routing.effort.models`)
- Modify: `docs/CONFIGURATION.md` (Model Routing 절)
- Test: `tests/config/test_config_files.py` (기존 — 설정 파일이 검증을 통과하는지)

**Interfaces:**
- Consumes: 전 작업

- [ ] **Step 1: 기본값을 정한다** — 이 값은 **정책**이고 표본 경계다. 넣을지와 값은 사람이 정한다. 사람의 답을 받기 전에는 블록을 주석 예시로만 둔다.

```yaml
model_routing:
  effort:
    # 모델별 사고량 기본값 {카탈로그 핀: 레벨}. 사용자 설정(DB)이 이긴다.
    # 키와 레벨은 부팅 때 카탈로그 effort_levels 와 맞대 본다 -- 오타는 부팅 실패.
    # 값을 바꾸는 것은 심층분석 표본 경계다 (로드맵 §경계 10).
    models: {}
    #   claude-opus-5-5: high
    #   gpt-6-sol: medium
```

(`config/neos.default.yaml` 에 `model_routing:` 블록이 없으면 새로 만든다 — 먼저 `grep -n "model_routing" config/neos.default.yaml` 로 확인한다.)

- [ ] **Step 2: 운영 문서를 쓴다** — `docs/CONFIGURATION.md` 의 `### Model Routing` 절 끝에 영어로:

```markdown
#### Effort (per model and per user)

Effort is the provider's thinking-depth parameter — Anthropic
`output_config.effort`, OpenAI `reasoning_effort`. It is not deep analysis
`Effort` (scout/dig/synth).

- **Which levels a model takes** is a catalog fact: `effort_levels` in
  `neos/config/models.yaml`, checked against each provider's SDK vocabulary.
  Empty means unknown, and nothing is sent.
- **Per-model defaults** are policy: `model_routing.effort.models`
  (`{pin: level}`). An unknown pin or a level the model does not take fails
  boot.
- **User choice** lives in `user_model_preferences` (migration 063), set via
  `PUT /api/v1/users/me/model-preferences/{model}` and the selector next to
  the chat picker. `{model}` accepts gateway ids and retired pins; they are
  stored as the canonical pin.

Precedence per chat turn: user × model → conversation → feature override →
model default → role default → nothing sent. Resolution happens once, in
`neos/services/chat_effort.py`; translation to request fields happens once,
in `neos/providers/effort.py`. A stored level the model no longer takes is
refused with a warning and the next rung applies. A failed preference lookup
never fails the turn.

On `thinking_always_on` models, a "thinking off" request becomes
`effort: low` when the model declares `low`, unless an explicit effort was
already resolved.

OpenAI `reasoning_effort` has not been verified live (the OpenAI key returned
401 when this shipped). Check that `temperature` is accepted alongside a
non-`none` effort before relying on it.
```

- [ ] **Step 3: Anthropic 실호출로 확인한다**

```bash
python - <<'EOF'
import anthropic
c = anthropic.Anthropic()
for model in ("claude-sonnet-5", "claude-opus-5-5"):
    r = c.messages.create(
        model=model, max_tokens=64,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": "Say ok."}],
    )
    print(model, r.stop_reason)
EOF
```

Expected: 두 줄, `end_turn`. 400 이면 그 모델의 `effort_levels` 를 다시 재고 Task 2 로 돌아간다.

- [ ] **Step 4: 전체 확인**

Run: `python -m pytest tests/config tests/db tests/database tests/services tests/api tests/providers tests/utils tests/workflow tests/coding tests/dataset tests/test_cost_calculator.py -q -p no:cacheprovider && (cd web && pnpm test:source) && ruff check neos scripts`
Expected: 전부 PASS

- [ ] **Step 5: 커밋한다**

```bash
git add config/neos.default.yaml docs/CONFIGURATION.md
git commit -m "docs(effort): per-model defaults block and the operator guide for effort"
```
