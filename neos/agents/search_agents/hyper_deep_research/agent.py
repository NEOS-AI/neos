"""HyperDeepResearch Agent.

This module contains the main business logic for the HyperDeepResearch agent,
using modular components for better maintainability and testability.

Design Patterns Used:
- Repository Pattern: Database operations
- Strategy Pattern: Language-specific prompt selection
- Builder Pattern: Report construction
- Facade Pattern: Simplified interface to complex subsystems
"""

from typing import Dict, Any, List
import uuid
from datetime import datetime
from tavily import TavilyClient
import logging

# Lazy import to avoid circular dependency
# from neos.agents.search_agents import IterativeWebExplorerAgent
from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.skills.manager import skill_manager

from ...base import SearchAgent
from ...planning_agent import PlanningAgent
from ..multi_query_search import MultiQuerySearchAgent
from ..multi_hop_search import MultiHopSearchAgent
from ..iterative_web_explorer import IterativeWebExplorerAgent
from ..criticism_feedback_agent import CriticismFeedbackAgent
from ...skill_based_tool_selector import SkillBasedToolSelector

from .config import ResearchConfig
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
    QuestionTypeClassifier,
    QuestionType,
)

# Import modular components
from .data_collection import DataCollector, ComplexSearchExecutor
from .hybrid_data_collector import HybridDataCollector
from .analysis import (
    TopicAnalyzer,
    ResearchPlanner,
    DeepAnalyzer,
    GapAnalyzer,
    ValidationAnalyzer,
    DataSummarizer,
)
from .skills_integration import SkillsIntegrator
from .report_generator import ReportGenerator, CriticismProcessor, QueryGenerator


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
    - Modular design with specialized components
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
        self.research_config = ResearchConfig()
        self.config = self.research_config.to_dict()

        # Initialize Tavily client
        self._init_tavily_client()

        # Initialize sub-agents
        self.planning_agent = PlanningAgent()
        self.multi_query_agent = MultiQuerySearchAgent()
        self.criticism_agent = CriticismFeedbackAgent()
        self.skill_tool_selector = SkillBasedToolSelector()

        # Initialize repository
        self.repository = HyperResearchRepository()

        # Initialize enhanced utilities
        self.token_counter = TokenCounter()
        self.quality_scorer = SourceQualityScorer()
        self.retry_handler = RetryHandler(max_attempts=4, base_delay=2.0)
        self.complexity_assessor = ComplexityAssessor()
        self.deep_dive_analyzer = DeepDiveAnalyzer(max_depth=2, min_importance_score=8.0)
        self.semantic_clusterer = SemanticClusterer(similarity_threshold=0.75)
        self.cost_optimizer = CostOptimizer(budget_limit=100.0, cache_ttl=3600)
        self.fact_checker = FactChecker()
        self.bias_detector = BiasDetector()

        # Initialize modular components
        self._init_modular_components()

        # Research state
        self.current_report_id = None
        self.sections_data = []
        self.all_collected_sources = []
        self.max_sources_in_memory = settings.DEEP_RESEARCH_MAX_SOURCES_IN_MEMORY

        # Initialize metadata
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
            "llm_calls": 0,
            "estimated_total_tokens": 0,
            "llm_calls_by_phase": {},
            "selected_skills": [],
            "selected_tools": [],
            "selection_reasoning": "",
        }

        # Event logger (initialized per research session)
        self.event_logger = None

        # Skills integration
        print("[DEBUG] Initializing Skills...")
        self.skill_manager = skill_manager
        self.skills_enabled = False

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

    def _init_modular_components(self) -> None:
        """Initialize modular components for research."""
        # Data collection
        self.data_collector = DataCollector(
            tavily_client=self.tavily_client,
            config=self.config,
            retry_handler=self.retry_handler,
            quality_scorer=self.quality_scorer,
        )

        self.complex_search_executor = ComplexSearchExecutor(
            multi_query_agent=self.multi_query_agent,
            repository=self.repository,
        )

        # Initialize sub-agents for hybrid collection
        try:
            self.multi_hop_agent = MultiHopSearchAgent()
            logger.info("MultiHopSearchAgent initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize MultiHopSearchAgent: {e}")
            self.multi_hop_agent = None

        try:
            self.iterative_explorer_agent = IterativeWebExplorerAgent()
            logger.info("IterativeWebExplorerAgent initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize IterativeWebExplorerAgent: {e}")
            self.iterative_explorer_agent = None

        # Hybrid data collector with intelligent strategy selection
        self.hybrid_data_collector = HybridDataCollector(
            tavily_client=self.tavily_client,
            config=self.config,
            multi_hop_agent=self.multi_hop_agent,
            iterative_explorer_agent=self.iterative_explorer_agent,
            data_collector=self.data_collector,
        )

        # Analysis components
        self.topic_analyzer = TopicAnalyzer(agent_name=self.name)
        self.research_planner = ResearchPlanner(agent_name=self.name)
        self.deep_analyzer = DeepAnalyzer(agent_name=self.name, config=self.config)
        self.gap_analyzer = GapAnalyzer(agent_name=self.name)
        self.validation_analyzer = ValidationAnalyzer(agent_name=self.name)
        self.data_summarizer = DataSummarizer(agent_name=self.name)

        # Skills integration
        self.skills_integrator = SkillsIntegrator(skill_manager=skill_manager)

        # Report generation
        self.report_generator = ReportGenerator(
            agent_name=self.name,
            repository=self.repository,
        )
        self.criticism_processor = CriticismProcessor(
            criticism_agent=self.criticism_agent,
            repository=self.repository,
            data_collector=self.data_collector,
        )
        
        self.query_generator = QueryGenerator(agent_name=self.name)


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
            report_id: Optional existing report ID to use

        Returns:
            Complete research report as markdown string
        """
        print("[INFO] ========== HyperDeepResearch Process Started ==========")
        print(f"[INFO] 🚀 Target: {self.config['target_total_sources']} sources minimum")

        # Initialize report
        await self._initialize_report(report_id, user_id, session_id, query)

        # Phase 0: Skill and Tool Selection
        await self._execute_phase_0(query, session_id, user_id, language)

        # Phase 1: Topic Analysis
        topic_analysis = await self._execute_phase_1(query, session_id, user_id, language)

        # Assess complexity and update config
        await self._assess_complexity(topic_analysis)

        # Phase 1.5 & 1.6: Domain Detection & Skill Initialization
        await self._ensure_and_initialize_skills(topic_analysis)

        # Phase 2: Research Planning
        methodology = await self._execute_phase_2(topic_analysis, session_id, user_id, language)

        # Phase 3: Initial Data Collection
        initial_data = await self._execute_phase_3(
            topic_analysis, methodology, session_id, user_id, language
        )

        # Phase 4: Deep Analysis
        deep_analysis = await self._execute_phase_4(
            topic_analysis, initial_data, session_id, user_id, language, query
        )

        # Phase 4.5: Recursive Deep Dive
        await self._execute_phase_4_5(deep_analysis, query, session_id, user_id, language)

        # Phase 5: Gap Analysis
        await self._execute_phase_5(
            topic_analysis, deep_analysis, session_id, user_id, language
        )

        # Phase 6: Cross-Validation
        validation = await self._execute_phase_6(
            query, topic_analysis, session_id, user_id, language
        )

        # Phase 6.5: Fact Verification
        await self._execute_phase_6_5(session_id, user_id, language)

        # Phase 7: Critical Analysis
        critical_analysis = await self._execute_phase_7(
            topic_analysis, deep_analysis, validation, session_id, user_id, language
        )

        # Phase 7.5: Bias Detection
        await self._execute_phase_7_5(session_id, user_id, language)

        # Phase 8: Final Report Synthesis
        final_report = await self._execute_phase_8(
            topic_analysis, methodology, deep_analysis,
            validation, critical_analysis, session_id, user_id, language
        )

        # Finalize report
        await self._finalize_report()

        self._print_research_summary()

        return final_report

    # ========== Phase Execution Methods ==========

    async def _initialize_report(
        self,
        report_id: str,
        user_id: str,
        session_id: str,
        query: str,
    ) -> None:
        """Initialize report and event logger."""
        self.current_report_id = report_id if report_id else f"hyper_report_{uuid.uuid4()}"

        await self.repository.ensure_tables_exist()

        if not report_id:
            await self.repository.create_report(
                self.current_report_id, user_id, session_id, query
            )

        # Initialize event logger
        enable_cli = session_id.startswith("cli_") if session_id else False
        self.event_logger = ResearchEventLogger(
            report_id=self.current_report_id,
            enable_cli_output=enable_cli
        )


    async def _execute_phase_0(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> None:
        """Phase 0: Skill and Tool Selection."""
        print("\n[INFO] ===== Phase 0: Skill and Tool Selection =====")
        await self.event_logger.log_phase_start(0, "Skill and Tool Selection")
        phase_start = datetime.now()

        try:
            selection_context = {
                "intent": "hyper_deep_research",
                "query_type": "research",
                "complexity": "high",
                "requires_analysis": True,
                "requires_data_sources": True
            }
            selection = await self.skill_tool_selector.select_skills_and_tools(
                query=query,
                context=selection_context,
                session_id=session_id,
                user_id=user_id,
                detected_language=language
            )
            
            self.research_metadata["selected_skills"] = selection.selected_skills
            self.research_metadata["selected_tools"] = selection.selected_tools
            self.research_metadata["selection_reasoning"] = selection.reasoning

            print(f"[INFO] ✅ Selected {len(selection.selected_skills)} skills: {selection.selected_skills}")
            print(f"[INFO] ✅ Selected {len(selection.selected_tools)} tools: {selection.selected_tools}")

        except Exception as e:
            print(f"[WARNING] Skill/tool selection failed: {e}")
            print("[INFO] Continuing with default configuration...")

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(0, "Skill and Tool Selection", duration)


    async def _execute_phase_1(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 1: Topic Analysis."""
        print("\n[INFO] ===== Phase 1/8: Topic Analysis =====")
        await self.event_logger.log_phase_start(1, "Topic Analysis")
        await self.repository.update_report_status(
            self.current_report_id, "in_progress", "started_at"
        )
        phase_start = datetime.now()

        topic_analysis = await self.topic_analyzer.analyze_topic(
            query, session_id, user_id, language,
            event_logger=self.event_logger,
            llm_tracker=self._track_llm_call,
        )

        await self.repository.create_section(
            self.current_report_id, "topic_analysis", 1,
            "Multi-Dimensional Topic Analysis",
            topic_analysis["full_analysis"], "completed"
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(1, "Topic Analysis", duration)

        return topic_analysis


    async def _assess_complexity(self, topic_analysis: Dict[str, Any]) -> None:
        """Assess topic complexity and update config."""
        print("\n[INFO] 🎯 Assessing topic complexity...")
        complexity_assessment = await self.complexity_assessor.assess_complexity(
            topic_analysis
        )
        print(
            f"[INFO] Complexity: {complexity_assessment['complexity_level']} "
            f"(score: {complexity_assessment['complexity_score']}, "
            f"iterations: {complexity_assessment['recommended_iterations']})"
        )
        self.config["analysis_iterations"] = complexity_assessment["recommended_iterations"]
        self.deep_analyzer.config = self.config


    async def _ensure_and_initialize_skills(
        self,
        topic_analysis: Dict[str, Any],
    ) -> None:
        """Phase 1.5 & 1.6: Domain Detection and Skill Initialization."""
        print("\n[INFO] ===== Domain Detection & Required Skills =====")
        
        selected_skills = self.research_metadata.get("selected_skills", [])
        updated_skills = self.skills_integrator.ensure_required_skills(
            topic_analysis, selected_skills
        )
        self.research_metadata["selected_skills"] = updated_skills
        
        print(f"[INFO] ✅ Final selected skills: {updated_skills}")

        print("\n[INFO] ===== Initializing Selected Skills =====")
        self.skills_enabled = await self.skills_integrator.initialize_skills(updated_skills)


    async def _execute_phase_2(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 2: Research Planning."""
        print("\n[INFO] ===== Phase 2/8: Research Planning =====")
        await self.event_logger.log_phase_start(2, "Research Planning")
        phase_start = datetime.now()

        methodology = await self.research_planner.plan_research(
            topic_analysis, session_id, user_id, language,
            llm_tracker=self._track_llm_call,
        )

        await self.repository.create_section(
            self.current_report_id, "methodology", 2,
            "Research Methodology & Framework",
            methodology["full_plan"], "completed"
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(2, "Research Planning", duration)

        return methodology

    async def _execute_phase_3(
        self,
        topic_analysis: Dict[str, Any],
        methodology: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 3: Initial Data Collection."""
        print("\n[INFO] ===== Phase 3/8: Data Collection =====")
        await self.event_logger.log_phase_start(3, "Data Collection")
        phase_start = datetime.now()

        # Generate query variations
        await self.event_logger.log_status_message(
            f"Generating {self.config['multi_query_expansion']} query variations...",
            "info"
        )
        query_variations = await self.data_collector.generate_query_variations(
            topic_analysis, session_id, user_id, language, self.name
        )
        await self.event_logger.log_status_message(
            f"Generated {len(query_variations)} queries for search",
            "success"
        )

        # ★ NEW: Classify queries and use hybrid collection for relational queries
        hybrid_results = []
        relational_queries = []
        standard_queries = []

        if self.config.get("enable_hybrid_collection", True):
            await self.event_logger.log_status_message(
                "Classifying queries for optimal search strategy...",
                "info"
            )

            # Classify all queries
            classifier = QuestionTypeClassifier()
            for query in query_variations[:10]:  # Limit to first 10 for hybrid (cost control)
                classification = classifier.classify(query)

                if classification.question_type == QuestionType.RELATIONAL:
                    relational_queries.append(query)
                else:
                    standard_queries.append(query)

            # Add remaining queries to standard
            if len(query_variations) > 10:
                standard_queries.extend(query_variations[10:])

            # Execute hybrid collection for relational queries
            if relational_queries:
                await self.event_logger.log_status_message(
                    f"Executing hybrid search for {len(relational_queries)} relational queries...",
                    "info"
                )

                collection_results = await self.hybrid_data_collector.collect_batch(
                    relational_queries,
                    context={
                        "user_id": user_id,
                        "session_id": session_id,
                        "language": language,
                    },
                    max_concurrent=2,  # Conservative parallelism
                )

                # Extract sources from hybrid results
                for result in collection_results:
                    if result.sources:
                        hybrid_results.extend(result.sources)

                        # Store hop-level citations if available
                        if result.hop_citations:
                            self.research_metadata.setdefault("hop_citations", []).extend(
                                result.hop_citations
                            )

                print(f"[INFO] ✅ Hybrid collection: {len(hybrid_results)} sources from "
                      f"{len(relational_queries)} relational queries")

                # Track strategy usage
                self.research_metadata["hybrid_collection_stats"] = (
                    self.hybrid_data_collector.get_statistics()
                )
        else:
            standard_queries = query_variations

        # Execute complex searches (on standard queries)
        await self.event_logger.log_status_message(
            "Executing complex multi-query searches...",
            "info"
        )
        complex_results = await self.complex_search_executor.execute_complex_searches(
            standard_queries, topic_analysis, session_id, user_id, language,
            event_logger=self.event_logger,
            report_id=self.current_report_id,
        )
        self.research_metadata["multi_query_searches"] = (
            self.complex_search_executor.stats["complex_searches"]
        )

        # Execute parallel batch searches (on standard queries)
        await self.event_logger.log_status_message(
            f"Executing parallel search batches ({self.config['parallel_search_batches']} batches)...",
            "info"
        )
        all_results = await self.data_collector.execute_parallel_searches(
            standard_queries,
            event_logger=self.event_logger,
            repository=self.repository,
            report_id=self.current_report_id,
        )
        self.research_metadata["total_queries_executed"] = (
            self.data_collector.stats["total_queries"]
        )

        # Add hybrid results
        if hybrid_results:
            all_results.extend(hybrid_results)

        # Add complex search results
        if complex_results:
            all_results.append(complex_results)

        # Collect data from skills
        if self.skills_enabled:
            await self.event_logger.log_status_message(
                f"Collecting data from {len(self.research_metadata['selected_skills'])} selected skills...",
                "info"
            )
            skill_results = await self.skills_integrator.collect_data_from_skills(
                query_variations, topic_analysis, language
            )
            if skill_results:
                all_results.extend(skill_results)
                print(f"[INFO] ✅ Added {len(skill_results)} skill-based sources")

        # Deduplicate and score sources
        unique_sources = DataProcessor.deduplicate_sources(all_results)

        print(f"[INFO] 📊 Scoring {len(unique_sources)} sources for quality...")
        scored_sources = self.quality_scorer.rank_sources(unique_sources)
        print(f"[INFO] ✅ Quality scoring complete. High quality: {self.quality_scorer.stats['high_quality_count']}")

        # Store sources
        await self._store_sources_batch(scored_sources)

        # Track domains
        self.research_metadata["unique_domains"].update(
            DataProcessor.extract_unique_domains(unique_sources)
        )

        # Summarize
        summary = await self.data_summarizer.summarize_collected_data(
            unique_sources, session_id, user_id, language
        )

        await self.repository.create_section(
            self.current_report_id, "initial_collection", 3,
            "Initial Data Collection", summary, "completed",
            sources_count=len(unique_sources)
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(3, "Data Collection", duration)

        # Phase 3.5: Iterative Web Exploration (if initial results insufficient)
        await self._execute_phase_3_5_iterative_exploration(
            topic_analysis, unique_sources, session_id, user_id, language
        )

        return {
            "summary": summary,
            "sources_count": len(unique_sources),
            "queries_executed": len(query_variations),
        }

    async def _execute_phase_3_5_iterative_exploration(
        self,
        topic_analysis: Dict[str, Any],
        initial_sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
    ) -> None:
        """Phase 3.5: Iterative Web Exploration (optional enhancement)

        초기 데이터 수집 결과가 불충분한 경우 iterative exploration 실행

        Args:
            topic_analysis: 주제 분석 결과
            initial_sources: 초기 수집된 소스들
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 감지된 언어
        """
        try:
            # Iterative explorer 초기화 (lazy import)
            from neos.agents.search_agents import IterativeWebExplorerAgent

            iterative_explorer = IterativeWebExplorerAgent()

            # 목표 소스 수 확인
            target_sources = self.config.get("target_total_sources", 100)
            current_sources = self.research_metadata["total_sources_collected"]

            # 초기 수집 결과가 목표의 50% 미만이면 iterative exploration 실행
            if current_sources < target_sources * 0.5:
                print("\n[INFO] ===== Phase 3.5: Iterative Web Exploration =====")
                print(f"[INFO] Initial sources ({current_sources}) below target ({target_sources})")
                print("[INFO] Initiating iterative web exploration for deeper coverage...")

                await self.event_logger.log_status_message(
                    f"Initial sources insufficient ({current_sources}/{target_sources}). "
                    "Starting iterative exploration...",
                    "info"
                )

                # Conservative settings for HyperDeepResearch
                # (더 보수적인 설정: depth=3, pages=15, threshold=0.70)
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "detected_language": language,
                    "max_depth": 3,  # Conservative depth
                    "max_pages": 15,  # Conservative page limit
                    "quality_threshold": 0.70,  # Lower threshold (easier to meet)
                }

                # 주제에서 핵심 쿼리 추출
                main_query = topic_analysis.get("main_topic", "")
                if not main_query:
                    # Fallback to sub-topics
                    sub_topics = topic_analysis.get("sub_topics", [])
                    if sub_topics:
                        main_query = sub_topics[0]

                if main_query:
                    # Iterative exploration 실행
                    result = await iterative_explorer.execute(main_query, context)

                    if result.get("success"):
                        iterative_sources = result.get("result", [])
                        metadata = result.get("metadata", {})

                        print(f"[INFO] ✅ Iterative exploration completed: {len(iterative_sources)} additional sources")
                        print(f"[INFO] Depth reached: {metadata.get('depth_reached', 0)}, "
                              f"Pages visited: {metadata.get('pages_visited', 0)}, "
                              f"Quality: {metadata.get('final_quality_score', 0):.2f}")

                        # 소스 변환 (SearchResult -> Dict)
                        converted_sources = []
                        for source in iterative_sources:
                            if hasattr(source, '__dict__'):
                                # SearchResult 객체를 dict로 변환
                                source_dict = {
                                    "title": getattr(source, 'title', ''),
                                    "url": getattr(source, 'url', ''),
                                    "content": getattr(source, 'content', ''),
                                    "score": getattr(source, 'score', 0.5),
                                    "source": getattr(source, 'source', 'iterative_exploration'),
                                    "metadata": getattr(source, 'metadata', {}),
                                }
                                converted_sources.append(source_dict)
                            else:
                                converted_sources.append(source)

                        # 소스 저장
                        await self._store_sources_batch(converted_sources)

                        # 도메인 다양성 추적
                        self.research_metadata["unique_domains"].update(
                            DataProcessor.extract_unique_domains(converted_sources)
                        )

                        await self.event_logger.log_status_message(
                            f"Iterative exploration added {len(converted_sources)} sources",
                            "success"
                        )

                        # Repository에 섹션 기록
                        await self.repository.create_section(
                            self.current_report_id,
                            "iterative_exploration",
                            3.5,
                            "Iterative Web Exploration",
                            f"Explored {metadata.get('pages_visited', 0)} pages across "
                            f"{metadata.get('depth_reached', 0)} depth levels, "
                            f"achieving quality score of {metadata.get('final_quality_score', 0):.2f}",
                            "completed",
                            sources_count=len(converted_sources)
                        )
                    else:
                        error_msg = result.get("error", "Unknown error")
                        print(f"[WARNING] Iterative exploration failed: {error_msg}")
                else:
                    print("[WARNING] No query available for iterative exploration")

            else:
                print(f"[INFO] Initial sources ({current_sources}) sufficient. Skipping iterative exploration.")

        except ImportError:
            print("[WARNING] IterativeWebExplorerAgent not available")
        except Exception as e:
            print(f"[WARNING] Iterative exploration failed: {e}")
            # Don't fail the entire process, just continue without iterative exploration

    async def _execute_phase_4(
        self,
        topic_analysis: Dict[str, Any],
        initial_data: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        query: str,
    ) -> Dict[str, Any]:
        """Phase 4: Iterative Deep Analysis."""
        print("\n[INFO] ===== Phase 4/8: Deep Analysis =====")
        await self.event_logger.log_phase_start(4, "Deep Analysis")
        phase_start = datetime.now()

        deep_analysis = await self.deep_analyzer.perform_deep_analysis(
            topic_analysis, initial_data, session_id, user_id, language,
            metadata_tracker=self.research_metadata,
        )

        await self.repository.create_section(
            self.current_report_id, "deep_analysis", 4,
            "Iterative Deep Analysis", deep_analysis["synthesis"], "completed"
        )

        # Process criticism feedback
        await self.criticism_processor.process_criticism_feedback(
            "deep_analysis", "Iterative Deep Analysis",
            deep_analysis["synthesis"], query, topic_analysis,
            session_id, user_id, language,
            self.current_report_id,
            self.research_metadata["total_sources_collected"],
        )
        self.research_metadata["criticism_feedbacks_generated"] = (
            self.criticism_processor.stats["feedbacks_generated"]
        )
        self.research_metadata["additional_research_triggered"] = (
            self.criticism_processor.stats["additional_research_triggered"]
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(4, "Deep Analysis", duration)

        return deep_analysis


    async def _execute_phase_4_5(
        self,
        deep_analysis: Dict[str, Any],
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> None:
        """Phase 4.5: Recursive Deep Dive."""
        print("\n[INFO] ===== Phase 4.5/8: Recursive Deep Dive =====")

        try:
            from neos.utils.llm_factory import create_llm
            from neos.utils.llm_wrapper import create_tracked_llm

            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["recursive_deep_dive"]
            )

            deep_dive_results = await self.deep_dive_analyzer.perform_deep_dive(
                analysis_text=deep_analysis["synthesis"],
                original_query=query,
                search_function=self.data_collector.single_search,
                llm_callable=llm.ainvoke,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            if deep_dive_results and deep_dive_results.get("explorations"):
                deep_dive_synthesis = self.deep_dive_analyzer.synthesize_deep_dives(
                    deep_dive_results
                )
                await self.repository.create_section(
                    self.current_report_id, "recursive_deep_dive", 4.5,
                    "Recursive Deep Dive Explorations", deep_dive_synthesis, "completed"
                )
                print(
                    f"[INFO] 🔬 Deep dive complete: "
                    f"{deep_dive_results.get('insights_explored', 0)} insights explored"
                )

        except Exception as e:
            print(f"[ERROR] Recursive deep dive failed: {e}")


    async def _execute_phase_5(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 5: Gap Analysis."""
        print("\n[INFO] ===== Phase 5/8: Gap Analysis =====")
        await self.event_logger.log_phase_start(5, "Gap Analysis")
        phase_start = datetime.now()

        # Identify gaps
        gaps = await self.gap_analyzer.identify_knowledge_gaps(
            topic_analysis, deep_analysis, session_id, user_id, language
        )
        print(f"[INFO] 📋 Identified {len(gaps)} knowledge gaps")

        # Execute complex searches for top gaps
        complex_gap_results = await self.complex_search_executor.execute_complex_searches(
            gaps[:3], topic_analysis, session_id, user_id, language,
            event_logger=self.event_logger,
            report_id=self.current_report_id,
        )

        # Investigate gaps
        gap_results = []
        for idx, gap in enumerate(gaps[:10], 1):
            print(f"[INFO] 🎯 Gap {idx}/{min(len(gaps), 10)}")
            gap_queries = await self.query_generator.generate_gap_queries(
                gap, session_id, user_id, language
            )

            # ★ NEW: Use hybrid collection for gap queries if enabled
            if self.config.get("enable_hybrid_collection", True) and len(gap_queries) > 0:
                # Classify first query to determine strategy
                classifier = QuestionTypeClassifier()
                classification = classifier.classify(gap_queries[0])

                if classification.question_type == QuestionType.RELATIONAL:
                    # Use hybrid collection for relational gap queries
                    collection_result = await self.hybrid_data_collector.collect(
                        gap_queries[0],
                        context={
                            "user_id": user_id,
                            "session_id": session_id,
                            "language": language,
                        },
                    )
                    if collection_result.sources:
                        gap_results.extend(collection_result.sources)
                        print(f"[INFO] ✅ Gap filled with {len(collection_result.sources)} sources "
                              f"using {collection_result.strategy_used} strategy")
                else:
                    # Use standard search for non-relational gaps
                    results = await self.data_collector._search_batch_parallel(gap_queries)
                    gap_results.extend(results)
            else:
                # Fallback to standard search
                results = await self.data_collector._search_batch_parallel(gap_queries)
                gap_results.extend(results)

            for query in gap_queries:
                await self.repository.record_data_collection(
                    self.current_report_id, query, "gap_filling", 5, {}
                )
                self.research_metadata["total_queries_executed"] += 1

        if complex_gap_results:
            gap_results.append(complex_gap_results)

        # Process gap sources
        unique_gap_sources = DataProcessor.deduplicate_sources(gap_results)
        await self._store_sources_batch(unique_gap_sources)

        # Summarize
        summary = await self.gap_analyzer.summarize_gap_investigation(
            gaps, unique_gap_sources, session_id, user_id, language
        )

        await self.repository.create_section(
            self.current_report_id, "gap_analysis", 5,
            "Gap Analysis & Additional Research", summary, "completed",
            sources_count=len(unique_gap_sources)
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(5, "Gap Analysis", duration)

        return {"gaps": gaps, "summary": summary, "sources_count": len(unique_gap_sources)}


    async def _execute_phase_6(
        self,
        query: str,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 6: Cross-Validation."""
        print("\n[INFO] ===== Phase 6/8: Cross-Validation =====")
        await self.event_logger.log_phase_start(6, "Cross-Validation")
        phase_start = datetime.now()

        # Apply semantic clustering
        print(f"[INFO] 🔗 Clustering {len(self.all_collected_sources)} sources semantically...")
        clusters = await self.semantic_clusterer.cluster_sources(self.all_collected_sources)
        print(
            f"[INFO] ✅ Created {len(clusters)} clusters "
            f"(avg size: {self.semantic_clusterer.stats['avg_cluster_size']:.1f})"
        )

        # Cross-validate
        validation = await self.validation_analyzer.cross_validate_sources(
            self.all_collected_sources, session_id, user_id, language, clusters
        )

        await self.repository.create_section(
            self.current_report_id, "validation", 6,
            "Cross-Validation & Triangulation", validation["report"], "completed"
        )

        # Process criticism feedback
        await self.criticism_processor.process_criticism_feedback(
            "validation", "Cross-Validation & Triangulation",
            validation["report"], query, topic_analysis,
            session_id, user_id, language,
            self.current_report_id,
            self.research_metadata["total_sources_collected"],
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(6, "Cross-Validation", duration)

        return validation


    async def _execute_phase_6_5(
        self,
        session_id: str,
        user_id: str,
        language: str,
    ) -> None:
        """Phase 6.5: Fact Verification."""
        print("\n[INFO] ===== Phase 6.5/8: Fact Verification & Claim Analysis =====")

        try:
            from neos.utils.llm_factory import create_llm
            from neos.utils.llm_wrapper import create_tracked_llm

            print(f"[INFO] Verifying facts across {len(self.all_collected_sources)} sources...")

            llm = create_tracked_llm(
                llm=create_llm(temperature=0.1, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["fact_verification"]
            )

            verification_results = await self.fact_checker.verify_sources(
                sources=self.all_collected_sources,
                llm_callable=llm.ainvoke,
                language=language
            )

            stats = verification_results.get("stats", {})
            print(f"[INFO] ✓ Extracted {stats.get('total_claims', 0)} claims")
            print(f"[INFO] ✓ Found {stats.get('contradictions_found', 0)} contradictions")

            await self.repository.create_section(
                self.current_report_id, "fact_verification", 6.5,
                "Fact Verification & Contradiction Analysis",
                verification_results.get("report", "Fact verification pending"),
                "completed"
            )

        except Exception as e:
            print(f"[ERROR] Fact verification failed: {e}")

    async def _execute_phase_7(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Phase 7: Critical Analysis."""
        print("\n[INFO] ===== Phase 7/8: Critical Analysis =====")
        await self.event_logger.log_phase_start(7, "Critical Analysis")
        phase_start = datetime.now()

        critical_analysis = await self.validation_analyzer.perform_critical_analysis(
            topic_analysis, deep_analysis, validation,
            session_id, user_id, language,
            metadata_tracker=self.research_metadata,
        )

        await self.repository.create_section(
            self.current_report_id, "critical_analysis", 7,
            "Critical Analysis & Perspectives",
            critical_analysis["full_analysis"], "completed"
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(7, "Critical Analysis", duration)

        return critical_analysis

    async def _execute_phase_7_5(
        self,
        session_id: str,
        user_id: str,
        language: str,
    ) -> None:
        """Phase 7.5: Bias Detection & Perspective Diversity."""
        print("\n[INFO] ===== Phase 7.5/8: Bias & Perspective Analysis =====")

        try:
            from neos.utils.llm_factory import create_llm
            from neos.utils.llm_wrapper import create_tracked_llm

            print(f"[INFO] Analyzing bias across {len(self.all_collected_sources)} sources...")

            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["bias_detection"]
            )

            bias_results = await self.bias_detector.analyze_bias(
                sources=self.all_collected_sources,
                llm_callable=llm.ainvoke,
                language=language
            )

            diversity_score = bias_results.get("diversity_score", 0)
            stats = bias_results.get("stats", {})
            print(f"[INFO] ✓ Diversity Score: {diversity_score:.1f}/100")
            print(f"[INFO] ✓ Biases Detected: {stats.get('biases_detected', 0)}")

            await self.repository.create_section(
                self.current_report_id, "bias_analysis", 7.5,
                "Bias Detection & Perspective Diversity",
                bias_results.get("report", "Bias analysis pending"),
                "completed"
            )

        except Exception as e:
            print(f"[ERROR] Bias analysis failed: {e}")

    async def _execute_phase_8(
        self,
        topic_analysis: Dict[str, Any],
        methodology: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        critical_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Phase 8: Final Report Synthesis."""
        print("\n[INFO] ===== Phase 8/8: Report Synthesis =====")
        await self.event_logger.log_phase_start(8, "Report Synthesis")
        phase_start = datetime.now()

        final_report = await self.report_generator.synthesize_final_report(
            topic_analysis, methodology, deep_analysis,
            validation, critical_analysis,
            session_id, user_id, language,
            self.current_report_id,
            self.research_metadata,
        )

        duration = int((datetime.now() - phase_start).total_seconds() * 1000)
        await self.event_logger.log_phase_complete(8, "Report Synthesis", duration)

        return final_report

    async def _finalize_report(self) -> None:
        """Finalize report in database."""
        await self.repository.update_report_status(
            self.current_report_id, "completed", "completed_at", quality_score=0.95
        )
        await self._update_report_metadata()


    # ========== Helper Methods ==========

    def _track_llm_call(self, phase: str, prompt: str, response: str) -> None:
        """Track LLM API call for cost monitoring."""
        usage = self.token_counter.track_usage(
            prompt, response, metadata={"phase": phase, "model": "gpt-4"}
        )

        prompt_tokens = usage["prompt_tokens"]
        response_tokens = usage["completion_tokens"]
        total_tokens = usage["total_tokens"]
        estimated_cost = usage["estimated_cost"]

        self.research_metadata["llm_calls"] += 1
        self.research_metadata["estimated_total_tokens"] += total_tokens

        if phase not in self.research_metadata["llm_calls_by_phase"]:
            self.research_metadata["llm_calls_by_phase"][phase] = {
                "calls": 0, "tokens": 0, "cost": 0.0
            }

        self.research_metadata["llm_calls_by_phase"][phase]["calls"] += 1
        self.research_metadata["llm_calls_by_phase"][phase]["tokens"] += total_tokens
        self.research_metadata["llm_calls_by_phase"][phase]["cost"] = (
            self.research_metadata["llm_calls_by_phase"][phase].get("cost", 0.0) + estimated_cost
        )

        # Cache response
        self.cost_optimizer.cache_response(
            prompt=prompt,
            response=response,
            cost=estimated_cost,
            metadata={"phase": phase, "tokens": total_tokens}
        )

        within_budget = self.cost_optimizer.track_cost(estimated_cost, phase)
        if not within_budget:
            print(
                f"[WARNING] ⚠️ Budget exceeded! Phase: {phase}, "
                f"Total: ${self.cost_optimizer.total_cost:.2f}"
            )

        print(
            f"[DEBUG] LLM call tracked - Phase: {phase}, "
            f"Tokens: {total_tokens} (prompt={prompt_tokens}, response={response_tokens}), "
            f"Cost: ${estimated_cost:.4f}"
        )

    async def _store_sources_batch(self, sources: List[Dict[str, Any]]) -> None:
        """Store sources with memory optimization."""
        if not sources:
            return

        self.all_collected_sources.extend(sources)
        if len(self.all_collected_sources) > self.max_sources_in_memory:
            self.all_collected_sources = self.all_collected_sources[-self.max_sources_in_memory:]

        self.research_metadata["total_sources_collected"] += len(sources)

        print(
            f"[DEBUG] Memory: {len(self.all_collected_sources)}/{self.max_sources_in_memory} sources, "
            f"Total: {self.research_metadata['total_sources_collected']}"
        )

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
                "llm_calls": self.research_metadata["llm_calls"],
                "estimated_total_tokens": self.research_metadata["estimated_total_tokens"],
                "llm_calls_by_phase": self.research_metadata["llm_calls_by_phase"]
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

        cost_stats = self.cost_optimizer.get_stats()
        print(f"[INFO] 💰 Cache Hit Rate: {cost_stats.get('cache_hit_rate', 0):.1f}%")
        print(f"[INFO] 💵 Cost Saved: ${cost_stats.get('total_cost_saved', 0):.2f}")
        print(f"[INFO] 📊 Budget Usage: {cost_stats.get('budget_usage_pct', 0):.1f}%")

        fact_stats = self.fact_checker.get_stats()
        if fact_stats.get("total_claims", 0) > 0:
            print(f"[INFO] ✅ Claims Verified: {fact_stats.get('total_claims', 0)}")
            print(f"[INFO] ⚠️ Contradictions Found: {fact_stats.get('contradictions_found', 0)}")

        bias_stats = self.bias_detector.get_stats()
        if bias_stats.get("sources_analyzed", 0) > 0:
            diversity_score = bias_stats.get("perspective_diversity_score", 0)
            print(f"[INFO] 👁️ Perspective Diversity: {diversity_score:.1f}/100")
            print(f"[INFO] 🎯 Biases Detected: {bias_stats.get('biases_detected', 0)}")
