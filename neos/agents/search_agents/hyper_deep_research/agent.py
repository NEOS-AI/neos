"""Refactored HyperDeepResearch Agent - Clean Architecture Implementation.

This module contains the main business logic for the HyperDeepResearch agent,
separated from prompts, database operations, and utility functions.

Design Patterns Used:
- Repository Pattern: Database operations
- Strategy Pattern: Language-specific prompt selection
- Builder Pattern: Report construction
"""

from typing import Dict, Any, List
import asyncio
import uuid
from datetime import datetime
from tavily import TavilyClient

from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from langchain.schema import HumanMessage

from ...base import SearchAgent
from ...planning_agent import PlanningAgent
from ..multi_query_search import MultiQuerySearchAgent
from ..criticism_feedback_agent import CriticismFeedbackAgent

# Import refactored modules
from .prompts import (
    TopicAnalysisPrompts,
    ResearchPlanningPrompts,
    QueryGenerationPrompts,
    AnalysisPrompts,
    ValidationPrompts
)
from .repository import HyperResearchRepository
from .utils import LanguageDetector, DataProcessor


class HyperDeepResearchAgent(SearchAgent):
    """Elite research agent with extreme thoroughness and critical analysis.

    Features:
    1. Multi-query search: Query augmentation from diverse perspectives
    2. Advanced planning: Research methodology, theoretical frameworks
    3. Iterative deep analysis: Initial → Gap → Additional → Validation → Integration
    4. Critical thinking: Multiple perspectives, opposing views, limitations
    5. Triangulation: Cross-verification from multiple sources
    6. Extensive investigation: 100+ sources minimum
    7. Complete tracking: All phases and data collection in database

    Architecture:
    - Clean separation of concerns
    - Repository pattern for database operations
    - Language-aware prompt selection
    - Testable and maintainable code structure
    """

    def __init__(self):
        """Initialize the HyperDeepResearch agent."""
        super().__init__(
            name="hyper_deep_research",
            search_type="hyper_deep_research",
            role="Elite Research Director & Critical Analyst",
            goal="Conduct exhaustive, multi-dimensional research with rigorous methodology",
            backstory="World-renowned research director combining academic rigor, "
                    "investigative journalism, and critical analysis depth."
        )

        # Research configuration
        self.config = {
            # 멀티 쿼리 설정
            "multi_query_expansion": 20,  # 쿼리당 20개 변형 생성
            "parallel_search_batches": 5,  # 5개 배치로 병렬 검색

            # 조사 강도
            "max_queries_per_phase": 30,  # 각 단계당 최대 30개 쿼리
            "results_per_query": 10,  # 각 쿼리당 10개 결과
            "min_total_sources": 100,  # 최소 100개 소스
            "target_total_sources": 200,  # 목표 200개 소스

            # 분석 깊이
            "analysis_iterations": 3,  # 3회 반복 분석
            "cross_validation_rounds": 2,  # 2회 교차 검증
            "critical_thinking_passes": 2,  # 2회 비판적 검토

            # 섹션 및 품질
            "max_sections": 15,
            "min_sources_per_section": 5,
            "timeout_per_phase": 900,  # 15분
            "quality_threshold": 0.9
        }

        # Initialize Tavily client
        self._init_tavily_client()

        # Initialize sub-agents
        self.planning_agent = PlanningAgent()
        self.multi_query_agent = MultiQuerySearchAgent()
        self.criticism_agent = CriticismFeedbackAgent()

        # Initialize repository
        self.repository = HyperResearchRepository()

        # Research state
        self.current_report_id = None
        self.sections_data = []
        self.all_collected_sources = []
        self.research_metadata = {
            "total_queries_executed": 0,
            "total_sources_collected": 0,
            "unique_domains": set(),
            "analysis_iterations_completed": 0,
            "critical_reviews_completed": 0,
            "multi_query_searches": 0,
            "criticism_feedbacks_generated": 0,
            "additional_research_triggered": 0
        }

    def _init_tavily_client(self) -> None:
        """Initialize Tavily API client."""
        self.tavily_client = None
        self.api_available = False

        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient initialized for HyperDeepResearch")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient: {e}")
        else:
            print("[WARNING] TAVILY_API_KEY not set")

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute HyperDeepResearch process.

        Args:
            query: Research query/topic
            context: Execution context with session_id, user_id, etc.

        Returns:
            Search result dictionary with comprehensive research report
        """
        print(f"[DEBUG] HyperDeepResearchAgent.execute: {query[:50]}...")

        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}

        if not self.api_available:
            return self.format_output(
                [], {"search_type": "hyper_deep_research", "warning": "API unavailable"}
            )

        try:
            # Extract context parameters
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""

            # Detect query language
            language = LanguageDetector.detect(query)
            print(f"[INFO] Detected language: {LanguageDetector.get_language_name(language)}")

            # Update context with detected language
            if context is None:
                context = {}
            context["detected_language"] = language

            # Execute research process
            report_content = await self._run_research_process(
                query, session_id, user_id, language
            )

            # Create search result
            result = SearchResult(
                source="hyper_deep_research_report",
                title=f"HyperDeepResearch: {query}",
                content=report_content,
                url="",
                score=0.98,
                metadata={
                    "processing_type": "hyper_deep_research",
                    "report_id": self.current_report_id,
                    "total_sections": len(self.sections_data),
                    "total_sources": self.research_metadata["total_sources_collected"],
                    "total_queries": self.research_metadata["total_queries_executed"],
                    "multi_query_searches": self.research_metadata["multi_query_searches"],
                    "unique_domains": len(self.research_metadata["unique_domains"]),
                    "db_stored": True
                }
            )

            print("[DEBUG] HyperDeepResearch execution completed successfully")
            return self.format_output([result], {"search_type": "hyper_deep_research"})

        except Exception as e:
            print(f"[ERROR] HyperDeepResearch execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}

    async def _run_research_process(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Execute the complete research process.

        Args:
            query: Research topic
            session_id: Session identifier
            user_id: User identifier
            language: Detected language code

        Returns:
            Complete research report as markdown string
        """
        print("[INFO] ========== HyperDeepResearch Process Started ==========")
        print(f"[INFO] 🚀 Target: {self.config['target_total_sources']} sources minimum")

        # Initialize report
        self.current_report_id = f"hyper_report_{uuid.uuid4()}"
        await self.repository.ensure_tables_exist()
        await self.repository.create_report(
            self.current_report_id, user_id, session_id, query
        )

        # Phase 1: Topic Analysis
        print("\n[INFO] ===== Phase 1/8: Topic Analysis =====")
        await self.repository.update_report_status(
            self.current_report_id, "in_progress", "started_at"
        )
        topic_analysis = await self._analyze_topic(query, session_id, user_id, language)
        await self.repository.create_section(
            self.current_report_id, "topic_analysis", 1,
            "Multi-Dimensional Topic Analysis",
            topic_analysis["full_analysis"], "completed"
        )

        # Phase 2: Research Planning
        print("\n[INFO] ===== Phase 2/8: Research Planning =====")
        methodology = await self._plan_research(
            topic_analysis, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "methodology", 2,
            "Research Methodology & Framework",
            methodology["full_plan"], "completed"
        )

        # Phase 3: Initial Data Collection
        print("\n[INFO] ===== Phase 3/8: Data Collection =====")
        initial_data = await self._collect_initial_data(
            topic_analysis, methodology, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "initial_collection", 3,
            "Initial Data Collection", initial_data["summary"], "completed",
            sources_count=initial_data["sources_count"]
        )

        # Phase 4: Iterative Deep Analysis
        print("\n[INFO] ===== Phase 4/8: Deep Analysis =====")
        deep_analysis = await self._perform_deep_analysis(
            topic_analysis, initial_data, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "deep_analysis", 4,
            "Iterative Deep Analysis", deep_analysis["synthesis"], "completed"
        )

        # Get criticism feedback
        await self._process_criticism_feedback(
            "deep_analysis", "Iterative Deep Analysis",
            deep_analysis["synthesis"], query, topic_analysis,
            session_id, user_id, language
        )

        # Phase 5: Gap Analysis
        print("\n[INFO] ===== Phase 5/8: Gap Analysis =====")
        gap_data = await self._analyze_gaps(
            topic_analysis, deep_analysis, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "gap_analysis", 5,
            "Gap Analysis & Additional Research", gap_data["summary"], "completed",
            sources_count=gap_data["sources_count"]
        )

        # Phase 6: Cross-Validation
        print("\n[INFO] ===== Phase 6/8: Cross-Validation =====")
        validation = await self._cross_validate_sources(
            self.all_collected_sources, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "validation", 6,
            "Cross-Validation & Triangulation", validation["report"], "completed"
        )

        # Get criticism feedback
        await self._process_criticism_feedback(
            "validation", "Cross-Validation & Triangulation",
            validation["report"], query, topic_analysis,
            session_id, user_id, language
        )

        # Phase 7: Critical Analysis
        print("\n[INFO] ===== Phase 7/8: Critical Analysis =====")
        critical_analysis = await self._perform_critical_analysis(
            topic_analysis, deep_analysis, validation, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "critical_analysis", 7,
            "Critical Analysis & Perspectives", critical_analysis["full_analysis"], "completed"
        )

        # Phase 8: Final Report Synthesis
        print("\n[INFO] ===== Phase 8/8: Report Synthesis =====")
        final_report = await self._synthesize_final_report(
            topic_analysis, methodology, deep_analysis,
            validation, critical_analysis, session_id, user_id, language
        )

        # Finalize report
        await self.repository.update_report_status(
            self.current_report_id, "completed", "completed_at", quality_score=0.95
        )
        await self._update_report_metadata()

        self._print_research_summary()

        return final_report

    # ========== Phase Implementation Methods ==========

    async def _analyze_topic(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 1: Analyze topic from multiple dimensions."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=3000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["topic_analysis"]
            )

            prompt = TopicAnalysisPrompts.get_prompt(query, language)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            analysis_text = response.content.strip()

            return {
                "full_analysis": analysis_text,
                "research_questions": DataProcessor.extract_research_questions(analysis_text),
                "original_query": query
            }
        except Exception as e:
            print(f"[ERROR] Topic analysis failed: {e}")
            return {
                "full_analysis": f"Topic: {query}\n\nAnalysis pending.",
                "research_questions": [query],
                "original_query": query
            }

    async def _plan_research(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 2: Create comprehensive research plan."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=4000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["research_planning"]
            )

            prompt = ResearchPlanningPrompts.get_prompt(
                topic_analysis['full_analysis'], language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            plan_text = response.content.strip()

            return {
                "full_plan": plan_text,
                "search_strategies": DataProcessor.extract_search_strategies(plan_text)
            }
        except Exception as e:
            print(f"[ERROR] Research planning failed: {e}")
            return {"full_plan": "Research plan pending", "search_strategies": []}

    async def _collect_initial_data(
        self,
        topic_analysis: Dict[str, Any],
        methodology: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 3: Multi-query mass data collection."""
        # Generate query variations
        query_variations = await self._generate_query_variations(
            topic_analysis, session_id, user_id, language
        )

        # Execute complex searches
        complex_results = await self._execute_complex_searches(
            query_variations, topic_analysis, session_id, user_id, language
        )

        # Execute parallel batch searches
        all_results = await self._execute_parallel_searches(query_variations)

        # Add complex search results
        if complex_results:
            all_results.append(complex_results)

        # Deduplicate and track sources
        unique_sources = DataProcessor.deduplicate_sources(all_results)
        self.all_collected_sources.extend(unique_sources)
        self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

        # Track unique domains
        self.research_metadata["unique_domains"].update(
            DataProcessor.extract_unique_domains(unique_sources)
        )

        # Summarize collected data
        summary = await self._summarize_collected_data(
            unique_sources, session_id, user_id, language
        )

        return {
            "summary": summary,
            "sources_count": len(unique_sources),
            "queries_executed": len(query_variations),
            "complex_searches": self.research_metadata["multi_query_searches"]
        }

    async def _perform_deep_analysis(
        self,
        topic_analysis: Dict[str, Any],
        initial_data: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 4: Iterative deep analysis (multiple rounds)."""
        analysis_rounds = []

        for round_num in range(self.config["analysis_iterations"]):
            print(f"[INFO] 🔬 Analysis Round {round_num + 1}/{self.config['analysis_iterations']}")

            previous_insights = "\n\n".join([r["insights"] for r in analysis_rounds]) if analysis_rounds else ""

            round_analysis = await self._execute_analysis_round(
                round_num + 1, topic_analysis, initial_data,
                previous_insights, session_id, user_id, language
            )

            analysis_rounds.append(round_analysis)
            self.research_metadata["analysis_iterations_completed"] += 1

        # Synthesize all rounds
        synthesis = await self._synthesize_analysis_rounds(
            analysis_rounds, session_id, user_id, language
        )

        return {"rounds": analysis_rounds, "synthesis": synthesis}

    async def _analyze_gaps(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 5: Comprehensive gap analysis and additional research."""
        # Identify knowledge gaps
        gaps = await self._identify_knowledge_gaps(
            topic_analysis, deep_analysis, session_id, user_id, language
        )

        print(f"[INFO] 📋 Identified {len(gaps)} knowledge gaps")

        # Execute complex searches for top gaps
        complex_gap_results = await self._execute_complex_searches(
            gaps[:3], topic_analysis, session_id, user_id, language
        )

        # Investigate each gap
        gap_results = await self._investigate_gaps(
            gaps, session_id, user_id, language
        )

        # Add complex search results
        if complex_gap_results:
            gap_results.append(complex_gap_results)

        # Process and add unique sources
        unique_gap_sources = DataProcessor.deduplicate_sources(gap_results)
        self.all_collected_sources.extend(unique_gap_sources)
        self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

        # Summarize gap investigation
        summary = await self._summarize_gap_investigation(
            gaps, unique_gap_sources, session_id, user_id, language
        )

        return {
            "gaps": gaps,
            "summary": summary,
            "sources_count": len(unique_gap_sources)
        }

    async def _cross_validate_sources(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 6: Cross-validation and triangulation."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=3500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["cross_validation"]
            )

            # Sample sources
            sampled_sources = sources[:30] if len(sources) > 30 else sources
            sources_text = "\n\n".join([
                f"Source {i+1} ({s.get('url', 'N/A')}):\n"
                f"{s.get('title', '')}\n{s.get('content', '')[:300]}"
                for i, s in enumerate(sampled_sources)
            ])

            prompt = ValidationPrompts.get_cross_validation_prompt(
                len(sampled_sources), sources_text, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {
                "report": response.content.strip(),
                "sources_analyzed": len(sampled_sources)
            }
        except Exception as e:
            print(f"[ERROR] Cross-validation failed: {e}")
            return {"report": "Cross-validation pending", "sources_analyzed": 0}

    async def _perform_critical_analysis(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 7: Critical thinking and multi-perspective analysis."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.4, max_tokens=4000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["critical_thinking"]
            )

            prompt = ValidationPrompts.get_critical_thinking_prompt(
                topic_analysis['original_query'],
                deep_analysis['synthesis'][:1500],
                validation['report'][:1500],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            self.research_metadata["critical_reviews_completed"] += 1

            return {"full_analysis": response.content.strip()}
        except Exception as e:
            print(f"[ERROR] Critical analysis failed: {e}")
            return {"full_analysis": "Critical analysis pending"}

    async def _synthesize_final_report(
        self,
        topic_analysis: Dict[str, Any],
        methodology: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        critical_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Phase 8: Synthesize comprehensive final report."""
        # Plan report structure
        report_structure = await self._plan_report_structure(
            topic_analysis, session_id, user_id, language
        )

        # Generate sections
        final_sections = []
        section_order = 8

        for section_info in report_structure["sections"]:
            section_title = section_info["title"]
            print(f"[INFO] 📝 Generating section: {section_title}")

            section_content = await self._generate_final_section(
                section_info, topic_analysis, deep_analysis,
                validation, critical_analysis, session_id, user_id, language
            )

            section_id = await self.repository.create_section(
                self.current_report_id, "final_report", section_order,
                section_title, section_content, "completed"
            )

            final_sections.append({
                "section_id": section_id,
                "title": section_title,
                "content": section_content
            })

            section_order += 1

        # Assemble report
        return self._assemble_report(topic_analysis["original_query"], final_sections)

    # ========== Helper Methods ==========

    async def _generate_query_variations(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> List[str]:
        """Generate diverse query variations."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.6, max_tokens=2500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["multi_query_generation"]
            )

            prompt = QueryGenerationPrompts.get_multi_query_prompt(
                topic_analysis['original_query'],
                topic_analysis['research_questions'],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [q.strip() for q in response.content.strip().split('\n')
                      if q.strip() and len(q.strip()) > 5]

            # Ensure minimum queries
            if len(queries) < self.config["multi_query_expansion"]:
                base_query = topic_analysis['original_query']
                fallback = [
                    f"{base_query} overview", f"{base_query} detailed analysis",
                    f"{base_query} latest trends", f"{base_query} market analysis",
                    f"{base_query} technical details", f"{base_query} future outlook",
                    f"{base_query} case studies", f"{base_query} expert opinions",
                    f"{base_query} comparative analysis", f"{base_query} challenges"
                ]
                queries.extend(fallback)

            return queries[:self.config["multi_query_expansion"]]

        except Exception as e:
            print(f"[ERROR] Query generation failed: {e}")
            return [topic_analysis['original_query']]

    async def _execute_complex_searches(
        self,
        queries: List[str],
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> List[Dict[str, Any]]:
        """Execute complex multi-query searches."""
        all_complex_results = []
        priority_queries = queries[:5]

        print(f"[INFO] 🔄 Executing {len(priority_queries)} complex searches...")

        for idx, base_query in enumerate(priority_queries, 1):
            print(f"[INFO] 🔍 Complex search {idx}/{len(priority_queries)}")

            try:
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "detected_language": language
                }

                result = await self.multi_query_agent.execute(base_query, context)

                if result.get("success") and result.get("results"):
                    search_result = result["results"][0]
                    content = search_result.content if hasattr(search_result, 'content') else ""

                    if content:
                        complex_source = {
                            "title": f"Complex Analysis: {base_query}",
                            "content": content[:500],
                            "url": f"multi_query_analysis_{idx}",
                            "score": 0.95,
                            "type": "multi_query_synthesis"
                        }
                        all_complex_results.append(complex_source)
                        self.research_metadata["multi_query_searches"] += 1

                        await self.repository.record_data_collection(
                            self.current_report_id, base_query,
                            "complex_multi_query", 3, [complex_source]
                        )

            except Exception as e:
                print(f"[WARNING] Complex search {idx} failed: {e}")
                continue

        return all_complex_results

    async def _execute_parallel_searches(
        self,
        queries: List[str]
    ) -> List[List[Dict[str, Any]]]:
        """Execute parallel batch searches."""
        batch_size = len(queries) // self.config["parallel_search_batches"]
        all_results = []

        for batch_num in range(self.config["parallel_search_batches"]):
            start_idx = batch_num * batch_size
            end_idx = (start_idx + batch_size
                      if batch_num < self.config["parallel_search_batches"] - 1
                      else len(queries))
            batch_queries = queries[start_idx:end_idx]

            print(f"[INFO] 📦 Batch {batch_num + 1}: {len(batch_queries)} queries")

            batch_results = await self._search_batch_parallel(batch_queries)
            all_results.extend(batch_results)

            # Record in database
            for query, results in zip(batch_queries, batch_results):
                await self.repository.record_data_collection(
                    self.current_report_id, query, "multi_query_initial", 3, results
                )
                self.research_metadata["total_queries_executed"] += 1

        return all_results

    async def _search_batch_parallel(
        self,
        queries: List[str]
    ) -> List[List[Dict[str, Any]]]:
        """Execute batch of queries in parallel."""
        tasks = [self._single_tavily_search(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[WARNING] Search failed for '{queries[i]}': {result}")
                processed.append([])
            else:
                processed.append(result)

        return processed

    async def _single_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute single Tavily search."""
        try:
            if not self.api_available or not self.tavily_client:
                return []

            import concurrent.futures
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
                        return None

                response = await asyncio.get_event_loop().run_in_executor(None, get_result)
                return response.get("results", []) if response else []

        except Exception as e:
            print(f"[ERROR] Tavily search error: {e}")
            return []

    async def _summarize_collected_data(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Summarize collected data."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=2500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["data_summarization"]
            )

            sample = sources[:20]
            sources_sample = "\n\n".join([
                f"- {s.get('title', '')}: {s.get('content', '')[:200]}"
                for s in sample
            ])

            prompt = AnalysisPrompts.get_data_summary_prompt(
                len(sources), sources_sample, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Data summarization failed: {e}")
            return f"Collected {len(sources)} sources for analysis"

    async def _execute_analysis_round(
        self,
        round_num: int,
        topic_analysis: Dict[str, Any],
        initial_data: Dict[str, Any],
        previous_insights: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Execute single analysis round."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=3000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=[f"analysis_round_{round_num}"]
            )

            prompt = AnalysisPrompts.get_iterative_analysis_prompt(
                round_num, topic_analysis['original_query'],
                initial_data['summary'], previous_insights, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {"round": round_num, "insights": response.content.strip()}

        except Exception as e:
            print(f"[ERROR] Analysis round {round_num} failed: {e}")
            return {"round": round_num, "insights": f"Round {round_num} pending"}

    async def _synthesize_analysis_rounds(
        self,
        rounds: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Synthesize all analysis rounds."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=3000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["analysis_synthesis"]
            )

            rounds_text = "\n\n".join([
                f"Round {r['round']}:\n{r['insights'][:800]}"
                for r in rounds
            ])

            prompt = AnalysisPrompts.get_synthesis_prompt(
                len(rounds), rounds_text, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Synthesis failed: {e}")
            return "Analysis synthesis pending"

    async def _identify_knowledge_gaps(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> List[str]:
        """Identify knowledge gaps."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_identification"]
            )

            prompt = AnalysisPrompts.get_gap_identification_prompt(
                topic_analysis['research_questions'],
                deep_analysis['synthesis'],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            gaps = [g.strip() for g in response.content.strip().split('\n')
                   if g.strip() and len(g.strip()) > 10]
            return gaps[:15]

        except Exception as e:
            print(f"[ERROR] Gap identification failed: {e}")
            return []

    async def _investigate_gaps(
        self,
        gaps: List[str],
        session_id: str,
        user_id: str,
        language: str
    ) -> List[List[Dict[str, Any]]]:
        """Investigate identified gaps."""
        gap_results = []

        for idx, gap in enumerate(gaps[:10], 1):
            print(f"[INFO] 🎯 Gap {idx}/{min(len(gaps), 10)}")

            gap_queries = await self._generate_gap_queries(
                gap, session_id, user_id, language
            )
            results = await self._search_batch_parallel(gap_queries)
            gap_results.extend(results)

            for query, result in zip(gap_queries, results):
                await self.repository.record_data_collection(
                    self.current_report_id, query, "gap_filling", 5, result
                )
                self.research_metadata["total_queries_executed"] += 1

        return gap_results

    async def _generate_gap_queries(
        self,
        gap: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> List[str]:
        """Generate queries for specific gap."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.4, max_tokens=800),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_query_generation"]
            )

            prompt = QueryGenerationPrompts.get_gap_query_prompt(gap, language)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [q.strip() for q in response.content.strip().split('\n')
                      if q.strip() and len(q.strip()) > 5]
            return queries[:5]

        except Exception as e:
            print(f"[ERROR] Gap query generation failed: {e}")
            return [gap]

    async def _summarize_gap_investigation(
        self,
        gaps: List[str],
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Summarize gap investigation."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_summary"]
            )

            # gaps_text = '\n'.join([f"- {g}" for g in gaps[:10]])
            sources_sample = '\n'.join([f"- {s.get('title', '')}" for s in sources[:15]])

            prompt = AnalysisPrompts.get_gap_summary_prompt(
                gaps, len(sources), sources_sample, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Gap summary failed: {e}")
            return f"Investigated {len(gaps)} gaps with {len(sources)} sources"

    async def _process_criticism_feedback(
        self,
        section_type: str,
        section_title: str,
        section_content: str,
        topic: str,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> None:
        """Get and process criticism feedback."""
        print(f"[INFO] 🔍 Requesting criticism feedback for: {section_title}")

        try:
            feedback = await self.criticism_agent.generate_feedback(
                topic=topic,
                section_type=section_type,
                section_content=section_content,
                research_context={
                    "sources_count": self.research_metadata["total_sources_collected"],
                    "research_questions": topic_analysis.get("research_questions", [])
                },
                session_id=session_id,
                user_id=user_id,
                language=language
            )

            self.research_metadata["criticism_feedbacks_generated"] += 1

            # Record feedback
            await self.repository.record_criticism_feedback(
                self.current_report_id, section_type, section_title, feedback
            )

            # Handle additional research if needed
            if self.criticism_agent.should_trigger_additional_research(feedback):
                print("[INFO] 🔄 Triggering additional research from feedback...")
                self.research_metadata["additional_research_triggered"] += 1
                await self._conduct_feedback_research(feedback, section_type)

        except Exception as e:
            print(f"[ERROR] Criticism feedback failed: {e}")

    async def _conduct_feedback_research(
        self,
        feedback: Dict[str, Any],
        section_type: str
    ) -> None:
        """Conduct additional research based on feedback."""
        suggested_queries = feedback.get("suggested_queries", [])[:5]
        missing_perspectives = feedback.get("missing_perspectives", [])[:3]

        queries = suggested_queries + [
            f"{p} detailed analysis" for p in missing_perspectives
        ]

        if queries:
            results = await self._search_batch_parallel(queries)
            flat_results = [item for sublist in results for item in sublist]

            unique_sources = DataProcessor.deduplicate_sources([flat_results])
            self.all_collected_sources.extend(unique_sources)
            self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

    async def _plan_report_structure(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Plan final report structure."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["report_structure"]
            )

            prompt = ValidationPrompts.get_report_structure_prompt(
                topic_analysis['original_query'], language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            sections = []
            for line in response.content.strip().split('\n'):
                if '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 2:
                        sections.append({
                            "title": parts[0],
                            "purpose": parts[1] if len(parts) > 1 else "",
                            "content_type": parts[2] if len(parts) > 2 else ""
                        })

            return {"sections": sections[:12]}

        except Exception as e:
            print(f"[ERROR] Report structure planning failed: {e}")
            return {"sections": [{"title": "Summary", "purpose": "Overview"}]}

    async def _generate_final_section(
        self,
        section_info: Dict[str, Any],
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        critical_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> str:
        """Generate final report section."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=3500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["final_section_generation"]
            )

            prompt = ValidationPrompts.get_final_section_prompt(
                section_info['title'],
                section_info.get('purpose', ''),
                topic_analysis['original_query'],
                deep_analysis['synthesis'],
                validation['report'],
                critical_analysis['full_analysis'],
                self.research_metadata['total_sources_collected'],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Section generation failed: {e}")
            return f"Section {section_info['title']}: Content pending"

    def _assemble_report(
        self,
        topic: str,
        sections: List[Dict[str, Any]]
    ) -> str:
        """Assemble final report from sections."""
        parts = [
            f"# {topic}\n",
            "## HyperDeepResearch Comprehensive Report\n",
            f"\n**Report ID:** `{self.current_report_id}`\n",
            f"**Generated:** {datetime.utcnow().isoformat()}\n",
            "\n---\n",
            "\n## 📊 Research Statistics\n",
            f"- **Total Sources:** {self.research_metadata['total_sources_collected']}\n",
            f"- **Total Queries:** {self.research_metadata['total_queries_executed']}\n",
            f"- **Complex Searches:** {self.research_metadata['multi_query_searches']}\n",
            f"- **Unique Domains:** {len(self.research_metadata['unique_domains'])}\n",
            f"- **Analysis Iterations:** {self.research_metadata['analysis_iterations_completed']}\n",
            f"- **Critical Reviews:** {self.research_metadata['critical_reviews_completed']}\n",
            f"- **Criticism Feedbacks:** {self.research_metadata['criticism_feedbacks_generated']}\n",
            f"- **Additional Research Triggered:** {self.research_metadata['additional_research_triggered']}\n",
            "\n---\n"
        ]

        for section in sections:
            parts.append(f"\n## {section['title']}\n")
            parts.append(f"\n{section['content']}\n")

        parts.append("\n---\n")
        parts.append(f"\n**Report ID: `{self.current_report_id}`**\n")

        return "".join(parts)

    async def _update_report_metadata(self) -> None:
        """Update final report metadata."""
        await self.repository.update_report_metadata(
            self.current_report_id,
            len(self.sections_data),
            self.research_metadata["total_sources_collected"],
            self.research_metadata["total_queries_executed"],
            {
                "unique_domains": len(self.research_metadata["unique_domains"]),
                "analysis_iterations": self.research_metadata["analysis_iterations_completed"],
                "critical_reviews": self.research_metadata["critical_reviews_completed"],
                "multi_query_searches": self.research_metadata["multi_query_searches"],
                "criticism_feedbacks_generated": self.research_metadata["criticism_feedbacks_generated"],
                "additional_research_triggered": self.research_metadata["additional_research_triggered"]
            }
        )

    def _print_research_summary(self) -> None:
        """Print research process summary."""
        print("\n[INFO] ========== HyperDeepResearch Completed ==========")
        print(f"[INFO] 📊 Report ID: {self.current_report_id}")
        print(f"[INFO] 📚 Sections: {len(self.sections_data)}")
        print(f"[INFO] 🔍 Queries: {self.research_metadata['total_queries_executed']}")
        print(f"[INFO] 🔄 Complex Searches: {self.research_metadata['multi_query_searches']}")
        print(f"[INFO] 📄 Sources: {self.research_metadata['total_sources_collected']}")
        print(f"[INFO] 🌐 Domains: {len(self.research_metadata['unique_domains'])}")
        print(f"[INFO] 🔍 Feedbacks: {self.research_metadata['criticism_feedbacks_generated']}")
        print(f"[INFO] 🔄 Additional Research: {self.research_metadata['additional_research_triggered']}")
