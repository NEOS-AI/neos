"""Authenticated SSE API for loop-based deep analysis runs."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from neos.api.dependencies.auth import get_current_active_user
from neos.api.models.deep_analysis_models import DeepAnalysisRequest
from neos.api.services.chat_service import ChatService
from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.database.models import User
from neos.utils.logger import get_logger
from neos.workflow.deep_analysis.ledger import create_run
from neos.workflow.deep_analysis.service import build_orchestrator


logger = get_logger(__name__)
router = APIRouter()


async def ensure_owned_conversation(
    conversation_id: str | None,
    user_id: str,
    chat_service=ChatService,
):
    if conversation_id is None:
        return None
    conversation = await chat_service.get_conversation(conversation_id)
    if (
        conversation is None
        or conversation.get("user_id") != user_id
    ):
        raise HTTPException(status_code=404, detail="Resource not found")
    return conversation


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/deep-analysis")
async def start_deep_analysis(
    request: DeepAnalysisRequest,
    current_user: User = Depends(get_current_active_user),
):
    conversation = await ensure_owned_conversation(
        request.conversation_id,
        current_user.user_id,
    )
    assistant_message_id = (
        str(uuid.uuid4()) if conversation is not None else None
    )

    if conversation is not None:
        await ChatService.add_message(
            conversation_id=request.conversation_id,
            role="user",
            content=request.question,
            metadata={"deep_analysis_initiated": True},
        )

    async def generate():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        def event_sink(kind: str, payload: dict) -> None:
            queue.put_nowait({"type": kind, **payload})

        task = None
        run_id = None
        try:
            async with await db_manager.get_session() as session:
                run_id = await create_run(
                    session,
                    request.question,
                    request.profile,
                    user_id=current_user.user_id,
                    conversation_id=request.conversation_id,
                    assistant_message_id=assistant_message_id,
                )
                await session.commit()
                yield _sse({"type": "started", "run_id": run_id})

                orchestrator = await build_orchestrator(
                    session,
                    run_id,
                    profile=request.profile,
                    event_sink=event_sink,
                    checkpoint=session.commit,
                )
                task = asyncio.create_task(
                    orchestrator.run(request.question)
                )
                while not task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(
                            queue.get(),
                            timeout=settings.config.deep_analysis.sse_keepalive_seconds,
                        )
                        yield _sse(event)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"

                result = await task
                if request.conversation_id and assistant_message_id:
                    await ChatService.add_message(
                        conversation_id=request.conversation_id,
                        role="assistant",
                        content=result["report_markdown"],
                        message_id=assistant_message_id,
                        model_name="deep-analysis-harness",
                        metadata={
                            "deep_analysis_run_id": run_id,
                            "research_status": "completed",
                        },
                    )
                yield _sse(
                    {
                        "type": "completed",
                        "run_id": run_id,
                        "report_markdown": result["report_markdown"],
                    }
                )
        except asyncio.CancelledError:
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            raise
        except Exception as exc:
            logger.error(
                "Deep analysis run failed: %s",
                exc,
                exc_info=True,
            )
            yield _sse(
                {
                    "type": "failed",
                    "run_id": run_id,
                    "error": str(exc),
                }
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

