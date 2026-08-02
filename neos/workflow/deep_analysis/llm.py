"""Pure async LLM calls with centralized JSON parsing and usage tracking."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from neos.providers.anthropic import normalize_anthropic_request
from neos.config.settings import settings
from neos.workflow.deep_analysis.token_budget import active_token_budget


class JSONParseError(ValueError):
    """Raised when an LLM response does not contain one valid JSON object."""


class TruncatedResponseError(JSONParseError):
    """Raised when the response failed to parse *because it was cut off*.

    A subclass of JSONParseError on purpose: the five call sites that already
    let a parse failure propagate keep working untouched, while the two that
    fail open on D14 can opt into the distinction by catching this first.
    """


class LLMProviderError(RuntimeError):
    """Raised when a live LLM provider call fails."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # 기본값이 필수다: 기존 golden cassette 레코드에는 이 키들이 없고,
    # 재생 시 LLMResponse(**recorded)로 복원된다(D19 golden 게이트 유지).
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    # 이 호출에 실제로 허용된 출력 상한. 0은 "미상"(레거시 레코드)이다.
    # _budgeted_dispatch가 카세트 계층 이후에 채운다 — 허용 상한은 기록 시점이
    # 아니라 이번 run의 예산 속성이므로, 재생 시에도 덮어써야 한다.
    granted_max_output_tokens: int = 0


@dataclass
class _DispatchState:
    started: bool = False


_CODE_FENCE = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$",
    re.DOTALL | re.IGNORECASE,
)


def parse_json(raw: str) -> dict[str, Any]:
    value = raw.strip()
    fenced = _CODE_FENCE.match(value)
    if fenced:
        value = fenced.group(1).strip()

    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise JSONParseError(f"no JSON object in: {raw[:120]!r}")

    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JSONParseError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise JSONParseError("top-level JSON value must be an object")
    return parsed


def _is_anthropic_model(model: str) -> bool:
    """Anthropic 모델인가 — 클라이언트와 페이로드 형태를 함께 결정한다.

    모델 카탈로그가 우선이다. 이름 접두사만 보던 예전 방식은 `claude`로
    시작하지 않는 모델을 전부 OpenAI로 보냈다.

    두 호출처(`_default_client`, `_call_provider`)가 반드시 같은 판단을 써야
    한다. 어긋나면 Anthropic 클라이언트에 OpenAI 페이로드를 보내게 된다.
    """
    from neos.config.model_config import provider_for_model

    provider = provider_for_model(model)
    if provider is not None:
        return provider == "anthropic"
    # 카탈로그는 allowlist가 아니다 — 모르는 이름은 접두사로 판단한다.
    return model.startswith("claude")


def _default_client(model: str):
    if _is_anthropic_model(model):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _blocks_to_dicts(content) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in content:
        kind = getattr(block, "type", "")
        if kind == "text":
            blocks.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return blocks


async def _call_provider(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    client,
    tools: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    # `_default_client`와 같은 판단을 써야 한다 — 어긋나면 클라이언트와
    # 페이로드 형태가 짝이 맞지 않는다.
    if _is_anthropic_model(model):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        kwargs = normalize_anthropic_request(
            model,
            kwargs,
            thinking_enabled=True,
        )
        response = await client.messages.create(**kwargs)
        blocks = _blocks_to_dicts(response.content)
        output = "".join(b["text"] for b in blocks if b["type"] == "text")
        return LLMResponse(
            text=output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=getattr(response, "model", model),
            content=blocks,
            stop_reason=getattr(response, "stop_reason", "") or "",
        )

    if tools:
        raise ValueError(
            f"tool calling is only supported on claude models, got {model}"
        )

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages,
    )
    text = response.choices[0].message.content or ""
    return LLMResponse(
        text=text,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=getattr(response, "model", model),
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
    )


async def _call_live_provider(*args, **kwargs) -> LLMResponse:
    try:
        return await _call_provider(*args, **kwargs)
    except LLMProviderError:
        raise
    except Exception as exc:
        raise LLMProviderError(str(exc)) from exc


async def _budgeted_dispatch(
    *,
    model: str,
    request: dict[str, Any],
    max_tokens: int,
    stage: str,
    invoke: Callable[[int, _DispatchState], Awaitable[LLMResponse]],
) -> LLMResponse:
    budget = active_token_budget()
    if budget is None:
        response = await invoke(max_tokens, _DispatchState())
        return replace(response, granted_max_output_tokens=max_tokens)

    reservation = await budget.reserve(
        request,
        max_tokens,
        stage=stage,
        model=model,
    )
    dispatch = _DispatchState()
    try:
        response = await invoke(reservation.max_output_tokens, dispatch)
    except BaseException:
        if dispatch.started:
            await budget.abandon(reservation)
        else:
            await budget.release(reservation)
        raise

    await budget.settle(
        reservation,
        response.input_tokens + response.output_tokens,
    )
    if response.stop_reason == "max_tokens":
        await budget.record_truncation(
            stage=reservation.stage,
            model=reservation.model,
            max_output_tokens=reservation.max_output_tokens,
            output_tokens=response.output_tokens,
        )
    return replace(
        response,
        granted_max_output_tokens=reservation.max_output_tokens,
    )


async def call_messages(
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    stage: str = "llm",
) -> LLMResponse:
    async def invoke(limit: int, dispatch: _DispatchState) -> LLMResponse:
        async def produce() -> dict[str, Any]:
            resolved_client = client or _default_client(model)
            dispatch.started = True
            response = await _call_live_provider(
                model,
                messages,
                max_tokens=limit,
                temperature=temperature,
                client=resolved_client,
                tools=tools,
            )
            return asdict(response)

        if cassette is None:
            return LLMResponse(**(await produce()))

        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "max_tokens": limit,
            "temperature": temperature,
        }
        recorded = await cassette.remember("llm", payload, produce)
        return LLMResponse(**recorded)

    return await _budgeted_dispatch(
        model=model,
        request={"model": model, "messages": messages, "tools": tools},
        max_tokens=max_tokens,
        stage=stage,
        invoke=invoke,
    )


async def call_llm(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    stage: str = "llm",
) -> LLMResponse:
    messages = [{"role": "user", "content": prompt}]

    async def invoke(limit: int, dispatch: _DispatchState) -> LLMResponse:
        async def produce() -> dict[str, Any]:
            resolved_client = client or _default_client(model)
            dispatch.started = True
            response = await _call_live_provider(
                model,
                messages,
                max_tokens=limit,
                temperature=temperature,
                client=resolved_client,
            )
            return asdict(response)

        if cassette is None:
            return LLMResponse(**(await produce()))

        # 페이로드 형태를 그대로 유지한다 — 기존 golden cassette 키가 바뀌면 안 된다.
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": limit,
            "temperature": temperature,
        }
        recorded = await cassette.remember("llm", payload, produce)
        return LLMResponse(**recorded)

    return await _budgeted_dispatch(
        model=model,
        request={"model": model, "messages": messages, "tools": None},
        max_tokens=max_tokens,
        stage=stage,
        invoke=invoke,
    )


async def _record_truncation_handled(
    *,
    stage: str,
    model: str,
    requested: int,
    granted: int,
    action: str,
) -> None:
    # TokenBudget is the writer (P2). Outside a budget scope there is nowhere
    # to write, and that is not an error -- tests and ad-hoc calls run there.
    budget = active_token_budget()
    if budget is None:
        return
    await budget.record_truncation_handled(
        stage=stage,
        model=model,
        requested=requested,
        granted=granted,
        action=action,
    )


async def call_json(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    retries: int = 1,
    stage: str = "llm",
) -> tuple[dict[str, Any], LLMResponse]:
    """Call the model and parse one JSON object out of its response.

    `retries` counts tolerance for *malformed* responses. Truncation is a
    separate axis: a call cut at its ceiling earns one extra attempt at a
    larger ceiling regardless of `retries`, because the two failures have
    different causes and different cures.
    """

    from neos.config.settings import settings

    multiplier = settings.config.deep_analysis.truncation_retry_multiplier
    original_limit = max_tokens
    limit = max_tokens
    expanded = False
    last_error: JSONParseError | None = None
    attempts_left = retries + 1

    while attempts_left > 0:
        response = await call_llm(
            model,
            prompt,
            max_tokens=limit,
            temperature=temperature,
            client=client,
            cassette=cassette,
            stage=stage,
        )
        try:
            parsed = parse_json(response.text)
        except JSONParseError as exc:
            last_error = exc
        else:
            if expanded:
                await _record_truncation_handled(
                    stage=stage,
                    model=model,
                    requested=original_limit,
                    granted=response.granted_max_output_tokens,
                    action="retried_ok",
                )
            return parsed, response

        if response.stop_reason != "max_tokens":
            attempts_left -= 1
            continue

        # Cut off. Retrying only helps if the ceiling -- not the budget --
        # was the binding constraint: settling this call already shrank
        # `remaining`, so a budget-clamped retry gets *less* room, not more.
        budget_bound = response.granted_max_output_tokens < limit
        if budget_bound or expanded:
            await _record_truncation_handled(
                stage=stage,
                model=model,
                requested=original_limit,
                granted=response.granted_max_output_tokens,
                action="budget_bound" if budget_bound else "retried_failed",
            )
            raise TruncatedResponseError(str(last_error))

        # The expansion is a separate axis from `retries`: it answers a
        # different failure, so it does not consume a malformed-response
        # attempt. It is available at most once, and the `expanded` guard
        # above makes a second truncation terminal -- so the loop always ends.
        expanded = True
        limit = int(limit * multiplier)

    if last_error is None:
        raise JSONParseError("JSON parsing failed without a response")
    raise last_error
