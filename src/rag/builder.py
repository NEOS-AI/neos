from src.config.tools import SELECTED_RAG_PROVIDER, RAGProvider
from src.rag.ragflow import RAGFlowProvider
from src.rag.vikingdb_knowledge_base import VikingDBKnowledgeBaseProvider
from src.rag.retriever import Retriever


def build_retriever() -> Retriever | None:
    if SELECTED_RAG_PROVIDER == RAGProvider.RAGFLOW.value:
        return RAGFlowProvider()
    elif SELECTED_RAG_PROVIDER == RAGProvider.VIKINGDB_KNOWLEDGE_BASE.value:
        return VikingDBKnowledgeBaseProvider()
    return None
