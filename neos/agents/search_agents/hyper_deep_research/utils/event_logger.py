"""Real-time event logging for deep research progress tracking.

Provides event logging to database and optional CLI output for
streaming progress updates to clients.
"""

from typing import Dict, Any, Optional, Callable
from enum import Enum
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DetailedEventType(str, Enum):
    """Detailed event types for granular progress tracking."""

    # Phase events
    PHASE_STARTED = "phase_started"
    PHASE_PROGRESS = "phase_progress"
    PHASE_COMPLETED = "phase_completed"

    # Data collection events
    QUERY_GENERATED = "query_generated"
    QUERY_EXECUTING = "query_executing"
    QUERY_COMPLETED = "query_completed"
    SOURCES_COLLECTED = "sources_collected"

    # LLM events
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"

    # Analysis events
    ANALYSIS_ITERATION = "analysis_iteration"
    GAP_IDENTIFIED = "gap_identified"
    CRITICISM_FEEDBACK = "criticism_feedback"

    # Progress tracking
    PROGRESS_UPDATE = "progress_update"
    STATUS_MESSAGE = "status_message"


class EventCategory(str, Enum):
    """Event categories for grouping related events."""

    PHASE = "phase"
    DATA_COLLECTION = "data_collection"
    LLM = "llm"
    ANALYSIS = "analysis"
    PROGRESS = "progress"
    STATUS = "status"


class ResearchEventLogger:
    """Real-time event logger for deep research progress.

    Logs events to database for SSE streaming and optionally
    prints formatted output to CLI.

    Example:
        logger = ResearchEventLogger(report_id="report_123", enable_cli_output=True)
        await logger.log_phase_start(1, "Topic Analysis")
        await logger.log_query_execution("quantum computing", 1, 5)
    """

    def __init__(
        self,
        report_id: str,
        enable_cli_output: bool = False,
        cli_callback: Optional[Callable[[str], None]] = None
    ):
        """Initialize event logger.

        Args:
            report_id: Research report ID
            enable_cli_output: Whether to print events to CLI
            cli_callback: Optional callback function for CLI output
        """
        self.report_id = report_id
        self.enable_cli_output = enable_cli_output
        self.cli_callback = cli_callback
        self.sequence_counter = 0
        self.db_manager = None

        # Initialize DB manager lazily
        self._init_db_manager()

    def _init_db_manager(self) -> None:
        """Initialize database manager with lazy loading."""
        try:
            from neos.database.connection import db_manager
            self.db_manager = db_manager
            logger.debug(f"[EventLogger] Initialized for report {self.report_id}")
        except ImportError as e:
            logger.warning(f"[EventLogger] DB manager not available: {e}")
            self.db_manager = None

    async def log_event(
        self,
        event_type: DetailedEventType,
        event_category: EventCategory,
        event_data: Dict[str, Any]
    ) -> bool:
        """Log event to database and optionally to CLI.

        Args:
            event_type: Type of event
            event_category: Category of event
            event_data: Event-specific data

        Returns:
            True if event was logged successfully
        """
        self.sequence_counter += 1

        try:
            # Log to database
            if self.db_manager:
                await self._log_to_db(event_type, event_category, event_data)
            else:
                logger.debug(f"[EventLogger] DB not available, skipping DB log")

            # Log to CLI if enabled
            if self.enable_cli_output:
                self._print_to_cli(event_type, event_data)

            return True

        except Exception as e:
            logger.error(f"[EventLogger] Failed to log event: {e}")
            return False

    async def _log_to_db(
        self,
        event_type: DetailedEventType,
        event_category: EventCategory,
        event_data: Dict[str, Any]
    ) -> None:
        """Save event to database.

        Args:
            event_type: Type of event
            event_category: Category of event
            event_data: Event-specific data
        """
        query = """
            INSERT INTO hyper_research_events
            (report_id, event_type, event_category, sequence_number, event_data)
            VALUES ($1, $2, $3, $4, $5)
        """

        try:
            await self.db_manager.execute(
                query,
                self.report_id,
                event_type.value,
                event_category.value,
                self.sequence_counter,
                event_data  # Pass dict directly for JSONB - asyncpg handles conversion
            )
            logger.debug(
                f"[EventLogger] Logged event #{self.sequence_counter}: {event_type.value}"
            )
        except Exception as e:
            logger.error(f"[EventLogger] DB insert failed: {e}")
            # Don't raise - we want to continue even if DB logging fails

    def _print_to_cli(
        self,
        event_type: DetailedEventType,
        event_data: Dict[str, Any]
    ) -> None:
        """Print formatted event to CLI.

        Args:
            event_type: Type of event
            event_data: Event-specific data
        """
        # Event icons for visual feedback
        icons = {
            DetailedEventType.PHASE_STARTED: "🚀",
            DetailedEventType.PHASE_COMPLETED: "✅",
            DetailedEventType.QUERY_EXECUTING: "🔍",
            DetailedEventType.QUERY_COMPLETED: "✓",
            DetailedEventType.SOURCES_COLLECTED: "📚",
            DetailedEventType.LLM_CALL_STARTED: "🤖",
            DetailedEventType.LLM_CALL_COMPLETED: "✓",
            DetailedEventType.PROGRESS_UPDATE: "📊",
            DetailedEventType.STATUS_MESSAGE: "ℹ️",
            DetailedEventType.ANALYSIS_ITERATION: "🔬",
            DetailedEventType.GAP_IDENTIFIED: "🎯",
        }

        icon = icons.get(event_type, "•")
        message = self._format_event_message(event_type, event_data)

        output = f"{icon} {message}"

        if self.cli_callback:
            self.cli_callback(output)
        else:
            print(output)

    def _format_event_message(
        self,
        event_type: DetailedEventType,
        event_data: Dict[str, Any]
    ) -> str:
        """Format event data into human-readable message.

        Args:
            event_type: Type of event
            event_data: Event-specific data

        Returns:
            Formatted message string
        """
        if event_type == DetailedEventType.PHASE_STARTED:
            return f"Phase {event_data.get('phase_number')}/8: {event_data.get('phase_name')}"

        elif event_type == DetailedEventType.PHASE_COMPLETED:
            duration = event_data.get('duration_ms', 0) / 1000
            return f"Phase {event_data.get('phase_number')} completed ({duration:.1f}s)"

        elif event_type == DetailedEventType.QUERY_EXECUTING:
            query = event_data.get('query', '')
            batch = event_data.get('batch', 0)
            total = event_data.get('total_batches', 0)
            return f"Searching [{batch}/{total}]: {query[:60]}..."

        elif event_type == DetailedEventType.SOURCES_COLLECTED:
            count = event_data.get('sources_count', 0)
            total = event_data.get('total_sources', 0)
            return f"Collected {count} sources (Total: {total})"

        elif event_type == DetailedEventType.LLM_CALL_STARTED:
            purpose = event_data.get('purpose', '')
            return f"Analyzing: {purpose}"

        elif event_type == DetailedEventType.PROGRESS_UPDATE:
            pct = event_data.get('percentage', 0)
            msg = event_data.get('message', '')
            return f"Progress: {pct:.0f}% - {msg}"

        elif event_type == DetailedEventType.STATUS_MESSAGE:
            return event_data.get('message', '')

        elif event_type == DetailedEventType.GAP_IDENTIFIED:
            gap = event_data.get('gap', '')
            return f"Gap identified: {gap}"

        else:
            # Generic fallback
            return json.dumps(event_data)

    # ========== Convenience Methods ==========

    async def log_phase_start(
        self,
        phase_number: int,
        phase_name: str,
        details: Optional[str] = None
    ) -> bool:
        """Log phase start event.

        Args:
            phase_number: Phase number (1-8)
            phase_name: Human-readable phase name
            details: Optional additional details

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.PHASE_STARTED,
            EventCategory.PHASE,
            {
                "phase_number": phase_number,
                "phase_name": phase_name,
                "details": details,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_phase_complete(
        self,
        phase_number: int,
        phase_name: str,
        duration_ms: Optional[int] = None
    ) -> bool:
        """Log phase completion event.

        Args:
            phase_number: Phase number (1-8)
            phase_name: Human-readable phase name
            duration_ms: Optional phase duration in milliseconds

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.PHASE_COMPLETED,
            EventCategory.PHASE,
            {
                "phase_number": phase_number,
                "phase_name": phase_name,
                "duration_ms": duration_ms,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_query_execution(
        self,
        query: str,
        batch_num: int,
        total_batches: int
    ) -> bool:
        """Log query execution event.

        Args:
            query: Search query being executed
            batch_num: Current batch number
            total_batches: Total number of batches

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.QUERY_EXECUTING,
            EventCategory.DATA_COLLECTION,
            {
                "query": query,
                "batch": batch_num,
                "total_batches": total_batches,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_sources_collected(
        self,
        sources_count: int,
        total_sources: int,
        batch_num: Optional[int] = None
    ) -> bool:
        """Log sources collected event.

        Args:
            sources_count: Number of sources in this batch
            total_sources: Total sources collected so far
            batch_num: Optional batch number

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.SOURCES_COLLECTED,
            EventCategory.DATA_COLLECTION,
            {
                "sources_count": sources_count,
                "total_sources": total_sources,
                "batch": batch_num,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_llm_call(
        self,
        phase: str,
        purpose: str,
        estimated_tokens: Optional[int] = None
    ) -> bool:
        """Log LLM call start event.

        Args:
            phase: Research phase name
            purpose: Purpose of LLM call
            estimated_tokens: Optional estimated token count

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.LLM_CALL_STARTED,
            EventCategory.LLM,
            {
                "phase": phase,
                "purpose": purpose,
                "estimated_tokens": estimated_tokens,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_llm_complete(
        self,
        phase: str,
        purpose: str,
        actual_tokens: Optional[int] = None
    ) -> bool:
        """Log LLM call completion event.

        Args:
            phase: Research phase name
            purpose: Purpose of LLM call
            actual_tokens: Optional actual token count

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.LLM_CALL_COMPLETED,
            EventCategory.LLM,
            {
                "phase": phase,
                "purpose": purpose,
                "actual_tokens": actual_tokens,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_progress(
        self,
        completed: int,
        total: int,
        message: str
    ) -> bool:
        """Log progress update event.

        Args:
            completed: Number of items completed
            total: Total number of items
            message: Progress message

        Returns:
            True if logged successfully
        """
        percentage = (completed / total * 100) if total > 0 else 0

        return await self.log_event(
            DetailedEventType.PROGRESS_UPDATE,
            EventCategory.PROGRESS,
            {
                "completed": completed,
                "total": total,
                "percentage": percentage,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_status_message(
        self,
        message: str,
        category: str = "info"
    ) -> bool:
        """Log status message event.

        Args:
            message: Status message
            category: Message category (info, success, warning, error)

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.STATUS_MESSAGE,
            EventCategory.STATUS,
            {
                "message": message,
                "category": category,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_gap_identified(
        self,
        gap: str,
        priority: str = "medium"
    ) -> bool:
        """Log knowledge gap identification event.

        Args:
            gap: Identified knowledge gap
            priority: Gap priority (low, medium, high)

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.GAP_IDENTIFIED,
            EventCategory.ANALYSIS,
            {
                "gap": gap,
                "priority": priority,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def log_analysis_iteration(
        self,
        iteration: int,
        total_iterations: int,
        focus: str
    ) -> bool:
        """Log analysis iteration event.

        Args:
            iteration: Current iteration number
            total_iterations: Total number of iterations
            focus: Focus of this iteration

        Returns:
            True if logged successfully
        """
        return await self.log_event(
            DetailedEventType.ANALYSIS_ITERATION,
            EventCategory.ANALYSIS,
            {
                "iteration": iteration,
                "total_iterations": total_iterations,
                "focus": focus,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
