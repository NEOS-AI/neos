"""deep_analysis run의 durable job 러너 (Phase 3a, D22).

D7은 "M1은 인라인 asyncio + SSE, Celery는 나중"을 정했다. 이 모듈이 그
"나중"의 실행 코어다 -- run을 제출한 요청 **밖에서** 완주시킨다.

이 모듈은 프레임워크 프리다: Celery도 FastAPI도 ChatService도 임포트하지
않는다. 실행자 선택(Celery vs 백그라운드 asyncio)과 대화 메시지 저장은
통합 계층인 `neos/tasks/deep_analysis_job_task.py`가 담당한다. 그래야
`deep_analysis`의 내부 의존 4개가 유지된다.

## event_sink를 쓰지 않는 이유

`Ledger.log()`가 이미 하네스 이벤트 대부분을 `deep_analysis_events`에
쓴다. 오케스트레이터의 `_emit`(event_sink)은 그 kind들과 겹치므로, job이
"DB에 쓰는 싱크"를 넘기면 같은 이벤트가 두 번 쌓인다. 겹치는 kind만
골라내는 allowlist는 오케스트레이터 내부와 조용히 결합되는 함정이다.

대신 `job_` 접두어의 라이프사이클 이벤트 4종만 직접 쓴다 -- 이 접두어는
하네스의 어떤 kind와도 충돌할 수 없고, 하네스 코어를 한 줄도 바꾸지
않는다(D18의 "최소 침습" 제약).

## resume (AC5)

resume은 새 상태 저장소가 아니라 진입점 추가다(스펙 §5.3). 같은 run_id로
`orch.run()`을 다시 부르는 것이 곧 resume이며, 중복 지출은 원장이 막는다:

- `ledger.recover()`가 investigating에 잠긴 질문을 open으로 회수한다
- `_ensure_root()`가 기존 루트를 찾으면 즉시 반환해 LLM 재분해를 막는다
- `budgeter.should_stop()`이 `ledger.total_spent()`(= DAQuestion.spent_tokens
  의 DB 합계)를 읽으므로, 인메모리 Budgeter가 리셋돼도 소비 기록은 남는다
- 충돌 재조사 캡은 인메모리 카운터가 아니라 이벤트 로그를 게이트로 쓴다
  (`orchestrator.py:611`, `ledger.has_event`) -- "resumed run은 두 번째
  라운드를 쓸 수 없다"는 불변식이 이미 코드에 있다

따라서 `resume` 플래그는 (a) 어떤 라이프사이클 이벤트를 남길지, (b)
failed run을 running으로 되돌릴지만 결정한다. 이 성질 덕분에 Celery가
worker-lost로 태스크를 resume=False로 재배달해도 안전하다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neos.database.deep_analysis_models import DARun
from neos.utils.logger import get_logger

from .ledger import Ledger
from .service import build_orchestrator

logger = get_logger(__name__)

JOB_STARTED = "job_started"
JOB_RESUMED = "job_resumed"
JOB_COMPLETED = "job_completed"
JOB_FAILED = "job_failed"

#: 스트림이 이 kind를 보면 종료한다.
TERMINAL_JOB_KINDS = frozenset({JOB_COMPLETED, JOB_FAILED})

#: 재개 가능한 run 상태. 'completed'는 제외한다 -- 완료된 run을 다시 돌리면
#: 리포트 조립/채점 비용을 재지출한다(재과금).
RESUMABLE_STATUSES = frozenset({"running", "failed"})


class RunNotResumable(Exception):
    """resume 대상 run이 없거나 이미 완료됐을 때."""


async def _log_lifecycle(
    session,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """라이프사이클 이벤트 1건을 기록하고 즉시 커밋한다.

    커밋이 필수다 -- flush만 하면 다른 프로세스의 커서 리더가 볼 수 없다.
    """
    await Ledger(session, run_id).log(kind, None, payload)
    await session.commit()


async def _record_failure(session_factory, run_id: str, error: str) -> None:
    """실패 상태를 **새 세션**에서 내구성 있게 확정한다.

    실행 세션은 롤백/오류 상태일 수 있어 재사용하지 않는다(D18 선결조건 #2가
    챗 노드에서 겪은 것과 같은 함정).
    """
    try:
        async with session_factory() as session:
            run = await session.get(DARun, run_id)
            if run is not None:
                run.status = "failed"
            await _log_lifecycle(session, run_id, JOB_FAILED, {"error": error})
    except Exception:  # noqa: BLE001 - 원래 예외를 가리면 안 된다
        logger.error(
            "failed to persist job_failed for deep_analysis run %s",
            run_id,
            exc_info=True,
        )


async def execute_run(
    session_factory,
    run_id: str,
    question: str,
    profile: str,
    *,
    resume: bool = False,
    timeout_seconds: float | None = None,
    build_orchestrator_fn=build_orchestrator,
) -> dict[str, str]:
    """이미 생성된 run을 완주(또는 재개)시킨다.

    `session_factory`는 인자 없이 호출하면 async context manager를 돌려주는
    팩토리다(프로덕션: `neos.database.connection.get_session_ctx`). job이
    자기 세션을 소유하므로 제출한 요청의 세션을 빌리지 않는다.
    """
    async with session_factory() as session:
        await _log_lifecycle(
            session,
            run_id,
            JOB_RESUMED if resume else JOB_STARTED,
            {"profile": profile, "resume": resume},
        )
        orchestrator = await build_orchestrator_fn(
            session,
            run_id,
            profile=profile,
            checkpoint=session.commit,
        )
        try:
            run_coro = orchestrator.run(question)
            result = (
                await asyncio.wait_for(run_coro, timeout=timeout_seconds)
                if timeout_seconds is not None
                else await run_coro
            )
        except Exception as exc:  # noqa: BLE001
            error = (
                f"deep_analysis job timed out after {timeout_seconds} seconds"
                if isinstance(exc, TimeoutError)
                else str(exc)
            )
            logger.error(
                "deep_analysis job %s failed: %s", run_id, error, exc_info=True
            )
            await _record_failure(session_factory, run_id, error[:500])
            raise
        # AC6: 늦게 접속한 구독자가 이벤트 재생만으로 리포트를 받도록
        # 완료 이벤트가 리포트 본문을 싣는다.
        await _log_lifecycle(
            session,
            run_id,
            JOB_COMPLETED,
            {"report_markdown": result["report_markdown"]},
        )
        return result


async def resume_run(
    session_factory,
    run_id: str,
    *,
    timeout_seconds: float | None = None,
    build_orchestrator_fn=build_orchestrator,
) -> dict[str, str]:
    """중단된 run을 원장에 저장된 질문/프로파일로 재개한다."""
    async with session_factory() as session:
        run = await session.get(DARun, run_id)
        if run is None:
            raise RunNotResumable(f"run {run_id!r} not found")
        if run.status not in RESUMABLE_STATUSES:
            raise RunNotResumable(
                f"run {run_id!r} is {run.status!r}; "
                f"resumable statuses are {sorted(RESUMABLE_STATUSES)}"
            )
        question = run.root_question
        profile = run.profile
        if run.status != "running":
            run.status = "running"
            await session.commit()

    return await execute_run(
        session_factory,
        run_id,
        question,
        profile,
        resume=True,
        timeout_seconds=timeout_seconds,
        build_orchestrator_fn=build_orchestrator_fn,
    )
