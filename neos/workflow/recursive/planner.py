"""
RecursivePlanner: 하위 태스크 분해기

non-atomic 태스크를 2-N개의 하위 태스크로 분해합니다.
상위 레벨(depth=0)은 Opus, 하위 레벨은 Haiku를 사용합니다.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from neos.config.settings import settings
from neos.utils.llm_factory import LLMFactory

from .models import RecursiveTaskNode, TaskAtomicity, TaskStatus, extract_llm_cost

logger = logging.getLogger(__name__)

_PLANNER_PROMPT = """You are a task decomposition expert. Break down the given complex task into smaller, independently executable sub-tasks.

Rules:
- Create {max_subtasks} or fewer sub-tasks (prefer fewer, more focused sub-tasks)
- Each sub-task should be clearly defined and independently actionable
- Order sub-tasks by dependency (list prerequisites first)
- If sub-task B depends on A, A must come first in the list
- Sub-tasks should collectively cover the full scope of the parent task
- Each sub-task description should be specific and self-contained

Parent task: {description}
Current depth: {depth} (max depth: {max_depth})
Original user query: {original_query}

Return ONLY a valid JSON object:
{{
  "subtasks": [
    {{
      "description": "specific sub-task description",
      "depends_on": []  // list of 0-based indices of sub-tasks this depends on
    }}
  ],
  "reasoning": "brief explanation of decomposition strategy"
}}"""

_REPLAN_PROMPT = """You are a research replanning expert. The previous attempt to answer the task was insufficient.

Original task: {description}
Original user query: {original_query}
Previous attempt result: {previous_result}
Identified gaps: {gaps}

Create a revised set of sub-tasks to address the gaps. Focus specifically on what was missing.

Return ONLY a valid JSON object:
{{
  "subtasks": [
    {{
      "description": "specific sub-task to fill the gap",
      "depends_on": []
    }}
  ],
  "reasoning": "what gaps these sub-tasks address"
}}"""


class RecursivePlanner:
    """하위 태스크 분해기.

    non-atomic 태스크를 2-N개의 하위 RecursiveTaskNode로 분해합니다.
    깊이(depth)에 따라 모델을 선택합니다:
    - depth=0: RECURSIVE_PLANNER_MODEL (Opus)
    - depth>0: RECURSIVE_ATOMIZER_MODEL (Haiku, 비용 절감)
    """

    def __init__(self, max_tasks_per_level: Optional[int] = None):
        self._max_depth = settings.RECURSIVE_MAX_DEPTH
        self._max_tasks_per_level = (
            max_tasks_per_level if max_tasks_per_level is not None
            else settings.RECURSIVE_MAX_TASKS_PER_LEVEL
        )

    def _select_model(self, depth: int) -> str:
        """깊이에 따라 LLM 모델 선택."""
        if depth == 0:
            return settings.RECURSIVE_PLANNER_MODEL
        return settings.RECURSIVE_ATOMIZER_MODEL  # Haiku

    async def decompose(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> List[RecursiveTaskNode]:
        """태스크를 하위 태스크 목록으로 분해.

        Args:
            task: 분해할 부모 태스크
            context: 실행 컨텍스트 (original_query 포함)

        Returns:
            하위 RecursiveTaskNode 목록 (순서: 의존성 순)
        """
        max_subtasks = max(2, self._max_tasks_per_level - task.depth)
        original_query = context.get("original_query", task.description)

        prompt = _PLANNER_PROMPT.format(
            description=task.description,
            depth=task.depth,
            max_depth=self._max_depth,
            max_subtasks=max_subtasks,
            original_query=original_query,
        )

        model = self._select_model(task.depth)
        subtask_dicts, cost = await self._call_llm(prompt, model, task.description)

        # R-01: 비용 누적
        task.cost += cost
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None:
            cost_acc[0] += cost

        if not subtask_dicts:
            # LLM 실패 시 태스크를 2개로 단순 분할
            logger.warning(f"[Planner] LLM failed, using fallback split for: {task.description[:50]}")
            subtask_dicts = self._fallback_split(task.description)

        # R-06: max_subtasks를 전달하여 hard limit 강제 적용
        return self._build_subtask_nodes(task, subtask_dicts, max_subtasks)

    async def replan(
        self,
        task: RecursiveTaskNode,
        previous_result: str,
        gaps: List[str],
        context: Dict[str, Any],
    ) -> List[RecursiveTaskNode]:
        """검증 실패 후 갭을 메우기 위한 재계획.

        Args:
            task: 원본 태스크
            previous_result: 이전 실행 결과
            gaps: 식별된 부족한 부분 목록
            context: 실행 컨텍스트

        Returns:
            갭을 채우기 위한 새로운 하위 태스크 목록
        """
        original_query = context.get("original_query", task.description)
        gaps_str = "\n".join(f"- {g}" for g in gaps)

        prompt = _REPLAN_PROMPT.format(
            description=task.description,
            original_query=original_query,
            previous_result=previous_result[:500],
            gaps=gaps_str,
        )

        model = self._select_model(task.depth)
        subtask_dicts, cost = await self._call_llm(prompt, model, task.description)

        # R-01: 비용 누적 (replan도 부모 task에 비용 합산)
        task.cost += cost
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None:
            cost_acc[0] += cost

        if not subtask_dicts:
            return []

        return self._build_subtask_nodes(task, subtask_dicts)

    async def _call_llm(
        self,
        prompt: str,
        model: str,
        task_description: str,
    ) -> tuple[List[Dict[str, Any]], float]:
        """LLM 호출 및 JSON 파싱. (subtask 목록, 호출 비용 USD) 반환."""
        try:
            provider = "anthropic" if "claude" in model.lower() else settings.LLM_PROVIDER
            llm = LLMFactory.create_llm(
                provider=provider,
                model=model,
                temperature=0.3,
                max_tokens=1500,
            )
            response = await llm.ainvoke(prompt)
            # R-01: 비용 파싱
            cost = extract_llm_cost(response, model, provider)
            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_response(content), cost
        except Exception as e:
            logger.warning(f"[Planner] LLM call failed: {e} | task={task_description[:50]}")
            return [], 0.0

    def _parse_response(self, content: str) -> List[Dict[str, Any]]:
        """LLM 응답에서 subtasks 추출."""
        try:
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
            subtasks = parsed.get("subtasks", [])
            reasoning = parsed.get("reasoning", "")
            logger.debug(f"[Planner] reasoning: {reasoning}")
            return subtasks if isinstance(subtasks, list) else []
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[Planner] JSON parse error: {e}")
            return []

    def _build_subtask_nodes(
        self,
        parent: RecursiveTaskNode,
        subtask_dicts: List[Dict[str, Any]],
        max_subtasks: int | None = None,
    ) -> List[RecursiveTaskNode]:
        """subtask dict 목록 → RecursiveTaskNode 목록.

        R-06: max_subtasks가 지정된 경우 초과 항목을 잘라냄으로써 설정값을 hard limit으로 강제.
        """
        # R-06: LLM이 max_subtasks를 초과해서 반환해도 실제 강제 적용
        if max_subtasks is not None:
            subtask_dicts = subtask_dicts[:max_subtasks]

        nodes: List[RecursiveTaskNode] = []
        for item in subtask_dicts:
            description = item.get("description", "").strip()
            if not description:
                continue
            node = RecursiveTaskNode(
                task_id=str(uuid.uuid4()),
                parent_id=parent.task_id,
                depth=parent.depth + 1,
                description=description,
                atomicity=TaskAtomicity.UNKNOWN,
                status=TaskStatus.PENDING,
                metadata={"depends_on": item.get("depends_on", [])},
            )
            nodes.append(node)
        logger.info(
            f"[Planner] Decomposed '{parent.description[:40]}' → {len(nodes)} subtasks "
            f"(depth={parent.depth}→{parent.depth + 1})"
        )
        return nodes

    def _fallback_split(self, description: str) -> List[Dict[str, Any]]:
        """LLM 실패 시 태스크를 두 부분으로 단순 분할."""
        return [
            {"description": f"Research background and context for: {description}", "depends_on": []},
            {"description": f"Analyze and synthesize findings for: {description}", "depends_on": [0]},
        ]
