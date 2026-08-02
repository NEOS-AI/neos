import json

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.llm import call_llm
from neos.workflow.deep_analysis.models import (
    Effort,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
)
from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetContractError,
    TokenBudgetExhausted,
    token_budget_scope,
)
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


def _claim_batch():
    return [
        ProposedClaim(
            text="supported claim",
            confidence=0.6,
            evidence=[
                ProposedEvidence(
                    source_url="https://example.com/source",
                    excerpt="Direct evidence.",
                    raw_ref="0123456789abcdef",
                )
            ],
        )
    ]


def _refinement_worker(*, llm_client=None, cassette=None):
    worker = Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=llm_client,
        cassette=cassette,
    )
    worker._model = "claude-haiku-4-5-20251001"
    return worker


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
                    {"index": 0, "action": "keep"},
                    {
                        "index": 1,
                        "action": "narrow",
                        "new_text": "narrow",
                    },
                    {"index": 2, "action": "discard"},
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
    assert llm.max_tokens[1] == settings.config.deep_analysis.entailment_max_output_tokens
    assert llm.max_tokens[1] > 1200  # the old literal must no longer bind
    assert '"index": 0' in llm.prompts[1]
    assert '"index": 2' in llm.prompts[1]


@pytest.mark.asyncio
async def test_scout_analysis_is_not_capped_by_the_effort_budget():
    # effort.token_cap is a budget, not a per-response output allowance.
    # SCOUT's 2000 truncated claim-bearing responses mid-JSON, losing every
    # claim in them. The analysis call must use the output ceiling instead.
    llm = ScriptedLLM(json.dumps({"results": [{"index": 0, "action": "keep"},
                                              {"index": 1, "action": "keep"},
                                              {"index": 2, "action": "keep"}]}))

    await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    analysis_max_tokens = llm.max_tokens[0]
    assert analysis_max_tokens == settings.config.deep_analysis.worker_max_output_tokens
    assert analysis_max_tokens > settings.config.deep_analysis.effort["scout"].token_cap


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entailment",
    [
        "not json",
        '{"results":[{"index":0,"action":"keep"}]}',
        '{"results":[{"index":0,"action":"unknown"},'
        '{"index":1,"action":"keep"},{"index":2,"action":"discard"}]}',
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
            '{"results":[{"index":0,"action":"keep"}]}'
        ),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert result.status == "partial"
    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.tokens_spent == 15


@pytest.mark.asyncio
async def test_worker_entailment_propagates_cassette_miss(tmp_path):
    cassette_path = tmp_path / "empty.json"
    cassette_path.write_text("{}", encoding="utf-8")
    worker = _refinement_worker(
        cassette=Cassette(cassette_path, mode="replay")
    )

    with pytest.raises(KeyError, match="cassette miss"):
        await worker._refine_claims(_claim_batch())


@pytest.mark.asyncio
async def test_worker_result_carries_discarded_claims():
    llm = ScriptedLLM(
        json.dumps(
            {
                "results": [
                    {"index": 0, "action": "keep"},
                    {
                        "index": 1,
                        "action": "narrow",
                        "new_text": "narrow",
                    },
                    {"index": 2, "action": "discard"},
                ]
            }
        )
    )

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    # narrow survives in claims and must not be reported as discarded
    assert [claim.text for claim in result.claims] == ["keep", "narrow"]
    assert [claim.text for claim in result.discarded_claims] == ["drop"]
    # evidence must survive so phase 2 can re-grade the claim
    assert result.discarded_claims[0].evidence[0].raw_ref == "0123456789abcdef"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entailment",
    [
        "not json",
        '{"results":[{"index":0,"action":"keep"}]}',
    ],
)
async def test_worker_records_no_discards_when_entailment_fails_open(
    entailment,
):
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=ScriptedLLM(entailment),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.discarded_claims == []


@pytest.mark.asyncio
async def test_worker_entailment_propagates_token_budget_contract_error():
    class ExcessiveUsageLLM:
        def __init__(self):
            self.messages = self

        async def create(self, **kwargs):
            return _response(
                '{"results":[{"index":0,"action":"keep"}]}',
                input_tokens=10_000,
                output_tokens=10_000,
            )

    worker = _refinement_worker(llm_client=ExcessiveUsageLLM())

    with token_budget_scope(TokenBudget(10_000)):
        with pytest.raises(TokenBudgetContractError):
            await worker._refine_claims(_claim_batch())
