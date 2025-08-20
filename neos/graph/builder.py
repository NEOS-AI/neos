from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
import logging

from neos.prompts.planner_model import StepType

from .nodes import (
    background_investigation_node,
    casual_chat_node,
    coder_node,
    coordinator_node,
    human_feedback_node,
    planner_node,
    reporter_node,
    research_team_node,
    researcher_node,
)
from .types import State


logger = logging.getLogger(__name__)


def continue_to_running_research_team(state: State) -> str:
    logger.info("Checking if research team should continue running")
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        logger.info("No current plan or steps found, continuing to planner")
        return "planner"

    if all(step.execution_res for step in current_plan.steps):
        logger.info("All steps in the current plan are completed, continuing to planner")
        return "planner"

    # Find first incomplete step
    incomplete_step = None
    for step in current_plan.steps:
        if not step.execution_res:
            incomplete_step = step
            break

    if not incomplete_step:
        logger.info("No incomplete steps found, continuing to planner")
        return "planner"

    if incomplete_step.step_type == StepType.RESEARCH:
        logger.info("Incompleted step is research, continuing to researcher")
        return "researcher"
    if incomplete_step.step_type == StepType.PROCESSING:
        logger.info("Incompleted step is processing, continuing to coder")
        return "coder"

    logger.info("Incompleted step is not research or processing, continuing to planner")
    return "planner"


def _build_base_graph():
    """Build and return the base state graph with all nodes and edges."""
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")
    builder.add_node("coordinator", coordinator_node)

    # Add nodes for deep research
    builder.add_node("background_investigator", background_investigation_node)
    builder.add_node("planner", planner_node)
    builder.add_node("reporter", reporter_node)
    builder.add_node("research_team", research_team_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("human_feedback", human_feedback_node)

    # Add casual chat node
    builder.add_node("casual_chat", casual_chat_node)  # 새로 추가

    # Define edges between nodes for the deep research workflow
    builder.add_edge("background_investigator", "planner")
    builder.add_conditional_edges(
        "research_team",
        continue_to_running_research_team,
        ["planner", "researcher", "coder"],
    )
    builder.add_edge("reporter", END)

    # Add edges for casual chat
    builder.add_edge("casual_chat", END)

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


graph = build_graph()
