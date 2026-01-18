"""Example usage of the NEOS Evaluation Framework.

This script demonstrates:
1. Loading tasks
2. Registering graders
3. Creating the orchestrator
4. Running evaluations (commented out - requires Phase 3+)
"""

import asyncio
import logging
from pathlib import Path

from core import TaskManager, TrialRunner, EvaluationOrchestrator
from graders import GraderRegistry
from graders.code_based import register_all_code_graders
from graders.model_based import register_all_model_graders

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Main example function."""
    logger.info("=" * 60)
    logger.info("NEOS Evaluation Framework - Example Usage")
    logger.info("=" * 60)

    # ========== Step 1: Initialize Task Manager ==========
    logger.info("\n[Step 1] Initializing Task Manager...")

    tasks_dir = Path(__file__).parent / "tasks"
    task_manager = TaskManager(str(tasks_dir))

    # Load all tasks
    all_tasks = task_manager.load_all()
    logger.info(f"✓ Loaded {len(all_tasks)} tasks")

    # Show task breakdown
    by_category = {}
    for task in all_tasks:
        by_category[task.category] = by_category.get(task.category, 0) + 1

    for category, count in by_category.items():
        logger.info(f"  - {category}: {count} tasks")

    # ========== Step 2: Register Graders ==========
    logger.info("\n[Step 2] Registering Graders...")

    registry = GraderRegistry()

    # Register code-based graders (deterministic, fast)
    register_all_code_graders(registry)
    logger.info(f"✓ Registered {len(registry)} code-based graders")

    # Register model-based graders (LLM-powered, subjective)
    register_all_model_graders(registry)
    logger.info(f"✓ Registered {len(registry)} total graders")

    logger.info("\nAll graders:")
    for grader in registry.list_all():
        logger.info(f"  - {grader.grader_id} ({grader.grader_type}, weight={grader.weight})")

    # Show grader weights by type
    weights = registry.get_weights()
    total_weight = sum(weights.values())

    code_weight = sum(g.weight for g in registry.get_by_type("code"))
    model_weight = sum(g.weight for g in registry.get_by_type("model"))

    logger.info(f"\nWeight distribution:")
    logger.info(f"  - Code-based: {code_weight:.2f} ({code_weight/total_weight*100:.0f}%)")
    logger.info(f"  - Model-based: {model_weight:.2f} ({model_weight/total_weight*100:.0f}%)")
    logger.info(f"  - Total: {total_weight:.2f}")

    # ========== Step 3: Initialize Trial Runner ==========
    logger.info("\n[Step 3] Initializing Trial Runner...")

    # NOTE: Uncomment when ready to run actual evaluations
    # from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent
    #
    # trial_runner = TrialRunner(
    #     agent_class=HyperDeepResearchAgent,
    #     default_timeout=900  # 15 minutes
    # )
    # logger.info(f"✓ Trial runner ready: {trial_runner}")

    logger.info("⚠ Trial runner not initialized (uncomment code to enable)")

    # ========== Step 4: Create Orchestrator ==========
    logger.info("\n[Step 4] Creating Evaluation Orchestrator...")

    # NOTE: Uncomment when ready to run
    # orchestrator = EvaluationOrchestrator(
    #     task_manager=task_manager,
    #     trial_runner=trial_runner,
    #     grader_registry=registry
    # )
    # logger.info(f"✓ Orchestrator ready: {orchestrator}")

    logger.info("⚠ Orchestrator not created (requires trial runner)")

    # ========== Step 5: Run Example Evaluation ==========
    logger.info("\n[Step 5] Running Example Evaluation...")
    logger.info("⚠ Evaluation execution requires Phase 2+ implementation")
    logger.info("⚠ Uncomment the code below when ready to run actual evaluations\n")

    # Example: Evaluate a single task
    # ─────────────────────────────────
    # task = all_tasks[0]  # First task
    # logger.info(f"Evaluating task: {task.name}")
    #
    # result = await orchestrator.evaluate_task(
    #     task=task,
    #     num_trials=3  # Run 3 trials for pass@3
    # )
    #
    # logger.info(f"Results:")
    # logger.info(f"  pass@3: {result['metrics']['pass_at_k']:.2f}")
    # logger.info(f"  pass^3: {result['metrics']['pass_all_k']:.2f}")
    # logger.info(f"  avg_score: {result['metrics']['avg_score']:.2f}")

    # Example: Evaluate all regression tasks
    # ────────────────────────────────────────
    # logger.info("\nEvaluating all regression tasks...")
    # results = await orchestrator.evaluate_all(
    #     num_trials=3,
    #     categories=["regression"]
    # )
    #
    # # Get summary
    # summary = orchestrator.get_summary(results)
    # logger.info(f"\nSummary:")
    # logger.info(f"  Total tasks: {summary['total_tasks']}")
    # logger.info(f"  Successful: {summary['successful_tasks']}")
    # logger.info(f"  Failed: {summary['failed_tasks']}")
    # logger.info(f"  Avg pass@k: {summary['avg_pass_at_k']:.2f}")

    logger.info("\n" + "=" * 60)
    logger.info("Example complete! Next steps:")
    logger.info("1. Implement model-based graders (Phase 3)")
    logger.info("2. Uncomment evaluation code above")
    logger.info("3. Run: python example_usage.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
