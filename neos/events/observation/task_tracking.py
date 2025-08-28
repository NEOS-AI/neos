from dataclasses import dataclass, field
from typing import Any

from neos.core.schema import ObservationType
from neos.events.observation.observation import Observation


@dataclass
class TaskTrackingObservation(Observation):
    """This data class represents the result of a task tracking operation."""

    observation: str = ObservationType.TASK_TRACKING
    command: str = ''
    task_list: list[dict[str, Any]] = field(default_factory=list)

    @property
    def message(self) -> str:
        return self.content
