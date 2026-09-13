"""리포트 영속화 계층 고정 (D23).

리포트가 job_completed 이벤트 페이로드로만 나가면, 프론트가 그 순간
연결돼 있지 않은 run은 대화에 아무것도 남기지 않는다. 영속화는 ChatService를
아는 계층 -- 실행자 계층 -- 이 맡고, Celery/inline 두 실행자가 공유하는
`_execute`에 걸려야 한다.
"""

import asyncio
import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.no_db


class FakeSessionContext:
    def __init__(self, session=None, enter_error=None):
        self.session = session
        self.enter_error = enter_error

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _install_persistence_dependencies(
    monkeypatch,
    *,
    session_context,
    upsert_message,
):
    # `_persist_assistant_message` 의 except 가 jobs 를 늦게 임포트한다.
    # 스텁을 먼저 끼우면 jobs → ledger 가 DABlob 을 못 찾는다.
    import neos.workflow.deep_analysis.jobs  # noqa: F401

    connection_module = ModuleType("neos.database.connection")
    connection_module.get_session_ctx = lambda: session_context
    models_module = ModuleType("neos.database.deep_analysis_models")
    models_module.DARun = type("DARun", (), {})
    chat_module = ModuleType("neos.api.services.chat_service")
    chat_module.ChatService = SimpleNamespace(upsert_message=upsert_message)
    monkeypatch.setitem(
        sys.modules,
        "neos.database.connection",
        connection_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "neos.database.deep_analysis_models",
        models_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "neos.api.services.chat_service",
        chat_module,
    )


@pytest.mark.asyncio
async def test_lookup_failure_is_swallowed_and_logged_without_payload(
    monkeypatch,
    caplog,
):
    from neos.tasks import deep_analysis_job_task as task_mod

    session = SimpleNamespace(
        get=AsyncMock(side_effect=RuntimeError("secret db url"))
    )
    upsert_message = AsyncMock()
    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(session),
        upsert_message=upsert_message,
    )

    with caplog.at_level(logging.WARNING):
        await task_mod._persist_assistant_message("run1", "secret report")

    assert "run=run1" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "secret db url" not in caplog.text
    assert "secret report" not in caplog.text
    upsert_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_entry_failure_is_swallowed(monkeypatch, caplog):
    from neos.tasks import deep_analysis_job_task as task_mod

    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(
            enter_error=ConnectionError("secret connection")
        ),
        upsert_message=AsyncMock(),
    )

    with caplog.at_level(logging.WARNING):
        await task_mod._persist_assistant_message("run2", "report")

    assert "run=run2" in caplog.text
    assert "error_type=ConnectionError" in caplog.text
    assert "secret connection" not in caplog.text


@pytest.mark.asyncio
async def test_message_failure_is_swallowed_with_bounded_log(
    monkeypatch,
    caplog,
):
    from neos.tasks import deep_analysis_job_task as task_mod

    run = SimpleNamespace(conversation_id="c1", assistant_message_id="m1")
    session = SimpleNamespace(get=AsyncMock(return_value=run))
    upsert_message = AsyncMock(side_effect=ValueError("secret message"))
    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(session),
        upsert_message=upsert_message,
    )

    with caplog.at_level(logging.WARNING):
        await task_mod._persist_assistant_message("run3", "secret report")

    assert "run=run3" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "secret message" not in caplog.text
    assert "secret report" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage", ["lookup", "session_entry", "message"]
)
async def test_a_swallowed_failure_is_recorded_in_the_ledger(
    monkeypatch,
    failure_stage,
):
    """P1 #8: 삼킨 자리에 원장 흔적을 남긴다.

    삼키는 것 자체는 옳다 -- run 은 성공했고 리포트는 이미 `job_completed`
    페이로드에 있다. 문제는 흔적이 `logger.warning` 하나뿐이라 조회할 수
    없다는 것이었다. FE5 이후 실패한 run 도 이 경로를 타므로, 여기서 예외가
    나면 **실패 사실과 강등이 둘 다** 대화에서 사라진다.

    세 실패 지점 전부를 건다 -- 하나만 걸면 나머지 둘은 계속 침묵한다.
    """
    from neos.tasks import deep_analysis_job_task as task_mod

    # jobs 를 **먼저** 임포트한다 -- `_install_persistence_dependencies` 가
    # `neos.database.deep_analysis_models` 를 DARun 하나짜리 스텁으로 갈아
    # 끼우므로, 그 뒤에 처음 임포트하면 jobs 가 DABlob 을 못 찾는다.
    from neos.workflow.deep_analysis import jobs as jobs_mod

    run = SimpleNamespace(conversation_id="c1", assistant_message_id="m1")
    session = SimpleNamespace(get=AsyncMock(return_value=run))
    upsert_message = AsyncMock()
    session_context = FakeSessionContext(session)

    if failure_stage == "lookup":
        session.get = AsyncMock(side_effect=RuntimeError("secret db url"))
    elif failure_stage == "session_entry":
        session_context = FakeSessionContext(
            enter_error=ConnectionError("secret connection")
        )
    else:
        upsert_message = AsyncMock(side_effect=ValueError("secret message"))

    _install_persistence_dependencies(
        monkeypatch,
        session_context=session_context,
        upsert_message=upsert_message,
    )

    recorded = []

    async def fake_record(session_factory, run_id, **kwargs):
        recorded.append((run_id, kwargs))

    monkeypatch.setattr(jobs_mod, "record_message_persist_failure", fake_record)

    await task_mod._persist_assistant_message(
        "run6",
        "secret report",
        [{"kind": "report_assembly_degraded", "count": 2}],
        status="failed",
    )

    assert len(recorded) == 1
    run_id, kwargs = recorded[0]
    assert run_id == "run6"
    assert kwargs["status"] == "failed"
    assert kwargs["degradations_lost"] == 1
    assert kwargs["error_type"] in {
        "RuntimeError",
        "ConnectionError",
        "ValueError",
    }


@pytest.mark.asyncio
async def test_a_successful_persist_records_nothing(monkeypatch):
    """성공 경로는 이벤트를 남기지 않는다 -- 남기면 원장에서 실패를
    찾는 질의가 정상 run 으로 오염된다."""
    from neos.tasks import deep_analysis_job_task as task_mod
    from neos.workflow.deep_analysis import jobs as jobs_mod

    run = SimpleNamespace(conversation_id="c1", assistant_message_id="m1")
    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(
            SimpleNamespace(get=AsyncMock(return_value=run))
        ),
        upsert_message=AsyncMock(),
    )

    recorded = []

    async def fake_record(session_factory, run_id, **kwargs):
        recorded.append(run_id)

    monkeypatch.setattr(jobs_mod, "record_message_persist_failure", fake_record)

    await task_mod._persist_assistant_message("run7", "report")

    assert recorded == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["lookup", "message"])
async def test_cancellation_propagates(monkeypatch, failure_stage):
    from neos.tasks import deep_analysis_job_task as task_mod

    run = SimpleNamespace(conversation_id="c1", assistant_message_id="m1")
    lookup = AsyncMock(return_value=run)
    upsert_message = AsyncMock()
    if failure_stage == "lookup":
        lookup.side_effect = asyncio.CancelledError()
    else:
        upsert_message.side_effect = asyncio.CancelledError()
    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(SimpleNamespace(get=lookup)),
        upsert_message=upsert_message,
    )

    with pytest.raises(asyncio.CancelledError):
        await task_mod._persist_assistant_message("run4", "report")


@pytest.mark.asyncio
async def test_missing_conversation_binding_is_noop(monkeypatch):
    from neos.tasks import deep_analysis_job_task as task_mod

    run = SimpleNamespace(conversation_id=None, assistant_message_id=None)
    session = SimpleNamespace(get=AsyncMock(return_value=run))
    upsert_message = AsyncMock()
    _install_persistence_dependencies(
        monkeypatch,
        session_context=FakeSessionContext(session),
        upsert_message=upsert_message,
    )

    await task_mod._persist_assistant_message("run5", "report")

    upsert_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_persists_report_to_assistant_message(monkeypatch):
    from neos.tasks import deep_analysis_job_task as task_mod

    async def fake_execute_run(session_factory, run_id, question, profile, **kw):
        return {"report_markdown": "# 리포트\n본문", "run_id": run_id}

    persisted = []

    async def fake_persist(run_id, report_markdown, degradations=None):
        persisted.append((run_id, report_markdown))

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.execute_run", fake_execute_run
    )
    monkeypatch.setattr(task_mod, "_persist_assistant_message", fake_persist)

    result = await task_mod._execute("runPERSIST", "q", "dev", False)

    assert result["report_markdown"] == "# 리포트\n본문"
    assert persisted == [("runPERSIST", "# 리포트\n본문")]


@pytest.mark.asyncio
async def test_resume_path_also_persists_report(monkeypatch):
    """재개된 run도 리포트를 대화에 남긴다 -- 두 진입점이 같은 본문을 탄다."""
    from neos.tasks import deep_analysis_job_task as task_mod

    async def fake_resume_run(session_factory, run_id, **kw):
        return {"report_markdown": "# 재개 리포트", "run_id": run_id}

    persisted = []

    async def fake_persist(run_id, report_markdown, degradations=None):
        persisted.append((run_id, report_markdown))

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.resume_run", fake_resume_run
    )
    monkeypatch.setattr(task_mod, "_persist_assistant_message", fake_persist)

    await task_mod._execute("runRESUME", "q", "dev", True)

    assert persisted == [("runRESUME", "# 재개 리포트")]


def test_both_executors_share_the_persistence_path():
    """Celery 태스크와 inline 제출이 모두 `_execute`를 거쳐야 한다.

    한쪽만 영속화하면 운영 설정(CELERY_ENABLED)에 따라 대화에 리포트가
    남기도 하고 안 남기도 하는 유령 버그가 된다.
    """
    import inspect

    from neos.tasks import deep_analysis_job_task as task_mod

    assert "_execute(" in inspect.getsource(task_mod.run_deep_analysis_job)
    assert "_execute(" in inspect.getsource(task_mod.submit_deep_analysis_job)


def test_persistence_layer_is_not_inside_the_framework_free_package():
    """ChatService는 deep_analysis 패키지 밖에 머물러야 한다.

    원시 문자열 스캔이 아니라 AST를 본다 -- jobs.py의 docstring은 "ChatService를
    임포트하지 않는다"는 설계 근거를 **일부러 서술**하므로, 산문에 이름이
    나온다는 것과 의존한다는 것은 전혀 다른 얘기다. 고정하려는 불변식은
    의존 그래프다.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(
        Path("neos/workflow/deep_analysis/jobs.py").read_text(encoding="utf-8")
    )
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not [m for m in modules if "chat_service" in m], modules

    # 영속화는 실행자 계층이 한다 -- 거기에는 ChatService가 있어야 한다.
    task_tree = ast.parse(
        Path("neos/tasks/deep_analysis_job_task.py").read_text(encoding="utf-8")
    )
    task_modules = {
        node.module
        for node in ast.walk(task_tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any("chat_service" in m for m in task_modules), task_modules
