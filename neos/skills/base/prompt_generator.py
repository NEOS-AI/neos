"""Generate LLM-ready prompts from skills.

Converts skill metadata and documentation into XML-formatted prompts
following Anthropic Claude Agent Skills specifications.
"""

import html
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def generate_skill_context(
    skill_name: str,
    description: str,
    skill_body: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    include_body: bool = True,
    max_tokens: int = 2000,
) -> str:
    """Generate XML context for a single skill.

    Args:
        skill_name: Name of the skill
        description: Skill description
        skill_body: SKILL.md body content (markdown after frontmatter)
        allowed_tools: Tools required by this skill
        capabilities: List of skill capabilities
        include_body: Whether to include the body in output
        max_tokens: Maximum tokens for body (approximate, 4 chars = 1 token)

    Returns:
        XML formatted skill context string

    Example:
        <skill>
        <name>pdf</name>
        <description>PDF document processing</description>
        <allowed_tools>Read, Write</allowed_tools>
        <capabilities>
          <capability>document_reading</capability>
          <capability>text_extraction</capability>
        </capabilities>
        <documentation>
        [SKILL.md body content]
        </documentation>
        </skill>
    """
    lines = ["<skill>"]

    # Name (required)
    lines.append("<name>")
    lines.append(html.escape(skill_name))
    lines.append("</name>")

    # Description (required)
    lines.append("<description>")
    lines.append(html.escape(description))
    lines.append("</description>")

    # Allowed tools (optional)
    if allowed_tools:
        lines.append("<allowed_tools>")
        lines.append(html.escape(allowed_tools))
        lines.append("</allowed_tools>")

    # Capabilities (optional)
    if capabilities:
        lines.append("<capabilities>")
        for cap in capabilities:
            lines.append("<capability>")
            lines.append(html.escape(cap))
            lines.append("</capability>")
        lines.append("</capabilities>")

    # Documentation body (optional)
    if include_body and skill_body:
        # Truncate if too long (rough estimate: 4 chars ≈ 1 token)
        max_chars = max_tokens * 4
        truncated_body = skill_body
        if len(skill_body) > max_chars:
            truncated_body = skill_body[:max_chars] + "\n\n[... truncated ...]"
            logger.debug(
                f"Truncated skill body for {skill_name} from {len(skill_body)} "
                f"to {len(truncated_body)} chars"
            )

        lines.append("<documentation>")
        lines.append(html.escape(truncated_body))
        lines.append("</documentation>")

    lines.append("</skill>")

    return "\n".join(lines)


def generate_skills_prompt(
    skills: List[Dict[str, Any]],
    include_body: bool = True,
) -> str:
    """Generate <available_skills> XML block for multiple skills.

    This format follows Anthropic's recommended structure for agent prompts.

    Args:
        skills: List of skill dictionaries with keys:
            - name: str (required)
            - description: str (required)
            - skill_body: str (optional)
            - allowed_tools: str (optional)
            - capabilities: List[str] (optional)
        include_body: Whether to include documentation bodies

    Returns:
        XML formatted skills prompt

    Example:
        <available_skills>
        <skill>
        <name>pdf</name>
        <description>PDF processing</description>
        ...
        </skill>
        <skill>
        <name>bigquery</name>
        <description>BigQuery analysis</description>
        ...
        </skill>
        </available_skills>
    """
    if not skills:
        return "<available_skills>\n</available_skills>"

    lines = ["<available_skills>"]

    for skill in skills:
        skill_context = generate_skill_context(
            skill_name=skill.get("name", "unknown"),
            description=skill.get("description", "No description"),
            skill_body=skill.get("skill_body"),
            allowed_tools=skill.get("allowed_tools"),
            capabilities=skill.get("capabilities"),
            include_body=include_body,
            max_tokens=skill.get("max_tokens", 2000),
        )
        lines.append(skill_context)

    lines.append("</available_skills>")

    return "\n".join(lines)


def estimate_token_count(text: str) -> int:
    """Rough estimation of token count.

    Args:
        text: Text to estimate

    Returns:
        Approximate token count (characters / 4)
    """
    return len(text) // 4
