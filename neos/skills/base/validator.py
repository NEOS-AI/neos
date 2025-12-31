"""Skill validation logic.

Provides strict validation rules following Anthropic Claude Agent Skills specifications.
Validates skill names, descriptions, and frontmatter fields.
"""

import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Validation limits
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500

# Allowed frontmatter fields per Agent Skills Spec (extended for NEOS)
ALLOWED_FRONTMATTER_FIELDS = {
    "name",
    "type",
    "description",
    "capabilities",
    "version",
    "dependencies",
    "allowed_tools",
    "license",
    "compatibility",
    "metadata",
}


def validate_skill_name(
    name: str, skill_dir: Optional[Path] = None
) -> List[str]:
    """Validate skill name format and directory match.

    Skill names support i18n characters (Unicode letters) plus hyphens.
    Names must be lowercase and cannot start/end with hyphens.

    Args:
        name: Skill name to validate
        skill_dir: Optional path to skill directory (for name-directory match check)

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not name or not isinstance(name, str) or not name.strip():
        errors.append("Field 'name' must be a non-empty string")
        return errors

    name = unicodedata.normalize("NFKC", name.strip())

    # Length check
    if len(name) > MAX_SKILL_NAME_LENGTH:
        errors.append(
            f"Skill name '{name}' exceeds {MAX_SKILL_NAME_LENGTH} character limit "
            f"({len(name)} chars)"
        )

    # Lowercase check
    if name != name.lower():
        errors.append(f"Skill name '{name}' must be lowercase")

    # Hyphen checks
    if name.startswith("-") or name.endswith("-"):
        errors.append("Skill name cannot start or end with a hyphen")

    if "--" in name:
        errors.append("Skill name cannot contain consecutive hyphens")

    # Character validation (letters, digits, hyphens only)
    if not all(c.isalnum() or c == "-" for c in name):
        errors.append(
            f"Skill name '{name}' contains invalid characters. "
            "Only letters, digits, and hyphens are allowed."
        )

    # Directory name matching
    if skill_dir:
        dir_name = unicodedata.normalize("NFKC", skill_dir.name)
        if dir_name != name:
            errors.append(
                f"Directory name '{skill_dir.name}' must match skill name '{name}'"
            )

    return errors


def validate_description(description: str) -> List[str]:
    """Validate description format.

    Args:
        description: Description to validate

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not description or not isinstance(description, str) or not description.strip():
        errors.append("Field 'description' must be a non-empty string")
        return errors

    if len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"Description exceeds {MAX_DESCRIPTION_LENGTH} character limit "
            f"({len(description)} chars)"
        )

    return errors


def validate_compatibility(compatibility: str) -> List[str]:
    """Validate compatibility format.

    Args:
        compatibility: Compatibility string to validate

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not isinstance(compatibility, str):
        errors.append("Field 'compatibility' must be a string")
        return errors

    if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        errors.append(
            f"Compatibility exceeds {MAX_COMPATIBILITY_LENGTH} character limit "
            f"({len(compatibility)} chars)"
        )

    return errors


def validate_frontmatter_fields(metadata: Dict[str, Any]) -> List[str]:
    """Validate that only allowed fields are present.

    Args:
        metadata: Parsed frontmatter metadata dictionary

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    extra_fields = set(metadata.keys()) - ALLOWED_FRONTMATTER_FIELDS
    if extra_fields:
        errors.append(
            f"Unexpected fields in frontmatter: {', '.join(sorted(extra_fields))}. "
            f"Only {sorted(ALLOWED_FRONTMATTER_FIELDS)} are allowed."
        )

    return errors


def validate_metadata(
    metadata: Dict[str, Any], skill_dir: Optional[Path] = None
) -> List[str]:
    """Validate parsed skill metadata.

    This is the core validation function that works on already-parsed metadata,
    avoiding duplicate file I/O when called from the parser.

    Args:
        metadata: Parsed YAML frontmatter dictionary
        skill_dir: Optional path to skill directory (for name-directory match check)

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    # Validate frontmatter fields
    errors.extend(validate_frontmatter_fields(metadata))

    # Validate required fields
    if "name" not in metadata:
        errors.append("Missing required field in frontmatter: name")
    else:
        errors.extend(validate_skill_name(metadata["name"], skill_dir))

    if "description" not in metadata:
        errors.append("Missing required field in frontmatter: description")
    else:
        errors.extend(validate_description(metadata["description"]))

    # Validate optional fields
    if "compatibility" in metadata:
        errors.extend(validate_compatibility(metadata["compatibility"]))

    # Validate type field (NEOS-specific)
    if "type" not in metadata:
        errors.append("Missing required field in frontmatter: type")
    elif not isinstance(metadata["type"], str):
        errors.append("Field 'type' must be a string")

    # Validate capabilities (NEOS-specific)
    if "capabilities" not in metadata:
        errors.append("Missing required field in frontmatter: capabilities")
    elif not isinstance(metadata["capabilities"], list):
        errors.append("Field 'capabilities' must be a list")
    elif not metadata["capabilities"]:
        errors.append("Field 'capabilities' cannot be empty")

    return errors


def validate_skill_directory(skill_dir: Path) -> List[str]:
    """Validate a skill directory.

    Args:
        skill_dir: Path to the skill directory

    Returns:
        List of validation error messages. Empty list means valid.
    """
    skill_dir = Path(skill_dir)

    if not skill_dir.exists():
        return [f"Path does not exist: {skill_dir}"]

    if not skill_dir.is_dir():
        return [f"Not a directory: {skill_dir}"]

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["Missing required file: SKILL.md"]

    return []
