from datetime import UTC, datetime

import pytest

from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditStatus,
)


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _edit(
    *,
    status: WorkspaceEditStatus,
    resulting_revision: str | None = "13",
    committed_at: datetime | None = NOW,
    applied_checkpoint_id: str | None = None,
) -> CodingWorkspaceEdit:
    return CodingWorkspaceEdit(
        edit_id="cwe_1",
        task_id="ct_1",
        run_id="cr_1",
        path="src/app.py",
        base_revision="12",
        resulting_revision=resulting_revision,
        status=status,
        content_digest="sha256:abc",
        content_bytes=6,
        created_at=NOW,
        committed_at=committed_at,
        applied_checkpoint_id=applied_checkpoint_id,
    )


def test_committed_workspace_edit_is_pending_agent_sync() -> None:
    assert _edit(status=WorkspaceEditStatus.COMMITTED).pending_agent_sync is True


def test_applied_edit_requires_checkpoint_identity() -> None:
    with pytest.raises(ValueError, match="applied checkpoint"):
        _edit(status=WorkspaceEditStatus.APPLIED)


def test_prepared_edit_cannot_have_resulting_revision() -> None:
    with pytest.raises(ValueError, match="prepared edit"):
        _edit(
            status=WorkspaceEditStatus.PREPARED,
            committed_at=None,
        )


def test_committed_edit_requires_revision_and_commit_time() -> None:
    with pytest.raises(ValueError, match="committed edit"):
        _edit(
            status=WorkspaceEditStatus.COMMITTED,
            resulting_revision=None,
            committed_at=None,
        )


def test_workspace_edit_rejects_negative_content_size() -> None:
    with pytest.raises(ValueError, match="content bytes"):
        CodingWorkspaceEdit(
            edit_id="cwe_1",
            task_id="ct_1",
            run_id="cr_1",
            path="src/app.py",
            base_revision="12",
            resulting_revision=None,
            status=WorkspaceEditStatus.PREPARED,
            content_digest="sha256:abc",
            content_bytes=-1,
            created_at=NOW,
            committed_at=None,
            applied_checkpoint_id=None,
        )
