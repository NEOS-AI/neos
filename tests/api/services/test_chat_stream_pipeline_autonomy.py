import json
import os
import sys
import types
from types import SimpleNamespace

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

youtube_module = types.ModuleType("youtube_transcript_api")
youtube_module.YouTubeTranscriptApi = object
youtube_errors_module = types.ModuleType("youtube_transcript_api._errors")
youtube_errors_module.TranscriptsDisabled = Exception
youtube_errors_module.NoTranscriptFound = Exception
youtube_errors_module.VideoUnavailable = Exception
sys.modules.setdefault("youtube_transcript_api", youtube_module)
sys.modules.setdefault("youtube_transcript_api._errors", youtube_errors_module)

googleapi_module = types.ModuleType("googleapiclient")
googleapi_discovery_module = types.ModuleType("googleapiclient.discovery")
googleapi_discovery_module.build = lambda *args, **kwargs: object()
googleapi_errors_module = types.ModuleType("googleapiclient.errors")
googleapi_errors_module.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapi_module)
sys.modules.setdefault("googleapiclient.discovery", googleapi_discovery_module)
sys.modules.setdefault("googleapiclient.errors", googleapi_errors_module)

isodate_module = types.ModuleType("isodate")
isodate_module.parse_duration = lambda value: value
sys.modules.setdefault("isodate", isodate_module)

from neos.api.adapters.stream_adapter import create_stream_generator
from neos.api.services.chat_stream_pipeline import ChatStreamPipeline, _WorkflowCtx


class _FakeWorkflowCallback:
    def __init__(self, session_id, event_queue, enable_db_logging, user_id):
        self.session_id = session_id
        self.event_queue = event_queue

    async def on_approval_request(self, pending_approvals, session_id):
        await self.event_queue.put(
            SimpleNamespace(
                event="approval_request",
                data={"pending_approvals": pending_approvals},
                node_name=None,
                progress_percent=0,
                content=None,
            )
        )


class _FakeWorkflow:
    def __init__(self):
        self.use_checkpointer = None
        self.user_input = None

    async def execute_workflow(self, user_input, event_handler, use_checkpointer):
        self.use_checkpointer = use_checkpointer
        self.user_input = user_input
        await event_handler.on_approval_request(
            [
                {
                    "request_id": "approval-1",
                    "skill_name": "knowledge_search",
                    "params": {"query": user_input["query"]},
                }
            ],
            user_input["session_id"],
        )
        return {"success": True, "interrupted": True, "response": None}


class _ScriptedWorkflow:
    """큐에 지정된 이벤트를 그대로 발행하고 완료하는 워크플로우.

    `WorkflowStreamCallback._create_event`가 만드는 모양
    (`event` / `node_name` / `content` / `data` / `progress_percent`)을 흉내낸다.
    실제로 워크플로우에 전달된 `user_input`도 포착해 둔다 (테스트 검증용).
    """

    def __init__(self, events):
        self._events = events
        self.user_input = None

    async def execute_workflow(self, user_input, event_handler, use_checkpointer):
        self.user_input = user_input
        for event in self._events:
            await event_handler.event_queue.put(event)
        await event_handler.event_queue.put(
            SimpleNamespace(
                event="completed",
                data={},
                node_name=None,
                progress_percent=100,
                content=None,
            )
        )
        return {"success": True, "response": "done"}


class _PassthroughCallback:
    def __init__(self, session_id, event_queue, enable_db_logging, user_id):
        self.event_queue = event_queue


def _run_scripted_workflow(events):
    """`_run_workflow`를 돌려 SSE payload 목록을 돌려준다."""
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=_ScriptedWorkflow(events),
        workflow_callback_cls=_PassthroughCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    return pipeline, stream_state


async def _collect_payloads(pipeline, stream_state):
    payloads = []
    async for chunk in pipeline._run_workflow(
        conversation_id="conversation_123",
        user_content="analyse this",
        current_user=SimpleNamespace(user_id="user_123"),
        history_messages=[],
        stream_state=stream_state,
        wf_ctx=_WorkflowCtx(),
        autonomy_level=1,
    ):
        for line in chunk.splitlines():
            if line.startswith("data: {"):
                payloads.append(json.loads(line.removeprefix("data: ").strip()))
    return payloads


@pytest.mark.asyncio
async def test_run_workflow_forwards_deep_analysis_started_handle():
    """D23: job 핸들이 챗 SSE로 나가지 않으면 프론트가 run에 붙을 방법이 없다."""
    pipeline, stream_state = _run_scripted_workflow(
        [
            SimpleNamespace(
                event="deep_analysis_started",
                data={
                    "run_id": "run-abc",
                    "events_url": "/api/v1/deep-analysis/run-abc/events",
                    "assistant_message_id": "assistant-1",
                },
                node_name="deep_analysis",
                progress_percent=10,
                content=None,
            )
        ]
    )

    payloads = await _collect_payloads(pipeline, stream_state)

    started = [p for p in payloads if p["type"] == "neos:deep_analysis_started"]
    assert len(started) == 1
    assert started[0]["run_id"] == "run-abc"
    assert started[0]["events_url"] == "/api/v1/deep-analysis/run-abc/events"
    assert started[0]["assistant_message_id"] == "assistant-1"


@pytest.mark.asyncio
async def test_run_workflow_converts_harness_progress_to_harness_event():
    """하네스 진행은 `neos:harness`여야 한다 — JSON 문자열을 progress에 실어 보내면 안 된다."""
    pipeline, stream_state = _run_scripted_workflow(
        [
            SimpleNamespace(
                event="agent_progress",
                data={},
                node_name="research_harness",
                progress_percent=40,
                content=json.dumps(
                    {
                        "event": "harness_check_completed",
                        "run_id": "run-abc",
                        "timestamp": "2026-09-03T00:00:00Z",
                        "data": {"check": "citation", "passed": True},
                    }
                ),
            )
        ]
    )

    payloads = await _collect_payloads(pipeline, stream_state)

    harness = [p for p in payloads if p["type"] == "neos:harness"]
    assert len(harness) == 1
    assert harness[0]["event"] == "harness_check_completed"
    assert harness[0]["run_id"] == "run-abc"
    assert harness[0]["data"] == {"check": "citation", "passed": True}
    assert not [p for p in payloads if p["type"] == "neos:workflow_progress"]


@pytest.mark.asyncio
async def test_run_workflow_keeps_plain_progress_as_workflow_progress():
    """하네스가 아닌 노드의 진행은 그대로 `neos:workflow_progress`로 남는다."""
    pipeline, stream_state = _run_scripted_workflow(
        [
            SimpleNamespace(
                event="agent_progress",
                data={},
                node_name="search_orchestrator",
                progress_percent=55,
                content="검색 중",
            )
        ]
    )

    payloads = await _collect_payloads(pipeline, stream_state)

    progress = [p for p in payloads if p["type"] == "neos:workflow_progress"]
    assert len(progress) == 1
    assert progress[0]["progress_percent"] == 55
    assert progress[0]["message"] == "검색 중"
    assert not [p for p in payloads if p["type"] == "neos:harness"]


@pytest.mark.asyncio
async def test_run_workflow_excludes_current_turn_from_chat_history():
    """현재 턴은 `query`가 나른다 — `chat_history`에도 있으면 워크플로우가 두 번 본다."""
    workflow = _ScriptedWorkflow(events=[])
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=workflow,
        workflow_callback_cls=_PassthroughCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    # `history_messages`는 ascending order의 tail 조회라, 방금 저장한 현재
    # 유저 턴이 마지막 원소다 (chat_stream_pipeline.py Step 1/3 참고).
    history = [
        {"role": "assistant", "content": "hi, how can I help?"},
        {"role": "user", "content": "what is the weather today?"},
    ]

    [
        chunk
        async for chunk in pipeline._run_workflow(
            conversation_id="conversation_123",
            user_content="what is the weather today?",
            current_user=SimpleNamespace(user_id="user_123"),
            history_messages=history,
            stream_state=stream_state,
            wf_ctx=_WorkflowCtx(),
            autonomy_level=1,
        )
    ]

    assert workflow.user_input["query"] == "what is the weather today?"
    chat_history = workflow.user_input["chat_history"]
    contents = [m["content"] for m in chat_history]
    assert "what is the weather today?" not in contents, (
        f"current turn leaked into chat_history: {chat_history!r}"
    )
    assert contents == ["hi, how can I help?"]


@pytest.mark.asyncio
async def test_run_workflow_history_keeps_most_recent_n_in_ascending_order(monkeypatch):
    """히스토리가 MAX_HISTORY_MESSAGES보다 길면 **최근** N개가 오름차순으로 가야 한다."""
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.MAX_HISTORY_MESSAGES",
        2,
    )
    workflow = _ScriptedWorkflow(events=[])
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=workflow,
        workflow_callback_cls=_PassthroughCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    # 오름차순 tail. 마지막 원소가 방금 저장된 현재 턴.
    history = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "turn 2"},
        {"role": "assistant", "content": "reply 2"},
        {"role": "user", "content": "turn 3 (current)"},
    ]

    [
        chunk
        async for chunk in pipeline._run_workflow(
            conversation_id="conversation_123",
            user_content="turn 3 (current)",
            current_user=SimpleNamespace(user_id="user_123"),
            history_messages=history,
            stream_state=stream_state,
            wf_ctx=_WorkflowCtx(),
            autonomy_level=1,
        )
    ]

    chat_history = workflow.user_input["chat_history"]
    contents = [m["content"] for m in chat_history]
    # 오래된 2개("turn 1", "reply 1")가 아니라, 최근 2개("turn 2", "reply 2")여야 한다.
    assert contents == ["turn 2", "reply 2"], (
        f"expected the most recent 2 prior messages in ascending order, got {contents!r}"
    )


@pytest.mark.asyncio
async def test_run_workflow_history_empty_when_only_current_turn():
    """대화의 첫 메시지: 히스토리가 현재 턴 하나뿐이면 제외 후 빈 리스트가 되어야 한다."""
    workflow = _ScriptedWorkflow(events=[])
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=workflow,
        workflow_callback_cls=_PassthroughCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    history = [{"role": "user", "content": "first message ever"}]

    [
        chunk
        async for chunk in pipeline._run_workflow(
            conversation_id="conversation_123",
            user_content="first message ever",
            current_user=SimpleNamespace(user_id="user_123"),
            history_messages=history,
            stream_state=stream_state,
            wf_ctx=_WorkflowCtx(),
            autonomy_level=1,
        )
    ]

    assert workflow.user_input["chat_history"] == []


class _RecordingLLMService:
    """`generate_response_stream_with_tools`에 실제로 전달된 kwargs를 포착한다."""

    def __init__(self):
        self.received_kwargs = None

    async def generate_response_stream_with_tools(self, **kwargs):
        self.received_kwargs = kwargs
        yield {
            "type": "complete",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost": {"total_cost": 0},
            "latency_ms": 0,
        }


class _HistoryChatService:
    """`get_conversation_messages`가 설정 가능한 히스토리를 돌려주는 페이크."""

    def __init__(self, history_messages):
        self._history_messages = history_messages
        self.saved_messages = []
        self.received_history_kwargs = None

    async def add_message(self, **kwargs):
        self.saved_messages.append(kwargs)
        return {"message_id": kwargs.get("message_id") or "generated-id", **kwargs}

    async def get_conversation(self, conversation_id):
        return {
            "conversation_id": conversation_id,
            "user_id": "user_123",
            "system_prompt": "",
            "model_name": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": None,
        }

    async def get_message(self, message_id):
        return None

    async def get_conversation_messages(self, conversation_id, limit=20):
        self.received_history_kwargs = {"conversation_id": conversation_id, "limit": limit}
        return self._history_messages


async def _noop_record_cost(**kwargs):
    return None


async def _run_pipeline_and_capture_llm_kwargs(
    history_messages, user_content, metadata=None
):
    """`pipeline.run()`을 끝까지 돌려 LLM에 실제로 전달된 kwargs를 돌려준다."""
    llm_service = _RecordingLLMService()
    chat_service = _HistoryChatService(history_messages)
    pipeline = ChatStreamPipeline(
        chat_llm_service=llm_service,
        cost_calculator=SimpleNamespace(
            record_cost_for_existing_message=_noop_record_cost
        ),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=chat_service,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content=user_content,
        attachments=[],
        parent_message_id=None,
        metadata=metadata or {},
    )

    _ = [
        chunk
        async for chunk in pipeline.run(
            "conversation_123",
            request,
            SimpleNamespace(user_id="user_123"),
            authorized_conversation={
                "conversation_id": "conversation_123",
                "user_id": "user_123",
                "model_name": "gpt-4o-mini",
            },
        )
    ]

    assert llm_service.received_kwargs is not None, "LLM stream was never invoked"
    return llm_service.received_kwargs, chat_service


async def _run_pipeline_and_capture_messages(history_messages, user_content):
    """`pipeline.run()`을 끝까지 돌려 LLM에 실제로 전달된 메시지 배열을 돌려준다."""
    kwargs, chat_service = await _run_pipeline_and_capture_llm_kwargs(
        history_messages, user_content
    )
    return kwargs["conversation_messages"], chat_service


@pytest.mark.asyncio
async def test_run_sends_history_tail_user_turn_exactly_once(monkeypatch):
    """히스토리가 이미 방금 저장한 유저 턴으로 끝나면, 수동 append가 그것을 중복시켜선 안 된다."""
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [
        {"role": "assistant", "content": "hi, how can I help?"},
        {"role": "user", "content": "what is the weather today?"},
    ]

    messages, chat_service = await _run_pipeline_and_capture_messages(
        history, "what is the weather today?"
    )

    user_turns = [m for m in messages if m.get("content") == "what is the weather today?"]
    assert len(user_turns) == 1, (
        f"expected the user turn exactly once, found {len(user_turns)} in {messages!r}"
    )
    assert messages[-1] == {"role": "user", "content": "what is the weather today?"}
    assert chat_service.received_history_kwargs["limit"] == 20


@pytest.mark.asyncio
async def test_run_keeps_user_turn_when_conversation_has_no_prior_history(monkeypatch):
    """대화의 첫 턴: 히스토리 조회가 방금 저장한 유저 턴 하나만 돌려줘도 유실되면 안 된다."""
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "first message ever"}]

    messages, _ = await _run_pipeline_and_capture_messages(history, "first message ever")

    assert messages == [{"role": "user", "content": "first message ever"}]


@pytest.mark.asyncio
async def test_run_uses_per_turn_model_override_when_valid(monkeypatch):
    """metadata.model이 카탈로그의 유효한 모델이면 LLM 호출이 그것을 받는다 (#6)."""
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "hello"}]

    kwargs, _ = await _run_pipeline_and_capture_llm_kwargs(
        history, "hello", metadata={"model": "claude-sonnet-5"}
    )

    assert kwargs["model_name"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_run_falls_back_to_conversation_model_when_no_override(monkeypatch):
    """metadata.model이 없으면 conversation.model_name을 받는다 (#6)."""
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "hello"}]

    kwargs, _ = await _run_pipeline_and_capture_llm_kwargs(history, "hello", metadata={})

    # run()이 쓰는 authorized_conversation이 고정으로 실어 오는 값
    # (get_conversation()이 아니다 — chat_stream_pipeline.py:262 참고)
    assert kwargs["model_name"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_run_rejects_unknown_per_turn_model_override(monkeypatch, caplog):
    """🔴 카탈로그에 없는 metadata.model은 무시되고 대화 모델로 떨어진다 (#6).

    이 값은 사용자가 통제하는 문자열이 모델 라우팅에 도달하는 경로다 —
    임의 문자열이 프로바이더로 새어 나가면 안 된다.
    """
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "hello"}]

    import logging

    with caplog.at_level(logging.WARNING):
        kwargs, _ = await _run_pipeline_and_capture_llm_kwargs(
            history, "hello", metadata={"model": "totally-bogus-model; DROP TABLE"}
        )

    assert kwargs["model_name"] == "gpt-4o-mini"
    assert "totally-bogus-model" in caplog.text


@pytest.mark.asyncio
async def test_run_rejects_non_selectable_catalog_model_override(monkeypatch, caplog):
    """🔴 카탈로그 *멤버*이지만 selectable: false인 모델은 여전히 거부된다 (#6 fix round 1).

    `claude-opus-4-8`은 심층분석 판정자 전용 내부 모델이다
    (`neos/config/models.yaml`: "피커에 올리지 않으므로... selectable: false").
    카탈로그에 있다는 사실만으로 통과시키면 사용자가 선택할 수 없어야 할,
    가격이 미검증인 내부 모델을 그 턴의 실제 LLM 호출로 끌어올 수 있다.
    """
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "hello"}]

    import logging

    with caplog.at_level(logging.WARNING):
        kwargs, _ = await _run_pipeline_and_capture_llm_kwargs(
            history, "hello", metadata={"model": "claude-opus-4-8"}
        )

    assert kwargs["model_name"] == "gpt-4o-mini", (
        "selectable: false 모델(claude-opus-4-8)이 그 턴의 LLM 호출에 도달했다"
    )
    assert "claude-opus-4-8" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "non_string_model",
    [["claude-sonnet-5"], {"id": "claude-sonnet-5"}],
    ids=["list", "dict"],
)
async def test_run_rejects_non_string_model_override_without_raising(
    monkeypatch, caplog, non_string_model
):
    """🔴 metadata.model이 list/dict여도 턴 전체가 죽지 않고 대화 모델로 떨어진다 (#6 fix round 1).

    `metadata`는 `Dict[str, Any]`이므로 `model` 필드가 문자열이 아닐 수 있다.
    카탈로그 조회(dict.get)에 해시 불가능한 값을 그대로 넘기면 TypeError가
    나서 파이프라인의 바깥 `except Exception`까지 번져 턴 전체가
    `response.failed`로 끝난다 — "경고 후 폴백" 계약과 다른, 더 나쁜 실패다.
    """
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    history = [{"role": "user", "content": "hello"}]

    import logging

    with caplog.at_level(logging.WARNING):
        kwargs, _ = await _run_pipeline_and_capture_llm_kwargs(
            history, "hello", metadata={"model": non_string_model}
        )

    assert kwargs["model_name"] == "gpt-4o-mini"


class _FakeChatService:
    messages = []
    parent_messages = {}
    conversations = {}

    @classmethod
    async def add_message(cls, **kwargs):
        cls.messages.append(kwargs)

    @classmethod
    async def get_conversation(cls, conversation_id):
        if conversation_id in cls.conversations:
            return cls.conversations[conversation_id]
        return {
            "conversation_id": conversation_id,
            "user_id": "user_123",
            "system_prompt": "",
            "model_name": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": None,
        }

    @classmethod
    async def get_message(cls, message_id):
        return cls.parent_messages.get(message_id)

    @classmethod
    async def get_conversation_messages(cls, conversation_id, limit=20):
        return []


@pytest.mark.asyncio
async def test_chat_pipeline_rejects_conversation_owner_mismatch():
    _FakeChatService.messages = []
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=_FakeChatService,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="secret",
        attachments=[],
        parent_message_id=None,
        metadata={},
    )

    chunks = [
        chunk
        async for chunk in pipeline.run(
            "conversation_123",
            request,
            SimpleNamespace(user_id="attacker"),
            authorized_conversation={
                "conversation_id": "conversation_123",
                "user_id": "owner",
            },
        )
    ]

    assert _FakeChatService.messages == []
    assert any("response.failed" in chunk for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parent_message_id", "parent_message", "parent_conversation"),
    [
        ("missing-m", None, None),
        (
            "victim-m",
            {"message_id": "victim-m", "conversation_id": "victim-c"},
            {"conversation_id": "victim-c", "user_id": "victim"},
        ),
        (
            "other-owned-m",
            {"message_id": "other-owned-m", "conversation_id": "other-owned-c"},
            {"conversation_id": "other-owned-c", "user_id": "user_123"},
        ),
    ],
    ids=["missing", "cross-owner", "same-owner-cross-conversation"],
)
async def test_chat_pipeline_rejects_invalid_parent_before_write(
    parent_message_id,
    parent_message,
    parent_conversation,
):
    _FakeChatService.messages = []
    _FakeChatService.parent_messages = (
        {parent_message_id: parent_message} if parent_message else {}
    )
    _FakeChatService.conversations = (
        {parent_conversation["conversation_id"]: parent_conversation}
        if parent_conversation
        else {}
    )
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=_FakeChatService,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="secret",
        attachments=[],
        parent_message_id=parent_message_id,
        metadata={},
    )

    chunks = [
        chunk
        async for chunk in pipeline.run(
            "conversation_123",
            request,
            SimpleNamespace(user_id="user_123"),
            authorized_conversation={
                "conversation_id": "conversation_123",
                "user_id": "user_123",
            },
        )
    ]

    payloads = [
        json.loads(line.removeprefix("data: "))
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: {")
    ]
    payload = payloads[0]
    assert payload["type"] == "response.failed"
    assert payload["response"]["error"] == {
        "type": "not_found",
        "message": "Resource not found",
        "code": None,
        "param": None,
    }
    assert chunks[-1] == "data: [DONE]\n\n"
    assert _FakeChatService.messages == []


@pytest.mark.asyncio
async def test_chat_workflow_uses_checkpointer_and_streams_approval_request():
    workflow = _FakeWorkflow()
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=workflow,
        workflow_callback_cls=_FakeWorkflowCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    wf_ctx = _WorkflowCtx()

    chunks = [
        chunk
        async for chunk in pipeline._run_workflow(
            conversation_id="conversation_123",
            user_content="latest news",
            current_user=SimpleNamespace(user_id="user_123"),
            history_messages=[],
            stream_state=stream_state,
            wf_ctx=wf_ctx,
            autonomy_level=0,
        )
    ]

    payloads = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line.removeprefix("data: ").strip()))

    assert workflow.use_checkpointer is True
    assert payloads[0]["type"] == "neos:approval_request"
    assert payloads[0]["pending_approvals"][0]["request_id"] == "approval-1"
    assert wf_ctx.result["interrupted"] is True


@pytest.mark.asyncio
async def test_chat_workflow_passes_mission_preferences():
    workflow = _FakeWorkflow()
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=object(),
        multi_agent_workflow=workflow,
        workflow_callback_cls=_FakeWorkflowCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    stream_state, _ = create_stream_generator(
        response_id="conversation_123",
        message_id="message_123",
    )
    wf_ctx = _WorkflowCtx()

    [
        chunk
        async for chunk in pipeline._run_workflow(
            conversation_id="conversation_123",
            user_content="compare products",
            current_user=SimpleNamespace(user_id="user_123"),
            history_messages=[],
            stream_state=stream_state,
            wf_ctx=wf_ctx,
            autonomy_level=1,
            workflow_preferences={
                "autonomy_level": 1,
                "use_mission_runtime": True,
            },
        )
    ]

    assert workflow.user_input["preferences"]["use_mission_runtime"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parent_message_id",
    [None, "parent_123"],
    ids=["no-parent", "same-conversation-parent"],
)
async def test_chat_interrupted_workflow_persists_approval_placeholder(
    monkeypatch,
    parent_message_id,
):
    _FakeChatService.messages = []
    _FakeChatService.parent_messages = (
        {
            "parent_123": {
                "message_id": "parent_123",
                "conversation_id": "conversation_123",
            }
        }
        if parent_message_id
        else {}
    )
    _FakeChatService.conversations = {}
    workflow = _FakeWorkflow()
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=_FakeChatService,
        multi_agent_workflow=workflow,
        workflow_callback_cls=_FakeWorkflowCallback,
        map_node_to_agent_fn=lambda node: node,
    )
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        True,
    )

    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="latest news",
        attachments=[],
        parent_message_id=parent_message_id,
        metadata={"autonomy_level": 0},
    )

    chunks = [
        chunk
        async for chunk in pipeline.run(
            conversation_id="conversation_123",
            request=request,
            current_user=SimpleNamespace(user_id="user_123"),
            authorized_conversation={
                "conversation_id": "conversation_123",
                "user_id": "user_123",
                "system_prompt": "",
                "model_name": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": None,
            },
        )
    ]

    assistant_messages = [
        message for message in _FakeChatService.messages
        if message["role"] == "assistant"
    ]
    assert assistant_messages
    assert assistant_messages[0]["content"] == ""
    assert assistant_messages[0]["metadata"]["responseStatus"] == "incomplete"
    assert assistant_messages[0]["metadata"]["approval_requests"][0]["request_id"] == "approval-1"
    assert _FakeChatService.messages[0]["parent_message_id"] == parent_message_id
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_run_workflow_forwards_graph_subagent_progress_without_the_report():
    """트랙 I: 설계 그래프 서브에이전트의 걸음·폴드가 챗 SSE 에 닿는다.

    본문은 싣지 않고(미검증), 노드별 마지막 상태는 새로고침을 위해 남긴다.
    """
    def _event(kind, **payload):
        return SimpleNamespace(
            event="graph_subagent",
            data={"kind": kind, "node": "explore_web", "label": "Investigating", **payload},
            node_name="explore_web",
            progress_percent=0,
            content=None,
        )

    pipeline, stream_state = _run_scripted_workflow(
        [
            _event("graph_subagent_step", steps=1, max_advances=9, step_kind="continuing"),
            _event(
                "graph_subagent_folded",
                steps=2,
                status="completed",
                exit_reason="completed",
                summary="REPORT BODY",
            ),
        ]
    )
    wf_ctx = _WorkflowCtx()
    payloads = []
    async for chunk in pipeline._run_workflow(
        conversation_id="conversation_123",
        user_content="analyse this",
        current_user=SimpleNamespace(user_id="user_123"),
        history_messages=[],
        stream_state=stream_state,
        wf_ctx=wf_ctx,
        autonomy_level=1,
    ):
        for line in chunk.splitlines():
            if line.startswith("data: {"):
                payloads.append(json.loads(line.removeprefix("data: ").strip()))

    sub = [p for p in payloads if p["type"] == "neos:graph_subagent"]
    assert [p["phase"] for p in sub] == ["step", "folded"]
    assert "REPORT BODY" not in json.dumps(payloads)
    assert wf_ctx.graph_subagents["explore_web"]["phase"] == "folded"
    assert wf_ctx.graph_subagents["explore_web"]["status"] == "completed"
