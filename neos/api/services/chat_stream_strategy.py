"""LLM 스트림 Strategy 패턴.

TOOL_SEARCH_ENABLED 여부에 따라 두 가지 LLM 스트림 전략 중 하나를 선택한다.
전략 추가 시 LLMStreamStrategy를 상속하고 resolve_llm_strategy()에만 등록하면 된다.

Usage:
    strategy = await resolve_llm_strategy()
    async for chunk in strategy.create_stream(...):
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable, Coroutine, Dict, List, Optional

from neos.config.settings import settings as app_settings
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class LLMStreamStrategy(ABC):
    """LLM 스트리밍 전략 추상 기반 클래스."""

    @abstractmethod
    def create_stream(
        self,
        conversation_id: str,
        message_id: str,
        messages: List[Dict[str, Any]],
        model_name: Optional[str],
        system_prompt: str,
        temperature: float,
        max_tokens: Optional[int],
        tools: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """LLM 청크 딕셔너리를 생성하는 비동기 제너레이터를 반환한다."""
        ...


class ToolSearchStreamStrategy(LLMStreamStrategy):
    """Advanced Tool Search 활성화 경로: 도구를 의미론적으로 검색하여 호출한다."""

    def __init__(
        self,
        chat_llm_service,
        search_handler,
        core_tools_dicts: List[Dict],
        max_rounds: int,
    ) -> None:
        self._svc = chat_llm_service
        self._search_handler = search_handler
        self._core_tools = core_tools_dicts
        self._max_rounds = max_rounds

    def create_stream(self, conversation_id, message_id, messages,
                      model_name, system_prompt, temperature, max_tokens, tools):
        # tools 인자는 이 전략에서 무시 — core_tools를 대신 사용한다
        return self._svc.generate_response_stream_with_tool_search(
            conversation_id=conversation_id,
            message_id=message_id,
            conversation_messages=messages,
            core_tools=self._core_tools,
            search_handler=self._search_handler,
            model_name=model_name,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_tool_rounds=self._max_rounds,
        )


class StandardStreamStrategy(LLMStreamStrategy):
    """기본 Tool Calling 경로: 미리 결정된 tools 목록을 그대로 사용한다."""

    def __init__(self, chat_llm_service) -> None:
        self._svc = chat_llm_service

    def create_stream(self, conversation_id, message_id, messages,
                      model_name, system_prompt, temperature, max_tokens, tools):
        return self._svc.generate_response_stream_with_tools(
            conversation_id=conversation_id,
            message_id=message_id,
            conversation_messages=messages,
            tools=tools,
            model_name=model_name,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )


async def resolve_llm_strategy(
    chat_llm_service,
    get_core_tools_fn: Callable[[], Coroutine],
    get_search_handler_fn: Callable,
) -> LLMStreamStrategy:
    """설정에 따라 적절한 LLMStreamStrategy를 반환하는 팩토리 함수."""
    if app_settings.TOOL_SEARCH_ENABLED and app_settings.ARTIFACTS_ENABLED:
        core_tools = await get_core_tools_fn()
        logger.debug(
            f"[LLMStrategy] ToolSearchStreamStrategy selected "
            f"(core_tools={len(core_tools)}, max_rounds={app_settings.TOOL_SEARCH_MAX_ROUNDS})"
        )
        return ToolSearchStreamStrategy(
            chat_llm_service=chat_llm_service,
            search_handler=get_search_handler_fn(),
            core_tools_dicts=core_tools,
            max_rounds=app_settings.TOOL_SEARCH_MAX_ROUNDS,
        )
    logger.debug("[LLMStrategy] StandardStreamStrategy selected")
    return StandardStreamStrategy(chat_llm_service=chat_llm_service)
