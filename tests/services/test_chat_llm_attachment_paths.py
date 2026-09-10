import ast
import inspect
from types import SimpleNamespace

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


#: 메시지 목록을 만지지만 **조립하지는 않는** 지점. 가드가 이 둘을 알아야
#: 새로 나타난 이름이 진짜 넷째 사본인지 아닌지가 드러난다.
KNOWN_MESSAGE_READERS = {
    "_has_any_attachment",              # 지연 소유자 조회를 위한 판정
    "generate_response_stream",         # usage 추정용 content 길이 합산
}

#: 이름이 이것으로 끝나면 메시지 목록으로 본다. 특정 두 이름만 보던 옛 가드는
#: 다른 이름을 쓰는 사본을 놓쳤다.
MESSAGE_LIST_SUFFIX = "messages"


async def _fake_owner_user_id(conversation_id: str) -> str:
    """실제 DB 를 건드리지 않고 소유자 조회를 가짜로 채운다.

    `resolve_attachments` 자체도 각 테스트에서 가짜로 갈아끼우므로
    `owner_user_id` 값 자체은 이 테스트 스위트에서 검증 대상이 아니다 —
    Finding 1 커버리지는 `test_attachment_resolution.py` 가 진다.
    """
    return "u1"


def _iterated_name(iter_node: ast.expr) -> str | None:
    """순회 대상의 이름. `enumerate(...)` 로 감싼 것도 벗겨서 본다."""
    target = iter_node
    if (
        isinstance(target, ast.Call)
        and isinstance(target.func, ast.Name)
        and target.func.id == "enumerate"
        and target.args
    ):
        target = target.args[0]
    return target.id if isinstance(target, ast.Name) else None


def _iterates_message_list(iter_node: ast.expr) -> bool:
    """이름이 `…messages` 로 끝나는 목록을 순회하는가."""
    name = _iterated_name(iter_node)
    return bool(name) and name.endswith(MESSAGE_LIST_SUFFIX)


def _functions_touching_message_lists(source: str) -> set[str]:
    """메시지 목록을 순회하는 함수 이름 전부.

    `for` 와 `async for` 뿐 아니라 **컴프리헨션**까지 본다 — for 문만 보면
    `[render(m) for m in messages]` 로 쓴 사본이 가드를 그냥 지나간다.
    """
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, (ast.For, ast.AsyncFor)):
                iter_node = inner.iter
            elif isinstance(inner, ast.comprehension):
                iter_node = inner.iter
            else:
                continue
            if _iterates_message_list(iter_node):
                found.add(node.name)
    return found


def test_no_fourth_message_assembler_appears() -> None:
    found = _functions_touching_message_lists(inspect.getsource(chat_llm_service))
    expected = KNOWN_ASSEMBLERS | KNOWN_MESSAGE_READERS

    assert found == expected, (
        "메시지 목록을 만지는 지점이 바뀌었다. 새 이름이 나왔다면 그것이 "
        "**조립기**인지(첨부 병합을 함께 배선하고 KNOWN_ASSEMBLERS 에 더한다) "
        "단순 **독자**인지(KNOWN_MESSAGE_READERS 에 더한다) 사람이 판정할 것. "
        f"실제: {sorted(found)}"
    )


def test_guard_catches_a_comprehension_based_assembler() -> None:
    """옛 가드가 놓쳤을 모양 — for 문이 아니라 컴프리헨션으로 쓴 사본."""
    sample = (
        "def sneaky_fourth_assembler(conversation_messages):\n"
        "    return [render(m) for m in conversation_messages]\n"
    )

    assert _functions_touching_message_lists(sample) == {"sneaky_fourth_assembler"}


def test_guard_catches_a_differently_named_message_list() -> None:
    """옛 가드는 이름 두 개만 알아서 `history_messages` 를 놓쳤다."""
    sample = (
        "def another_assembler(history_messages):\n"
        "    out = []\n"
        "    for index, message in enumerate(history_messages):\n"
        "        out.append(message)\n"
        "    return out\n"
    )

    assert _functions_touching_message_lists(sample) == {"another_assembler"}


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

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    events = []
    async for event in service.generate_response_stream_with_tools(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        tools=[],
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

    async def fake_resolve(messages, *, model, owner_user_id=None):
        raise AttachmentNotSupportedError(
            model="blind-model",
            items=[{"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}],
        )

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )

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

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs, *, thinking_enabled=True):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    async for _event in service.generate_response_stream_with_tool_search(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        core_tools=[],
        search_handler=object(),
        model_name="claude-sonnet-5",
    ):
        pass

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_stream_path_surfaces_attachment_notices(monkeypatch) -> None:
    """첨부 안내가 완료 이벤트에 나타난다."""
    notice = {"index": 0, "name": "demoted.pdf", "reason": "byte_budget"}

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return AttachmentPlan(
            by_index={},
            notices=[notice],
        )

    # Mock the entire streaming path to avoid API calls
    class FakeChunk:
        def __init__(self):
            self.content = "response"
            self.response_metadata = {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                }
            }

    async def fake_astream(messages, **kwargs):
        yield FakeChunk()

    class FakeLLM:
        async def astream(self, messages, **kwargs):
            async for chunk in fake_astream(messages, **kwargs):
                yield chunk

    def fake_create_llm(**kwargs):
        return FakeLLM()

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(chat_llm_service, "create_llm", fake_create_llm)

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "help"}],
            model_name="claude-sonnet-5",
        )
    ]

    complete_events = [e for e in events if e.get("type") == "complete"]
    assert complete_events, f"No complete event: {events}"
    assert "attachment_notices" in complete_events[0]
    assert complete_events[0]["attachment_notices"] == [notice]


@pytest.mark.asyncio
async def test_tool_path_surfaces_attachment_notices(monkeypatch) -> None:
    """도구 경로도 첨부 안내를 완료 이벤트에 실린다."""
    notice = {"index": 0, "name": "blocked.docx", "reason": "vision_unsupported"}

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return AttachmentPlan(
            by_index={},
            notices=[notice],
        )

    # Fake the Anthropic client to run the path to completion
    class _FakeStream:
        def __aiter__(self):
            async def _empty():
                return
                yield  # pragma: no cover
            return _empty()

        async def get_final_message(self):
            return SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                ),
                content=[],
                stop_reason="end_turn",
            )

    class _FakeStreamCM:
        async def __aenter__(self):
            return _FakeStream()

        async def __aexit__(self, *exc):
            return False

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStreamCM()

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(
        chat_llm_service, "build_async_anthropic", lambda *a, **k: _FakeClient()
    )
    monkeypatch.setattr(
        chat_llm_service, "normalize_anthropic_usage",
        lambda usage, **kwargs: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_input_tokens": 0,
            "cache_status": "disabled",
            "iterations": [],
        },
    )

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream_with_tools(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "help"}],
            tools=[],
            model_name="claude-sonnet-5",
        )
    ]

    complete_events = [e for e in events if e.get("type") == "complete"]
    assert complete_events, f"완료 이벤트가 없다: {events}"
    assert "attachment_notices" in complete_events[0], f"첨부 안내가 없다: {complete_events[0]}"
    assert complete_events[0]["attachment_notices"] == [notice]


@pytest.mark.asyncio
async def test_tool_search_path_surfaces_attachment_notices(monkeypatch) -> None:
    """도구 검색 경로도 첨부 안내를 완료 이벤트에 실린다."""
    notice = {"index": 1, "name": "oversized.zip", "reason": "byte_budget"}

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return AttachmentPlan(
            by_index={},
            notices=[notice],
        )

    # Fake the Anthropic client to run the path to completion
    class _FakeStream:
        def __aiter__(self):
            async def _empty():
                return
                yield  # pragma: no cover
            return _empty()

        async def get_final_message(self):
            return SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                ),
                content=[],
                stop_reason="end_turn",
            )

    class _FakeStreamCM:
        async def __aenter__(self):
            return _FakeStream()

        async def __aexit__(self, *exc):
            return False

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStreamCM()

    class _FakeBetaMessages:
        def stream(self, **kwargs):
            return _FakeStreamCM()

    class _FakeClient:
        messages = _FakeMessages()
        beta = SimpleNamespace(messages=_FakeBetaMessages())

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(
        chat_llm_service, "build_async_anthropic", lambda *a, **k: _FakeClient()
    )
    monkeypatch.setattr(
        chat_llm_service, "normalize_anthropic_usage",
        lambda usage, **kwargs: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_input_tokens": 0,
            "cache_status": "disabled",
            "iterations": [],
        },
    )

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream_with_tool_search(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "help"}],
            core_tools=[],
            search_handler=object(),
            model_name="claude-sonnet-5",
        )
    ]

    complete_events = [e for e in events if e.get("type") == "complete"]
    assert complete_events, f"완료 이벤트가 없다: {events}"
    assert "attachment_notices" in complete_events[0], f"첨부 안내가 없다: {complete_events[0]}"
    assert complete_events[0]["attachment_notices"] == [notice]


@pytest.mark.asyncio
async def test_non_streaming_response_surfaces_attachment_notices(monkeypatch) -> None:
    """비스트림 경로도 첨부 안내를 응답 딕셔너리에 실린다."""
    notice = {"index": 0, "name": "too_large.pdf", "reason": "byte_budget"}

    async def fake_resolve(messages, *, model, owner_user_id=None):
        return AttachmentPlan(
            by_index={},
            notices=[notice],
        )

    class FakeResponse:
        def __init__(self):
            self.content = "test response"
            self.response_metadata = {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                }
            }

    async def fake_ainvoke(messages, **kwargs):
        return FakeResponse()

    class FakeLLM:
        async def ainvoke(self, messages, **kwargs):
            return await fake_ainvoke(messages, **kwargs)

    def fake_create_llm(**kwargs):
        return FakeLLM()

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(
        chat_llm_service, "_resolve_owner_user_id", _fake_owner_user_id
    )
    monkeypatch.setattr(chat_llm_service, "create_llm", fake_create_llm)

    service = chat_llm_service.ChatLLMService()
    result = await service.generate_response(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "help"}],
        model_name="claude-sonnet-5",
    )

    assert "attachment_notices" in result, f"첨부 안내가 없다: {result}"
    assert result["attachment_notices"] == [notice]


@pytest.mark.asyncio
async def test_refusal_happens_before_the_llm_client_is_built(monkeypatch) -> None:
    """거부될 턴에는 프로바이더 클라이언트를 짓지 않는다.

    순서가 반대면 프로바이더 설정 오류(API 키 부재 등)가 첨부 거부보다 먼저
    터져 진짜 사유를 가린다. CI 는 키가 없으므로 그 순서가 뒤집히면 여기서
    잡힌다 — 로컬은 키가 있어 조용히 통과하던 자리다.
    """
    from neos.services.attachment_blocks import AttachmentNotSupportedError

    created = []

    async def refusing_resolve(messages, *, model, owner_user_id):
        raise AttachmentNotSupportedError(
            model=model,
            items=[
                {"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}
            ],
        )

    def tracking_create_llm(*args, **kwargs):
        created.append(kwargs.get("model"))
        raise AssertionError("거부될 턴인데 LLM 클라이언트를 지었다")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", refusing_resolve)
    monkeypatch.setattr(chat_llm_service, "create_llm", tracking_create_llm)

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "봐줘"}],
            model_name="claude-sonnet-5",
        )
    ]

    assert created == [], "LLM 클라이언트가 거부보다 먼저 만들어졌다"
    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events and error_events[0]["code"] == "attachment_unsupported"


@pytest.mark.asyncio
async def test_non_streaming_refusal_also_precedes_the_llm_client(monkeypatch) -> None:
    """비스트림 경로도 같은 순서를 지킨다."""
    from neos.services.attachment_blocks import AttachmentNotSupportedError

    created = []

    async def refusing_resolve(messages, *, model, owner_user_id):
        raise AttachmentNotSupportedError(
            model=model,
            items=[
                {"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}
            ],
        )

    def tracking_create_llm(*args, **kwargs):
        created.append(kwargs.get("model"))
        raise AssertionError("거부될 턴인데 LLM 클라이언트를 지었다")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", refusing_resolve)
    monkeypatch.setattr(chat_llm_service, "create_llm", tracking_create_llm)

    service = chat_llm_service.ChatLLMService()
    with pytest.raises(AttachmentNotSupportedError):
        await service.generate_response(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "봐줘"}],
            model_name="claude-sonnet-5",
        )

    assert created == [], "LLM 클라이언트가 거부보다 먼저 만들어졌다"
