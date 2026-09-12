from __future__ import annotations

import subprocess
import sys

import pytest

from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ToolCallCompleted,
)
from neos.coding.model.errors import CodingModelError
from neos.workflow.deep_analysis.harness_bridge import (
    da_provider_for_model,
    messages_to_canonical,
    looks_like_coding_model,
)
from neos.workflow.deep_analysis.llm import (
    LLMProviderError,
    call_json,
    call_llm,
    call_messages,
)


pytestmark = pytest.mark.no_db


class ScriptedCodingModel:
    def __init__(self, events) -> None:
        self.events = list(events)
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.events:
            yield event


def test_da_provider_follows_the_catalog() -> None:
    assert da_provider_for_model("claude-sonnet-5") == "anthropic"
    assert da_provider_for_model("gpt-6-astra") == "openai"
    assert da_provider_for_model("claude-from-the-future") == "anthropic"
    assert da_provider_for_model("gpt-from-the-future") == "openai"


def test_looks_like_coding_model_rejects_sdk_fakes() -> None:
    class FakeAnthropic:
        async def create(self, **kwargs):
            return None

        messages = None

    assert looks_like_coding_model(FakeAnthropic()) is False
    assert looks_like_coding_model(ScriptedCodingModel(())) is True


def test_tool_result_user_blocks_become_canonical_tool_messages() -> None:
    messages = messages_to_canonical(
        [
            {"role": "user", "content": "조사해"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "검색"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "search_arxiv",
                        "input": {"query": "moe"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "[]",
                    }
                ],
            },
        ]
    )

    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[2].role == "tool"
    assert messages[2].content[0].tool_call_id == "toolu_1"


@pytest.mark.asyncio
async def test_call_llm_uses_coding_model_stream_when_injected() -> None:
    model = ScriptedCodingModel(
        (
            TextDelta("harnessed"),
            ModelCompleted("end_turn", ModelUsage(4, 2)),
        )
    )

    response = await call_llm(
        "gpt-6-astra",
        "prompt",
        max_tokens=100,
        client=model,
    )

    assert response.text == "harnessed"
    assert response.input_tokens == 4
    assert response.output_tokens == 2
    assert response.stop_reason == "end_turn"
    assert model.requests[0].model == "gpt-6-astra"


@pytest.mark.asyncio
async def test_call_messages_maps_harness_tool_calls() -> None:
    model = ScriptedCodingModel(
        (
            TextDelta("검색하겠습니다"),
            ToolCallCompleted("toolu_1", "search_arxiv", {"query": "moe"}),
            ModelCompleted("tool_use", ModelUsage(7, 3)),
        )
    )
    response = await call_messages(
        "claude-sonnet-5",
        [{"role": "user", "content": "MoE"}],
        tools=[
            {
                "name": "search_arxiv",
                "description": "Search",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
        max_tokens=100,
        client=model,
    )

    assert response.stop_reason == "tool_use"
    assert response.text == "검색하겠습니다"
    assert response.content[1]["name"] == "search_arxiv"
    assert response.content[1]["input"] == {"query": "moe"}


@pytest.mark.asyncio
async def test_harness_failure_is_llm_provider_error_and_keeps_prior_spend() -> None:
    class FailOnSecond(ScriptedCodingModel):
        def __init__(self) -> None:
            super().__init__(())
            self.calls = 0

        async def stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls >= 2:
                raise CodingModelError("model_provider_failed", retryable=True)
            yield TextDelta("garbage")
            yield ModelCompleted("end_turn", ModelUsage(10, 5))

    client = FailOnSecond()
    with pytest.raises(LLMProviderError) as raised:
        await call_json(
            "gpt-6-astra",
            "prompt",
            max_tokens=100,
            client=client,
        )

    assert client.calls == 2
    assert raised.value.tokens_spent == 15
    assert isinstance(raised.value.__cause__, CodingModelError)


def test_importing_da_llm_does_not_import_durable_loop() -> None:
    script = (
        "import sys\n"
        "import neos.workflow.deep_analysis.llm as llm\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
        "from neos.workflow.deep_analysis import harness_bridge\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
        "import neos.subagent\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
        "import neos.workflow.deep_analysis.orchestrator\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
