import pytest
from neos.subagent.metrics import _spec

pytestmark = pytest.mark.no_db


def test_fsi_alias_does_not_fold_to_explore() -> None:
    assert _spec({"spec": "kyc-doc-reader"}) == "kyc-doc-reader"
    assert _spec({"spec": "kyc-rules-engine"}) == "kyc-rules-engine"
    assert _spec({"spec": "kyc-escalator"}) == "kyc-escalator"
    assert _spec({"spec": "fsi-reader"}) == "fsi-reader"
    assert _spec({"spec": "explore"}) == "explore"
