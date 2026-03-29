"""
RecursiveAtomizer: 태스크 원자성 판별기

태스크가 직접 실행 가능한지(atomic), 더 작은 하위 문제로 분해해야 하는지 판단합니다.
비용 최소화를 위해 Haiku 모델을 사용합니다.
"""

import json
import logging
import time
from typing import Any, Dict, List

from neos.config.settings import settings
from neos.utils.llm_factory import LLMFactory

from .models import RecursiveTaskNode, TaskAtomicity, extract_llm_cost

logger = logging.getLogger(__name__)

_ATOMIZER_PROMPT = """You are a task complexity analyzer. Determine if the given task can be directly executed (atomic) or needs to be broken down into smaller sub-tasks (decomposable).

ATOMIC tasks (can be done directly):
- Answerable with a single web search
- Solvable with one tool call
- Clear factual question with single answer
- Simple lookup or retrieval

DECOMPOSABLE tasks (need breakdown):
- Require multiple sources or perspectives
- Need comparison across multiple subjects
- Require sequential steps (A must be known before B)
- Multi-aspect analysis or comprehensive reports
- Questions with multiple distinct sub-questions

Task to analyze: {description}

Context (depth={depth}, max_depth={max_depth}):
{context_summary}

Return ONLY a valid JSON object:
{{
  "atomic": true/false,
  "reasoning": "brief explanation (1-2 sentences)",
  "confidence": 0.0-1.0,
  "estimated_tools": ["tool1", "tool2"]
}}"""


class RecursiveAtomizer:
    """태스크 원자성 판별기.

    LLM(Haiku)을 사용하여 태스크가 직접 실행 가능한지, 분해가 필요한지 판단합니다.
    신뢰도 < 0.5이면 보수적으로 DECOMPOSABLE 반환.
    depth >= max_depth이면 항상 ATOMIC 반환 (graceful degradation).
    """

    def __init__(self):
        self._model = settings.RECURSIVE_ATOMIZER_MODEL
        self._max_depth = settings.RECURSIVE_MAX_DEPTH

    async def assess(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> TaskAtomicity:
        """태스크 원자성 판별.

        Args:
            task: 판별할 태스크 노드
            context: 현재 실행 컨텍스트 (original_query, available_tools 등)

        Returns:
            TaskAtomicity.ATOMIC 또는 TaskAtomicity.DECOMPOSABLE
        """
        # 안전 장치: 최대 깊이 도달 시 항상 ATOMIC (graceful degradation)
        if task.depth >= self._max_depth:
            logger.info(
                f"[Atomizer] depth={task.depth} >= max_depth={self._max_depth}, "
                f"forcing ATOMIC: {task.description[:60]}"
            )
            return TaskAtomicity.ATOMIC

        try:
            result = await self._call_llm(task, context)
            return result
        except Exception as e:
            logger.warning(f"[Atomizer] LLM call failed, defaulting to DECOMPOSABLE: {e}")
            # 실패 시 보수적으로 DECOMPOSABLE (분해하면 더 안전)
            return TaskAtomicity.DECOMPOSABLE

    async def _call_llm(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> TaskAtomicity:
        """Haiku LLM을 호출하여 원자성 판별."""
        context_summary = self._build_context_summary(context)

        prompt = _ATOMIZER_PROMPT.format(
            description=task.description,
            depth=task.depth,
            max_depth=self._max_depth,
            context_summary=context_summary,
        )

        provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
        llm = LLMFactory.create_llm(
            provider=provider,
            model=self._model,
            temperature=0.0,
            max_tokens=300,
        )

        start = time.time()
        response = await llm.ainvoke(prompt)
        elapsed = time.time() - start

        # R-01: 비용 추적 - LLM 응답 usage 파싱 후 task.cost 갱신
        provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
        cost = extract_llm_cost(response, self._model, provider)
        task.cost += cost
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None:
            cost_acc[0] += cost

        content = response.content if hasattr(response, "content") else str(response)
        parsed = self._parse_response(content)

        if parsed is None:
            logger.warning(f"[Atomizer] Failed to parse LLM response, defaulting to DECOMPOSABLE")
            return TaskAtomicity.DECOMPOSABLE

        atomic: bool = parsed.get("atomic", False)
        confidence: float = float(parsed.get("confidence", 0.5))
        reasoning: str = parsed.get("reasoning", "")

        logger.debug(
            f"[Atomizer] depth={task.depth} atomic={atomic} confidence={confidence:.2f} "
            f"elapsed={elapsed:.2f}s cost=${cost:.6f} | {task.description[:50]}"
        )
        logger.debug(f"[Atomizer] reasoning: {reasoning}")

        # R-12: confidence < 0.5이면 무조건 DECOMPOSABLE (중복 조건 제거)
        if confidence < 0.5:
            return TaskAtomicity.DECOMPOSABLE

        return TaskAtomicity.ATOMIC if atomic else TaskAtomicity.DECOMPOSABLE

    def _build_context_summary(self, context: Dict[str, Any]) -> str:
        """컨텍스트 요약 문자열 생성."""
        parts: List[str] = []
        if original_query := context.get("original_query"):
            parts.append(f"Original query: {original_query[:200]}")
        if completed := context.get("completed_task_descriptions"):
            parts.append(f"Already solved: {', '.join(completed[:3])}")
        if not parts:
            return "No additional context."
        return "\n".join(parts)

    def _parse_response(self, content: str) -> Dict[str, Any] | None:
        """LLM 응답에서 JSON 추출."""
        try:
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            logger.debug(f"[Atomizer] JSON parse error: {e}, content={content[:100]}")
            return None
