import pytest

from neos.workflow.deep_analysis.discovery import build_tool_defs, run_discovery


pytestmark = pytest.mark.no_db


class FakeSkill:
    def __init__(self, name, items=None):
        self.name = name
        self.description = f"{name} search"
        self.items = items or []
        self.cleaned_up = False

    async def initialize(self):
        return True

    async def execute(self, params):
        outer = self

        class Result:
            success = True
            data = outer.items

        return Result()

    async def cleanup(self):
        self.cleaned_up = True


class FakeBlock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ScriptedAnthropic:
    """turns: 각 턴이 (content_blocks, stop_reason)."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.messages = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop_reason = self._turns.pop(0)

        class Usage:
            input_tokens = 10
            output_tokens = 4

        return FakeBlock(
            content=content,
            usage=Usage(),
            model="claude-opus-4-6",
            stop_reason=stop_reason,
        )


async def fake_search_fn(query, k):
    return [{"url": "https://web.example/1", "title": "web", "snippet": "w"}]


def test_build_tool_defs_always_includes_web_search():
    defs = build_tool_defs([])
    assert [d["name"] for d in defs] == ["search_web"]
    assert defs[0]["input_schema"]["required"] == ["query"]


def test_build_tool_defs_adds_one_tool_per_skill():
    defs = build_tool_defs([FakeSkill("arxiv"), FakeSkill("pubmed")])
    assert [d["name"] for d in defs] == ["search_web", "search_arxiv", "search_pubmed"]


@pytest.mark.asyncio
async def test_run_discovery_executes_tool_calls_and_collects_results():
    skill = FakeSkill(
        "arxiv", [{"url": "https://arxiv.example/1", "title": "paper", "summary": "s"}]
    )
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use",
                        id="t1",
                        name="search_arxiv",
                        input={"query": "moe"},
                    )
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )

    items, tokens = await run_discovery(
        "MoE 라우팅 조사",
        [skill],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )

    assert items == [
        {"url": "https://arxiv.example/1", "title": "paper", "snippet": "s"}
    ]
    assert tokens == 28  # 2턴 x (10 + 4)


@pytest.mark.asyncio
async def test_run_discovery_records_web_search_through_cassette():
    # search_fn을 직접 부르면 이 경로만 녹화에서 빠져 replay가 깨진다.
    # 키 형태는 Worker._search와 같아야 한다.
    class FakeCassette:
        def __init__(self):
            self.keys = []

        async def remember(self, kind, payload, produce):
            self.keys.append((kind, payload))
            return await produce()

    cassette = FakeCassette()
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use", id="t1", name="search_web", input={"query": "a"}
                    )
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    await run_discovery(
        "q",
        [],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
        cassette=cassette,
    )

    assert ("search", {"query": "a", "limit": 5}) in cassette.keys


@pytest.mark.asyncio
async def test_run_discovery_returns_all_tool_results_in_one_user_message():
    # 병렬 도구 호출 결과를 여러 user 메시지로 쪼개면 모델이 병렬 호출을 멈춘다.
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use", id="t1", name="search_web", input={"query": "a"}
                    ),
                    FakeBlock(
                        type="tool_use",
                        id="t2",
                        name="search_arxiv",
                        input={"query": "b"},
                    ),
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    await run_discovery(
        "q",
        [FakeSkill("arxiv", [{"url": "https://arxiv.example/1", "title": "p"}])],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )

    second_turn_messages = client.calls[1]["messages"]
    tool_result_messages = [
        m
        for m in second_turn_messages
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2


@pytest.mark.asyncio
async def test_run_discovery_dedups_urls_across_tools():
    skill = FakeSkill("arxiv", [{"url": "https://web.example/1", "title": "dup"}])
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use", id="t1", name="search_web", input={"query": "a"}
                    ),
                    FakeBlock(
                        type="tool_use",
                        id="t2",
                        name="search_arxiv",
                        input={"query": "b"},
                    ),
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    items, _ = await run_discovery(
        "q",
        [skill],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )
    assert [i["url"] for i in items] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_run_discovery_reports_unknown_tool_as_error_result():
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use",
                        id="t1",
                        name="search_bogus",
                        input={"query": "a"},
                    )
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    items, _ = await run_discovery(
        "q",
        [],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )
    assert items == []
    results = client.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True


@pytest.mark.asyncio
async def test_run_discovery_stops_at_max_turns():
    always_tool_use = (
        [FakeBlock(type="tool_use", id="t1", name="search_web", input={"query": "a"})],
        "tool_use",
    )
    client = ScriptedAnthropic([always_tool_use] * 10)
    items, _ = await run_discovery(
        "q",
        [],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
        max_turns=2,
    )
    assert len(client.calls) == 2
    assert [i["url"] for i in items] == ["https://web.example/1"]
