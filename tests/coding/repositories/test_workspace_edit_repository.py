from datetime import UTC, datetime

from neos.coding.repositories.workspace_edit_repository import (
    PostgresWorkspaceEditRepository,
)


NOW = datetime(2026, 7, 23, tzinfo=UTC)


class Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


class Session:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def begin(self):
        return self

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.results.pop(0) if self.results else None)


def factory(session: Session):
    async def create_session():
        return session

    return create_session


def edit_row(status: str = "prepared", revision=None, committed_at=None):
    return (
        "cwe_1",
        "ct_1",
        "cr_1",
        "src/app.py",
        "12",
        revision,
        status,
        "sha256:abc",
        9,
        NOW,
        committed_at,
        None,
    )


async def test_prepare_locks_canonical_run_and_persists_intent_only() -> None:
    session = Session([("cr_1",), edit_row()])
    repository = PostgresWorkspaceEditRepository(factory(session))

    result = await repository.prepare_edit(
        task_id="ct_1",
        run_id="cr_1",
        edit_id="cwe_1",
        path="src/app.py",
        base_revision="12",
        digest="sha256:abc",
        content_bytes=9,
        now=NOW,
    )

    queries = "\n".join(call[0] for call in session.calls)
    assert "status = 'running'" in queries
    assert "FOR UPDATE" in queries
    assert "INSERT INTO coding_workspace_edits" in queries
    assert "INSERT INTO coding_events" not in queries
    assert result.edit.status.value == "prepared"


async def test_commit_writes_public_event_and_outbox_in_same_transaction() -> None:
    committed = edit_row("committed", "13", NOW)
    session = Session([edit_row(), (7,), committed, None, None])
    repository = PostgresWorkspaceEditRepository(factory(session))

    result = await repository.commit_edit(
        edit_id="cwe_1", resulting_revision="13", now=NOW
    )

    queries = "\n".join(call[0] for call in session.calls)
    assert "FOR UPDATE" in queries
    assert "UPDATE coding_tasks" in queries
    assert "INSERT INTO coding_events" in queries
    assert "INSERT INTO coding_event_outbox" in queries
    assert result.event is not None
    assert result.event.type == "workspace.user_edit.applied"
    assert "content_digest" not in result.event.payload
