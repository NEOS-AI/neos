from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import CachePolicy

from neos.prompts.planner_model import StepType

from .types import State
from .nodes import (
    coordinator_node,
    planner_node,
    reporter_node,
    research_team_node,
    researcher_node,
    coder_node,
    human_feedback_node,
    background_investigation_node,
    react_coder_node,
)


def continue_to_running_research_team(state: State) -> str:
    """
    Determine the next node based on the current state of the research team.
    If the current plan is empty or all steps are executed, continue to planner.
    If there are incomplete steps, return the first incomplete step's type.

    Args:
        state (State): The current state of the workflow.

    Returns:
        str: The next node to transition to.
    """
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        return "planner"

    if all(step.execution_res for step in current_plan.steps):
        return "planner"

    # Find first incomplete step
    incomplete_step = None
    for step in current_plan.steps:
        if not step.execution_res:
            incomplete_step = step
            break

    if not incomplete_step:
        return "planner"

    if incomplete_step.step_type == StepType.RESEARCH:
        return "researcher"
    if incomplete_step.step_type == StepType.PROCESSING:
        return "coder"
    if incomplete_step.step_type == StepType.WEB_FE_CODING:
        return "react_coder"
    return "planner"


def _build_base_graph(use_cache: bool = False, cache_ttl: int = 3) -> StateGraph:
    """
    Build and return the base state graph with all nodes and edges.
    This graph includes the coordinator, planner, reporter, research team,
    researcher, coder, human feedback, and background investigation nodes.
    It defines the workflow for handling user queries and coordinating tasks
    among different roles in the agent system.

    Args:
        use_cache (bool): If True, enables caching for the graph.
        cache_ttl (int): Time-to-live for the cache in seconds.

    Returns:
        StateGraph: The constructed state graph with all nodes and edges.
    """
    config_map = {}
    if use_cache:
        config_map['cache_policy'] = CachePolicy(ttl=cache_ttl)

    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")
    builder.add_node("coordinator", coordinator_node, **config_map)
    builder.add_node("background_investigator", background_investigation_node, **config_map)
    builder.add_node("planner", planner_node, **config_map)
    builder.add_node("reporter", reporter_node, **config_map)
    builder.add_node("research_team", research_team_node, **config_map)
    builder.add_node("researcher", researcher_node, **config_map)
    builder.add_node("coder", coder_node, **config_map)
    builder.add_node("react_coder", react_coder_node, **config_map)
    builder.add_node("human_feedback", human_feedback_node, **config_map)
    builder.add_edge("background_investigator", "planner")
    builder.add_conditional_edges(
        "research_team",
        continue_to_running_research_team,
        ["planner", "researcher", "coder", "react_coder"],
    )
    builder.add_edge("reporter", END)
    return builder


def build_graph_with_memory():
    """Build and return the agent workflow graph with memory."""
    # use persistent memory to save conversation history
    # TODO: be compatible with SQLite / PostgreSQL
    memory = MemorySaver()

    # build state graph
    builder = _build_base_graph()
    return builder.compile(checkpointer=memory)


def build_graph():
    """Build and return the agent workflow graph without memory."""
    # build state graph
    builder = _build_base_graph()
    return builder.compile()


if __name__ == "__main__":
    # This is just for testing purposes, not used in production
    graph = build_graph()
    print("Graph built successfully.")
