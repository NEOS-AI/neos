"""LLM client for model-based graders.

This module provides a simple interface for making LLM API calls
for evaluation purposes.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import json

try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for making LLM API calls in graders.

    Supports:
    - Anthropic Claude API
    - Async execution
    - Retry logic
    - Token tracking

    Example:
        ```python
        client = LLMClient()
        response = await client.call(
            prompt="Evaluate this text...",
            max_tokens=1000
        )
        ```
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        max_retries: int = 3,
        timeout: int = 60
    ):
        """Initialize LLM client.

        Args:
            api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
            model: Model to use
            max_retries: Maximum retry attempts
            timeout: Request timeout in seconds
        """
        if not ANTHROPIC_AVAILABLE:
            logger.warning(
                "Anthropic library not installed. "
                "Model-based graders will not work. "
                "Install: pip install anthropic"
            )
            self.client = None
        else:
            self.client = AsyncAnthropic(
                api_key=api_key,
                timeout=timeout
            )

        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout

        # Track usage
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def call(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.0,
        system: Optional[str] = None
    ) -> str:
        """Make an LLM API call.

        Args:
            prompt: User prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)
            system: Optional system prompt

        Returns:
            Model response text

        Raises:
            RuntimeError: If Anthropic library not available
            Exception: If API call fails after retries
        """
        if not self.client:
            raise RuntimeError(
                "Anthropic library not available. "
                "Install: pip install anthropic"
            )

        for attempt in range(self.max_retries):
            try:
                messages = [{"role": "user", "content": prompt}]

                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                if system:
                    kwargs["system"] = system

                response = await self.client.messages.create(**kwargs)

                # Track usage
                self.total_calls += 1
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens

                # Extract text
                return response.content[0].text

            except Exception as e:
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                )

                if attempt == self.max_retries - 1:
                    raise

                # Exponential backoff
                await asyncio.sleep(2 ** attempt)

        raise Exception("LLM call failed after all retries")

    async def call_with_json(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.0,
        system: Optional[str] = None
    ) -> Dict[str, Any]:
        """Make an LLM call expecting JSON response.

        Args:
            prompt: User prompt (should ask for JSON)
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            system: Optional system prompt

        Returns:
            Parsed JSON dictionary

        Raises:
            json.JSONDecodeError: If response is not valid JSON
        """
        response = await self.call(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system
        )

        # Try to extract JSON from response
        # Sometimes LLM wraps JSON in ```json blocks
        response = response.strip()

        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        return json.loads(response)

    def get_usage_stats(self) -> Dict[str, int]:
        """Get usage statistics.

        Returns:
            Dictionary with call count and token usage
        """
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }

    def reset_stats(self) -> None:
        """Reset usage statistics."""
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0


# Global client instance (shared across graders)
_global_client: Optional[LLMClient] = None


def get_global_llm_client() -> LLMClient:
    """Get the global LLM client instance.

    Returns:
        Global LLMClient instance
    """
    global _global_client

    if _global_client is None:
        _global_client = LLMClient()

    return _global_client


def set_global_llm_client(client: LLMClient) -> None:
    """Set the global LLM client instance.

    Args:
        client: LLMClient to use globally
    """
    global _global_client
    _global_client = client
