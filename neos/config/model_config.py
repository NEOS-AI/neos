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
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from neos.config.schema import StrictConfigModel

if TYPE_CHECKING:
    from neos.config.schema import CodingModelConfig, ModelRoutingConfig

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

    손으로 편집된 옛 파일은 형태가 깨져 있을 수 있다(항목이 dict가 아니거나
    `model_id`가 없거나). 이런 항목은 예외를 내지 않고 건너뛴다 — 별칭 하나가
    잘못됐다고 파일 전체를 무효화하지 않는다. `load_catalog`의 "실패해도
    부팅을 막지 않는다" 계약은 이 함수가 예외를 내지 않을 때만 성립한다.
    """
    models: dict[str, dict[str, Any]] = {}
    aliases: dict[str, dict[str, str]] = {}

    for legacy_key, group in _LEGACY_GROUPS:
        for alias, entry in (data.get(legacy_key) or {}).items():
            if not isinstance(entry, dict):
                logger.warning(
                    "Skipping malformed legacy catalog entry %s.%s: expected a "
                    "mapping, got %s",
                    legacy_key,
                    alias,
                    type(entry).__name__,
                )
                continue
            if "model_id" not in entry:
                logger.warning(
                    "Skipping malformed legacy catalog entry %s.%s: missing "
                    "'model_id'",
                    legacy_key,
                    alias,
                )
                continue
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
        """카탈로그를 다시 읽는다.

        검증 실패 시 빈 카탈로그로 통째로 갈아치우지 않는다 — 그것은
        조용한 성능 저하가 아니라 라이브 사고다(예: thinking 계약이 전부
        BUDGETED로 떨어지며 Claude 5에 잘못된 요청 모양이 나간다). 대신:

        - 이전에 유효한 카탈로그가 있었다면(`last-good`) 그것을 유지하고
          ERROR로 리로드가 거부됐음을 알린다.
        - 첫 로드부터 실패했다면(last-good 없음) 기존처럼 빈 카탈로그로
          가되, ERROR가 "카탈로그가 비었고 목록/가격/thinking 계약이 모두
          기본값으로 떨어진다"를 분명히 말한다.
        """
        path = _catalog_path()
        previous = self._catalog
        try:
            new_catalog = load_catalog(path)
        except ValidationError as exc:
            if previous is not None:
                logger.error(
                    "Model catalog %s failed validation: %s — reload rejected, "
                    "the previous catalog (%d models) is still in effect",
                    path,
                    exc,
                    len(previous.models),
                )
                self._catalog = previous
            else:
                logger.error(
                    "Model catalog %s failed validation: %s — the catalog is "
                    "now EMPTY; model lists, pricing, and thinking contracts "
                    "will all fall back to defaults",
                    path,
                    exc,
                )
                self._catalog = ModelCatalog()
            return
        self._catalog = new_catalog
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


def warn_unknown_routed_models(routing: "ModelRoutingConfig") -> list[str]:
    """역할 기본값이 카탈로그에 없는 모델을 가리키면 경고한다.

    예외는 던지지 않는다 — 카탈로그 갱신 전에도 배포에서 신종 모델을
    지정할 수 있어야 한다(spec §6). 오타는 로그로 드러난다.

    기능 오버라이드(`coding_model.model`, `knowledge_graph.extraction.model` 등)는
    여기서 검사하지 않는다. 그 값들이 `create_llm(model=...)`로 흘러가는
    한, 거기서 모델별 1회 경고를 받는다. 반면 역할 기본값은 `model=`을
    생략한 경로에서만 쓰여 사용 시점 경고가 늦으므로, 기동 검사의 값이
    여기에 있다.

    주의: 다음 두 경로는 `create_llm()`을 아예 거치지 않으므로 이 기동
    검사도, `create_llm`의 사용 시점 경고도 받지 못한다 — 오타가 나면
    provider 오류로만 드러난다.

    - deep_analysis (`deep_analysis.models.{scout,dig,synth,judge}`): 자체
      클라이언트를 만드는 `neos/workflow/deep_analysis/llm.py`의
      `call_llm`/`_default_client`로 넘어간다.
    - chat tool-streaming: `neos/services/chat_llm_service.py`가
      `anthropic.AsyncAnthropic`을 직접 생성한다.

    Returns:
        카탈로그에 없던 모델 이름 목록 (선언 순서).
    """
    catalog = model_config.catalog
    if not catalog.models:
        logger.error(
            "Model catalog is EMPTY — model lists, pricing, and thinking "
            "contracts are all falling back to defaults. This is likely a "
            "rejected reload or a first-load validation failure; check the "
            "ERROR logged at catalog load time and fix neos/config/models.yaml "
            "(or the file at NEOS_MODEL_CONFIG_PATH)."
        )
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


# USD / 1M 토큰 → micros / 1M 토큰
_MICROS_PER_USD = 1_000_000


def warn_coding_model_price_drift(
    coding_model: "CodingModelConfig",
) -> list[str]:
    """`coding_model` 가격이 카탈로그와 어긋나면 경고한다.

    이 값들은 코딩 루프의 예산 가드용이며 **운영자 정책**이다. 협상 요율을
    쓸 수 있어야 하므로 카탈로그가 덮어쓰지 않는다. 다만 같은 모델의 가격이
    두 곳에 있으면 조용히 어긋날 수 있으므로, 불일치를 기동 시 드러낸다.

    카탈로그를 `neos/config/schema.py`의 검증기에서 조회할 수는 없다 —
    이 모듈이 그쪽에서 `StrictConfigModel`을 가져오므로 순환 import가 된다.
    그래서 스키마가 아니라 기동 경로에서 확인한다.

    Returns:
        어긋난 항목 이름 목록 (`"input"`, `"output"`). 일치하거나 비교
        대상이 없으면 빈 목록.
    """
    if not coding_model.enabled or not coding_model.model:
        return []

    spec = model_config.catalog.get_model_spec(coding_model.model)
    pricing = spec.pricing if spec is not None else None
    if pricing is None:
        # 카탈로그는 allowlist가 아니다 — 모르는 모델은 비교할 근거가 없다.
        return []

    drift: list[str] = []
    for field, configured, catalog_usd in (
        ("input", coding_model.input_cost_micros_per_million, pricing.input),
        ("output", coding_model.output_cost_micros_per_million, pricing.output),
    ):
        expected = int(round(catalog_usd * _MICROS_PER_USD))
        if configured != expected:
            drift.append(field)
            logger.warning(
                "coding_model.%s_cost_micros_per_million = %d disagrees with the "
                "model catalog price for %r (%d micros = $%.2f per 1M tokens). "
                "Budget accounting and cost reporting will not match. Intentional "
                "(negotiated rate)? Leave it; otherwise align it with "
                "neos/config/models.yaml.",
                field,
                configured,
                coding_model.model,
                expected,
                catalog_usd,
            )
    return drift
