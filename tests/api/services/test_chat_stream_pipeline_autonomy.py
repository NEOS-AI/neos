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


class _FakeChatService:
    messages = []

    @classmethod
    async def add_message(cls, **kwargs):
        cls.messages.append(kwargs)

    @classmethod
    async def get_conversation(cls, conversation_id):
        return {
            "conversation_id": conversation_id,
            "system_prompt": "",
            "model_name": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": None,
        }

    @classmethod
    async def get_conversation_messages(cls, conversation_id, limit=20):
        return []


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
async def test_chat_interrupted_workflow_persists_approval_placeholder(monkeypatch):
    _FakeChatService.messages = []
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
        parent_message_id=None,
        metadata={"autonomy_level": 0},
    )

    chunks = [
        chunk
        async for chunk in pipeline.run(
            conversation_id="conversation_123",
            request=request,
            current_user=SimpleNamespace(user_id="user_123"),
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
    assert chunks[-1] == "data: [DONE]\n\n"
