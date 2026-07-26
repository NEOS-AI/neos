"""Enhanced token counting utility for context optimization.

Provides accurate token counting with support for multiple models and
context overflow detection.
"""

from typing import Dict, Any, List, Optional, Union
import logging
from neos.config.model_config import get_model_spec
from neos.config.settings import settings

logger = logging.getLogger(__name__)


def estimate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """모델 카탈로그 가격으로 비용을 추정한다 (USD).

    가격의 단일 원천은 `neos/config/models.yaml`이다. 가격을 모르면 추측하지
    않고 경고 후 0.0을 돌려준다 — 틀린 가격은 없는 가격보다 나쁘다. 그럴듯한
    숫자는 아무도 의심하지 않는 반면, 0과 경고는 눈에 띈다.

    이 함수는 추정 전용이다. 과금 경로는 `CostCalculator`이며 DB 가격을
    최우선으로 쓴다.
    """
    spec = get_model_spec(model)
    pricing = spec.pricing if spec is not None else None

    if pricing is None:
        logger.warning(
            "No catalog pricing for model %r; estimating cost as 0.0. "
            "Add it to neos/config/models.yaml to get real estimates.",
            model,
        )
        return 0.0

    return (
        prompt_tokens * pricing.input + completion_tokens * pricing.output
    ) / 1_000_000


class TokenCounter:
    """Enhanced token counter with context overflow detection."""

    def __init__(self, model_name: Optional[str] = None):
        """Initialize token counter.

        Args:
            model_name: Model name for encoding selection. Uses settings if not provided.
        """
        self.model_name = model_name or settings.TOKEN_COUNTER_MODEL
        self.encoding = None
        self._init_encoding()

    def _init_encoding(self) -> None:
        """Initialize tiktoken encoding with fallback."""
        if not settings.USE_TIKTOKEN:
            logger.info("[TokenCounter] tiktoken disabled in settings, using approximation")
            return

        try:
            import tiktoken

            # Claude 모델의 경우 gpt-4 인코더 사용 (유사한 토큰화)
            if "claude" in self.model_name.lower():
                encoding_model = "gpt-4"
            else:
                encoding_model = self.model_name

            self.encoding = tiktoken.encoding_for_model(encoding_model)
            logger.info(f"[TokenCounter] Initialized tiktoken for {self.model_name}")
        except ImportError:
            logger.warning("[TokenCounter] tiktoken not installed, using approximation. Install with: pip install tiktoken")
            self.encoding = None
        except Exception as e:
            logger.warning(f"[TokenCounter] Failed to initialize tiktoken: {e}, using approximation")
            self.encoding = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Number of tokens
        """
        if not text:
            return 0

        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception as e:
                logger.warning(f"[TokenCounter] Encoding error: {e}, using approximation")
                return self._approximate_tokens(text)
        else:
            return self._approximate_tokens(text)

    def _approximate_tokens(self, text: str) -> int:
        """Approximate token count when tiktoken unavailable.

        Uses ~4 characters per token as rough estimate.

        Args:
            text: Text to estimate tokens for

        Returns:
            Approximate token count
        """
        return len(text) // 4

    def count_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens in message list with proper formatting overhead.

        Args:
            messages: List of message dictionaries with 'role' and 'content'

        Returns:
            Total token count including formatting overhead
        """
        total = 0

        for message in messages:
            if isinstance(message, dict):
                # Count role
                role = message.get('role', '')
                total += self.count_tokens(role)

                # Count content (can be string or list for multi-modal)
                content = message.get('content', '')
                if isinstance(content, str):
                    total += self.count_tokens(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get('type') == 'text':
                                total += self.count_tokens(item.get('text', ''))
                            elif item.get('type') == 'image':
                                # Image tokens (rough estimate for Claude/GPT-4V)
                                total += 765  # Average for standard image
                        else:
                            total += self.count_tokens(str(item))

                # Count tool calls/results
                if 'tool_calls' in message:
                    total += self._count_tool_calls_tokens(message['tool_calls'])

                if 'tool_call_id' in message:
                    total += self.count_tokens(message.get('tool_call_id', ''))
            else:
                total += self.count_tokens(str(message))

        # Add overhead for message formatting
        # Each message has formatting tokens for role markers, etc.
        total += len(messages) * 4

        return total

    def _count_tool_calls_tokens(self, tool_calls: List[Dict[str, Any]]) -> int:
        """Count tokens in tool calls.

        Args:
            tool_calls: List of tool call dictionaries

        Returns:
            Total tokens in tool calls
        """
        total = 0
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                # Function name
                if 'function' in tool_call:
                    total += self.count_tokens(tool_call['function'].get('name', ''))
                    total += self.count_tokens(str(tool_call['function'].get('arguments', '')))
                # Tool call ID
                total += self.count_tokens(tool_call.get('id', ''))
        return total

    def check_context_overflow(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        reserve_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Check if context is approaching or exceeding limits.

        Args:
            messages: Message list to check
            max_tokens: Max context window (uses settings if not provided)
            reserve_tokens: Tokens to reserve for response (uses settings if not provided)

        Returns:
            Dictionary with overflow status and recommendations
        """
        max_tokens = max_tokens or settings.MAX_CONTEXT_TOKENS
        reserve_tokens = reserve_tokens or settings.CONTEXT_RESERVE_TOKENS

        current_tokens = self.count_messages_tokens(messages)
        available_tokens = max_tokens - reserve_tokens
        usage_ratio = current_tokens / available_tokens if available_tokens > 0 else 1.0

        threshold = settings.CONTEXT_WINDOW_THRESHOLD

        status = {
            "current_tokens": current_tokens,
            "max_tokens": max_tokens,
            "reserve_tokens": reserve_tokens,
            "available_tokens": available_tokens,
            "usage_ratio": usage_ratio,
            "is_overflow": current_tokens > available_tokens,
            "is_warning": usage_ratio >= threshold,
            "tokens_to_remove": max(0, current_tokens - int(available_tokens * threshold)),
        }

        # Add recommendations
        if status["is_overflow"]:
            status["recommendation"] = "CRITICAL: Context overflow! Apply compression immediately."
        elif status["is_warning"]:
            status["recommendation"] = f"WARNING: Context usage at {usage_ratio*100:.1f}%. Consider compression."
        else:
            status["recommendation"] = "OK: Context within safe limits."

        return status

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: Optional[str] = None
    ) -> float:
        """Calculate cost based on token usage.

        가격은 모델 카탈로그(`neos/config/models.yaml`)에서 온다. 이 메서드는
        `estimate_cost_usd()`에 위임할 뿐 자체 가격표를 갖지 않는다 — 예전에는
        per-1K 표 + 부분 문자열 매칭 + "모르면 GPT-4" 기본값이었고, 그 결과
        현행 주 모델 claude-sonnet-5가 실제의 10배(입력)로 계산됐다.

        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            model: Model name (uses instance model if not provided)

        Returns:
            Estimated cost in USD. 가격 미상이면 0.0 (경고 로그 발생).
        """
        return estimate_cost_usd(
            model or self.model_name,
            prompt_tokens,
            completion_tokens,
        )

    def track_usage(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        response: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Track token usage for a single LLM call.

        Args:
            prompt: Prompt text or message list
            response: Response text
            metadata: Optional metadata (phase, model, etc.)

        Returns:
            Usage statistics dictionary
        """
        # Count prompt tokens
        if isinstance(prompt, str):
            prompt_tokens = self.count_tokens(prompt)
        elif isinstance(prompt, list):
            prompt_tokens = self.count_messages_tokens(prompt)
        else:
            prompt_tokens = self.count_tokens(str(prompt))

        response_tokens = self.count_tokens(response)
        total_tokens = prompt_tokens + response_tokens

        model = metadata.get("model", self.model_name) if metadata else self.model_name
        cost = self.calculate_cost(prompt_tokens, response_tokens, model)

        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": response_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": cost,
            "model": model,
        }

        if metadata:
            usage.update({
                "phase": metadata.get("phase"),
                "tags": metadata.get("tags", []),
                "timestamp": metadata.get("timestamp"),
            })

        return usage


# Global token counter instance
_global_counter: Optional[TokenCounter] = None


def get_token_counter(model_name: Optional[str] = None) -> TokenCounter:
    """Get or create global token counter instance.

    Args:
        model_name: Optional model name override

    Returns:
        TokenCounter instance
    """
    global _global_counter

    if _global_counter is None or model_name:
        _global_counter = TokenCounter(model_name)

    return _global_counter
