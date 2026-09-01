from __future__ import annotations

from decimal import Decimal
from typing import Any, Awaitable, Callable

from neos.config.model_config import (
    cache_minimum_tokens as _cache_minimum_tokens,
)


def _field(value: Any, name: str, default: Any = 0) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _tokens(value: Any, name: str) -> int:
    return int(_field(value, name, 0) or 0)


def cache_minimum_tokens(model: str) -> int:
    """프롬프트 캐시가 성립하는 최소 입력 토큰.

    CA12: 세대별 값은 `neos/config/models.yaml` 의 `anthropic_families:` 에
    있다. 여기 있던 시절 이 함수는 advisor 호환표와 함께 **카탈로그가 갖지
    않는 둘째 모델 사실 테이블**이었고, 두 표가 서로 다른 접두사 어휘를
    쓰고 있었다는 것도 옮기면서 드러났다(`claude-opus-4-5` 등 셋은 캐시
    표에만 있었다). 지금은 한 블록이 둘 다 답한다.
    """
    return _cache_minimum_tokens(model)


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
                "cache_creation_tokens": _tokens(
                    item, "cache_creation_input_tokens"
                ),
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
        usage,
        model=executor_model,
        cache_requested=True,
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
                advisor_details["cache_creation_tokens"] += item[
                    "cache_creation_tokens"
                ]
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
