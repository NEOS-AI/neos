from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.domain.events import CodingEvent


class TextPartStatus(StrEnum):
    STREAMING = "streaming"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class CodingTextPart:
    part_id: str
    task_id: str
    run_id: str
    turn_id: str
    first_seq: int
    last_seq: int
    status: TextPartStatus
    content: str
    content_bytes: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not all((self.part_id, self.task_id, self.run_id, self.turn_id)):
            raise ValueError("text part identities are required")
        if self.first_seq < 1 or self.last_seq < self.first_seq:
            raise ValueError("text part sequence range is invalid")
        if self.content_bytes != len(self.content.encode("utf-8")):
            raise ValueError("text part byte count must match content")


@dataclass(frozen=True, slots=True)
class ModelTextPartCommit:
    part: CodingTextPart
    event: CodingEvent
    interrupted_part_ids: tuple[str, ...] = ()


class TextPartConflict(RuntimeError):
    pass
