"""Celery 태스크: 상시 에이전트 질문 만료 폴러 -- 트랙 Q9d
(docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §8, 결정 Q-C).

`ask_effective(config)` 가 참일 때만 beat 에 등록된다
(`celery_app.configure_standing_ask_beat_schedule`). 매 분 한 번 기한이 지난 대기 질문을
만료시킨다. 태스크는 끝나지 않는다 -- `waiting_user -> running` 으로 돌아가고, 깨어난 루프가
`ask_user.v1` 에 `ask_expired` 거절을 준다. 소유자에게 `ask_expired` 알림이 한 번 간다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from celery import shared_task

logger = logging.getLogger(__name__)

#: 한 번에 만료시키는 질문 수. 남은 것은 다음 분에 본다.
_BATCH = 100


@shared_task(
    name="neos.tasks.expire_standing_asks",
    bind=True,
    max_retries=0,
)
def expire_standing_asks(self):
    """한 번 돈다. 실패는 다음 분에 다시 본다 -- 재시도로 겹쳐 돌지 않는다."""
    try:
        asyncio.run(_expire_async())
    except Exception as exc:  # noqa: BLE001
        logger.error("expire_standing_asks failed: %s", exc, exc_info=True)


async def _expire_async() -> None:
    from neos.coding.repositories.run_repository import PostgresCodingRunRepository
    from neos.config.settings import settings
    from neos.database.connection import DatabaseManager
    from neos.standing.asks import ask_effective, expire_due_asks

    config = settings.config
    if not ask_effective(config):
        return

    async def wake(task_id: str, checkpoint_id: str | None) -> None:
        # Celery 가 꺼진 개발 실행에서는 조정 스윕이 `running` 태스크를 찾는다.
        if not settings.CODING_CELERY_ENABLED:
            return
        from neos.coding.runtime import create_celery_dispatcher
        from neos.coding.workers.dispatcher import CodingDispatchSource

        create_celery_dispatcher().enqueue(
            task_id, expected_checkpoint_id=checkpoint_id, source=CodingDispatchSource.RESUME
        )

    manager = DatabaseManager()
    await manager.initialize()
    try:
        commits = await expire_due_asks(
            PostgresCodingRunRepository(manager.get_session),
            limit=_BATCH,
            now=datetime.now(UTC),
            wake=wake,
            max_body_chars=config.standing_agents.notifications.max_body_chars,
        )
    finally:
        await manager.close()
    if commits:
        logger.info("standing asks: expired=%d", len(commits))
