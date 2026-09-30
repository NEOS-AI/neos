"""Gate long-term memory writes behind write_approval. Fail-closed."""

from __future__ import annotations

from typing import Any

from neos.learn.lessons import (
    Lesson,
    force_stage_on_write,
    get_lesson_store,
    new_lesson,
    resolve_lesson_session_factory,
)
from neos.learn.policy import clip_knowledge, namespace, write_approval_required
from neos.learn.postgres import PostgresLessonStore


def _lesson_title(key: str, knowledge: object) -> str:
    label = str(key or "").strip()
    if label:
        return label[:60]
    body = str(knowledge or "").strip()
    if body:
        return body.split("\n", 1)[0][:60]
    return "ltm"


async def _persist_staged_lesson(lesson: Lesson) -> Lesson:
    factory = resolve_lesson_session_factory()
    if factory is not None:
        return await PostgresLessonStore(factory).add(lesson)
    return get_lesson_store().add(lesson)


async def stage_memo(*, namespace: str, title: str, body: str, kind: str) -> Lesson:
    """STAGED 로**만** 쓴다 -- `write_approval` 설정과 무관하다(트랙 Q13e).

    `maybe_learn_ltm` 은 `write_approval` 이 꺼져 있으면 장기 메모리에 바로 쓴다.
    아무도 시키지 않은 쪽(상시 에이전트)의 메모는 그 스위치를 따르지 않는다(D19).
    """
    return await _persist_staged_lesson(
        new_lesson(namespace=namespace, title=title, body=body, kind=kind)
    )


async def maybe_learn_ltm(
    user_id: str,
    key: str,
    knowledge: object,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Stage a fact lesson when write_approval is on; otherwise learn into LTM.

    Store or learn failures propagate. Never fall through to learn() after a
    staging error.
    """
    from neos.learn.session_search import is_hidden_session_row

    payload = dict(metadata or {})
    if "session_id" not in payload and key.startswith("episode:"):
        payload["session_id"] = key.split(":", 1)[1]
    if is_hidden_session_row(payload) or str(key).startswith("episode:scheduled_"):
        return "skipped"
    if write_approval_required():
        lesson = force_stage_on_write(
            new_lesson(
                namespace=namespace(user_id),
                title=_lesson_title(key, knowledge),
                body=clip_knowledge(str(knowledge or "")),
                kind="fact",
            )
        )
        await _persist_staged_lesson(lesson)
        return "staged"

    from neos.memory.manager import memory_manager

    await memory_manager.learn(
        user_id,
        key=key,
        knowledge=knowledge,
        metadata=metadata,
    )
    return "learned"
