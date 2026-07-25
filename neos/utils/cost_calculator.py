"""
LLM 비용 계산 유틸리티

실시간으로 LLM 호출 비용을 계산하고 DB에 기록합니다.
"""

from typing import Dict, Any, Optional
from decimal import Decimal

from neos.database.connection import db_manager
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class CostCalculator:
    """LLM 비용 계산기"""

    # 모델별 기본 가격 (USD per 1M tokens) - DB 조회 실패 시 fallback
    DEFAULT_PRICING = {
        "openai": {
            "gpt-5.6-terra": {"input": 2.50, "output": 15.00},
            "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4-turbo": {"input": 10.00, "output": 30.00},
            "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        },
        "anthropic": {
            "claude-sonnet-5": {
                "input": 3.00,
                "output": 15.00,
                "cache_creation": 3.75,
                "cache_read": 0.30,
            },
            "claude-opus-5": {
                "input": 5.00,
                "output": 25.00,
                "cache_creation": 6.25,
                "cache_read": 0.50,
            },
            "claude-sonnet-4-5-20250929": {
                "input": 3.00,
                "output": 15.00,
                "cache_creation": 3.75,
                "cache_read": 0.30,
            },
            "claude-3-5-sonnet-20240620": {
                "input": 3.00,
                "output": 15.00,
                "cache_creation": 3.75,
                "cache_read": 0.30,
            },
            "claude-opus-4-5-20251101": {
                "input": 15.00,
                "output": 75.00,
                "cache_creation": 18.75,
                "cache_read": 1.50,
            },
            "claude-haiku-4-5-20251001": {
                "input": 0.25,
                "output": 1.25,
                "cache_creation": 0.30,
                "cache_read": 0.03,
            },
        },
    }

    @staticmethod
    async def get_model_pricing(
        provider: str, model_name: str
    ) -> Optional[Dict[str, Decimal]]:
        """
        DB에서 모델 가격 정보 조회

        Returns:
            {"input": Decimal, "output": Decimal, "cache_creation": Decimal, "cache_read": Decimal}
        """
        try:
            query = """
            SELECT
                input_price_per_1m,
                output_price_per_1m,
                cache_creation_price_per_1m,
                cache_read_price_per_1m
            FROM llm_model_pricing
            WHERE provider = $1
              AND model_name = $2
              AND is_active = TRUE
              AND effective_from <= CURRENT_TIMESTAMP
              AND (effective_until IS NULL OR effective_until > CURRENT_TIMESTAMP)
            ORDER BY effective_from DESC
            LIMIT 1
            """

            row = await db_manager.fetch_one(query, provider, model_name)

            if row:
                return {
                    "input": Decimal(str(row[0])) if row[0] else Decimal("0"),
                    "output": Decimal(str(row[1])) if row[1] else Decimal("0"),
                    "cache_creation": Decimal(str(row[2]))
                    if row[2]
                    else Decimal("0"),
                    "cache_read": Decimal(str(row[3])) if row[3] else Decimal("0"),
                }

            # DB에 없으면 기본값 사용
            return CostCalculator._get_default_pricing(provider, model_name)

        except Exception as e:
            logger.warning(
                f"Failed to get pricing from DB for {provider}/{model_name}: {e}"
            )
            return CostCalculator._get_default_pricing(provider, model_name)

    @staticmethod
    def _get_default_pricing(
        provider: str, model_name: str
    ) -> Optional[Dict[str, Decimal]]:
        """기본 가격 정보 반환"""
        if provider in CostCalculator.DEFAULT_PRICING:
            if model_name in CostCalculator.DEFAULT_PRICING[provider]:
                pricing = CostCalculator.DEFAULT_PRICING[provider][model_name]
                return {
                    "input": Decimal(str(pricing.get("input", 0))),
                    "output": Decimal(str(pricing.get("output", 0))),
                    "cache_creation": Decimal(str(pricing.get("cache_creation", 0))),
                    "cache_read": Decimal(str(pricing.get("cache_read", 0))),
                }

        logger.warning(f"No pricing found for {provider}/{model_name}")
        return None

    @staticmethod
    async def calculate_cost(
        provider: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> Dict[str, Any]:
        """
        토큰 사용량 기반 비용 계산

        Returns:
            {
                "input_cost": Decimal,
                "output_cost": Decimal,
                "cache_creation_cost": Decimal,
                "cache_read_cost": Decimal,
                "total_cost": Decimal,
                "input_price_per_1m": Decimal,
                "output_price_per_1m": Decimal
            }
        """
        pricing = await CostCalculator.get_model_pricing(provider, model_name)

        if not pricing:
            logger.error(f"Cannot calculate cost: no pricing for {provider}/{model_name}")
            return {
                "input_cost": Decimal("0"),
                "output_cost": Decimal("0"),
                "cache_creation_cost": Decimal("0"),
                "cache_read_cost": Decimal("0"),
                "total_cost": Decimal("0"),
                "input_price_per_1m": Decimal("0"),
                "output_price_per_1m": Decimal("0"),
            }

        # 비용 계산 (USD) = (tokens * price_per_1m) / 1,000,000
        input_cost = (Decimal(str(prompt_tokens)) * pricing["input"]) / Decimal(
            "1000000"
        )
        output_cost = (Decimal(str(completion_tokens)) * pricing["output"]) / Decimal(
            "1000000"
        )
        cache_creation_cost = (
            Decimal(str(cache_creation_tokens)) * pricing["cache_creation"]
        ) / Decimal("1000000")
        cache_read_cost = (
            Decimal(str(cache_read_tokens)) * pricing["cache_read"]
        ) / Decimal("1000000")

        total_cost = input_cost + output_cost + cache_creation_cost + cache_read_cost

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "cache_creation_cost": cache_creation_cost,
            "cache_read_cost": cache_read_cost,
            "total_cost": total_cost,
            "input_price_per_1m": pricing["input"],
            "output_price_per_1m": pricing["output"],
        }

    @staticmethod
    async def record_message_cost(
        message_id: str,
        conversation_id: str,
        provider: str,
        model_name: str,
        model_version: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: Optional[int] = None,
        finish_reason: Optional[str] = None,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        메시지 비용을 계산하고 DB에 기록

        Returns:
            비용 정보 딕셔너리
        """
        # 비용 계산
        cost_info = await CostCalculator.calculate_cost(
            provider=provider,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )

        # DB에 기록
        # Note: This might fail if the message hasn't been saved yet due to FK constraint
        # In that case, the cost info is still returned and stored in message metadata
        try:
            import json

            query = """
            INSERT INTO message_costs (
                message_id,
                conversation_id,
                provider,
                model_name,
                model_version,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                input_cost,
                output_cost,
                cache_creation_cost,
                cache_read_cost,
                total_cost,
                input_price_per_1m,
                output_price_per_1m,
                latency_ms,
                finish_reason,
                metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
            RETURNING id
            """

            await db_manager.execute(
                query,
                message_id,
                conversation_id,
                provider,
                model_name,
                model_version,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                float(cost_info["input_cost"]),
                float(cost_info["output_cost"]),
                float(cost_info["cache_creation_cost"]),
                float(cost_info["cache_read_cost"]),
                float(cost_info["total_cost"]),
                float(cost_info["input_price_per_1m"]),
                float(cost_info["output_price_per_1m"]),
                latency_ms,
                finish_reason,
                json.dumps(metadata or {}),
            )

            logger.info(
                f"Recorded cost for message {message_id}: ${cost_info['total_cost']:.6f}"
            )

        except Exception as e:
            # If foreign key constraint fails, it's likely because the message
            # hasn't been saved yet. This is OK - cost is already in message metadata.
            if "ForeignKeyViolationError" in str(e) or "message_costs_message_id_fkey" in str(e):
                logger.debug(
                    f"Message {message_id} not found when recording cost (will be in metadata): ${cost_info['total_cost']:.6f}"
                )
            else:
                logger.error(f"Failed to record message cost: {e}")

        return cost_info

    @staticmethod
    async def record_cost_for_existing_message(
        message_id: str,
        conversation_id: str,
        provider: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: Optional[int] = None,
        finish_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        이미 저장된 메시지에 대해 비용을 기록
        (메시지 저장 후 호출하여 FK 제약 위반 방지)
        """
        return await CostCalculator.record_message_cost(
            message_id=message_id,
            conversation_id=conversation_id,
            provider=provider,
            model_name=model_name,
            model_version=None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )

    @staticmethod
    async def get_conversation_cost_summary(
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """대화의 총 비용 조회"""
        query = """
        SELECT
            COUNT(*) as total_messages,
            SUM(prompt_tokens) as total_prompt_tokens,
            SUM(completion_tokens) as total_completion_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(input_cost) as total_input_cost,
            SUM(output_cost) as total_output_cost,
            SUM(total_cost) as total_cost,
            AVG(latency_ms) as avg_latency_ms
        FROM message_costs
        WHERE conversation_id = $1
        """

        row = await db_manager.fetch_one(query, conversation_id)

        if not row or row[0] == 0:
            return None

        return {
            "total_messages": row[0],
            "total_prompt_tokens": row[1] or 0,
            "total_completion_tokens": row[2] or 0,
            "total_tokens": row[3] or 0,
            "total_input_cost": float(row[4]) if row[4] else 0.0,
            "total_output_cost": float(row[5]) if row[5] else 0.0,
            "total_cost": float(row[6]) if row[6] else 0.0,
            "avg_latency_ms": int(row[7]) if row[7] else 0,
        }

    @staticmethod
    async def get_user_cost_summary(
        user_id: str, period_type: str = "daily"
    ) -> Optional[Dict[str, Any]]:
        """사용자의 기간별 비용 조회"""
        query = """
        SELECT
            period_start,
            period_end,
            total_messages,
            total_conversations,
            total_prompt_tokens,
            total_completion_tokens,
            total_tokens,
            total_cost,
            input_cost,
            output_cost,
            cost_by_provider,
            usage_by_model
        FROM user_cost_summary
        WHERE user_id = $1 AND period_type = $2
        ORDER BY period_start DESC
        LIMIT 1
        """

        row = await db_manager.fetch_one(query, user_id, period_type)

        if not row:
            return None

        return {
            "period_start": row[0],
            "period_end": row[1],
            "total_messages": row[2],
            "total_conversations": row[3],
            "total_prompt_tokens": row[4] or 0,
            "total_completion_tokens": row[5] or 0,
            "total_tokens": row[6] or 0,
            "total_cost": float(row[7]) if row[7] else 0.0,
            "input_cost": float(row[8]) if row[8] else 0.0,
            "output_cost": float(row[9]) if row[9] else 0.0,
            "cost_by_provider": row[10] or {},
            "usage_by_model": row[11] or {},
        }

    @staticmethod
    async def update_user_cost_summary(
        user_id: str, period_type: str = "daily"
    ) -> None:
        """사용자 비용 집계 업데이트"""
        try:
            query = "SELECT update_user_cost_summary($1, $2)"
            await db_manager.execute(query, user_id, period_type)
            logger.info(
                f"Updated cost summary for user {user_id}, period: {period_type}"
            )
        except Exception as e:
            logger.error(f"Failed to update user cost summary: {e}")


# 전역 인스턴스
cost_calculator = CostCalculator()
