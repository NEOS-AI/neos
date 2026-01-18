"""Evaluation orchestrator - main entry point for running evaluations.

This module provides the main orchestrator that coordinates:
- Loading tasks
- Running trials
- Executing graders
- Calculating metrics
- Storing results
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .task import EvalTask
from .trial import EvalTrial
from .task_manager import TaskManager
from .trial_runner import TrialRunner

# Import GraderRegistry with try/except for both relative and absolute imports
try:
    from ..graders.registry import GraderRegistry
except ImportError:
    from graders.registry import GraderRegistry

logger = logging.getLogger(__name__)


class EvaluationOrchestrator:
    """Main orchestrator for the evaluation framework.

    Coordinates the entire evaluation pipeline:
    1. Load evaluation tasks
    2. Execute trials (run agent)
    3. Grade trials (run graders)
    4. Calculate metrics
    5. Store results

    Attributes:
        task_manager: Manages evaluation tasks
        trial_runner: Executes agent trials
        grader_registry: Registry of graders
        grader_weights: Weights for scoring

    Example:
        ```python
        # Initialize orchestrator
        orchestrator = EvaluationOrchestrator(
            task_manager=TaskManager("tasks/"),
            trial_runner=TrialRunner(HyperDeepResearchAgent),
            grader_registry=registry
        )

        # Run single task evaluation
        result = await orchestrator.evaluate_task(
            task_id="task_123",
            num_trials=3
        )

        # Run full evaluation suite
        results = await orchestrator.evaluate_all()
        ```
    """

    def __init__(
        self,
        task_manager: TaskManager,
        trial_runner: TrialRunner,
        grader_registry: GraderRegistry,
        grader_weights: Optional[Dict[str, float]] = None
    ):
        """Initialize orchestrator.

        Args:
            task_manager: Task manager instance
            trial_runner: Trial runner instance
            grader_registry: Grader registry instance
            grader_weights: Optional custom grader weights
        """
        self.task_manager = task_manager
        self.trial_runner = trial_runner
        self.grader_registry = grader_registry

        # Use provided weights or get from registry
        self.grader_weights = grader_weights or grader_registry.get_weights()

    async def evaluate_task(
        self,
        task: EvalTask,
        num_trials: int = 3,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Evaluate a single task with multiple trials.

        Args:
            task: The evaluation task
            num_trials: Number of trials to run (for pass@k)
            timeout: Optional timeout override

        Returns:
            Dictionary with evaluation results
        """
        logger.info(f"Starting evaluation of task '{task.name}' ({num_trials} trials)")

        # 1. Execute trials
        trials = await self.trial_runner.execute_multiple_trials(
            task=task,
            num_trials=num_trials,
            timeout=timeout
        )

        # 2. Grade each trial
        for trial in trials:
            if trial.status == "completed":
                await self._grade_trial(task, trial)
            else:
                logger.warning(
                    f"Trial {trial.trial_number} not completed "
                    f"(status: {trial.status}), skipping grading"
                )

        # 3. Calculate metrics
        metrics = self._calculate_metrics(task, trials, num_trials)

        # 4. Prepare result
        result = {
            "task_id": task.task_id,
            "task_name": task.name,
            "num_trials": num_trials,
            "trials": [trial.to_dict() for trial in trials],
            "metrics": metrics,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"Evaluation complete for task '{task.name}': "
            f"pass@{num_trials}={metrics['pass_at_k']:.2f}, "
            f"avg_score={metrics['avg_score']:.2f}"
        )

        return result

    async def _grade_trial(
        self,
        task: EvalTask,
        trial: EvalTrial
    ) -> None:
        """Grade a single trial using all specified graders.

        Args:
            task: The evaluation task
            trial: The trial to grade
        """
        logger.info(f"Grading trial {trial.trial_number} for task '{task.name}'")

        # Get graders specified in task
        graders_to_use = []
        for grader_id in task.graders:
            grader = self.grader_registry.get(grader_id)
            if grader:
                graders_to_use.append(grader)
            else:
                logger.warning(f"Grader '{grader_id}' not found in registry")

        if not graders_to_use:
            logger.error("No graders available for this task")
            return

        # Execute all graders
        for grader in graders_to_use:
            try:
                result = await grader.grade_with_timing(task, trial)

                # Add result to trial
                trial.add_grader_result(
                    grader_id=result.grader_id,
                    score=result.score,
                    feedback=result.feedback,
                    details=result.details
                )

                logger.debug(
                    f"Grader '{grader.grader_id}': "
                    f"score={result.score:.2f}, passed={result.passed}"
                )

            except Exception as e:
                logger.error(
                    f"Grader '{grader.grader_id}' failed: {e}",
                    exc_info=True
                )
                # Add failed result
                trial.add_grader_result(
                    grader_id=grader.grader_id,
                    score=0.0,
                    feedback=f"Grader failed: {str(e)}",
                    details={"error": str(e)}
                )

        # Calculate overall score
        trial.calculate_overall_score(self.grader_weights)

        # Check if passed
        trial.check_passed(task.pass_threshold)

        logger.info(
            f"Trial {trial.trial_number} grading complete: "
            f"score={trial.overall_score:.2f}, passed={trial.passed}"
        )

    def _calculate_metrics(
        self,
        task: EvalTask,
        trials: List[EvalTrial],
        k: int
    ) -> Dict[str, Any]:
        """Calculate evaluation metrics from trials.

        Args:
            task: The evaluation task
            trials: List of completed trials
            k: Number of trials (for pass@k)

        Returns:
            Dictionary with calculated metrics
        """
        # Filter completed trials only
        completed_trials = [t for t in trials if t.status == "completed"]

        if not completed_trials:
            return {
                "pass_at_k": 0.0,
                "pass_all_k": 0.0,
                "avg_score": 0.0,
                "completed_trials": 0,
                "failed_trials": len(trials),
            }

        # pass@k: At least one success
        passed_trials = [t for t in completed_trials if t.passed]
        pass_at_k = 1.0 if len(passed_trials) > 0 else 0.0

        # pass^k: All successes
        pass_all_k = 1.0 if len(passed_trials) == len(completed_trials) else 0.0

        # Average score
        avg_score = sum(t.overall_score for t in completed_trials) / len(completed_trials)

        # Per-grader average scores
        grader_avg_scores = {}
        for grader_id in task.graders:
            scores = [
                t.grader_scores.get(grader_id, 0.0)
                for t in completed_trials
                if grader_id in t.grader_scores
            ]
            if scores:
                grader_avg_scores[grader_id] = sum(scores) / len(scores)

        return {
            "pass_at_k": pass_at_k,
            "pass_all_k": pass_all_k,
            "avg_score": avg_score,
            "completed_trials": len(completed_trials),
            "passed_trials": len(passed_trials),
            "failed_trials": len([t for t in trials if t.status == "failed"]),
            "timeout_trials": len([t for t in trials if t.status == "timeout"]),
            "grader_avg_scores": grader_avg_scores,
        }

    async def evaluate_all(
        self,
        num_trials: int = 3,
        categories: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Evaluate all tasks in the task manager.

        Args:
            num_trials: Number of trials per task
            categories: Optional list of categories to evaluate

        Returns:
            List of evaluation results
        """
        # Load tasks
        if categories:
            tasks = []
            for category in categories:
                tasks.extend(self.task_manager.load_category(category))
        else:
            tasks = self.task_manager.load_all()

        if not tasks:
            logger.warning("No tasks found to evaluate")
            return []

        logger.info(f"Starting evaluation of {len(tasks)} tasks")

        # Evaluate each task
        results = []
        for i, task in enumerate(tasks, 1):
            logger.info(f"Evaluating task {i}/{len(tasks)}: {task.name}")

            try:
                result = await self.evaluate_task(task, num_trials)
                results.append(result)

            except Exception as e:
                logger.error(
                    f"Failed to evaluate task '{task.name}': {e}",
                    exc_info=True
                )
                results.append({
                    "task_id": task.task_id,
                    "task_name": task.name,
                    "error": str(e),
                    "status": "failed"
                })

        logger.info(f"Completed evaluation of {len(results)} tasks")

        return results

    def get_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary statistics from evaluation results.

        Args:
            results: List of evaluation results

        Returns:
            Summary dictionary
        """
        if not results:
            return {}

        # Count by status
        successful = [r for r in results if "error" not in r]
        failed = [r for r in results if "error" in r]

        if not successful:
            return {
                "total_tasks": len(results),
                "successful_tasks": 0,
                "failed_tasks": len(failed),
            }

        # Aggregate metrics
        avg_pass_at_k = sum(r["metrics"]["pass_at_k"] for r in successful) / len(successful)
        avg_pass_all_k = sum(r["metrics"]["pass_all_k"] for r in successful) / len(successful)
        avg_score = sum(r["metrics"]["avg_score"] for r in successful) / len(successful)

        return {
            "total_tasks": len(results),
            "successful_tasks": len(successful),
            "failed_tasks": len(failed),
            "avg_pass_at_k": avg_pass_at_k,
            "avg_pass_all_k": avg_pass_all_k,
            "avg_score": avg_score,
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"EvaluationOrchestrator("
            f"tasks={len(self.task_manager)}, "
            f"graders={len(self.grader_registry)})"
        )
