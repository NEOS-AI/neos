"""Context Optimization Service

컨텍스트 길이 최적화를 위한 통합 서비스:
- 컨텍스트 오버플로우 감지 및 방지
- Tool result 요약
- 메시지 히스토리 압축
- 의미론적 중복 제거
- 워크플로우별 컨텍스트 예산 관리
"""

from typing import Dict, Any, List, Optional, Tuple
import json
import logging
from datetime import datetime

from neos.config.settings import settings
from neos.utils.token_counter import get_token_counter
from neos.utils.llm_factory import create_llm
from neos.utils.semantic_deduplicator import semantic_deduplicator

logger = logging.getLogger(__name__)


class ContextOptimizer:
    """컨텍스트 최적화 서비스"""

    def __init__(self):
        self.token_counter = get_token_counter()
        self.compression_llm = None  # Lazy initialization

    def _get_compression_llm(self):
        """압축용 LLM 획득 (lazy initialization)"""
        if self.compression_llm is None:
            # 빠르고 저렴한 모델 사용 (GPT-3.5 or Claude Haiku)
            try:
                self.compression_llm = create_llm(
                    provider="openai",
                    model="gpt-3.5-turbo",
                    temperature=0.3,
                    max_tokens=500
                )
            except Exception as e:
                logger.warning(f"Failed to create compression LLM: {e}")
                self.compression_llm = None
        return self.compression_llm

    async def check_and_optimize_context(
        self,
        messages: List[Dict[str, Any]],
        workflow_type: str = "default",
        force_compress: bool = False
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """컨텍스트 검사 및 최적화

        Args:
            messages: 메시지 리스트
            workflow_type: 워크플로우 타입 (default, deep_research, chat)
            force_compress: 강제 압축 여부

        Returns:
            (최적화된 메시지 리스트, 최적화 통계)
        """
        stats = {
            "original_messages": len(messages),
            "original_tokens": 0,
            "optimized_tokens": 0,
            "removed_messages": 0,
            "compressed_messages": 0,
            "summarized_tool_results": 0,
            "optimizations_applied": []
        }

        if not settings.CONTEXT_OVERFLOW_DETECTION:
            logger.info("[ContextOptimizer] Context optimization disabled")
            return messages, stats

        # 1. 토큰 카운팅
        original_tokens = self.token_counter.count_messages_tokens(messages)
        stats["original_tokens"] = original_tokens

        # 2. 컨텍스트 예산 확인
        token_budget = self._get_workflow_budget(workflow_type)
        overflow_status = self.token_counter.check_context_overflow(
            messages,
            max_tokens=token_budget
        )

        logger.info(
            f"[ContextOptimizer] Context status: {original_tokens}/{token_budget} tokens "
            f"({overflow_status['usage_ratio']*100:.1f}%)"
        )

        # 3. 최적화 필요성 판단
        needs_optimization = (
            force_compress or
            overflow_status["is_warning"] or
            overflow_status["is_overflow"]
        )

        if not needs_optimization:
            stats["optimized_tokens"] = original_tokens
            return messages, stats

        # 4. 최적화 적용
        optimized_messages = messages.copy()

        # 4.1 Tool Result 요약
        if settings.TOOL_RESULT_SUMMARIZATION:
            optimized_messages, tool_stats = await self._summarize_tool_results(
                optimized_messages
            )
            stats["summarized_tool_results"] = tool_stats["summarized_count"]
            if tool_stats["summarized_count"] > 0:
                stats["optimizations_applied"].append("tool_result_summarization")

        # 4.2 메시지 압축 (30턴 이상)
        if settings.MESSAGE_COMPRESSION_ENABLED and len(optimized_messages) >= settings.MESSAGE_COMPRESSION_THRESHOLD:
            optimized_messages, compress_stats = await self._compress_old_messages(
                optimized_messages
            )
            stats["compressed_messages"] = compress_stats["compressed_count"]
            if compress_stats["compressed_count"] > 0:
                stats["optimizations_applied"].append("message_compression")

        # 4.3 의미론적 중복 제거
        if settings.SEMANTIC_DEDUPLICATION:
            optimized_messages, dedup_stats = await self._deduplicate_messages(
                optimized_messages
            )
            stats["removed_messages"] = dedup_stats["removed_count"]
            if dedup_stats["removed_count"] > 0:
                stats["optimizations_applied"].append("semantic_deduplication")

        # 5. 최종 통계
        optimized_tokens = self.token_counter.count_messages_tokens(optimized_messages)
        stats["optimized_tokens"] = optimized_tokens
        reduction_pct = ((original_tokens - optimized_tokens) / original_tokens * 100) if original_tokens > 0 else 0

        logger.info(
            f"[ContextOptimizer] Optimization complete: "
            f"{original_tokens} → {optimized_tokens} tokens "
            f"({reduction_pct:.1f}% reduction)"
        )

        return optimized_messages, stats

    def _get_workflow_budget(self, workflow_type: str) -> int:
        """워크플로우별 토큰 예산 반환

        Args:
            workflow_type: 워크플로우 타입

        Returns:
            토큰 예산
        """
        if not settings.WORKFLOW_CONTEXT_BUDGET:
            return settings.MAX_CONTEXT_TOKENS

        budget_map = {
            "deep_research": settings.DEEP_RESEARCH_TOKEN_BUDGET,
            "chat": settings.CHAT_TOKEN_BUDGET,
            "default": settings.DEFAULT_WORKFLOW_TOKEN_BUDGET
        }

        return budget_map.get(workflow_type, settings.DEFAULT_WORKFLOW_TOKEN_BUDGET)

    async def _summarize_tool_results(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Tool result를 요약하여 토큰 절약

        Args:
            messages: 메시지 리스트

        Returns:
            (요약된 메시지 리스트, 통계)
        """
        stats = {"summarized_count": 0, "tokens_saved": 0}
        optimized_messages = []
        max_length = settings.TOOL_RESULT_MAX_LENGTH

        for msg in messages:
            msg_copy = msg.copy()

            # Tool result 메시지 탐지
            if msg.get("role") == "tool" or "tool_call_id" in msg:
                content = msg.get("content", "")

                # 긴 tool result만 요약
                if isinstance(content, str) and len(content) > max_length:
                    original_tokens = self.token_counter.count_tokens(content)

                    # 요약 적용
                    try:
                        # JSON 파싱 시도
                        try:
                            data = json.loads(content)
                            summarized = self._summarize_structured_data(data, max_length)
                        except (json.JSONDecodeError, TypeError):
                            # 텍스트 요약
                            summarized = self._summarize_text(content, max_length)

                        msg_copy["content"] = summarized
                        msg_copy["_original_length"] = len(content)
                        msg_copy["_summarized"] = True

                        new_tokens = self.token_counter.count_tokens(summarized)
                        stats["tokens_saved"] += (original_tokens - new_tokens)
                        stats["summarized_count"] += 1

                        logger.debug(
                            f"[ContextOptimizer] Summarized tool result: "
                            f"{original_tokens} → {new_tokens} tokens"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to summarize tool result: {e}")

            optimized_messages.append(msg_copy)

        return optimized_messages, stats

    def _summarize_structured_data(self, data: Any, max_length: int) -> str:
        """구조화된 데이터 요약

        Args:
            data: JSON 데이터
            max_length: 최대 길이

        Returns:
            요약된 문자열
        """
        if isinstance(data, dict):
            # 키-값 쌍 중 중요한 것만 유지
            summary = {}
            for key, value in data.items():
                if key in ["error", "status", "result", "summary", "title", "message"]:
                    summary[key] = value
                elif key == "data" and isinstance(value, list):
                    summary["data_count"] = len(value)
                    summary["data_sample"] = value[:3] if len(value) > 3 else value

            result = json.dumps(summary, ensure_ascii=False)
            if len(result) > max_length:
                result = result[:max_length] + "...[truncated]"
            return result

        elif isinstance(data, list):
            return f"[List with {len(data)} items, sample: {data[:3]}...]"

        else:
            return str(data)[:max_length]

    def _summarize_text(self, text: str, max_length: int) -> str:
        """텍스트 요약 (간단한 truncation)

        Args:
            text: 원본 텍스트
            max_length: 최대 길이

        Returns:
            요약된 텍스트
        """
        if len(text) <= max_length:
            return text

        # 문장 경계에서 자르기 시도
        truncated = text[:max_length]
        last_period = max(
            truncated.rfind('. '),
            truncated.rfind('.\n'),
            truncated.rfind('! '),
            truncated.rfind('? ')
        )

        if last_period > max_length * 0.7:  # 70% 이상이면 문장 경계 사용
            truncated = truncated[:last_period + 1]

        return truncated + "\n...[truncated for context optimization]"

    async def _compress_old_messages(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """오래된 메시지를 압축하여 요약

        Args:
            messages: 메시지 리스트

        Returns:
            (압축된 메시지 리스트, 통계)
        """
        stats = {"compressed_count": 0, "tokens_saved": 0}

        if len(messages) < settings.MESSAGE_COMPRESSION_THRESHOLD:
            return messages, stats

        # 압축 비율에 따라 유지할 최근 메시지 수 계산
        keep_recent = int(len(messages) * settings.MESSAGE_COMPRESSION_RATIO)
        keep_recent = max(keep_recent, 10)  # 최소 10개는 유지

        # 시스템 메시지와 최근 메시지는 유지
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        if len(other_messages) <= keep_recent:
            return messages, stats

        # 오래된 메시지와 최근 메시지 분리
        old_messages = other_messages[:-keep_recent]
        recent_messages = other_messages[-keep_recent:]

        # 오래된 메시지 요약
        original_tokens = self.token_counter.count_messages_tokens(old_messages)

        summary_text = self._create_conversation_summary(old_messages)
        summary_message = {
            "role": "system",
            "content": f"[Previous conversation summary]\n{summary_text}",
            "_compressed": True,
            "_original_message_count": len(old_messages)
        }

        new_tokens = self.token_counter.count_tokens(summary_text)
        stats["compressed_count"] = len(old_messages)
        stats["tokens_saved"] = original_tokens - new_tokens

        logger.info(
            f"[ContextOptimizer] Compressed {len(old_messages)} messages: "
            f"{original_tokens} → {new_tokens} tokens"
        )

        # 재구성: 시스템 메시지 + 요약 + 최근 메시지
        return system_messages + [summary_message] + recent_messages, stats

    def _create_conversation_summary(self, messages: List[Dict[str, Any]]) -> str:
        """대화 요약 생성

        Args:
            messages: 요약할 메시지 리스트

        Returns:
            요약 텍스트
        """
        # 간단한 요약 (LLM 없이)
        summary_parts = []

        user_queries = [msg.get("content", "")[:100] for msg in messages if msg.get("role") == "user"]
        assistant_responses = [msg.get("content", "")[:100] for msg in messages if msg.get("role") == "assistant"]

        if user_queries:
            summary_parts.append(f"User discussed: {len(user_queries)} topics")
            summary_parts.append(f"Sample queries: {', '.join(user_queries[:3])}")

        if assistant_responses:
            summary_parts.append(f"Assistant provided {len(assistant_responses)} responses")

        return "\n".join(summary_parts)

    async def _deduplicate_messages(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """의미론적으로 유사한 메시지 제거

        Args:
            messages: 메시지 리스트

        Returns:
            (중복 제거된 메시지 리스트, 통계)
        """
        # Semantic deduplicator 사용
        unique_messages, stats = await semantic_deduplicator.deduplicate_messages(
            messages,
            preserve_recent=10
        )

        return unique_messages, stats

    def get_context_health_report(
        self,
        messages: List[Dict[str, Any]],
        workflow_type: str = "default"
    ) -> Dict[str, Any]:
        """컨텍스트 상태 리포트 생성

        Args:
            messages: 메시지 리스트
            workflow_type: 워크플로우 타입

        Returns:
            상태 리포트
        """
        token_count = self.token_counter.count_messages_tokens(messages)
        token_budget = self._get_workflow_budget(workflow_type)
        overflow_status = self.token_counter.check_context_overflow(
            messages,
            max_tokens=token_budget
        )

        # 메시지 타입별 분석
        message_types = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            message_types[role] = message_types.get(role, 0) + 1

        return {
            "timestamp": datetime.now().isoformat(),
            "workflow_type": workflow_type,
            "total_messages": len(messages),
            "message_types": message_types,
            "total_tokens": token_count,
            "token_budget": token_budget,
            "usage_ratio": overflow_status["usage_ratio"],
            "is_healthy": not overflow_status["is_warning"],
            "overflow_status": overflow_status,
            "recommendations": self._get_recommendations(overflow_status, messages)
        }

    def _get_recommendations(
        self,
        overflow_status: Dict[str, Any],
        messages: List[Dict[str, Any]]
    ) -> List[str]:
        """최적화 권장사항 생성

        Args:
            overflow_status: 오버플로우 상태
            messages: 메시지 리스트

        Returns:
            권장사항 리스트
        """
        recommendations = []

        if overflow_status["is_overflow"]:
            recommendations.append("URGENT: Apply compression immediately to avoid API errors")

        if overflow_status["is_warning"]:
            recommendations.append("Consider enabling message compression")

        if len(messages) > 50:
            recommendations.append("Long conversation detected. Enable auto-compression.")

        # Tool result 분석
        tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
        if len(tool_messages) > 10:
            recommendations.append("Many tool results detected. Enable tool result summarization.")

        if not recommendations:
            recommendations.append("Context is healthy. No optimization needed.")

        return recommendations


# 전역 인스턴스
context_optimizer = ContextOptimizer()
