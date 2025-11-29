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
from langchain_core.messages import HumanMessage
import logging

from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm

from ...base import SearchAgent
from ...planning_agent import PlanningAgent
from ..multi_query_search import MultiQuerySearchAgent
from ..criticism_feedback_agent import CriticismFeedbackAgent

from .prompts import (
    TopicAnalysisPrompts,
    ResearchPlanningPrompts,
    QueryGenerationPrompts,
    AnalysisPrompts,
    ValidationPrompts
)
from .repository import HyperResearchRepository
from .utils import (
    LanguageDetector,
    DataProcessor,
    TokenCounter,
    SourceQualityScorer,
    RetryHandler,
    ComplexityAssessor,
    DeepDiveAnalyzer,
    SemanticClusterer,
    CostOptimizer,
    FactChecker,
    BiasDetector,
    ResearchEventLogger,
)


logger = logging.getLogger(__name__)


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
        print("[DEBUG] HyperDeepResearchAgent.__init__ called")
        super().__init__(
            name="hyper_deep_research",
            search_type="hyper_deep_research",
            role="Elite Research Director & Critical Analyst",
            goal="Conduct exhaustive, multi-dimensional research with rigorous methodology",
            backstory="World-renowned research director combining academic rigor, "
                    "investigative journalism, and critical analysis depth."
        )
        print("[DEBUG] Parent class initialized")

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
        print("[DEBUG] Initializing Tavily client...")
        self._init_tavily_client()
        print(f"[DEBUG] Tavily client initialized. API available: {self.api_available}")

        # Initialize sub-agents
        print("[DEBUG] Initializing sub-agents...")
        self.planning_agent = PlanningAgent()
        self.multi_query_agent = MultiQuerySearchAgent()
        self.criticism_agent = CriticismFeedbackAgent()
        print("[DEBUG] Sub-agents initialized")

        # Initialize repository
        print("[DEBUG] Initializing repository...")
        self.repository = HyperResearchRepository()
        print("[DEBUG] Repository initialized")

        # Initialize enhanced utilities
        print("[DEBUG] Initializing enhanced utilities...")
        self.token_counter = TokenCounter()
        self.quality_scorer = SourceQualityScorer()
        self.retry_handler = RetryHandler(max_attempts=4, base_delay=2.0)
        self.complexity_assessor = ComplexityAssessor()
        self.deep_dive_analyzer = DeepDiveAnalyzer(max_depth=2, min_importance_score=8.0)
        self.semantic_clusterer = SemanticClusterer(similarity_threshold=0.75)
        self.cost_optimizer = CostOptimizer(budget_limit=100.0, cache_ttl=3600)
        self.fact_checker = FactChecker()
        self.bias_detector = BiasDetector()
        print("[DEBUG] Enhanced utilities initialized")

        # Rate limiting for API calls (from settings)
        # Limit concurrent Tavily API requests to prevent 429 errors
        self.tavily_rate_limiter = asyncio.Semaphore(settings.DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS)
        self.min_request_interval = settings.DEEP_RESEARCH_MIN_REQUEST_INTERVAL
        self.last_request_time = 0

        # Research state
        self.current_report_id = None
        self.sections_data = []
        # Memory optimization: Keep only recent sources in memory (from settings)
        self.all_collected_sources = []
        self.max_sources_in_memory = settings.DEEP_RESEARCH_MAX_SOURCES_IN_MEMORY
        self.research_metadata = {
            "total_queries_executed": 0,
            "total_sources_collected": 0,
            "unique_domains": set(),
            "analysis_iterations_completed": 0,
            "critical_reviews_completed": 0,
            "multi_query_searches": 0,
            "criticism_feedbacks_generated": 0,
            "additional_research_triggered": 0,
            "api_rate_limit_hits": 0,
            # LLM cost tracking
            "llm_calls": 0,
            "estimated_total_tokens": 0,
            "llm_calls_by_phase": {}
        }

        # Event logger for real-time progress tracking (initialized per research session)
        self.event_logger = None

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
        print(f"[DEBUG] HyperDeepResearchAgent.execute called with query: {query[:50]}...")
        print(f"[DEBUG] Context: {context}")
        print(f"[DEBUG] API available: {self.api_available}")

        if not self.validate_input(query, context):
            print(f"[ERROR] Input validation failed for query: {query}")
            return {"success": False, "error": "Invalid input"}

        if not self.api_available:
            print("[ERROR] Tavily API unavailable, cannot proceed with research")
            return self.format_output(
                [], {"search_type": "hyper_deep_research", "warning": "API unavailable"}
            )

        try:
            # Extract context parameters
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""
            report_id = context.get("report_id", None) if context else None

            # Detect query language
            language = LanguageDetector.detect(query)
            print(f"[INFO] Detected language: {LanguageDetector.get_language_name(language)}")

            # Update context with detected language
            if context is None:
                context = {}
            context["detected_language"] = language

            # Execute research process
            report_content = await self._run_research_process(
                query, session_id, user_id, language, report_id
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
        language: str,
        report_id: str = None
    ) -> str:
        """Execute the complete research process.

        Args:
            query: Research topic
            session_id: Session identifier
            user_id: User identifier
            language: Detected language code
            report_id: Optional existing report ID to use (if None, creates new)

        Returns:
            Complete research report as markdown string
        """
        print("[INFO] ========== HyperDeepResearch Process Started ==========")
        print(f"[INFO] 🚀 Target: {self.config['target_total_sources']} sources minimum")

        # Initialize report
        if report_id:
            self.current_report_id = report_id
            print(f"[INFO] Using existing report ID: {report_id}")
        else:
            self.current_report_id = f"hyper_report_{uuid.uuid4()}"
            print(f"[INFO] Created new report ID: {self.current_report_id}")

        await self.repository.ensure_tables_exist()

        # Only create report if we generated a new ID (external report already exists)
        if not report_id:
            await self.repository.create_report(
                self.current_report_id, user_id, session_id, query
            )

        # Initialize event logger for real-time progress tracking
        # Enable CLI output based on context (will be True for CLI mode, False for API)
        enable_cli = session_id.startswith("cli_") if session_id else False
        self.event_logger = ResearchEventLogger(
            report_id=self.current_report_id,
            enable_cli_output=enable_cli
        )
        print(f"[DEBUG] EventLogger initialized (CLI output: {enable_cli})")

        # Phase 1: Topic Analysis
        print("\n[INFO] ===== Phase 1/8: Topic Analysis =====")
        await self.event_logger.log_phase_start(1, "Topic Analysis")
        await self.repository.update_report_status(
            self.current_report_id, "in_progress", "started_at"
        )
        phase1_start = datetime.utcnow()
        topic_analysis = await self._analyze_topic(query, session_id, user_id, language)
        await self.repository.create_section(
            self.current_report_id, "topic_analysis", 1,
            "Multi-Dimensional Topic Analysis",
            topic_analysis["full_analysis"], "completed"
        )
        phase1_duration = int((datetime.utcnow() - phase1_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(1, "Topic Analysis", phase1_duration)

        # Assess topic complexity for adaptive depth
        print("\n[INFO] 🎯 Assessing topic complexity...")
        complexity_assessment = await self.complexity_assessor.assess_complexity(
            topic_analysis
        )
        print(
            f"[INFO] Complexity: {complexity_assessment['complexity_level']} "
            f"(score: {complexity_assessment['complexity_score']}, "
            f"iterations: {complexity_assessment['recommended_iterations']})"
        )
        # Update config with adaptive iterations
        self.config["analysis_iterations"] = complexity_assessment["recommended_iterations"]

        # Phase 2: Research Planning
        print("\n[INFO] ===== Phase 2/8: Research Planning =====")
        await self.event_logger.log_phase_start(2, "Research Planning")
        phase2_start = datetime.utcnow()
        methodology = await self._plan_research(
            topic_analysis, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "methodology", 2,
            "Research Methodology & Framework",
            methodology["full_plan"], "completed"
        )
        phase2_duration = int((datetime.utcnow() - phase2_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(2, "Research Planning", phase2_duration)

        # Phase 3: Initial Data Collection
        print("\n[INFO] ===== Phase 3/8: Data Collection =====")
        await self.event_logger.log_phase_start(3, "Data Collection")
        phase3_start = datetime.utcnow()
        initial_data = await self._collect_initial_data(
            topic_analysis, methodology, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "initial_collection", 3,
            "Initial Data Collection", initial_data["summary"], "completed",
            sources_count=initial_data["sources_count"]
        )
        phase3_duration = int((datetime.utcnow() - phase3_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(3, "Data Collection", phase3_duration)

        # Phase 4: Iterative Deep Analysis
        print("\n[INFO] ===== Phase 4/8: Deep Analysis =====")
        await self.event_logger.log_phase_start(4, "Deep Analysis")
        phase4_start = datetime.utcnow()
        deep_analysis = await self._perform_deep_analysis(
            topic_analysis, initial_data, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "deep_analysis", 4,
            "Iterative Deep Analysis", deep_analysis["synthesis"], "completed"
        )
        phase4_duration = int((datetime.utcnow() - phase4_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(4, "Deep Analysis", phase4_duration)

        # Get criticism feedback
        await self._process_criticism_feedback(
            "deep_analysis", "Iterative Deep Analysis",
            deep_analysis["synthesis"], query, topic_analysis,
            session_id, user_id, language
        )

        # Phase 4.5: Recursive Deep Dive (NEW)
        print("\n[INFO] ===== Phase 4.5/8: Recursive Deep Dive =====")
        deep_dive_results = await self._perform_recursive_deep_dive(
            deep_analysis["synthesis"], query, session_id, user_id, language
        )
        if deep_dive_results and deep_dive_results.get("explorations"):
            deep_dive_synthesis = self.deep_dive_analyzer.synthesize_deep_dives(deep_dive_results)
            await self.repository.create_section(
                self.current_report_id, "recursive_deep_dive", 4.5,
                "Recursive Deep Dive Explorations", deep_dive_synthesis, "completed"
            )
            print(
                f"[INFO] 🔬 Deep dive complete: {deep_dive_results.get('insights_explored', 0)} "
                f"insights explored in depth"
            )

        # Phase 5: Gap Analysis
        print("\n[INFO] ===== Phase 5/8: Gap Analysis =====")
        await self.event_logger.log_phase_start(5, "Gap Analysis")
        phase5_start = datetime.utcnow()
        gap_data = await self._analyze_gaps(
            topic_analysis, deep_analysis, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "gap_analysis", 5,
            "Gap Analysis & Additional Research", gap_data["summary"], "completed",
            sources_count=gap_data["sources_count"]
        )
        phase5_duration = int((datetime.utcnow() - phase5_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(5, "Gap Analysis", phase5_duration)

        # Phase 6: Cross-Validation
        print("\n[INFO] ===== Phase 6/8: Cross-Validation =====")
        await self.event_logger.log_phase_start(6, "Cross-Validation")
        phase6_start = datetime.utcnow()

        # Apply semantic clustering to all collected sources
        clusters = await self._apply_semantic_clustering(self.all_collected_sources)

        validation = await self._cross_validate_sources(
            self.all_collected_sources, session_id, user_id, language, clusters
        )
        await self.repository.create_section(
            self.current_report_id, "validation", 6,
            "Cross-Validation & Triangulation", validation["report"], "completed"
        )
        phase6_duration = int((datetime.utcnow() - phase6_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(6, "Cross-Validation", phase6_duration)

        # Get criticism feedback
        await self._process_criticism_feedback(
            "validation", "Cross-Validation & Triangulation",
            validation["report"], query, topic_analysis,
            session_id, user_id, language
        )

        # Phase 6.5: Fact Verification
        print("\n[INFO] ===== Phase 6.5/8: Fact Verification & Claim Analysis =====")
        fact_verification = await self._perform_fact_verification(
            self.all_collected_sources, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "fact_verification", 6.5,
            "Fact Verification & Contradiction Analysis",
            fact_verification["report"], "completed"
        )

        # Phase 7: Critical Analysis
        print("\n[INFO] ===== Phase 7/8: Critical Analysis =====")
        await self.event_logger.log_phase_start(7, "Critical Analysis")
        phase7_start = datetime.utcnow()
        critical_analysis = await self._perform_critical_analysis(
            topic_analysis, deep_analysis, validation, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "critical_analysis", 7,
            "Critical Analysis & Perspectives", critical_analysis["full_analysis"], "completed"
        )
        phase7_duration = int((datetime.utcnow() - phase7_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(7, "Critical Analysis", phase7_duration)

        # Phase 7.5: Bias Detection & Perspective Diversity
        print("\n[INFO] ===== Phase 7.5/8: Bias & Perspective Analysis =====")
        bias_analysis = await self._perform_bias_analysis(
            self.all_collected_sources, session_id, user_id, language
        )
        await self.repository.create_section(
            self.current_report_id, "bias_analysis", 7.5,
            "Bias Detection & Perspective Diversity",
            bias_analysis["report"], "completed"
        )

        # Phase 8: Final Report Synthesis
        print("\n[INFO] ===== Phase 8/8: Report Synthesis =====")
        await self.event_logger.log_phase_start(8, "Report Synthesis")
        phase8_start = datetime.utcnow()
        final_report = await self._synthesize_final_report(
            topic_analysis, methodology, deep_analysis,
            validation, critical_analysis, session_id, user_id, language
        )
        phase8_duration = int((datetime.utcnow() - phase8_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(8, "Report Synthesis", phase8_duration)

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

            # Log LLM call start
            await self.event_logger.log_llm_call(
                "topic_analysis",
                "Analyzing topic from multiple dimensions",
                estimated_tokens=3000
            )

            prompt = TopicAnalysisPrompts.get_prompt(query, language)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            analysis_text = response.content.strip()

            # Track LLM usage
            self._track_llm_call("topic_analysis", prompt, analysis_text)

            # Log LLM completion
            await self.event_logger.log_llm_complete(
                "topic_analysis",
                "Topic analysis completed",
                actual_tokens=len(analysis_text)
            )

            return {
                "full_analysis": analysis_text,
                "research_questions": DataProcessor.extract_research_questions(analysis_text),
                "original_query": query
            }
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            print(f"[ERROR] Topic analysis timeout/cancelled: {e}")
            raise
        except (KeyError, AttributeError, ValueError) as e:
            print(f"[ERROR] Topic analysis data processing error: {e}")
            return {
                "full_analysis": f"Topic: {query}\n\nAnalysis pending.",
                "research_questions": [query],
                "original_query": query
            }
        except Exception as e:
            print(f"[ERROR] Topic analysis unexpected error: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
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

            # Track LLM usage
            self._track_llm_call("research_planning", prompt, plan_text)

            return {
                "full_plan": plan_text,
                "search_strategies": DataProcessor.extract_search_strategies(plan_text)
            }
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            print(f"[ERROR] Research planning timeout/cancelled: {e}")
            raise
        except KeyError as e:
            print(f"[ERROR] Research planning missing key: {e}")
            return {"full_plan": "Research plan pending", "search_strategies": []}
        except Exception as e:
            print(f"[ERROR] Research planning unexpected error: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
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
        await self.event_logger.log_status_message(
            f"Generating {self.config['multi_query_expansion']} query variations...",
            "info"
        )
        query_variations = await self._generate_query_variations(
            topic_analysis, session_id, user_id, language
        )
        await self.event_logger.log_status_message(
            f"Generated {len(query_variations)} queries for search",
            "success"
        )

        # Execute complex searches
        await self.event_logger.log_status_message(
            "Executing complex multi-query searches...",
            "info"
        )
        complex_results = await self._execute_complex_searches(
            query_variations, topic_analysis, session_id, user_id, language
        )

        # Execute parallel batch searches
        await self.event_logger.log_status_message(
            f"Executing parallel search batches ({self.config['parallel_search_batches']} batches)...",
            "info"
        )
        all_results = await self._execute_parallel_searches(query_variations)

        # Add complex search results
        if complex_results:
            all_results.append(complex_results)

        # Deduplicate and track sources
        unique_sources = DataProcessor.deduplicate_sources(all_results)

        # Apply quality scoring
        print(f"[INFO] 📊 Scoring {len(unique_sources)} sources for quality...")
        await self.event_logger.log_status_message(
            f"Scoring {len(unique_sources)} sources for quality...",
            "info"
        )
        scored_sources = self.quality_scorer.rank_sources(unique_sources)
        print(f"[INFO] ✅ Quality scoring complete. High quality: {self.quality_scorer.stats['high_quality_count']}")
        await self.event_logger.log_sources_collected(
            len(scored_sources),
            self.research_metadata["total_sources_collected"]
        )

        # Memory optimization: Store sources in batches, keep only recent ones in memory
        await self._store_sources_batch(scored_sources)

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

        # Memory optimization: Store sources in batches
        await self._store_sources_batch(unique_gap_sources)

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
        language: str,
        clusters: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Phase 6: Cross-validation and triangulation with semantic clustering."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=3500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["cross_validation"]
            )

            # Sample sources - use recent sources from memory
            all_sources = await self._get_all_sources_sample(limit=30)
            sampled_sources = all_sources[:30] if len(all_sources) > 30 else all_sources
            sources_text = "\n\n".join([
                f"Source {i+1} ({s.get('url', 'N/A')}):\n"
                f"{s.get('title', '')}\n{s.get('content', '')[:300]}"
                for i, s in enumerate(sampled_sources)
            ])

            # Include cluster information if available
            cluster_info = ""
            if clusters:
                cluster_info = f"\n\nSemantic Clusters Identified: {len(clusters)}\n"
                for i, cluster in enumerate(clusters[:5], 1):
                    themes = ", ".join(cluster.get("themes", [])[:3])
                    cluster_info += f"- Cluster {i}: {cluster.get('size', 0)} sources on {themes}\n"

            prompt = ValidationPrompts.get_cross_validation_prompt(
                len(sampled_sources), sources_text + cluster_info, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {
                "report": response.content.strip(),
                "sources_analyzed": len(sampled_sources),
                "clusters_identified": len(clusters) if clusters else 0
            }
        except Exception as e:
            print(f"[ERROR] Cross-validation failed: {e}")
            return {"report": "Cross-validation pending", "sources_analyzed": 0}

    async def _perform_fact_verification(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 6.5: Fact verification and contradiction detection."""
        try:
            print(f"[INFO] Verifying facts across {len(sources)} sources...")

            # Create LLM for fact extraction
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.1, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["fact_verification"]
            )

            # Use fact checker to verify sources
            verification_results = await self.fact_checker.verify_sources(
                sources=sources,
                llm_callable=llm.ainvoke,
                language=language
            )

            # Log statistics
            stats = verification_results.get("stats", {})
            print(f"[INFO] ✓ Extracted {stats.get('total_claims', 0)} claims")
            print(f"[INFO] ✓ Found {stats.get('contradictions_found', 0)} contradictions")

            return {
                "report": verification_results.get("report", "Fact verification pending"),
                "claims": verification_results.get("claims", []),
                "contradictions": verification_results.get("contradictions", []),
                "stats": stats
            }

        except Exception as e:
            print(f"[ERROR] Fact verification failed: {e}")
            logger.error(f"[FactVerification] Error: {e}", exc_info=True)
            return {
                "report": "Fact verification pending due to error",
                "claims": [],
                "contradictions": [],
                "stats": {}
            }

    async def _perform_bias_analysis(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """Phase 7.5: Bias detection and perspective diversity analysis."""
        try:
            print(f"[INFO] Analyzing bias and perspectives across {len(sources)} sources...")

            # Create LLM for bias analysis
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["bias_detection"]
            )

            # Use bias detector to analyze sources
            bias_results = await self.bias_detector.analyze_bias(
                sources=sources,
                llm_callable=llm.ainvoke,
                language=language
            )

            # Log statistics
            stats = bias_results.get("stats", {})
            diversity_score = bias_results.get("diversity_score", 0)
            print(f"[INFO] ✓ Diversity Score: {diversity_score:.1f}/100")
            print(f"[INFO] ✓ Biases Detected: {stats.get('biases_detected', 0)}")
            print(f"[INFO] ✓ High Severity: {stats.get('high_severity_biases', 0)}")

            return {
                "report": bias_results.get("report", "Bias analysis pending"),
                "diversity_score": diversity_score,
                "bias_indicators": bias_results.get("bias_indicators", []),
                "diversity_analysis": bias_results.get("diversity_analysis", {}),
                "stats": stats
            }

        except Exception as e:
            print(f"[ERROR] Bias analysis failed: {e}")
            logger.error(f"[BiasAnalysis] Error: {e}", exc_info=True)
            return {
                "report": "Bias analysis pending due to error",
                "diversity_score": 0.0,
                "bias_indicators": [],
                "stats": {}
            }

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

            # Log the query being executed
            await self.event_logger.log_query_execution(
                base_query,
                idx,
                len(priority_queries)
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
        total_batches = self.config["parallel_search_batches"]

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = (start_idx + batch_size
                      if batch_num < total_batches - 1
                      else len(queries))
            batch_queries = queries[start_idx:end_idx]

            print(f"[INFO] 📦 Batch {batch_num + 1}: {len(batch_queries)} queries")

            # Log batch execution start
            await self.event_logger.log_progress(
                batch_num + 1,
                total_batches,
                f"Executing search batch {batch_num + 1}/{total_batches}"
            )

            # Log each query before execution
            for query in batch_queries:
                await self.event_logger.log_query_execution(
                    query,
                    batch_num + 1,
                    total_batches
                )

            batch_results = await self._search_batch_parallel(batch_queries)
            all_results.extend(batch_results)

            # Count sources in this batch
            batch_sources_count = sum(len(r) for r in batch_results)

            # Record in database
            for query, results in zip(batch_queries, batch_results):
                await self.repository.record_data_collection(
                    self.current_report_id, query, "multi_query_initial", 3, results
                )
                self.research_metadata["total_queries_executed"] += 1

            # Log batch completion with source count
            await self.event_logger.log_sources_collected(
                batch_sources_count,
                self.research_metadata["total_sources_collected"],
                batch_num + 1
            )

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
        """Execute single Tavily search with rate limiting and retry logic.

        Rate limiting prevents API 429 errors by:
        - Limiting concurrent requests to 3
        - Enforcing minimum 0.5s interval between requests
        - Retry with exponential backoff on failures
        """
        try:
            if not self.api_available or not self.tavily_client:
                return []

            # Use retry handler for robust execution
            return await self.retry_handler.execute_with_retry(
                self._execute_tavily_search,
                query,
                retry_exceptions=(ConnectionError, TimeoutError, OSError)
            )

        except Exception as e:
            print(f"[ERROR] Tavily search failed after retries: {e}")
            return []

    async def _execute_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute Tavily search (internal method for retry).

        Args:
            query: Search query

        Returns:
            List of search results
        """
        try:
            # Rate limiting: wait for semaphore slot
            async with self.tavily_rate_limiter:
                # Enforce minimum interval between requests
                import time
                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_request_interval:
                    await asyncio.sleep(self.min_request_interval - time_since_last)

                self.last_request_time = time.time()

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
                            print(f"[WARNING] Tavily search timeout for query: {query[:50]}...")
                            return None

                    response = await asyncio.get_event_loop().run_in_executor(None, get_result)

                    # Check for rate limit response
                    if response and isinstance(response, dict):
                        if response.get("status_code") == 429:
                            print("[WARNING] Rate limit hit for Tavily API")
                            self.research_metadata["api_rate_limit_hits"] += 1
                            await asyncio.sleep(2)  # Wait 2 seconds before retry
                            return []

                    return response.get("results", []) if response else []

        except concurrent.futures.TimeoutError as e:
            print(f"[WARNING] Tavily search timeout: {e}")
            return []
        except (ConnectionError, OSError) as e:
            print(f"[ERROR] Tavily search network error: {e}")
            return []
        except (KeyError, AttributeError) as e:
            print(f"[ERROR] Tavily search response parsing error: {e}")
            return []
        except Exception as e:
            print(f"[ERROR] Tavily search unexpected error: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
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

            # Memory optimization: Store sources in batches
            await self._store_sources_batch(unique_sources)

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
                "additional_research_triggered": self.research_metadata["additional_research_triggered"],
                "api_rate_limit_hits": self.research_metadata["api_rate_limit_hits"],
                # LLM cost tracking
                "llm_calls": self.research_metadata["llm_calls"],
                "estimated_total_tokens": self.research_metadata["estimated_total_tokens"],
                "llm_calls_by_phase": self.research_metadata["llm_calls_by_phase"]
            }
        )

    def _track_llm_call(self, phase: str, prompt: str, response: str) -> None:
        """Track LLM API call for cost monitoring.

        Uses TokenCounter for accurate token counting with tiktoken.
        Integrates with CostOptimizer for caching and budget management.
        """
        # Use TokenCounter for accurate counting
        usage = self.token_counter.track_usage(
            prompt, response, metadata={"phase": phase, "model": "gpt-4"}
        )

        prompt_tokens = usage["prompt_tokens"]
        response_tokens = usage["completion_tokens"]
        total_tokens = usage["total_tokens"]
        estimated_cost = usage["estimated_cost"]

        self.research_metadata["llm_calls"] += 1
        self.research_metadata["estimated_total_tokens"] += total_tokens

        # Track by phase
        if phase not in self.research_metadata["llm_calls_by_phase"]:
            self.research_metadata["llm_calls_by_phase"][phase] = {
                "calls": 0,
                "tokens": 0,
                "cost": 0.0
            }

        self.research_metadata["llm_calls_by_phase"][phase]["calls"] += 1
        self.research_metadata["llm_calls_by_phase"][phase]["tokens"] += total_tokens
        self.research_metadata["llm_calls_by_phase"][phase]["cost"] = (
            self.research_metadata["llm_calls_by_phase"][phase].get("cost", 0.0) + estimated_cost
        )

        # Cache response for future reuse
        self.cost_optimizer.cache_response(
            prompt=prompt,
            response=response,
            cost=estimated_cost,
            metadata={"phase": phase, "tokens": total_tokens}
        )

        # Track cost and check budget
        within_budget = self.cost_optimizer.track_cost(estimated_cost, phase)

        if not within_budget:
            print(
                f"[WARNING] ⚠️ Budget exceeded! Phase: {phase}, "
                f"Total: ${self.cost_optimizer.total_cost:.2f}"
            )

        print(
            f"[DEBUG] LLM call tracked - Phase: {phase}, Tokens: {total_tokens}, "
            f"Cost: ${estimated_cost:.4f}, Budget: {self.cost_optimizer.total_cost:.2f}/"
            f"{self.cost_optimizer.budget_limit:.2f}"
        )

    async def _store_sources_batch(self, sources: List[Dict[str, Any]]) -> None:
        """Store sources with memory optimization

        Keeps only recent sources in memory, stores all in DB for persistence
        """
        if not sources:
            return

        # Add to in-memory cache (keep only most recent)
        self.all_collected_sources.extend(sources)
        if len(self.all_collected_sources) > self.max_sources_in_memory:
            # Keep only the most recent sources in memory
            self.all_collected_sources = self.all_collected_sources[-self.max_sources_in_memory:]

        # Update total count
        self.research_metadata["total_sources_collected"] += len(sources)

        # Sources are already stored in DB via record_data_collection
        # This method just manages the in-memory cache
        print(f"[DEBUG] Memory: {len(self.all_collected_sources)}/{self.max_sources_in_memory} sources, "
              f"Total: {self.research_metadata['total_sources_collected']}")

    async def _get_all_sources_sample(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Get sample of sources for analysis

        Returns recent sources from memory for efficiency
        """
        if len(self.all_collected_sources) >= limit:
            # Return recent sources from memory
            return self.all_collected_sources[-limit:]
        else:
            # Return all available sources in memory
            return self.all_collected_sources.copy()

    async def _perform_recursive_deep_dive(
        self,
        analysis_text: str,
        original_query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Perform recursive deep dive on analysis insights.

        Args:
            analysis_text: Analysis text to extract insights from
            original_query: Original research query
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Deep dive results dictionary
        """
        try:
            # Create LLM callable
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=2500),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["recursive_deep_dive"]
            )

            # Perform deep dive
            results = await self.deep_dive_analyzer.perform_deep_dive(
                analysis_text=analysis_text,
                original_query=original_query,
                search_function=self._single_tavily_search,
                llm_callable=llm.ainvoke,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            return results

        except Exception as e:
            print(f"[ERROR] Recursive deep dive failed: {e}")
            return {}

    async def _apply_semantic_clustering(
        self,
        sources: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply semantic clustering to sources.

        Args:
            sources: List of sources to cluster

        Returns:
            List of clusters
        """
        try:
            print(f"[INFO] 🔗 Clustering {len(sources)} sources semantically...")

            clusters = await self.semantic_clusterer.cluster_sources(sources)

            print(
                f"[INFO] ✅ Created {len(clusters)} clusters "
                f"(avg size: {self.semantic_clusterer.stats['avg_cluster_size']:.1f})"
            )

            # Identify gaps from clusters
            gaps = self.semantic_clusterer.identify_knowledge_gaps(clusters)
            if gaps:
                print(f"[INFO] 📋 Identified {len(gaps)} knowledge gaps from clustering")

            return clusters

        except Exception as e:
            print(f"[ERROR] Semantic clustering failed: {e}")
            return []

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
        print(f"[INFO] ⚠️ API Rate Limit Hits: {self.research_metadata['api_rate_limit_hits']}")
        print(f"[INFO] 💰 LLM Calls: {self.research_metadata['llm_calls']}")
        print(f"[INFO] 📊 Estimated Tokens: ~{self.research_metadata['estimated_total_tokens']:,}")

        # Print enhanced statistics
        quality_stats = self.quality_scorer.get_stats()
        print(f"[INFO] ⭐ High Quality Sources: {quality_stats.get('high_quality_percentage', 0):.1f}%")

        retry_stats = self.retry_handler.get_stats()
        print(f"[INFO] 🔁 Success Rate: {retry_stats.get('success_rate', 0):.1f}%")

        deep_dive_stats = self.deep_dive_analyzer.get_stats()
        if deep_dive_stats["insights_explored"] > 0:
            print(f"[INFO] 🔬 Deep Dive Insights: {deep_dive_stats['insights_explored']}")

        # Cost optimizer statistics
        cost_stats = self.cost_optimizer.get_stats()
        print(f"[INFO] 💰 Cache Hit Rate: {cost_stats.get('cache_hit_rate', 0):.1f}%")
        print(f"[INFO] 💵 Cost Saved: ${cost_stats.get('total_cost_saved', 0):.2f}")
        print(f"[INFO] 📊 Budget Usage: {cost_stats.get('budget_usage_pct', 0):.1f}%")

        # Fact checker statistics
        fact_stats = self.fact_checker.get_stats()
        if fact_stats.get("total_claims", 0) > 0:
            print(f"[INFO] ✅ Claims Verified: {fact_stats.get('total_claims', 0)}")
            print(f"[INFO] ⚠️ Contradictions Found: {fact_stats.get('contradictions_found', 0)}")

        # Bias detector statistics
        bias_stats = self.bias_detector.get_stats()
        if bias_stats.get("sources_analyzed", 0) > 0:
            diversity_score = bias_stats.get("perspective_diversity_score", 0)
            print(f"[INFO] 👁️ Perspective Diversity: {diversity_score:.1f}/100")
            print(f"[INFO] 🎯 Biases Detected: {bias_stats.get('biases_detected', 0)}")
