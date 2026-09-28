"""질문 하나를 조사 자식으로 돌린다 (계약 §2 · §3.4).

`investigate_via_subagent` 의 조사판이다. 다른 점 셋:

1. **도구 포트가 질문마다 새로 태어난다.** 샌드박스도 그렇다. `_run_round`
   가 `asyncio.gather` 로 질문들을 동시에 돌리므로 공유하면 서로의 증거를
   덮어쓴다.
2. **blob 을 결과에 싣지 않는다.** `fetch.v1` 이 이미 건별로 커밋했다.
   결과에 또 실으면 오케스트레이터의 `commit_blobs(result.blobs)` 가 같은
   blob 을 두 번째 경로로 흘려보낸다.
3. **제출이 곧 결과다.** 자식의 산문을 요약하는 것이 아니라 `submit.v1` 의
   JSON 을 읽는다 -- 그것이 계약 §3.4 가 "JSON 외 출력 금지" 를 대체한
   이유다.
"""

from __future__ import annotations

from typing import Any

from neos.subagent.types import StepKind

from .models import Assignment, WorkerResult
from .research_session import CommandLimits, open_research_session
from .sandbox import RESEARCH_PROFILE
from .subagent_adapter import build_research_ticket, research_briefing

#: 제출 없이 턴이 끝났다. 계약 §3.4 는 이것을 `partial` 로 처리하고 **이유를
#: 남기라**고 적는다 -- 조용한 degrade 금지.
SUBMIT_NOT_CALLED = "submit_not_called"


async def _briefing_material(
    ledger: Any, question_id: str
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """briefing 에 실을 원장 상태: verified quote 클레임(ID 와 함께)과 막다른 길.

    원장 접근자를 방어적으로 읽는 것은 `assignment.py` 와 같은 패턴이다 --
    최소 test double 이 둘을 구현하지 않아도 된다. 그 경우 briefing 은 goal
    만 싣는다(옛 모양).
    """
    verified_fn = getattr(ledger, "verified_claims", None)
    pairs = await verified_fn(question_id) if verified_fn is not None else []
    verified = tuple(
        (str(claim.id), str(claim.text))
        for claim, _evidence in pairs
        # 계산 위에 계산을 쌓지 못한다(계약 §5 규칙 2). premises 후보에서부터 뺀다.
        if (getattr(claim, "kind", None) or "quote") == "quote"
    )
    dead_ends_fn = getattr(ledger, "unverified_and_deadends", None)
    dead_ends = (
        tuple(await dead_ends_fn(question_id)) if dead_ends_fn is not None else ()
    )
    return verified, dead_ends


def _pointers(outcome: Any) -> dict[str, Any]:
    return {
        "tokens_spent": int(getattr(outcome, "tokens_delta", 0) or 0),
        "subagent_run_id": str(getattr(outcome, "run_id", "") or ""),
        "subagent_checkpoint_id": str(getattr(outcome, "checkpoint_id", "") or ""),
        "subagent_step_kind": getattr(getattr(outcome, "kind", None), "value", ""),
    }


async def run_research_worker(
    assignment: Assignment,
    *,
    ledger: Any,
    provider: Any,
    grader: Any,
    cap_bytes: int,
    limits: Any,
    fetch_fn: Any,
    runtime_factory: Any,
    parent_id: str,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
    command_limits: CommandLimits | None,
    profile: str = RESEARCH_PROFILE,
) -> WorkerResult:
    """샌드박스를 열고, 자식을 한 걸음 돌리고, 제출을 거둔다.

    `command_limits` 는 **기본값이 없다** (J1.5). 호출부가 둘이고(오케스트레이터 ·
    J3 섀도) 기본값이 None 이면 한쪽이 잊어도 초록이다 -- 그쪽 자식은 코드를
    돌리지 못하는 채로 돈다. 코딩 도구 없이 돌리려면 None 을 **적어서** 넘긴다.

    `runtime_factory(port)` 로 런타임을 받는 이유는 포트가 질문마다 새로
    만들어지기 때문이다. 런타임은 `SubagentRuntime.__init__` 이 순수 대입이라
    질문마다 지어도 싸다.
    """
    session = await open_research_session(
        ledger=ledger,
        provider=provider,
        question_id=assignment.question_id,
        cap_bytes=cap_bytes,
        fetch_fn=fetch_fn,
        limits=limits,
        grader=grader,
        profile=profile,
        command_limits=command_limits,
    )
    verified, dead_ends = await _briefing_material(ledger, assignment.question_id)
    ticket = build_research_ticket(
        assignment,
        parent_id=parent_id,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
        briefing=research_briefing(
            assignment, verified=verified, dead_ends=dead_ends
        ),
    )
    try:
        runtime = runtime_factory(session.port)
        try:
            outcome = await runtime.advance(ticket)
        except Exception as exc:  # noqa: BLE001 — `_run_legacy_worker` 와 같은 울타리
            return WorkerResult(
                question_id=assignment.question_id,
                status="failed",
                fail_reason=str(exc) or type(exc).__name__,
                model=ticket.model.model,
            )

        pointers = _pointers(outcome)
        if outcome.kind is StepKind.CONTINUING:
            # 아직 끝나지 않았다. 포인터를 넘겨 다음 라운드가 이어받는다.
            return WorkerResult(
                question_id=assignment.question_id,
                status="partial",
                model=ticket.model.model,
                **pointers,
            )

        submission = session.port.submission
        if submission is None:
            return WorkerResult(
                question_id=assignment.question_id,
                status="partial",
                fail_reason=SUBMIT_NOT_CALLED,
                model=ticket.model.model,
                **pointers,
            )

        return WorkerResult(
            question_id=assignment.question_id,
            status=submission.status,
            claims=list(submission.claims),
            # 비어 있는 것이 맞다 -- 건별로 이미 원장에 들어갔다.
            blobs=[],
            repairs=list(submission.repairs),
            proposed_subquestions=list(submission.proposed_subquestions),
            dead_ends=list(submission.dead_ends),
            self_assessment=submission.self_assessment,
            report_path=submission.report_path,
            model=ticket.model.model,
            **pointers,
        )
    finally:
        # 리스가 없으므로 뒤늦게 회수해 줄 층이 없다.
        await session.close()
