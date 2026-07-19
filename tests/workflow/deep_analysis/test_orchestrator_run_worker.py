import asyncio, pytest
from neos.workflow.deep_analysis.orchestrator import Orchestrator
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
    async def investigate(self, brief, effort, qid, repairs=None, question_text=""): raise RuntimeError("boom")
    def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")

def _orch(factory):
    return Orchestrator(session=None, run_id="r", worker_factory=factory, grader=None,
                        ledger=object(), decompose_fn=lambda t: [])

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

