"""Workflow package public exports.

Heavy graph dependencies are loaded lazily so lightweight submodules such as
`neos.workflow.enums` can be imported without initializing agents and tools.
"""

from .state import AgentState, WorkflowConfig

__all__ = [
    "MultiAgentWorkflow",
    "multi_agent_workflow",
    "AgentState",
    "WorkflowConfig",
    "SearchOrchestrator",
    "AnalysisOrchestrator",
    "GenerationOrchestrator",
    "ResultProcessor",
    "QualityValidator",
    "ResponseGenerator",
    "QueryClassifier",
    "ContentProcessor",
]


def __getattr__(name: str):
    if name in {"MultiAgentWorkflow", "multi_agent_workflow"}:
        from .graph import MultiAgentWorkflow, multi_agent_workflow

        return {
            "MultiAgentWorkflow": MultiAgentWorkflow,
            "multi_agent_workflow": multi_agent_workflow,
        }[name]

    if name in {"SearchOrchestrator", "AnalysisOrchestrator", "GenerationOrchestrator"}:
        from .orchestrators import (
            AnalysisOrchestrator,
            GenerationOrchestrator,
            SearchOrchestrator,
        )

        return {
            "SearchOrchestrator": SearchOrchestrator,
            "AnalysisOrchestrator": AnalysisOrchestrator,
            "GenerationOrchestrator": GenerationOrchestrator,
        }[name]

    if name in {"ResultProcessor", "QualityValidator", "ResponseGenerator"}:
        from .processors import QualityValidator, ResponseGenerator, ResultProcessor

        return {
            "ResultProcessor": ResultProcessor,
            "QualityValidator": QualityValidator,
            "ResponseGenerator": ResponseGenerator,
        }[name]

    if name in {"QueryClassifier", "ContentProcessor"}:
        from .utils import ContentProcessor, QueryClassifier

        return {
            "QueryClassifier": QueryClassifier,
            "ContentProcessor": ContentProcessor,
        }[name]

    raise AttributeError(f"module 'neos.workflow' has no attribute {name!r}")
