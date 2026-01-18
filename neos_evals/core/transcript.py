"""Transcript capture system for recording agent execution.

This module provides functionality to capture and store detailed
execution logs (transcripts) of agent runs for later analysis.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TranscriptEvent:
    """Single event in the execution transcript.

    Attributes:
        timestamp: When the event occurred
        event_type: Type of event (phase_start, phase_end, llm_call, error, etc.)
        phase: Which research phase (if applicable)
        data: Event-specific data
        message: Human-readable message
    """

    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    phase: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "phase": self.phase,
            "data": self.data,
            "message": self.message,
        }


class TranscriptCapture:
    """Captures detailed execution transcripts of agent runs.

    The transcript includes:
    - Phase start/end events
    - LLM API calls
    - Search queries
    - Data collection events
    - Errors and warnings
    - Timing information

    Example:
        ```python
        capture = TranscriptCapture()

        # Start capturing for a trial
        capture.start_capture("trial_123")

        # Log events
        capture.log_event(
            trial_id="trial_123",
            event_type="phase_start",
            phase="data_collection",
            message="Starting data collection phase"
        )

        # Get the captured transcript
        transcript = capture.get_capture("trial_123")

        # Stop capturing
        capture.stop_capture("trial_123")
        ```
    """

    def __init__(self):
        """Initialize transcript capture."""
        self._captures: Dict[str, List[TranscriptEvent]] = {}
        self._active: Dict[str, bool] = {}

    def start_capture(self, trial_id: str) -> None:
        """Start capturing events for a trial.

        Args:
            trial_id: ID of trial to capture
        """
        self._captures[trial_id] = []
        self._active[trial_id] = True

        self.log_event(
            trial_id=trial_id,
            event_type="capture_start",
            message="Started transcript capture"
        )

        logger.debug(f"Started transcript capture for trial {trial_id}")

    def stop_capture(self, trial_id: str) -> None:
        """Stop capturing events for a trial.

        Args:
            trial_id: ID of trial to stop
        """
        if trial_id in self._active:
            self._active[trial_id] = False

        self.log_event(
            trial_id=trial_id,
            event_type="capture_stop",
            message="Stopped transcript capture"
        )

        logger.debug(f"Stopped transcript capture for trial {trial_id}")

    def log_event(
        self,
        trial_id: str,
        event_type: str,
        phase: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        message: str = ""
    ) -> None:
        """Log an event to the transcript.

        Args:
            trial_id: ID of trial
            event_type: Type of event
            phase: Optional research phase
            data: Optional event data
            message: Human-readable message
        """
        if trial_id not in self._captures:
            logger.warning(f"Trial {trial_id} not found in captures")
            return

        event = TranscriptEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            phase=phase,
            data=data or {},
            message=message
        )

        self._captures[trial_id].append(event)

    def get_capture(self, trial_id: str) -> Dict[str, Any]:
        """Get the captured transcript for a trial.

        Args:
            trial_id: ID of trial

        Returns:
            Dictionary containing transcript data
        """
        if trial_id not in self._captures:
            logger.warning(f"Trial {trial_id} not found in captures")
            return {}

        events = self._captures[trial_id]

        return {
            "trial_id": trial_id,
            "total_events": len(events),
            "events": [event.to_dict() for event in events],
            "summary": self._generate_summary(events)
        }

    def _generate_summary(self, events: List[TranscriptEvent]) -> Dict[str, Any]:
        """Generate a summary of transcript events.

        Args:
            events: List of transcript events

        Returns:
            Summary dictionary
        """
        if not events:
            return {}

        # Calculate timing
        start_time = events[0].timestamp
        end_time = events[-1].timestamp
        duration = (end_time - start_time).total_seconds()

        # Count event types
        event_types = {}
        for event in events:
            event_types[event.event_type] = event_types.get(event.event_type, 0) + 1

        # Extract phases
        phases = list(set(event.phase for event in events if event.phase))

        return {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "total_events": len(events),
            "event_type_counts": event_types,
            "phases": phases,
        }

    def clear_capture(self, trial_id: str) -> None:
        """Clear captured data for a trial.

        Args:
            trial_id: ID of trial to clear
        """
        if trial_id in self._captures:
            del self._captures[trial_id]

        if trial_id in self._active:
            del self._active[trial_id]

        logger.debug(f"Cleared transcript capture for trial {trial_id}")

    def clear_all(self) -> None:
        """Clear all captured transcripts."""
        self._captures.clear()
        self._active.clear()
        logger.debug("Cleared all transcript captures")

    def get_active_trials(self) -> List[str]:
        """Get list of currently active trial captures.

        Returns:
            List of trial IDs with active captures
        """
        return [
            trial_id
            for trial_id, active in self._active.items()
            if active
        ]

    def __len__(self) -> int:
        """Get number of captured transcripts."""
        return len(self._captures)

    def __repr__(self) -> str:
        """String representation."""
        active_count = len(self.get_active_trials())
        return f"TranscriptCapture(captures={len(self._captures)}, active={active_count})"
