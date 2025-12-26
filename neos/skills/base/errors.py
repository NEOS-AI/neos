"""Skill-related exceptions.

Exception hierarchy for skill system errors, providing detailed error reporting
for validation, parsing, and prompt generation failures.
"""


class SkillError(Exception):
    """Base exception for all skill-related errors."""

    pass


class SkillValidationError(SkillError):
    """Raised when skill metadata validation fails.

    Attributes:
        errors: List of validation error messages (may contain just one)
    """

    def __init__(self, message: str, errors: list[str] | None = None):
        """Initialize validation error with optional error list.

        Args:
            message: Main error message
            errors: List of specific validation errors
        """
        super().__init__(message)
        self.errors = errors if errors is not None else [message]


class SkillParseError(SkillError):
    """Raised when SKILL.md parsing fails."""

    pass


class SkillPromptGenerationError(SkillError):
    """Raised when skill prompt generation fails."""

    pass
