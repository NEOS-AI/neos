"""API services package - business logic layer."""

__all__ = [
    "QueryService",
    "DocumentService",
    "WorkflowService",
]


def __getattr__(name: str):
    if name == "QueryService":
        from neos.api.services.query_service import QueryService

        return QueryService
    if name == "DocumentService":
        from neos.api.services.document_service import DocumentService

        return DocumentService
    if name == "WorkflowService":
        from neos.api.services.workflow_service import WorkflowService

        return WorkflowService
    raise AttributeError(f"module 'neos.api.services' has no attribute {name!r}")
