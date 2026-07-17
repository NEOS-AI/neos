import pytest
from pathlib import Path
from pydantic import ValidationError
from types import SimpleNamespace

from neos.api.handlers.deep_analysis_handlers import (
    ensure_owned_conversation,
)
from neos.api.models.deep_analysis_models import DeepAnalysisRequest


pytestmark = pytest.mark.no_db


def test_deep_analysis_request_rejects_blank_question():
    with pytest.raises(ValidationError):
        DeepAnalysisRequest(question="   ")


@pytest.mark.asyncio
async def test_optional_conversation_must_belong_to_authenticated_user():
    class Chat:
        @staticmethod
        async def get_conversation(conversation_id):
            return {
                "conversation_id": conversation_id,
                "user_id": "owner",
            }

    assert await ensure_owned_conversation(None, "owner", Chat) is None
    owned = await ensure_owned_conversation("conversation", "owner", Chat)
    assert owned["conversation_id"] == "conversation"

    with pytest.raises(Exception) as captured:
        await ensure_owned_conversation("conversation", "intruder", Chat)
    assert getattr(captured.value, "status_code", None) == 404


def test_deep_analysis_route_registered():
    from neos.api.deep_analysis_routes import router

    assert "/deep-analysis" in {route.path for route in router.routes}
    main_source = Path("neos/main.py").read_text(encoding="utf-8")
    assert "_include_router_for_runtime(deep_analysis_router" in main_source


@pytest.mark.asyncio
async def test_sse_run_links_user_and_report_messages(monkeypatch):
    from neos.api.handlers import deep_analysis_handlers as handlers

    messages = []

    async def get_conversation(conversation_id):
        return {
            "conversation_id": conversation_id,
            "user_id": "owner",
        }

    async def add_message(**kwargs):
        messages.append(kwargs)
        return kwargs

    monkeypatch.setattr(
        handlers.ChatService,
        "get_conversation",
        get_conversation,
    )
    monkeypatch.setattr(
        handlers.ChatService,
        "add_message",
        add_message,
    )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_create_run(*args, **kwargs):
        return "run00001"

    monkeypatch.setattr(handlers, "create_run", fake_create_run)

    async def fake_build(*args, **kwargs):
        sink = kwargs["event_sink"]

        class Orchestrator:
            async def run(self, question):
                sink("pass_completed", {"qid": "q1"})
                return {
                    "run_id": "run00001",
                    "report_markdown": "## 요약\nReport",
                }

        return Orchestrator()

    monkeypatch.setattr(handlers, "build_orchestrator", fake_build)

    response = await handlers.start_deep_analysis(
        DeepAnalysisRequest(
            question="Question",
            conversation_id="conversation",
        ),
        SimpleNamespace(user_id="owner"),
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(
            chunk.decode() if isinstance(chunk, bytes) else chunk
        )
    stream = "".join(chunks)

    assert '"type": "started"' in stream
    assert '"type": "pass_completed"' in stream
    assert '"type": "completed"' in stream
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
    ]
    assert messages[-1]["content"] == "## 요약\nReport"
