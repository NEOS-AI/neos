from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel, IntentType

from .approval import build_mission_approval_request
from .models import (
    Mission,
    MissionPlan,
    MissionStatus,
    MissionTask,
    MissionType,
    RiskLevel,
    ValidationContract,
)


AGENT_CAPABILITY_MAP = {
    "knowledge_search": "knowledge_search",
    "realtime_info_search": "web_search",
    "realtime_data_search": "web_search",
    "multi_query_search": "web_search",
    "web_lookup": "web_search",
    "deep_research": "deep_research",
    "comparative_analysis": "comparative_analysis",
    "data_analysis": "complex_analysis",
    "file_processing": "file_processing",
    "image_generation": "generation",
    "api_call": "external_action",
    "task_creation": "generation",
}


class MissionPlanner:
    async def plan(self, state: Dict[str, Any]) -> Dict[str, Any]:
        mission_id = f"mission-{uuid.uuid4()}"
        raw_autonomy_level = state.get("autonomy_level")
        if raw_autonomy_level is None:
            raw_autonomy_level = AutonomyLevel.ASSISTED.value
        autonomy_level = int(raw_autonomy_level)
        mission_type = self._mission_type_for_state(state)
        status = (
            MissionStatus.AWAITING_APPROVAL
            if autonomy_level == AutonomyLevel.MANUAL.value
            else MissionStatus.PLANNED
        )

        plan = self._build_plan(mission_id, state)
        contract = self._build_contract(mission_id, state, plan)
        mission = Mission(
            mission_id=mission_id,
            session_id=state.get("session_id", ""),
            user_id=state.get("user_id", ""),
            original_query=state.get("original_query", ""),
            intent=state.get("query_intent", ""),
            autonomy_level=autonomy_level,
            status=status,
            mission_type=mission_type,
            plan_hash=plan.plan_hash(),
            validation_contract_hash=contract.contract_hash(),
        )

        result = {
            "mission_id": mission_id,
            "mission": mission.to_state(),
            "mission_plan": plan.to_state(),
            "validation_contract": contract.to_state(),
            "mission_status": status.value,
            "mission_task_results": [],
            "validator_runs": [],
            "validation_summary": None,
        }

        if status == MissionStatus.AWAITING_APPROVAL:
            result.update(
                {
                    "pending_approvals": [
                        build_mission_approval_request(
                            mission_id=mission_id,
                            plan=plan.to_state(),
                            contract=contract.to_state(),
                            timeout_seconds=getattr(
                                settings, "APPROVAL_TIMEOUT_SECONDS", 300
                            ),
                        )
                    ],
                    "approval_decision": None,
                }
            )
        return result

    def _build_plan(self, mission_id: str, state: Dict[str, Any]) -> MissionPlan:
        agents = list(_dedupe(state.get("required_agents") or []))
        tasks: List[MissionTask] = []
        previous_task_id: str | None = None
        intent_capability = self._intent_capability_for_state(state)

        if intent_capability:
            task_id = "task-1"
            tasks.append(
                MissionTask(
                    task_id=task_id,
                    mission_id=mission_id,
                    description=self._description_for_capability(intent_capability),
                    required_capability=intent_capability,
                    suggested_agent=None,
                    inputs={"query": state.get("original_query", "")},
                    depends_on=[],
                    expected_output_type=self._output_type_for_capability(
                        intent_capability
                    ),
                    expected_artifact=self._artifact_for_capability(intent_capability),
                    risk_level=RiskLevel.LOW,
                )
            )
            previous_task_id = task_id
        else:
            for idx, agent in enumerate(agents, start=1):
                capability = AGENT_CAPABILITY_MAP.get(agent)
                if not capability:
                    continue
                task_id = f"task-{idx}"
                tasks.append(
                    MissionTask(
                        task_id=task_id,
                        mission_id=mission_id,
                        description=self._description_for_capability(capability),
                        required_capability=capability,
                        suggested_agent=agent,
                        inputs={"query": state.get("original_query", "")},
                        depends_on=[previous_task_id] if previous_task_id else [],
                        expected_output_type=self._output_type_for_capability(
                            capability
                        ),
                        expected_artifact=self._artifact_for_capability(capability),
                        risk_level=RiskLevel.MEDIUM
                        if capability == "external_action"
                        else RiskLevel.LOW,
                    )
                )
                previous_task_id = task_id

        if not tasks:
            tasks.append(
                MissionTask(
                    task_id="task-1",
                    mission_id=mission_id,
                    description="Run the selected workflow path",
                    required_capability="generation",
                    suggested_agent=None,
                    inputs={"query": state.get("original_query", "")},
                    depends_on=[],
                    expected_output_type="workflow_result",
                    expected_artifact="draft answer",
                    risk_level=RiskLevel.LOW,
                )
            )
            previous_task_id = "task-1"

        integration_task_id = f"task-{len(tasks) + 1}"
        tasks.append(
            MissionTask(
                task_id=integration_task_id,
                mission_id=mission_id,
                description="Integrate worker outputs into a final answer",
                required_capability="result_integration",
                suggested_agent=None,
                inputs={},
                depends_on=[previous_task_id] if previous_task_id else [],
                expected_output_type="final_response",
                expected_artifact="mission-ready response",
                risk_level=RiskLevel.LOW,
            )
        )

        return MissionPlan(
            mission_id=mission_id,
            objective=state.get("original_query", ""),
            assumptions=["Mission Runtime v1 executes tasks serially."],
            constraints=["Do not replace the legacy workflow path."],
            tasks=tasks,
            execution_policy={"mode": "serial"},
            budget={"max_tasks": len(tasks), "max_repair_attempts": 1},
            timeout=300,
            user_visible_summary=self._summary_for_tasks(tasks),
        )

    def _build_contract(
        self, mission_id: str, state: Dict[str, Any], plan: MissionPlan
    ) -> ValidationContract:
        capabilities = {task.required_capability for task in plan.tasks}
        requires_sources = bool(
            capabilities
            & {
                "web_search",
                "knowledge_search",
                "deep_research",
                "recursive",
                "hyper_deep",
            }
        )
        is_comparison = "comparative_analysis" in capabilities or "compare" in (
            state.get("original_query", "").lower()
        )

        criteria = [
            "Address the original user objective.",
            "Include the outputs from completed mission tasks.",
        ]
        if requires_sources:
            criteria.append("Use enough source material for the requested depth.")
        if is_comparison:
            criteria.append("Include a comparison-oriented synthesis.")

        return ValidationContract(
            contract_id=f"contract-{uuid.uuid4()}",
            mission_id=mission_id,
            success_criteria=criteria,
            required_sources=3 if requires_sources else 0,
            freshness_requirement="current" if requires_sources else None,
            citation_requirement="major_claims" if requires_sources else None,
            factuality_checks=["Avoid unsupported factual claims."],
            coverage_checks=["Cover every named subject in the request."],
            artifact_checks=[],
            safety_checks=[],
            min_quality_score=0.8,
            allowed_repair_attempts=1,
            failure_policy="return_partial",
        )

    def _mission_type_for_state(self, state: Dict[str, Any]) -> MissionType:
        intent = state.get("query_intent")
        if intent == IntentType.RECURSIVE_RESEARCH.value:
            return MissionType.RECURSIVE
        if intent == IntentType.HYPER_DEEP_RESEARCH.value:
            return MissionType.HYPER_DEEP
        if "file_processing" in (state.get("required_agents") or []):
            return MissionType.ARTIFACT
        return MissionType.STANDARD

    def _intent_capability_for_state(self, state: Dict[str, Any]) -> str | None:
        intent = state.get("query_intent")
        if intent == IntentType.RECURSIVE_RESEARCH.value:
            return "recursive"
        if intent == IntentType.HYPER_DEEP_RESEARCH.value:
            return "hyper_deep"
        return None

    def _description_for_capability(self, capability: str) -> str:
        descriptions = {
            "web_search": "Collect current source material",
            "knowledge_search": "Search internal knowledge",
            "deep_research": "Run deep research",
            "recursive": "Run recursive research orchestration",
            "hyper_deep": "Run HyperDeep research orchestration",
            "comparative_analysis": "Compare findings across subjects",
            "complex_analysis": "Analyze gathered evidence",
            "file_processing": "Extract relevant artifact information",
            "generation": "Generate requested content",
            "external_action": "Prepare external action result",
        }
        return descriptions.get(capability, f"Run {capability}")

    def _output_type_for_capability(self, capability: str) -> str:
        if capability in {"web_search", "knowledge_search", "deep_research"}:
            return "search_results"
        if capability in {"comparative_analysis", "complex_analysis"}:
            return "analysis_results"
        if capability in {"recursive", "hyper_deep"}:
            return "workflow_result"
        return "generation_results"

    def _artifact_for_capability(self, capability: str) -> str:
        if capability in {"web_search", "knowledge_search", "deep_research"}:
            return "source-backed findings"
        if capability in {"comparative_analysis", "complex_analysis"}:
            return "analysis findings"
        if capability in {"recursive", "hyper_deep"}:
            return "recursive research result"
        return "generated artifact"

    def _summary_for_tasks(self, tasks: List[MissionTask]) -> str:
        labels = [task.description for task in tasks]
        return " -> ".join(labels)


def _dedupe(values: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        yield value
