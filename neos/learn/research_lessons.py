"""Stage successful research procedures. Opt-in; staged even when enabled."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from neos.config.settings import settings
from neos.learn.extract import extract_research_procedure
from neos.learn.lessons import Lesson, get_lesson_store, resolve_lesson_session_factory
from neos.learn.policy import is_executable_lesson_source
from neos.learn.postgres import PostgresLessonStore


async def _persist_lesson(lesson: Lesson) -> Lesson:
    factory = resolve_lesson_session_factory()
    if factory is not None:
        return await PostgresLessonStore(factory).add(lesson)
    return get_lesson_store().add(lesson)


def _document_pipeline(pipeline: str) -> str:
    name = str(pipeline or "").strip() or "research"
    if is_executable_lesson_source(name) or name.lower().endswith(".py"):
        return "research"
    return name


def _document_steps(steps: Sequence[object]) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for step in steps:
        text = str(step).strip()
        if not text or is_executable_lesson_source(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return tuple(cleaned)


def procedure_from_run(
    final_state: Mapping[str, object] | None = None,
    result: Mapping[str, object] | None = None,
) -> tuple[str, tuple[str, ...]] | None:
    state = final_state or {}
    payload = result or {}
    pipeline = (
        str(state.get("template_id") or payload.get("template_id") or "").strip()
        or str(state.get("query_intent") or payload.get("intent") or "").strip()
        or "research"
    )
    raw_steps: list[object] = []
    plan = state.get("research_plan") or ()
    if isinstance(plan, Sequence) and not isinstance(plan, (str, bytes)):
        for item in plan:
            if isinstance(item, str):
                raw_steps.append(item)
            elif isinstance(item, Mapping):
                for key in ("description", "step", "title", "action", "task"):
                    value = item.get(key)
                    if value:
                        raw_steps.append(value)
                        break
    for key in ("required_agents", "selected_skills"):
        values = state.get(key) or ()
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            raw_steps.extend(values)
    execution = state.get("execution_steps") or ()
    if isinstance(execution, Sequence) and not isinstance(execution, (str, bytes)):
        for item in execution:
            if isinstance(item, Mapping):
                name = item.get("step") or item.get("node") or item.get("name")
                if name:
                    raw_steps.append(name)
            elif item:
                raw_steps.append(item)
    steps = _document_steps(raw_steps)
    if not steps:
        return None
    return _document_pipeline(pipeline), steps


async def stage_research_procedure(
    *,
    owner_id: str | None,
    pipeline: str,
    steps: Sequence[str],
) -> Lesson | None:
    if not settings.config.learn.research_procedures:
        return None
    owner = (owner_id or "").strip()
    if not owner:
        return None
    cleaned = _document_steps(steps)
    if not cleaned:
        return None
    lesson = extract_research_procedure(
        owner_id=owner,
        pipeline=_document_pipeline(pipeline),
        steps=cleaned,
    )
    if is_executable_lesson_source(lesson.body):
        return None
    return await _persist_lesson(lesson)


async def stage_research_procedure_from_run(
    *,
    user_input: Mapping[str, object],
    result: Mapping[str, object],
    final_state: Mapping[str, object],
) -> Lesson | None:
    if not result.get("success"):
        return None
    from neos.learn.session_search import is_hidden_session_row

    if is_hidden_session_row(dict(user_input)):
        return None
    derived = procedure_from_run(final_state, result)
    if derived is None:
        return None
    pipeline, steps = derived
    return await stage_research_procedure(
        owner_id=str(user_input.get("user_id") or ""),
        pipeline=pipeline,
        steps=steps,
    )
