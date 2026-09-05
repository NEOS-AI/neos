import ast
import inspect

import pytest

from neos.services import chat_llm_service
from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentPlan,
    ResolvedAttachment,
)

#: 대화 메시지를 각자 조립하는 지점. 넷째가 생기면 이 테스트가 빨개진다.
#: 개수가 아니라 이름으로 센다 — 개수는 누가 빠졌는지 말하지 않는다.
KNOWN_ASSEMBLERS = {
    "_build_messages",
    "generate_response_stream_with_tools",
    "generate_response_stream_with_tool_search",
}


MESSAGE_LIST_NAMES = {"conversation_messages", "optimized_messages"}


def _iterates_message_list(node: ast.For) -> bool:
    """`for … in messages:` 와 `for i, m in enumerate(messages):` 둘 다 센다.

    배선이 enumerate 를 도입하므로 Name 만 보면 사본을 놓친다.
    """
    target = node.iter
    if isinstance(target, ast.Call) and isinstance(target.func, ast.Name):
        if target.func.id != "enumerate" or not target.args:
            return False
        target = target.args[0]
    return isinstance(target, ast.Name) and target.id in MESSAGE_LIST_NAMES


def _functions_iterating_conversation_messages() -> set[str]:
    source = inspect.getsource(chat_llm_service)
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.For) and _iterates_message_list(inner):
                found.add(node.name)
    return found


def test_no_fourth_message_assembler_appears() -> None:
    found = _functions_iterating_conversation_messages()

    assert found == KNOWN_ASSEMBLERS, (
        "메시지 조립 사본이 바뀌었다. 새 사본이면 첨부 병합을 함께 배선하고 "
        f"KNOWN_ASSEMBLERS 에 이름을 더할 것. 실제: {sorted(found)}"
    )


def _plan_with_image(index: int) -> AttachmentPlan:
    return AttachmentPlan(
        by_index={
            index: [
                ResolvedAttachment(
                    name="scan.png",
                    mime_type="image/png",
                    kind=AttachmentKind.IMAGE,
                    data=b"png",
                    text=None,
                )
            ]
        },
        notices=[],
    )


def test_build_messages_carries_the_attachment_block() -> None:
    service = chat_llm_service.ChatLLMService()

    messages = service._build_messages(
        [{"role": "user", "content": "봐줘"}],
        None,
        plan=_plan_with_image(0),
    )

    content = messages[-1].content
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[-1] == {"type": "text", "text": "봐줘"}


def test_build_messages_without_a_plan_keeps_plain_strings() -> None:
    service = chat_llm_service.ChatLLMService()

    messages = service._build_messages([{"role": "user", "content": "안녕"}], None)

    assert messages[-1].content == "안녕"


@pytest.mark.asyncio
async def test_tool_path_carries_the_attachment_block(monkeypatch) -> None:
    """raw SDK 경로도 첨부를 싣는다 — 여기가 비면 툴 대화에서만 조용히 사라진다."""
    captured = {}

    async def fake_resolve(messages, *, model):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    events = []
    async for event in service.generate_response_stream_with_tools(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        model_name="claude-sonnet-5",
    ):
        events.append(event)

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_stream_path_reports_a_refusal_as_an_error_event(monkeypatch) -> None:
    from neos.services.attachment_blocks import AttachmentNotSupportedError

    async def fake_resolve(messages, *, model):
        raise AttachmentNotSupportedError(
            model="blind-model",
            items=[{"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}],
        )

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "봐줘"}],
            model_name="blind-model",
        )
    ]

    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events, f"오류 이벤트가 없다: {events}"
    assert error_events[0]["code"] == "attachment_unsupported"
    assert "scan.png" in error_events[0]["error"]


@pytest.mark.asyncio
async def test_tool_search_path_carries_the_attachment_block(monkeypatch) -> None:
    """세 번째 사본. 앞의 둘이 초록이어도 여기가 비면 tool search 대화에서 사라진다."""
    captured = {}

    async def fake_resolve(messages, *, model):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    async for _event in service.generate_response_stream_with_tool_search(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        model_name="claude-sonnet-5",
    ):
        pass

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
