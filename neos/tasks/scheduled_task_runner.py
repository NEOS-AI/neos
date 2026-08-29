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
from datetime import datetime

from celery import shared_task
from croniter import croniter
from sqlalchemy import select

from neos.utils.time_utils import utc_now_naive

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
    """
    try:
        asyncio.run(_poll_async())
    except Exception as exc:
        logger.error("poll_and_run_scheduled_tasks failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


async def _poll_async():
    """비동기 폴러: next_run_at이 만료된 태스크를 조회하고 워크플로우 태스크 제출."""
    from neos.database.connection import get_session_ctx
    from neos.database.models import ScheduledTask

    now = utc_now_naive()  # DB는 naive UTC 저장

    async with get_session_ctx() as db:
        stmt = (
            select(ScheduledTask)
            .where(
                ScheduledTask.is_active == True,
                ScheduledTask.next_run_at <= now,
            )
            .with_for_update(skip_locked=True)  # 다중 워커 중복 실행 방지
        )
        result = await db.execute(stmt)
        tasks = result.scalars().all()

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

        await db.commit()

    if dispatched:
        logger.info("Dispatched %d scheduled task(s)", dispatched)


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
    try:
        asyncio.run(_run_workflow_task_async(task_id))
    except Exception as exc:
        logger.error("run_workflow_task %s failed: %s", task_id, exc, exc_info=True)
        # DB에 오류 기록
        try:
            asyncio.run(_record_task_error(task_id, str(exc)[:500]))
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _run_workflow_task_async(task_id: str) -> None:
    """태스크 조회, 워크플로우 실행, 채널 전송을 모두 비동기로 처리."""
    from neos.database.connection import get_session_ctx
    from neos.database.models import ScheduledTask

    async with get_session_ctx() as db:
        task = await db.get(ScheduledTask, uuid.UUID(task_id))
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

    result = await _run_workflow(query, str(user_id))

    # 채널 어댑터 결과 전송 (채널이 활성화된 경우)
    if channel_type != "api" and channel_id:
        await _send_to_channel(channel_type, channel_id, result)


async def _record_task_error(task_id: str, error_msg: str) -> None:
    """워크플로우 실패 시 DB에 오류 메시지를 기록."""
    from neos.database.connection import get_session_ctx
    from neos.database.models import ScheduledTask

    async with get_session_ctx() as db:
        task = await db.get(ScheduledTask, uuid.UUID(task_id))
        if task:
            task.last_error = error_msg
            await db.commit()


async def _run_workflow(query: str, user_id: str) -> str:
    """NEOS 워크플로우를 직접 호출하여 응답 반환."""
    from neos.workflow.graph import multi_agent_workflow

    state = {
        "query": query,            # execute_workflow가 기대하는 필수 키
        "user_id": user_id,
        "session_id": f"scheduled_{uuid.uuid4().hex[:8]}",
        "channel_source": "scheduler",
    }

    try:
        result_state = await multi_agent_workflow.execute_workflow(state)
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


# ── Task 6 (Approval): 만료된 PendingApproval 자동 거부 ─────────────────────


@shared_task(
    name="neos.tasks.expire_pending_approvals",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def expire_pending_approvals(self):
    """5분마다 실행 — expires_at이 지난 미결 승인 요청을 자동 거부한다.

    Celery Beat beat_schedule에 300초 주기로 등록한다.
    resolved=FALSE이고 expires_at < NOW() 인 항목을 조회하여
    워크플로우 상태에 approval_decision='rejected'를 삽입하고
    pending_approvals.resolved=TRUE로 표시한다.
    """
    try:
        asyncio.run(_expire_pending_approvals_async())
    except Exception as exc:
        logger.error("expire_pending_approvals failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


async def _expire_pending_approvals_async() -> None:
    """만료된 pending_approvals 항목을 조회하여 자동 거부 처리한다."""
    from neos.database.connection import get_session_ctx, db_manager
    from neos.database.models import PendingApproval
    from sqlalchemy import update as sa_update

    now = utc_now_naive()

    async with get_session_ctx() as db:
        stmt = (
            select(PendingApproval)
            .where(
                PendingApproval.resolved == False,
                PendingApproval.expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        expired = result.scalars().all()

        if not expired:
            return

        expired_ids = []
        for item in expired:
            expired_ids.append(item.id)
            item.resolved = True  # 먼저 resolved 표시 (중복 처리 방지)

        await db.commit()

    # resolved 표시 후 워크플로우 상태 업데이트 (graph 의존성은 커밋 후 처리)
    rejected_count = 0
    for item in expired:
        try:
            # 실제로 결정을 쓴 것만 센다. 건너뜀과 복원 실패는 거부가 아니다 --
            # 세면 아래 로그의 N 이 원장과 어긋난다.
            if await _inject_timeout_rejection(
                session_id=item.session_id,
                request_id=item.request_id,
            ):
                rejected_count += 1
        except Exception as exc:
            logger.warning(
                "Failed to inject timeout rejection for request_id=%s: %s",
                item.request_id,
                exc,
            )

    logger.info(
        "[ExpirePendingApprovals] Auto-rejected %d expired approval(s)",
        rejected_count,
    )


async def _inject_timeout_rejection(session_id: str, request_id: str) -> bool:
    """만료된 승인 요청에 대해 워크플로우 상태에 rejection을 주입한다.

    **결정은 재개와 같은 그래프에 쓴다.** 설계된 run 은 `execution_topology`
    를 상태에 싣고 멈추므로, 정적 그래프로 쓰면 LangGraph 가 정적 간선으로
    `as_node` 를 풀어 엉뚱한 후속 노드를 트리거하거나 `InvalidUpdateError` 를
    낸다. 핸들러 경로(`approval_handlers.respond_to_approval`)가 이미 쓰는
    `resume_graph_for` 를 여기서도 쓴다 -- 사람이 누른 거부와 타임아웃이 낸
    거부가 서로 다른 그래프에 쓸 이유가 없다.

    반환값은 **실제로 결정을 썼는지**다. 건너뜀(체크포인터 미사용·이미
    결정됨·pending 아님)과 복원 실패는 전부 `False` 이며, 호출부는 이것으로
    "Auto-rejected N개" 를 센다. 예외는 삼키지 않고 호출부로 올린다 -- 예전의
    `except Exception ... non-critical` 은 바깥 루프의 try/except 를 죽은
    코드로 만들어 실패한 주입까지 성공으로 세게 했다.
    """
    from neos.workflow.graph import multi_agent_workflow
    from neos.workflow.resume_graph import ResumeGraphUnavailable, resume_graph_for

    if (
        not multi_agent_workflow._graph_initialized
        or not multi_agent_workflow._graph_uses_checkpointer
    ):
        logger.debug(
            "[ExpirePendingApprovals] Graph not in checkpointer mode, skipping injection "
            "for session=%s",
            session_id,
        )
        return False

    graph = multi_agent_workflow.graph
    config = {"configurable": {"thread_id": session_id}}

    current_state = await graph.aget_state(config)
    if current_state is None:
        return False

    pending = current_state.values.get("pending_approvals") or []
    # 이미 다른 결정이 내려졌으면 스킵
    if current_state.values.get("approval_decision") is not None:
        return False
    # 해당 request_id가 아직 pending 상태인지 확인
    if not any(p.get("request_id") == request_id for p in pending):
        return False

    try:
        resume_graph = await resume_graph_for(
            current_state.values,
            workflow=multi_agent_workflow,
            checkpointer=graph.checkpointer,
        )
    except ResumeGraphUnavailable as error:
        # **정적 그래프로 내려가지 않는다.** 내려가면 타임아웃이 처리된 것처럼
        # 보이면서 설계가 의도한 것과 다른 파이프라인이 트리거된다. 쓰지 않으면
        # `pending_approvals` 가 그대로 남아 상태가 사실과 어긋나지 않는다.
        logger.error(
            "[ExpirePendingApprovals] resume graph unavailable, not injecting: "
            "session=%s request_id=%s reason=%s",
            session_id,
            request_id,
            error.reason,
        )
        return False

    await resume_graph.aupdate_state(
        config=config,
        values={"approval_decision": "rejected"},
    )
    logger.info(
        "[ExpirePendingApprovals] Injected timeout rejection: session=%s request_id=%s",
        session_id,
        request_id,
    )
    return True


# ── Phase 8 (A2UI): 만료된 UIFrameSession 정리 ──────────────────────────────


@shared_task(
    name="neos.tasks.cleanup_expired_ui_frames",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def cleanup_expired_ui_frames(self):
    """1시간마다 실행 — 만료된 UIFrameSession 레코드를 삭제한다.

    Celery Beat beat_schedule에 crontab(minute=0)으로 등록한다.
    """
    try:
        asyncio.run(_cleanup_ui_frames_async())
    except Exception as exc:
        logger.error("cleanup_expired_ui_frames failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


async def _cleanup_ui_frames_async() -> None:
    """만료된 ui_frame_sessions 레코드를 DB에서 삭제."""
    from neos.database.connection import get_session_ctx
    from neos.database.models import UIFrameSession
    from sqlalchemy import delete as sa_delete

    now = utc_now_naive()

    async with get_session_ctx() as db:
        result = await db.execute(
            sa_delete(UIFrameSession).where(UIFrameSession.expires_at < now)
        )
        await db.commit()
        logger.info(
            "[CleanupUIFrames] Deleted %d expired UIFrameSession records",
            result.rowcount,
        )
