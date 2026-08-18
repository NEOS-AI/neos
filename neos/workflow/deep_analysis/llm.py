"""Pure async LLM calls with centralized JSON parsing and usage tracking."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from neos.providers.anthropic import normalize_anthropic_request
from neos.config.settings import settings
from neos.workflow.deep_analysis.prompt_loader import (
    UnfilledPlaceholder,
    unfilled_placeholders,
)
from neos.workflow.deep_analysis.token_budget import (
    TokenBudgetExhausted,
    active_token_budget,
    conservative_input_bound,
)


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


def prompt_input_bound(model: str, prompt: str) -> int:
    """The input bound `reserve()` would charge for this single-prompt call.

    Deliberately mirrors the `request` dict `call_llm` passes to
    `_budgeted_dispatch` below. Two rulers -- one for measuring, one for
    charging -- would let a clamp certify a prompt the budget then refuses,
    which is the whole failure this measurement exists to prevent. If the
    request shape below changes, this changes with it.
    """
    return conservative_input_bound(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": None,
        }
    )


def _record_dataset_call(
    model: str,
    request: dict[str, Any],
    stage: str,
    response: LLMResponse,
) -> None:
    """이 호출을 데이터셋 콜렉터에 남긴다 (D1c).

    `_budgeted_dispatch` 는 deep_analysis 의 **모든** LLM 호출이 지나가는
    한 곳이다 -- `call_llm` 도 `call_messages` 도 여기로 온다. 그래서 계측을
    여기 한 번만 붙이면 이 계층 전체가 덮인다.

    토큰은 `LLMResponse` 가 API `usage` 에서 그대로 옮겨 온 값이다(§A5).
    `record_llm_call` 이 절대 던지지 않으므로 여기서도 감싸지 않는다.
    """
    from neos.dataset.adapters import record_llm_call

    record_llm_call(
        provider="anthropic",
        model=model,
        workflow_step=stage,
        input_messages=list(request.get("messages") or []),
        output_text=response.text,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        custom_metadata={"stop_reason": response.stop_reason},
    )


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
        _record_dataset_call(model, request, stage, response)
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

    _record_dataset_call(model, request, stage, response)
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
    # 채워지지 않은 치환 자리를 가진 프롬프트는 모델에 보내지 않는다.
    #
    # `prompt_loader.render` 는 키마다 `str.replace` 이고 부분 렌더가 설계다
    # (오케스트레이터가 `{fetched_evidence}` 를 남기면 워커가 나중에 채운다).
    # 그래서 렌더 시점에는 검사할 수 없고, 여기가 마지막 관문이다.
    #
    # 조용히 통과시키면 모델은 `{resolve_threshold} 이상이면` 같은 문장을 받고도
    # 그럴듯한 답을 돌려준다 -- 산출물을 봐서는 프롬프트가 반쯤 비었다는 것을
    # 알 수 없다. 프롬프트에 새 자리를 더하면서 호출 지점 하나를 빠뜨리는 것이
    # 이 검사가 막는 실제 사고다.
    unfilled = unfilled_placeholders(prompt)
    if unfilled:
        raise UnfilledPlaceholder(
            f"stage {stage!r} would send a prompt still holding {unfilled}"
        )
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


async def call_text(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    stage: str = "llm",
) -> LLMResponse:
    """A prose call that earns one larger attempt when it hits its ceiling.

    `call_json` has had this since A2. `call_llm` only *recorded* the
    truncation, and `report_assembly` is the one stage that calls `call_llm`
    directly -- so it was the one stage that could not recover. Measured
    2026-08-08 (sample #2): 18 of 18 assemblies stopped exactly at their
    ceiling (dev 1200 / default 4000) with no `truncation_handled` event for
    that stage at all. The prompt's last required section
    ("## 한계와 미확인 사항") never survived, and the only attempt that ever
    cleared the citation bar (`dd8dc763` #2, ratio 0.1538 < 0.20) was
    rejected for missing it.

    Unlike `call_json` this never raises. There is no parse step that could
    fail, and a cut report is still a report -- §6.8 forbids the
    empty-handed exit that a raised error would produce here.
    """

    from neos.config.settings import settings

    response = await call_llm(
        model,
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        client=client,
        cassette=cassette,
        stage=stage,
    )
    if response.stop_reason != "max_tokens":
        return response

    # Retrying only helps if the ceiling -- not the budget -- was binding:
    # settling this call already shrank `remaining`, so a budget-clamped
    # retry gets *less* room, not more. Same judgement `call_json` makes.
    if response.granted_max_output_tokens < max_tokens:
        await _record_truncation_handled(
            stage=stage,
            model=model,
            requested=max_tokens,
            granted=response.granted_max_output_tokens,
            action="budget_bound",
        )
        return response

    multiplier = settings.config.deep_analysis.truncation_retry_multiplier
    try:
        retried = await call_llm(
            model,
            prompt,
            max_tokens=int(max_tokens * multiplier),
            temperature=temperature,
            client=client,
            cassette=cassette,
            stage=stage,
        )
    except TokenBudgetExhausted:
        # No room for the bigger attempt. The cut text still stands.
        await _record_truncation_handled(
            stage=stage,
            model=model,
            requested=max_tokens,
            granted=response.granted_max_output_tokens,
            action="budget_bound",
        )
        return response

    await _record_truncation_handled(
        stage=stage,
        model=model,
        requested=max_tokens,
        granted=retried.granted_max_output_tokens,
        action=(
            "retried_failed"
            if retried.stop_reason == "max_tokens"
            else "retried_ok"
        ),
    )
    if retried.stop_reason != "max_tokens":
        return retried
    # Both were cut. Neither is complete, so prefer the one that carries
    # more of the report -- the expanded attempt usually does, but a model
    # can wander and produce less from the same prompt.
    return retried if len(retried.text) >= len(response.text) else response


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

    On a `truncation_handled` event, `requested` is always the *original*
    ceiling passed in as `max_tokens`, but `granted` reflects the *final*
    attempt -- the expanded one, if an expansion retry ran. That means
    `granted` can exceed `requested` (a `retried_failed` outcome where the
    budget clamps the expanded attempt to something between the original
    and expanded ceilings): that is not a bug, it is the expanded ceiling
    being visible in the payload.
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
            # `expanded` takes priority: once an expansion retry has run,
            # "retried_failed" is the truthful label regardless of what
            # bound the second attempt. Recomputing `budget_bound` against
            # the already-doubled `limit` on the expanded attempt can be
            # True (e.g. ceiling 800 -> expanded to 1600 -> the global
            # token cap clamps `reserve` to ~1000) even though a retry DID
            # run -- mislabelling it "budget_bound" would also produce a
            # self-contradictory payload where granted > requested.
            action = "retried_failed" if expanded else "budget_bound"
            await _record_truncation_handled(
                stage=stage,
                model=model,
                requested=original_limit,
                granted=response.granted_max_output_tokens,
                action=action,
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
