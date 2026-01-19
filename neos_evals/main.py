"""NEOS Evaluation Framework CLI.

Command-line interface for running evaluations of the NEOS
Hyper Deep Research Agent.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Create CLI app
app = typer.Typer(
    name="neos-eval",
    help="Evaluation framework for NEOS Hyper Deep Research Agent",
    add_completion=False
)

console = Console()


@app.command()
def create_example_tasks(
    output_dir: str = typer.Option(
        "tasks/",
        "--output-dir",
        "-o",
        help="Directory to save example tasks"
    ),
    num_tasks: int = typer.Option(
        5,
        "--num",
        "-n",
        help="Number of example tasks to create"
    )
):
    """Create example evaluation tasks for testing."""
    from core.task_manager import TaskManager

    console.print("[bold blue]Creating example tasks...[/bold blue]")

    task_manager = TaskManager(output_dir)

    # Create example tasks
    categories = ["factual", "comparative"]
    tasks_created = 0

    for i in range(num_tasks):
        category = categories[i % len(categories)]
        difficulty = "easy" if i < 2 else "medium"

        task = task_manager.create_example_task(category, difficulty)
        task.name = f"{task.name} {i+1}"

        if task_manager.save_task(task, category):
            tasks_created += 1
            console.print(f"  ✓ Created: {task.name} ({category}/{difficulty})")

    console.print(f"\n[bold green]Created {tasks_created} example tasks in {output_dir}[/bold green]")


@app.command()
def list_tasks(
    tasks_dir: str = typer.Option(
        "tasks/",
        "--tasks-dir",
        "-t",
        help="Directory containing task files"
    ),
    category: Optional[str] = typer.Option(
        None,
        "--category",
        "-c",
        help="Filter by category"
    )
):
    """List available evaluation tasks."""
    from core.task_manager import TaskManager

    task_manager = TaskManager(tasks_dir)

    # Load tasks
    if category:
        tasks = task_manager.load_category(category)
        console.print(f"[bold blue]Tasks in category '{category}':[/bold blue]\n")
    else:
        tasks = task_manager.load_all()
        console.print("[bold blue]All tasks:[/bold blue]\n")

    if not tasks:
        console.print("[yellow]No tasks found[/yellow]")
        return

    # Create table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Difficulty", style="yellow")
    table.add_column("Min Sources", justify="right")
    table.add_column("Graders", justify="right")

    for task in tasks:
        table.add_row(
            task.name,
            task.category,
            task.difficulty,
            str(task.min_sources),
            str(len(task.graders))
        )

    console.print(table)
    console.print(f"\n[bold]Total: {len(tasks)} tasks[/bold]")


@app.command()
def info():
    """Show information about the evaluation framework."""
    console.print("\n[bold cyan]NEOS Evaluation Framework[/bold cyan]\n")

    console.print("[bold]Version:[/bold] 0.1.0")
    console.print("[bold]Purpose:[/bold] Automated evaluation of NEOS Hyper Deep Research Agent\n")

    console.print("[bold blue]Phase 1 (Core Infrastructure) - Complete:[/bold blue]")
    console.print("  ✓ Task management system")
    console.print("  ✓ Trial execution engine")
    console.print("  ✓ Grader framework")
    console.print("  ✓ Transcript capture")
    console.print("  ✓ Orchestration layer\n")

    console.print("[bold yellow]Next Steps:[/bold yellow]")
    console.print("  → Phase 2: Implement code-based graders")
    console.print("  → Phase 3: Implement model-based graders")
    console.print("  → Phase 4: Create task dataset")
    console.print("  → Phase 5: Build analytics dashboard\n")


@app.command()
def run(
    task_name: Optional[str] = typer.Argument(
        None,
        help="Name of specific task to run (runs all if not specified)"
    ),
    tasks_dir: str = typer.Option(
        "tasks/",
        "--tasks-dir",
        "-t",
        help="Directory containing task files"
    ),
    trials: int = typer.Option(
        3,
        "--trials",
        "-n",
        help="Number of trials to run per task"
    )
):
    """Run evaluation(s).

    NOTE: This command requires Phase 2+ implementation (graders).
    """
    console.print("[bold red]ERROR:[/bold red] Evaluation execution not yet implemented")
    console.print("This requires graders from Phase 2+")
    console.print("\nCurrent status: Phase 1 (Core Infrastructure) complete")
    console.print("Next: Implement graders in Phase 2")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
