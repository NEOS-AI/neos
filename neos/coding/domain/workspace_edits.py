from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.domain.events import CodingEvent


class WorkspaceEditStatus(StrEnum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    RECONCILE_REQUIRED = "reconcile_required"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class CodingWorkspaceEdit:
    edit_id: str
    task_id: str
    run_id: str
    path: str
    base_revision: str
    resulting_revision: str | None
    status: WorkspaceEditStatus
    content_digest: str
    content_bytes: int
    created_at: datetime
    committed_at: datetime | None
    applied_checkpoint_id: str | None

    def __post_init__(self) -> None:
        if not all(
            (
                self.edit_id,
                self.task_id,
                self.run_id,
                self.path,
                self.base_revision,
                self.content_digest,
            )
        ):
            raise ValueError("workspace edit identities are required")
        if self.content_bytes < 0:
            raise ValueError("workspace edit content bytes cannot be negative")
        if self.status is WorkspaceEditStatus.PREPARED and (
            self.resulting_revision is not None
            or self.committed_at is not None
            or self.applied_checkpoint_id is not None
        ):
            raise ValueError("prepared edit cannot have commit state")
        if self.status in {
            WorkspaceEditStatus.COMMITTED,
            WorkspaceEditStatus.APPLIED,
        } and (
            self.resulting_revision is None or self.committed_at is None
        ):
            raise ValueError(
                "committed edit requires resulting revision and commit time"
            )
        if (
            self.status is WorkspaceEditStatus.APPLIED
            and not self.applied_checkpoint_id
        ):
            raise ValueError("applied checkpoint is required")
        if (
            self.status is not WorkspaceEditStatus.APPLIED
            and self.applied_checkpoint_id is not None
        ):
            raise ValueError("only applied edits can reference a checkpoint")

    @property
    def pending_agent_sync(self) -> bool:
        return self.status is WorkspaceEditStatus.COMMITTED


@dataclass(frozen=True, slots=True)
class WorkspaceEditCommit:
    edit: CodingWorkspaceEdit
    event: CodingEvent | None
    created: bool


class WorkspaceEditConflict(RuntimeError):
    pass
