# 모델 카탈로그 config화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude·GPT 등 모델에 관한 사실(목록 노출, 추천 티어, thinking 요청 계약, 가격)을 `neos/config/models.yaml` 한 곳에서 관리해, 새 모델 추가가 config 편집만으로 끝나게 한다.

**Architecture:** `neos/config/model_config.py`를 Pydantic 검증 카탈로그 로더로 진화시킨다. 파이썬에 흩어진 하드코딩 4곳(`AnthropicProvider.list_models`, `OpenAIProvider.list_models`, `get_recommended_models`, `CostCalculator.DEFAULT_PRICING`)과 `is_claude_5`가 모두 카탈로그의 파생 뷰가 된다. 로더는 파일만 읽고 DB를 요구하지 않는다. 카탈로그는 allowlist가 아니라 기본값의 원천이므로, 미등록 모델은 통과시키고 경고만 낸다.

**Tech Stack:** Python 3.12, Pydantic v2 (`StrictConfigModel`, `extra="forbid"`), PyYAML, pytest + pytest-asyncio (session-scoped loop, `asyncio_mode=auto`)

## Global Constraints

- 카탈로그 파일은 `neos/config/models.yaml` 하나. 새 config 파일을 만들지 않는다.
- 로더 진입점은 `neos/config/model_config.py` 하나. 새 모듈을 만들지 않는다 (spec §7).
- 로더는 **DB를 요구하지 않는다.** 모든 카탈로그 테스트는 `pytest.mark.no_db`로 표시한다.
- **배포 정책은 이전하지 않는다.** `model_routing`(provider × role)과 기능 오버라이드(`coding_model.model`, `deep_analysis.models.*`, `knowledge_graph.extraction.model`, `context_optimization.tool_result_summarization_model` 등)는 `config/neos.*.yaml`에 그대로 둔다.
- **가격 우선순위 불변:** `llm_model_pricing` DB → `models.yaml` `pricing` → 경고 + `None`.
- **카탈로그는 allowlist가 아니다.** 미등록 모델은 통과시키고 경고만 낸다. 예외를 던지지 않는다.
- 미등록 모델의 thinking 계약 기본값은 `budgeted` (현행 동작 보존).
- `is_claude_5`는 **삭제한다.** 하위 호환 shim을 남기지 않는다.
- `list_models()` 파생은 **Anthropic·OpenAI에만** 적용한다. Gemini는 정적 목록 유지, Ollama는 라이브 서버 조회 유지. 두 provider의 `tiers`만 카탈로그로 옮긴다.
- `list_models()` 반환 순서는 카탈로그 선언 순서를 따르며, **현재 순서와 정확히 같아야** 한다.
- 역할 기본값은 정확히 유지: anthropic `everyday=claude-sonnet-5` / `powerful=claude-opus-5`, openai `everyday=gpt-5.6-terra` / `powerful=gpt-5.6-sol`.
- 테스트는 실제 프로바이더 자격증명을 요구하지 않는다.
- 기존 전체 테스트 2112 passed를 유지한다.

---

## 스펙 대비 2건의 의도적 편차

구현 준비 중 스펙의 두 결정이 현재 코드와 충돌하는 것을 확인했다. 근거와 함께 수정한다.

### 편차 1: `tier: <scalar>` → `tiers: [<tier>, ...]` (리스트)

스펙 §3은 모델당 `tier` 스칼라 하나를 둔다. 그런데 현재 `get_recommended_models()`는 **한 모델을 두 티어에 매핑**한다:

```python
"gemini": {"fast": "gemini-2.0-flash-exp",
           "balanced": "gemini-1.5-pro-latest",
           "powerful": "gemini-1.5-pro-latest"},   # ← balanced == powerful
"ollama": {"fast": "llama3.1:8b",
           "balanced": "llama3.1:8b",              # ← fast == balanced
           "powerful": "llama3.1:70b"},
```

스칼라 `tier`로는 이 값을 전사할 수 없다. `neos/cli.py:1653`이 `get_recommended_models(provider)`를 표시용으로 소비하므로, gemini의 `powerful`을 조용히 잃으면 CLI 출력이 실제로 퇴화한다.

따라서 `tiers: list[Tier]` (기본값 `[]`)로 둔다. 부수 이득: "(provider, tier) 쌍은 최대 1개 모델" 검증기를 붙일 수 있어, 새 모델을 추가하며 옛 모델의 티어를 지우는 것을 잊으면 **로딩 시점에** 잡힌다. 스칼라 `tier`로는 두 모델이 같은 티어를 조용히 주장할 수 있었다.

### 편차 2: 기동 시 미등록 경고 범위를 `model_routing`으로 한정

스펙 §6은 "`model_routing`이나 기능 오버라이드가 카탈로그에 없는 이름을 가리키면 기동 시 경고"라고 한다. `neos/config/schema.py`에는 모델 이름을 담는 필드가 20개 이상 있고, 그중 여럿은 **의도적으로 카탈로그 범위 밖**이다:

| 필드 | 값 | 카탈로그 밖인 이유 |
|---|---|---|
| `context_optimization.token_counter_model` | `gpt-4` | 토크나이저 식별자, 호출 대상 모델이 아님 |
| `embedding.model` | `gemini-embedding-2-flash` | 임베딩 모델 (spec §2 범위 밖) |
| `reranker.model` | `rerank-english-v3.0` | 리랭커, LLM 아님 |

전 필드를 검사하면 기동마다 거짓 경고 3건 이상이 나온다. 반면 **기능 오버라이드는 이미 덮인다** — 오버라이드를 설정하면 그 값이 `create_llm(model=...)`로 전달되고, 그 경로에 모델별 1회 경고가 붙는다 (Task 6). 그래서 기동 검사는 `model_routing`의 4개 역할 기본값에만 적용한다. 이 4개는 `create_llm`이 `model=`을 생략한 경로에서만 쓰여 사용 시점 경고가 늦게 도달하므로, 기동 검사의 값이 실제로 있는 유일한 자리다.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `neos/config/models.yaml` | 모델 사실의 단일 원천 | 새 형태로 재작성 (Task 2) |
| `neos/config/model_config.py` | 카탈로그 스키마 + 로더 + 파생 조회 API. 유일한 진입점 | 재작성 (Task 1), 기동 경고 추가 (Task 6) |
| `neos/providers/anthropic.py` | thinking 계약 적용, 목록 파생 | Task 3, 4 |
| `neos/providers/openai.py` | 목록 파생 | Task 4 |
| `neos/utils/llm_factory.py` | `get_recommended_models` 파생, 미등록 경고 | Task 4, 6 |
| `neos/utils/cost_calculator.py` | 가격 파생 | Task 5 |
| `neos/config/model_routing.py` | 순수 리졸버로 환원 (`is_claude_5` 삭제) | Task 3 |
| `neos/main.py` | 기동 시 미등록 경고 호출 | Task 6 |
| `docs/CONFIGURATION.md` | 카탈로그 절 추가 | Task 6 |
| `tests/config/test_model_catalog.py` | 스키마·로더·하위 호환 (신규) | Task 1 |
| `tests/config/test_model_catalog_parity.py` | 이관 정합성 안전망 (신규) | Task 2 |
| `tests/config/test_model_routing.py` | `is_claude_5` 테스트 제거 | Task 3 |
| `tests/providers/test_current_model_providers.py` | 파생 단언으로 전환 | Task 3, 4 |
| `tests/test_cost_calculator.py` | `DEFAULT_PRICING` 직접 접근 제거 | Task 5 |

`model_config.py`는 재작성 후 약 380줄이며 책임은 하나다(모델 카탈로그). 스키마를 별 모듈로 쪼개지 않는 이유는 Global Constraints의 단일 진입점 제약이다.

---

## Task 1: 카탈로그 스키마 + 로더

`model_config.py`를 Pydantic 카탈로그 로더로 재작성한다. **소비자는 아무것도 바꾸지 않는다.** 이 시점에 `models.yaml`은 아직 옛 형태이므로, 옛 형태 자동 변환 경로가 전 코드를 지탱한다.

**Files:**
- Modify: `neos/config/model_config.py` (전체 재작성, 현재 228줄)
- Test: `tests/config/test_model_catalog.py` (신규)

**Interfaces:**
- Consumes: `neos.config.schema.StrictConfigModel` (`extra="forbid"`, `validate_assignment=True`)
- Produces:
  - `class ThinkingContract(str, Enum)`: `ADAPTIVE="adaptive"`, `BUDGETED="budgeted"`, `NONE="none"`
  - `Tier = Literal["fast", "balanced", "powerful"]`
  - `CatalogProvider = Literal["anthropic", "openai", "gemini", "ollama"]`
  - `class ModelPricing(StrictConfigModel)`: `input: float`, `output: float`, `cache_creation: float = 0.0`, `cache_read: float = 0.0`
  - `class ModelSpec(StrictConfigModel)`: `provider: CatalogProvider`, `tiers: list[Tier] = []`, `thinking: ThinkingContract = BUDGETED`, `selectable: bool = True`, `max_tokens: int | None = None`, `description: str | None = None`, `supports_video: bool = False`, `dimension: int | None = None`, `pricing: ModelPricing | None = None`
  - `class ModelCatalog(StrictConfigModel)`: `models: dict[str, ModelSpec] = {}`, `aliases: dict[str, dict[str, str]] = {}`, `defaults: dict[str, str] = {}` (모두 기본값 있음 — 파일 누락 시 `ModelCatalog()`로 빈 카탈로그를 만든다)
  - `def load_catalog(path: Path) -> ModelCatalog` — 순수 함수, 옛 형태 자동 변환 포함
  - `def get_model_spec(model: str) -> ModelSpec | None`
  - `def models_for_provider(provider: str) -> list[str]` — `selectable`만, 선언 순서 유지
  - `def tiers_for_provider(provider: str) -> dict[str, str]` — `{tier: model}`, `fast`→`balanced`→`powerful` 순
  - `def thinking_contract(model: str) -> ThinkingContract` — 미등록은 `BUDGETED`
  - `def pricing_for(provider: str, model: str) -> ModelPricing | None`
  - 레거시 유지: `model_config` 싱글톤, `get_vision_model_id`, `get_llm_model_id`, `get_embedding_model_id`, `ModelConfig.get_vision_model` / `get_llm_model` / `get_embedding_model` / `list_*_models` / `get_default_*_model` / `reload`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/config/test_model_catalog.py`를 새로 만든다:

```python
"""모델 카탈로그 스키마와 로더 테스트.

로더는 파일만 읽는다 — DB를 요구하지 않는다 (spec §7).
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from neos.config.model_config import (
    ModelCatalog,
    ThinkingContract,
    load_catalog,
)

pytestmark = pytest.mark.no_db


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_catalog_rejects_unknown_model_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "capabilities": ["vision"]}}},
    )

    with pytest.raises(ValidationError, match="capabilities"):
        load_catalog(path)


def test_catalog_rejects_unknown_thinking_value(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "thinking": "extended"}}},
    )

    with pytest.raises(ValidationError, match="thinking"):
        load_catalog(path)


def test_catalog_rejects_unknown_tier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "tiers": ["cheapest"]}}},
    )

    with pytest.raises(ValidationError, match="tiers"):
        load_catalog(path)


def test_catalog_rejects_two_models_claiming_the_same_tier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "claude-a": {"provider": "anthropic", "tiers": ["balanced"]},
                "claude-b": {"provider": "anthropic", "tiers": ["balanced"]},
            }
        },
    )

    with pytest.raises(ValidationError, match="balanced"):
        load_catalog(path)


def test_catalog_allows_one_model_in_two_tiers(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"llama": {"provider": "ollama", "tiers": ["fast", "balanced"]}}},
    )

    catalog = load_catalog(path)

    assert catalog.models["llama"].tiers == ["fast", "balanced"]


def test_catalog_rejects_alias_pointing_at_unknown_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {"claude-a": {"provider": "anthropic"}},
            "aliases": {"llm": {"sonnet": "claude-typo"}},
        },
    )

    with pytest.raises(ValidationError, match="claude-typo"):
        load_catalog(path)


def test_catalog_rejects_default_pointing_at_unknown_alias(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {"claude-a": {"provider": "anthropic"}},
            "aliases": {"llm": {"sonnet": "claude-a"}},
            "defaults": {"llm": "opus"},
        },
    )

    with pytest.raises(ValidationError, match="opus"):
        load_catalog(path)


def test_pricing_defaults_cache_fields_to_zero(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "gpt-x": {
                    "provider": "openai",
                    "pricing": {"input": 2.5, "output": 10.0},
                }
            }
        },
    )

    pricing = load_catalog(path).models["gpt-x"].pricing

    assert pricing is not None
    assert pricing.cache_creation == 0.0
    assert pricing.cache_read == 0.0


def test_unspecified_thinking_defaults_to_budgeted(tmp_path: Path) -> None:
    """미등록·미선언 모델은 레거시 분기를 유지한다 (spec §4)."""
    path = _write(tmp_path, {"models": {"claude-a": {"provider": "anthropic"}}})

    assert load_catalog(path).models["claude-a"].thinking is ThinkingContract.BUDGETED


def test_legacy_shape_file_is_converted(tmp_path: Path) -> None:
    """`models:` 키가 없는 옛 형태 파일을 자동 변환한다 (spec §7)."""
    path = _write(
        tmp_path,
        {
            "vision_models": {
                "gpt4o": {
                    "model_id": "gpt-4o",
                    "provider": "openai",
                    "description": "OpenAI GPT-4o Vision",
                    "max_tokens": 4096,
                    "supports_video": False,
                },
                "gemini": {
                    "model_id": "gemini-1.5-pro-latest",
                    "provider": "google",
                    "max_tokens": 8192,
                    "supports_video": True,
                },
            },
            "llm_models": {
                "claude_sonnet": {
                    "model_id": "claude-sonnet-5",
                    "provider": "anthropic",
                    "max_tokens": 8192,
                }
            },
            "embedding_models": {
                "openai_small": {
                    "model_id": "text-embedding-3-small",
                    "provider": "openai",
                    "dimension": 1536,
                }
            },
            "defaults": {"vision": "gpt4o", "llm": "claude_sonnet", "embedding": "openai_small"},
        },
    )

    catalog = load_catalog(path)

    assert catalog.aliases["vision"]["gpt4o"] == "gpt-4o"
    assert catalog.aliases["llm"]["claude_sonnet"] == "claude-sonnet-5"
    assert catalog.aliases["embedding"]["openai_small"] == "text-embedding-3-small"
    # provider "google"은 LLMFactory 키 "gemini"로 정규화된다
    assert catalog.models["gemini-1.5-pro-latest"].provider == "gemini"
    assert catalog.models["gemini-1.5-pro-latest"].supports_video is True
    assert catalog.models["text-embedding-3-small"].dimension == 1536
    # 옛 형태에는 tier·pricing·thinking이 없다
    assert catalog.models["claude-sonnet-5"].tiers == []
    assert catalog.models["claude-sonnet-5"].pricing is None
    assert catalog.models["claude-sonnet-5"].thinking is ThinkingContract.BUDGETED
    assert catalog.defaults == {
        "vision": "gpt4o",
        "llm": "claude_sonnet",
        "embedding": "openai_small",
    }


def test_legacy_shape_conversion_logs_migration_notice(tmp_path: Path, caplog) -> None:
    path = _write(
        tmp_path,
        {"llm_models": {"sonnet": {"model_id": "claude-sonnet-5", "provider": "anthropic"}}},
    )

    with caplog.at_level("INFO", logger="neos.config.model_config"):
        load_catalog(path)

    assert any("legacy" in record.message.lower() for record in caplog.records)


def test_missing_file_yields_empty_catalog(tmp_path: Path, caplog) -> None:
    """파일이 없으면 부팅을 막지 않고 빈 카탈로그로 성능 저하만 감수한다."""
    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        catalog = load_catalog(tmp_path / "does-not-exist.yaml")

    assert catalog.models == {}
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_models_for_provider_returns_only_selectable_in_declaration_order(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "claude-new": {"provider": "anthropic"},
                "gpt-x": {"provider": "openai"},
                "claude-old": {"provider": "anthropic", "selectable": False},
                "claude-mid": {"provider": "anthropic"},
            }
        },
    )
    catalog = load_catalog(path)

    assert catalog.models_for_provider("anthropic") == ["claude-new", "claude-mid"]


def test_tiers_for_provider_emits_canonical_tier_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "big": {"provider": "anthropic", "tiers": ["powerful"]},
                "small": {"provider": "anthropic", "tiers": ["fast"]},
                "mid": {"provider": "anthropic", "tiers": ["balanced"]},
            }
        },
    )
    catalog = load_catalog(path)

    assert list(catalog.tiers_for_provider("anthropic")) == ["fast", "balanced", "powerful"]
    assert catalog.tiers_for_provider("anthropic")["powerful"] == "big"


def test_pricing_for_requires_provider_match(tmp_path: Path) -> None:
    """provider가 어긋나면 가격을 주지 않는다 (현행 중첩 dict 동작 보존)."""
    path = _write(
        tmp_path,
        {
            "models": {
                "gpt-x": {
                    "provider": "openai",
                    "pricing": {"input": 2.5, "output": 10.0},
                }
            }
        },
    )
    catalog = load_catalog(path)

    assert catalog.pricing_for("openai", "gpt-x") is not None
    assert catalog.pricing_for("anthropic", "gpt-x") is None
    assert catalog.pricing_for("openai", "gpt-unknown") is None


def test_thinking_contract_of_unregistered_model_is_budgeted(tmp_path: Path) -> None:
    catalog = load_catalog(_write(tmp_path, {"models": {}}))

    assert catalog.thinking_contract("claude-from-the-future") is ThinkingContract.BUDGETED


def test_committed_catalog_loads_and_is_non_empty() -> None:
    """리포지토리에 커밋된 카탈로그가 실제로 유효하다."""
    catalog = load_catalog(Path("neos/config/models.yaml"))

    assert isinstance(catalog, ModelCatalog)
    assert catalog.models


def test_legacy_alias_helpers_resolve_committed_catalog() -> None:
    from neos.config.model_config import (
        get_embedding_model_id,
        get_llm_model_id,
        get_vision_model_id,
    )

    assert get_vision_model_id("gpt4o") == "gpt-4o"
    assert get_vision_model_id("claude") == "claude-sonnet-5"
    assert get_llm_model_id("claude_sonnet") == "claude-sonnet-5"
    assert get_llm_model_id("claude_opus") == "claude-opus-5"
    assert get_llm_model_id("claude_haiku") == "claude-haiku-4-5-20251001"
    assert get_embedding_model_id("openai_small") == "text-embedding-3-small"
    # 인자 없이 호출하면 defaults를 따른다
    assert get_vision_model_id() == "gpt-4o"
    assert get_llm_model_id() == "claude-sonnet-5"
    assert get_embedding_model_id() == "text-embedding-3-small"


def test_legacy_model_dict_keeps_model_id_and_provider() -> None:
    from neos.config.model_config import model_config

    entry = model_config.get_vision_model("claude")

    assert entry["model_id"] == "claude-sonnet-5"
    assert entry["provider"] == "anthropic"


def test_legacy_lookup_of_unknown_alias_raises_with_available_names() -> None:
    from neos.config.model_config import model_config

    with pytest.raises(ValueError, match="Available models"):
        model_config.get_llm_model("nonexistent_alias")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog.py -p no:cacheprovider -q`
Expected: FAIL — `ImportError: cannot import name 'ModelCatalog' from 'neos.config.model_config'`

- [ ] **Step 3: `model_config.py`를 재작성한다**

`neos/config/model_config.py` 전체를 아래로 바꾼다:

```python
"""모델 카탈로그 로더

`neos/config/models.yaml`이 모델에 관한 사실의 단일 원천이다 — 목록 노출,
추천 티어, thinking 요청 계약, 가격.

이 모듈은 파일만 읽는다. DB나 네트워크를 요구하지 않는다.

카탈로그는 allowlist가 **아니다.** 미등록 모델은 통과하며, 경고는 사용
지점(`LLMFactory.create_llm`, 비용 집계)에서만 낸다.

배포 *정책*(provider × role 라우팅, 기능 오버라이드)은 여기가 아니라
`config/neos.*.yaml`에 있다.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from neos.config.schema import StrictConfigModel

logger = logging.getLogger(__name__)


Tier = Literal["fast", "balanced", "powerful"]
CatalogProvider = Literal["anthropic", "openai", "gemini", "ollama"]

# 추천 티어 표시 순서 (저비용 → 고성능)
_TIER_ORDER: tuple[Tier, ...] = ("fast", "balanced", "powerful")


class ThinkingContract(str, Enum):
    """모델이 따르는 thinking 요청 계약.

    모델 *정체성*이 아니라 *계약*을 이름으로 한다. Claude 5.5나 6이 같은
    계약을 쓴다면 YAML에 `thinking: adaptive` 한 줄이면 되고, 코드에
    버전이 박히지 않는다.
    """

    ADAPTIVE = "adaptive"
    BUDGETED = "budgeted"
    NONE = "none"


class ModelPricing(StrictConfigModel):
    """USD / 1M 토큰."""

    input: float
    output: float
    cache_creation: float = 0.0
    cache_read: float = 0.0


class ModelSpec(StrictConfigModel):
    provider: CatalogProvider
    # 추천 티어. 비어 있으면 추천 목록에 등장하지 않는다(수동 선택 전용).
    # 한 모델이 두 티어를 겸할 수 있다 — Ollama llama3.1:8b가 fast와 balanced를 겸한다.
    tiers: list[Tier] = Field(default_factory=list)
    thinking: ThinkingContract = ThinkingContract.BUDGETED
    # list_models() 노출 여부. 가격만 아는 레거시 모델은 false.
    selectable: bool = True
    max_tokens: int | None = None
    description: str | None = None
    supports_video: bool = False
    dimension: int | None = None
    pricing: ModelPricing | None = None


class ModelCatalog(StrictConfigModel):
    models: dict[str, ModelSpec] = Field(default_factory=dict)
    # 레거시 별칭 API용. {group: {alias: model_name}}
    aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_references(self) -> "ModelCatalog":
        claimed: dict[tuple[str, str], str] = {}
        for name, spec in self.models.items():
            for tier in spec.tiers:
                key = (spec.provider, tier)
                if key in claimed:
                    raise ValueError(
                        f"tier '{tier}' for provider '{spec.provider}' is claimed by "
                        f"both {claimed[key]!r} and {name!r}"
                    )
                claimed[key] = name

        for group, entries in self.aliases.items():
            for alias, model in entries.items():
                if model not in self.models:
                    raise ValueError(
                        f"alias {group}.{alias} points to unknown model {model!r}"
                    )

        for group, alias in self.defaults.items():
            if group not in self.aliases:
                raise ValueError(
                    f"default '{group}' has no matching aliases.{group} group"
                )
            if alias not in self.aliases[group]:
                raise ValueError(
                    f"default {group}={alias!r} is not defined in aliases.{group}"
                )
        return self

    # ---- 파생 뷰 ----

    def get_model_spec(self, model: str) -> ModelSpec | None:
        return self.models.get(model)

    def models_for_provider(self, provider: str) -> list[str]:
        """선택 가능한 모델 목록. 선언 순서를 보존한다."""
        return [
            name
            for name, spec in self.models.items()
            if spec.provider == provider and spec.selectable
        ]

    def tiers_for_provider(self, provider: str) -> dict[str, str]:
        """{tier: model}. fast → balanced → powerful 순으로 낸다."""
        by_tier: dict[str, str] = {}
        for name, spec in self.models.items():
            if spec.provider != provider:
                continue
            for tier in spec.tiers:
                by_tier[tier] = name
        return {tier: by_tier[tier] for tier in _TIER_ORDER if tier in by_tier}

    def thinking_contract(self, model: str) -> ThinkingContract:
        """모델의 thinking 요청 계약. 미등록 모델은 BUDGETED(레거시 경로)."""
        spec = self.models.get(model)
        return spec.thinking if spec else ThinkingContract.BUDGETED

    def pricing_for(self, provider: str, model: str) -> ModelPricing | None:
        spec = self.models.get(model)
        if spec is None or spec.provider != provider:
            return None
        return spec.pricing

    def resolve_alias(self, group: str, alias: str) -> str:
        entries = self.aliases.get(group, {})
        if alias not in entries:
            available = ", ".join(entries)
            raise ValueError(
                f"{group} model '{alias}' not found in configuration. "
                f"Available models: {available}"
            )
        return entries[alias]


# ---- 옛 형태 변환 ----

_LEGACY_GROUPS: tuple[tuple[str, str], ...] = (
    ("vision_models", "vision"),
    ("llm_models", "llm"),
    ("embedding_models", "embedding"),
)
# 옛 파일은 Gemini provider를 "google"로 적었다. LLMFactory 키로 정규화한다.
_PROVIDER_ALIASES = {"google": "gemini"}
_LEGACY_SPEC_FIELDS = ("description", "max_tokens", "supports_video", "dimension")


def _looks_legacy(data: dict[str, Any]) -> bool:
    return "models" not in data and any(key in data for key, _ in _LEGACY_GROUPS)


def _convert_legacy_catalog(data: dict[str, Any]) -> dict[str, Any]:
    """옛 형태(`vision_models`/`llm_models`/`embedding_models`)를 카탈로그로 변환.

    옛 형태에는 tier·pricing·thinking이 없으므로 그 모델들은 티어 없음,
    가격 미상, `thinking: budgeted`로 취급된다. 한 모델 ID가 여러 그룹에
    나타나면 처음 만난 항목의 메타데이터를 쓴다.
    """
    models: dict[str, dict[str, Any]] = {}
    aliases: dict[str, dict[str, str]] = {}

    for legacy_key, group in _LEGACY_GROUPS:
        for alias, entry in (data.get(legacy_key) or {}).items():
            model_id = entry["model_id"]
            aliases.setdefault(group, {})[alias] = model_id
            if model_id in models:
                continue
            provider = entry.get("provider", "openai")
            spec: dict[str, Any] = {
                "provider": _PROVIDER_ALIASES.get(provider, provider)
            }
            for field in _LEGACY_SPEC_FIELDS:
                if field in entry:
                    spec[field] = entry[field]
            models[model_id] = spec

    return {
        "models": models,
        "aliases": aliases,
        "defaults": data.get("defaults") or {},
    }


def load_catalog(path: Path) -> ModelCatalog:
    """카탈로그를 읽는다. 실패하면 빈 카탈로그로 성능 저하만 감수한다.

    부팅을 막지 않는 이유: 카탈로그는 기본값의 원천이지 필수 자원이 아니다.
    비어 있으면 소비자가 경고를 내며 각자의 폴백으로 간다.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.error("Model catalog not found: %s — using an empty catalog", path)
        return ModelCatalog()
    except yaml.YAMLError as exc:
        logger.error("Model catalog is not valid YAML (%s): %s", path, exc)
        return ModelCatalog()

    if _looks_legacy(raw):
        logger.info(
            "Model catalog %s uses the legacy shape "
            "(vision_models/llm_models/embedding_models) and was converted in memory. "
            "Migrate it to the `models:` shape to declare tiers, pricing and "
            "thinking contracts.",
            path,
        )
        raw = _convert_legacy_catalog(raw)

    return ModelCatalog.model_validate(raw)


def _catalog_path() -> Path:
    custom = os.getenv("NEOS_MODEL_CONFIG_PATH")
    if custom:
        return Path(custom)
    return Path(__file__).parent / "models.yaml"


class ModelConfig:
    """카탈로그 싱글톤.

    레거시 `get_vision_model()` 계열 API를 카탈로그 위에 유지한다.
    """

    _instance: "ModelConfig | None" = None
    _catalog: ModelCatalog | None = None

    def __new__(cls) -> "ModelConfig":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._catalog is None:
            self.reload()

    @property
    def catalog(self) -> ModelCatalog:
        if self._catalog is None:
            self.reload()
        assert self._catalog is not None
        return self._catalog

    def reload(self) -> None:
        path = _catalog_path()
        try:
            self._catalog = load_catalog(path)
        except ValidationError as exc:
            logger.error("Model catalog %s failed validation: %s", path, exc)
            self._catalog = ModelCatalog()
        else:
            logger.info("Model catalog loaded from: %s", path)

    # ---- 레거시 API ----

    def _legacy_entry(self, group: str, alias: str) -> dict[str, Any]:
        model_id = self.catalog.resolve_alias(group, alias)
        spec = self.catalog.models[model_id]
        entry = spec.model_dump(exclude_none=True, exclude={"pricing", "tiers"})
        entry["model_id"] = model_id
        return entry

    def get_vision_model(self, model_name: str) -> dict[str, Any]:
        return self._legacy_entry("vision", model_name)

    def get_vision_model_id(self, model_name: str) -> str:
        return self.catalog.resolve_alias("vision", model_name)

    def get_llm_model(self, model_name: str) -> dict[str, Any]:
        return self._legacy_entry("llm", model_name)

    def get_llm_model_id(self, model_name: str) -> str:
        return self.catalog.resolve_alias("llm", model_name)

    def get_embedding_model(self, model_name: str) -> dict[str, Any]:
        return self._legacy_entry("embedding", model_name)

    def get_embedding_model_id(self, model_name: str) -> str:
        return self.catalog.resolve_alias("embedding", model_name)

    def get_default_vision_model(self) -> str:
        return self.catalog.defaults.get("vision", "gpt4o")

    def get_default_llm_model(self) -> str:
        return self.catalog.defaults.get("llm", "claude_sonnet")

    def get_default_embedding_model(self) -> str:
        return self.catalog.defaults.get("embedding", "openai_small")

    def list_vision_models(self) -> list[str]:
        return list(self.catalog.aliases.get("vision", {}))

    def list_llm_models(self) -> list[str]:
        return list(self.catalog.aliases.get("llm", {}))

    def list_embedding_models(self) -> list[str]:
        return list(self.catalog.aliases.get("embedding", {}))


model_config = ModelConfig()


# ---- 모듈 수준 편의 함수 ----


def get_vision_model_id(model_name: str | None = None) -> str:
    name = model_name or model_config.get_default_vision_model()
    return model_config.get_vision_model_id(name)


def get_llm_model_id(model_name: str | None = None) -> str:
    name = model_name or model_config.get_default_llm_model()
    return model_config.get_llm_model_id(name)


def get_embedding_model_id(model_name: str | None = None) -> str:
    name = model_name or model_config.get_default_embedding_model()
    return model_config.get_embedding_model_id(name)


def get_model_spec(model: str) -> ModelSpec | None:
    return model_config.catalog.get_model_spec(model)


def models_for_provider(provider: str) -> list[str]:
    return model_config.catalog.models_for_provider(provider)


def tiers_for_provider(provider: str) -> dict[str, str]:
    return model_config.catalog.tiers_for_provider(provider)


def thinking_contract(model: str) -> ThinkingContract:
    return model_config.catalog.thinking_contract(model)


def pricing_for(provider: str, model: str) -> ModelPricing | None:
    return model_config.catalog.pricing_for(provider, model)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog.py -p no:cacheprovider -q`
Expected: PASS (20 passed)

`test_committed_catalog_loads_and_is_non_empty`와 `test_legacy_alias_helpers_resolve_committed_catalog`는 아직 옛 형태인 `neos/config/models.yaml`이 자동 변환되어 통과한다. 이것이 이 단계의 핵심 확인이다.

- [ ] **Step 5: 기존 소비자 회귀를 확인한다**

Run: `python -m pytest tests/config tests/providers tests/test_cost_calculator.py -p no:cacheprovider -q`
Expected: PASS — 소비자는 아직 바뀌지 않았고, 옛 형태 변환이 `get_vision_model_id` 계열을 지탱한다.

- [ ] **Step 6: 커밋**

```bash
git add neos/config/model_config.py tests/config/test_model_catalog.py
git commit -m "feat: validate the model catalog with a pydantic loader"
```

---

## Task 2: `models.yaml`을 새 형태로 작성 + 이관 정합성 안전망

현재 하드코딩 값을 **그대로** 옮긴다. 동작 변화는 0이어야 한다. 소비자는 여전히 하드코딩을 쓰므로, 카탈로그와 하드코딩을 **양방향 대조**할 수 있다 — 이것이 전사 오류를 잡는 안전망이다.

**Files:**
- Modify: `neos/config/models.yaml` (옛 형태 → 새 형태)
- Test: `tests/config/test_model_catalog_parity.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `load_catalog`, `models_for_provider`, `tiers_for_provider`, `thinking_contract`, `pricing_for`, `ThinkingContract`
- Produces: 커밋된 카탈로그. Task 3~5가 이 값을 파생 원천으로 삼는다.

- [ ] **Step 1: 실패하는 정합성 테스트를 작성한다**

`tests/config/test_model_catalog_parity.py`를 새로 만든다. 두 종류의 단언이 들어간다 — **절대값 단언**(영구 회귀 테스트)과 **교차 대조**(하드코딩이 살아 있는 동안만; Task 3~5에서 해당 하드코딩과 함께 제거).

```python
"""이관 정합성 — 카탈로그가 이관 전 하드코딩 값과 일치하는가.

가장 큰 위험은 전사(transcription) 오류다. 절대값 단언은 영구 회귀
테스트로 남고, `_crosscheck` 표시가 붙은 테스트는 대응 하드코딩이
삭제되는 Task와 함께 제거된다.
"""

import pytest

from neos.config.model_config import (
    ThinkingContract,
    models_for_provider,
    pricing_for,
    thinking_contract,
    tiers_for_provider,
)

pytestmark = pytest.mark.no_db


ANTHROPIC_SELECTABLE = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

OPENAI_SELECTABLE = [
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5-mini-2025-08-07",
    "gpt-5-2025-08-07",
    "o3-mini",
    "o3",
]

EXPECTED_TIERS = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "balanced": "claude-sonnet-5",
        "powerful": "claude-opus-5",
    },
    "openai": {
        "fast": "gpt-5-mini-2025-08-07",
        "balanced": "gpt-5.6-terra",
        "powerful": "gpt-5.6-sol",
    },
    "gemini": {
        "fast": "gemini-2.0-flash-exp",
        "balanced": "gemini-1.5-pro-latest",
        "powerful": "gemini-1.5-pro-latest",
    },
    "ollama": {
        "fast": "llama3.1:8b",
        "balanced": "llama3.1:8b",
        "powerful": "llama3.1:70b",
    },
}

EXPECTED_PRICING = {
    ("openai", "gpt-5.6-terra"): (2.50, 15.00, 0.0, 0.0),
    ("openai", "gpt-5.6-sol"): (5.00, 30.00, 0.0, 0.0),
    ("openai", "gpt-4o"): (2.50, 10.00, 0.0, 0.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60, 0.0, 0.0),
    ("openai", "gpt-4-turbo"): (10.00, 30.00, 0.0, 0.0),
    ("openai", "gpt-3.5-turbo"): (0.50, 1.50, 0.0, 0.0),
    ("anthropic", "claude-sonnet-5"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-5"): (5.00, 25.00, 6.25, 0.50),
    ("anthropic", "claude-sonnet-4-5-20250929"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-3-5-sonnet-20240620"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-4-5-20251101"): (15.00, 75.00, 18.75, 1.50),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.25, 1.25, 0.30, 0.03),
}

ADAPTIVE_MODELS = ["claude-sonnet-5", "claude-opus-5"]

BUDGETED_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-3-5-sonnet-20240620",
    "claude-opus-4-5-20251101",
]


def test_catalog_selectable_lists_match_expected_order() -> None:
    assert models_for_provider("anthropic") == ANTHROPIC_SELECTABLE
    assert models_for_provider("openai") == OPENAI_SELECTABLE


@pytest.mark.parametrize("provider", sorted(EXPECTED_TIERS))
def test_catalog_tiers_match_expected(provider: str) -> None:
    assert tiers_for_provider(provider) == EXPECTED_TIERS[provider]


@pytest.mark.parametrize(("key", "expected"), sorted(EXPECTED_PRICING.items()))
def test_catalog_pricing_matches_expected(
    key: tuple[str, str], expected: tuple[float, float, float, float]
) -> None:
    provider, model = key
    pricing = pricing_for(provider, model)

    assert pricing is not None, f"{provider}/{model} has no catalog pricing"
    assert (
        pricing.input,
        pricing.output,
        pricing.cache_creation,
        pricing.cache_read,
    ) == expected


@pytest.mark.parametrize("model", ADAPTIVE_MODELS)
def test_adaptive_thinking_models(model: str) -> None:
    assert thinking_contract(model) is ThinkingContract.ADAPTIVE


@pytest.mark.parametrize("model", BUDGETED_MODELS)
def test_budgeted_thinking_models(model: str) -> None:
    assert thinking_contract(model) is ThinkingContract.BUDGETED


def test_openai_models_declare_no_thinking_contract() -> None:
    for model in OPENAI_SELECTABLE:
        assert thinking_contract(model) is ThinkingContract.NONE


def test_every_selectable_model_without_pricing_is_known() -> None:
    """가격 미상 모델은 의도된 목록과 정확히 일치해야 한다.

    선택 가능하지만 가격이 없는 모델의 비용은 0으로 집계된다(spec §1).
    새 모델을 가격 없이 추가하면 이 테스트가 알려준다.
    """
    unpriced = {
        model
        for provider in ("anthropic", "openai")
        for model in models_for_provider(provider)
        if pricing_for(provider, model) is None
    }

    assert unpriced == {
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "gpt-5-mini-2025-08-07",
        "gpt-5-2025-08-07",
        "o3",
        "o3-mini",
    }


# ---- 교차 대조: 하드코딩이 살아 있는 동안만 (해당 Task에서 제거) ----


def test_crosscheck_list_models_against_hardcoded() -> None:
    """Task 4에서 제거 — list_models()가 카탈로그 파생이 되면 항진명제가 된다."""
    from neos.providers.anthropic import AnthropicProvider
    from neos.providers.openai import OpenAIProvider

    assert (
        AnthropicProvider.__new__(AnthropicProvider).list_models()
        == ANTHROPIC_SELECTABLE
    )
    assert OpenAIProvider.__new__(OpenAIProvider).list_models() == OPENAI_SELECTABLE


def test_crosscheck_recommended_models_against_hardcoded() -> None:
    """Task 4에서 제거."""
    from neos.utils.llm_factory import get_recommended_models

    for provider, expected in EXPECTED_TIERS.items():
        assert get_recommended_models(provider) == expected


def test_crosscheck_pricing_against_hardcoded() -> None:
    """Task 5에서 제거 — DEFAULT_PRICING과 함께."""
    from neos.utils.cost_calculator import CostCalculator

    flat = {
        (provider, model): values
        for provider, models in CostCalculator.DEFAULT_PRICING.items()
        for model, values in models.items()
    }

    assert set(flat) == set(EXPECTED_PRICING)
    for key, values in flat.items():
        expected_input, expected_output, expected_cc, expected_cr = EXPECTED_PRICING[key]
        assert values["input"] == expected_input
        assert values["output"] == expected_output
        assert values.get("cache_creation", 0.0) == expected_cc
        assert values.get("cache_read", 0.0) == expected_cr


def test_crosscheck_adaptive_contract_against_is_claude_5() -> None:
    """Task 3에서 제거 — is_claude_5와 함께."""
    from neos.config.model_routing import is_claude_5

    for model in ADAPTIVE_MODELS:
        assert is_claude_5(model) is True
    for model in BUDGETED_MODELS:
        assert is_claude_5(model) is False
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog_parity.py -p no:cacheprovider -q`
Expected: FAIL — `models.yaml`이 아직 옛 형태라 `models_for_provider("anthropic")`가 `['claude-sonnet-5', 'claude-opus-5', 'claude-haiku-4-5-20251001']`(vision/llm 별칭에서 변환된 것)을 돌려준다. `tiers_for_provider`는 `{}`, `pricing_for`는 `None`.

교차 대조 4건은 이 시점에 **통과한다** — 하드코딩끼리 비교하므로 기대 리터럴이 옳다는 것을 먼저 증명한다. 이 순서가 안전망의 핵심이다.

- [ ] **Step 3: `neos/config/models.yaml`을 새 형태로 재작성한다**

선언 순서 규칙: provider별로 묶고, 각 provider 안에서 **현재 `list_models()` 순서**대로 선택 가능한 모델을 먼저 쓰고, 그 뒤에 `selectable: false` 모델을 쓴다. `models_for_provider()`가 dict 삽입 순서로 필터링하므로 이 배치가 현재 순서를 보존한다.

```yaml
# 모델 카탈로그 — 모델 사실의 단일 원천
#
# 새 Claude/GPT 모델 추가는 이 파일 편집으로 끝난다.
# 배포 *정책*(provider × role 라우팅, 기능 오버라이드)은 여기가 아니라
# config/neos.*.yaml에 있다.
#
# 필드:
#   provider     anthropic | openai | gemini | ollama
#   tiers        추천 티어 목록 (fast|balanced|powerful). 비면 추천에 등장하지 않음
#   thinking     adaptive | budgeted | none  (미선언 시 budgeted)
#   selectable   list_models()에 노출되는가 (기본 true). Anthropic·OpenAI에만 파생 적용
#   pricing      USD / 1M 토큰. 없으면 "가격 미상" — 비용 집계 시 경고 후 0
#
# 선언 순서가 list_models() 순서다. 최신 → 레거시 순을 유지할 것.

models:
  # ---- Anthropic (선택 가능) ----
  claude-sonnet-5:
    provider: anthropic
    tiers: [balanced]
    thinking: adaptive
    description: "Anthropic Claude Sonnet 5"
    max_tokens: 8192
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}

  claude-opus-5:
    provider: anthropic
    tiers: [powerful]
    thinking: adaptive
    description: "Anthropic Claude Opus 5"
    max_tokens: 8192
    pricing: {input: 5.00, output: 25.00, cache_creation: 6.25, cache_read: 0.50}

  claude-haiku-4-5-20251001:
    provider: anthropic
    tiers: [fast]
    thinking: budgeted
    description: "Anthropic Claude Haiku 4.5"
    max_tokens: 8192
    pricing: {input: 0.25, output: 1.25, cache_creation: 0.30, cache_read: 0.03}

  claude-sonnet-4-5-20250929:
    provider: anthropic
    thinking: budgeted
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}

  claude-sonnet-4-6:
    provider: anthropic
    thinking: budgeted
    # 가격 미상 — 현행과 동일. 비용 집계 시 경고 후 0으로 처리된다.

  claude-opus-4-6:
    provider: anthropic
    thinking: budgeted
    # 가격 미상

  # ---- Anthropic (가격만 아는 레거시) ----
  claude-3-5-sonnet-20240620:
    provider: anthropic
    thinking: budgeted
    selectable: false
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}

  claude-opus-4-5-20251101:
    provider: anthropic
    thinking: budgeted
    selectable: false
    pricing: {input: 15.00, output: 75.00, cache_creation: 18.75, cache_read: 1.50}

  # ---- OpenAI (선택 가능) ----
  gpt-5.6-terra:
    provider: openai
    tiers: [balanced]
    thinking: none
    pricing: {input: 2.50, output: 15.00}

  gpt-5.6-sol:
    provider: openai
    tiers: [powerful]
    thinking: none
    pricing: {input: 5.00, output: 30.00}

  gpt-5-mini-2025-08-07:
    provider: openai
    tiers: [fast]
    thinking: none
    # 가격 미상

  gpt-5-2025-08-07:
    provider: openai
    thinking: none
    # 가격 미상

  o3-mini:
    provider: openai
    thinking: none
    # 가격 미상

  o3:
    provider: openai
    thinking: none
    # 가격 미상

  # ---- OpenAI (가격·별칭만 아는 레거시) ----
  gpt-4o:
    provider: openai
    thinking: none
    selectable: false
    description: "OpenAI GPT-4o Vision"
    max_tokens: 4096
    pricing: {input: 2.50, output: 10.00}

  gpt-4o-mini:
    provider: openai
    thinking: none
    selectable: false
    pricing: {input: 0.15, output: 0.60}

  gpt-4-turbo:
    provider: openai
    thinking: none
    selectable: false
    pricing: {input: 10.00, output: 30.00}

  gpt-3.5-turbo:
    provider: openai
    thinking: none
    selectable: false
    pricing: {input: 0.50, output: 1.50}

  gpt-4-turbo-preview:
    provider: openai
    thinking: none
    selectable: false
    description: "OpenAI GPT-4 Turbo"
    max_tokens: 4096
    # 가격 미상. aliases.llm.gpt4가 가리키는 레거시 별칭 대상이다.

  text-embedding-3-small:
    provider: openai
    thinking: none
    selectable: false
    description: "OpenAI Embedding Small"
    dimension: 1536

  text-embedding-3-large:
    provider: openai
    thinking: none
    selectable: false
    description: "OpenAI Embedding Large"
    dimension: 3072

  # ---- Gemini (tier만 이관. list_models()는 정적 목록 유지) ----
  gemini-2.0-flash-exp:
    provider: gemini
    tiers: [fast]
    thinking: none
    selectable: false

  gemini-1.5-pro-latest:
    provider: gemini
    tiers: [balanced, powerful]
    thinking: none
    selectable: false
    description: "Google Gemini 1.5 Pro"
    max_tokens: 8192
    supports_video: true

  # ---- Ollama (tier만 이관. list_models()는 라이브 서버 조회 유지) ----
  # 키에 콜론이 있으므로 반드시 인용한다 — 인용하지 않으면 PyYAML이 파싱에 실패한다.
  "llama3.1:8b":
    provider: ollama
    tiers: [fast, balanced]
    thinking: none
    selectable: false

  "llama3.1:70b":
    provider: ollama
    tiers: [powerful]
    thinking: none
    selectable: false

# 레거시 별칭 API — get_vision_model_id / get_llm_model_id / get_embedding_model_id
aliases:
  vision:
    gpt4o: gpt-4o
    claude: claude-sonnet-5
    gemini: gemini-1.5-pro-latest
  llm:
    gpt4: gpt-4-turbo-preview
    claude_opus: claude-opus-5
    claude_sonnet: claude-sonnet-5
    claude_haiku: claude-haiku-4-5-20251001
  embedding:
    openai_small: text-embedding-3-small
    openai_large: text-embedding-3-large

defaults:
  vision: gpt4o
  llm: claude_sonnet
  embedding: openai_small
```

- [ ] **Step 4: YAML이 파싱되고 검증을 통과하는지 확인한다**

```bash
python -c "
from pathlib import Path
from neos.config.model_config import load_catalog
c = load_catalog(Path('neos/config/models.yaml'))
print('models:', len(c.models))
print('anthropic selectable:', c.models_for_provider('anthropic'))
print('openai selectable:', c.models_for_provider('openai'))
print('ollama tiers:', c.tiers_for_provider('ollama'))
"
```
Expected: `models: 25` (anthropic 8 + openai 13 + gemini 2 + ollama 2), `models_for_provider('anthropic')`가 6개(claude-sonnet-5 … claude-opus-4-6), `models_for_provider('openai')`가 6개(gpt-5.6-terra … o3), `tiers_for_provider('ollama')`가 `{'fast': 'llama3.1:8b', 'balanced': 'llama3.1:8b', 'powerful': 'llama3.1:70b'}`.

- [ ] **Step 5: 정합성 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog_parity.py tests/config/test_model_catalog.py -p no:cacheprovider -q`
Expected: PASS — 절대값 단언과 교차 대조가 **모두** 통과한다. 교차 대조가 통과한다는 것은 리터럴이 하드코딩과 일치한다는 뜻이고, 절대값 단언이 통과한다는 것은 카탈로그가 그 리터럴과 일치한다는 뜻이다. 두 단언의 결합이 전사 오류 0을 증명한다.

- [ ] **Step 6: 전체 회귀를 확인한다**

Run: `python -m pytest tests/config tests/providers tests/test_cost_calculator.py -p no:cacheprovider -q`
Expected: PASS. 소비자는 아직 하드코딩을 쓰므로 동작 변화가 없어야 한다.

- [ ] **Step 7: 커밋**

```bash
git add neos/config/models.yaml tests/config/test_model_catalog_parity.py
git commit -m "feat: transcribe hardcoded model facts into the catalog"
```

---

## Task 3: thinking 계약 이관 — `is_claude_5` 삭제

**Files:**
- Modify: `neos/config/model_routing.py:30-34` (`_CLAUDE_5_MODELS`, `is_claude_5` 삭제)
- Modify: `neos/providers/anthropic.py:12,27,90` (카탈로그 조회로 전환)
- Modify: `tests/config/test_model_routing.py:1-13,98-113` (`is_claude_5` 테스트 제거)
- Modify: `tests/providers/test_current_model_providers.py:135` (에러 메시지 match 갱신)
- Modify: `tests/config/test_model_catalog_parity.py` (`test_crosscheck_adaptive_contract_against_is_claude_5` 제거)
- Test: `tests/providers/test_current_model_providers.py` (미등록 모델 케이스 추가)

**Interfaces:**
- Consumes: `thinking_contract(model) -> ThinkingContract`, `ThinkingContract` (Task 1)
- Produces: `normalize_anthropic_request(model, params, *, thinking_enabled) -> dict` — 시그니처 불변, 판별 근거만 카탈로그로 이동. `neos/workflow/deep_analysis/llm.py`가 이 함수를 재사용하므로 별도 변경이 없다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/providers/test_current_model_providers.py` 끝에 추가한다:

```python
def test_unregistered_anthropic_model_keeps_budgeted_thinking(monkeypatch):
    """카탈로그에 없는 Anthropic 모델은 레거시 분기를 유지한다 (spec §4)."""
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=True, max_thinking_length=2048),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-9-not-in-catalog",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert params["temperature"] == 1.0
    assert params["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_thinking_contract_drives_normalization_not_the_model_name(monkeypatch):
    """계약이 adaptive면 이름과 무관하게 adaptive 경로를 탄다.

    Claude 5.5 / 6이 나와도 YAML 한 줄로 끝나는지를 고정한다.
    """
    from neos.config.model_config import ThinkingContract

    monkeypatch.setattr(
        "neos.providers.anthropic.thinking_contract",
        lambda model: ThinkingContract.ADAPTIVE,
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=False, max_thinking_length=0),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-7-hypothetical",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert "temperature" not in params
    assert params["thinking"] == {"type": "adaptive"}


def test_version_baked_identifiers_are_gone():
    """`is_claude_5`가 shim으로도 남지 않는다 (spec §4)."""
    import neos.config.model_routing as model_routing

    assert not hasattr(model_routing, "is_claude_5")
    assert "is_claude_5" not in Path("neos/providers/anthropic.py").read_text(
        encoding="utf-8"
    )
```

같은 파일 상단 import에 `from pathlib import Path`를 추가한다.

그리고 같은 파일 135행의 기존 단언을 고친다 — 에러 메시지에서 버전 표현을 없애기 때문이다:

```python
    with pytest.raises(ValueError, match="budget_tokens.*adaptive"):
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/providers/test_current_model_providers.py -p no:cacheprovider -q`
Expected: FAIL 3건 —
- `test_thinking_contract_drives_normalization_not_the_model_name`: `AttributeError: <module 'neos.providers.anthropic'> has no attribute 'thinking_contract'`
- `test_version_baked_identifiers_are_gone`: `assert not hasattr(...)` 실패
- `test_claude_5_rejects_manual_thinking_budget`: 현재 메시지가 "Claude 5"이므로 `match="budget_tokens.*adaptive"` 불일치

`test_unregistered_anthropic_model_keeps_budgeted_thinking`은 현재도 통과한다(is_claude_5가 False이므로). 이관 후에도 통과하는지가 이 테스트의 목적이다.

- [ ] **Step 3: `model_routing.py`에서 `is_claude_5`를 삭제한다**

`neos/config/model_routing.py`의 30~34행을 삭제한다:

```python
_CLAUDE_5_MODELS = frozenset({"claude-sonnet-5", "claude-opus-5"})


def is_claude_5(model: str) -> bool:
    return model in _CLAUDE_5_MODELS
```

`ModelResolution` 정의와 `resolve_model` 사이의 빈 줄 2개만 남는다. 이제 이 모듈은 순수 리졸버다 — 파일 I/O를 하는 `model_config`를 참조하지 않으므로 순환 import도 없다.

- [ ] **Step 4: `anthropic.py`가 카탈로그를 조회하게 바꾼다**

`neos/providers/anthropic.py` 12행의 import를 바꾼다:

```python
from neos.config.model_config import ThinkingContract, thinking_contract
```

`normalize_anthropic_request`를 바꾼다 (19~40행):

```python
def normalize_anthropic_request(
    model: str,
    params: dict[str, Any],
    *,
    thinking_enabled: bool,
) -> dict[str, Any]:
    """adaptive thinking 계약을 쓰는 모델의 요청을 정규화한다.

    계약은 모델 카탈로그(`neos/config/models.yaml`)가 선언한다.
    """
    normalized = dict(params)
    if thinking_contract(model) is not ThinkingContract.ADAPTIVE:
        return normalized

    thinking = normalized.get("thinking")
    if isinstance(thinking, dict) and "budget_tokens" in thinking:
        raise ValueError(
            "budget_tokens is not supported by the adaptive thinking contract"
        )

    normalized.pop("temperature", None)
    normalized.pop("top_p", None)
    normalized.pop("top_k", None)
    normalized["thinking"] = (
        {"type": "adaptive"} if thinking_enabled else {"type": "disabled"}
    )
    return normalized
```

`create_llm`의 분기를 바꾼다 (88~114행). `contract` 값을 명시적으로 분기해 암묵적 `else`를 없앤다:

```python
        # Thinking Blocks 제어 — 계약은 카탈로그가 선언한다
        disable_thinking = params.pop("disable_thinking", False)
        contract = thinking_contract(model)

        if contract is ThinkingContract.ADAPTIVE:
            params = normalize_anthropic_request(
                model,
                params,
                thinking_enabled=not disable_thinking,
            )
        elif contract is ThinkingContract.BUDGETED and (
            (settings.THINKING_BLOCKS_ENABLED or settings.MAX_THINKING_LENGTH > 0)
            and not disable_thinking
        ):
            budget = settings.MAX_THINKING_LENGTH
            if budget < 1024:
                logger.warning("MAX_THINKING_LENGTH too low; raising to 1024")
                budget = 1024

            if params.get("temperature", 1.0) != 1.0:
                logger.warning(
                    "Thinking blocks require temperature=1.0; overriding %s → 1.0",
                    params.get("temperature"),
                )
                params["temperature"] = 1.0

            params["thinking"] = {"type": "enabled", "budget_tokens": budget}

            current_max = params.get("max_tokens", 0)
            if not current_max or current_max <= budget:
                params["max_tokens"] = budget + 4096
                logger.info("Set max_tokens=%d for thinking blocks", params["max_tokens"])
```

`ThinkingContract.NONE`은 어느 분기에도 들지 않아 페이로드가 변형되지 않는다.

- [ ] **Step 5: `is_claude_5` 테스트를 제거한다**

`tests/config/test_model_routing.py`에서 import(9행)의 `is_claude_5,`를 지우고, 98~113행의 파라미터화 테스트 전체를 삭제한다:

```python
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-sonnet-5", True),
        ...
    ],
)
def test_is_claude_5_matches_only_claude_five_models(
    model: str, expected: bool
) -> None:
    assert is_claude_5(model) is expected
```

이 테스트가 지키던 계약(어떤 모델이 adaptive인가)은 `tests/config/test_model_catalog_parity.py::test_adaptive_thinking_models` / `test_budgeted_thinking_models`가 이미 지킨다.

`tests/config/test_model_catalog_parity.py`에서 `test_crosscheck_adaptive_contract_against_is_claude_5` 함수 전체를 삭제한다.

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/providers tests/config -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 7: `is_claude_5` 잔재가 없는지 확인한다**

Run: `grep -rn "is_claude_5" --include="*.py" --include="*.md" . | grep -v docs/superpowers`
Expected: 출력 없음. (`docs/superpowers/` 아래 스펙·계획 문서는 이력이므로 제외한다.)

- [ ] **Step 8: 커밋**

```bash
git add neos/config/model_routing.py neos/providers/anthropic.py \
        tests/config/test_model_routing.py tests/config/test_model_catalog_parity.py \
        tests/providers/test_current_model_providers.py
git commit -m "refactor: declare thinking contracts in the model catalog"
```

---

## Task 4: 목록·티어 이관

**Files:**
- Modify: `neos/providers/anthropic.py:56-64` (`list_models`)
- Modify: `neos/providers/openai.py:25-33` (`list_models`)
- Modify: `neos/utils/llm_factory.py:280-304` (`get_recommended_models`)
- Modify: `tests/config/test_model_catalog_parity.py` (교차 대조 2건 제거)
- Modify: `tests/providers/test_current_model_providers.py:23-44` (파생 단언으로 전환)

**Interfaces:**
- Consumes: `models_for_provider(provider) -> list[str]`, `tiers_for_provider(provider) -> dict[str, str]` (Task 1)
- Produces: `get_recommended_models(provider) -> dict[str, str]` — 시그니처 불변. `neos/cli.py:1653`이 소비한다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/providers/test_current_model_providers.py`의 23~44행 두 테스트를 아래로 교체한다:

```python
def test_provider_catalogs_are_derived_from_the_model_catalog():
    from neos.config.model_config import models_for_provider

    assert (
        AnthropicProvider.__new__(AnthropicProvider).list_models()
        == models_for_provider("anthropic")
    )
    assert (
        OpenAIProvider.__new__(OpenAIProvider).list_models()
        == models_for_provider("openai")
    )


def test_provider_catalogs_include_current_and_legacy_models():
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert {"claude-sonnet-5", "claude-opus-5"} <= set(anthropic_models)
    assert {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    } <= set(anthropic_models)
    assert {"gpt-5.6-terra", "gpt-5.6-sol"} <= set(openai_models)
    assert {"gpt-5-mini-2025-08-07", "gpt-5-2025-08-07", "o3-mini", "o3"} <= set(
        openai_models
    )


def test_priced_only_models_stay_out_of_the_selectable_lists():
    """가격만 아는 레거시 모델을 목록에 끼워넣지 않는다 (spec §3 selectable)."""
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert "claude-opus-4-5-20251101" not in anthropic_models
    assert "claude-3-5-sonnet-20240620" not in anthropic_models
    assert "gpt-4o" not in openai_models
    assert "gpt-3.5-turbo" not in openai_models


def test_recommendations_are_derived_from_the_model_catalog():
    from neos.config.model_config import tiers_for_provider

    for provider in ("anthropic", "openai", "gemini", "ollama"):
        assert get_recommended_models(provider) == tiers_for_provider(provider)


def test_recommendations_use_current_everyday_and_powerful_models():
    assert get_recommended_models("anthropic")["balanced"] == "claude-sonnet-5"
    assert get_recommended_models("anthropic")["powerful"] == "claude-opus-5"
    assert get_recommended_models("openai")["balanced"] == "gpt-5.6-terra"
    assert get_recommended_models("openai")["powerful"] == "gpt-5.6-sol"


def test_recommendations_for_unknown_provider_are_empty():
    assert get_recommended_models("no-such-provider") == {}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/providers/test_current_model_providers.py -p no:cacheprovider -q`
Expected: FAIL 2건 — `test_provider_catalogs_are_derived_from_the_model_catalog`와 `test_recommendations_are_derived_from_the_model_catalog`. 하드코딩 값이 우연히 같으므로 `==` 비교는 통과할 수 있다.

> ⚠️ 이 두 테스트는 값이 같으면 하드코딩 상태에서도 통과한다. 그러므로 **RED를 강제로 관찰해야 한다.** 아래로 파생이 실제로 연결됐는지 확인한다:
>
> ```bash
> python - <<'PY'
> from unittest.mock import patch
> from neos.providers.anthropic import AnthropicProvider
> with patch("neos.config.model_config.models_for_provider", return_value=["sentinel"]):
>     print(AnthropicProvider.__new__(AnthropicProvider).list_models())
> PY
> ```
> Expected (Step 2, 하드코딩 상태): `['claude-sonnet-5', ...]` — 카탈로그를 무시한다.
> Expected (Step 4 이후): `['sentinel']` — 파생이 연결됐다.

- [ ] **Step 3: 프로바이더 목록을 파생으로 바꾼다**

`neos/providers/anthropic.py` — import에 추가:

```python
from neos.config.model_config import (
    ThinkingContract,
    models_for_provider,
    thinking_contract,
)
```

`list_models`를 교체한다:

```python
    def list_models(self) -> List[str]:
        return models_for_provider("anthropic")
```

`neos/providers/openai.py` — import에 추가:

```python
from neos.config.model_config import models_for_provider
```

`list_models`를 교체한다:

```python
    def list_models(self) -> List[str]:
        return models_for_provider("openai")
```

Gemini와 Ollama의 `list_models()`는 **바꾸지 않는다.** Gemini는 정적 목록을 유지하고(정책 범위 밖), Ollama는 라이브 서버(`/api/tags`)를 조회하므로 순수 파생이 불가능하다.

- [ ] **Step 4: 추천 티어를 파생으로 바꾼다**

`neos/utils/llm_factory.py` — import에 추가:

```python
from neos.config.model_config import tiers_for_provider
```

280~304행을 교체한다:

```python
def get_recommended_models(provider: str) -> dict[str, str]:
    """Provider별 추천 모델 (fast / balanced / powerful).

    모델 카탈로그(`neos/config/models.yaml`)의 `tiers`에서 파생된다.
    라우팅 역할이 아니라 운영자용 수동 참고값이다
    (`docs/CONFIGURATION.md` — Model Routing 참조).
    """
    return tiers_for_provider(provider)
```

- [ ] **Step 5: 파생이 연결됐는지 확인한다**

Step 2의 sentinel 스크립트를 다시 돌린다.
Expected: `['sentinel']`

- [ ] **Step 6: 교차 대조 테스트를 제거한다**

`tests/config/test_model_catalog_parity.py`에서 두 함수를 삭제한다:
- `test_crosscheck_list_models_against_hardcoded`
- `test_crosscheck_recommended_models_against_hardcoded`

절대값 단언(`test_catalog_selectable_lists_match_expected_order`, `test_catalog_tiers_match_expected`)이 남아 목록과 순서를 계속 지킨다.

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/providers tests/config -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 8: CLI 표시가 깨지지 않는지 확인한다**

```bash
python -c "
from neos.utils.llm_factory import get_recommended_models
for p in ('anthropic', 'openai', 'gemini', 'ollama'):
    print(p, get_recommended_models(p))
"
```
Expected: 네 provider 모두 `fast`/`balanced`/`powerful` 세 키를 갖는다. 특히 `gemini`의 `balanced`와 `powerful`이 모두 `gemini-1.5-pro-latest`, `ollama`의 `fast`와 `balanced`가 모두 `llama3.1:8b`여야 한다 (`neos/cli.py:1653`이 이 dict를 표시한다).

- [ ] **Step 9: 커밋**

```bash
git add neos/providers/anthropic.py neos/providers/openai.py \
        neos/utils/llm_factory.py \
        tests/config/test_model_catalog_parity.py \
        tests/providers/test_current_model_providers.py
git commit -m "refactor: derive provider model lists and tiers from the catalog"
```

---

## Task 5: 가격 이관

DB 우선순위는 그대로 두고, 하드코딩 폴백만 카탈로그로 교체한다.

**Files:**
- Modify: `neos/utils/cost_calculator.py:19-67` (`DEFAULT_PRICING` 삭제), `:117-133` (`_get_default_pricing`)
- Modify: `tests/test_cost_calculator.py:105-116` (`DEFAULT_PRICING` 직접 접근 제거)
- Modify: `tests/config/test_model_catalog_parity.py` (교차 대조 1건 제거)

**Interfaces:**
- Consumes: `pricing_for(provider, model) -> ModelPricing | None` (Task 1)
- Produces: `CostCalculator._get_default_pricing(provider, model_name) -> dict[str, Decimal] | None` — 시그니처·반환 형태 불변 (`input`/`output`/`cache_creation`/`cache_read` 키의 `Decimal`)

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/test_cost_calculator.py`의 105~116행 `test_get_default_pricing_current_model_catalog`를 아래로 교체한다:

```python
    def test_get_default_pricing_is_derived_from_the_model_catalog(self):
        from neos.config.model_config import pricing_for

        for provider, model in (
            ("anthropic", "claude-sonnet-5"),
            ("anthropic", "claude-opus-5"),
            ("openai", "gpt-5.6-terra"),
            ("openai", "gpt-5.6-sol"),
        ):
            catalog_pricing = pricing_for(provider, model)
            assert catalog_pricing is not None

            pricing = CostCalculator._get_default_pricing(provider, model)

            assert pricing is not None
            assert pricing["input"] == Decimal(str(catalog_pricing.input))
            assert pricing["output"] == Decimal(str(catalog_pricing.output))

    def test_get_default_pricing_current_model_values(self):
        anthropic_sonnet = CostCalculator._get_default_pricing(
            "anthropic", "claude-sonnet-5"
        )
        anthropic_opus = CostCalculator._get_default_pricing("anthropic", "claude-opus-5")
        openai_terra = CostCalculator._get_default_pricing("openai", "gpt-5.6-terra")
        openai_sol = CostCalculator._get_default_pricing("openai", "gpt-5.6-sol")

        assert anthropic_sonnet["input"] == Decimal("3.00")
        assert anthropic_sonnet["output"] == Decimal("15.00")
        assert anthropic_opus["input"] == Decimal("5.00")
        assert anthropic_opus["output"] == Decimal("25.00")
        assert openai_terra["input"] == Decimal("2.50")
        assert openai_terra["output"] == Decimal("15.00")
        assert openai_sol["input"] == Decimal("5.00")
        assert openai_sol["output"] == Decimal("30.00")

    def test_get_default_pricing_ignores_provider_mismatch(self):
        """provider가 어긋난 조회는 가격을 주지 않는다."""
        assert CostCalculator._get_default_pricing("openai", "claude-sonnet-5") is None
        assert CostCalculator._get_default_pricing("anthropic", "gpt-4o") is None

    def test_get_default_pricing_warns_for_unpriced_catalog_model(self, caplog):
        """카탈로그에 있지만 가격이 없는 모델은 경고 후 None (spec §6)."""
        with caplog.at_level("WARNING", logger="neos.utils.cost_calculator"):
            pricing = CostCalculator._get_default_pricing("anthropic", "claude-sonnet-4-6")

        assert pricing is None
        assert any("claude-sonnet-4-6" in record.message for record in caplog.records)

    def test_default_pricing_table_is_gone(self):
        """가격 하드코딩이 shim으로도 남지 않는다."""
        assert not hasattr(CostCalculator, "DEFAULT_PRICING")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_cost_calculator.py -p no:cacheprovider -q`
Expected: FAIL 1건 — `test_default_pricing_table_is_gone`: `assert not hasattr(CostCalculator, 'DEFAULT_PRICING')`.

나머지 새 테스트는 값이 같으므로 현재도 통과한다. 그것이 의도다 — **이관 후에도 같은 값이 나오는지**를 고정한다.

- [ ] **Step 3: `cost_calculator.py`를 카탈로그 파생으로 바꾼다**

11행 import 아래에 추가한다:

```python
from neos.config.model_config import pricing_for
```

19~67행의 `DEFAULT_PRICING` 블록 전체를 삭제하고, 클래스 본문을 아래로 시작하게 한다:

```python
class CostCalculator:
    """LLM 비용 계산기

    가격 우선순위: `llm_model_pricing` DB → `neos/config/models.yaml` → 경고 + None
    """

    @staticmethod
    async def get_model_pricing(
```

117~133행 `_get_default_pricing`을 교체한다:

```python
    @staticmethod
    def _get_default_pricing(
        provider: str, model_name: str
    ) -> Optional[Dict[str, Decimal]]:
        """모델 카탈로그의 가격을 반환한다 (DB 조회 실패/미등재 시 폴백)."""
        pricing = pricing_for(provider, model_name)
        if pricing is not None:
            return {
                "input": Decimal(str(pricing.input)),
                "output": Decimal(str(pricing.output)),
                "cache_creation": Decimal(str(pricing.cache_creation)),
                "cache_read": Decimal(str(pricing.cache_read)),
            }

        logger.warning(f"No pricing found for {provider}/{model_name}")
        return None
```

- [ ] **Step 4: 교차 대조 테스트를 제거한다**

`tests/config/test_model_catalog_parity.py`에서 `test_crosscheck_pricing_against_hardcoded` 함수 전체를 삭제한다. 절대값 단언 `test_catalog_pricing_matches_expected`가 12개 모델의 4개 가격 필드를 계속 지킨다.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_cost_calculator.py tests/config -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 6: 순환 import가 없는지 확인한다**

```bash
python -c "import neos.utils.cost_calculator; import neos.utils.llm_factory; print('ok')"
```
Expected: `ok`

- [ ] **Step 7: 커밋**

```bash
git add neos/utils/cost_calculator.py tests/test_cost_calculator.py \
        tests/config/test_model_catalog_parity.py
git commit -m "refactor: read fallback model pricing from the catalog"
```

---

## Task 6: 미등록 모델 경고 + 문서화

**Files:**
- Modify: `neos/utils/llm_factory.py` (모델별 1회 경고)
- Modify: `neos/config/model_config.py` (기동 시 `model_routing` 검사)
- Modify: `neos/main.py` (lifespan에서 호출)
- Modify: `docs/CONFIGURATION.md` (카탈로그 절 추가)
- Test: `tests/config/test_model_catalog.py` (경고 테스트 추가)

**Interfaces:**
- Consumes: `get_model_spec(model) -> ModelSpec | None` (Task 1), `neos.config.schema.ModelRoutingConfig`
- Produces: `warn_unknown_routed_models(routing: ModelRoutingConfig) -> list[str]` — 카탈로그에 없는 역할 기본값 모델 이름 목록 (경고를 낸 뒤 반환)

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/config/test_model_catalog.py` 끝에 추가한다:

```python
def test_unknown_model_warns_once_per_name(caplog) -> None:
    """카탈로그에 없는 모델은 통과시키되, 이름별로 한 번만 경고한다 (spec §6)."""
    from neos.utils.llm_factory import LLMFactory

    LLMFactory._warned_unknown_models.clear()

    with caplog.at_level("WARNING", logger="neos.utils.llm_factory"):
        LLMFactory._warn_if_unknown_model("claude-from-the-future")
        LLMFactory._warn_if_unknown_model("claude-from-the-future")
        LLMFactory._warn_if_unknown_model("claude-sonnet-5")

    warnings = [r for r in caplog.records if "claude-from-the-future" in r.message]
    assert len(warnings) == 1
    assert not [r for r in caplog.records if "claude-sonnet-5" in r.message]


def test_create_llm_warns_for_unregistered_model(caplog, monkeypatch) -> None:
    """미등록 모델은 예외가 아니라 경고로 통과한다."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from neos.utils.llm_factory import LLMFactory

    LLMFactory._warned_unknown_models.clear()
    LLMFactory.clear_cache()
    # settings 객체 전체를 바꾼다 — 실제 Settings에 setattr하면
    # validate_assignment가 걸리거나 다른 테스트로 상태가 새어 나간다.
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="test-key",
            LLM_TIMEOUT=30,
            THINKING_BLOCKS_ENABLED=False,
            MAX_THINKING_LENGTH=0,
        ),
    )

    with caplog.at_level("WARNING", logger="neos.utils.llm_factory"):
        with patch("neos.providers.anthropic.ChatAnthropic"):
            LLMFactory.create_llm(
                provider="anthropic",
                model="claude-not-in-catalog",
                temperature=0.3,
                use_cache=False,
            )

    assert any("claude-not-in-catalog" in r.message for r in caplog.records)


def test_warn_unknown_routed_models_flags_typos(caplog) -> None:
    from neos.config.model_config import warn_unknown_routed_models
    from neos.config.schema import ModelRoutingConfig

    routing = ModelRoutingConfig.model_validate(
        {
            "anthropic": {"everyday": "claude-sonnet-5", "powerful": "claude-opus-5"},
            "openai": {"everyday": "gpt-5.6-tera", "powerful": "gpt-5.6-sol"},
        }
    )

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        unknown = warn_unknown_routed_models(routing)

    assert unknown == ["gpt-5.6-tera"]
    assert any("gpt-5.6-tera" in record.message for record in caplog.records)


def test_warn_unknown_routed_models_is_silent_for_committed_defaults(caplog) -> None:
    from neos.config.model_config import warn_unknown_routed_models
    from neos.config.schema import ModelRoutingConfig

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        unknown = warn_unknown_routed_models(ModelRoutingConfig())

    assert unknown == []
    assert not [r for r in caplog.records if "model_routing" in r.message]


def test_main_lifespan_checks_routed_models_against_the_catalog() -> None:
    """기동 경로에 검사가 연결돼 있는지 소스로 고정한다."""
    source = Path("neos/main.py").read_text(encoding="utf-8")

    assert "warn_unknown_routed_models" in source
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog.py -p no:cacheprovider -q`
Expected: FAIL 5건 — `AttributeError: type object 'LLMFactory' has no attribute '_warned_unknown_models'`, `ImportError: cannot import name 'warn_unknown_routed_models'`, `assert "warn_unknown_routed_models" in source` 실패.

- [ ] **Step 3: `llm_factory.py`에 모델별 1회 경고를 넣는다**

Task 4에서 추가한 import에 `get_model_spec`를 더한다:

```python
from neos.config.model_config import get_model_spec, tiers_for_provider
```

`LLMFactory` 클래스에서 `_llm_cache` 선언(48행) 아래에 추가한다:

```python
    # 카탈로그에 없는 모델을 이미 경고한 이름들 — 로그 폭주를 막는다
    _warned_unknown_models: set[str] = set()
```

`_get_cache_key` 위에 메서드를 추가한다:

```python
    @classmethod
    def _warn_if_unknown_model(cls, model: str) -> None:
        """카탈로그에 없는 모델을 이름별 1회 경고한다.

        카탈로그는 allowlist가 아니다 — 카탈로그 갱신 전에도 신종 모델을
        지정할 수 있어야 하므로 통과시킨다. 다만 그 모델의 가격과 thinking
        계약은 기본값으로 떨어진다.
        """
        if model in cls._warned_unknown_models:
            return
        if get_model_spec(model) is not None:
            return
        cls._warned_unknown_models.add(model)
        logger.warning(
            "Model %r is not declared in the model catalog "
            "(neos/config/models.yaml); pricing and thinking contract fall back "
            "to defaults",
            model,
        )
```

`create_llm`에서 `resolved_model`을 정한 직후(129행 아래)에 호출을 추가한다:

```python
        resolved_model = model or cls._resolve_default_model(provider_name)
        cls._warn_if_unknown_model(resolved_model)
```

캐시 조회보다 앞에 두어 캐시 히트에도 경고가 한 번은 도달하게 한다. `_warned_unknown_models`가 중복을 막는다.

- [ ] **Step 4: `model_config.py`에 기동 검사를 넣는다**

`neos/config/model_config.py` 파일 끝에 추가한다:

```python
def warn_unknown_routed_models(routing: "ModelRoutingConfig") -> list[str]:
    """역할 기본값이 카탈로그에 없는 모델을 가리키면 경고한다.

    예외는 던지지 않는다 — 카탈로그 갱신 전에도 배포에서 신종 모델을
    지정할 수 있어야 한다(spec §6). 오타는 로그로 드러난다.

    기능 오버라이드(`coding_model.model`, `deep_analysis.models.*` 등)는
    검사하지 않는다. 그 값들은 `create_llm(model=...)`로 흘러가 거기서
    모델별 1회 경고를 받는다. 반면 역할 기본값은 `model=`을 생략한
    경로에서만 쓰여 사용 시점 경고가 늦으므로, 기동 검사의 값이 여기에 있다.

    Returns:
        카탈로그에 없던 모델 이름 목록 (선언 순서).
    """
    catalog = model_config.catalog
    unknown: list[str] = []
    for provider in ("anthropic", "openai"):
        provider_roles = getattr(routing, provider)
        for role in ("everyday", "powerful"):
            model = getattr(provider_roles, role)
            if model and catalog.get_model_spec(model) is None:
                unknown.append(model)
                logger.warning(
                    "model_routing.%s.%s = %r is not declared in the model catalog "
                    "(neos/config/models.yaml) — check for a typo",
                    provider,
                    role,
                    model,
                )
    return unknown
```

모듈 상단의 `from typing import Any, Literal` 아래에 타입 전용 import를 추가한다 (런타임 import는 순환을 만들지 않지만, 이 모듈은 스키마 정의만 필요하므로 TYPE_CHECKING으로 둔다):

```python
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from neos.config.schema import ModelRoutingConfig
```

- [ ] **Step 5: `main.py` lifespan에서 호출한다**

`neos/main.py`의 lifespan에서 OpenTelemetry 초기화 직후, DB 초기화 **앞**에 넣는다 (파일만 읽으므로 DB보다 먼저 실행할 수 있다). 141~145행의 텔레메트리 블록 뒤에 추가한다:

```python
        # 모델 카탈로그와 라우팅 정책 정합성 확인 (경고만 — 부팅을 막지 않는다)
        from neos.config.model_config import warn_unknown_routed_models

        warn_unknown_routed_models(settings.config.model_routing)
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/config/test_model_catalog.py -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 7: `docs/CONFIGURATION.md`에 카탈로그 절을 추가한다**

`### Model Routing` 절(139행) **바로 앞**에 아래를 넣는다. 카탈로그가 모델 *사실*, `model_routing`이 배포 *정책*이라는 구분을 독자가 순서대로 만나게 된다.

```markdown
### Model Catalog

`neos/config/models.yaml` is the single source of truth for facts *about*
models — which ones the pickers offer, which recommendation tier they fill,
which thinking contract they follow, and what they cost. Adding a new Claude or
GPT model is an edit to this one file.

```yaml
models:
  claude-sonnet-5:
    provider: anthropic          # anthropic | openai | gemini | ollama
    tiers: [balanced]            # fast | balanced | powerful (a model may fill two)
    thinking: adaptive           # adaptive | budgeted | none
    selectable: true             # exposed by list_models() (default true)
    max_tokens: 8192
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}
```

Declaration order is the `list_models()` order, so keep newest models first.

| Field | Consumer |
|---|---|
| `provider` + `selectable` | `AnthropicProvider.list_models()`, `OpenAIProvider.list_models()` |
| `tiers` | `get_recommended_models(provider)` |
| `thinking` | `normalize_anthropic_request()` |
| `pricing` | `CostCalculator._get_default_pricing()` |

`thinking` names the request *contract*, not the model generation. A future
Claude that uses adaptive thinking needs one line — `thinking: adaptive` — and
no code change:

| Value | Behavior |
|---|---|
| `adaptive` | sends `thinking={"type": "adaptive"}` and strips `temperature`, `top_p`, `top_k`. A caller-supplied `budget_tokens` raises `ValueError` |
| `budgeted` | legacy path — honors `THINKING_BLOCKS_ENABLED` / `MAX_THINKING_LENGTH` and forces `temperature=1.0` |
| `none` | no thinking support; the payload is left alone |

A model absent from the catalog defaults to `budgeted`, which preserves the
behavior unknown Anthropic models had before the catalog existed.

`selectable: false` marks models the system still knows a price or a legacy
alias for but does not offer in a picker — for example `gpt-4o`, which
`aliases.vision.gpt4o` resolves to. It exists because `list_models()` and the
pricing table used to disagree: models were selectable with no price, and their
cost silently aggregated as zero.

Derivation applies to Anthropic and OpenAI only. Gemini keeps a static
`list_models()` (out of routing-policy scope) and Ollama queries its live
server at `/api/tags`, so neither list can be derived. Their `tiers` still live
in the catalog so `get_recommended_models()` covers all four providers, and
their entries are marked `selectable: false` to make that split explicit.

#### The catalog is not an allowlist

An unlisted model passes through and only produces a warning, so a brand-new
model can be used before the catalog is updated:

- `create_llm(model=...)` logs a warning **once per model name**.
- Cost aggregation warns and records zero when no price is known.
- `model_routing` role defaults are checked at startup and warn only — they
  never raise. Feature override fields are not checked there because their
  values reach `create_llm(model=...)`, which already warns.

Pricing resolves in three layers, and the database still wins:

```
llm_model_pricing DB (time-bounded)  →  models.yaml pricing  →  warn + no price
```

#### Legacy catalog files

`NEOS_MODEL_CONFIG_PATH` can point at a custom file. A file with no `models:`
key is read in the old shape (`vision_models` / `llm_models` /
`embedding_models`), converted in memory, and logged with a migration notice.
Converted entries have no tier and no price, and fall back to
`thinking: budgeted`. Provider `google` is normalized to `gemini`.
```

- [ ] **Step 8: 문서 링크와 코드 참조가 맞는지 확인한다**

Run: `python -m pytest tests/config -p no:cacheprovider -q`
Expected: PASS. `tests/config/test_config_files.py`는 `config/neos.*.yaml`만 검사하므로 `neos/config/models.yaml`에는 영향이 없다.

- [ ] **Step 9: 커밋**

```bash
git add neos/utils/llm_factory.py neos/config/model_config.py neos/main.py \
        docs/CONFIGURATION.md tests/config/test_model_catalog.py
git commit -m "feat: warn when a model is missing from the catalog"
```

---

## Task 7: 전체 회귀 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 스위트를 돌린다**

Run: `python -m pytest -p no:cacheprovider -q 2>&1 | tail -30`
Expected: `2112 passed` 이상, 0 failed.

> 이 스위트는 결정론적이다 (`docs/role_based_model_routing_task_resume.md` §8). 실패가 나오면 진짜 회귀다.
> 실패 목록을 뽑을 때는 `grep '^FAILED tests/'`를 쓴다 — `grep '^FAILED'`는 라이브 로그의 진행 표시(`FAILED   [ 7%]`)까지 잡는다.

- [ ] **Step 2: 새 모델 추가가 config 한 파일로 끝나는지 확인한다**

성공 기준(spec §11)의 실증이다. 카탈로그에 가상의 모델을 추가하고 네 소비자가 모두 반응하는지 확인한 뒤 되돌린다.

```bash
python - <<'PY'
from pathlib import Path

path = Path("neos/config/models.yaml")
original = path.read_text(encoding="utf-8")
entry = """
  claude-sonnet-6:
    provider: anthropic
    thinking: adaptive
    pricing: {input: 3.50, output: 17.50}
"""
# 첫 모델 항목 앞에 삽입
marker = "  claude-sonnet-5:"
path.write_text(original.replace(marker, entry.strip("\n") + "\n\n" + marker, 1), encoding="utf-8")

try:
    from neos.config.model_config import model_config, thinking_contract, pricing_for
    from neos.providers.anthropic import AnthropicProvider
    model_config.reload()
    print("list_models:", AnthropicProvider.__new__(AnthropicProvider).list_models()[:2])
    print("thinking:", thinking_contract("claude-sonnet-6"))
    print("pricing:", pricing_for("anthropic", "claude-sonnet-6"))
finally:
    path.write_text(original, encoding="utf-8")
PY
```
Expected:
- `list_models: ['claude-sonnet-6', 'claude-sonnet-5']`
- `thinking: ThinkingContract.ADAPTIVE`
- `pricing: input=3.5 output=17.5 cache_creation=0.0 cache_read=0.0`

파이썬 코드는 한 줄도 바뀌지 않았다.

- [ ] **Step 3: 파일이 원상 복구됐는지 확인한다**

Run: `git diff --stat neos/config/models.yaml`
Expected: 출력 없음.

- [ ] **Step 4: 코드 리뷰를 요청한다**

REQUIRED SUB-SKILL: `superpowers:requesting-code-review`. Task 1의 첫 커밋 직전을 `BASE_SHA`로, Task 6의 커밋을 `HEAD_SHA`로 넘긴다.

- [ ] **Step 5: 개발 브랜치를 마무리한다**

REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch`.

---

## 부수 변경 기록

이관 과정에서 생기는, 명시적으로 수용한 동작 변화들이다.

| 변화 | 영향 | 판단 |
|---|---|---|
| `get_vision_model('gemini')['provider']`가 `"google"` → `"gemini"` | `examples/test_model_config.py`의 출력만. `pytest` `testpaths=tests`이므로 수집되지 않는다 | 수용 — LLMFactory 프로바이더 키로 통일하는 것이 옳다 |
| 레거시 dict에서 `pricing`·`tiers` 키 제외 | 소비자 없음 | 수용 |
| `models.yaml` 누락 시 하드코딩 폴백 대신 빈 카탈로그 | 파일은 커밋돼 있다. 누락은 배포 오류이며 `logger.error`로 드러난다 | 수용 — `_get_default_config()`의 낡은 하드코딩을 되살리는 것이 더 나쁘다 |
| `gemini-2.5-flash-lite`가 카탈로그에 없음 | `GeminiProvider.list_models()`는 정적 목록을 유지하므로 계속 노출된다 | 수용 — 티어도 가격도 없어 카탈로그에 담을 사실이 없다 |
| `budget_tokens` 거부 메시지가 "Claude 5" → "adaptive thinking contract" | `tests/providers/test_current_model_providers.py:135`의 `match` 갱신 | 의도 — 버전이 박힌 표현을 없앤다 |

## 남는 알려진 격차

- `get_recommended_models("openai")["fast"]`는 `gpt-5-mini-2025-08-07`로 남는다. GPT-5.6 세대의 소형 모델 ID가 공개되지 않았으므로 발명하지 않는다.
- `claude-sonnet-4-6`, `claude-opus-4-6`, `gpt-5-mini-2025-08-07`, `gpt-5-2025-08-07`, `o3`, `o3-mini`는 선택 가능하지만 가격이 없다. 현행과 동일하며, 이제 `test_every_selectable_model_without_pricing_is_known`이 이 목록을 고정해 새 모델이 조용히 추가되는 것을 막는다.
