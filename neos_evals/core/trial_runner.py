"""Trial runner for executing evaluation trials.

This module handles the execution of the research agent for evaluation
purposes, including timeout handling, error catching, and transcript
capture.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .task import EvalTask
from .trial import EvalTrial
from .transcript import TranscriptCapture

logger = logging.getLogger(__name__)


class TrialRunner:
    """Executes evaluation trials by running the research agent.

    The TrialRunner:
    - Initializes the agent
    - Executes the query
    - Captures full execution transcript
    - Handles timeouts and errors
    - Records metadata

    Attributes:
        agent_class: The agent class to instantiate
        default_timeout: Default timeout in seconds
        transcript_capture: Transcript capturing system

    Example:
        ```python
        runner = TrialRunner(
            agent_class=HyperDeepResearchAgent,
            default_timeout=900
        )

        trial = EvalTrial(task_id=task.task_id, trial_number=1)
        await runner.execute_trial(task, trial)

        # Trial now contains results
        print(trial.final_report)
        print(trial.metadata)
        ```
    """

    def __init__(
        self,
        agent_class: Any,
        default_timeout: int = 900,
        enable_transcript: bool = True
    ):
        """Initialize trial runner.

        Args:
            agent_class: Agent class to instantiate (e.g., HyperDeepResearchAgent)
            default_timeout: Default timeout in seconds (15 minutes)
            enable_transcript: Whether to capture full transcript
        """
        self.agent_class = agent_class
        self.default_timeout = default_timeout
        self.enable_transcript = enable_transcript
        self.transcript_capture = TranscriptCapture() if enable_transcript else None

    async def execute_trial(
        self,
        task: EvalTask,
        trial: EvalTrial,
        timeout: Optional[int] = None
    ) -> EvalTrial:
        """Execute a single trial.

        Args:
            task: The evaluation task
            trial: The trial instance to populate
            timeout: Override timeout in seconds

        Returns:
            The trial instance with results populated
        """
        # Mark trial as started
        trial.start()

        # Use task-specific or default timeout
        timeout_seconds = timeout or task.estimated_runtime or self.default_timeout

        logger.info(
            f"Starting trial {trial.trial_number} for task '{task.name}' "
            f"(timeout: {timeout_seconds}s)"
        )

        try:
            # Execute with timeout
            await asyncio.wait_for(
                self._run_agent(task, trial),
                timeout=timeout_seconds
            )

            # Mark as completed
            trial.complete()
            logger.info(
                f"Trial {trial.trial_number} completed successfully "
                f"({trial.duration_seconds:.1f}s)"
            )

        except asyncio.TimeoutError:
            trial.timeout()
            logger.error(
                f"Trial {trial.trial_number} timed out after {timeout_seconds}s"
            )

        except Exception as e:
            trial.fail(error=str(e))
            logger.error(
                f"Trial {trial.trial_number} failed: {e}",
                exc_info=True
            )

        return trial

    async def _run_agent(
        self,
        task: EvalTask,
        trial: EvalTrial
    ) -> None:
        """Run the agent and capture results.

        Args:
            task: Evaluation task
            trial: Trial to populate with results
        """
        # Initialize agent
        agent = self.agent_class()

        # Start transcript capture if enabled
        if self.transcript_capture:
            self.transcript_capture.start_capture(trial.trial_id)

        try:
            # Prepare context
            context = {
                "eval_mode": True,
                "eval_task_id": task.task_id,
                "eval_trial_id": trial.trial_id,
                "session_id": trial.trial_id,
                "user_id": "eval_system",
            }

            # Execute agent
            logger.info(f"Executing agent with query: {task.query[:100]}...")
            result = await agent.execute(
                query=task.query,
                context=context
            )

            # Extract results
            trial.final_report = result.get("report", "")
            trial.metadata = result.get("metadata", {})

            # Capture transcript
            if self.transcript_capture:
                trial.transcript = self.transcript_capture.get_capture(trial.trial_id)

            logger.info(
                f"Agent execution complete. "
                f"Report length: {len(trial.final_report)} chars"
            )

        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            raise

        finally:
            # Stop transcript capture
            if self.transcript_capture:
                self.transcript_capture.stop_capture(trial.trial_id)

    async def execute_multiple_trials(
        self,
        task: EvalTask,
        num_trials: int = 3,
        timeout: Optional[int] = None
    ) -> list[EvalTrial]:
        """Execute multiple trials for pass@k evaluation.

        Args:
            task: The evaluation task
            num_trials: Number of trials to run
            timeout: Optional timeout override

        Returns:
            List of completed trials
        """
        trials = []

        for trial_num in range(1, num_trials + 1):
            trial = EvalTrial(
                task_id=task.task_id,
                trial_number=trial_num
            )

            await self.execute_trial(task, trial, timeout)
            trials.append(trial)

            # Log progress
            logger.info(
                f"Completed trial {trial_num}/{num_trials} for task '{task.name}'"
            )

        return trials

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent being evaluated.

        Returns:
            Dictionary with agent metadata
        """
        try:
            agent = self.agent_class()
            return {
                "agent_class": self.agent_class.__name__,
                "agent_name": getattr(agent, "name", "unknown"),
                "search_type": getattr(agent, "search_type", "unknown"),
            }
        except Exception as e:
            logger.warning(f"Could not get agent info: {e}")
            return {
                "agent_class": self.agent_class.__name__,
                "error": str(e)
            }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"TrialRunner("
            f"agent={self.agent_class.__name__}, "
            f"timeout={self.default_timeout}s)"
        )
