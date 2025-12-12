"""Data Collection Module for HyperDeepResearch.

This module handles all data collection operations including:
- Tavily API search with rate limiting
- Parallel batch searches
- Query generation and execution
- Source deduplication and quality scoring
"""

from typing import Dict, Any, List, Optional
import asyncio
import time
import concurrent.futures
import logging

from langchain_core.messages import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

from .prompts import QueryGenerationPrompts
from .utils import RetryHandler


logger = logging.getLogger(__name__)


class DataCollector:
    """Handles data collection operations for research.
    
    Features:
    - Tavily API search with rate limiting
    - Parallel batch processing
    - Query generation
    - Source quality scoring
    """
    
    def __init__(
        self,
        tavily_client: Any,
        config: Dict[str, Any],
        retry_handler: Optional[RetryHandler] = None,
        quality_scorer: Optional[Any] = None,
    ):
        """Initialize the data collector.
        
        Args:
            tavily_client: Initialized Tavily client
            config: Research configuration dictionary
            retry_handler: Optional retry handler for API calls
            quality_scorer: Optional source quality scorer
        """
        self.tavily_client = tavily_client
        self.config = config
        self.retry_handler = retry_handler or RetryHandler(max_attempts=4, base_delay=2.0)
        self.quality_scorer = quality_scorer
        
        # Rate limiting
        self.rate_limiter = asyncio.Semaphore(
            settings.DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS
        )
        self.min_request_interval = settings.DEEP_RESEARCH_MIN_REQUEST_INTERVAL
        self.last_request_time = 0
        
        # Statistics
        self.stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "rate_limit_hits": 0,
            "total_results": 0,
        }
    
    @property
    def api_available(self) -> bool:
        """Check if Tavily API is available."""
        return self.tavily_client is not None
    
    async def generate_query_variations(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        agent_name: str = "hyper_deep_research",
    ) -> List[str]:
        """Generate diverse query variations for search.
        
        Args:
            topic_analysis: Topic analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            agent_name: Name of the agent
            
        Returns:
            List of query variations
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.6, max_tokens=2500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=agent_name,
                tags=["multi_query_generation"]
            )

            prompt = QueryGenerationPrompts.get_multi_query_prompt(
                topic_analysis['original_query'],
                topic_analysis['research_questions'],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [
                q.strip() for q in extract_text_from_response(response).strip().split('\n')
                if q.strip() and len(q.strip()) > 5
            ]

            # Ensure minimum queries with fallbacks
            if len(queries) < self.config["multi_query_expansion"]:
                base_query = topic_analysis['original_query']
                fallback = [
                    f"{base_query} overview",
                    f"{base_query} detailed analysis",
                    f"{base_query} latest trends",
                    f"{base_query} market analysis",
                    f"{base_query} technical details",
                    f"{base_query} future outlook",
                    f"{base_query} case studies",
                    f"{base_query} expert opinions",
                    f"{base_query} comparative analysis",
                    f"{base_query} challenges"
                ]
                queries.extend(fallback)

            return queries[:self.config["multi_query_expansion"]]

        except Exception as e:
            logger.error(f"Query generation failed: {e}")
            return [topic_analysis['original_query']]
    
    async def execute_parallel_searches(
        self,
        queries: List[str],
        event_logger: Any = None,
        repository: Any = None,
        report_id: str = None,
    ) -> List[List[Dict[str, Any]]]:
        """Execute parallel batch searches.
        
        Args:
            queries: List of queries to search
            event_logger: Optional event logger for progress tracking
            repository: Optional repository for data recording
            report_id: Optional report ID for recording
            
        Returns:
            List of search results per query
        """
        batch_size = len(queries) // self.config["parallel_search_batches"]
        all_results = []
        total_batches = self.config["parallel_search_batches"]

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = (
                start_idx + batch_size
                if batch_num < total_batches - 1
                else len(queries)
            )
            batch_queries = queries[start_idx:end_idx]

            print(f"[INFO] 📦 Batch {batch_num + 1}: {len(batch_queries)} queries")

            # Log batch execution
            if event_logger:
                await event_logger.log_progress(
                    batch_num + 1,
                    total_batches,
                    f"Executing search batch {batch_num + 1}/{total_batches}"
                )
                for query in batch_queries:
                    await event_logger.log_query_execution(
                        query, batch_num + 1, total_batches
                    )

            # Execute batch
            batch_results = await self._search_batch_parallel(batch_queries)
            all_results.extend(batch_results)

            # Record in database
            if repository and report_id:
                for query, results in zip(batch_queries, batch_results):
                    await repository.record_data_collection(
                        report_id, query, "multi_query_initial", 3, results
                    )
                    self.stats["total_queries"] += 1

        return all_results
    
    async def _search_batch_parallel(
        self,
        queries: List[str]
    ) -> List[List[Dict[str, Any]]]:
        """Execute batch of queries in parallel.
        
        Args:
            queries: List of queries to execute
            
        Returns:
            List of results per query
        """
        tasks = [self.single_search(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Search failed for '{queries[i]}': {result}")
                processed.append([])
                self.stats["failed_queries"] += 1
            else:
                processed.append(result)
                self.stats["successful_queries"] += 1
                self.stats["total_results"] += len(result)

        return processed
    
    async def single_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute single Tavily search with rate limiting and retry logic.
        
        Args:
            query: Search query
            
        Returns:
            List of search results
        """
        try:
            if not self.api_available:
                return []

            return await self.retry_handler.execute_with_retry(
                self._execute_tavily_search,
                query,
                retry_exceptions=(ConnectionError, TimeoutError, OSError)
            )

        except Exception as e:
            logger.error(f"Tavily search failed after retries: {e}")
            return []
    
    async def _execute_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute Tavily search (internal method for retry).
        
        Args:
            query: Search query
            
        Returns:
            List of search results
        """
        try:
            async with self.rate_limiter:
                # Enforce minimum interval
                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_request_interval:
                    await asyncio.sleep(self.min_request_interval - time_since_last)

                self.last_request_time = time.time()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self.tavily_client.search,
                        query=query,
                        search_depth="advanced",
                        max_results=self.config["results_per_query"],
                        include_answer=True,
                        include_raw_content=True
                    )

                    def get_result():
                        try:
                            return future.result(timeout=25)
                        except concurrent.futures.TimeoutError:
                            logger.warning(f"Tavily timeout for: {query[:50]}...")
                            return None

                    response = await asyncio.get_event_loop().run_in_executor(
                        None, get_result
                    )

                    # Check for rate limit
                    if response and isinstance(response, dict):
                        if response.get("status_code") == 429:
                            logger.warning("Rate limit hit for Tavily API")
                            self.stats["rate_limit_hits"] += 1
                            await asyncio.sleep(2)
                            return []

                    return response.get("results", []) if response else []

        except concurrent.futures.TimeoutError:
            logger.warning("Tavily search timeout")
            return []
        except (ConnectionError, OSError) as e:
            logger.error(f"Tavily network error: {e}")
            return []
        except Exception as e:
            logger.error(f"Tavily unexpected error: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get data collection statistics."""
        return self.stats.copy()
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self.stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "rate_limit_hits": 0,
            "total_results": 0,
        }


class ComplexSearchExecutor:
    """Executes complex multi-query searches using sub-agents."""
    
    def __init__(
        self,
        multi_query_agent: Any,
        repository: Any = None,
    ):
        """Initialize complex search executor.
        
        Args:
            multi_query_agent: Multi-query search agent
            repository: Optional repository for data recording
        """
        self.multi_query_agent = multi_query_agent
        self.repository = repository
        self.stats = {
            "complex_searches": 0,
            "successful_searches": 0,
        }
    
    async def execute_complex_searches(
        self,
        queries: List[str],
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        event_logger: Any = None,
        report_id: str = None,
    ) -> List[Dict[str, Any]]:
        """Execute complex multi-query searches.
        
        Args:
            queries: List of queries
            topic_analysis: Topic analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            event_logger: Optional event logger
            report_id: Optional report ID
            
        Returns:
            List of complex search results
        """
        all_complex_results = []
        priority_queries = queries[:5]

        print(f"[INFO] 🔄 Executing {len(priority_queries)} complex searches...")

        for idx, base_query in enumerate(priority_queries, 1):
            print(f"[INFO] 🔍 Complex search {idx}/{len(priority_queries)}")

            if event_logger:
                await event_logger.log_query_execution(
                    base_query, idx, len(priority_queries)
                )

            try:
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "detected_language": language
                }

                result = await self.multi_query_agent.execute(base_query, context)

                if result.get("success") and result.get("results"):
                    search_result = result["results"][0]
                    content = (
                        search_result.content
                        if hasattr(search_result, 'content')
                        else ""
                    )

                    if content:
                        complex_source = {
                            "title": f"Complex Analysis: {base_query}",
                            "content": content[:500],
                            "url": f"multi_query_analysis_{idx}",
                            "score": 0.95,
                            "type": "multi_query_synthesis"
                        }
                        all_complex_results.append(complex_source)
                        self.stats["complex_searches"] += 1
                        self.stats["successful_searches"] += 1

                        if self.repository and report_id:
                            await self.repository.record_data_collection(
                                report_id, base_query,
                                "complex_multi_query", 3, [complex_source]
                            )

            except Exception as e:
                logger.warning(f"Complex search {idx} failed: {e}")
                continue

        return all_complex_results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get complex search statistics."""
        return self.stats.copy()
