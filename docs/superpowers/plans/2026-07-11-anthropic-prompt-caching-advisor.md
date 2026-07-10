# Anthropic Prompt Caching and Advisor Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add default-on prompt caching to reusable Anthropic request paths and default-off, config-controlled Advisor injection to the multi-round tool-search loop with correct continuation and billing.

**Architecture:** Typed `llm.prompt_caching` and `llm.advisor` configuration feeds two focused Anthropic helper modules: one builds request features and preserves beta blocks, while the other normalizes usage and calculates executor-plus-Advisor cost. Chat services apply automatic caching only on conversational paths; the tool-search loop adds a stable tool breakpoint and conditionally selects the beta API; contextual retrieval warms the existing document cache before parallel fan-out.

**Tech Stack:** Python 3.12, Pydantic v2, Anthropic Python SDK 0.102.0, LangChain Anthropic 1.4.3, pytest, pytest-asyncio.

## Global Constraints

- Prompt caching defaults to enabled with TTL exactly `5m`; allowed TTL values are `5m` and `1h`.
- Advisor defaults to disabled and must not appear in any request unless `llm.advisor.enabled` is true and the executor/advisor pair is compatible.
- Advisor defaults are model `claude-opus-4-8`, `max_uses: 2`, `max_tokens: 2048`, and `max_pause_turns: 3`.
- Advisor-side caching defaults to disabled; enable it independently only for conversations expected to make at least three Advisor calls.
- Advisor injection is limited to `generate_response_stream_with_tool_search` in this implementation.
- Do not add cache writes to artifact generation, deep-analysis JSON calls, or vision requests.
- Do not change the default chat model or add a database migration.
- Never expose prompt text or raw Advisor guidance in logs or metrics.
- Preserve the user's existing uncommitted `.env.template`, `AGENTS.md`, `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md`, and `docs/DEVELOPMENT_SETUP.md` changes.

---

## File Structure

- Create `neos/providers/anthropic_features.py`: pure request-policy, model compatibility, tool-copying, Advisor definition, and content-block serialization.
- Create `neos/providers/anthropic_usage.py`: Anthropic usage normalization, cache classification, iteration aggregation, and composite cost calculation.
- Modify `neos/config/schema.py`: typed prompt-cache and Advisor settings.
- Modify `neos/config/settings.py`: exact uppercase compatibility aliases for nested settings.
- Modify `config/neos.default.yaml` and `config/neos.example.yaml`: committed defaults and example overrides.
- Modify `docs/CONFIGURATION.md`: operator-facing configuration and rollout guidance.
- Modify `neos/utils/cost_calculator.py`: current Anthropic fallback prices, 1-hour cache-write pricing, and persisted additional iteration cost.
- Modify `neos/services/chat_llm_service.py`: automatic cache request fields, normalized usage, composite cost, beta Advisor loop, and `pause_turn` continuation.
- Modify chat persistence callers under `neos/api/`: forward cache tokens and additional iteration cost.
- Modify `neos/pipelines/document/contextual_retrieval.py`: warm the document cache before concurrent fan-out.
- Create focused tests below `tests/unit/` and extend existing config/cost tests.

---

### Task 1: Typed Feature Configuration

**Files:**
- Modify: `neos/config/schema.py`
- Modify: `neos/config/settings.py`
- Modify: `config/neos.default.yaml`
- Modify: `config/neos.example.yaml`
- Modify: `docs/CONFIGURATION.md`
- Test: `tests/config/test_config_schema.py`
- Test: `tests/config/test_settings_compat.py`
- Test: `tests/config/test_config_files.py`

**Interfaces:**
- Consumes: `StrictConfigModel` and `LLMConfig` from `neos.config.schema`.
- Produces: `PromptCachingConfig`, `AdvisorPromptCachingConfig`, `AdvisorConfig`, `LLMConfig.prompt_caching`, and `LLMConfig.advisor`.
- Produces compatibility names: `LLM_PROMPT_CACHING_ENABLED`, `LLM_PROMPT_CACHING_TTL`, `LLM_ADVISOR_ENABLED`, `LLM_ADVISOR_MODEL`, `LLM_ADVISOR_MAX_USES`, `LLM_ADVISOR_MAX_TOKENS`, `LLM_ADVISOR_MAX_PAUSE_TURNS`, `LLM_ADVISOR_PROMPT_CACHING_ENABLED`, and `LLM_ADVISOR_PROMPT_CACHING_TTL`.

- [ ] **Step 1: Write failing schema and compatibility tests**

Add to `tests/config/test_config_schema.py`:

```python
@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_anthropic_feature_config_accepts_supported_cache_ttls(ttl):
    config = AppConfig.model_validate(
        {
            "llm": {
                "prompt_caching": {"ttl": ttl},
                "advisor": {"prompt_caching": {"ttl": ttl}},
            }
        }
    )

    assert config.llm.prompt_caching.ttl == ttl
    assert config.llm.advisor.prompt_caching.ttl == ttl


def test_anthropic_feature_config_defaults():
    config = AppConfig()

    assert config.llm.prompt_caching.enabled is True
    assert config.llm.prompt_caching.ttl == "5m"
    assert config.llm.advisor.enabled is False
    assert config.llm.advisor.model == "claude-opus-4-8"
    assert config.llm.advisor.max_uses == 2
    assert config.llm.advisor.max_tokens == 2048
    assert config.llm.advisor.max_pause_turns == 3
    assert config.llm.advisor.prompt_caching.enabled is False


@pytest.mark.parametrize(
    "advisor",
    [
        {"max_uses": 0},
        {"max_tokens": 1023},
        {"max_pause_turns": -1},
        {"prompt_caching": {"ttl": "30m"}},
    ],
)
def test_anthropic_feature_config_rejects_invalid_values(advisor):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llm": {"advisor": advisor}})
```

Add to `tests/config/test_settings_compat.py`:

```python
def test_nested_anthropic_feature_settings_have_legacy_aliases():
    local_settings = Settings(config=AppConfig())

    assert local_settings.LLM_PROMPT_CACHING_ENABLED is True
    assert local_settings.LLM_PROMPT_CACHING_TTL == "5m"
    assert local_settings.LLM_ADVISOR_ENABLED is False
    assert local_settings.LLM_ADVISOR_MODEL == "claude-opus-4-8"
    assert local_settings.LLM_ADVISOR_MAX_USES == 2
    assert local_settings.LLM_ADVISOR_MAX_TOKENS == 2048
    assert local_settings.LLM_ADVISOR_MAX_PAUSE_TURNS == 3
    assert local_settings.LLM_ADVISOR_PROMPT_CACHING_ENABLED is False
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/config/test_config_schema.py tests/config/test_settings_compat.py -q
```

Expected: failures because `LLMConfig` has no `prompt_caching` or `advisor` fields and the compatibility aliases cannot resolve.

- [ ] **Step 3: Implement the typed schema and aliases**

Insert before `LLMConfig` in `neos/config/schema.py`:

```python
class PromptCachingConfig(StrictConfigModel):
    enabled: bool = True
    ttl: Literal["5m", "1h"] = "5m"


class AdvisorPromptCachingConfig(PromptCachingConfig):
    enabled: bool = False


class AdvisorConfig(StrictConfigModel):
    enabled: bool = False
    model: str = "claude-opus-4-8"
    max_uses: int = Field(default=2, ge=1)
    max_tokens: int = Field(default=2048, ge=1024)
    max_pause_turns: int = Field(default=3, ge=0)
    prompt_caching: AdvisorPromptCachingConfig = Field(
        default_factory=AdvisorPromptCachingConfig
    )
```

Extend `LLMConfig`:

```python
class LLMConfig(StrictConfigModel):
    provider: str = "anthropic"
    model: str = "gpt-4-turbo-preview"
    temperature: float = 0.1
    timeout: int = 120
    research_planning_timeout: int = 180
    fast_model: str = "claude-haiku-4-5-20251001"
    prompt_caching: PromptCachingConfig = Field(default_factory=PromptCachingConfig)
    advisor: AdvisorConfig = Field(default_factory=AdvisorConfig)
```

Add exact paths to `LEGACY_EXACT_PATHS` in `neos/config/settings.py`:

```python
"LLM_PROMPT_CACHING_ENABLED": "llm.prompt_caching.enabled",
"LLM_PROMPT_CACHING_TTL": "llm.prompt_caching.ttl",
"LLM_ADVISOR_ENABLED": "llm.advisor.enabled",
"LLM_ADVISOR_MODEL": "llm.advisor.model",
"LLM_ADVISOR_MAX_USES": "llm.advisor.max_uses",
"LLM_ADVISOR_MAX_TOKENS": "llm.advisor.max_tokens",
"LLM_ADVISOR_MAX_PAUSE_TURNS": "llm.advisor.max_pause_turns",
"LLM_ADVISOR_PROMPT_CACHING_ENABLED": "llm.advisor.prompt_caching.enabled",
"LLM_ADVISOR_PROMPT_CACHING_TTL": "llm.advisor.prompt_caching.ttl",
```

- [ ] **Step 4: Add YAML defaults and operator documentation**

Add the exact nested blocks from the design spec to both committed YAML files. Add a `### Anthropic prompt caching and Advisor` section to `docs/CONFIGURATION.md` explaining default-on `5m` caching, default-off Advisor, compatible executor requirement, `pause_turn` cap, and the three-call threshold for Advisor-side caching. Do not modify `.env.template`; these are non-secret YAML settings.

- [ ] **Step 5: Run config tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/config/test_config_schema.py tests/config/test_settings_compat.py tests/config/test_config_files.py -q
```

Expected: all selected config tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add neos/config/schema.py neos/config/settings.py config/neos.default.yaml config/neos.example.yaml docs/CONFIGURATION.md tests/config/test_config_schema.py tests/config/test_settings_compat.py
git commit -m "feat(config): add Anthropic caching and advisor settings"
```

---

### Task 2: Anthropic Request Feature Policy

**Files:**
- Create: `neos/providers/anthropic_features.py`
- Create: `tests/unit/providers/test_anthropic_features.py`

**Interfaces:**
- Consumes: `PromptCachingConfig` and `AdvisorConfig` from Task 1.
- Produces: `ADVISOR_BETA`, `AdvisorDecision`, `AnthropicToolPolicy`, `build_cache_control`, `canonical_model_family`, `build_tool_policy`, and `serialize_content_block`.
- `build_tool_policy(tools, executor_model, prompt_caching, advisor) -> AnthropicToolPolicy` is consumed by Task 5.

- [ ] **Step 1: Write failing request-policy tests**

Create `tests/unit/providers/test_anthropic_features.py`:

```python
from types import SimpleNamespace

from neos.config.schema import AdvisorConfig, PromptCachingConfig
from neos.providers.anthropic_features import (
    ADVISOR_BETA,
    build_cache_control,
    build_tool_policy,
    serialize_content_block,
)


def test_build_cache_control_respects_enabled_and_ttl():
    assert build_cache_control(PromptCachingConfig()) == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert build_cache_control(PromptCachingConfig(enabled=False)) is None
    assert build_cache_control(PromptCachingConfig(ttl="1h"))["ttl"] == "1h"


def test_tool_policy_copies_tools_and_marks_last_stable_tool():
    original = [{"name": "search_tools", "input_schema": {"type": "object"}}]

    policy = build_tool_policy(
        original,
        executor_model="claude-sonnet-4-6",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=False),
    )

    assert original[0].get("cache_control") is None
    assert policy.tools[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert policy.use_beta is False
    assert policy.advisor.injected is False


def test_tool_policy_injects_advisor_only_for_compatible_pair():
    policy = build_tool_policy(
        [{"name": "search_tools", "input_schema": {"type": "object"}}],
        executor_model="claude-sonnet-4-6",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True, model="claude-opus-4-8"),
    )

    assert policy.use_beta is True
    assert policy.betas == [ADVISOR_BETA]
    assert policy.tools[-1]["type"] == "advisor_20260301"
    assert policy.tools[-1]["name"] == "advisor"
    assert policy.tools[-1]["max_tokens"] == 2048
    assert policy.tools[-1]["cache_control"]["type"] == "ephemeral"
    assert policy.advisor.injected is True


def test_tool_policy_skips_unknown_or_incompatible_executor():
    unknown = build_tool_policy(
        [],
        executor_model="claude-future-99",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True),
    )
    incompatible = build_tool_policy(
        [],
        executor_model="claude-sonnet-4-5-20250929",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True),
    )

    assert unknown.advisor.skip_reason == "unknown_executor_model"
    assert incompatible.advisor.skip_reason == "incompatible_model_pair"
    assert unknown.use_beta is False
    assert incompatible.use_beta is False


def test_serialize_content_block_preserves_beta_fields():
    block = SimpleNamespace(
        model_dump=lambda **_: {
            "type": "advisor_tool_result",
            "tool_use_id": "srv_1",
            "content": {"type": "advisor_result", "text": "internal guidance"},
        }
    )

    assert serialize_content_block(block)["content"]["text"] == "internal guidance"
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/providers/test_anthropic_features.py -q
```

Expected: collection error because `neos.providers.anthropic_features` does not exist.

- [ ] **Step 3: Implement the pure request policy**

Create `neos/providers/anthropic_features.py` with immutable result dataclasses, a canonical model-family mapper, the exact compatibility table from the design document's Anthropic reference, deep-copied tool definitions, and full block serialization. The core shape is:

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from neos.config.schema import AdvisorConfig, PromptCachingConfig

ADVISOR_BETA = "advisor-tool-2026-03-01"

_MODEL_PREFIXES = (
    ("claude-haiku-4-5", "haiku-4.5"),
    ("claude-sonnet-4-5", "sonnet-4.5"),
    ("claude-sonnet-4-6", "sonnet-4.6"),
    ("claude-sonnet-5", "sonnet-5"),
    ("claude-opus-4-6", "opus-4.6"),
    ("claude-opus-4-7", "opus-4.7"),
    ("claude-opus-4-8", "opus-4.8"),
    ("claude-fable-5", "fable-5"),
    ("claude-mythos-5", "mythos-5"),
)

_ADVISOR_COMPATIBILITY = {
    "haiku-4.5": {"sonnet-4.6", "opus-4.6", "opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "sonnet-4.6": {"sonnet-4.6", "opus-4.6", "opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "sonnet-5": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.6": {"opus-4.6", "opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.7": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.8": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "fable-5": {"fable-5"},
    "mythos-5": {"mythos-5"},
}


@dataclass(frozen=True)
class AdvisorDecision:
    requested: bool
    injected: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class AnthropicToolPolicy:
    tools: list[dict[str, Any]]
    betas: list[str]
    use_beta: bool
    advisor: AdvisorDecision


def build_cache_control(config: PromptCachingConfig) -> dict[str, str] | None:
    if not config.enabled:
        return None
    return {"type": "ephemeral", "ttl": config.ttl}


def canonical_model_family(model: str) -> str | None:
    normalized = model.lower()
    for prefix, family in _MODEL_PREFIXES:
        if normalized.startswith(prefix):
            return family
    return None


def build_tool_policy(
    tools: Iterable[dict[str, Any]],
    *,
    executor_model: str,
    prompt_caching: PromptCachingConfig,
    advisor: AdvisorConfig,
) -> AnthropicToolPolicy:
    copied_tools = deepcopy(list(tools))
    decision = AdvisorDecision(requested=advisor.enabled, injected=False)
    betas: list[str] = []

    if advisor.enabled:
        executor_family = canonical_model_family(executor_model)
        advisor_family = canonical_model_family(advisor.model)
        if executor_family is None:
            decision = AdvisorDecision(True, False, "unknown_executor_model")
        elif advisor_family is None or advisor_family not in _ADVISOR_COMPATIBILITY.get(
            executor_family, set()
        ):
            decision = AdvisorDecision(True, False, "incompatible_model_pair")
        else:
            advisor_tool: dict[str, Any] = {
                "type": "advisor_20260301",
                "name": "advisor",
                "model": advisor.model,
                "max_uses": advisor.max_uses,
                "max_tokens": advisor.max_tokens,
            }
            advisor_cache = build_cache_control(advisor.prompt_caching)
            if advisor_cache:
                advisor_tool["caching"] = advisor_cache
            copied_tools.append(advisor_tool)
            betas.append(ADVISOR_BETA)
            decision = AdvisorDecision(True, True)

    cache_control = build_cache_control(prompt_caching)
    if copied_tools and cache_control:
        copied_tools[-1]["cache_control"] = cache_control

    return AnthropicToolPolicy(
        tools=copied_tools,
        betas=betas,
        use_beta=decision.injected,
        advisor=decision,
    )


def serialize_content_block(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    if isinstance(block, dict):
        return deepcopy(block)
    raise TypeError(f"Unsupported Anthropic content block: {type(block).__name__}")
```

`build_tool_policy` must append the Advisor definition before applying the explicit breakpoint so the breakpoint includes every stable tool. Advisor-side `caching` uses `advisor.prompt_caching`; the tool-level `cache_control` uses the executor's `prompt_caching`.

- [ ] **Step 4: Run request-policy tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/unit/providers/test_anthropic_features.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add neos/providers/anthropic_features.py tests/unit/providers/test_anthropic_features.py
git commit -m "feat(anthropic): add request feature policy"
```

---

### Task 3: Cache Usage and Composite Billing

**Files:**
- Create: `neos/providers/anthropic_usage.py`
- Create: `tests/unit/providers/test_anthropic_usage.py`
- Modify: `neos/utils/cost_calculator.py`
- Modify: `tests/test_cost_calculator.py`

**Interfaces:**
- Consumes: Anthropic SDK usage objects or equivalent dictionaries.
- Produces: `normalize_anthropic_usage(usage, model, cache_requested) -> dict[str, Any]`.
- Produces: `calculate_anthropic_cost(usage, executor_model, executor_cache_ttl, advisor_cache_ttl, calculator) -> dict[str, Any]`.
- Extends `CostCalculator.calculate_cost` and persistence methods with `cache_ttl` and `additional_cost_usd`.

- [ ] **Step 1: Write failing usage and pricing tests**

Create `tests/unit/providers/test_anthropic_usage.py` with a fake usage object that includes `iterations`:

```python
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.providers.anthropic_usage import (
    calculate_anthropic_cost,
    normalize_anthropic_usage,
)


def test_normalize_usage_keeps_cache_categories_separate():
    usage = SimpleNamespace(
        input_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1000,
        output_tokens=25,
        iterations=[],
    )

    result = normalize_anthropic_usage(
        usage,
        model="claude-sonnet-4-6",
        cache_requested=True,
    )

    assert result["prompt_tokens"] == 50
    assert result["cache_creation_tokens"] == 0
    assert result["cache_read_tokens"] == 1000
    assert result["total_input_tokens"] == 1050
    assert result["total_tokens"] == 1075
    assert result["cache_status"] == "hit"


@pytest.mark.asyncio
async def test_composite_cost_prices_executor_and_advisor_iterations():
    usage = SimpleNamespace(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=500,
        output_tokens=20,
        iterations=[
            SimpleNamespace(
                type="message",
                input_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=500,
                output_tokens=20,
            ),
            SimpleNamespace(
                type="advisor_message",
                model="claude-opus-4-8",
                input_tokens=200,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                output_tokens=40,
            ),
        ],
    )
    calculator = AsyncMock(
        side_effect=[
            {"total_cost": Decimal("0.01")},
            {"total_cost": Decimal("0.20")},
            {"total_cost": Decimal("0.01")},
        ]
    )

    result = await calculate_anthropic_cost(
        usage,
        executor_model="claude-sonnet-4-6",
        executor_cache_ttl="5m",
        advisor_cache_ttl="5m",
        calculator=calculator,
    )

    assert result["total_cost"] == Decimal("0.21")
    assert result["advisor_cost"] == Decimal("0.20")
    assert result["additional_cost"] == Decimal("0.20")
    assert result["advisor"]["call_count"] == 1
```

Extend `tests/test_cost_calculator.py` to assert current official fallback prices for Haiku 4.5, Sonnet 4.6, and Opus 4.8, and add:

```python
@pytest.mark.asyncio
async def test_one_hour_cache_creation_uses_twice_input_price(mock_db_manager):
    mock_db_manager.fetch_one = AsyncMock(return_value=None)

    cost = await CostCalculator.calculate_cost(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        prompt_tokens=0,
        completion_tokens=0,
        cache_creation_tokens=1_000_000,
        cache_ttl="1h",
    )

    assert cost["cache_creation_cost"] == Decimal("6.00")
```

- [ ] **Step 2: Run usage and cost tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/providers/test_anthropic_usage.py tests/test_cost_calculator.py -q
```

Expected: import failure for `anthropic_usage`, missing `cache_ttl`, and stale fallback-price assertions.

- [ ] **Step 3: Implement normalization and iteration billing**

Create `neos/providers/anthropic_usage.py`. Use one accessor that reads both dictionaries and SDK models, normalize every iteration into a plain dictionary, classify cache status from the API fields and documented model minimums, and calculate each iteration using its own model. Calculate a top-level base cost separately so:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any, Awaitable, Callable


def _field(value: Any, name: str, default: Any = 0) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _tokens(value: Any, name: str) -> int:
    return int(_field(value, name, 0) or 0)


def normalize_anthropic_usage(
    usage: Any,
    *,
    model: str,
    cache_requested: bool,
) -> dict[str, Any]:
    prompt_tokens = _tokens(usage, "input_tokens")
    cache_creation_tokens = _tokens(usage, "cache_creation_input_tokens")
    cache_read_tokens = _tokens(usage, "cache_read_input_tokens")
    completion_tokens = _tokens(usage, "output_tokens")
    total_input_tokens = prompt_tokens + cache_creation_tokens + cache_read_tokens

    if cache_read_tokens:
        cache_status = "hit"
    elif cache_creation_tokens:
        cache_status = "write"
    elif not cache_requested:
        cache_status = "disabled"
    elif prompt_tokens < cache_minimum_tokens(model):
        cache_status = "ineligible"
    else:
        cache_status = "miss"

    iterations = []
    for item in _field(usage, "iterations", []) or []:
        iterations.append(
            {
                "type": _field(item, "type", "message"),
                "model": _field(item, "model", None),
                "input_tokens": _tokens(item, "input_tokens"),
                "cache_creation_tokens": _tokens(item, "cache_creation_input_tokens"),
                "cache_read_tokens": _tokens(item, "cache_read_input_tokens"),
                "output_tokens": _tokens(item, "output_tokens"),
            }
        )

    return {
        "prompt_tokens": prompt_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_input_tokens": total_input_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_input_tokens + completion_tokens,
        "cache_status": cache_status,
        "iterations": iterations,
    }


CostCalculatorFn = Callable[..., Awaitable[dict[str, Any]]]


async def calculate_anthropic_cost(
    usage: Any,
    *,
    executor_model: str,
    executor_cache_ttl: str,
    advisor_cache_ttl: str,
    calculator: CostCalculatorFn,
) -> dict[str, Any]:
    summary = normalize_anthropic_usage(
        usage, model=executor_model, cache_requested=True
    )
    base = await calculator(
        provider="anthropic",
        model_name=executor_model,
        prompt_tokens=summary["prompt_tokens"],
        completion_tokens=summary["completion_tokens"],
        cache_creation_tokens=summary["cache_creation_tokens"],
        cache_read_tokens=summary["cache_read_tokens"],
        cache_ttl=executor_cache_ttl,
    )

    composite_total = Decimal("0")
    advisor_total = Decimal("0")
    advisor_details = {
        "call_count": 0,
        "models": [],
        "input_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "error_codes": [],
    }
    iterations = summary["iterations"]
    if not iterations:
        composite_total = Decimal(str(base["total_cost"]))
    else:
        for item in iterations:
            is_advisor = item["type"] == "advisor_message"
            iteration_model = item["model"] if is_advisor else executor_model
            priced = await calculator(
                provider="anthropic",
                model_name=iteration_model,
                prompt_tokens=item["input_tokens"],
                completion_tokens=item["output_tokens"],
                cache_creation_tokens=item["cache_creation_tokens"],
                cache_read_tokens=item["cache_read_tokens"],
                cache_ttl=advisor_cache_ttl if is_advisor else executor_cache_ttl,
            )
            iteration_total = Decimal(str(priced["total_cost"]))
            composite_total += iteration_total
            if is_advisor:
                advisor_total += iteration_total
                advisor_details["call_count"] += 1
                advisor_details["models"].append(iteration_model)
                advisor_details["input_tokens"] += item["input_tokens"]
                advisor_details["cache_creation_tokens"] += item["cache_creation_tokens"]
                advisor_details["cache_read_tokens"] += item["cache_read_tokens"]
                advisor_details["output_tokens"] += item["output_tokens"]

    top_level_base_total = Decimal(str(base["total_cost"]))
    additional_cost = max(Decimal("0"), composite_total - top_level_base_total)
    return {
        **base,
        "total_cost": composite_total,
        "advisor_cost": advisor_total,
        "additional_cost": additional_cost,
        "advisor": advisor_details,
    }
```

Implement `cache_minimum_tokens(model)` beside these functions using the model-family thresholds listed in the approved design reference. Enrich `error_codes` later from Advisor result blocks in Task 5; usage iterations do not carry those response codes.

- [ ] **Step 4: Update fallback pricing and persistence hooks**

In `CostCalculator.DEFAULT_PRICING`, use the current document prices:

```python
"claude-sonnet-4-6": {
    "input": 3.00,
    "output": 15.00,
    "cache_creation": 3.75,
    "cache_read": 0.30,
},
"claude-opus-4-8": {
    "input": 5.00,
    "output": 25.00,
    "cache_creation": 6.25,
    "cache_read": 0.50,
},
"claude-haiku-4-5-20251001": {
    "input": 1.00,
    "output": 5.00,
    "cache_creation": 1.25,
    "cache_read": 0.10,
},
```

Add `cache_ttl: Literal["5m", "1h"] = "5m"` to cost calculation methods. For Anthropic `1h`, use `pricing["input"] * Decimal("2")` for cache creation. Add `additional_cost_usd: Decimal | float = 0` to `record_message_cost` and `record_cost_for_existing_message`, add it once to `total_cost`, and include it in returned cost info and metadata.

- [ ] **Step 5: Run usage and cost tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/unit/providers/test_anthropic_usage.py tests/test_cost_calculator.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add neos/providers/anthropic_usage.py neos/utils/cost_calculator.py tests/unit/providers/test_anthropic_usage.py tests/test_cost_calculator.py
git commit -m "feat(anthropic): track cache and advisor cost"
```

---

### Task 4: Automatic Caching in Chat Paths

**Files:**
- Modify: `neos/services/chat_llm_service.py`
- Create: `tests/unit/services/test_chat_llm_prompt_caching.py`
- Modify: `neos/api/services/chat_stream_pipeline.py`
- Modify: `neos/api/services/chat_message_processor.py`
- Modify: `neos/api/handlers/chat_handlers.py`

**Interfaces:**
- Consumes: `build_cache_control`, `normalize_anthropic_usage`, and `calculate_anthropic_cost` from Tasks 2 and 3.
- Produces: chat usage dictionaries containing `cache_creation_tokens`, `cache_read_tokens`, `total_input_tokens`, `cache_status`, and `advisor` metadata while preserving current keys.

- [ ] **Step 1: Write failing chat cache tests**

Create `tests/unit/services/test_chat_llm_prompt_caching.py` with fake LangChain models:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from neos.services.chat_llm_service import ChatLLMService


@pytest.mark.asyncio
async def test_anthropic_invoke_receives_automatic_cache_control():
    llm = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content="answer",
                response_metadata={
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 1000,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 5,
                    },
                    "stop_reason": "end_turn",
                },
            )
        )
    )

    with patch("neos.services.chat_llm_service.create_llm", return_value=llm), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=AsyncMock(return_value={"total_cost": 0}),
    ):
        result = await ChatLLMService().generate_response(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "hello"}],
            model_name="claude-sonnet-4-6",
            enable_context_optimization=False,
        )

    assert llm.ainvoke.await_args.kwargs["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert result["usage"]["cache_creation_tokens"] == 1000
    assert result["usage"]["total_input_tokens"] == 1010
```

Add a second test with model `gpt-4o` asserting `ainvoke.await_args.kwargs` has no `cache_control` key. Add a streaming fake asserting the same parameter reaches `llm.astream`.

- [ ] **Step 2: Run chat cache tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/services/test_chat_llm_prompt_caching.py -q
```

Expected: cache-control assertions fail and usage lacks cache fields.

- [ ] **Step 3: Apply cache control and normalized usage**

In `ChatLLMService`, snapshot `settings.config.llm.prompt_caching` per method. Pass `cache_control` only when the provider is Anthropic:

```python
invoke_kwargs: dict[str, Any] = {}
cache_control = build_cache_control(settings.config.llm.prompt_caching)
if provider == "anthropic" and cache_control:
    invoke_kwargs["cache_control"] = cache_control
response = await llm.ainvoke(messages, **invoke_kwargs)
```

Apply the same pattern to `astream` and the direct stable tool-stream request. Replace manual Anthropic usage dictionaries with `normalize_anthropic_usage`. Pass cache tokens and configured TTL to cost calculation.

- [ ] **Step 4: Forward cache accounting to persistence**

At chat persistence call sites, pass:

```python
cache_creation_tokens=usage.get("cache_creation_tokens", 0),
cache_read_tokens=usage.get("cache_read_tokens", 0),
cache_ttl=settings.config.llm.prompt_caching.ttl,
additional_cost_usd=cost_info.get("additional_cost", 0),
metadata={"anthropic": usage.get("anthropic", {})},
```

Keep defaults for OpenAI and for older callers whose usage lacks these keys.

- [ ] **Step 5: Run chat cache and affected persistence tests**

Run:

```bash
.venv/bin/pytest tests/unit/services/test_chat_llm_prompt_caching.py tests/api/services/test_chat_stream_pipeline_autonomy.py tests/test_cost_calculator.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add neos/services/chat_llm_service.py neos/api/services/chat_stream_pipeline.py neos/api/services/chat_message_processor.py neos/api/handlers/chat_handlers.py tests/unit/services/test_chat_llm_prompt_caching.py
git commit -m "feat(chat): enable Anthropic prompt caching"
```

---

### Task 5: Config-controlled Advisor Tool Loop

**Files:**
- Modify: `neos/services/chat_llm_service.py`
- Create: `tests/unit/services/test_chat_llm_advisor.py`

**Interfaces:**
- Consumes: `build_tool_policy`, `serialize_content_block`, `normalize_anthropic_usage`, and `calculate_anthropic_cost`.
- Produces: beta routing only for injected Advisor, unchanged normal routing otherwise, deterministic `pause_turn` continuation, and completion metadata under `usage["anthropic"]["advisor"]`.

- [ ] **Step 1: Write failing Advisor routing tests**

Create `tests/unit/services/test_chat_llm_advisor.py`. Use a fake `AsyncAnthropic` whose `messages.stream` and `beta.messages.stream` record kwargs and return scripted async stream managers. Cover these assertions:

```python
assert normal_client.messages.stream.call_count == 1
assert normal_client.beta.messages.stream.call_count == 0
assert all(tool.get("type") != "advisor_20260301" for tool in normal_tools)
```

With `AdvisorConfig(enabled=True)` and executor `claude-sonnet-4-6`:

```python
assert client.beta.messages.stream.call_count == 1
kwargs = client.beta.messages.stream.call_args.kwargs
assert kwargs["betas"] == ["advisor-tool-2026-03-01"]
assert kwargs["tools"][-1]["type"] == "advisor_20260301"
assert kwargs["tools"][-1]["max_uses"] == 2
assert kwargs["tools"][-1]["max_tokens"] == 2048
```

Add an incompatible Sonnet 4.5 case asserting stable API routing and `advisor.skip_reason == "incompatible_model_pair"` in the completion event.

- [ ] **Step 2: Write failing `pause_turn` continuation test**

Script the first beta response as `stop_reason="pause_turn"` with a `server_tool_use` block and no result, and the second response as `end_turn` with an Advisor result and text. Assert:

```python
assert client.beta.messages.stream.call_count == 2
second_messages = client.beta.messages.stream.call_args_list[1].kwargs["messages"]
assert second_messages[-1]["role"] == "assistant"
assert second_messages[-1]["content"][0]["type"] == "server_tool_use"
assert client.beta.messages.stream.call_args_list[0].kwargs["tools"] == \
       client.beta.messages.stream.call_args_list[1].kwargs["tools"]
assert client.beta.messages.stream.call_args_list[0].kwargs["betas"] == \
       client.beta.messages.stream.call_args_list[1].kwargs["betas"]
```

Add a scripted sequence longer than `max_pause_turns` and assert the generator yields a single clear error and terminates.

- [ ] **Step 3: Run Advisor tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/services/test_chat_llm_advisor.py -q
```

Expected: the current service always uses stable `client.messages.stream`, never injects Advisor, and exits on `pause_turn`.

- [ ] **Step 4: Implement beta selection and stable tool policy**

At the start of `generate_response_stream_with_tool_search`, snapshot both config objects and call:

```python
tool_policy = build_tool_policy(
    [*core_tools, SEARCH_TOOLS_TOOL],
    executor_model=model,
    prompt_caching=prompt_cache_config,
    advisor=advisor_config,
)
active_tools_dicts = list(tool_policy.tools)
messages_api = client.beta.messages if tool_policy.use_beta else client.messages
```

For each request, pass `betas=tool_policy.betas` only on the beta API. Discovered tools are appended after the stable checkpoint.

- [ ] **Step 5: Implement `pause_turn` and complete block preservation**

If `final_message.stop_reason == "pause_turn"`, increment a separate pause counter, append the complete serialized assistant content, and continue without adding a user message or consuming a client-tool round. If the counter exceeds the configured cap, yield:

```python
{
    "type": "error",
    "error": "Anthropic Advisor pause_turn exceeded configured limit (3)",
}
```

Use `serialize_content_block` for every assistant continuation, including `server_tool_use`, `advisor_tool_result`, `advisor_redacted_result`, thinking, text, and client tool blocks. Inspect Advisor result blocks only to record call counts and error codes; never yield raw guidance.

- [ ] **Step 6: Aggregate beta iteration usage and cost**

Use `normalize_anthropic_usage` for every completed request and `calculate_anthropic_cost` for the final/composite result. Include:

```python
"anthropic": {
    "prompt_caching": {"status": usage["cache_status"]},
    "advisor": {
        "enabled": advisor_config.enabled,
        "injected": tool_policy.advisor.injected,
        "skip_reason": tool_policy.advisor.skip_reason,
        **advisor_usage,
    },
}
```

- [ ] **Step 7: Run Advisor and chat regression tests**

Run:

```bash
.venv/bin/pytest tests/unit/services/test_chat_llm_advisor.py tests/unit/services/test_chat_llm_prompt_caching.py tests/api/handlers/test_chat_authorization.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add neos/services/chat_llm_service.py tests/unit/services/test_chat_llm_advisor.py
git commit -m "feat(chat): add config-controlled Anthropic advisor"
```

---

### Task 6: Warm Contextual Retrieval Cache Before Fan-out

**Files:**
- Modify: `neos/pipelines/document/contextual_retrieval.py`
- Create: `tests/unit/pipelines/document/test_contextual_retrieval_caching.py`

**Interfaces:**
- Consumes: existing `ContextualRetrieval._generate_context_for_chunk`.
- Produces: the same ordered `list[ContextualChunk]`, with chunk zero completing before remaining work begins.

- [ ] **Step 1: Write the failing ordering test**

Create `tests/unit/pipelines/document/test_contextual_retrieval_caching.py`:

```python
import asyncio

import pytest

from neos.pipelines.document.chunker import DocumentChunk
from neos.pipelines.document.contextual_retrieval import ContextualChunk, ContextualRetrieval


def chunk(index: int) -> DocumentChunk:
    text = f"chunk-{index}"
    return DocumentChunk(chunk_index=index, chunk_text=text, chunk_size=len(text))


@pytest.mark.asyncio
async def test_first_chunk_completes_before_parallel_fanout(monkeypatch):
    retrieval = ContextualRetrieval(max_concurrent=3, max_chunks_per_doc=10)
    events: list[tuple[str, int]] = []

    async def fake_generate(*, full_document, chunk, chunk_index):
        events.append(("start", chunk_index))
        await asyncio.sleep(0)
        events.append(("finish", chunk_index))
        return ContextualChunk(
            original_chunk=chunk,
            contextual_text=chunk.chunk_text,
            context_snippet=f"context-{chunk_index}",
        )

    monkeypatch.setattr(retrieval, "_generate_context_for_chunk", fake_generate)
    result = await retrieval.generate_contexts("document", [chunk(0), chunk(1), chunk(2)])

    assert events.index(("finish", 0)) < events.index(("start", 1))
    assert events.index(("finish", 0)) < events.index(("start", 2))
    assert [item.original_chunk.chunk_index for item in result] == [0, 1, 2]
```

Add a first-call exception test asserting chunk zero falls back while remaining chunks still run in order.

- [ ] **Step 2: Run the contextual retrieval test and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/pipelines/document/test_contextual_retrieval_caching.py -q
```

Expected: both later calls start before chunk zero finishes.

- [ ] **Step 3: Implement warm-first scheduling**

Replace the all-at-once task construction with:

```python
raw_results: list[ContextualChunk | Exception] = []
try:
    raw_results.append(await _generate_single(chunks_to_process[0], 0))
except Exception as exc:
    raw_results.append(exc)

remaining_tasks = [
    _generate_single(chunk, idx)
    for idx, chunk in enumerate(chunks_to_process[1:], start=1)
]
if remaining_tasks:
    raw_results.extend(await asyncio.gather(*remaining_tasks, return_exceptions=True))
```

Preserve current fallback, budget, metrics, and result-order logic after `raw_results` is built.

- [ ] **Step 4: Run contextual retrieval tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/unit/pipelines/document/test_contextual_retrieval_caching.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 6**

```bash
git add neos/pipelines/document/contextual_retrieval.py tests/unit/pipelines/document/test_contextual_retrieval_caching.py
git commit -m "perf(retrieval): warm Anthropic document cache"
```

---

### Task 7: Integrated Verification and Documentation Reconciliation

**Files:**
- Modify only if verification exposes a documented contract mismatch: `docs/CONFIGURATION.md`
- Test: all files created or changed by Tasks 1-6

**Interfaces:**
- Consumes: every public interface from Tasks 1-6.
- Produces: a verified feature branch with no uncommitted implementation changes and an operator guide matching runtime defaults.

- [ ] **Step 1: Run focused feature tests**

Run:

```bash
.venv/bin/pytest \
  tests/config/test_config_schema.py \
  tests/config/test_settings_compat.py \
  tests/config/test_config_files.py \
  tests/unit/providers/test_anthropic_features.py \
  tests/unit/providers/test_anthropic_usage.py \
  tests/unit/services/test_chat_llm_prompt_caching.py \
  tests/unit/services/test_chat_llm_advisor.py \
  tests/unit/pipelines/document/test_contextual_retrieval_caching.py \
  tests/test_cost_calculator.py -q
```

Expected: all focused tests pass with no live API calls.

- [ ] **Step 2: Run affected regression suites**

Run:

```bash
.venv/bin/pytest \
  tests/config \
  tests/api/services/test_chat_stream_pipeline_autonomy.py \
  tests/api/handlers/test_chat_authorization.py \
  tests/test_tool_search.py \
  tests/test_chat_service.py -q
```

Expected: all affected regression tests pass.

- [ ] **Step 3: Run static compilation**

Run:

```bash
.venv/bin/python -m compileall -q neos tests/unit/providers tests/unit/services tests/unit/pipelines
```

Expected: exit status 0 and no output.

- [ ] **Step 4: Audit feature invariants**

Run:

```bash
rg -n 'advisor_20260301|advisor-tool-2026-03-01|cache_control' neos config docs/CONFIGURATION.md
```

Verify manually from the output:

- Advisor constants and tool construction are centralized in `anthropic_features.py`.
- Only the tool-search method selects the Advisor beta API.
- Artifact, vision, and deep-analysis request files have no new cache-control writes.
- Committed YAML shows caching enabled and Advisor disabled.

- [ ] **Step 5: Reconcile documentation if needed**

Compare `docs/CONFIGURATION.md` against `AppConfig()` defaults printed by:

```bash
.venv/bin/python -c 'from neos.config.schema import AppConfig; print(AppConfig().llm.model_dump())'
```

If wording differs, update the document with the actual printed values and rerun the config tests. Do not change runtime defaults merely to match prose.

- [ ] **Step 6: Commit any verification-only documentation correction**

If Step 5 changed documentation:

```bash
git add docs/CONFIGURATION.md
git commit -m "docs: align Anthropic feature configuration"
```

If it did not change documentation, do not create an empty commit.

- [ ] **Step 7: Confirm final worktree scope**

Run:

```bash
git status --short
git log --oneline --decorate -8
```

Expected: no uncommitted feature files. Any pre-existing user-owned files remain untouched in the original worktree.

---

## Completion Checklist

- [ ] Prompt cache configuration is typed, documented, and enabled by default.
- [ ] Advisor configuration is typed, documented, and disabled by default.
- [ ] Conversational Anthropic calls carry automatic cache control.
- [ ] Tool-search has a stable explicit tool breakpoint.
- [ ] Compatible Advisor requests route through the beta API only when enabled.
- [ ] `pause_turn` preserves complete server blocks and terminates at the configured cap.
- [ ] Cache and Advisor iterations are priced once and persisted without a schema migration.
- [ ] Contextual retrieval warms before concurrent fan-out.
- [ ] Focused and affected regression tests pass.
- [ ] Artifact, deep-analysis, and vision paths remain intentionally unchanged.
