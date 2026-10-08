import asyncio

import pytest
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.stall import StallTracker
from neos.workflow.deep_analysis.models import Assignment, Effort, WorkerResult, ProposedClaim

class HangingWorker:
    """buffer에 클레임 1개 넣고 무한 대기 → 타임아웃 시 flush_partial이 그 클레임 반환."""
    def __init__(self): self._claims = [ProposedClaim(text="buffered", confidence=0.5)]
    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        await asyncio.sleep(10)
        return WorkerResult(question_id=qid, status="completed")
    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial", claims=list(self._claims))

class BoomWorker:
    # C3: 실패 경로가 워커의 누적 지출을 읽으므로 테스트 더블도 그것을 답해야 한다.
    # 값이 0 이 아닌 것이 요점이다 -- 0 이면 옛 동작(전부 버림)과 구별되지 않는다.
    tokens_spent = 137
    model = "claude-sonnet-5"

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""): raise RuntimeError("boom")
    def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")

def _orch(factory, **kwargs):
    return Orchestrator(session=None, run_id="r", worker_factory=factory, grader=None,
                        ledger=object(), decompose_fn=lambda t: [], **kwargs)

@pytest.mark.asyncio
async def test_timeout_yields_partial_with_buffer(monkeypatch):
    orch = _orch(lambda: HangingWorker())
    # wall_clock_cap을 짧게: config 접근을 우회하기 위해 effort별 캡을 패치
    from neos.workflow.deep_analysis import orchestrator as mod
    monkeypatch.setattr(mod, "_wall_clock_cap", lambda effort: 0.05)
    r = await orch._run_worker(Assignment(question_id="q", brief="b", effort=Effort.SCOUT))
    assert r.status == "partial" and r.claims[0].text == "buffered"

@pytest.mark.asyncio
async def test_exception_becomes_failed():
    orch = _orch(lambda: BoomWorker())
    r = await orch._run_worker(Assignment(question_id="q", brief="b", effort=Effort.SCOUT))
    assert r.status == "failed" and "boom" in r.fail_reason
    # C3: 예전에는 여기가 0 이었다 -- 실패한 워커가 태운 토큰이 통째로 사라졌다.
    # 바로 위 타임아웃 분기는 `flush_partial` 을 써서 같은 문제가 없었고,
    # 그 비대칭이 이 누수를 오래 숨겼다.
    assert r.tokens_spent == 137
    assert r.model == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_non_failed_worker_result_resets_systemic_failure_rounds():
    tracker = StallTracker(max_rounds=2)
    orch = _orch(lambda: BoomWorker(), stall_tracker=tracker)
    failed = WorkerResult(question_id="q", status="failed")
    completed = WorkerResult(question_id="q", status="completed")

    await orch._register_round_outcome([failed])
    await orch._register_round_outcome([completed])
    await orch._register_round_outcome([failed])

    assert tracker.failed_rounds == 1
