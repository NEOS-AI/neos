"""시스템 프롬프트 Builder 패턴.

conversation 설정, 워크플로우 결과, 아티팩트·인라인 시각화 기능을
단계적으로 조합하여 최종 system_prompt와 tools 리스트를 생성한다.

Usage:
    prompt, tools = (
        SystemPromptBuilder(base=conversation.get("system_prompt", ""))
        .with_workflow_result(workflow_result)
        .with_artifacts()
        .with_inline_vis()
        .build()
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from neos.config.settings import settings as app_settings
from neos.learn.session_search_tool import list_chat_research_tools
from neos.tools.artifact_tools import get_artifact_tools
from neos.tools.inline_vis_tools import get_inline_vis_tools
from neos.utils.logger import get_logger

logger = get_logger(__name__)

_WORKFLOW_CONTEXT_TEMPLATE = """\
# Workflow Results
The multi-agent workflow has gathered the following information to help answer the user's question:

{response}

Use this information to provide a comprehensive and accurate answer. \
If needed, you can create artifacts using the available tools."""

_MAX_WORKFLOW_RESPONSE_CHARS = 5000


class SystemPromptBuilder:
    """Builder: system prompt 부분들을 단계적으로 조합한다."""

    def __init__(self, base: str = "") -> None:
        self._parts: List[str] = [base] if base else []
        self._tools: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Builder steps
    # ------------------------------------------------------------------ #

    def with_workflow_result(
        self, workflow_result: Optional[Dict[str, Any]]
    ) -> "SystemPromptBuilder":
        """워크플로우 수집 결과를 컨텍스트 블록으로 추가한다."""
        if not workflow_result:
            return self
        response_text = workflow_result.get("response", "")
        if not response_text:
            return self
        truncated = response_text[:_MAX_WORKFLOW_RESPONSE_CHARS]
        self._parts.append(
            _WORKFLOW_CONTEXT_TEMPLATE.format(response=truncated)
        )
        return self

    def with_artifacts(self) -> "SystemPromptBuilder":
        """아티팩트 기능이 활성화된 경우 도구와 프롬프트를 추가한다."""
        if app_settings.ARTIFACTS_ENABLED:
            self._parts.append(app_settings.ARTIFACTS_SYSTEM_PROMPT)
            self._tools.extend(get_artifact_tools())
            logger.debug("[SystemPromptBuilder] Artifact tools added")
        return self

    def with_inline_vis(self) -> "SystemPromptBuilder":
        """인라인 시각화 기능이 활성화된 경우 도구와 프롬프트를 추가한다."""
        if app_settings.INLINE_VIS_ENABLED:
            self._parts.append(app_settings.INLINE_VIS_SYSTEM_PROMPT)
            self._tools.extend(get_inline_vis_tools())
            logger.debug("[SystemPromptBuilder] Inline-vis tools added")
        return self

    def with_session_search(self) -> "SystemPromptBuilder":
        """Add prior-session search when learn.session_search_tool is on."""
        tools = list_chat_research_tools()
        if tools:
            self._tools.extend(tools)
            logger.debug("[SystemPromptBuilder] Session-search tool added")
        return self

    # ------------------------------------------------------------------ #
    # Terminal step
    # ------------------------------------------------------------------ #

    def build(self) -> Tuple[str, List[Dict[str, Any]]]:
        """(system_prompt, tools) 튜플을 반환한다."""
        prompt = "\n\n".join(part for part in self._parts if part)
        return prompt, list(self._tools)
