import json

import pytest

from neos.workflow.deep_analysis.llm import call_llm
from neos.workflow.deep_analysis.models import Effort, ProposedBlob
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted
from neos.workflow.deep_analysis.worker import Worker


pytestmark = pytest.mark.no_db


class Search:
    async def __call__(self, query, k):
        return [{"url": "https://example.com/source"}]


class Fetch:
    async def __call__(self, url, **kwargs):
        return ProposedBlob(
            content_hash="0123456789abcdef",
            source_url=url,
            http_status=200,
            raw_text="Direct evidence.",
        )


def _response(text, input_tokens=10, output_tokens=5):
    class Usage:
        pass

    Usage.input_tokens = input_tokens
    Usage.output_tokens = output_tokens

    class Block:
        type = "text"

    Block.text = text

    class Response:
        content = [Block()]
        usage = Usage()
        model = "fake-model"

    return Response()


def _generation(claims):
    return json.dumps(
        {
            "status": "completed",
            "claims": [
                {
                    "text": text,
                    "confidence": 0.6,
                    "evidence": [
                        {
                            "source_url": "https://example.com/source",
                            "excerpt": "Direct evidence.",
                        }
                    ],
                }
                for text in claims
            ],
        }
    )


class ScriptedLLM:
    def __init__(self, entailment):
        self.messages = self
        self.responses = [_generation(["keep", "broad", "drop"]), entailment]
        self.prompts = []
        self.max_tokens = []

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        self.max_tokens.append(kwargs["max_tokens"])
        return _response(self.responses.pop(0))


@pytest.mark.asyncio
async def test_worker_applies_one_batched_entailment_response():
    llm = ScriptedLLM(
        json.dumps(
            {
                "results": [
                    {"index": 0, "verdict": "keep"},
                    {
                        "index": 1,
                        "verdict": "narrow",
                        "narrowed_claim": "narrow",
                    },
                    {"index": 2, "verdict": "discard"},
                ]
            }
        )
    )
    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "narrow"]
    assert result.claims[1].confidence == 0.6
    assert result.claims[1].evidence[0].excerpt == "Direct evidence."
    assert result.tokens_spent == 30
    assert len(llm.prompts) == 2
    assert llm.max_tokens[1] == 1200
    assert '"index": 0' in llm.prompts[1]
    assert '"index": 2' in llm.prompts[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entailment",
    [
        "not json",
        '{"results":[{"index":0,"verdict":"keep"}]}',
        '{"results":[{"index":0,"verdict":"unknown"},'
        '{"index":1,"verdict":"keep"},{"index":2,"verdict":"discard"}]}',
    ],
)
async def test_worker_entailment_fail_open_is_atomic(entailment):
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=ScriptedLLM(entailment),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.tokens_spent == 30


class EntailmentTimeoutLLM:
    def __init__(self):
        self.messages = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _response(_generation(["keep", "broad", "drop"]))
        raise TimeoutError("provider timeout")


class NoClaimsLLM:
    def __init__(self):
        self.messages = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return _response(
            '{"status":"completed","claims":[],"self_assessment":0.5}'
        )


@pytest.mark.asyncio
async def test_worker_entailment_provider_failure_keeps_original_batch():
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=EntailmentTimeoutLLM(),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.tokens_spent == 15


@pytest.mark.asyncio
async def test_worker_skips_entailment_for_empty_claim_batch():
    llm = NoClaimsLLM()

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert result.claims == []
    assert llm.calls == 1
    assert result.tokens_spent == 15


@pytest.mark.asyncio
async def test_entailment_token_exhaustion_returns_buffered_partial(monkeypatch):
    async def exhausted(model, prompt, **kwargs):
        if kwargs["stage"] == "claim_entailment":
            raise TokenBudgetExhausted("cap")
        return await call_llm(model, prompt, **kwargs)

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.call_llm",
        exhausted,
    )
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=ScriptedLLM(
            '{"results":[{"index":0,"verdict":"keep"}]}'
        ),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert result.status == "partial"
    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.tokens_spent == 15
