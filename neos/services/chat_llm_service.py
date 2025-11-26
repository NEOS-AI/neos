"""
Chat LLM Service

채팅 기능을 위한 LLM 통합 서비스
실시간 스트리밍, 비용 추적, 대화 컨텍스트 관리
"""

from typing import Dict, Any, List, Optional, AsyncGenerator
import time
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models import BaseLanguageModel

from neos.utils.llm_factory import create_llm
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger
from neos.services.context_optimizer import context_optimizer
from neos.config.settings import settings

logger = get_logger(__name__)


class ChatLLMService:
    """채팅 LLM 서비스"""

    def __init__(self):
        self.default_model = "claude-sonnet-4-5-20250929"
        self.default_provider = "anthropic"

    def _extract_provider_from_model(self, model_name: str) -> str:
        """모델명에서 provider 추출"""
        if "gpt" in model_name.lower():
            return "openai"
        elif "claude" in model_name.lower():
            return "anthropic"
        else:
            return self.default_provider

    def _build_messages(
        self,
        conversation_messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> List:
        """대화 메시지를 LangChain 메시지 형식으로 변환"""
        messages = []

        # 시스템 프롬프트 추가
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        # 대화 메시지 변환
        for msg in conversation_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))

        return messages

    def _extract_usage_from_response(self, response: Any) -> Dict[str, int]:
        """응답에서 토큰 사용량 추출"""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # response_metadata에서 추출 (Anthropic/OpenAI)
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata

            # Anthropic 형식
            if "usage" in metadata:
                anthropic_usage = metadata["usage"]
                usage["prompt_tokens"] = anthropic_usage.get("input_tokens", 0)
                usage["completion_tokens"] = anthropic_usage.get("output_tokens", 0)
                usage["total_tokens"] = (
                    usage["prompt_tokens"] + usage["completion_tokens"]
                )

            # OpenAI 형식
            elif "token_usage" in metadata:
                token_usage = metadata["token_usage"]
                usage["prompt_tokens"] = token_usage.get("prompt_tokens", 0)
                usage["completion_tokens"] = token_usage.get("completion_tokens", 0)
                usage["total_tokens"] = token_usage.get("total_tokens", 0)

        return usage

    def _extract_finish_reason(self, response: Any) -> Optional[str]:
        """응답에서 finish_reason 추출"""
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata
            # Anthropic
            if "stop_reason" in metadata:
                return metadata["stop_reason"]
            # OpenAI
            if "finish_reason" in metadata:
                return metadata["finish_reason"]
        return None

    async def generate_response(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        workflow_type: str = "chat",
        enable_context_optimization: bool = True,
    ) -> Dict[str, Any]:
        """
        채팅 응답 생성 (비스트리밍)

        Returns:
            {
                "content": str,
                "model_name": str,
                "provider": str,
                "usage": {...},
                "cost": {...},
                "latency_ms": int,
                "finish_reason": str
            }
        """
        model = model_name or self.default_model
        provider = self._extract_provider_from_model(model)

        start_time = time.time()

        try:
            # 컨텍스트 최적화
            optimized_messages = conversation_messages
            optimization_stats = None

            if enable_context_optimization and settings.CONTEXT_OVERFLOW_DETECTION:
                optimized_messages, optimization_stats = await context_optimizer.check_and_optimize_context(
                    conversation_messages,
                    workflow_type=workflow_type
                )

                if optimization_stats and optimization_stats.get("optimizations_applied"):
                    logger.info(
                        f"[ChatLLM] Context optimized: {optimization_stats['original_tokens']} → "
                        f"{optimization_stats['optimized_tokens']} tokens, "
                        f"applied: {optimization_stats['optimizations_applied']}"
                    )

            # LLM 생성
            llm_params = {"model": model, "temperature": temperature}
            if max_tokens:
                llm_params["max_tokens"] = max_tokens

            llm = create_llm(provider=provider, **llm_params)

            # 메시지 구성
            messages = self._build_messages(optimized_messages, system_prompt)

            # LLM 호출
            response = await llm.ainvoke(messages)

            # 응답 처리
            content = response.content if hasattr(response, "content") else str(response)
            usage = self._extract_usage_from_response(response)
            finish_reason = self._extract_finish_reason(response)
            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산 (기록은 호출자가 메시지 저장 후 수행)
            cost_info = await cost_calculator.calculate_cost(
                provider=provider,
                model_name=model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )

            logger.info(
                f"Generated response: {len(content)} chars, "
                f"{usage['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            result = {
                "content": content,
                "model_name": model,
                "provider": provider,
                "usage": usage,
                "cost": cost_info,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
            }

            # 최적화 통계 추가
            if optimization_stats:
                result["context_optimization"] = optimization_stats

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to generate response: {e}")
            raise

    async def generate_response_stream(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        workflow_type: str = "chat",
        enable_context_optimization: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        채팅 응답 스트리밍 생성

        Yields:
            {
                "type": "start" | "content" | "complete" | "error",
                "content": str (type=content인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우),
                "error": str (type=error인 경우)
            }
        """
        model = model_name or self.default_model
        provider = self._extract_provider_from_model(model)

        start_time = time.time()
        full_content = ""
        usage_info = None
        finish_reason_value = None
        optimization_stats = None

        try:
            # 컨텍스트 최적화
            optimized_messages = conversation_messages

            if enable_context_optimization and settings.CONTEXT_OVERFLOW_DETECTION:
                optimized_messages, optimization_stats = await context_optimizer.check_and_optimize_context(
                    conversation_messages,
                    workflow_type=workflow_type
                )

                if optimization_stats and optimization_stats.get("optimizations_applied"):
                    logger.info(
                        f"[ChatLLM Stream] Context optimized: {optimization_stats['original_tokens']} → "
                        f"{optimization_stats['optimized_tokens']} tokens"
                    )

            # LLM 생성
            llm_params = {"model": model, "temperature": temperature, "streaming": True}
            if max_tokens:
                llm_params["max_tokens"] = max_tokens

            llm = create_llm(provider=provider, **llm_params)

            # 메시지 구성
            messages = self._build_messages(optimized_messages, system_prompt)

            # 시작 이벤트
            yield {"type": "start", "model": model, "provider": provider}

            # 스트리밍 호출
            async for chunk in llm.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    content_chunk = chunk.content
                    full_content += content_chunk

                    # 컨텐츠 이벤트
                    yield {"type": "content", "content": content_chunk}

                # 마지막 청크에서 usage 정보 추출
                if hasattr(chunk, "response_metadata"):
                    usage_info = self._extract_usage_from_response(chunk)
                    finish_reason_value = self._extract_finish_reason(chunk)

            # 스트리밍 완료 후 usage 정보가 없으면 추정
            if not usage_info or usage_info["total_tokens"] == 0:
                # 간단한 토큰 추정 (정확하지 않음)
                estimated_prompt_tokens = sum(
                    len(msg.get("content", "")) // 4 for msg in conversation_messages
                )
                estimated_completion_tokens = len(full_content) // 4
                usage_info = {
                    "prompt_tokens": estimated_prompt_tokens,
                    "completion_tokens": estimated_completion_tokens,
                    "total_tokens": estimated_prompt_tokens
                    + estimated_completion_tokens,
                }

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산 (기록은 호출자가 메시지 저장 후 수행)
            cost_info = await cost_calculator.calculate_cost(
                provider=provider,
                model_name=model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Stream completed: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            complete_event = {
                "type": "complete",
                "full_content": full_content,
                "model_name": model,
                "provider": provider,
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason_value,
            }

            # 최적화 통계 추가
            if optimization_stats:
                complete_event["context_optimization"] = optimization_stats

            yield complete_event

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {"type": "error", "error": str(e)}


# 전역 인스턴스
chat_llm_service = ChatLLMService()
