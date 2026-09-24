"""네 진입점 모두에서 effort 가 나가는 요청에 도착한다.

진입점은 이름으로 센다 -- 개수는 누가 빠졌는지 말하지 않는다.
"""

import pytest

from neos.config.model_routing import EffortResolution
from neos.services import chat_llm_service
from neos.services.attachment_blocks import AttachmentPlan

pytestmark = pytest.mark.no_db

MSGS = [{"role": "user", "content": "hi"}]


async def _no_attachments(messages, *, model, owner_user_id=None):
    return AttachmentPlan(by_index={}, notices=[])


def _stub(monkeypatch, effort):
    calls: list = []

    async def fake_effort(model, conversation_id):
        calls.append((model, conversation_id))
        return EffortResolution(effort=effort)

    monkeypatch.setattr(chat_llm_service, "resolve_chat_effort", fake_effort)
    monkeypatch.setattr(chat_llm_service, "resolve_attachments", _no_attachments)
    return calls


def _capture_create_llm(monkeypatch, captured):
    def fake_create_llm(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop-after-create")

    monkeypatch.setattr(chat_llm_service, "create_llm", fake_create_llm)


def _capture_sdk(monkeypatch, captured):
    real = chat_llm_service.normalize_anthropic_request

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        out = real(model, kwargs, thinking_enabled=thinking_enabled)
        captured.update(out)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)


async def _drain(agen):
    try:
        async for _ in agen:
            pass
    except RuntimeError:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["claude-sonnet-5", "gpt-6-sol"])
async def test_generate_response_stream_passes_effort(monkeypatch, model) -> None:
    captured: dict = {}
    _stub(monkeypatch, "high")
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream(
        conversation_id="c", message_id="m", conversation_messages=MSGS, model_name=model,
    ))

    assert captured["effort"] == "high"


@pytest.mark.asyncio
async def test_generate_response_passes_effort(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "low")
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    try:
        await service.generate_response(
            conversation_id="c", message_id="m", conversation_messages=MSGS,
            model_name="claude-sonnet-5",
        )
    except RuntimeError:
        pass

    assert captured["effort"] == "low"


@pytest.mark.asyncio
async def test_no_effort_means_no_effort_kwarg_on_create_llm(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, None)
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        model_name="claude-sonnet-5",
    ))

    assert "effort" not in captured


@pytest.mark.asyncio
async def test_tool_path_puts_effort_in_output_config(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "high")
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tools(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        tools=[], model_name="claude-sonnet-5",
    ))

    assert captured["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_tool_search_path_puts_effort_in_output_config(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, "medium")
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tool_search(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        core_tools=[], search_handler=object(), model_name="claude-sonnet-5",
    ))

    assert captured["output_config"] == {"effort": "medium"}


@pytest.mark.asyncio
async def test_no_effort_means_no_key_on_the_sdk_path(monkeypatch) -> None:
    captured: dict = {}
    _stub(monkeypatch, None)
    _capture_sdk(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream_with_tools(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        tools=[], model_name="claude-sonnet-5",
    ))

    assert "output_config" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["with_tools", "with_tool_search"])
async def test_non_anthropic_tool_path_resolves_effort_once(monkeypatch, entry) -> None:
    """Review Focus 4: 위임해도 한 번만 해석하고 값이 사라지지 않는다."""
    captured: dict = {}
    calls = _stub(monkeypatch, "low")
    _capture_create_llm(monkeypatch, captured)

    service = chat_llm_service.ChatLLMService()
    if entry == "with_tools":
        agen = service.generate_response_stream_with_tools(
            conversation_id="c", message_id="m", conversation_messages=MSGS,
            tools=[], model_name="gpt-6-sol",
        )
    else:
        agen = service.generate_response_stream_with_tool_search(
            conversation_id="c", message_id="m", conversation_messages=MSGS,
            core_tools=[], search_handler=object(), model_name="gpt-6-sol",
        )
    await _drain(agen)

    assert calls == [("gpt-6-sol", "c")]
    assert captured["effort"] == "low"


@pytest.mark.asyncio
async def test_effort_resolution_does_not_look_up_the_owner(monkeypatch) -> None:
    """Fix round 2 Item 2: 첨부 없는 턴은 conversations 소유자 조회를 하지 않는다."""
    captured: dict = {}
    _stub(monkeypatch, "high")
    _capture_create_llm(monkeypatch, captured)
    owner_calls: list = []

    async def owner(conversation_id):
        owner_calls.append(conversation_id)
        return "u1"

    monkeypatch.setattr(chat_llm_service, "_resolve_owner_user_id", owner)

    service = chat_llm_service.ChatLLMService()
    await _drain(service.generate_response_stream(
        conversation_id="c", message_id="m", conversation_messages=MSGS,
        model_name="claude-sonnet-5",
    ))

    assert owner_calls == []
