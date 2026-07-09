"""Pure async LLM calls with centralized JSON parsing and usage tracking."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from neos.config.settings import settings


class JSONParseError(ValueError):
    """Raised when an LLM response does not contain one valid JSON object."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


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


def _default_client(model: str):
    if model.startswith("claude"):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def _call_provider(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    client,
) -> LLMResponse:
    if model.startswith("claude"):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        output = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        )
        return LLMResponse(
            text=output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=getattr(response, "model", model),
        )

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return LLMResponse(
        text=response.choices[0].message.content or "",
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=getattr(response, "model", model),
    )


async def call_llm(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
) -> LLMResponse:
    async def produce() -> dict[str, Any]:
        resolved_client = client or _default_client(model)
        response = await _call_provider(
            model,
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            client=resolved_client,
        )
        return asdict(response)

    if cassette is None:
        return LLMResponse(**(await produce()))

    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    recorded = await cassette.remember("llm", payload, produce)
    return LLMResponse(**recorded)


async def call_json(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    retries: int = 1,
) -> tuple[dict[str, Any], LLMResponse]:
    last_error: JSONParseError | None = None
    for _attempt in range(retries + 1):
        response = await call_llm(
            model,
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            client=client,
            cassette=cassette,
        )
        try:
            return parse_json(response.text), response
        except JSONParseError as exc:
            last_error = exc

    if last_error is None:
        raise JSONParseError("JSON parsing failed without a response")
    raise last_error
