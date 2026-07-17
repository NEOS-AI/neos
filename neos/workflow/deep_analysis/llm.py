"""Pure async LLM calls with centralized JSON parsing and usage tracking."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
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
    # 기본값이 필수다: 기존 golden cassette 레코드에는 이 키들이 없고,
    # 재생 시 LLMResponse(**recorded)로 복원된다(D19 golden 게이트 유지).
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""


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
    if model.startswith("claude"):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
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


async def call_messages(
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
) -> LLMResponse:
    async def produce() -> dict[str, Any]:
        resolved_client = client or _default_client(model)
        response = await _call_provider(
            model,
            messages,
            max_tokens=max_tokens,
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
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    recorded = await cassette.remember("llm", payload, produce)
    return LLMResponse(**recorded)


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
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
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
