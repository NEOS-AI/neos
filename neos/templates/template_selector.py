"""
Template Selector (Phase 4.7)

쿼리를 분석하여 최적의 연구 템플릿을 자동 선택합니다.
LLM structured output으로 분류하고, confidence가 낮으면 템플릿 없이 일반 워크플로우 사용.
"""

import json
import logging
from typing import Optional, Dict, Any

from neos.config.settings import settings

from .research_templates import ResearchTemplate, RESEARCH_TEMPLATES

logger = logging.getLogger(__name__)

_TEMPLATE_IDS = list(RESEARCH_TEMPLATES.keys())

_TEMPLATE_SELECTION_PROMPT = """You are a research template classifier. Given a user query, determine if it matches a pre-built research template.

Available templates:
{template_descriptions}

User query: {query}

Return ONLY a valid JSON object:
{{
  "template_id": "<template_id or 'none'>",
  "confidence": <float 0.0-1.0>,
  "extracted_params": {{<key-value pairs matching template parameter_schema>}}
}}

Rules:
- Return "none" if the query doesn't clearly match any template
- confidence should reflect how well the query matches the template purpose
- Extract relevant parameters from the query (e.g., company name, topic, competitors)
- Only return high confidence (>0.7) if the query clearly fits the template type"""


class TemplateSelector:
    """쿼리에서 적절한 연구 템플릿을 자동 선택"""

    CONFIDENCE_THRESHOLD = 0.7

    def __init__(self):
        self._llm = None
        self._template_desc_cache: Optional[str] = None

    def _get_template_descriptions(self) -> str:
        """템플릿 설명 텍스트 생성 (캐시)"""
        if self._template_desc_cache:
            return self._template_desc_cache

        lines = []
        for tid, tmpl in RESEARCH_TEMPLATES.items():
            params = ", ".join(
                f"{k}: {v}" for k, v in tmpl.parameter_schema.items()
            )
            lines.append(
                f"- {tid}: {tmpl.description} "
                f"(category: {tmpl.category}, params: {params})"
            )
        self._template_desc_cache = "\n".join(lines)
        return self._template_desc_cache

    async def _get_llm(self):
        """경량 LLM 인스턴스 (lazy init)"""
        if self._llm is None:
            from neos.utils.llm_factory import create_llm

            self._llm = create_llm(
                temperature=0.0,
                model=settings.FAST_LLM_MODEL,
            )
        return self._llm

    async def select(
        self,
        query: str,
        intent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        쿼리에 맞는 템플릿 선택

        Returns:
            None: 매칭 템플릿 없음
            Dict: {"template": ResearchTemplate, "params": {...}, "confidence": float}
        """
        try:
            llm = await self._get_llm()

            prompt = _TEMPLATE_SELECTION_PROMPT.format(
                template_descriptions=self._get_template_descriptions(),
                query=query,
            )

            from langchain_core.messages import HumanMessage
            from neos.utils.llm_wrapper import extract_text_from_response

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = extract_text_from_response(response)

            # JSON 파싱
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            result = json.loads(text)
            template_id = result.get("template_id", "none")
            confidence = float(result.get("confidence", 0.0))
            extracted_params = result.get("extracted_params", {})

            if template_id == "none" or confidence < self.CONFIDENCE_THRESHOLD:
                logger.debug(
                    f"[TemplateSelector] No template matched "
                    f"(id={template_id}, confidence={confidence:.2f})"
                )
                return None

            template = RESEARCH_TEMPLATES.get(template_id)
            if not template:
                logger.warning(
                    f"[TemplateSelector] Unknown template_id: {template_id}"
                )
                return None

            logger.info(
                f"[TemplateSelector] Selected '{template.name}' "
                f"(confidence={confidence:.2f})"
            )
            return {
                "template": template,
                "params": extracted_params,
                "confidence": confidence,
            }

        except json.JSONDecodeError as e:
            logger.warning(f"[TemplateSelector] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"[TemplateSelector] Selection failed, skipping: {e}")
            return None
