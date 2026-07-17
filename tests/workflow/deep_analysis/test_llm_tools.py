import pytest

from neos.workflow.deep_analysis.llm import call_messages


pytestmark = pytest.mark.no_db


class FakeBlock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeToolAnthropic:
    """stop_reason='tool_use' 응답을 1회 낸 뒤 'end_turn'을 내는 Fake."""

    def __init__(self):
        self.messages = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        class Usage:
            input_tokens = 7
            output_tokens = 3

        if len(self.calls) == 1:
            content = [
                FakeBlock(type="text", text="검색하겠습니다"),
                FakeBlock(
                    type="tool_use",
                    id="toolu_1",
                    name="search_arxiv",
                    input={"query": "moe routing"},
                ),
            ]
            stop_reason = "tool_use"
        else:
            content = [FakeBlock(type="text", text="완료")]
            stop_reason = "end_turn"

        return FakeBlock(
            content=content,
            usage=Usage(),
            model="claude-opus-4-6",
            stop_reason=stop_reason,
        )


@pytest.mark.asyncio
async def test_call_messages_passes_tools_and_returns_tool_use_blocks():
    client = FakeToolAnthropic()
    tools = [
        {
            "name": "search_arxiv",
            "description": "Search arXiv",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    response = await call_messages(
        "claude-opus-4-6",
        [{"role": "user", "content": "MoE 라우팅 조사"}],
        tools=tools,
        max_tokens=1000,
        client=client,
    )

    assert client.calls[0]["tools"] == tools
    assert response.stop_reason == "tool_use"
    tool_uses = [b for b in response.content if b["type"] == "tool_use"]
    assert tool_uses[0]["name"] == "search_arxiv"
    assert tool_uses[0]["input"] == {"query": "moe routing"}
    assert tool_uses[0]["id"] == "toolu_1"
    assert response.text == "검색하겠습니다"
    assert response.input_tokens == 7


@pytest.mark.asyncio
async def test_call_messages_omits_tools_key_when_none():
    client = FakeToolAnthropic()
    await call_messages(
        "claude-opus-4-6",
        [{"role": "user", "content": "hi"}],
        max_tokens=100,
        client=client,
    )
    assert "tools" not in client.calls[0]
