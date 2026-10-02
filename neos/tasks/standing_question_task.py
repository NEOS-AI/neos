"""Celery 태스크: 상시 질문 폴러 -- 트랙 Q3 (docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §5).

`standing_agents.enabled` 와 `standing_agents.questions.enabled` 가 둘 다 켜졌을 때만
beat 에 등록된다(`celery_app.configure_standing_question_beat_schedule`). 매 분 한 번
`poll_once` 를 돈다 -- 끝난 DA 런을 정산하고, 때가 된 질문을 제출한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="neos.tasks.poll_standing_questions",
    bind=True,
    max_retries=0,
)
def poll_standing_questions(self):
    """한 번 돈다. 실패는 다음 분에 다시 본다 -- 재시도로 겹쳐 돌지 않는다."""
    try:
        asyncio.run(_poll_async())
    except Exception as exc:  # noqa: BLE001
        logger.error("poll_standing_questions failed: %s", exc, exc_info=True)


async def _poll_async() -> None:
    from neos.config.settings import settings
    from neos.database.connection import DatabaseManager
    from neos.standing.budget import build_agent_envelope
    from neos.standing.notifications import build_standing_notifier
    from neos.standing.questions import (
        PostgresDAReader,
        PostgresQuestionStore,
        da_submitter,
        poll_once,
    )

    standing = settings.config.standing_agents
    if not (standing.enabled and standing.questions.enabled):
        return
    # 태스크마다 새 이벤트 루프(`asyncio.run`)라 매니저도 새로 만든다 -- 지난 루프에 묶인
    # 커넥션을 다시 쓰지 않게(`curate_learned_skills` 와 같은 모양).
    manager = DatabaseManager()
    await manager.initialize()
    sessions = manager.get_session
    try:
        report = await poll_once(
            PostgresQuestionStore(sessions),
            PostgresDAReader(sessions),
            submit=da_submitter(sessions),
            envelope=build_agent_envelope(standing, sessions),
            notifier=build_standing_notifier(standing, sessions),
            profile=standing.questions.profile,
            max_claims=standing.questions.max_claims_per_section,
            settle_timeout=timedelta(minutes=standing.questions.settle_timeout_minutes),
            now=datetime.now(UTC),
        )
    finally:
        await manager.close()
    if report.dispatched or report.settled or report.failed or report.skipped:
        logger.info(
            "standing questions: dispatched=%d settled=%d notified=%d failed=%d skipped=%d",
            len(report.dispatched),
            len(report.settled),
            len(report.notified),
            len(report.failed),
            len(report.skipped),
        )
