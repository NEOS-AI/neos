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
    """

    def __init__(self, events):
        self._events = events

    async def execute_workflow(self, user_input, event_handler, use_checkpointer):
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
