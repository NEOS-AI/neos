import inspect
import logging

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.models import Effort, ProposedBlob
from neos.workflow.deep_analysis.pdf_text import PDFExtractionError
from neos.workflow.deep_analysis.worker import Worker
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted


pytestmark = pytest.mark.no_db


class FakeSearch:
    def __init__(self):
        self.calls = []

    async def __call__(self, query, k):
        self.calls.append((query, k))
        return [
            {
                "url": "https://example.com/source",
                "title": "Source",
                "snippet": "MoE routing",
            }
        ]


class FakeFetch:
    def __init__(self):
        self.calls = []

    async def __call__(self, url, **kwargs):
        self.calls.append(url)
        return ProposedBlob(
            content_hash="0123456789abcdef",
            source_url=url,
            http_status=200,
            raw_text="MoE routing reduces inference cost by 40 percent",
        )


class FakeLLM:
    def __init__(self):
        self.messages = self
        self.prompts = []
        self.models = []

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        self.models.append(kwargs["model"])
        response_text = (
            '{"status":"completed","claims":[{"text":"MoE routing reduces '
            'inference cost","confidence":0.6,"evidence":[{"source_url":'
            '"https://example.com/source","excerpt":"MoE routing reduces '
            'inference cost by 40 percent","raw_ref":"wrong"}]}],'
            '"self_assessment":0.8,"proposed_subquestions":[],"dead_ends":[]}'
        )

        class Usage:
            input_tokens = 100
            output_tokens = 50

        class Block:
            type = "text"
            text = response_text

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


class InventedSourceLLM(FakeLLM):
    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        response_text = (
            '{"status":"completed","claims":[{"text":"Invented",'
            '"confidence":5.0,"evidence":[{"source_url":'
            '"https://invented.example","excerpt":"fabricated",'
            '"raw_ref":"invented"}]}],"self_assessment":0.8,'
            '"proposed_subquestions":[],"dead_ends":[]}'
        )

        class Usage:
            input_tokens = 100
            output_tokens = 50

        class Block:
            type = "text"
            text = response_text

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


class SourceListSearch:
    def __init__(self, urls):
        self.urls = urls

    async def __call__(self, query, k):
        return [{"url": url} for url in self.urls]


class SourceListFetch:
    async def __call__(self, url, **kwargs):
        return ProposedBlob(
            content_hash=(url.encode().hex() + "0" * 16)[:16],
            source_url=url,
            http_status=200,
            raw_text=f"evidence for {url}",
        )


class ConfidenceLLM(FakeLLM):
    def __init__(self, urls, confidence):
        super().__init__()
        self.urls = urls
        self.confidence = confidence

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        evidence = [
            {"source_url": url, "excerpt": f"evidence for {url}"}
            for url in self.urls
        ]
        response_text = __import__("json").dumps(
            {
                "status": "completed",
                "claims": [
                    {
                        "text": "claim",
                        "confidence": self.confidence,
                        "evidence": evidence,
                    }
                ],
            }
        )

        class Usage:
            input_tokens = 10
            output_tokens = 5

        class Block:
            type = "text"
            text = response_text

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


def test_worker_constructor_has_no_database_or_run_state():
    parameters = inspect.signature(Worker).parameters

    assert "session" not in parameters
    assert "session_for_fetch" not in parameters
    assert "run_id" not in parameters


@pytest.mark.parametrize(
    ("effort", "field", "feature_model", "expected_model"),
    [
        (Effort.SCOUT, "scout", None, "claude-sonnet-5"),
        (Effort.SCOUT, "scout", "claude-scout-manual", "claude-scout-manual"),
        (Effort.DIG, "dig", None, "claude-opus-5-5"),
        (Effort.DIG, "dig", "claude-dig-manual", "claude-dig-manual"),
    ],
)
@pytest.mark.asyncio
async def test_worker_resolves_role_at_provider_boundary(
    monkeypatch, effort, field, feature_model, expected_model
) -> None:
    monkeypatch.setattr(
        settings.config.deep_analysis.models,
        field,
        feature_model,
    )
    llm = FakeLLM()
    worker = Worker(FakeSearch(), fetch_fn=FakeFetch(), llm_client=llm)

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        effort,
        "question",
    )

    assert result.model == expected_model
    assert llm.models
    assert set(llm.models) == {expected_model}


@pytest.mark.asyncio
async def test_worker_returns_blob_proposals_and_rewrites_raw_refs():
    search = FakeSearch()
    fetch = FakeFetch()
    llm = FakeLLM()
    worker = Worker(
        search,
        fetch_fn=fetch,
        llm_client=llm,
    )

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
    )

    assert result.status == "completed"
    assert result.tokens_spent == 300
    assert result.self_assessment == 0.8
    assert result.blobs[0].content_hash == "0123456789abcdef"
    assert (
        result.claims[0].evidence[0].raw_ref
        == result.blobs[0].content_hash
    )
    assert "<evidence" in llm.prompts[0]
    assert "MoE routing reduces inference cost by 40 percent" in llm.prompts[0]
    assert len(llm.prompts) == 2
    assert '"index": 0' in llm.prompts[1]


@pytest.mark.asyncio
async def test_flush_partial_returns_current_incremental_buffer():
    worker = Worker(FakeSearch(), fetch_fn=FakeFetch(), llm_client=FakeLLM())
    completed = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
    )

    partial = worker.flush_partial("question")

    assert partial.status == "partial"
    assert partial.claims == completed.claims
    assert partial.blobs == completed.blobs
    assert partial.tokens_spent == completed.tokens_spent


@pytest.mark.asyncio
async def test_worker_drops_unfetched_evidence_and_bounds_confidence():
    worker = Worker(
        FakeSearch(),
        fetch_fn=FakeFetch(),
        llm_client=InventedSourceLLM(),
    )

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
    )

    assert result.claims[0].confidence == 0.0
    assert result.claims[0].evidence == []
    assert result.confidence_clamped_count == 1
    assert result.confidence_clamped_by_source_count == {"0": 1}


@pytest.mark.parametrize(
    ("urls", "requested", "expected", "bucket"),
    [
        ([], 0.9, 0.0, "0"),
        (["a"], 0.9, 0.6, "1"),
        (["a", "b"], 0.9, 0.8, "2"),
        (["a", "b", "c"], 1.0, 0.95, "3_plus"),
        (["a", "a"], 0.7, 0.6, "1"),
    ],
)
@pytest.mark.asyncio
async def test_worker_clamps_after_retained_unique_sources(
    urls, requested, expected, bucket
):
    worker = Worker(
        SourceListSearch(urls),
        fetch_fn=SourceListFetch(),
        llm_client=ConfidenceLLM(urls, requested),
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
    )

    result = await worker.investigate(
        "Question\n{fetched_evidence}", Effort.SCOUT, "question"
    )

    assert result.claims[0].confidence == expected
    assert result.confidence_clamped_count == 1
    assert result.confidence_clamped_by_source_count == {bucket: 1}


@pytest.mark.asyncio
async def test_worker_does_not_count_confidence_at_cap_and_resets_next_run():
    worker = Worker(
        SourceListSearch(["a"]),
        fetch_fn=SourceListFetch(),
        llm_client=ConfidenceLLM(["a"], 0.9),
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
    )
    completed = await worker.investigate(
        "Question\n{fetched_evidence}", Effort.SCOUT, "question"
    )
    partial = worker.flush_partial("question")

    assert partial.confidence_clamped_count == completed.confidence_clamped_count
    assert (
        partial.confidence_clamped_by_source_count
        == completed.confidence_clamped_by_source_count
    )

    worker.llm_client = ConfidenceLLM(["a"], 0.6)
    boundary = await worker.investigate(
        "Question\n{fetched_evidence}", Effort.SCOUT, "question-2"
    )
    assert boundary.claims[0].confidence == 0.6
    assert boundary.confidence_clamped_count == 0
    assert boundary.confidence_clamped_by_source_count == {}


@pytest.mark.asyncio
async def test_worker_returns_accumulated_partial_when_budget_exhausts(monkeypatch):
    async def exhausted(*args, **kwargs):
        raise TokenBudgetExhausted("cap")

    monkeypatch.setattr("neos.workflow.deep_analysis.worker.call_json", exhausted)
    worker = Worker(FakeSearch(), fetch_fn=FakeFetch(), llm_client=FakeLLM())

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
    )

    assert result.status == "partial"
    assert len(result.blobs) == 1
    assert result.claims == []
    assert result.confidence_clamped_count == 0
    assert result.confidence_clamped_by_source_count == {}


@pytest.mark.asyncio
async def test_worker_skips_only_unreadable_pdf_source(caplog):
    class TwoSourceSearch:
        async def __call__(self, query, k):
            return [
                {"url": "https://example.com/broken.pdf"},
                {"url": "https://example.com/source"},
            ]

    class PartiallyFailingFetch(FakeFetch):
        async def __call__(self, url, **kwargs):
            if url.endswith("broken.pdf"):
                raise PDFExtractionError("secret parser payload")
            return await super().__call__(url, **kwargs)

    worker = Worker(
        TwoSourceSearch(),
        fetch_fn=PartiallyFailingFetch(),
        llm_client=FakeLLM(),
    )

    with caplog.at_level(logging.WARNING):
        result = await worker.investigate(
            "Question\n{fetched_evidence}",
            Effort.SCOUT,
            "question",
        )

    assert [blob.source_url for blob in result.blobs] == [
        "https://example.com/source"
    ]
    assert "https://example.com/broken.pdf" in caplog.text
    assert "PDFExtractionError" in caplog.text
    assert "secret parser payload" not in caplog.text


def test_tier_ranking_lifts_primary_sources_without_discarding_relevance():
    """`source_tiers` 는 여태 충돌 해소에서만 쓰였다 -- 어떤 클레임이 이기는지는
    정했지만 **무엇을 수집할지는 전혀 정하지 못했다.** 워커는 엔진이 준 상위
    N 개를 순서대로 전부 fetch 했고, 그래서 표본 #7 의 증거 119건 중 tier1 은
    19건(16%)이었다.

    tier 는 검색 순위를 **대체하지 않고 그 위에 얹힌다** -- 안정 정렬이므로
    같은 tier 안에서는 엔진의 관련도 순서가 그대로 남는다.
    """
    from neos.workflow.deep_analysis.worker import _rank_by_source_tier

    tiers = {"tier1": [".gov", "europa.eu"], "tier2": ["*"]}
    candidates = [
        {"url": "https://dev.to/a"},
        {"url": "https://blog.example.com/b"},
        {"url": "https://eur-lex.europa.eu/c"},
        {"url": "https://news.example.com/d"},
        {"url": "https://cdc.gov/e"},
    ]

    ranked = [c["url"] for c in _rank_by_source_tier(candidates, tiers)]

    assert ranked[:2] == ["https://eur-lex.europa.eu/c", "https://cdc.gov/e"]
    # tier2 끼리는 엔진이 준 순서 그대로다.
    assert ranked[2:] == [
        "https://dev.to/a",
        "https://blog.example.com/b",
        "https://news.example.com/d",
    ]


def test_tier_ranking_is_a_no_op_without_primary_sources():
    """tier1 후보가 없으면 아무것도 바뀌지 않아야 한다 -- 이 기능은 순위를
    흔드는 것이 아니라 1차 출처가 있을 때 그것을 앞세우는 것이다."""
    from neos.workflow.deep_analysis.worker import _rank_by_source_tier

    tiers = {"tier1": [".gov"], "tier2": ["*"]}
    urls = ["https://a.com/1", "https://b.com/2", "https://c.com/3"]

    ranked = _rank_by_source_tier([{"url": u} for u in urls], tiers)

    assert [c["url"] for c in ranked] == urls


@pytest.mark.asyncio
async def test_primary_source_augmentation_adds_candidates_the_base_query_missed():
    """D45 는 **후보 선택**만 고쳤다 -- 엔진이 tier1 을 0건 주면 정렬은 항등
    함수다. 증강 질의는 **무엇을 후보로 받는가**를 바꾼다.

    표본 #10 의 판정자 불만 두 가지 중 하나가 여기다: "질문이 요구한 공식 EU
    출처 대신 2차 비공식 출처".
    """

    class TieredSearch:
        """기저 질의는 tier2 만, 증강 질의는 tier1 을 준다."""

        def __init__(self):
            self.calls = []

        async def __call__(self, query, k):
            self.calls.append(query)
            if "official primary source" in query:
                return [{"url": "https://eur-lex.europa.eu/reg", "title": "t"}]
            return [
                {"url": f"https://blog.example.com/{i}", "title": "t"}
                for i in range(k)
            ]

    search = TieredSearch()
    fetch = FakeFetch()
    worker = Worker(search, fetch_fn=fetch, llm_client=FakeLLM())

    result = await worker.investigate(
        "Q\n{fetched_evidence}", Effort.SCOUT, "question", question_text="Q"
    )

    assert len(search.calls) == 2
    assert search.calls[0] == "Q"
    assert search.calls[1].startswith("Q ")
    # 기저 질의가 못 찾은 1차 출처를 증강이 찾아왔고, 슬라이스를 통과했다.
    assert result.search_augmentation["base_tier1"] == 0
    assert result.search_augmentation["added_tier1"] == 1
    assert result.search_augmentation["selected_tier1"] == 1
    assert "https://eur-lex.europa.eu/reg" in fetch.calls


@pytest.mark.asyncio
async def test_augmentation_never_removes_a_base_candidate():
    """증강 질의가 관련도를 흐리는 최악의 경우에도 결과는 기저 질의의
    **상위집합**이어야 한다. 그래야 이 기능이 손해를 볼 수 없다."""
    from neos.workflow.deep_analysis.worker import _merge_candidates

    base = [{"url": "https://a.com/1"}, {"url": "https://b.com/2"}]
    extra = [{"url": "https://b.com/2"}, {"url": "https://junk.com/9"}]

    merged = [c["url"] for c in _merge_candidates(base, extra)]

    # 기저가 먼저, 중복 없이, 증강은 뒤에만 붙는다. `_rank_by_source_tier` 가
    # 안정 정렬이므로 같은 tier 안에서는 이 순서가 그대로 남는다.
    assert merged == ["https://a.com/1", "https://b.com/2", "https://junk.com/9"]


@pytest.mark.asyncio
async def test_empty_augment_string_skips_the_second_query():
    """빈 문자열이 off 스위치다 -- 별도 플래그를 두지 않는다."""
    search = FakeSearch()
    worker = Worker(search, fetch_fn=FakeFetch(), llm_client=FakeLLM())
    config = settings.config.deep_analysis
    original = config.search_primary_augment
    object.__setattr__(config, "search_primary_augment", "")
    try:
        result = await worker.investigate(
            "Q\n{fetched_evidence}", Effort.SCOUT, "question", question_text="Q"
        )
    finally:
        object.__setattr__(config, "search_primary_augment", original)

    assert len(search.calls) == 1
    assert result.search_augmentation["added_candidates"] == 0


@pytest.mark.asyncio
async def test_wider_candidate_search_does_not_widen_fetching():
    """넓게 받아 고르되 **fetch 수는 그대로**여야 한다.

    이 기능이 비용을 늘리면 안 된다 -- 늘어나는 것은 검색 결과 몇 줄이고,
    fetch(그리고 그 뒤의 프롬프트 크기)는 `search_result_limit` 에 묶인다.
    """
    from neos.config.settings import settings

    config = settings.config.deep_analysis
    limit = config.search_result_limit

    class WideSearch:
        def __init__(self):
            self.calls = []

        async def __call__(self, query, k):
            self.calls.append((query, k))
            # 엔진이 요청한 만큼 준다 -- 전부 tier2 라 순위는 그대로다.
            return [
                {"url": f"https://example.com/{i}", "title": "t", "snippet": "s"}
                for i in range(k)
            ]

    search = WideSearch()
    fetch = FakeFetch()
    worker = Worker(search, fetch_fn=fetch, llm_client=FakeLLM())

    await worker.investigate("Q\n{fetched_evidence}", Effort.SCOUT, "question")

    requested = search.calls[0][1]
    assert requested == limit * config.source_candidate_multiplier
    assert requested > limit
    assert len(fetch.calls) == limit
