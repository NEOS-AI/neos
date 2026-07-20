import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.worker import Worker


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
        from neos.workflow.deep_analysis.models import ProposedBlob

        return ProposedBlob(
            content_hash="0123456789abcdef",
            source_url=url,
            http_status=200,
            raw_text="MoE routing reduces inference cost by 40 percent",
        )


def _fake_response(response_text: str):
    class Usage:
        input_tokens = 100
        output_tokens = 50

    class Block:
        type = "text"
        text = response_text

    class Response:
        content = [Block()]
        usage = Usage()
        model = "fake-model"

    return Response()


class WeakenLLM:
    """LLM used for weaken-only mode: returns a weakened repair for the
    claim, no `claims` key expected/used in this path."""

    def __init__(self):
        self.prompts = []
        self.messages = self

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        response_text = (
            '{"repairs": [{"claim_id": "c1", "new_text": '
            '"일부 사례에서 관찰되었다(단정 아님)"}]}'
        )
        return _fake_response(response_text)


class AbandonWeakenLLM(WeakenLLM):
    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return _fake_response(
            '{"repairs": [{"claim_id": "c1", "action": "abandoned"}]}'
        )


class RepairParsingLLM:
    """LLM used for the normal (search+fetch) path with a mix of repair
    codes: returns both claims and a `repairs` list to be parsed."""

    def __init__(self):
        self.prompts = []
        self.messages = self

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        response_text = (
            '{"status":"completed","claims":[{"text":"MoE routing reduces '
            'inference cost","confidence":0.6,"evidence":[{"source_url":'
            '"https://example.com/source","excerpt":"MoE routing reduces '
            'inference cost by 40 percent","raw_ref":"wrong"}]}],'
            '"self_assessment":0.8,"proposed_subquestions":[],"dead_ends":[],'
            '"repairs":[{"claim_id":"c2","action":"fixed",'
            '"new_text":"40퍼센트 감소는 관찰되지 않았다",'
            '"new_evidence":[{"source_url":"https://example.com/source",'
            '"excerpt":"MoE routing reduces inference cost by 40 percent"}]},'
            '{"claim_id":"c3","action":"abandoned"}]}'
        )
        return _fake_response(response_text)


@pytest.mark.asyncio
async def test_weaken_only_mode_skips_search_and_fetch():
    search = FakeSearch()
    fetch = FakeFetch()
    llm = WeakenLLM()
    worker = Worker(search, fetch_fn=fetch, llm_client=llm)

    repairs = [
        {
            "claim_id": "c1",
            "code": "E_OVERCLAIM",
            "detail": "과도한 일반화",
            "salvage": None,
        }
    ]

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
        repairs=repairs,
    )

    assert search.calls == []
    assert fetch.calls == []
    assert result.status == "completed"
    assert len(result.repairs) == 1
    assert result.repairs[0].claim_id == "c1"
    assert result.repairs[0].action == "weakened"
    assert result.repairs[0].new_text == "일부 사례에서 관찰되었다(단정 아님)"
    assert "날짜·집단·조건·수치 범위" in llm.prompts[0]
    assert "상관 근거에는 인과 표현" in llm.prompts[0]
    assert "action=abandoned" in llm.prompts[0]


@pytest.mark.asyncio
async def test_weaken_only_accepts_explicit_abandoned_action():
    search = FakeSearch()
    fetch = FakeFetch()
    worker = Worker(search, fetch_fn=fetch, llm_client=AbandonWeakenLLM())

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
        repairs=[{"claim_id": "c1", "code": "E_OVERCLAIM"}],
    )

    assert search.calls == []
    assert fetch.calls == []
    assert result.repairs[0].action == "abandoned"
    assert result.repairs[0].new_text is None


@pytest.mark.asyncio
async def test_mixed_or_other_code_repairs_go_through_normal_path_and_parse():
    search = FakeSearch()
    fetch = FakeFetch()
    llm = RepairParsingLLM()
    worker = Worker(search, fetch_fn=fetch, llm_client=llm)

    repairs = [
        {
            "claim_id": "c2",
            "code": "E_CONTRADICTED",
            "detail": "반대 증거 발견",
            "salvage": None,
        },
        {
            "claim_id": "c3",
            "code": "E_UNSUPPORTED",
            "detail": "근거 부족",
            "salvage": None,
        },
    ]

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
        repairs=repairs,
    )

    assert len(search.calls) == 1
    assert len(fetch.calls) == 1
    assert result.status == "completed"
    assert len(result.claims) == 1
    assert len(result.repairs) == 2

    fixed = next(r for r in result.repairs if r.claim_id == "c2")
    assert fixed.action == "fixed"
    assert fixed.new_text == "40퍼센트 감소는 관찰되지 않았다"
    assert len(fixed.new_evidence) == 1
    assert fixed.new_evidence[0].raw_ref == "0123456789abcdef"

    abandoned = next(r for r in result.repairs if r.claim_id == "c3")
    assert abandoned.action == "abandoned"


@pytest.mark.asyncio
async def test_investigate_without_repairs_is_unchanged():
    search = FakeSearch()
    fetch = FakeFetch()
    llm = RepairParsingLLM()
    worker = Worker(search, fetch_fn=fetch, llm_client=llm)

    result = await worker.investigate(
        "Question\n{fetched_evidence}",
        Effort.SCOUT,
        "question",
    )

    assert len(search.calls) == 1
    assert len(fetch.calls) == 1
    assert result.status == "completed"
    # repairs still parsed from data["repairs"] even without pending
    # feedback passed in -> proves the parsing is additive/unconditional.
    assert len(result.repairs) == 2
