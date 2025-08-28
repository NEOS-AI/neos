from dataclasses import dataclass, field

from neos.server.data_models.conversation_info import ConversationInfo


@dataclass
class ConversationInfoResultSet:
    results: list[ConversationInfo] = field(default_factory=list)
    next_page_id: str | None = None
