import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort

def _q(qid, **kw):
    base = dict(id=qid, confidence=0.0, value_est=1.0, spent_tokens=0,
                cap_tokens=2000, fail_streak=0, depth=1, status="open", parent_id="root")
    base.update(kw); return SimpleNamespace(**base)

class FakeLedger:
    def __init__(self, questions, spent=0, root_id="root"):
        self._questions = questions; self._spent = spent; self._root_id = root_id
    async def open_questions(self): return [q for q in self._questions if q.status == "open"]
    async def children(self, qid): return [q for q in self._questions if q.parent_id == qid]
    async def root_question(self): return SimpleNamespace(id=self._root_id)
    async def gain_history(self, qid, last_n=3): return []
    async def total_spent(self): return self._spent

@pytest.mark.asyncio
async def test_first_round_breadth_pass_all_scout():
    qs = [_q("a"), _q("b"), _q("c")]
    b = Budgeter(global_token_cap=10000, breadth_pass_ratio=0.30)
    picks = await b.select(FakeLedger(qs, spent=0), k=2)
    assert len(picks) == 3 and all(e == Effort.SCOUT for _, e in picks)  # breadth = 전원

@pytest.mark.asyncio
async def test_second_round_top_k_by_score():
    qs = [_q("a", value_est=0.2), _q("b", value_est=0.9), _q("c", value_est=0.5)]
    b = Budgeter(global_token_cap=10000)
    await b.select(FakeLedger(qs), k=3)          # 1라운드 소진
    picks = await b.select(FakeLedger(qs), k=2)  # 2라운드
    ids = [q.id for q, _ in picks]
    assert ids == ["b", "c"]                      # score 내림차순 상위 2

@pytest.mark.asyncio
async def test_should_stop_on_global_cap():
    b = Budgeter(global_token_cap=1000)
    assert await b.should_stop(FakeLedger([_q("a")], spent=1000)) is True

@pytest.mark.asyncio
async def test_should_stop_when_all_below_floor():
    b = Budgeter(global_token_cap=10000, score_floor=0.05)
    # confidence 1.0 → base 0, aging 0(첫 판정) → score 0 < floor
    assert await b.should_stop(FakeLedger([_q("a", confidence=1.0)], spent=0)) is True
