"""계층 어댑터 -- 정본 스키마는 하나, 어댑터는 계층마다 (D1c, D-8 b안).

`LLMCallRecord` 는 이미 프레임워크 중립이고(D1a), 영속화는 `add_record` 가
곧 수행한다(D1b). 남은 것은 계측이 닿지 않던 두 계층을 붙이는 일이다:
`neos/workflow/deep_analysis/`(자체 `LLMResponse`)와 `neos/coding/`
(`ModelUsage`/`ModelCompleted`). 로드맵 §11.1 이 "usage 표현이 셋 있고
콜렉터는 그중 하나만 안다"고 적은 상태를 끝낸다.

두 어댑터가 공유하는 규율 둘:
- **절대 던지지 않는다.** 계측 실패는 데이터 손실이지만, 예외를 올려보내면
  그 LLM 호출이나 코딩 루프가 죽는다.
- **토큰은 API 가 준 것만.** 설계 §A5 -- 자체 추정 금지.
"""

import pytest

from neos.dataset.adapters import record_llm_call
from neos.dataset.collector import LLMCallCollector


pytestmark = pytest.mark.no_db


@pytest.fixture
def collected(monkeypatch):
    """이 테스트가 만든 레코드만 본다 (싱글턴이 세션 간에 누적된다)."""
    captured = []
    monkeypatch.setattr(
        LLMCallCollector, "add_record", lambda self, record: captured.append(record)
    )
    return captured


def test_a_deep_analysis_call_becomes_a_canonical_record(collected):
    record_llm_call(
        provider="anthropic",
        model="claude-opus-5",
        workflow_step="report_assembly",
        input_messages=[{"role": "user", "content": "질문"}],
        output_text="답",
        input_tokens=120,
        output_tokens=45,
    )

    assert len(collected) == 1
    record = collected[0]
    assert record.model == "claude-opus-5"
    assert record.workflow_step == "report_assembly"
    assert record.prompt_tokens == 120
    assert record.completion_tokens == 45
    assert record.total_tokens == 165


def test_missing_usage_is_left_absent_rather_than_guessed(collected):
    """§A5 -- 0 을 지어내면 자체 추정이 된다."""
    record_llm_call(
        provider="anthropic",
        model="claude-sonnet-5",
        workflow_step="worker_analysis",
        input_messages=[],
        output_text="답",
        input_tokens=None,
        output_tokens=None,
    )

    record = collected[0]
    assert record.prompt_tokens is None
    assert record.completion_tokens is None
    assert record.total_tokens is None


def test_a_failing_collector_never_reaches_the_caller(monkeypatch):
    """계측이 본업을 막으면 안 된다."""

    def _boom(self, record):
        raise RuntimeError("collector is down")

    monkeypatch.setattr(LLMCallCollector, "add_record", _boom)

    record_llm_call(  # 던지지 않는다
        provider="anthropic",
        model="m",
        workflow_step="s",
        input_messages=[],
        output_text="",
        input_tokens=1,
        output_tokens=1,
    )


def test_a_failed_call_is_recorded_with_its_error(collected):
    record_llm_call(
        provider="anthropic",
        model="m",
        workflow_step="claim_grading",
        input_messages=[],
        output_text="",
        input_tokens=None,
        output_tokens=None,
        success=False,
        error_message="TimeoutError",
    )

    record = collected[0]
    assert record.success is False
    assert record.error_message == "TimeoutError"


@pytest.mark.asyncio
async def test_a_deep_analysis_dispatch_is_instrumented(collected):
    """D1c 완료 기준 -- `neos/workflow/deep_analysis/` 호출이 레코드로 남는다.

    `_budgeted_dispatch` 는 `call_llm` 과 `call_messages` 가 모두 지나가는 한
    곳이므로, 여기가 계측되면 이 계층 전체가 덮인다.
    """
    from neos.workflow.deep_analysis.llm import LLMResponse, _budgeted_dispatch

    async def invoke(limit, dispatch):
        return LLMResponse(
            text="조립된 리포트",
            input_tokens=77,
            output_tokens=33,
            model="claude-opus-5",
            stop_reason="end_turn",
        )

    await _budgeted_dispatch(
        model="claude-opus-5",
        request={"messages": [{"role": "user", "content": "프롬프트"}]},
        max_tokens=1200,
        stage="report_assembly",
        invoke=invoke,
    )

    assert len(collected) == 1
    record = collected[0]
    assert record.workflow_step == "report_assembly"
    assert record.model == "claude-opus-5"
    assert record.provider == "anthropic"
    assert record.prompt_tokens == 77


@pytest.mark.asyncio
async def test_a_deep_analysis_openai_dispatch_records_openai_provider(collected):
    from neos.workflow.deep_analysis.llm import LLMResponse, _budgeted_dispatch

    async def invoke(limit, dispatch):
        return LLMResponse(
            text="ok",
            input_tokens=1,
            output_tokens=1,
            model="gpt-6-astra",
            stop_reason="end_turn",
        )

    await _budgeted_dispatch(
        model="gpt-6-astra",
        request={"messages": [{"role": "user", "content": "q"}]},
        max_tokens=100,
        stage="scout",
        invoke=invoke,
    )

    assert collected[0].provider == "openai"
    assert collected[0].model == "gpt-6-astra"


@pytest.mark.asyncio
async def test_a_coding_stream_is_instrumented_once_per_completion(collected):
    """D1c 완료 기준 -- `neos/coding/` 호출이 레코드로 남는다."""
    from neos.dataset.adapters import TrackedCodingModel

    class _Usage:
        input_tokens = 11
        output_tokens = 22

    class _Delta:
        text = "코드 조각"

    class _Completed:
        stop_reason = "end_turn"
        usage = _Usage()

    class _Request:
        model = "claude-sonnet-5"
        messages = [{"role": "user", "content": "고쳐줘"}]

    class _Inner:
        async def stream(self, request):
            yield _Delta()
            yield _Completed()

    tracked = TrackedCodingModel(_Inner(), workflow_step="coding_loop")
    events = [event async for event in tracked.stream(_Request())]

    assert len(events) == 2  # 이벤트를 삼키지 않는다
    assert len(collected) == 1
    record = collected[0]
    assert record.workflow_step == "coding_loop"
    assert record.prompt_tokens == 11
    assert record.completion_tokens == 22
    assert record.output_text == "코드 조각"


@pytest.mark.asyncio
async def test_coding_stream_without_usage_is_not_recorded(collected):
    from neos.dataset.adapters import TrackedCodingModel

    class _Completed:
        stop_reason = "end_turn"
        usage = None

    class _Request:
        model = "gpt-6-astra"
        messages = []

    class _Inner:
        async def stream(self, request):
            yield _Completed()

    tracked = TrackedCodingModel(_Inner(), provider="openai", workflow_step="coding_loop")
    _ = [event async for event in tracked.stream(_Request())]

    assert collected == []
