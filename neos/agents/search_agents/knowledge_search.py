"""Knowledge-based search agent"""

from typing import Dict, Any, List, TYPE_CHECKING
from sqlalchemy import text

from neos.utils.cache import cache_manager
from neos.database.connection import db_manager
from ..base import SearchAgent

if TYPE_CHECKING:
    from neos.workflow.state import SearchResult


class KnowledgeSearchAgent(SearchAgent):
    """지식 기반 검색 에이전트"""

    def __init__(self):
        super().__init__(
            name="knowledge_search",
            search_type="knowledge",
            role="Knowledge Base Searcher",
            goal="Search through internal knowledge base and historical queries to find relevant information",
            backstory="You are an expert at searching through structured knowledge bases and finding patterns in historical data."
        )

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        print(f"[DEBUG] KnowledgeSearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] KnowledgeSearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # 캐시 확인
        cache_key = f"knowledge_search:{hash(query)}"
        print(f"[DEBUG] Checking cache with key: {cache_key}")
        cached_result = await cache_manager.get(cache_key)
        if cached_result:
            print("[DEBUG] Found cached result, returning")
            return cached_result

        try:
            print("[DEBUG] Searching knowledge base...")
            similar_queries = await self._search_knowledge_base(query, context.get('query_embedding'))
            print(f"[DEBUG] Knowledge base returned {len(similar_queries)} items")

            from neos.workflow.state import SearchResult

            results = []
            for item in similar_queries:
                results.append(SearchResult(
                    source="knowledge_base",
                    title=item.get("title", "Knowledge Item"),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                    metadata=item.get("metadata", {})
                ))

            print(f"[DEBUG] Created {len(results)} SearchResult objects")
            result = self.format_output(results, {"search_type": "knowledge"})

            # 결과 캐싱
            print("[DEBUG] Caching result...")
            await cache_manager.set(cache_key, result, ttl=3600)
            print("[DEBUG] KnowledgeSearchAgent execution completed successfully")
            return result
        except Exception as e:
            print(f"[ERROR] KnowledgeSearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}


    async def _search_knowledge_base(self, query: str, query_embedding: List[float]) -> List[Dict[str, Any]]:
        """지식 베이스 검색 (트리그램 기반)"""
        print(f"[DEBUG] _search_knowledge_base called with embedding: {type(query_embedding)}")

        # If no embedding provided, return empty results
        if not query_embedding:
            print("[WARNING] No query embedding provided, returning empty results")
            return []

        try:
            print("[DEBUG] Getting database session...")
            async with await db_manager.get_session() as session:
                print("[DEBUG] Database session acquired")
                #TODO pg_search 등 paradedb 기능 도입!
                sql = text("""
                    SELECT original_query, search_results, response_quality_score,
                           query_vector <=> :query_vector as distance
                    FROM query_history
                    WHERE query_vector IS NOT NULL
                    ORDER BY query_vector <=> :query_vector
                    LIMIT 5
                """)

                print(f"[DEBUG] Executing SQL query with embedding length: {len(query_embedding)}")
                result = await session.execute(sql, {"query_vector": str(query_embedding)})
                rows = result.fetchall()
                print(f"[DEBUG] SQL query returned {len(rows)} rows")

                knowledge_results = []
                for i, row in enumerate(rows):
                    print(f"[DEBUG] Processing row {i+1}: distance={row.distance}")
                    # Convert distance to similarity score (1 - distance, clamped between 0 and 1)
                    similarity_score = max(0.0, min(1.0, 1.0 - row.distance))
                    knowledge_results.append({
                        "title": row.original_query,
                        "content": str(row.search_results) if row.search_results else "",
                        "score": similarity_score,
                        "metadata": {"quality_score": row.response_quality_score}
                    })

                print(f"[DEBUG] Returning {len(knowledge_results)} knowledge results")
                return knowledge_results

        except Exception as e:
            print(f"[ERROR] Database search failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return []
