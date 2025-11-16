"""Accurate token counting using tiktoken library.

Provides precise token estimation for cost tracking and optimization.
"""

from typing import Dict, Any
import logging

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

        Pricing (as of 2024):
        - GPT-4: $0.03/1K prompt, $0.06/1K completion
        - GPT-3.5: $0.0015/1K prompt, $0.002/1K completion

        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            model: Model name

        Returns:
            Estimated cost in USD
        """
        # Pricing table
        pricing = {
            "gpt-4": {"prompt": 0.03, "completion": 0.06},
            "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
            "gpt-3.5-turbo": {"prompt": 0.0015, "completion": 0.002},
            "claude-3-opus": {"prompt": 0.015, "completion": 0.075},
            "claude-3-sonnet": {"prompt": 0.003, "completion": 0.015},
            "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
        }

        # Default to GPT-4 pricing if model not found
        model_key = model.lower()
        for key in pricing.keys():
            if key in model_key:
                model_key = key
                break

        if model_key not in pricing:
            model_key = "gpt-4"

        rates = pricing[model_key]
        prompt_cost = (prompt_tokens / 1000) * rates["prompt"]
        completion_cost = (completion_tokens / 1000) * rates["completion"]

        return prompt_cost + completion_cost

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
