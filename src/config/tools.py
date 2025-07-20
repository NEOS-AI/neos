import os
import enum
from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()


class SearchEngine(enum.Enum):
    TAVILY = "tavily"
    DUCKDUCKGO = "duckduckgo"
    BRAVE_SEARCH = "brave_search"
    ARXIV = "arxiv"


# Tool configuration
SELECTED_SEARCH_ENGINE = os.getenv("SEARCH_API", SearchEngine.TAVILY.value)


class RAGProvider(enum.Enum):
    RAGFLOW = "ragflow"
    VIKINGDB_KNOWLEDGE_BASE = "vikingdb_knowledge_base"
    NONE = "none" # Default value if no provider is selected


RagProviderMembers = list(RAGProvider.__members__.keys())

SELECTED_RAG_PROVIDER = os.getenv("RAG_PROVIDER", RAGProvider.NONE.value)
if SELECTED_RAG_PROVIDER is None:
    SELECTED_RAG_PROVIDER = RAGProvider.NONE.value
if SELECTED_RAG_PROVIDER and SELECTED_RAG_PROVIDER not in RagProviderMembers:
    raise ValueError(
        f"Invalid RAG provider: {SELECTED_RAG_PROVIDER}. "
        f"Supported providers are: {list(RAGProvider.__members__.keys())}"
    )
