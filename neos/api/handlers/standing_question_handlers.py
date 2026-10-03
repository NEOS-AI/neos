"""상시 질문 API -- 트랙 Q3 (docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §5).

소유자가 에이전트의 상시 질문을 만들고 보고 끄고 지운다. 남의 에이전트·질문은 404 다
(존재를 확인해 주지 않는다). cron 은 UTC 이고, 가장 짧은 간격이
`standing_agents.questions.min_interval_minutes` 이상이어야 한다(SQ9).

`standing_agents.enabled` 와 `standing_agents.questions.enabled` 가 둘 다 켜져야
`main.py` 가 마운트한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.database.connection import db_manager
from neos.database.models import User
from neos.standing.questions import (
    PostgresQuestionStore,
    QuestionRefused,
    QuestionRun,
    QuestionStore,
    StandingQuestion,
    next_run,
    validate_cron,
)

router = APIRouter(prefix="/standing-agents", tags=["Standing Agent Questions"])


def get_question_store() -> QuestionStore:
    return PostgresQuestionStore(db_manager.get_session)


def get_question_settings() -> tuple[int, int]:
    """(에이전트당 상한, 최소 간격 분)."""
    from neos.config.settings import settings

    questions = settings.config.standing_agents.questions
    return questions.max_per_agent, questions.min_interval_minutes


def get_clock() -> Callable[[], datetime]:
    return lambda: datetime.now(UTC)


class CreateQuestionIn(BaseModel):
    question: str
    cron_expression: str


class UpdateQuestionIn(BaseModel):
    enabled: bool


class QuestionOut(BaseModel):
    question_id: str
    agent_id: str
    question: str
    cron_expression: str
    enabled: bool
    next_run_at: datetime
    created_at: datetime
    last_skip_reason: str | None = None


class QuestionRunOut(BaseModel):
    da_run_id: str
    status: str
    created_at: datetime
    settled_at: datetime | None = None
    notified: bool
    diff: dict[str, Any] | None = None


def _out(question: StandingQuestion) -> dict[str, Any]:
    return {
        "question_id": question.question_id,
        "agent_id": question.agent_id,
        "question": question.question,
        "cron_expression": question.cron_expression,
        "enabled": question.enabled,
        "next_run_at": question.next_run_at,
        "created_at": question.created_at,
        "last_skip_reason": question.last_skip_reason,
    }


def _run_out(run: QuestionRun) -> dict[str, Any]:
    return {
        "da_run_id": run.da_run_id,
        "status": run.status,
        "created_at": run.created_at,
        "settled_at": run.settled_at,
        "notified": run.notified,
        "diff": run.diff,
    }


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


async def _owned(store: QuestionStore, owner_id: str, agent_id: str, question_id: str):
    question = await store.get(owner_id, question_id)
    if question is None or question.agent_id != agent_id:
        raise _not_found()
    return question


@router.post(
    "/{agent_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED
)
async def create_standing_question(
    agent_id: str,
    body: CreateQuestionIn,
    current_user: User = Depends(get_current_user),
    store: QuestionStore = Depends(get_question_store),
    limits: tuple[int, int] = Depends(get_question_settings),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    max_per_agent, min_interval = limits
    question = body.question.strip()
    cron_expression = body.cron_expression.strip()
    now = clock()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_question")
    try:
        validate_cron(cron_expression, min_interval_minutes=min_interval, now=now)
        created = await store.create(
            current_user.user_id,
            agent_id,
            question=question,
            cron_expression=cron_expression,
            next_run_at=next_run(cron_expression, now),
            max_per_agent=max_per_agent,
            now=now,
        )
    except QuestionRefused as refused:
        code = (
            status.HTTP_409_CONFLICT
            if refused.reason == "too_many_questions"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(code, detail=refused.reason) from refused
    if created is None:
        raise _not_found()
    return _out(created)


@router.get("/{agent_id}/questions", response_model=list[QuestionOut])
async def list_standing_questions(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    store: QuestionStore = Depends(get_question_store),
):
    return [_out(q) for q in await store.list_for_agent(current_user.user_id, agent_id)]


@router.patch("/{agent_id}/questions/{question_id}", response_model=QuestionOut)
async def update_standing_question(
    agent_id: str,
    question_id: str,
    body: UpdateQuestionIn,
    current_user: User = Depends(get_current_user),
    store: QuestionStore = Depends(get_question_store),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    await _owned(store, current_user.user_id, agent_id, question_id)
    updated = await store.set_enabled(
        current_user.user_id, question_id, body.enabled, now=clock()
    )
    if updated is None:
        raise _not_found()
    return _out(updated)


@router.delete(
    "/{agent_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_standing_question(
    agent_id: str,
    question_id: str,
    current_user: User = Depends(get_current_user),
    store: QuestionStore = Depends(get_question_store),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    await _owned(store, current_user.user_id, agent_id, question_id)
    if not await store.delete(current_user.user_id, question_id, now=clock()):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{agent_id}/questions/{question_id}/runs", response_model=list[QuestionRunOut]
)
async def list_standing_question_runs(
    agent_id: str,
    question_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    store: QuestionStore = Depends(get_question_store),
):
    await _owned(store, current_user.user_id, agent_id, question_id)
    return [_run_out(r) for r in await store.runs(current_user.user_id, question_id, limit=limit)]
