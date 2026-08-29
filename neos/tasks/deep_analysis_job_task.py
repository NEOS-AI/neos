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


class DeepAnalysisDispatchError(RuntimeError):
    """Bounded public error for a Celery broker enqueue failure."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"deep_analysis dispatch failed for run {run_id}")
        self.run_id = run_id


def _celery_enabled() -> bool:
    return bool(getattr(settings, "CELERY_ENABLED", False))


_FAILURE_BODY = (
    "심층분석을 완료하지 못했습니다. 실패 사유는 실행 원장에 기록되었습니다."
)
_TIMEOUT_BODY = (
    "심층분석이 제한 시간 안에 끝나지 않았습니다. "
    "실패 사유는 실행 원장에 기록되었습니다."
)


def _failure_body(exc: BaseException) -> str:
    """실패한 run 이 대화에 남길 본문.

    **예외 문자열을 싣지 않는다.** 진단은 이미 `job_failed` 페이로드에 있고
    그쪽은 운영자용이다. 이 문자열은 대화에 남는 **사용자용**이라, 내부 경로나
    접속 정보가 섞일 수 있는 `str(exc)` 를 그대로 흘리면 안 된다.

    가르는 것은 사용자가 실제로 다르게 행동할 수 있는 한 가지, 시간 초과뿐이다
    -- 그때는 다시 물어보는 것이 의미가 있고, 다른 실패는 그렇지 않다.
    """
    return _TIMEOUT_BODY if isinstance(exc, TimeoutError) else _FAILURE_BODY


async def _persist_assistant_message(
    run_id: str,
    report_markdown: str,
    degradations: list[dict[str, object]] | None = None,
    *,
    status: str = "completed",
) -> None:
    """리포트를 대화 메시지로 저장한다(대화에 묶인 run만).

    인라인 SSE 시절 핸들러가 하던 일이다. 실행이 요청 밖으로 나갔으므로
    job 쪽으로 옮긴다. 실패해도 run 자체는 성공이므로 삼킨다 -- 리포트는
    이미 job_completed 이벤트에 실려 있다.

    ⚠️ 다만 **강등은 이 경로에만 있다.** 여기서 예외가 나면 새로고침 후 UI가
    다시 침묵한다 -- 로드맵 §7 P1 #8(예외를 삼키는 영속화)의 새 피해자다.
    삼키는 동작은 유지한다(run 은 성공했고 리포트는 `job_completed` 에 있다).
    ✅ **P1 #8: 흔적을 원장으로 올렸다** -- 예전에는 `logger.warning` 하나뿐이라
    조회할 수 없었다. 이제 `assistant_message_persist_failed` 이벤트가 남는다.

    **`upsert` 여야 한다 (FE5).** 실패한 run 도 여기로 오게 되면서 같은
    `message_id` 가 두 번 쓰일 수 있게 됐다 -- 실패로 한 번, Celery 재시도가
    `resume=True` 로 완주하면 진짜 리포트로 다시. `add_message` 는 순수
    INSERT 이고 `message_id` 는 UNIQUE 라 둘째 쓰기가 예외를 내는데, 바로 위
    `except` 가 그것을 삼킨다. 그러면 **실패 메시지가 남고 성공한 리포트는
    영영 저장되지 않는다** -- 고치려던 조용한 실패를 하나 더 만드는 셈이다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.deep_analysis_models import DARun

    try:
        async with get_session_ctx() as session:
            run = await session.get(DARun, run_id)
            conversation_id = getattr(run, "conversation_id", None)
            message_id = getattr(run, "assistant_message_id", None)

        if not conversation_id or not message_id:
            return

        await ChatService.upsert_message(
            conversation_id=conversation_id,
            role="assistant",
            content=report_markdown,
            message_id=message_id,
            model_name="deep-analysis-harness",
            metadata={
                "deep_analysis_run_id": run_id,
                "research_status": status,
                # 프론트 브리지(`web/lib/deep-analysis/metadata.ts`)가 읽는 키다.
                # 이름을 바꾸면 새로고침 후 강등 경고가 조용히 사라진다.
                "deep_analysis_degradations": degradations or [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        lost = len(degradations or [])
        logger.warning(
            "failed to persist deep_analysis report message: "
            "run=%s status=%s error_type=%s degradations_lost=%d",
            run_id,
            status,
            type(exc).__name__,
            lost,
        )
        # P1 #8: 로그는 조회할 수 없다. 같은 사실을 원장에도 남긴다 -- 이
        # 경로의 실패는 사용자가 리포트도 강등도 못 보게 만드는데, 지금까지
        # 그 사실 자체가 어디에도 durable 하게 없었다. `record_...` 는 절대
        # 던지지 않으므로 이 except 블록의 의미를 바꾸지 않는다.
        from neos.workflow.deep_analysis import jobs

        await jobs.record_message_persist_failure(
            get_session_ctx,
            run_id,
            status=status,
            error_type=type(exc).__name__,
            degradations_lost=lost,
        )


async def _execute(
    run_id: str,
    question: str,
    profile: str,
    resume: bool,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    """두 실행자가 공유하는 async 본문."""
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.jobs import (
        execute_run,
        load_degradations,
        resume_run,
    )

    try:
        if resume:
            result = await resume_run(
                get_session_ctx,
                run_id,
                timeout_seconds=timeout_seconds,
            )
        else:
            result = await execute_run(
                get_session_ctx,
                run_id,
                question,
                profile,
                timeout_seconds=timeout_seconds,
            )
    except Exception as exc:  # noqa: BLE001 - 원래 예외를 그대로 다시 던진다
        # FE5: 실패한 run 의 강등은 여태 메시지에 남지 않았다 -- 이 경로가
        # 없어서 **메시지 자체가 만들어지지 않았기** 때문이다. 라이브 스트림을
        # 보고 있던 사용자는 강등을 봤지만 새로고침하면 사라졌고, 나중에
        # 이력을 여는 사용자는 애초에 못 봤다.
        #
        # 강등은 원장에 남아 있으므로 여기서 읽어 붙인다. 실패 자체의 기록
        # (`job_failed`)은 이미 `execute_run` 이 새 세션에서 확정했다.
        await _persist_assistant_message(
            run_id,
            _failure_body(exc),
            await load_degradations(get_session_ctx, run_id),
            status="failed",
        )
        raise

    await _persist_assistant_message(
        run_id,
        result["report_markdown"],
        result.get("degradations"),
    )
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


async def _record_dispatch_failure(run_id: str) -> None:
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.jobs import record_dispatch_failure

    await record_dispatch_failure(get_session_ctx, run_id)


async def submit_deep_analysis_job(
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
        try:
            run_deep_analysis_job.apply_async(
                kwargs=kwargs,
                queue=settings.config.deep_analysis.job_queue,
            )
        except Exception as exc:  # noqa: BLE001 - transport-specific errors
            logger.error(
                "deep_analysis broker dispatch failed for run %s",
                run_id,
                exc_info=True,
            )
            try:
                await _record_dispatch_failure(run_id)
            except Exception:  # noqa: BLE001 - preserve the broker failure
                logger.error(
                    "deep_analysis dispatch failure persistence failed "
                    "for run %s",
                    run_id,
                    exc_info=True,
                )
            raise DeepAnalysisDispatchError(run_id) from exc
        return "celery"

    task = asyncio.create_task(
        _execute(
            run_id,
            question,
            profile,
            resume,
            timeout_seconds=_config.job_soft_time_limit,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_task)
    return "inline"
