from pathlib import Path

import pytest

from neos.learn.lessons import LessonStatus, approved_texts, reset_lesson_store
from neos.learn.research_lessons import (
    stage_research_procedure,
    stage_research_procedure_from_run,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_stage_research_procedure_is_noop_when_disabled() -> None:
    store = reset_lesson_store()
    lesson = await stage_research_procedure(
        owner_id="u1",
        pipeline="pdf-html-gate",
        steps=("fetch pdf", "html gate", "cite"),
    )
    assert lesson is None
    assert store.list() == ()


@pytest.mark.asyncio
async def test_stage_research_procedure_writes_staged_document(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "research_procedures", True)
    store = reset_lesson_store()
    lesson = await stage_research_procedure(
        owner_id="u1",
        pipeline="pdf-html-gate",
        steps=("fetch pdf", "html gate", "cite", "emit skill.py"),
    )
    assert lesson is not None
    assert lesson.status is LessonStatus.STAGED
    assert lesson.kind == "procedure"
    assert lesson.title == "pdf-html-gate"
    assert "skill.py" not in lesson.body
    assert approved_texts(store, "owner:u1") == ()


@pytest.mark.asyncio
async def test_from_run_success_is_noop_when_flag_off() -> None:
    store = reset_lesson_store()
    lesson = await stage_research_procedure_from_run(
        user_input={"user_id": "u1"},
        result={"success": True, "template_id": "pdf-html-gate"},
        final_state={
            "template_id": "pdf-html-gate",
            "required_agents": ["knowledge_search"],
            "execution_steps": [{"step": "result_integration"}],
        },
    )
    assert lesson is None
    assert store.list() == ()


@pytest.mark.asyncio
async def test_from_run_success_stages_procedure_when_enabled(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "research_procedures", True)
    store = reset_lesson_store()
    lesson = await stage_research_procedure_from_run(
        user_input={"user_id": "u1"},
        result={"success": True, "template_id": "pdf-html-gate"},
        final_state={
            "template_id": "pdf-html-gate",
            "required_agents": ["knowledge_search"],
            "execution_steps": [{"step": "html gate"}, {"step": "cite"}],
            "research_plan": [{"description": "fetch pdf"}],
        },
    )
    assert lesson is not None
    assert lesson.status is LessonStatus.STAGED
    assert lesson.kind == "procedure"
    assert lesson.title == "pdf-html-gate"
    assert "skill.py" not in lesson.body
    assert approved_texts(store, "owner:u1") == ()


@pytest.mark.asyncio
async def test_from_run_failure_does_not_write(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "research_procedures", True)
    store = reset_lesson_store()
    lesson = await stage_research_procedure_from_run(
        user_input={"user_id": "u1"},
        result={"success": False},
        final_state={
            "template_id": "pdf-html-gate",
            "execution_steps": [{"step": "fetch pdf"}],
        },
    )
    assert lesson is None
    assert store.list() == ()


def test_research_procedures_default_off() -> None:
    from neos.config.schema import AppConfig

    config = AppConfig()
    assert config.learn.research_procedures is False
    assert config.learn.write_approval is True


def test_workflow_success_hook_calls_research_stager() -> None:
    source = (REPO_ROOT / "neos" / "workflow" / "graph.py").read_text(
        encoding="utf-8"
    )
    assert "stage_research_procedure_from_run" in source
    assert "skill.py" not in source


@pytest.mark.asyncio
async def test_from_run_skips_scheduler_origin(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "research_procedures", True)
    store = reset_lesson_store()
    lesson = await stage_research_procedure_from_run(
        user_input={
            "user_id": "u1",
            "channel_source": "scheduler",
            "origin": "scheduler",
        },
        result={"success": True, "template_id": "pdf-html-gate"},
        final_state={
            "template_id": "pdf-html-gate",
            "required_agents": ["knowledge_search"],
            "execution_steps": [{"step": "html gate"}],
        },
    )
    assert lesson is None
    assert store.list() == ()
