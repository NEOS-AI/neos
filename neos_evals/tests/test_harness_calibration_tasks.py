from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.task_manager import TaskManager


def test_harness_calibration_tasks_load():
    manager = TaskManager(Path("neos_evals/tasks"))
    tasks = manager.load_category("harness_calibration")

    assert {task.metadata["expected_failure"] for task in tasks} == {
        "factuality",
        "source_count",
        "bias_perspective",
        "performance_budget",
    }
