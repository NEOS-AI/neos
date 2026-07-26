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
