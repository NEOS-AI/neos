"""리포트 영속화 계층 고정 (D23).

리포트가 job_completed 이벤트 페이로드로만 나가면, 프론트가 그 순간
연결돼 있지 않은 run은 대화에 아무것도 남기지 않는다. 영속화는 ChatService를
아는 계층 -- 실행자 계층 -- 이 맡고, Celery/inline 두 실행자가 공유하는
`_execute`에 걸려야 한다.
"""

import pytest

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_execute_persists_report_to_assistant_message(monkeypatch):
    from neos.tasks import deep_analysis_job_task as task_mod

    async def fake_execute_run(session_factory, run_id, question, profile, **kw):
        return {"report_markdown": "# 리포트\n본문", "run_id": run_id}

    persisted = []

    async def fake_persist(run_id, report_markdown):
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

    async def fake_persist(run_id, report_markdown):
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
