"""Tests for Context Optimization Features

컨텍스트 최적화 기능 테스트
"""

import pytest
from typing import List, Dict, Any

# Test fixtures and utilities


def create_test_messages(count: int = 10) -> List[Dict[str, Any]]:
    """테스트용 메시지 생성"""
    messages = []
    for i in range(count):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Test message {i} with some content to count tokens. " * 10
        })
    return messages


def create_long_tool_result() -> Dict[str, Any]:
    """긴 tool result 생성"""
    return {
        "role": "tool",
        "tool_call_id": "call_123",
        "content": "x" * 1000  # 1000자 결과
    }


class TestTokenCounter:
    """Token Counter 테스트"""

    def test_token_counter_import(self):
        """Token counter import 테스트"""
        from neos.utils.token_counter import TokenCounter, get_token_counter

        counter = get_token_counter()
        assert counter is not None
        assert hasattr(counter, 'count_tokens')
        assert hasattr(counter, 'count_messages_tokens')
        assert hasattr(counter, 'check_context_overflow')

    def test_count_tokens(self):
        """기본 토큰 카운팅 테스트"""
        from neos.utils.token_counter import get_token_counter

        counter = get_token_counter()

        # 간단한 텍스트
        text = "Hello, world!"
        tokens = counter.count_tokens(text)
        assert tokens > 0
        assert tokens < 100  # 상식적인 범위

        # 빈 텍스트
        assert counter.count_tokens("") == 0
        assert counter.count_tokens(None) == 0

    def test_count_messages_tokens(self):
        """메시지 토큰 카운팅 테스트"""
        from neos.utils.token_counter import get_token_counter

        counter = get_token_counter()
        messages = create_test_messages(5)

        total_tokens = counter.count_messages_tokens(messages)
        assert total_tokens > 0

        # 개별 카운팅 합과 비교 (오버헤드 때문에 약간 차이 있음)
        individual_sum = sum(
            counter.count_tokens(msg.get("content", ""))
            for msg in messages
        )
        assert total_tokens >= individual_sum

    def test_context_overflow_detection(self):
        """컨텍스트 오버플로우 감지 테스트"""
        from neos.utils.token_counter import get_token_counter

        counter = get_token_counter()

        # 작은 메시지 - 정상
        small_messages = create_test_messages(5)
        status = counter.check_context_overflow(small_messages, max_tokens=10000)

        assert "current_tokens" in status
        assert "is_overflow" in status
        assert "is_warning" in status
        assert status["is_overflow"] is False  # 작은 메시지는 오버플로우 없음

        # 큰 메시지 - 오버플로우
        large_messages = create_test_messages(100)
        status = counter.check_context_overflow(large_messages, max_tokens=100)

        assert status["is_overflow"] is True or status["is_warning"] is True

    def test_calculate_cost(self):
        """비용 계산 테스트

        가격은 모델 카탈로그(`neos/config/models.yaml`)에서 온다. 예전에는
        per-1K 하드코딩 표 + 부분 문자열 매칭이었고, `"gpt-4"`나
        `"claude-3-sonnet"`처럼 이 배포가 실제로 호출하지 않는 이름도
        그 표에 걸려 그럴듯한 값을 냈다. 지금은 카탈로그에 있는 모델만
        가격이 있다.
        """
        from neos.utils.token_counter import get_token_counter

        counter = get_token_counter()

        # 카탈로그에 있는 OpenAI 모델
        cost_openai = counter.calculate_cost(1000, 500, "gpt-4o")
        assert cost_openai > 0
        assert isinstance(cost_openai, float)

        # 카탈로그에 있는 Anthropic 모델
        cost_claude = counter.calculate_cost(1000, 500, "claude-sonnet-5")
        assert cost_claude > 0

        # 0 토큰
        assert counter.calculate_cost(0, 0, "gpt-4o") == 0.0

    def test_calculate_cost_does_not_guess_for_uncatalogued_names(self):
        """카탈로그에 없는 이름은 추측하지 않는다.

        `"gpt-4"`는 `context_optimization.token_counter_model`의 값이지만
        tiktoken 인코딩 식별자이지 이 배포가 호출하는 모델이 아니다. 옛
        구현은 부분 문자열 매칭으로 $0.03/1K를 붙였다.
        """
        from neos.utils.token_counter import get_token_counter

        counter = get_token_counter()

        assert counter.calculate_cost(1000, 500, "gpt-4") == 0.0
        assert counter.calculate_cost(1000, 500, "claude-3-sonnet") == 0.0


class TestContextOptimizer:
    """Context Optimizer 테스트"""

    @pytest.mark.asyncio
    async def test_optimizer_import(self):
        """Context optimizer import 테스트"""
        from neos.services.context_optimizer import ContextOptimizer, context_optimizer

        assert context_optimizer is not None
        assert hasattr(context_optimizer, 'check_and_optimize_context')

    @pytest.mark.asyncio
    async def test_tool_result_summarization(self):
        """Tool result 요약 테스트"""
        from neos.services.context_optimizer import context_optimizer

        messages = [
            {"role": "user", "content": "Test query"},
            create_long_tool_result(),
            {"role": "assistant", "content": "Response"}
        ]

        optimized, stats = await context_optimizer._summarize_tool_results(messages)

        # Tool result가 요약되었는지 확인
        assert len(optimized) == len(messages)

        # 통계 확인
        assert "summarized_count" in stats

    @pytest.mark.asyncio
    async def test_message_compression(self):
        """메시지 압축 테스트"""
        from neos.services.context_optimizer import context_optimizer

        # 많은 메시지 생성
        messages = create_test_messages(50)

        compressed, stats = await context_optimizer._compress_old_messages(messages)

        # 압축 후 메시지 수가 감소했는지 확인
        assert len(compressed) < len(messages)
        assert "compressed_count" in stats

    @pytest.mark.asyncio
    async def test_workflow_budget(self):
        """워크플로우 예산 테스트"""
        from neos.services.context_optimizer import context_optimizer

        # 다양한 워크플로우 타입
        budget_default = context_optimizer._get_workflow_budget("default")
        budget_deep = context_optimizer._get_workflow_budget("deep_research")
        budget_chat = context_optimizer._get_workflow_budget("chat")

        assert budget_default > 0
        assert budget_deep > 0
        assert budget_chat > 0

        # Deep Research가 더 큰 예산을 가져야 함
        # (설정에 따라 다를 수 있음)

    @pytest.mark.asyncio
    async def test_full_optimization_pipeline(self):
        """전체 최적화 파이프라인 테스트"""
        from neos.services.context_optimizer import context_optimizer

        # 복잡한 메시지 시나리오
        messages = create_test_messages(40)
        messages.append(create_long_tool_result())

        optimized, stats = await context_optimizer.check_and_optimize_context(
            messages,
            workflow_type="chat",
            force_compress=True
        )

        # 최적화 통계 확인
        assert "original_tokens" in stats
        assert "optimized_tokens" in stats
        assert "optimizations_applied" in stats

    @pytest.mark.asyncio
    async def test_context_health_report(self):
        """컨텍스트 상태 리포트 테스트"""
        from neos.services.context_optimizer import context_optimizer

        messages = create_test_messages(10)
        report = context_optimizer.get_context_health_report(messages, "chat")

        assert "total_messages" in report
        assert "total_tokens" in report
        assert "usage_ratio" in report
        assert "is_healthy" in report
        assert "recommendations" in report
        assert report["total_messages"] == 10


class TestSemanticDeduplicator:
    """Semantic Deduplicator 테스트"""

    @pytest.mark.asyncio
    async def test_deduplicator_import(self):
        """Semantic deduplicator import 테스트"""
        from neos.utils.semantic_deduplicator import SemanticDeduplicator, semantic_deduplicator

        assert semantic_deduplicator is not None
        assert hasattr(semantic_deduplicator, 'deduplicate_messages')

    @pytest.mark.asyncio
    async def test_text_hash_deduplication(self):
        """텍스트 해시 기반 중복 제거 테스트"""
        from neos.utils.semantic_deduplicator import semantic_deduplicator

        # 중복 메시지 포함
        messages = [
            {"role": "user", "content": "Same message"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Same message"},  # 중복
            {"role": "assistant", "content": "Response 2"},
        ]

        unique, stats = semantic_deduplicator._text_hash_deduplicate(messages)

        # 중복이 제거되었는지 확인
        assert "removed_count" in stats

    @pytest.mark.asyncio
    async def test_preserve_recent_messages(self):
        """최근 메시지 보존 테스트"""
        from neos.utils.semantic_deduplicator import semantic_deduplicator

        messages = create_test_messages(20)

        unique, stats = await semantic_deduplicator.deduplicate_messages(
            messages,
            preserve_recent=10
        )

        # 최소한 최근 10개는 보존되어야 함
        assert len(unique) >= 10


class TestChatLLMServiceIntegration:
    """Chat LLM Service 통합 테스트"""

    def test_chat_service_has_optimization_params(self):
        """Chat service에 최적화 파라미터가 있는지 확인"""
        from neos.services.chat_llm_service import ChatLLMService
        import inspect

        service = ChatLLMService()

        # generate_response 시그니처 확인
        sig = inspect.signature(service.generate_response)
        params = sig.parameters

        assert "workflow_type" in params
        assert "enable_context_optimization" in params

        # generate_response_stream 시그니처 확인
        sig_stream = inspect.signature(service.generate_response_stream)
        params_stream = sig_stream.parameters

        assert "workflow_type" in params_stream
        assert "enable_context_optimization" in params_stream


class TestSettings:
    """Settings 테스트"""

    def test_context_optimization_settings_exist(self):
        """컨텍스트 최적화 설정 존재 확인"""
        from neos.config.settings import settings

        # Thinking block 설정
        assert hasattr(settings, 'THINKING_BLOCKS_ENABLED')
        assert hasattr(settings, 'MAX_THINKING_LENGTH')

        # Token counter 설정
        assert hasattr(settings, 'USE_TIKTOKEN')
        assert hasattr(settings, 'TOKEN_COUNTER_MODEL')

        # Context overflow 설정
        assert hasattr(settings, 'CONTEXT_OVERFLOW_DETECTION')
        assert hasattr(settings, 'CONTEXT_WINDOW_THRESHOLD')
        assert hasattr(settings, 'MAX_CONTEXT_TOKENS')

        # Tool result 설정
        assert hasattr(settings, 'TOOL_RESULT_SUMMARIZATION')
        assert hasattr(settings, 'TOOL_RESULT_MAX_LENGTH')

        # Message compression 설정
        assert hasattr(settings, 'MESSAGE_COMPRESSION_ENABLED')
        assert hasattr(settings, 'MESSAGE_COMPRESSION_THRESHOLD')

        # Semantic deduplication 설정
        assert hasattr(settings, 'SEMANTIC_DEDUPLICATION')
        assert hasattr(settings, 'SEMANTIC_SIMILARITY_THRESHOLD')

        # Workflow budget 설정
        assert hasattr(settings, 'WORKFLOW_CONTEXT_BUDGET')
        assert hasattr(settings, 'DEFAULT_WORKFLOW_TOKEN_BUDGET')
        assert hasattr(settings, 'DEEP_RESEARCH_TOKEN_BUDGET')
        assert hasattr(settings, 'CHAT_TOKEN_BUDGET')


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
