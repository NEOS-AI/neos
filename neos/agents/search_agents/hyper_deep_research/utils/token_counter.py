"""Accurate token counting using tiktoken library.

Provides precise token estimation for cost tracking and optimization.
"""

from typing import Dict, Any
import logging

from neos.utils.token_counter import estimate_cost_usd

logger = logging.getLogger(__name__)


class TokenCounter:
    """Accurate token counter using tiktoken."""

    def __init__(self, model_name: str = "gpt-4"):
        """Initialize token counter.

        Args:
            model_name: Model name for encoding selection
        """
        self.model_name = model_name
        self.encoding = None
        self._init_encoding()

    def _init_encoding(self) -> None:
        """Initialize tiktoken encoding with fallback."""
        try:
            import tiktoken
            self.encoding = tiktoken.encoding_for_model(self.model_name)
            logger.info(f"[TokenCounter] Initialized tiktoken for {self.model_name}")
        except ImportError:
            logger.warning("[TokenCounter] tiktoken not available, using approximation")
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

    def count_messages_tokens(self, messages: list) -> int:
        """Count tokens in message list.

        Args:
            messages: List of message dictionaries

        Returns:
            Total token count
        """
        total = 0
        for message in messages:
            if isinstance(message, dict):
                content = message.get('content', '')
            else:
                content = str(message)
            total += self.count_tokens(content)

        # Add overhead for message formatting (rough estimate)
        total += len(messages) * 4

        return total

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "gpt-4"
    ) -> float:
        """Calculate cost based on token usage.

        가격은 모델 카탈로그(`neos/config/models.yaml`)에서 오며,
        `neos.utils.token_counter.estimate_cost_usd()`에 위임한다.

        예전에는 이 모듈이 `neos/utils/token_counter.py`와 거의 같은 per-1K
        가격표를 따로 들고 있었다. 두 표는 이미 서로 어긋나 있었다 — 이쪽은
        "gpt-4"를 먼저 검사해서 `gpt-4-turbo`가 gpt-4 요율($0.03/1K)로 계산됐다.

        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            model: Model name

        Returns:
            Estimated cost in USD. 가격 미상이면 0.0 (경고 로그 발생).
        """
        return estimate_cost_usd(model, prompt_tokens, completion_tokens)

    def track_usage(
        self,
        prompt: str,
        response: str,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Track token usage for a single LLM call.

        Args:
            prompt: Prompt text
            response: Response text
            metadata: Optional metadata (phase, model, etc.)

        Returns:
            Usage statistics dictionary
        """
        prompt_tokens = self.count_tokens(prompt)
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
            })

        return usage
