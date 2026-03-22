"""Celery 태스크: DB 폴링 기반 동적 스케줄 실행기

Phase 4 (OpenClaw Cron 스케줄 스킬)

설계 원칙:
- Celery Beat의 정적 beat_schedule에 단 1개의 폴러 태스크만 등록
- DB에서 next_run_at <= now 인 활성 태스크를 조회하여 비동기 워크플로우 태스크 제출
- croniter로 다음 실행 시각(next_run_at)을 계산 후 DB 업데이트
- 외부 라이브러리(redbeat 등) 없이 동적 스케줄 추가/삭제 지원
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from celery import shared_task
from croniter import croniter
from sqlalchemy import select

logger = logging.getLogger(__name__)


@shared_task(
    name="neos.tasks.poll_scheduled_tasks",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def poll_and_run_scheduled_tasks(self):
    """매 1분마다 실행 — next_run_at이 만료된 활성 태스크를 워크플로우에 제출.

    Celery Beat beat_schedule에 crontab(minute="*")으로 등록한다.
    동기 SQLAlchemy 세션을 사용하는 이유: Celery 워커는 asyncio 이벤트 루프가 없음.
    """
    from neos.database.connection import SessionLocal  # 동기 세션
    from neos.database.models import ScheduledTask

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # DB는 naive UTC 저장

    try:
        with SessionLocal() as db:
            stmt = (
                select(ScheduledTask)
                .where(
                    ScheduledTask.is_active == True,
                    ScheduledTask.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)  # 다중 워커 중복 실행 방지
            )
            tasks = db.scalars(stmt).all()

            dispatched = 0
            for task in tasks:
                try:
                    # 워크플로우 비동기 태스크 제출
                    run_workflow_task.delay(str(task.id))

                    # 다음 실행 시각 계산
                    cron = croniter(task.cron_expression, now)
                    task.next_run_at = cron.get_next(datetime)
                    task.last_run_at = now
                    task.run_count = (task.run_count or 0) + 1
                    task.last_error = None
                    dispatched += 1

                except Exception as exc:
                    logger.error(
                        "Failed to dispatch scheduled task %s: %s",
                        task.id,
                        exc,
                        exc_info=True,
                    )
                    task.last_error = str(exc)[:500]

            db.commit()

        if dispatched:
            logger.info("Dispatched %d scheduled task(s)", dispatched)

    except Exception as exc:
        logger.error("poll_and_run_scheduled_tasks failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    name="neos.tasks.run_workflow_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_workflow_task(self, task_id: str):
    """단일 스케줄 태스크를 NEOS 워크플로우로 실행.

    채널 어댑터가 활성화된 경우 결과를 해당 채널로 전송한다.
    """
    from neos.database.connection import SessionLocal
    from neos.database.models import ScheduledTask

    try:
        with SessionLocal() as db:
            task = db.get(ScheduledTask, uuid.UUID(task_id))
            if not task or not task.is_active:
                logger.warning("Scheduled task %s not found or inactive, skipping", task_id)
                return

            query = task.query
            user_id = task.user_id
            channel_type = task.channel_type
            channel_id = task.channel_id

        logger.info(
            "Running scheduled task %s for user %s: %s",
            task_id,
            user_id,
            query[:80],
        )

        # 비동기 워크플로우 실행을 동기 Celery 태스크 내에서 호출
        result = asyncio.run(_run_workflow(query, user_id))

        # 채널 어댑터 결과 전송 (채널이 활성화된 경우)
        if channel_type != "api" and channel_id:
            asyncio.run(_send_to_channel(channel_type, channel_id, result))

    except Exception as exc:
        logger.error("run_workflow_task %s failed: %s", task_id, exc, exc_info=True)
        # DB에 오류 기록
        try:
            with SessionLocal() as db:
                task = db.get(ScheduledTask, uuid.UUID(task_id))
                if task:
                    task.last_error = str(exc)[:500]
                    db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _run_workflow(query: str, user_id: str) -> str:
    """NEOS 워크플로우를 직접 호출하여 응답 반환."""
    from neos.workflow.graph import build_workflow

    workflow = build_workflow()
    state = {
        "original_query": query,
        "user_id": user_id,
        "session_id": f"scheduled_{uuid.uuid4().hex[:8]}",
        "channel_source": "scheduler",
    }

    try:
        result_state = await workflow.ainvoke(state)
        return result_state.get("final_response", "")
    except Exception as exc:
        logger.error("Workflow execution failed for scheduled task: %s", exc)
        return f"[오류] 스케줄 태스크 실행 중 오류가 발생했습니다: {exc}"


async def _send_to_channel(channel_type: str, channel_id: str, content: str) -> None:
    """채널 어댑터를 통해 결과를 외부 채널로 전송."""
    try:
        from neos.api.channels.gateway import ChannelGateway
        gateway = ChannelGateway.get_instance()
        await gateway.send_to_channel(channel_type, channel_id, content)
    except Exception as exc:
        logger.warning(
            "Failed to send scheduled task result to channel %s/%s: %s",
            channel_type,
            channel_id,
            exc,
        )
