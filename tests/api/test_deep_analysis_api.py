import pytest
from pathlib import Path
from pydantic import ValidationError
from types import SimpleNamespace

from neos.api.handlers.deep_analysis_handlers import (
    ensure_owned_conversation,
)
from neos.api.models.deep_analysis_models import DeepAnalysisRequest


pytestmark = pytest.mark.no_db


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def commit(self):
        return None


class Request:
    async def is_disconnected(self):
        return False


def _patch_session(monkeypatch, handlers):
    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)


async def _drain(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


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
async def test_post_returns_202_with_run_id_without_blocking(monkeypatch):
    """AC1: 제출은 즉시 반환한다 -- 오케스트레이터를 기다리지 않는다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    messages = []

    async def get_conversation(conversation_id):
        return {"conversation_id": conversation_id, "user_id": "owner"}

    async def add_message(**kwargs):
        messages.append(kwargs)
        return kwargs

    monkeypatch.setattr(handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(handlers.ChatService, "add_message", add_message)
    _patch_session(monkeypatch, handlers)

    async def fake_create_run(*args, **kwargs):
        return "run00001"

    monkeypatch.setattr(handlers, "create_run", fake_create_run)

    submitted = {}

    def fake_submit(run_id, question="", profile="dev", *, resume=False):
        submitted.update(
            run_id=run_id, question=question, profile=profile, resume=resume
        )
        return "inline"

    monkeypatch.setattr(handlers, "submit_deep_analysis_job", fake_submit)

    response = await handlers.start_deep_analysis(
        DeepAnalysisRequest(question="Question", conversation_id="conversation"),
        SimpleNamespace(user_id="owner"),
    )

    assert response.run_id == "run00001"
    assert response.status == "accepted"
    assert response.executor == "inline"
    assert response.events_url == "/api/v1/deep-analysis/run00001/events"
    assert submitted == {
        "run_id": "run00001",
        "question": "Question",
        "profile": "dev",
        "resume": False,
    }
    # 사용자 메시지는 제출 시점에 저장된다. assistant 메시지는 job이 쓴다.
    assert [message["role"] for message in messages] == ["user"]


def test_post_is_declared_202():
    from neos.api.deep_analysis_routes import router

    route = next(
        r
        for r in router.routes
        if r.path == "/deep-analysis" and "POST" in r.methods
    )
    assert route.status_code == 202


def test_job_routes_registered():
    from neos.api.deep_analysis_routes import router

    paths = {route.path for route in router.routes}
    assert "/deep-analysis" in paths
    assert "/deep-analysis/{run_id}/events" in paths
    assert "/deep-analysis/{run_id}/resume" in paths


@pytest.mark.asyncio
async def test_events_stream_replays_full_history_for_a_late_subscriber(
    monkeypatch,
):
    """AC6: 커서를 0에서 시작하면 진행 중인 run의 전체 이력이 재생된다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    _patch_session(monkeypatch, handlers)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    history = [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {}},
        {"seq": 2, "type": "question_opened", "qid": "q1", "payload": {"depth": 0}},
        {"seq": 3, "type": "pass_completed", "qid": "q1", "payload": {"verified": 1}},
        {
            "seq": 4,
            "type": "job_completed",
            "qid": None,
            "payload": {"report_markdown": "## 요약"},
        },
    ]

    async def fake_read(session, run_id, after_seq=0, limit=200):
        return [event for event in history if event["seq"] > after_seq]

    monkeypatch.setattr(handlers, "read_events_after", fake_read)

    response = await handlers.stream_deep_analysis_events(
        "run00001",
        Request(),
        0,
        SimpleNamespace(user_id="owner"),
    )
    stream = await _drain(response)

    assert '"type": "job_started"' in stream
    assert '"type": "question_opened"' in stream
    assert '"type": "pass_completed"' in stream
    assert '"type": "job_completed"' in stream
    # 종료 이벤트에서 스트림이 닫힌다.
    assert stream.count('"type": "job_completed"') == 1


@pytest.mark.asyncio
async def test_events_stream_honours_the_after_cursor(monkeypatch):
    """재접속 클라이언트는 마지막 seq를 넘겨 이어받는다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    _patch_session(monkeypatch, handlers)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    history = [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {}},
        {"seq": 2, "type": "job_failed", "qid": None, "payload": {"error": "boom"}},
    ]

    async def fake_read(session, run_id, after_seq=0, limit=200):
        return [event for event in history if event["seq"] > after_seq]

    monkeypatch.setattr(handlers, "read_events_after", fake_read)

    response = await handlers.stream_deep_analysis_events(
        "run00001",
        Request(),
        1,
        SimpleNamespace(user_id="owner"),
    )
    stream = await _drain(response)

    assert '"type": "job_started"' not in stream
    assert '"type": "job_failed"' in stream


@pytest.mark.asyncio
async def test_events_stream_hides_other_users_runs(monkeypatch):
    from neos.api.handlers import deep_analysis_handlers as handlers

    _patch_session(monkeypatch, handlers)

    async def fake_owner(session, run_id):
        return ("someone-else", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    with pytest.raises(Exception) as captured:
        await handlers.stream_deep_analysis_events(
            "run00001", Request(), 0, SimpleNamespace(user_id="owner")
        )
    assert getattr(captured.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_resume_dispatches_the_job_for_a_running_run(monkeypatch):
    """AC5의 API 표면."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    _patch_session(monkeypatch, handlers)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    submitted = {}

    def fake_submit(run_id, question="", profile="dev", *, resume=False):
        submitted.update(run_id=run_id, resume=resume)
        return "celery"

    monkeypatch.setattr(handlers, "submit_deep_analysis_job", fake_submit)

    response = await handlers.resume_deep_analysis(
        "run00001", SimpleNamespace(user_id="owner")
    )

    assert response.run_id == "run00001"
    assert response.status == "accepted"
    assert response.executor == "celery"
    assert submitted == {"run_id": "run00001", "resume": True}


@pytest.mark.asyncio
async def test_resume_refuses_a_completed_run(monkeypatch):
    from neos.api.handlers import deep_analysis_handlers as handlers

    _patch_session(monkeypatch, handlers)

    async def fake_owner(session, run_id):
        return ("owner", "completed")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    with pytest.raises(Exception) as captured:
        await handlers.resume_deep_analysis(
            "run00001", SimpleNamespace(user_id="owner")
        )
    assert getattr(captured.value, "status_code", None) == 409
