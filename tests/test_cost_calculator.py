"""
Comprehensive unit tests for CostCalculator module

Tests cover:
- Model pricing retrieval (DB and fallback)
- Cost calculation accuracy with various token counts
- Cache cost calculations
- Message cost recording
- Conversation and user cost summaries
- Error handling and edge cases
- Decimal precision
"""

import json

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from neos.utils.cost_calculator import CostCalculator, cost_calculator


@pytest.mark.unit
class TestCostCalculator:
    """Test suite for CostCalculator class"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock database manager"""
        with patch("neos.utils.cost_calculator.db_manager") as mock_db:
            yield mock_db

    # ==================== Pricing Retrieval Tests ====================

    @pytest.mark.asyncio
    async def test_get_model_pricing_from_db(self, mock_db_manager):
        """Test successful pricing retrieval from database"""
        # Mock DB response
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(
                2.50,  # input_price_per_1m
                10.00,  # output_price_per_1m
                3.75,  # cache_creation_price_per_1m
                0.30,  # cache_read_price_per_1m
            )
        )

        pricing = await CostCalculator.get_model_pricing("openai", "gpt-4o")

        assert pricing is not None
        assert pricing["input"] == Decimal("2.50")
        assert pricing["output"] == Decimal("10.00")
        assert pricing["cache_creation"] == Decimal("3.75")
        assert pricing["cache_read"] == Decimal("0.30")

    @pytest.mark.asyncio
    async def test_get_model_pricing_fallback_to_default(self, mock_db_manager):
        """Test fallback to default pricing when DB returns None"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        pricing = await CostCalculator.get_model_pricing("openai", "gpt-4o")

        assert pricing is not None
        assert pricing["input"] == Decimal("2.50")
        assert pricing["output"] == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_get_model_pricing_db_error_fallback(self, mock_db_manager):
        """Test fallback to default pricing when DB query fails"""
        mock_db_manager.fetch_one = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        pricing = await CostCalculator.get_model_pricing("anthropic", "claude-sonnet-4-5-20250929")

        assert pricing is not None
        assert pricing["input"] == Decimal("3.00")
        assert pricing["output"] == Decimal("15.00")
        assert pricing["cache_creation"] == Decimal("3.75")
        assert pricing["cache_read"] == Decimal("0.30")

    @pytest.mark.asyncio
    async def test_get_model_pricing_unknown_model(self, mock_db_manager):
        """Test pricing retrieval for unknown model"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        pricing = await CostCalculator.get_model_pricing("unknown", "unknown-model")

        assert pricing is None

    def test_get_default_pricing_openai_gpt4o(self):
        """Test default pricing for OpenAI GPT-4o"""
        pricing = CostCalculator._get_default_pricing("openai", "gpt-4o")

        assert pricing is not None
        assert pricing["input"] == Decimal("2.50")
        assert pricing["output"] == Decimal("10.00")

    def test_get_default_pricing_openai_gpt4o_mini(self):
        """Test default pricing for OpenAI GPT-4o mini"""
        pricing = CostCalculator._get_default_pricing("openai", "gpt-4o-mini")

        assert pricing is not None
        assert pricing["input"] == Decimal("0.15")
        assert pricing["output"] == Decimal("0.60")

    def test_get_default_pricing_is_derived_from_the_model_catalog(self):
        from neos.config.model_config import pricing_for

        for provider, model in (
            ("anthropic", "claude-sonnet-5"),
            ("anthropic", "claude-opus-5"),
            ("openai", "gpt-5.6-terra"),
            ("openai", "gpt-5.6-sol"),
        ):
            catalog_pricing = pricing_for(provider, model)
            assert catalog_pricing is not None

            pricing = CostCalculator._get_default_pricing(provider, model)

            assert pricing is not None
            assert pricing["input"] == Decimal(str(catalog_pricing.input))
            assert pricing["output"] == Decimal(str(catalog_pricing.output))

    def test_get_default_pricing_current_model_values(self):
        anthropic_sonnet = CostCalculator._get_default_pricing(
            "anthropic", "claude-sonnet-5"
        )
        anthropic_opus = CostCalculator._get_default_pricing("anthropic", "claude-opus-5")
        openai_terra = CostCalculator._get_default_pricing("openai", "gpt-5.6-terra")
        openai_sol = CostCalculator._get_default_pricing("openai", "gpt-5.6-sol")

        assert anthropic_sonnet["input"] == Decimal("3.00")
        assert anthropic_sonnet["output"] == Decimal("15.00")
        assert anthropic_opus["input"] == Decimal("5.00")
        assert anthropic_opus["output"] == Decimal("25.00")
        assert openai_terra["input"] == Decimal("2.50")
        assert openai_terra["output"] == Decimal("15.00")
        assert openai_sol["input"] == Decimal("5.00")
        assert openai_sol["output"] == Decimal("30.00")

    def test_get_default_pricing_ignores_provider_mismatch(self):
        """provider가 어긋난 조회는 가격을 주지 않는다."""
        assert CostCalculator._get_default_pricing("openai", "claude-sonnet-5") is None
        assert CostCalculator._get_default_pricing("anthropic", "gpt-4o") is None

    def test_get_default_pricing_warns_for_unpriced_catalog_model(self, caplog):
        """카탈로그에 있지만 가격이 없는 모델은 경고 후 None (spec §6).

        `gpt-4-turbo-preview`는 `aliases.llm.gpt4`가 가리키는 레거시 별칭
        대상이라 카탈로그에 있지만 가격이 없다. 선택 가능한 모델 중에는
        이런 경우가 없어야 하며, 그 불변식은 별도로 지켜진다
        (`test_model_catalog_parity.py::test_every_selectable_model_is_priced`).
        """
        with caplog.at_level("WARNING", logger="neos.utils.cost_calculator"):
            pricing = CostCalculator._get_default_pricing("openai", "gpt-4-turbo-preview")

        assert pricing is None
        assert any(
            "gpt-4-turbo-preview" in record.message for record in caplog.records
        )

    def test_default_pricing_table_is_gone(self):
        """가격 하드코딩이 shim으로도 남지 않는다."""
        assert not hasattr(CostCalculator, "DEFAULT_PRICING")

    def test_get_default_pricing_anthropic_claude_sonnet(self):
        """Test default pricing for Anthropic Claude Sonnet"""
        pricing = CostCalculator._get_default_pricing("anthropic", "claude-sonnet-4-5-20250929")

        assert pricing is not None
        assert pricing["input"] == Decimal("3.00")
        assert pricing["output"] == Decimal("15.00")
        assert pricing["cache_creation"] == Decimal("3.75")
        assert pricing["cache_read"] == Decimal("0.30")

    def test_get_default_pricing_anthropic_claude_opus(self):
        """Test default pricing for Anthropic Claude Opus"""
        pricing = CostCalculator._get_default_pricing("anthropic", "claude-opus-4-5-20251101")

        assert pricing is not None
        assert pricing["input"] == Decimal("15.00")
        assert pricing["output"] == Decimal("75.00")
        assert pricing["cache_creation"] == Decimal("18.75")
        assert pricing["cache_read"] == Decimal("1.50")

    def test_get_default_pricing_anthropic_claude_haiku(self):
        """Haiku 가격은 카탈로그가 정한다.

        🔴 **병합 시 값이 갈렸다 (CA6, 2026-08-29).** 이 테스트는 원래
        1.00/5.00/1.25/0.10 을 단언했고 `models.yaml` 은 0.25/1.25/0.30/0.03 이다.
        둘 중 하나는 틀렸지만 **저장소 안에서는 어느 쪽인지 확인할 수 없다.**
        카탈로그를 따르는 이유는 그것이 모델 사실의 단일 원천이기 때문이지
        그 수가 옳다고 확인해서가 아니다 -- 확인되면 `models.yaml` 을 고치고
        이 주석을 지운다.
        """
        pricing = CostCalculator._get_default_pricing("anthropic", "claude-haiku-4-5-20251001")

        assert pricing is not None
        assert pricing["input"] == Decimal("0.25")
        assert pricing["output"] == Decimal("1.25")
        assert pricing["cache_creation"] == Decimal("0.30")
        assert pricing["cache_read"] == Decimal("0.03")

    def test_get_default_pricing_unknown_provider(self):
        """Test default pricing for unknown provider"""
        pricing = CostCalculator._get_default_pricing("unknown-provider", "some-model")

        assert pricing is None

    def test_get_default_pricing_unknown_model(self):
        """Test default pricing for unknown model within known provider"""
        pricing = CostCalculator._get_default_pricing("openai", "unknown-model")

        assert pricing is None

    # ==================== Cost Calculation Tests ====================

    @pytest.mark.asyncio
    async def test_calculate_cost_basic(self, mock_db_manager):
        """Test basic cost calculation without cache"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        # GPT-4o: input $2.50/1M, output $10.00/1M
        # 1000 prompt tokens, 500 completion tokens
        cost_info = await CostCalculator.calculate_cost(
            provider="openai",
            model_name="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
        )

        # Expected: (1000 * 2.50) / 1M + (500 * 10.00) / 1M
        expected_input = Decimal("0.0025")  # $0.0025
        expected_output = Decimal("0.005")  # $0.005
        expected_total = Decimal("0.0075")  # $0.0075

        assert cost_info["input_cost"] == expected_input
        assert cost_info["output_cost"] == expected_output
        assert cost_info["cache_creation_cost"] == Decimal("0")
        assert cost_info["cache_read_cost"] == Decimal("0")
        assert cost_info["total_cost"] == expected_total

    @pytest.mark.asyncio
    async def test_calculate_cost_with_cache(self, mock_db_manager):
        """Test cost calculation with cache tokens"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        # Claude Sonnet: input $3.00/1M, output $15.00/1M, cache_creation $3.75/1M, cache_read $0.30/1M
        cost_info = await CostCalculator.calculate_cost(
            provider="anthropic",
            model_name="claude-sonnet-4-5-20250929",
            prompt_tokens=2000,
            completion_tokens=1000,
            cache_creation_tokens=5000,
            cache_read_tokens=10000,
        )

        # Expected calculations:
        # input: (2000 * 3.00) / 1M = 0.006
        # output: (1000 * 15.00) / 1M = 0.015
        # cache_creation: (5000 * 3.75) / 1M = 0.01875
        # cache_read: (10000 * 0.30) / 1M = 0.003
        # total: 0.04275

        expected_input = Decimal("0.006")
        expected_output = Decimal("0.015")
        expected_cache_creation = Decimal("0.01875")
        expected_cache_read = Decimal("0.003")
        expected_total = Decimal("0.04275")

        assert cost_info["input_cost"] == expected_input
        assert cost_info["output_cost"] == expected_output
        assert cost_info["cache_creation_cost"] == expected_cache_creation
        assert cost_info["cache_read_cost"] == expected_cache_read
        assert cost_info["total_cost"] == expected_total

    @pytest.mark.asyncio
    async def test_one_hour_cache_creation_uses_twice_input_price(self, mock_db_manager):
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        cost = await CostCalculator.calculate_cost(
            provider="anthropic",
            model_name="claude-sonnet-5",
            prompt_tokens=0,
            completion_tokens=0,
            cache_creation_tokens=1_000_000,
            cache_ttl="1h",
        )

        assert cost["cache_creation_cost"] == Decimal("6.00")

    @pytest.mark.asyncio
    async def test_calculate_cost_zero_tokens(self, mock_db_manager):
        """Test cost calculation with zero tokens"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        cost_info = await CostCalculator.calculate_cost(
            provider="openai",
            model_name="gpt-4o",
            prompt_tokens=0,
            completion_tokens=0,
        )

        assert cost_info["input_cost"] == Decimal("0")
        assert cost_info["output_cost"] == Decimal("0")
        assert cost_info["total_cost"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_calculate_cost_large_numbers(self, mock_db_manager):
        """Test cost calculation with large token counts"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        # Test with 1M tokens (edge case)
        cost_info = await CostCalculator.calculate_cost(
            provider="openai",
            model_name="gpt-4o",
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
        )

        # Expected: (1M * 2.50) / 1M + (500K * 10.00) / 1M
        expected_input = Decimal("2.50")
        expected_output = Decimal("5.00")
        expected_total = Decimal("7.50")

        assert cost_info["input_cost"] == expected_input
        assert cost_info["output_cost"] == expected_output
        assert cost_info["total_cost"] == expected_total

    @pytest.mark.asyncio
    async def test_calculate_cost_no_pricing(self, mock_db_manager):
        """Test cost calculation when no pricing is available"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        cost_info = await CostCalculator.calculate_cost(
            provider="unknown",
            model_name="unknown-model",
            prompt_tokens=1000,
            completion_tokens=500,
        )

        # Should return zeros when no pricing available
        assert cost_info["input_cost"] == Decimal("0")
        assert cost_info["output_cost"] == Decimal("0")
        assert cost_info["total_cost"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_calculate_cost_decimal_precision(self, mock_db_manager):
        """Test that cost calculations maintain decimal precision"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        # Use small numbers to test precision
        cost_info = await CostCalculator.calculate_cost(
            provider="openai",
            model_name="gpt-4o-mini",  # Cheapest model
            prompt_tokens=1,
            completion_tokens=1,
        )

        # GPT-4o-mini: input $0.15/1M, output $0.60/1M
        # Expected: (1 * 0.15) / 1M + (1 * 0.60) / 1M
        expected_input = Decimal("0.00000015")
        expected_output = Decimal("0.00000060")
        expected_total = Decimal("0.00000075")

        assert cost_info["input_cost"] == expected_input
        assert cost_info["output_cost"] == expected_output
        assert cost_info["total_cost"] == expected_total

    # ==================== Message Cost Recording Tests ====================

    @pytest.mark.asyncio
    async def test_record_message_cost_success(self, mock_db_manager):
        """Test successful message cost recording"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)

        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_123",
            conversation_id="conv_456",
            provider="openai",
            model_name="gpt-4o",
            model_version="2024-05-13",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            latency_ms=1234,
            finish_reason="stop",
        )

        # Verify cost was calculated
        assert cost_info["total_cost"] > Decimal("0")
        assert cost_info["input_cost"] == Decimal("0.0025")
        assert cost_info["output_cost"] == Decimal("0.005")

        # Verify DB insert was called
        mock_db_manager.execute.assert_called_once()
        call_args = mock_db_manager.execute.call_args
        assert call_args[0][1] == "msg_123"  # message_id
        assert call_args[0][2] == "conv_456"  # conversation_id

    @pytest.mark.asyncio
    async def test_record_message_cost_with_cache(self, mock_db_manager):
        """Test message cost recording with cache tokens"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)

        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_123",
            conversation_id="conv_456",
            provider="anthropic",
            model_name="claude-sonnet-4-5-20250929",
            model_version="2025-09-29",
            prompt_tokens=2000,
            completion_tokens=1000,
            total_tokens=3000,
            cache_creation_tokens=5000,
            cache_read_tokens=10000,
        )

        # Verify cache costs are included
        assert cost_info["cache_creation_cost"] > Decimal("0")
        assert cost_info["cache_read_cost"] > Decimal("0")
        assert cost_info["total_cost"] == (
            cost_info["input_cost"]
            + cost_info["output_cost"]
            + cost_info["cache_creation_cost"]
            + cost_info["cache_read_cost"]
        )

    @pytest.mark.asyncio
    async def test_record_message_cost_adds_additional_cost_once(self, mock_db_manager):
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)
        metadata = {"advisor": {"call_count": 1}}

        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_advisor",
            conversation_id="conv_advisor",
            provider="anthropic",
            model_name="claude-sonnet-5",
            model_version=None,
            prompt_tokens=1_000_000,
            completion_tokens=0,
            total_tokens=1_000_000,
            additional_cost_usd=Decimal("2.00"),
            metadata=metadata,
        )

        assert cost_info["input_cost"] == Decimal("3.00")
        assert cost_info["additional_cost_usd"] == Decimal("2.00")
        assert cost_info["total_cost"] == Decimal("5.00")
        execute_args = mock_db_manager.execute.call_args.args
        assert Decimal(str(execute_args[15])) == Decimal("5.00")
        assert json.loads(execute_args[20])["additional_cost_usd"] == 2.0
        assert metadata == {"advisor": {"call_count": 1}}

    @pytest.mark.asyncio
    async def test_record_message_cost_foreign_key_violation(self, mock_db_manager):
        """Test graceful handling of foreign key violation"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(
            side_effect=Exception("ForeignKeyViolationError: message_costs_message_id_fkey")
        )

        # Should not raise exception, just log warning
        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_nonexistent",
            conversation_id="conv_456",
            provider="openai",
            model_name="gpt-4o",
            model_version="2024-05-13",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
        )

        # Cost should still be calculated and returned
        assert cost_info["total_cost"] > Decimal("0")

    @pytest.mark.asyncio
    async def test_record_message_cost_db_error(self, mock_db_manager):
        """Test handling of database errors during cost recording"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        # Should not raise exception
        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_123",
            conversation_id="conv_456",
            provider="openai",
            model_name="gpt-4o",
            model_version="2024-05-13",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
        )

        # Cost should still be calculated
        assert cost_info["total_cost"] > Decimal("0")

    @pytest.mark.asyncio
    async def test_record_cost_for_existing_message(self, mock_db_manager):
        """Test recording cost for existing message"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)

        cost_info = await CostCalculator.record_cost_for_existing_message(
            message_id="msg_existing",
            conversation_id="conv_789",
            provider="openai",
            model_name="gpt-3.5-turbo",
            prompt_tokens=500,
            completion_tokens=250,
            total_tokens=750,
            latency_ms=500,
            finish_reason="stop",
        )

        assert cost_info is not None
        assert cost_info["total_cost"] > Decimal("0")

    @pytest.mark.asyncio
    async def test_record_existing_message_forwards_composite_billing(self, mock_db_manager):
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)

        cost_info = await CostCalculator.record_cost_for_existing_message(
            message_id="msg_existing",
            conversation_id="conv_789",
            provider="anthropic",
            model_name="claude-sonnet-5",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
            cache_ttl="1h",
            additional_cost_usd=Decimal("2.00"),
            metadata={"advisor": {"call_count": 1}},
        )

        assert cost_info is not None
        assert cost_info["cache_creation_cost"] == Decimal("6.00")
        assert cost_info["additional_cost_usd"] == Decimal("2.00")
        assert cost_info["total_cost"] == Decimal("8.00")

    # ==================== Conversation Cost Summary Tests ====================

    @pytest.mark.asyncio
    async def test_get_conversation_cost_summary_success(self, mock_db_manager):
        """Test successful conversation cost summary retrieval"""
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(
                5,  # total_messages
                5000,  # total_prompt_tokens
                2500,  # total_completion_tokens
                7500,  # total_tokens
                0.0125,  # total_input_cost
                0.025,  # total_output_cost
                0.0375,  # total_cost
                1200,  # avg_latency_ms
            )
        )

        summary = await CostCalculator.get_conversation_cost_summary("conv_123")

        assert summary is not None
        assert summary["total_messages"] == 5
        assert summary["total_prompt_tokens"] == 5000
        assert summary["total_completion_tokens"] == 2500
        assert summary["total_tokens"] == 7500
        assert summary["total_input_cost"] == 0.0125
        assert summary["total_output_cost"] == 0.025
        assert summary["total_cost"] == 0.0375
        assert summary["avg_latency_ms"] == 1200

    @pytest.mark.asyncio
    async def test_get_conversation_cost_summary_no_data(self, mock_db_manager):
        """Test conversation cost summary when no data exists"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        summary = await CostCalculator.get_conversation_cost_summary("conv_nonexistent")

        assert summary is None

    @pytest.mark.asyncio
    async def test_get_conversation_cost_summary_zero_messages(self, mock_db_manager):
        """Test conversation cost summary with zero messages"""
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(0, None, None, None, None, None, None, None)
        )

        summary = await CostCalculator.get_conversation_cost_summary("conv_empty")

        assert summary is None

    # ==================== User Cost Summary Tests ====================

    @pytest.mark.asyncio
    async def test_get_user_cost_summary_daily(self, mock_db_manager):
        """Test user cost summary retrieval for daily period"""
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(
                "2025-11-18 00:00:00",  # period_start
                "2025-11-18 23:59:59",  # period_end
                25,  # total_messages
                5,  # total_conversations
                50000,  # total_prompt_tokens
                25000,  # total_completion_tokens
                75000,  # total_tokens
                0.5,  # total_cost
                0.2,  # input_cost
                0.3,  # output_cost
                {"openai": 0.3, "anthropic": 0.2},  # cost_by_provider
                {"gpt-4o": 15, "claude-sonnet": 10},  # usage_by_model
            )
        )

        summary = await CostCalculator.get_user_cost_summary("user_123", "daily")

        assert summary is not None
        assert summary["total_messages"] == 25
        assert summary["total_conversations"] == 5
        assert summary["total_cost"] == 0.5
        assert summary["cost_by_provider"] == {"openai": 0.3, "anthropic": 0.2}

    @pytest.mark.asyncio
    async def test_get_user_cost_summary_monthly(self, mock_db_manager):
        """Test user cost summary retrieval for monthly period"""
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(
                "2025-11-01 00:00:00",
                "2025-11-30 23:59:59",
                500,
                50,
                1000000,
                500000,
                1500000,
                50.0,
                20.0,
                30.0,
                {"openai": 30.0, "anthropic": 20.0},
                {"gpt-4o": 300, "claude-sonnet": 200},
            )
        )

        summary = await CostCalculator.get_user_cost_summary("user_123", "monthly")

        assert summary is not None
        assert summary["total_messages"] == 500
        assert summary["total_cost"] == 50.0

    @pytest.mark.asyncio
    async def test_get_user_cost_summary_no_data(self, mock_db_manager):
        """Test user cost summary when no data exists"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        summary = await CostCalculator.get_user_cost_summary("user_nonexistent", "daily")

        assert summary is None

    @pytest.mark.asyncio
    async def test_update_user_cost_summary_success(self, mock_db_manager):
        """Test successful user cost summary update"""
        mock_db_manager.execute = AsyncMock(return_value=None)

        # Should not raise exception
        await CostCalculator.update_user_cost_summary("user_123", "daily")

        mock_db_manager.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_user_cost_summary_error(self, mock_db_manager):
        """Test handling of errors during cost summary update"""
        mock_db_manager.execute = AsyncMock(
            side_effect=Exception("Database error")
        )

        # Should not raise exception, just log error
        await CostCalculator.update_user_cost_summary("user_123", "daily")

    # ==================== Global Instance Test ====================

    def test_cost_calculator_global_instance(self):
        """Test that global cost_calculator instance exists"""
        assert cost_calculator is not None
        assert isinstance(cost_calculator, CostCalculator)

    # ==================== Edge Cases and Validation ====================

    @pytest.mark.asyncio
    async def test_calculate_cost_negative_tokens(self, mock_db_manager):
        """Test cost calculation with negative token counts (invalid input)"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)

        # Note: Current implementation doesn't validate negative tokens
        # This test documents expected behavior - might want to add validation
        cost_info = await CostCalculator.calculate_cost(
            provider="openai",
            model_name="gpt-4o",
            prompt_tokens=-100,
            completion_tokens=-50,
        )

        # Currently returns negative costs - might want to add validation
        assert cost_info["input_cost"] < Decimal("0")
        assert cost_info["output_cost"] < Decimal("0")

    @pytest.mark.asyncio
    async def test_pricing_with_null_cache_prices(self, mock_db_manager):
        """Test pricing retrieval when cache prices are NULL in DB"""
        mock_db_manager.fetch_one = AsyncMock(
            return_value=(
                2.50,  # input_price_per_1m
                10.00,  # output_price_per_1m
                None,  # cache_creation_price_per_1m (NULL)
                None,  # cache_read_price_per_1m (NULL)
            )
        )

        pricing = await CostCalculator.get_model_pricing("openai", "some-model")

        assert pricing is not None
        assert pricing["cache_creation"] == Decimal("0")
        assert pricing["cache_read"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_record_message_cost_with_metadata(self, mock_db_manager):
        """Test message cost recording with custom metadata"""
        mock_db_manager.fetch_one = AsyncMock(return_value=None)
        mock_db_manager.execute = AsyncMock(return_value=None)

        metadata = {
            "request_id": "req_123",
            "user_id": "user_456",
            "session_id": "session_789",
        }

        cost_info = await CostCalculator.record_message_cost(
            message_id="msg_123",
            conversation_id="conv_456",
            provider="openai",
            model_name="gpt-4o",
            model_version="2024-05-13",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            metadata=metadata,
        )

        assert cost_info is not None
        # Verify metadata was passed to DB
        call_args = mock_db_manager.execute.call_args
        assert '"request_id": "req_123"' in call_args[0][20]
