"""deep_analysis durable job의 실행자 계층 (Phase 3a, D22).

**실행자는 둘, 계약은 하나다.**

- `CELERY_ENABLED=true`  → `apply_async`로 큐잉, 워커 프로세스가 완주
- `CELERY_ENABLED=false` → 응답을 막지 않는 백그라운드 asyncio 태스크

기본값이 `false`이므로(`schema.py` CeleryConfig.enabled) 폴백이 없으면
기본 구성에서 심층분석이 아예 안 도는 회귀가 된다. 두 경로 모두 같은
`_execute`를 돌고 **같은 DB 이벤트 로그**에 쓰므로,
`GET /api/v1/deep-analysis/{run_id}/events`는 실행자와 무관하게 동일하게
동작한다. 실행자는 운영 선택이지 API 계약이 아니다.

이 모듈이 `neos/tasks/`에 있는 이유: `deep_analysis` 패키지는 프레임워크
프리이고 내부 의존이 4개다. Celery와 ChatService는 그 안으로 들어가면
안 되는 통합 관심사이므로 여기서 흡수한다.
"""

from __future__ import annotations

import asyncio

from celery import shared_task

from neos.config.settings import settings
from neos.utils.logger import get_logger

logger = get_logger(__name__)

#: 실행 중인 인라인 태스크의 강한 참조. asyncio.create_task의 반환값을
#: 붙들지 않으면 GC가 실행 중 태스크를 거둬갈 수 있다.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

_config = settings.config.deep_analysis


def _celery_enabled() -> bool:
    return bool(getattr(settings, "CELERY_ENABLED", False))


async def _persist_assistant_message(run_id: str, report_markdown: str) -> None:
    """리포트를 대화 메시지로 저장한다(대화에 묶인 run만).

    인라인 SSE 시절 핸들러가 하던 일이다. 실행이 요청 밖으로 나갔으므로
    job 쪽으로 옮긴다. 실패해도 run 자체는 성공이므로 삼킨다 -- 리포트는
    이미 job_completed 이벤트에 실려 있다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.deep_analysis_models import DARun

    async with get_session_ctx() as session:
        run = await session.get(DARun, run_id)
        conversation_id = getattr(run, "conversation_id", None)
        message_id = getattr(run, "assistant_message_id", None)

    if not conversation_id or not message_id:
        return

    try:
        await ChatService.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=report_markdown,
            message_id=message_id,
            model_name="deep-analysis-harness",
            metadata={
                "deep_analysis_run_id": run_id,
                "research_status": "completed",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to persist deep_analysis report message for run %s: %s",
            run_id,
            exc,
        )


async def _execute(
    run_id: str,
    question: str,
    profile: str,
    resume: bool,
) -> dict[str, str]:
    """두 실행자가 공유하는 async 본문."""
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.jobs import execute_run, resume_run

    if resume:
        result = await resume_run(get_session_ctx, run_id)
    else:
        result = await execute_run(get_session_ctx, run_id, question, profile)

    await _persist_assistant_message(run_id, result["report_markdown"])
    return result


@shared_task(
    name="neos.tasks.run_deep_analysis_job",
    bind=True,
    max_retries=_config.job_max_retries,
    default_retry_delay=30,
    soft_time_limit=_config.job_soft_time_limit,
    time_limit=_config.job_time_limit,
)
def run_deep_analysis_job(
    self,
    run_id: str,
    question: str = "",
    profile: str = "dev",
    resume: bool = False,
):
    """deep_analysis run 하나를 완주시킨다.

    재시도는 **resume=True로** 재큐잉한다(스펙 §9 "resume 트리거 = Celery
    재시도"). 중복 지출은 원장이 막으므로(jobs.py 참조) 재시도가 라운드
    예산을 다시 쓰지 않는다.
    """
    try:
        asyncio.run(_execute(run_id, question, profile, resume))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "run_deep_analysis_job %s failed: %s", run_id, exc, exc_info=True
        )
        raise self.retry(
            exc=exc,
            kwargs={
                "run_id": run_id,
                "question": question,
                "profile": profile,
                "resume": True,
            },
        )


def _discard_task(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("inline deep_analysis job failed: %s", exc, exc_info=exc)


def submit_deep_analysis_job(
    run_id: str,
    question: str = "",
    profile: str = "dev",
    *,
    resume: bool = False,
) -> str:
    """run을 설정된 실행자로 디스패치한다. 실행자 이름을 반환한다."""
    kwargs = {
        "run_id": run_id,
        "question": question,
        "profile": profile,
        "resume": resume,
    }
    if _celery_enabled():
        run_deep_analysis_job.apply_async(
            kwargs=kwargs,
            queue=settings.config.deep_analysis.job_queue,
        )
        return "celery"

    task = asyncio.create_task(_execute(run_id, question, profile, resume))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_task)
    return "inline"
