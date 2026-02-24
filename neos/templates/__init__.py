"""
Research Templates (Phase 4.7)

사전 구축된 연구 설정으로 특정 연구 유형에 최적화된 워크플로우를 제공합니다.
"""

from .research_templates import ResearchTemplate, RESEARCH_TEMPLATES
from .template_selector import TemplateSelector

__all__ = [
    "ResearchTemplate",
    "RESEARCH_TEMPLATES",
    "TemplateSelector",
]
