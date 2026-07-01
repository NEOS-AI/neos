"""Auth dependencies"""

from .auth import (
    get_current_user,
    get_current_active_user,
    get_current_admin_user,
    get_current_user_from_gateway,
    get_current_user_from_jwt,
    get_current_user_from_api_key,
    get_optional_user,
    require_api_key,
    require_scopes,
    ScopeChecker,
)
from .resource_access import (
    get_owned_conversation,
    get_readable_conversation,
    get_owned_message,
    get_owned_document,
    require_same_user_id,
    require_stream_session_owner,
)

__all__ = [
    "get_current_user",
    "get_current_active_user",
    "get_current_admin_user",
    "get_current_user_from_gateway",
    "get_current_user_from_jwt",
    "get_current_user_from_api_key",
    "get_optional_user",
    "require_api_key",
    "require_scopes",
    "ScopeChecker",
    "get_owned_conversation",
    "get_readable_conversation",
    "get_owned_message",
    "get_owned_document",
    "require_same_user_id",
    "require_stream_session_owner",
]
