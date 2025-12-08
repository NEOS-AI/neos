"""Facet extraction pipeline using LLM."""

import json
import logging
from typing import Any, Dict, List, Optional

import anthropic
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class ExtractedFacets(BaseModel):
    """Extracted facets from a conversation."""

    topic: str = Field(description="Main topic or subject of the conversation")
    language: str = Field(description="Primary language used in the conversation")
    task_type: str = Field(
        description="Type of task (coding, writing, analysis, creative, etc.)"
    )
    intent: str = Field(
        description="User's primary intent (learn, create, solve, explore, etc.)"
    )
    domain: str = Field(
        description="Domain area (technology, business, science, arts, etc.)"
    )
    complexity: int = Field(
        ge=1, le=5, description="Complexity level from 1 (simple) to 5 (complex)"
    )
    sentiment: str = Field(
        description="Overall sentiment (positive, neutral, negative, mixed)"
    )
    safety_score: int = Field(
        ge=1,
        le=5,
        description="Safety score from 1 (safe) to 5 (potentially concerning)",
    )
    summary: str = Field(
        description="Brief summary of the conversation (max 100 chars, no PII)"
    )
    keywords: List[str] = Field(
        description="List of 3-5 keywords describing the conversation"
    )


class FacetExtractor:
    """Extracts facets from conversations using LLM."""

    EXTRACTION_PROMPT = """Analyze the following conversation and extract structured facets.
You must extract the following information:

1. topic: Main topic or subject (e.g., "Python debugging", "Email drafting", "Data analysis")
2. language: Primary language used (e.g., "English", "Korean", "Japanese")
3. task_type: Type of task being performed:
   - coding: Programming, debugging, code review
   - writing: Document creation, editing, translation
   - analysis: Data analysis, research, comparisons
   - creative: Creative writing, brainstorming, design
   - learning: Education, explanations, tutorials
   - assistant: General assistance, scheduling, planning
   - other: Miscellaneous tasks

4. intent: User's primary intent:
   - learn: Seeking to understand or learn
   - create: Building or producing something
   - solve: Fixing a problem or debugging
   - explore: Researching or discovering
   - improve: Enhancing existing work
   - automate: Streamlining processes

5. domain: Domain area:
   - technology: Software, hardware, IT
   - business: Commerce, management, finance
   - science: Research, academic, medical
   - arts: Creative, entertainment, media
   - education: Learning, teaching
   - personal: Daily life, hobbies
   - other: Miscellaneous

6. complexity: 1-5 scale (1=simple question, 5=complex multi-step task)
7. sentiment: positive, neutral, negative, or mixed
8. safety_score: 1-5 scale (1=completely safe, 5=potentially concerning)
9. summary: Brief summary in 100 characters or less. MUST NOT contain any personal information, names, emails, or specific identifiers.
10. keywords: 3-5 keywords describing the conversation

IMPORTANT PRIVACY RULES:
- Never include personal names, emails, phone numbers, or addresses
- Never include specific company or organization names
- Never include specific project names or identifiers
- Replace any specific identifiers with generic descriptions

Conversation:
{conversation}

Respond in JSON format only:"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the facet extractor.

        Args:
            api_key: Anthropic API key. Uses settings if not provided.
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = settings.LLM_MODEL

    def _format_conversation(self, messages: List[Dict[str, Any]]) -> str:
        """Format conversation messages for the prompt.

        Args:
            messages: List of message dictionaries with 'role' and 'content'.

        Returns:
            Formatted conversation string.
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            formatted.append(f"{role}: {content}")

        return "\n\n".join(formatted)

    async def extract_facets(
        self, messages: List[Dict[str, Any]]
    ) -> Optional[ExtractedFacets]:
        """Extract facets from a conversation.

        Args:
            messages: List of messages in the conversation.

        Returns:
            ExtractedFacets object or None if extraction fails.
        """
        if not messages:
            logger.warning("No messages provided for facet extraction")
            return None

        conversation_text = self._format_conversation(messages)
        prompt = self.EXTRACTION_PROMPT.format(conversation=conversation_text)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract JSON from response
            response_text = response.content[0].text
            # Try to find JSON in the response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                facets_dict = json.loads(json_str)
                return ExtractedFacets(**facets_dict)
            else:
                logger.error("No JSON found in LLM response")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during facet extraction: {e}")
            return None

    async def extract_facets_batch(
        self, conversations: List[List[Dict[str, Any]]], batch_size: int = 10
    ) -> List[Optional[ExtractedFacets]]:
        """Extract facets from multiple conversations.

        Args:
            conversations: List of conversations (each is a list of messages).
            batch_size: Number of concurrent extractions.

        Returns:
            List of ExtractedFacets (or None for failures).
        """
        import asyncio

        results = []
        for i in range(0, len(conversations), batch_size):
            batch = conversations[i : i + batch_size]
            batch_results = await asyncio.gather(
                *[self.extract_facets(conv) for conv in batch],
                return_exceptions=True,
            )
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Batch extraction error: {result}")
                    results.append(None)
                else:
                    results.append(result)

        return results


class SimpleFacetExtractor:
    """Simplified facet extractor using heuristics (for testing/fallback)."""

    LANGUAGE_KEYWORDS = {
        "korean": ["안녕", "감사", "입니다", "있습니다", "어떻게"],
        "japanese": ["です", "ます", "こんにちは", "ありがとう"],
        "chinese": ["你好", "谢谢", "是什么", "怎么"],
        "spanish": ["hola", "gracias", "cómo", "qué"],
        "french": ["bonjour", "merci", "comment", "pourquoi"],
    }

    TASK_KEYWORDS = {
        "coding": ["code", "function", "error", "debug", "python", "javascript", "api"],
        "writing": ["write", "draft", "email", "letter", "essay", "document"],
        "analysis": ["analyze", "data", "compare", "statistics", "report"],
        "creative": ["story", "poem", "creative", "design", "brainstorm"],
        "learning": ["explain", "learn", "understand", "tutorial", "how does"],
    }

    def extract_language(self, text: str) -> str:
        """Detect language from text."""
        text_lower = text.lower()
        for lang, keywords in self.LANGUAGE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return lang
        return "english"

    def extract_task_type(self, text: str) -> str:
        """Detect task type from text."""
        text_lower = text.lower()
        for task, keywords in self.TASK_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return task
        return "assistant"

    def extract_facets(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract facets using simple heuristics.

        Args:
            messages: List of message dictionaries.

        Returns:
            Dictionary of extracted facets.
        """
        if not messages:
            return {}

        full_text = " ".join(msg.get("content", "") for msg in messages)
        user_messages = [
            msg.get("content", "") for msg in messages if msg.get("role") == "user"
        ]
        user_text = " ".join(user_messages)

        return {
            "language": self.extract_language(full_text),
            "task_type": self.extract_task_type(user_text),
            "message_count": len(messages),
            "total_length": len(full_text),
            "complexity": min(5, max(1, len(messages) // 2)),
        }
