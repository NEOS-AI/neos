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
        (Effort.DIG, "dig", None, "claude-opus-5"),
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
