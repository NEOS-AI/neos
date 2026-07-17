import pytest

from neos.workflow.deep_analysis.skills_adapter import (
    normalize_discovery_items,
    skill_search,
)


pytestmark = pytest.mark.no_db


class FakeSkillResult:
    def __init__(self, success, data):
        self.success = success
        self.data = data


class FakeSkill:
    def __init__(self, name="arxiv", result=None, init_ok=True):
        self.name = name
        self._result = result
        self._init_ok = init_ok
        self.cleaned_up = False
        self.executed_with = None

    async def initialize(self):
        return self._init_ok

    async def execute(self, params):
        self.executed_with = params
        return self._result

    async def cleanup(self):
        self.cleaned_up = True


def test_normalize_picks_url_title_snippet_from_varied_shapes():
    items = normalize_discovery_items(
        [
            {"url": "https://a.example/1", "title": "A", "summary": "sa"},
            {"link": "https://b.example/2", "name": "B", "abstract": "sb"},
            {"pdf_url": "https://c.example/3", "title": "C", "content": "sc"},
        ]
    )
    assert items == [
        {"url": "https://a.example/1", "title": "A", "snippet": "sa"},
        {"url": "https://b.example/2", "title": "B", "snippet": "sb"},
        {"url": "https://c.example/3", "title": "C", "snippet": "sc"},
    ]


def test_normalize_drops_items_without_url():
    # URL이 없으면 fetch.py가 blob을 만들 수 없고, DeterministicGrader가
    # E_SOURCE_DEAD로 거절한다. 검증 사슬에 못 들어가므로 여기서 버린다.
    items = normalize_discovery_items(
        [
            {"title": "no url", "summary": "x"},
            {"url": "", "title": "empty url"},
            {"url": "https://ok.example/1", "title": "ok"},
        ]
    )
    assert items == [{"url": "https://ok.example/1", "title": "ok", "snippet": ""}]


def test_normalize_handles_non_list_data():
    assert normalize_discovery_items(None) == []
    assert normalize_discovery_items({"url": "https://x.example"}) == []
    assert normalize_discovery_items("string") == []


@pytest.mark.asyncio
async def test_skill_search_runs_lifecycle_and_normalizes():
    skill = FakeSkill(
        result=FakeSkillResult(
            True, [{"url": "https://a.example/1", "title": "A", "summary": "s"}]
        )
    )
    items = await skill_search(skill, "moe routing", 5)

    assert items == [{"url": "https://a.example/1", "title": "A", "snippet": "s"}]
    assert skill.executed_with == {
        "query": "moe routing",
        "action": "search",
        "max_results": 5,
    }
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_returns_empty_when_init_fails_and_still_cleans_up():
    skill = FakeSkill(init_ok=False)
    assert await skill_search(skill, "q", 3) == []


@pytest.mark.asyncio
async def test_skill_search_returns_empty_on_unsuccessful_result():
    skill = FakeSkill(result=FakeSkillResult(False, None))
    assert await skill_search(skill, "q", 3) == []
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_swallows_skill_exception():
    class ExplodingSkill(FakeSkill):
        async def execute(self, params):
            raise RuntimeError("upstream 503")

    skill = ExplodingSkill()
    assert await skill_search(skill, "q", 3) == []
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_records_through_cassette():
    class FakeCassette:
        def __init__(self):
            self.keys = []

        async def remember(self, kind, payload, produce):
            self.keys.append((kind, payload))
            return await produce()

    cassette = FakeCassette()
    skill = FakeSkill(
        result=FakeSkillResult(True, [{"url": "https://a.example/1", "title": "A"}])
    )
    await skill_search(skill, "q", 3, cassette=cassette)

    assert cassette.keys == [("skill", {"skill": "arxiv", "query": "q", "limit": 3})]
