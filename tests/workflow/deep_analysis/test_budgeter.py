import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort

pytestmark = pytest.mark.no_db


def _q(**kw):
    base = dict(id="q1", confidence=0.0, value_est=1.0, spent_tokens=0,
                cap_tokens=2000, fail_streak=0, depth=1, status="open")
    base.update(kw)
    return SimpleNamespace(**base)

def test_gain_decay_buckets():
    b = Budgeter()
    assert b.gain_decay([2, 3]) == 1.0
    assert b.gain_decay([1, 1]) == 0.6
    assert b.gain_decay([0, 0]) == 0.3
    assert b.gain_decay([]) == 1.0

def test_ladder_fail_streak_forces_split():
    b = Budgeter()
    assert b.ladder(_q(fail_streak=2)) == Effort.SPLIT

def test_ladder_cap_exhausted_forces_split():
    b = Budgeter()
    assert b.ladder(_q(spent_tokens=2000, cap_tokens=2000)) == Effort.SPLIT

def test_ladder_low_confidence_after_scout_digs():
    b = Budgeter()
    assert b.ladder(_q(confidence=0.2, spent_tokens=500)) == Effort.DIG

def test_ladder_default_scout():
    b = Budgeter()
    assert b.ladder(_q()) == Effort.SCOUT

def test_aging_increases_with_rounds():
    b = Budgeter(aging_per_round=0.05)
    b._round = 4
    assert abs(b.aging("never_selected") - 0.20) < 1e-9
    b._last_selected["q1"] = 2
    assert abs(b.aging("q1") - 0.10) < 1e-9
