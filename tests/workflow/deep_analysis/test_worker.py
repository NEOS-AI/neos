import inspect

import pytest

from neos.workflow.deep_analysis.models import Effort, ProposedBlob
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

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
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


def test_worker_constructor_has_no_database_or_run_state():
    parameters = inspect.signature(Worker).parameters

    assert "session" not in parameters
    assert "session_for_fetch" not in parameters
    assert "run_id" not in parameters


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
    assert result.tokens_spent == 150
    assert result.self_assessment == 0.8
    assert result.blobs[0].content_hash == "0123456789abcdef"
    assert (
        result.claims[0].evidence[0].raw_ref
        == result.blobs[0].content_hash
    )
    assert "<evidence" in llm.prompts[0]
    assert "MoE routing reduces inference cost by 40 percent" in llm.prompts[0]


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

    assert result.claims[0].confidence == 1.0
    assert result.claims[0].evidence == []


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
