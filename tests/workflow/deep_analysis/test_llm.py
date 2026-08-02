import pytest

from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.llm import (
    JSONParseError,
    LLMResponse,
    call_json,
    call_llm,
    call_messages,
    parse_json,
)
from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetExhausted,
    token_budget_scope,
)


pytestmark = pytest.mark.no_db


def test_parse_json_strips_code_fence_and_surrounding_text():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('result follows: {"x": 2} trailing') == {"x": 2}


def test_parse_json_rejects_missing_or_invalid_object():
    with pytest.raises(JSONParseError):
        parse_json("no json here")
    with pytest.raises(JSONParseError):
        parse_json('{"unterminated": true')


class FakeAnthropic:
    def __init__(self, texts, stop_reasons=None):
        self._texts = list(texts)
        self._stop_reasons = list(stop_reasons) if stop_reasons is not None else None
        self.messages = self
        self.calls = 0
        self.kwargs = []

    async def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        response_text = self._texts.pop(0)
        stop_reason = (
            self._stop_reasons.pop(0) if self._stop_reasons else "end_turn"
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

        Response.stop_reason = stop_reason
        return Response()


class FakeOpenAI:
    def __init__(self, text_value):
        self.text_value = text_value
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        class Message:
            content = self.text_value

        class Choice:
            message = Message()

        class Usage:
            prompt_tokens = 7
            completion_tokens = 3

        class Response:
            choices = [Choice()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


@pytest.mark.asyncio
async def test_call_llm_uses_provider_usage_fields():
    anthropic_response = await call_llm(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=100,
        client=FakeAnthropic(["answer"]),
    )
    openai_response = await call_llm(
        "gpt-5-mini",
        "prompt",
        max_tokens=100,
        client=FakeOpenAI("answer"),
    )

    assert (anthropic_response.input_tokens, anthropic_response.output_tokens) == (
        10,
        5,
    )
    assert (openai_response.input_tokens, openai_response.output_tokens) == (
        7,
        3,
    )


@pytest.mark.asyncio
async def test_claude_5_direct_call_uses_adaptive_thinking_without_temperature():
    client = FakeAnthropic(["answer"])

    await call_llm(
        "claude-sonnet-5",
        "prompt",
        max_tokens=100,
        temperature=0.7,
        client=client,
    )

    params = client.kwargs[0]
    assert "temperature" not in params
    assert params["thinking"] == {"type": "adaptive"}


@pytest.mark.asyncio
async def test_call_json_retries_once_after_parse_failure():
    client = FakeAnthropic(["garbage", '{"ok": true}'])

    data, response = await call_json(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=100,
        client=client,
    )

    assert data == {"ok": True}
    assert response.input_tokens == 10
    assert client.calls == 2


@pytest.mark.asyncio
async def test_call_llm_replay_does_not_construct_provider_client(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "llm.json"
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "prompt": "prompt",
        "max_tokens": 100,
        "temperature": 0.0,
    }
    record = Cassette(path, "record")

    async def recorded():
        return {
            "text": "cached",
            "input_tokens": 2,
            "output_tokens": 1,
            "model": payload["model"],
        }

    await record.remember("llm", payload, recorded)
    record.save()
    replay = Cassette(path, "replay")

    def forbidden(_model):
        raise AssertionError("provider client constructed in replay mode")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.llm._default_client",
        forbidden,
    )

    response = await call_llm(
        payload["model"],
        payload["prompt"],
        max_tokens=payload["max_tokens"],
        cassette=replay,
    )

    assert response.text == "cached"


def test_llm_response_defaults_keep_old_cassette_records_loadable():
    # 기존 golden cassette 레코드에는 content/stop_reason 키가 없다.
    old_record = {
        "text": "hello",
        "input_tokens": 10,
        "output_tokens": 5,
        "model": "claude-opus-4-6",
    }
    response = LLMResponse(**old_record)
    assert response.content == []
    assert response.stop_reason == ""


def test_llm_response_carries_content_blocks_and_stop_reason():
    response = LLMResponse(
        text="",
        input_tokens=1,
        output_tokens=2,
        model="claude-opus-4-6",
        content=[{"type": "tool_use", "id": "toolu_1", "name": "search_arxiv", "input": {"query": "moe"}}],
        stop_reason="tool_use",
    )
    assert response.stop_reason == "tool_use"
    assert response.content[0]["name"] == "search_arxiv"


@pytest.mark.asyncio
async def test_scoped_call_reduces_provider_limit_and_settles_usage():
    client = FakeAnthropic(["answer"])
    budget = TokenBudget(220)

    with token_budget_scope(budget):
        response = await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=1_000,
            client=client,
            stage="worker",
        )

    assert client.kwargs[0]["max_tokens"] < 1_000
    assert budget.consumed_tokens == response.input_tokens + response.output_tokens
    assert budget.reserved_tokens == 0


@pytest.mark.asyncio
async def test_scoped_call_does_not_dispatch_when_request_cannot_fit():
    client = FakeAnthropic(["unused"])
    budget = TokenBudget(1)

    with token_budget_scope(budget):
        with pytest.raises(TokenBudgetExhausted):
            await call_llm(
                "claude-haiku-4-5-20251001",
                "prompt",
                max_tokens=100,
                client=client,
            )

    assert client.calls == 0


@pytest.mark.asyncio
async def test_scoped_call_releases_reservation_on_pre_dispatch_failure(monkeypatch):
    budget = TokenBudget(500)

    def fail_before_dispatch(_model):
        raise RuntimeError("client unavailable")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.llm._default_client",
        fail_before_dispatch,
    )
    with token_budget_scope(budget):
        with pytest.raises(RuntimeError, match="client unavailable"):
            await call_llm(
                "claude-haiku-4-5-20251001",
                "prompt",
                max_tokens=100,
            )

    assert budget.reserved_tokens == 0
    assert budget.remaining_tokens == 500


@pytest.mark.asyncio
async def test_scoped_call_keeps_reservation_on_provider_failure():
    class FailingAnthropic(FakeAnthropic):
        async def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("provider failed")

    client = FailingAnthropic([])
    budget = TokenBudget(500)

    with token_budget_scope(budget):
        with pytest.raises(RuntimeError, match="provider failed"):
            await call_messages(
                "claude-haiku-4-5-20251001",
                [{"role": "user", "content": "prompt"}],
                max_tokens=100,
                client=client,
                stage="grader",
            )

    assert client.calls == 1
    assert budget.reserved_tokens > 0


@pytest.mark.asyncio
async def test_scoped_json_retry_reserves_and_settles_each_attempt():
    client = FakeAnthropic(["garbage", '{"ok": true}'])
    budget = TokenBudget(1_000)

    with token_budget_scope(budget):
        await call_json(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=100,
            client=client,
            retries=1,
            stage="decomposition",
        )

    assert client.calls == 2
    assert budget.consumed_tokens == 30
    assert budget.reserved_tokens == 0


@pytest.mark.asyncio
async def test_unscoped_call_preserves_requested_limit():
    client = FakeAnthropic(["answer"])

    await call_llm(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=123,
        client=client,
    )

    assert client.kwargs[0]["max_tokens"] == 123


@pytest.mark.asyncio
async def test_truncated_response_records_an_llm_truncated_event():
    # A response stopped at max_tokens must leave a durable trace: this bug
    # cost a whole baseline run precisely because nothing recorded it.
    events = []

    async def capture(kind, payload):
        events.append((kind, payload))

    client = FakeAnthropic(["truncated text"], stop_reasons=["max_tokens"])
    budget = TokenBudget(500, persist=capture)

    with token_budget_scope(budget):
        await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=100,
            client=client,
            stage="worker_analysis",
        )

    assert any(kind == "llm_truncated" for kind, _ in events)
    payload = next(p for k, p in events if k == "llm_truncated")
    assert payload["stage"] == "worker_analysis"
    assert payload["max_output_tokens"] > 0
    assert payload["output_tokens"] > 0
    # No response text may reach the event.
    assert "text" not in payload
    assert "content" not in payload


@pytest.mark.asyncio
async def test_completed_response_records_no_truncation_event():
    events = []

    async def capture(kind, payload):
        events.append((kind, payload))

    client = FakeAnthropic(["answer"], stop_reasons=["end_turn"])
    budget = TokenBudget(500, persist=capture)

    with token_budget_scope(budget):
        await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=100,
            client=client,
            stage="worker_analysis",
        )

    assert not any(kind == "llm_truncated" for kind, _ in events)


@pytest.mark.asyncio
async def test_truncation_event_does_not_replace_settlement():
    # The budget must still settle on the real usage; the new event is
    # additive, not a substitute.
    events = []

    async def capture(kind, payload):
        events.append((kind, payload))

    client = FakeAnthropic(["truncated text"], stop_reasons=["max_tokens"])
    budget = TokenBudget(500, persist=capture)

    with token_budget_scope(budget):
        await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=100,
            client=client,
            stage="worker_analysis",
        )

    kinds = [kind for kind, _ in events]
    assert "token_budget_settled" in kinds
    assert "llm_truncated" in kinds
    # Settlement stays first: never trade accounting correctness for
    # observability. A test that only checked presence would still pass
    # if the truncation event were emitted before settlement.
    assert kinds.index("token_budget_settled") < kinds.index("llm_truncated")


@pytest.mark.asyncio
async def test_granted_max_output_tokens_reports_the_requested_ceiling():
    """예산이 넉넉하면 허용 상한 == 요청 상한이다."""
    budget = TokenBudget(100_000)

    with token_budget_scope(budget):
        response = await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=500,
            client=FakeAnthropic(["answer"]),
        )

    assert response.granted_max_output_tokens == 500


@pytest.mark.asyncio
async def test_granted_max_output_tokens_reports_the_budget_clamp():
    """예산이 모자라면 허용 상한이 요청 상한보다 작다 — 이 차이가 재시도 판정의 근거다."""
    # conservative_input_bound가 요청 크기에 64를 더하므로 정확한 값 대신
    # "요청보다 작고 양수"만 단언한다.
    budget = TokenBudget(400)

    with token_budget_scope(budget):
        response = await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=5000,
            client=FakeAnthropic(["answer"]),
        )

    assert 0 < response.granted_max_output_tokens < 5000


@pytest.mark.asyncio
async def test_granted_max_output_tokens_without_a_budget_is_the_ceiling():
    """예산 스코프 밖에서는 깎을 것이 없으므로 항상 상한 그대로다."""
    response = await call_llm(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=300,
        client=FakeAnthropic(["answer"]),
    )

    assert response.granted_max_output_tokens == 300
