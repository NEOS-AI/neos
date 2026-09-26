import pytest

from neos.univer.safety import (
    BINDING_ACTIONS,
    SUCCESS_ARTIFACT_STATUS,
    SUCCESS_HARNESS_VERDICT,
    binding_error,
    policy_binding_denied,
    quoted_json_is_handoff,
)

pytestmark = pytest.mark.no_db


def test_publish_send_email_denied() -> None:
    for action in ("publish", "send", "email"):
        assert action in BINDING_ACTIONS
        assert policy_binding_denied(action) is True
        assert binding_error(action) == {
            "error": "policy_binding_denied",
            "action": action,
        }


def test_merge_trunk_and_worktree_denied() -> None:
    assert policy_binding_denied("merge_trunk") is True
    assert policy_binding_denied("merge_worktree") is True


def test_xlsx_export_mcp_pro_denied() -> None:
    for action in ("xlsx_export", "mcp_univer_ai", "register_pro_license"):
        assert policy_binding_denied(action) is True


def test_inspect_and_save_are_not_binding() -> None:
    assert policy_binding_denied("univer.inspect.v1") is False
    assert policy_binding_denied("univer.save.v1") is False
    assert policy_binding_denied("write_file.v1") is False


def test_success_is_staged_for_signoff() -> None:
    assert SUCCESS_ARTIFACT_STATUS == "staged_for_signoff"
    assert SUCCESS_HARNESS_VERDICT == "pass"


def test_quoted_json_is_never_a_handoff() -> None:
    assert quoted_json_is_handoff('{"action": "publish"}') is False
