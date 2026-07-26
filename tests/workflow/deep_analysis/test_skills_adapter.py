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


def test_normalize_prefers_arxiv_html_abstract_over_pdf():
    # arxiv는 entry_url(HTML 초록)과 pdf_url을 둘 다 준다. fetch.py는 content-type
    # 분기 없이 html_to_text를 돌리므로 PDF를 고르면 쓰레기 텍스트가 되어
    # E_QUOTE_MISMATCH로 기각된다 — HTML을 골라야 검증을 통과한다.
    items = normalize_discovery_items(
        [
            {
                "entry_url": "https://arxiv.org/abs/2401.00001",
                "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
                "title": "A paper",
                "summary": "s",
            }
        ]
    )
    assert items[0]["url"] == "https://arxiv.org/abs/2401.00001"


def test_normalize_keeps_pubmed_items():
    # pubmed는 pubmed_url만 준다. 키 목록에 없으면 URL 없는 항목으로 취급돼
    # 정규화 단계에서 통째로 사라진다 — fetch까지 가지도 못한다.
    items = normalize_discovery_items(
        [{"pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "title": "P"}]
    )
    assert items == [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "title": "P", "snippet": ""}
    ]


def test_normalize_prefers_openalex_landing_page_over_pdf():
    items = normalize_discovery_items(
        [
            {
                "landing_page_url": "https://doi.org/10.1234/x",
                "pdf_url": "https://example.org/x.pdf",
                "title": "O",
            }
        ]
    )
    assert items[0]["url"] == "https://doi.org/10.1234/x"


def test_normalize_falls_back_to_pdf_when_it_is_the_only_url():
    # PDF만 있는 항목은 현재 검증을 통과하지 못하지만, 버리면 fetch.py가
    # PDF를 지원하게 됐을 때 조용히 누락된다. 최후 수단으로 남긴다.
    items = normalize_discovery_items(
        [{"pdf_url": "https://example.org/only.pdf", "title": "P"}]
    )
    assert items[0]["url"] == "https://example.org/only.pdf"


def test_normalize_still_prefers_plain_url_key():
    # url을 쓰는 스킬(semantic-scholar·sec-edgar·wikipedia·news-api·google-scholar)
    # 무회귀. news-api의 image_url을 집어서는 안 된다.
    items = normalize_discovery_items(
        [
            {
                "url": "https://news.example/article",
                "image_url": "https://news.example/thumb.jpg",
                "title": "N",
            }
        ]
    )
    assert items[0]["url"] == "https://news.example/article"


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
