from dataclasses import dataclass

from neos.coding.domain.events import CodingEvent


@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    outbox_id: str
    event: CodingEvent
    attempt_count: int
