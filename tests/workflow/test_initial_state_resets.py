"""턴 리셋 필드 (spec 2026-10-13 §4.3, S-PEND). 이어받은 승인이 다음 턴을 막지 않는다."""

import pytest

pytestmark = pytest.mark.no_db


def test_approval_fields_are_turn_scoped() -> None:
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow.__new__(MultiAgentWorkflow)
    state = workflow._create_initial_state({"user_id": "u", "session_id": "s", "query": "q"})
    assert state["pending_approvals"] == []
    assert state["approval_decision"] is None
