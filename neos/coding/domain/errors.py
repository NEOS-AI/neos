class CodingDomainError(Exception):
    """Base error for coding-domain rule violations."""


class InvalidTaskTransition(CodingDomainError):
    """Raised when a task status transition is not allowed."""


class CodingTaskNotFound(CodingDomainError):
    """The task is absent or not owned by the requesting user."""
