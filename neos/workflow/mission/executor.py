from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Optional


SEARCH_CAPABILITIES = {"web_search", "knowledge_search", "deep_research"}
ANALYSIS_CAPABILITIES = {"comparative_analysis", "complex_analysis"}
GENERATION_CAPABILITIES = {"generation", "file_processing", "external_action"}


class MissionExecutor:
    def __init__(
        self,
        *,
        search_orchestrator: Any,
        analysis_orchestrator: Any,
        generation_orchestrator: Any,
        recursive_orchestrator: Callable[[], Optional[Any]],
        hyper_deep_orchestrator: Callable[[], Optional[Any]],
    ) -> None:
        self.search_orchestrator = search_orchestrator
        self.analysis_orchestrator = analysis_orchestrator
        self.generation_orchestrator = generation_orchestrator
        self.recursive_orchestrator = recursive_orchestrator
        self.hyper_deep_orchestrator = hyper_deep_orchestrator

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        plan = state.get("mission_plan") or {}
        tasks = plan.get("tasks") or []
        merged_state = dict(state)
        task_results = list(state.get("mission_task_results") or [])
        failed_task_ids: set[str] = set()

        for task in tasks:
            task_id = task.get("task_id")
            capability = task.get("required_capability", "")
            depends_on = task.get("depends_on") or []

            if any(dep in failed_task_ids for dep in depends_on):
                task_results.append(
                    {
                        "task_id": task_id,
                        "status": "skipped",
                        "capability": capability,
                        "result_ref": None,
                        "error": "dependency_failed",
                    }
                )
                continue

            try:
                node_result = await self._run_task(task, merged_state)
                self._merge_state(merged_state, node_result)
                task_results.append(
                    {
                        "task_id": task_id,
                        "status": "completed",
                        "capability": capability,
                        "result_ref": self._result_ref_for_capability(capability),
                        "error": None,
                    }
                )
            except Exception as exc:
                failed_task_ids.add(task_id)
                errors = list(merged_state.get("errors") or [])
                errors.append(str(exc))
                merged_state["errors"] = errors
                task_results.append(
                    {
                        "task_id": task_id,
                        "status": "failed",
                        "capability": capability,
                        "result_ref": None,
                        "error": str(exc),
                    }
                )

        merged_state["mission_task_results"] = task_results
        merged_state["mission_status"] = "partial" if failed_task_ids else "completed"
        return merged_state

    async def _run_task(
        self, task: Dict[str, Any], state: Dict[str, Any]
    ) -> Dict[str, Any]:
        capability = task.get("required_capability", "")
        task_state = deepcopy(state)
        suggested_agent = task.get("suggested_agent")
        if suggested_agent:
            task_state["required_agents"] = [suggested_agent]

        if capability in SEARCH_CAPABILITIES:
            return await self.search_orchestrator.orchestrate(task_state)
        if capability in ANALYSIS_CAPABILITIES:
            return await self.analysis_orchestrator.orchestrate(task_state)
        if capability in GENERATION_CAPABILITIES:
            return await self.generation_orchestrator.orchestrate(task_state)
        if capability == "recursive":
            orchestrator = self.recursive_orchestrator()
            if orchestrator is None:
                raise RuntimeError("recursive orchestrator unavailable")
            return await orchestrator.execute(task_state)
        if capability == "hyper_deep":
            orchestrator = self.hyper_deep_orchestrator()
            if orchestrator is None:
                raise RuntimeError("hyper deep orchestrator unavailable")
            return await orchestrator.execute(task_state)
        return {}

    def _merge_state(self, state: Dict[str, Any], result: Dict[str, Any]) -> None:
        for key, value in (result or {}).items():
            if key in {
                "search_results",
                "analysis_results",
                "generation_results",
                "execution_steps",
                "errors",
            }:
                existing = list(state.get(key) or [])
                returned = list(value or [])
                if returned[: len(existing)] == existing:
                    state[key] = existing + returned[len(existing) :]
                else:
                    state[key] = existing + returned
            else:
                state[key] = value

    def _result_ref_for_capability(self, capability: str) -> str:
        if capability in SEARCH_CAPABILITIES:
            return "search_results"
        if capability in ANALYSIS_CAPABILITIES:
            return "analysis_results"
        if capability in GENERATION_CAPABILITIES:
            return "generation_results"
        return "workflow_state"
