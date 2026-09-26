import pytest
from neos.subagent.metrics import _spec

pytestmark = pytest.mark.no_db


def test_univer_reader_spec_label_is_kept() -> None:
    assert _spec({"spec": "univer-reader"}) == "univer-reader"
    assert _spec({"spec": "univer-writer"}) == "univer-writer"
    assert _spec({"spec": "univer-critic"}) == "univer-critic"
    assert _spec({"spec": "univer-formula"}) == "univer-formula"


def test_unknown_univer_kebab_folds_to_explore() -> None:
    assert _spec({"spec": "univer-session-reader"}) == "explore"
    assert _spec({"spec": "univer_reader"}) == "explore"
