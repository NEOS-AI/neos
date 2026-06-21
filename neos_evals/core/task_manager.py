"""Task manager for loading and storing evaluation tasks.

This module provides functionality to:
- Load tasks from JSON files
- Save tasks to JSON files
- List available tasks by category
- Validate task definitions
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

from .task import EvalTask

logger = logging.getLogger(__name__)


TASK_CATEGORIES = [
    "factual",
    "comparative",
    "controversial",
    "regression",
    "harness_calibration",
]


class TaskManager:
    """Manager for evaluation tasks.

    Handles loading, saving, and organizing evaluation tasks from
    the filesystem.

    Attributes:
        tasks_dir: Root directory containing task files
        _tasks: Cache of loaded tasks

    Example:
        ```python
        manager = TaskManager("tasks/")

        # Load all tasks
        all_tasks = manager.load_all()

        # Load tasks from a category
        factual_tasks = manager.load_category("factual")

        # Load a specific task
        task = manager.load_task("factual/fact_001.json")

        # Save a new task
        manager.save_task(task, "factual")
        ```
    """

    def __init__(self, tasks_dir: str = "tasks"):
        """Initialize task manager.

        Args:
            tasks_dir: Directory containing task files
        """
        self.tasks_dir = Path(tasks_dir)
        self._tasks: Dict[str, EvalTask] = {}

        # Ensure tasks directory exists
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

        # Create category subdirectories
        for category in TASK_CATEGORIES:
            (self.tasks_dir / category).mkdir(exist_ok=True)

    def load_task(self, task_path: str) -> Optional[EvalTask]:
        """Load a single task from file.

        Args:
            task_path: Path to task JSON file (relative to tasks_dir)

        Returns:
            EvalTask instance or None if loading fails
        """
        full_path = self.tasks_dir / task_path

        if not full_path.exists():
            logger.error(f"Task file not found: {full_path}")
            return None

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            task = EvalTask.from_dict(data)

            # Validate task
            errors = task.validate()
            if errors:
                logger.error(f"Task validation failed: {errors}")
                return None

            # Cache task
            self._tasks[task.task_id] = task
            logger.info(f"Loaded task: {task.name} ({task.task_id})")

            return task

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load task: {e}")
            return None

    def load_category(self, category: str) -> List[EvalTask]:
        """Load all tasks from a category.

        Args:
            category: Category name (factual, comparative, etc.)

        Returns:
            List of loaded tasks
        """
        category_dir = self.tasks_dir / category

        if not category_dir.exists():
            logger.warning(f"Category directory not found: {category}")
            return []

        tasks = []
        for task_file in category_dir.glob("*.json"):
            relative_path = task_file.relative_to(self.tasks_dir)
            task = self.load_task(str(relative_path))
            if task:
                tasks.append(task)

        logger.info(f"Loaded {len(tasks)} tasks from category '{category}'")
        return tasks

    def load_all(self) -> List[EvalTask]:
        """Load all tasks from all categories.

        Returns:
            List of all loaded tasks
        """
        all_tasks = []

        for category in TASK_CATEGORIES:
            category_tasks = self.load_category(category)
            all_tasks.extend(category_tasks)

        logger.info(f"Loaded {len(all_tasks)} total tasks")
        return all_tasks

    def save_task(
        self,
        task: EvalTask,
        category: Optional[str] = None
    ) -> bool:
        """Save a task to file.

        Args:
            task: Task to save
            category: Category directory (uses task.category if None)

        Returns:
            True if saved successfully, False otherwise
        """
        # Validate task first
        errors = task.validate()
        if errors:
            logger.error(f"Cannot save invalid task: {errors}")
            return False

        # Determine category
        if category is None:
            category = task.category

        # Create filename from task name
        filename = self._sanitize_filename(task.name) + ".json"
        filepath = self.tasks_dir / category / filename

        try:
            # Ensure category directory exists
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Save to JSON
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, indent=2, ensure_ascii=False)

            # Cache task
            self._tasks[task.task_id] = task

            logger.info(f"Saved task: {task.name} to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to save task: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[EvalTask]:
        """Get a cached task by ID.

        Args:
            task_id: Task ID to retrieve

        Returns:
            Task instance or None if not found
        """
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None
    ) -> List[EvalTask]:
        """List cached tasks with optional filtering.

        Args:
            category: Filter by category
            difficulty: Filter by difficulty

        Returns:
            List of matching tasks
        """
        tasks = list(self._tasks.values())

        if category:
            tasks = [t for t in tasks if t.category == category]

        if difficulty:
            tasks = [t for t in tasks if t.difficulty == difficulty]

        return tasks

    def create_example_task(
        self,
        category: str = "factual",
        difficulty: str = "easy"
    ) -> EvalTask:
        """Create an example task for testing.

        Args:
            category: Task category
            difficulty: Task difficulty

        Returns:
            Example EvalTask instance
        """
        if category == "factual":
            return EvalTask(
                name="Basic Quantum Computing",
                query="What is quantum computing?",
                expected_sections=[
                    "Introduction",
                    "Technical Principles",
                    "Current State",
                    "Applications"
                ],
                required_topics=[
                    "qubits",
                    "superposition",
                    "entanglement",
                    "quantum gates"
                ],
                min_sources=50,
                quality_threshold=0.8,
                graders=[
                    "citation_accuracy",
                    "source_diversity",
                    "structure_completeness",
                    "topic_coverage",
                    "quality_assessment"
                ],
                pass_threshold=0.8,
                difficulty=difficulty,
                category=category,
                description="Basic factual research on quantum computing fundamentals"
            )
        elif category == "comparative":
            return EvalTask(
                name="TensorFlow vs PyTorch",
                query="Compare TensorFlow and PyTorch for deep learning",
                expected_sections=[
                    "Introduction",
                    "TensorFlow Overview",
                    "PyTorch Overview",
                    "Feature Comparison",
                    "Performance Comparison",
                    "Use Case Recommendations",
                    "Conclusion"
                ],
                required_topics=[
                    "ease of use",
                    "performance",
                    "community support",
                    "deployment",
                    "debugging"
                ],
                min_sources=80,
                quality_threshold=0.85,
                graders=[
                    "citation_accuracy",
                    "source_diversity",
                    "structure_completeness",
                    "topic_coverage",
                    "quality_assessment"
                ],
                pass_threshold=0.85,
                difficulty=difficulty,
                category=category,
                description="Comparative analysis of two deep learning frameworks"
            )
        else:
            return EvalTask(
                name="Example Task",
                query="Example query",
                category=category,
                difficulty=difficulty
            )

    def _sanitize_filename(self, name: str) -> str:
        """Convert task name to valid filename.

        Args:
            name: Task name

        Returns:
            Sanitized filename (without extension)
        """
        # Replace spaces and special characters
        filename = name.lower()
        filename = filename.replace(" ", "_")
        filename = "".join(c for c in filename if c.isalnum() or c == "_")
        return filename

    def __len__(self) -> int:
        """Get number of cached tasks."""
        return len(self._tasks)

    def __repr__(self) -> str:
        """String representation."""
        return f"TaskManager(tasks_dir='{self.tasks_dir}', cached_tasks={len(self._tasks)})"
