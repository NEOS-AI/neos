from __future__ import annotations

import httpx
import pytest

import anthropic
from neos.coding.model.anthropic import (
    AnthropicCodingModel,
    CodingModelError,
    _to_anthropic_request,
)
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
    ToolDefinition,
)
from neos.coding.prompts import SYSTEM_PROMPT_DYNAMIC_BOUNDARY


class RaisingMessages:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def stream(self, **request: object) -> None:
        raise self._error


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.messages = RaisingMessages(error)


def request(*, system: str = "Work safely.") -> ModelRequest:
    return ModelRequest(
        system=system,
        messages=(
            CanonicalMessage(
                role="user", content=(TextContent("Read README"),)
            ),
        ),
        tools=(
            ToolDefinition(
                name="read_file.v1",
                description="Read a file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ),
        model="claude-test",
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


def status_error(status_code: int) -> anthropic.APIStatusError:
    http_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=http_request)
    return anthropic.APIStatusError(
        "request too large", response=response, body=None
    )


@pytest.mark.asyncio
async def test_http_413_maps_to_prompt_too_long_retryable() -> None:
    client = RaisingClient(status_error(413))

    with pytest.raises(CodingModelError, match="prompt_too_long") as caught:
        _ = [item async for item in AnthropicCodingModel(client).stream(request())]

    assert caught.value.code == "prompt_too_long"
    assert caught.value.retryable is True


def test_to_anthropic_request_splits_cache_control_at_dynamic_boundary() -> None:
    static = "Stay in the sandbox."
    dynamic = "Current tools and lessons."
    payload = _to_anthropic_request(
        request(system=f"{static}{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}{dynamic}")
    )

    assert payload["system"] == [
        {
            "type": "text",
            "text": static,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic},
    ]


def test_to_anthropic_request_keeps_string_system_without_boundary() -> None:
    payload = _to_anthropic_request(request(system="Work safely."))

    assert payload["system"] == "Work safely."
