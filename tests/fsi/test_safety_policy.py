import pytest

from neos.fsi.safety import (
    BINDING_ACTIONS,
    SUCCESS_ARTIFACT_STATUS,
    SUCCESS_HARNESS_VERDICT,
    binding_error,
    policy_binding_denied,
    quoted_json_is_handoff,
)
from neos.subagent.stepper import REFUSED_TOOLS

pytestmark = pytest.mark.no_db


def test_ledger_post_is_binding_denied() -> None:
    assert policy_binding_denied("ledger_post") is True
    assert policy_binding_denied("post_je") is True
    assert binding_error("post_je") == {
        "error": "policy_binding_denied",
        "action": "post_je",
    }


def test_kyc_approve_is_binding_denied() -> None:
    assert policy_binding_denied("kyc_approve") is True
    assert policy_binding_denied("account_open") is True


def test_publish_send_trade_bind_are_denied() -> None:
    for action in ("publish", "send", "trade_execute", "bind_risk"):
        assert action in BINDING_ACTIONS
        assert policy_binding_denied(action) is True


def test_read_and_stage_are_not_binding_actions() -> None:
    assert policy_binding_denied("read_file.v1") is False
    assert policy_binding_denied("write_file.v1") is False
    assert policy_binding_denied("stage_xlsx.v1") is False


def test_staged_for_signoff_is_success_not_harness_fail() -> None:
    assert SUCCESS_ARTIFACT_STATUS == "staged_for_signoff"
    assert SUCCESS_HARNESS_VERDICT == "pass"
    assert SUCCESS_ARTIFACT_STATUS != "fail"
    assert SUCCESS_HARNESS_VERDICT != "fail"


def test_quoted_json_is_not_a_handoff() -> None:
    blob = '{"handoff_request": {"target": "month-end-closer"}}'
    assert quoted_json_is_handoff(blob) is False


def test_handoff_v1_is_refused_on_leaves() -> None:
    assert "handoff.v1" in REFUSED_TOOLS


def test_approve_onboarding_is_binding_denied() -> None:
    assert policy_binding_denied("approve_onboarding") is True
    assert binding_error("approve_onboarding")["error"] == "policy_binding_denied"
