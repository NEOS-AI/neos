from datetime import datetime

import pytest

from neos.workflow.stream_manager import StreamManager


def test_claim_session_rejects_owner_that_loses_creation_race_without_mutation():
    manager = StreamManager()

    assert manager.get_session("shared") is None
    foreign_session = manager.create_session("shared", "user-b")
    before_connections = foreign_session.active_connections
    before_activity = foreign_session.last_activity

    with pytest.raises(PermissionError):
        manager.claim_session("shared", "user-a")

    assert manager.get_session("shared") is foreign_session
    assert foreign_session.active_connections == before_connections
    assert foreign_session.last_activity == before_activity


def test_claim_session_atomically_creates_and_reuses_only_for_owner():
    manager = StreamManager()

    created = manager.claim_session("owner-session", "owner")
    first_activity = created.last_activity
    reused = manager.claim_session("owner-session", "owner")

    assert reused is created
    assert created.user_id == "owner"
    assert created.active_connections == 2
    assert created.last_activity >= first_activity
