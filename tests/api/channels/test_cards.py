import pytest

from neos.api.channels.cards import (
    ACTION_APPROVE,
    ACTION_DENY,
    ACTION_STOP,
    coding_actions,
    coding_blocks,
    command_for_action,
    parse_action_payload,
)

pytestmark = pytest.mark.no_db


def test_waiting_approval_status_renders_approve_deny_and_stop() -> None:
    blocks = coding_blocks("ct_1 waiting_approval ca_9")
    assert blocks is not None
    actions = [item for item in blocks if item["type"] == "actions"][0]["elements"]
    ids = [item["action_id"] for item in actions]
    assert ids == [ACTION_STOP, ACTION_APPROVE, ACTION_DENY]
    assert command_for_action(ACTION_APPROVE, "ca_9") == "/approve ca_9"
    assert command_for_action(ACTION_DENY, "ca_9") == "/deny ca_9"
    assert command_for_action(ACTION_STOP, "ct_1") == "/stop"


def test_ask_user_waiting_approval_omits_approve() -> None:
    blocks = coding_blocks("ct_1 waiting_approval ca_9 ask_user.v1")
    assert blocks is not None
    actions = [item for item in blocks if item["type"] == "actions"][0]["elements"]
    ids = [item["action_id"] for item in actions]
    assert ids == [ACTION_STOP, ACTION_DENY]


def test_coding_actions_match_slack_block_ids() -> None:
    actions = coding_actions("Started coding task ct_1")
    assert [item.action_id for item in actions] == [ACTION_STOP, "neos_code_status"]
    assert parse_action_payload("neos_code_stop:ct_1") == (ACTION_STOP, "ct_1")
    assert parse_action_payload("neos_code_approve:ca_9") == (ACTION_APPROVE, "ca_9")


def test_started_card_does_not_pretend_to_be_an_approval() -> None:
    blocks = coding_blocks("Started coding task ct_1")
    assert blocks is not None
    actions = [item for item in blocks if item["type"] == "actions"][0]["elements"]
    assert [item["action_id"] for item in actions] == [
        ACTION_STOP,
        "neos_code_status",
    ]
