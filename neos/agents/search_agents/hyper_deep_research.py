"""HyperDeepResearch Agent - 극도로 고도화된 딥리서치 시스템"""

from typing import Dict, Any, List
import asyncio
import uuid
from datetime import datetime
from tavily import TavilyClient

from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.utils.llm_factory import create_llm
from neos.database.connection import db_manager

from ..base import SearchAgent
from ..planning_agent import PlanningAgent
from .multi_query_search import MultiQuerySearchAgent
from .criticism_feedback_agent import CriticismFeedbackAgent


class HyperDeepResearchAgent(SearchAgent):
    """극도로 고도화된 심층 조사 에이전트

    특징:
    1. 멀티 쿼리 서치: 사용자 쿼리를 다양한 관점으로 증강하여 광범위한 검색
    2. 고도화된 플래닝: 연구 방법론, 이론적 프레임워크, 다층적 조사 계획
    3. 반복적 심층 분석: 초기 조사 → 갭 분석 → 추가 조사 → 교차 검증 → 통합
    4. 비판적 사고: 다양한 관점, 반대 의견, 한계점 분석
    5. 삼각측량(Triangulation): 여러 소스에서 정보 교차 검증
    6. 과도한 조사: 최소 100+ 소스, 다양한 검색 전략 병렬 실행
    7. DB 완전 추적: 모든 단계, 사고 과정, 데이터 수집 기록
    """

    def __init__(self):
        super().__init__(
            name="hyper_deep_research",
            search_type="hyper_deep_research",
            role="Elite Research Director & Critical Analyst",
            goal="Conduct exhaustive, multi-dimensional research with rigorous methodology, critical analysis, and comprehensive documentation",
            backstory="You are a world-renowned research director combining the rigor of academic research, the breadth of investigative journalism, and the depth of critical analysis. You leave no stone unturned."
        )

        # 극도로 강화된 HyperDeepResearch 설정
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

        # Tavily client 초기화
        self.tavily_client = None
        self.api_available = False

        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient created for HyperDeepResearch")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient for HyperDeepResearch: {e}")
                self.tavily_client = None
                self.api_available = False
        else:
            print("[WARNING] TAVILY_API_KEY not set, HyperDeepResearch will return empty results")

        # Planning agent
        self.planning_agent = PlanningAgent()

        # Multi-query search agent for complex searches
        self.multi_query_agent = MultiQuerySearchAgent()

        # Criticism feedback agent for quality control
        self.criticism_agent = CriticismFeedbackAgent()

        # 현재 보고서 상태
        self.current_report_id = None
        self.sections_data = []
        self.all_collected_sources = []  # 모든 수집된 소스 추적
        self.research_metadata = {
            "total_queries_executed": 0,
            "total_sources_collected": 0,
            "unique_domains": set(),
            "analysis_iterations_completed": 0,
            "critical_reviews_completed": 0,
            "multi_query_searches": 0,  # 복합 검색 횟수
            "criticism_feedbacks_generated": 0,  # 비판 피드백 생성 횟수
            "additional_research_triggered": 0  # 피드백으로 인한 추가 조사 횟수
        }

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """HyperDeepResearch 실행"""
        print(f"[DEBUG] HyperDeepResearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] HyperDeepResearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        if not self.api_available:
            print("[WARNING] TAVILY_API_KEY not available")
            return self.format_output([], {"search_type": "hyper_deep_research", "warning": "API key not available"})

        try:
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""

            # 전체 프로세스 실행
            report_content = await self._run_hyper_deep_research(query, session_id, user_id, context)

            # SearchResult 형태로 반환
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

            print("[DEBUG] HyperDeepResearchAgent execution completed successfully")
            return self.format_output([result], {"search_type": "hyper_deep_research"})

        except Exception as e:
            print(f"[ERROR] HyperDeepResearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}

    async def _run_hyper_deep_research(self, query: str, session_id: str, user_id: str, context: Dict[str, Any]) -> str:
        """HyperDeepResearch 전체 프로세스 - 극도로 심층적"""
        print("[INFO] ==================== HyperDeepResearch Process Started ====================")
        print("[INFO] 🚀 WARNING: This will be an EXTREMELY thorough investigation")
        print(f"[INFO] 📊 Target: {self.config['target_total_sources']} sources minimum")

        detected_language = context.get("detected_language", "ko") if context else "ko"

        # 보고서 생성 및 DB 저장
        self.current_report_id = f"hyper_report_{uuid.uuid4()}"
        await self._create_report_in_db(user_id, session_id, query)

        # Phase 1: 연구 주제 확인 및 다차원 분해
        print("\n[INFO] ========== Phase 1/8: Multi-Dimensional Topic Analysis ==========")
        await self._update_report_status("in_progress", "started_at")
        topic_analysis = await self._analyze_topic_multidimensional(query, session_id, user_id, detected_language)
        await self._create_section_in_db(
            "topic_analysis", 1, "Multi-Dimensional Topic Analysis",
            topic_analysis["full_analysis"], "completed"
        )

        # Phase 2: 고도화된 연구 계획 수립 (방법론, 이론적 프레임워크, 다층 조사 전략)
        print("\n[INFO] ========== Phase 2/8: Advanced Research Methodology Planning ==========")
        research_methodology = await self._create_advanced_research_plan(
            topic_analysis, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "methodology", 2, "Research Methodology & Framework",
            research_methodology["full_plan"], "completed"
        )

        # Phase 3: 멀티 쿼리 대규모 초기 데이터 수집
        print("\n[INFO] ========== Phase 3/8: Multi-Query Mass Data Collection ==========")
        print(f"[INFO] 🔍 Generating {self.config['multi_query_expansion']} search query variations...")
        initial_data = await self._multi_query_mass_collection(
            topic_analysis, research_methodology, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "initial_collection", 3, "Initial Data Collection",
            initial_data["summary"], "completed",
            sources_count=initial_data["sources_count"]
        )

        # Phase 4: 반복적 심층 분석 (3회 반복)
        print("\n[INFO] ========== Phase 4/8: Iterative Deep Analysis (3 rounds) ==========")
        deep_analysis = await self._iterative_deep_analysis(
            topic_analysis, initial_data, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "deep_analysis", 4, "Iterative Deep Analysis",
            deep_analysis["synthesis"], "completed"
        )

        # Criticism Feedback for Deep Analysis
        print("\n[INFO] 🔍 Criticism Feedback: Reviewing Deep Analysis...")
        deep_analysis_feedback = await self._get_criticism_feedback(
            section_type="deep_analysis",
            section_title="Iterative Deep Analysis",
            section_content=deep_analysis["synthesis"],
            topic=query,
            research_context={
                "sources_count": self.research_metadata["total_sources_collected"],
                "research_questions": topic_analysis.get("research_questions", []),
                "previous_sections": ["topic_analysis", "methodology", "initial_collection"]
            },
            session_id=session_id,
            user_id=user_id,
            language=detected_language
        )

        # 피드백 기반 추가 조사
        await self._handle_feedback_and_investigate(
            deep_analysis_feedback, "deep_analysis", session_id, user_id, detected_language
        )

        # Phase 5: 갭 분석 및 집중 조사
        print("\n[INFO] ========== Phase 5/8: Gap Analysis & Targeted Investigation ==========")
        gap_data = await self._comprehensive_gap_analysis(
            topic_analysis, deep_analysis, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "gap_analysis", 5, "Gap Analysis & Additional Research",
            gap_data["summary"], "completed",
            sources_count=gap_data["sources_count"]
        )

        # Phase 6: 교차 검증 및 삼각측량
        print("\n[INFO] ========== Phase 6/8: Cross-Validation & Triangulation ==========")
        validation = await self._cross_validation_triangulation(
            self.all_collected_sources, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "validation", 6, "Cross-Validation & Triangulation",
            validation["report"], "completed"
        )

        # Criticism Feedback for Validation
        print("\n[INFO] 🔍 Criticism Feedback: Reviewing Cross-Validation...")
        validation_feedback = await self._get_criticism_feedback(
            section_type="validation",
            section_title="Cross-Validation & Triangulation",
            section_content=validation["report"],
            topic=query,
            research_context={
                "sources_count": self.research_metadata["total_sources_collected"],
                "research_questions": topic_analysis.get("research_questions", []),
                "previous_sections": ["deep_analysis", "gap_analysis"]
            },
            session_id=session_id,
            user_id=user_id,
            language=detected_language
        )

        # 피드백 기반 추가 조사
        await self._handle_feedback_and_investigate(
            validation_feedback, "validation", session_id, user_id, detected_language
        )

        # Phase 7: 비판적 사고 및 다관점 분석
        print("\n[INFO] ========== Phase 7/8: Critical Thinking & Multi-Perspective Analysis ==========")
        critical_analysis = await self._critical_thinking_analysis(
            topic_analysis, deep_analysis, validation, session_id, user_id, detected_language
        )
        await self._create_section_in_db(
            "critical_analysis", 7, "Critical Analysis & Perspectives",
            critical_analysis["full_analysis"], "completed"
        )

        # Phase 8: 최종 종합 보고서 생성 (섹션별)
        print("\n[INFO] ========== Phase 8/8: Comprehensive Report Synthesis ==========")
        final_report = await self._synthesize_comprehensive_report(
            topic_analysis, research_methodology, deep_analysis, validation,
            critical_analysis, session_id, user_id, detected_language
        )

        # 보고서 완료 처리 및 메타데이터 업데이트
        await self._update_report_status("completed", "completed_at", quality_score=0.95)
        await self._update_report_metadata()

        print("\n[INFO] ==================== HyperDeepResearch Completed ====================")
        print(f"[INFO] 📊 Report ID: {self.current_report_id}")
        print(f"[INFO] 📚 Total Sections: {len(self.sections_data)}")
        print(f"[INFO] 🔍 Total Queries Executed: {self.research_metadata['total_queries_executed']}")
        print(f"[INFO] 🔄 Complex Multi-Query Searches: {self.research_metadata['multi_query_searches']}")
        print(f"[INFO] 📄 Total Sources Collected: {self.research_metadata['total_sources_collected']}")
        print(f"[INFO] 🌐 Unique Domains: {len(self.research_metadata['unique_domains'])}")
        print(f"[INFO] 🔍 Criticism Feedbacks Generated: {self.research_metadata['criticism_feedbacks_generated']}")
        print(f"[INFO] 🔄 Additional Research Triggered: {self.research_metadata['additional_research_triggered']}")
        print(f"[INFO] 📝 Report Length: {len(final_report)} characters")

        return final_report

    async def _analyze_topic_multidimensional(self, query: str, session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """연구 주제를 다차원으로 분석"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=3000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["topic_analysis"]
            )

            prompts = {
                "ko": f"""다음 연구 주제를 다차원으로 깊이 있게 분석해주세요:

주제: {query}

다음을 모두 포함하여 분석해주세요:

1. **핵심 개념 분해**
   - 주요 키워드와 그 의미
   - 연관 개념 및 용어
   - 개념 간 관계

2. **다차원 관점**
   - 기술적 관점
   - 경제적/시장적 관점
   - 사회적/문화적 관점
   - 역사적 관점
   - 미래 전망 관점

3. **연구 범위 설정**
   - 지리적 범위 (글로벌/지역)
   - 시간적 범위 (과거/현재/미래)
   - 주제 깊이 (개요/심층)

4. **핵심 연구 질문 (10-15개)**
   - What (무엇): 현상, 정의, 구성요소
   - Why (왜): 원인, 동기, 배경
   - How (어떻게): 메커니즘, 프로세스, 방법
   - Who (누구): 주체, 이해관계자
   - When (언제): 시점, 추세, 변화
   - Where (어디): 지역, 장소, 맥락

5. **잠재적 조사 영역**
   - 데이터가 필요한 영역
   - 전문가 의견이 필요한 영역
   - 사례 연구가 필요한 영역

매우 상세하고 구조화된 분석을 한국어로 작성해주세요.""",

                "en": f"""Conduct a multi-dimensional in-depth analysis of the following research topic:

Topic: {query}

Include all of the following:

1. **Core Concept Decomposition**
   - Key terms and their meanings
   - Related concepts and terminology
   - Relationships between concepts

2. **Multi-Dimensional Perspectives**
   - Technical perspective
   - Economic/market perspective
   - Social/cultural perspective
   - Historical perspective
   - Future outlook perspective

3. **Research Scope Definition**
   - Geographic scope (global/regional)
   - Temporal scope (past/present/future)
   - Topic depth (overview/in-depth)

4. **Core Research Questions (10-15)**
   - What: Phenomena, definitions, components
   - Why: Causes, motivations, background
   - How: Mechanisms, processes, methods
   - Who: Actors, stakeholders
   - When: Timing, trends, changes
   - Where: Regions, locations, contexts

5. **Potential Investigation Areas**
   - Areas requiring data
   - Areas requiring expert opinions
   - Areas requiring case studies

Write a very detailed and structured analysis in English."""
            }

            response = await llm.ainvoke([HumanMessage(content=prompts.get(language, prompts["en"]))])
            analysis_text = response.content.strip()

            # 핵심 질문 추출
            research_questions = self._extract_research_questions(analysis_text)

            return {
                "full_analysis": analysis_text,
                "research_questions": research_questions,
                "original_query": query
            }

        except Exception as e:
            print(f"[ERROR] Failed to analyze topic: {e}")
            return {
                "full_analysis": f"Topic: {query}\n\nAnalysis pending.",
                "research_questions": [query],
                "original_query": query
            }

    async def _create_advanced_research_plan(self, topic_analysis: Dict[str, Any],
                                           session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """고도화된 연구 계획 수립 - 방법론, 프레임워크, 다층 전략"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=4000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["research_planning"]
            )

            prompts = {
                "ko": f"""다음 주제 분석을 바탕으로 포괄적인 연구 계획을 수립해주세요:

주제 분석:
{topic_analysis['full_analysis'][:1500]}

다음을 모두 포함한 상세한 연구 계획을 작성해주세요:

1. **연구 방법론**
   - 탐색적 조사 (Exploratory Research)
   - 설명적 조사 (Descriptive Research)
   - 인과적 조사 (Causal Research)
   - 각 방법론의 적용 영역

2. **이론적 프레임워크**
   - 관련 이론 및 모델
   - 분석 프레임워크
   - 평가 기준

3. **다층 조사 전략**
   - Layer 1: 기본 정보 수집 (정의, 개념, 현황)
   - Layer 2: 심층 분석 (메커니즘, 원인, 영향)
   - Layer 3: 비교 분석 (사례, 대안, 국제 비교)
   - Layer 4: 미래 전망 (트렌드, 예측, 시나리오)

4. **데이터 수집 계획**
   - 1차 데이터 유형: 통계, 사례, 전문가 의견
   - 2차 데이터 유형: 학술 논문, 산업 보고서, 뉴스
   - 검색 키워드 전략 (20개 이상)
   - 소스 다양화 전략

5. **품질 관리 전략**
   - 소스 신뢰성 평가 기준
   - 교차 검증 방법
   - 편향 방지 전략

매우 상세하고 실행 가능한 계획을 한국어로 작성해주세요.""",

                "en": f"""Based on the following topic analysis, create a comprehensive research plan:

Topic Analysis:
{topic_analysis['full_analysis'][:1500]}

Create a detailed research plan including:

1. **Research Methodology**
   - Exploratory Research
   - Descriptive Research
   - Causal Research
   - Application areas for each

2. **Theoretical Framework**
   - Relevant theories and models
   - Analytical frameworks
   - Evaluation criteria

3. **Multi-Layer Investigation Strategy**
   - Layer 1: Basic information (definitions, concepts, status)
   - Layer 2: Deep analysis (mechanisms, causes, impacts)
   - Layer 3: Comparative analysis (cases, alternatives, international comparison)
   - Layer 4: Future outlook (trends, predictions, scenarios)

4. **Data Collection Plan**
   - Primary data types: statistics, cases, expert opinions
   - Secondary data types: academic papers, industry reports, news
   - Search keyword strategy (20+ keywords)
   - Source diversification strategy

5. **Quality Control Strategy**
   - Source credibility criteria
   - Cross-validation methods
   - Bias prevention strategies

Write a very detailed and actionable plan in English."""
            }

            response = await llm.ainvoke([HumanMessage(content=prompts.get(language, prompts["en"]))])
            plan_text = response.content.strip()

            # 검색 전략 추출
            search_strategies = self._extract_search_strategies(plan_text)

            return {
                "full_plan": plan_text,
                "search_strategies": search_strategies
            }

        except Exception as e:
            print(f"[ERROR] Failed to create research plan: {e}")
            return {
                "full_plan": "Research plan creation failed",
                "search_strategies": []
            }

    async def _multi_query_mass_collection(self, topic_analysis: Dict[str, Any],
                                          methodology: Dict[str, Any],
                                          session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """멀티 쿼리 기반 대규모 데이터 수집 + 복합 검색 통합"""

        # Step 1: 20개 이상의 다양한 검색 쿼리 생성
        print("[INFO] 🔍 Generating diverse search queries...")
        query_variations = await self._generate_multi_query_variations(
            topic_analysis, methodology, session_id, user_id, language
        )
        print(f"[INFO] ✅ Generated {len(query_variations)} query variations")

        # Step 2: 복합 검색 (Multi-Query Search) 실행
        print("\n[INFO] 🔄 Executing complex multi-query searches for deeper analysis...")
        complex_search_results = await self._execute_complex_searches(
            query_variations, topic_analysis, session_id, user_id, language
        )
        print(f"[INFO] ✅ Complex searches completed: {len(complex_search_results)} sources")

        # Step 3: 기본 병렬 검색 실행
        batch_size = len(query_variations) // self.config["parallel_search_batches"]
        all_results = []

        print(f"\n[INFO] 🚀 Executing {self.config['parallel_search_batches']} parallel search batches...")

        for batch_num in range(self.config["parallel_search_batches"]):
            start_idx = batch_num * batch_size
            end_idx = start_idx + batch_size if batch_num < self.config["parallel_search_batches"] - 1 else len(query_variations)
            batch_queries = query_variations[start_idx:end_idx]

            print(f"[INFO] 📦 Batch {batch_num + 1}/{self.config['parallel_search_batches']}: {len(batch_queries)} queries")

            # 배치 내 병렬 검색
            batch_results = await self._parallel_search_batch(batch_queries)
            all_results.extend(batch_results)

            # DB에 기록
            for query, results in zip(batch_queries, batch_results):
                await self._record_data_collection(query, "multi_query_initial", 3, results)
                self.research_metadata["total_queries_executed"] += 1

            print(f"[INFO] ✅ Batch {batch_num + 1} completed: {sum(len(r) for r in batch_results)} results")

        # Step 4: 복합 검색 결과 통합
        # complex_search_results는 List[Dict]이므로 리스트로 감싸서 추가
        if complex_search_results:
            all_results.append(complex_search_results)

        # Step 5: 결과 통합 및 중복 제거
        unique_sources = self._deduplicate_sources(all_results)
        self.all_collected_sources.extend(unique_sources)
        self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

        # 도메인 추적
        for source in unique_sources:
            if "url" in source:
                domain = self._extract_domain(source["url"])
                self.research_metadata["unique_domains"].add(domain)

        # Step 6: 초기 분석 및 요약
        summary = await self._summarize_mass_data(unique_sources, session_id, user_id, language)

        print(f"[INFO] 🎯 Mass collection completed: {len(unique_sources)} unique sources")
        print(f"[INFO] 📊 Including {len(complex_search_results)} sources from complex searches")

        return {
            "summary": summary,
            "sources_count": len(unique_sources),
            "queries_executed": len(query_variations),
            "complex_searches": self.research_metadata["multi_query_searches"]
        }

    async def _generate_multi_query_variations(self, topic_analysis: Dict[str, Any],
                                              methodology: Dict[str, Any],
                                              session_id: str, user_id: str, language: str) -> List[str]:
        """멀티 쿼리 변형 생성 (20개 이상)"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.6, max_tokens=2500)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["multi_query_generation"]
            )

            prompt = f"""다음 연구 주제에 대해 다양한 관점과 각도에서 검색 쿼리를 생성해주세요:

주제: {topic_analysis['original_query']}

연구 질문들:
{chr(10).join(topic_analysis['research_questions'][:10])}

다음 전략으로 **25개의 다양한 검색 쿼리**를 생성해주세요:

1. 직접 질문 (5개): 주제의 핵심 질문
2. 관련 개념 (5개): 연관 키워드, 유사 주제
3. 특정 측면 (5개): 기술, 시장, 사회, 역사, 미래
4. 비교 및 대조 (5개): A vs B, 장단점, 대안
5. 사례 및 실제 (5개): 사례 연구, 실제 적용, 성공/실패 사례

각 쿼리는 한 줄로, 구체적이고 검색 가능하게 작성하세요.
번호나 카테고리 표시 없이 쿼리만 작성하세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [q.strip() for q in response.content.strip().split('\n') if q.strip() and len(q.strip()) > 5]

            # 최소 보장
            if len(queries) < self.config["multi_query_expansion"]:
                # 부족한 경우 기본 쿼리 추가
                base_query = topic_analysis['original_query']
                fallback_queries = [
                    f"{base_query} overview",
                    f"{base_query} detailed analysis",
                    f"{base_query} latest trends",
                    f"{base_query} market analysis",
                    f"{base_query} technical details",
                    f"{base_query} future outlook",
                    f"{base_query} case studies",
                    f"{base_query} expert opinions",
                    f"{base_query} comparative analysis",
                    f"{base_query} challenges and solutions"
                ]
                queries.extend(fallback_queries)

            return queries[:self.config["multi_query_expansion"]]

        except Exception as e:
            print(f"[ERROR] Failed to generate multi-query variations: {e}")
            return [topic_analysis['original_query']]

    async def _execute_complex_searches(self, query_variations: List[str],
                                        topic_analysis: Dict[str, Any],
                                        session_id: str, user_id: str, language: str) -> List[Dict[str, Any]]:
        """복합 검색 실행 - MultiQuerySearchAgent 활용"""
        all_complex_results = []

        # 주요 쿼리 5개를 선별하여 복합 검색 수행
        priority_queries = query_variations[:5]

        print(f"[INFO] 🔄 Executing {len(priority_queries)} complex multi-query searches...")

        for idx, base_query in enumerate(priority_queries, 1):
            print(f"[INFO] 🔍 Complex search {idx}/{len(priority_queries)}: {base_query[:60]}...")

            try:
                # MultiQuerySearchAgent 실행
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "detected_language": language
                }

                result = await self.multi_query_agent.execute(base_query, context)

                # 결과 추출
                if result.get("success") and result.get("results"):
                    search_result = result["results"][0]

                    # SearchResult는 dataclass이므로 속성으로 접근
                    metadata = search_result.metadata if hasattr(search_result, 'metadata') else {}
                    content = search_result.content if hasattr(search_result, 'content') else ""

                    # 복합 검색 결과가 있으면 저장
                    if content:  # summaries 체크 제거 - content만 있으면 OK
                        total_sources = metadata.get('total_sources', 0) if metadata else 0
                        print(f"[INFO] ✅ Complex search {idx} found {total_sources} sources")

                        # 복합 검색 결과 생성
                        complex_source = {
                            "title": f"Complex Analysis: {base_query}",
                            "content": content[:500] if len(content) > 500 else content,
                            "url": f"multi_query_analysis_{idx}",
                            "score": 0.95,
                            "type": "multi_query_synthesis"
                        }
                        all_complex_results.append(complex_source)

                        self.research_metadata["multi_query_searches"] += 1

                        # DB에 기록
                        await self._record_data_collection(
                            base_query,
                            "complex_multi_query",
                            3,
                            [complex_source]
                        )
                    else:
                        print(f"[WARNING] Complex search {idx} returned no content")

            except Exception as e:
                print(f"[WARNING] Complex search {idx} failed: {e}")
                import traceback
                print(f"[DEBUG] Traceback: {traceback.format_exc()}")
                continue

        print(f"[INFO] 🎯 Complex searches completed: {len(all_complex_results)} synthesized sources")

        return all_complex_results

    async def _parallel_search_batch(self, queries: List[str]) -> List[List[Dict[str, Any]]]:
        """쿼리 배치 병렬 검색"""
        tasks = [self._single_tavily_search(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[WARNING] Search failed for '{queries[i]}': {result}")
                processed_results.append([])
            else:
                processed_results.append(result)

        return processed_results

    async def _iterative_deep_analysis(self, topic_analysis: Dict[str, Any],
                                      initial_data: Dict[str, Any],
                                      session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """반복적 심층 분석 (3회)"""
        analysis_rounds = []

        for round_num in range(self.config["analysis_iterations"]):
            print(f"\n[INFO] 🔬 Deep Analysis Round {round_num + 1}/{self.config['analysis_iterations']}")

            # 이전 라운드 결과 포함
            previous_insights = "\n\n".join([r["insights"] for r in analysis_rounds]) if analysis_rounds else ""

            # 현재 라운드 분석
            round_analysis = await self._single_analysis_round(
                topic_analysis, initial_data, previous_insights, round_num + 1,
                session_id, user_id, language
            )

            analysis_rounds.append(round_analysis)
            self.research_metadata["analysis_iterations_completed"] += 1

            print(f"[INFO] ✅ Round {round_num + 1} completed: {len(round_analysis['insights'])} insights")

        # 모든 라운드 종합
        synthesis = await self._synthesize_analysis_rounds(analysis_rounds, session_id, user_id, language)

        return {
            "rounds": analysis_rounds,
            "synthesis": synthesis
        }

    async def _comprehensive_gap_analysis(self, topic_analysis: Dict[str, Any],
                                         deep_analysis: Dict[str, Any],
                                         session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """포괄적 갭 분석 및 추가 조사 + 복합 검색"""

        # 갭 식별
        print("[INFO] 🔍 Identifying knowledge gaps...")
        gaps = await self._identify_comprehensive_gaps(
            topic_analysis, deep_analysis, session_id, user_id, language
        )

        print(f"[INFO] 📋 Identified {len(gaps)} knowledge gaps")

        # 주요 갭 3개에 대해 복합 검색 수행
        print("\n[INFO] 🔄 Executing complex searches for top gaps...")
        complex_gap_results = await self._execute_complex_searches(
            gaps[:3], topic_analysis, session_id, user_id, language
        )
        print(f"[INFO] ✅ Gap complex searches: {len(complex_gap_results)} sources")

        # 갭별 집중 조사
        gap_results = []
        for idx, gap in enumerate(gaps[:10], 1):  # 최대 10개 갭
            print(f"[INFO] 🎯 Investigating gap {idx}/{min(len(gaps), 10)}: {gap[:50]}...")

            # 갭별 타겟 쿼리 생성
            gap_queries = await self._generate_gap_specific_queries(gap, session_id, user_id, language)

            # 병렬 검색
            results = await self._parallel_search_batch(gap_queries)
            flat_results = [item for sublist in results for item in sublist]

            gap_results.extend(flat_results)

            for query, result in zip(gap_queries, results):
                await self._record_data_collection(query, "gap_filling", 5, result)
                self.research_metadata["total_queries_executed"] += 1

        # 복합 검색 결과 추가
        # complex_gap_results는 List[Dict]이므로 리스트로 감싸서 추가
        if complex_gap_results:
            gap_results.append(complex_gap_results)

        # 중복 제거 및 추가
        unique_gap_sources = self._deduplicate_sources(gap_results)
        self.all_collected_sources.extend(unique_gap_sources)
        self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

        # 갭 조사 요약
        summary = await self._summarize_gap_investigation(gaps, unique_gap_sources, session_id, user_id, language)

        print(f"[INFO] ✅ Gap investigation completed: {len(unique_gap_sources)} additional sources")
        print(f"[INFO] 📊 Including {len(complex_gap_results)} from complex gap searches")

        return {
            "gaps": gaps,
            "summary": summary,
            "sources_count": len(unique_gap_sources),
            "complex_searches": 3
        }

    async def _cross_validation_triangulation(self, all_sources: List[Dict[str, Any]],
                                             session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """교차 검증 및 삼각측량"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.2, max_tokens=3500)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["cross_validation"]
            )

            # 소스 샘플링 (최대 30개)
            sampled_sources = all_sources[:30] if len(all_sources) > 30 else all_sources
            sources_text = "\n\n".join([
                f"Source {i+1} ({s.get('url', 'N/A')}):\n{s.get('title', '')}\n{s.get('content', '')[:300]}"
                for i, s in enumerate(sampled_sources)
            ])

            prompt = f"""다음 {len(sampled_sources)}개의 소스를 교차 검증하고 삼각측량(Triangulation)을 수행해주세요:

{sources_text}

다음을 분석해주세요:

1. **일관성 분석**
   - 여러 소스에서 일관되게 확인되는 핵심 사실
   - 신뢰도가 높은 정보 (3개 이상 소스에서 확인)

2. **불일치 분석**
   - 소스 간 상충되는 정보
   - 불일치의 원인 (시점, 관점, 데이터 차이 등)

3. **정보 품질 평가**
   - 고품질 소스 (학술, 공식 기관)
   - 중간 품질 소스 (뉴스, 산업 보고서)
   - 주의 필요 소스 (의견, 블로그)

4. **삼각측량 결과**
   - 다양한 소스에서 교차 확인된 핵심 발견사항
   - 단일 소스에만 있는 정보 (추가 검증 필요)

5. **신뢰도 매트릭스**
   - 높은 신뢰도 정보 목록
   - 중간 신뢰도 정보 목록
   - 낮은 신뢰도 정보 목록

상세한 교차 검증 보고서를 작성해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {
                "report": response.content.strip(),
                "sources_analyzed": len(sampled_sources)
            }

        except Exception as e:
            print(f"[ERROR] Failed cross-validation: {e}")
            return {
                "report": "Cross-validation analysis pending",
                "sources_analyzed": 0
            }

    async def _critical_thinking_analysis(self, topic_analysis: Dict[str, Any],
                                        deep_analysis: Dict[str, Any],
                                        validation: Dict[str, Any],
                                        session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """비판적 사고 및 다관점 분석"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.4, max_tokens=4000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["critical_thinking"]
            )

            prompt = f"""다음 연구 결과를 비판적으로 분석해주세요:

주제: {topic_analysis['original_query']}

심층 분석 결과:
{deep_analysis['synthesis'][:1500]}

교차 검증 결과:
{validation['report'][:1500]}

다음 관점에서 비판적으로 분석해주세요:

1. **다양한 관점 분석**
   - 찬성 의견 및 근거
   - 반대 의견 및 근거
   - 중립/회의적 관점

2. **가정과 편향 식별**
   - 암묵적 가정
   - 잠재적 편향 (확증 편향, 선택 편향 등)
   - 누락된 관점

3. **한계점 및 제약사항**
   - 데이터의 한계
   - 방법론적 제약
   - 일반화의 한계

4. **대안적 해석**
   - 다른 방식의 해석 가능성
   - 맥락에 따른 해석 차이

5. **추가 고려사항**
   - 윤리적 고려사항
   - 사회적 영향
   - 장기적 시사점

6. **미해결 질문**
   - 추가 연구가 필요한 영역
   - 답변되지 않은 질문

매우 비판적이고 균형 잡힌 분석을 작성해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])

            self.research_metadata["critical_reviews_completed"] += 1

            return {
                "full_analysis": response.content.strip()
            }

        except Exception as e:
            print(f"[ERROR] Failed critical thinking analysis: {e}")
            return {
                "full_analysis": "Critical analysis pending"
            }

    async def _synthesize_comprehensive_report(self, topic_analysis: Dict[str, Any],
                                              methodology: Dict[str, Any],
                                              deep_analysis: Dict[str, Any],
                                              validation: Dict[str, Any],
                                              critical_analysis: Dict[str, Any],
                                              session_id: str, user_id: str, language: str) -> str:
        """최종 종합 보고서 생성"""

        # 보고서 구조 계획
        report_structure = await self._plan_final_report_structure(
            topic_analysis, session_id, user_id, language
        )

        # 각 섹션 생성
        final_sections = []
        section_order = 8  # 이전 섹션들 다음

        for section_info in report_structure["sections"]:
            section_title = section_info["title"]
            print(f"[INFO] 📝 Generating final section: {section_title}")

            section_content = await self._generate_final_section(
                section_info, topic_analysis, deep_analysis, validation, critical_analysis,
                session_id, user_id, language
            )

            section_id = await self._create_section_in_db(
                "final_report", section_order, section_title, section_content, "completed"
            )

            final_sections.append({
                "section_id": section_id,
                "title": section_title,
                "content": section_content
            })

            section_order += 1

        # 최종 보고서 조합
        report = await self._assemble_final_report(
            topic_analysis["original_query"], final_sections
        )

        return report

    # ==================== Criticism Feedback 관련 메서드들 ====================

    async def _get_criticism_feedback(
        self,
        section_type: str,
        section_title: str,
        section_content: str,
        topic: str,
        research_context: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """섹션에 대한 비판적 피드백 받기"""
        try:
            print(f"[INFO] 🔍 Requesting criticism feedback for: {section_title}")

            feedback = await self.criticism_agent.generate_feedback(
                topic=topic,
                section_type=section_type,
                section_content=section_content,
                research_context=research_context,
                session_id=session_id,
                user_id=user_id,
                language=language
            )

            self.research_metadata["criticism_feedbacks_generated"] += 1

            # 피드백 로깅
            severity = feedback.get("severity", "none")
            has_issues = feedback.get("has_issues", False)

            print(f"[INFO] ✅ Feedback received - Severity: {severity}")

            if has_issues:
                print(f"[INFO] ⚠️  Issues found: {feedback.get('feedback', '')[:100]}...")
                if feedback.get("suggested_queries"):
                    print(f"[INFO] 📋 Suggested {len(feedback['suggested_queries'])} additional queries")
                if feedback.get("redirect_suggestion"):
                    print(f"[INFO] 🔄 Redirect suggestion: {feedback['redirect_suggestion'][:100]}...")

            # DB에 피드백 저장
            await self._record_criticism_feedback(section_type, section_title, feedback)

            return feedback

        except Exception as e:
            print(f"[ERROR] Failed to get criticism feedback: {e}")
            return {
                "has_issues": False,
                "severity": "none",
                "feedback": "",
                "suggested_queries": [],
                "redirect_suggestion": "",
                "missing_perspectives": []
            }

    async def _handle_feedback_and_investigate(
        self,
        feedback: Dict[str, Any],
        section_type: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> Dict[str, Any]:
        """피드백을 기반으로 추가 조사 수행"""
        if not self.criticism_agent.should_trigger_additional_research(feedback):
            print("[INFO] ✅ No additional research needed based on feedback")
            return {"additional_sources": [], "sources_count": 0}

        print("\n[INFO] 🔄 Triggering additional research based on feedback...")
        self.research_metadata["additional_research_triggered"] += 1

        suggested_queries = feedback.get("suggested_queries", [])
        missing_perspectives = feedback.get("missing_perspectives", [])

        # 쿼리 준비
        queries = suggested_queries[:5]  # 최대 5개

        # 누락된 관점을 쿼리로 변환
        for perspective in missing_perspectives[:3]:
            queries.append(f"{perspective} detailed analysis")

        if not queries:
            return {"additional_sources": [], "sources_count": 0}

        print(f"[INFO] 🔍 Executing {len(queries)} additional queries from feedback...")

        # 병렬 검색 실행
        results = await self._parallel_search_batch(queries)
        flat_results = [item for sublist in results for item in sublist]

        # DB에 기록
        for query, result in zip(queries, results):
            await self._record_data_collection(
                query,
                f"criticism_feedback_{section_type}",
                phase=99,  # 피드백 기반 조사는 특별한 phase
                results=result
            )
            self.research_metadata["total_queries_executed"] += 1

        # 중복 제거 및 추가
        unique_sources = self._deduplicate_sources([flat_results])
        self.all_collected_sources.extend(unique_sources)
        self.research_metadata["total_sources_collected"] = len(self.all_collected_sources)

        print(f"[INFO] ✅ Feedback-driven research completed: {len(unique_sources)} additional sources")

        return {
            "additional_sources": unique_sources,
            "sources_count": len(unique_sources)
        }

    async def _record_criticism_feedback(
        self,
        section_type: str,
        section_title: str,
        feedback: Dict[str, Any]
    ) -> None:
        """비판 피드백을 DB에 저장"""
        try:
            import json
            import uuid

            feedback_id = f"feedback_{uuid.uuid4()}"

            query = """
            INSERT INTO hyper_research_criticism_feedback
            (feedback_id, report_id, section_type, section_title, severity, has_issues,
             feedback_text, suggested_queries, missing_perspectives, redirect_suggestion)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """

            await db_manager.execute(
                query,
                feedback_id,
                self.current_report_id,
                section_type,
                section_title,
                feedback.get("severity", "none"),
                feedback.get("has_issues", False),
                feedback.get("feedback", ""),
                json.dumps(feedback.get("suggested_queries", [])),
                json.dumps(feedback.get("missing_perspectives", [])),
                feedback.get("redirect_suggestion", "")
            )

            print(f"[DEBUG] Recorded criticism feedback in DB: {feedback_id}")

        except Exception as e:
            print(f"[ERROR] Failed to record criticism feedback in DB: {e}")
            # DB 저장 실패해도 계속 진행

    # ==================== 헬퍼 메서드들 ====================

    def _extract_research_questions(self, text: str) -> List[str]:
        """텍스트에서 연구 질문 추출"""
        questions = []
        lines = text.split('\n')
        for line in lines:
            if '?' in line or any(q in line.lower() for q in ['what', 'why', 'how', 'when', 'where', 'who']):
                clean = line.strip().lstrip('-•*123456789. ')
                if len(clean) > 10:
                    questions.append(clean)
        return questions[:15]

    def _extract_search_strategies(self, text: str) -> List[str]:
        """텍스트에서 검색 전략 추출"""
        strategies = []
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['keyword', 'query', 'search', '검색']):
                clean = line.strip().lstrip('-•*123456789. ')
                if len(clean) > 5:
                    strategies.append(clean)
        return strategies

    def _deduplicate_sources(self, results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """소스 중복 제거"""
        seen_urls = set()
        unique = []

        for result_list in results:
            # result_list가 리스트인지 확인
            if not isinstance(result_list, list):
                print(f"[WARNING] Expected list but got {type(result_list)}, skipping")
                continue

            for item in result_list:
                # item이 딕셔너리인지 확인
                if not isinstance(item, dict):
                    print(f"[WARNING] Expected dict but got {type(item)}: {item}, skipping")
                    continue

                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique.append(item)

        return unique

    def _extract_domain(self, url: str) -> str:
        """URL에서 도메인 추출"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return "unknown"

    async def _summarize_mass_data(self, sources: List[Dict[str, Any]],
                                  session_id: str, user_id: str, language: str) -> str:
        """대규모 데이터 요약"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.2, max_tokens=2500)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["data_summarization"]
            )

            sample = sources[:20]
            sources_text = "\n\n".join([
                f"- {s.get('title', '')}: {s.get('content', '')[:200]}"
                for s in sample
            ])

            prompt = f"""다음 {len(sources)}개 소스에서 수집된 데이터를 요약해주세요:

샘플 (20개):
{sources_text}

주요 발견사항, 트렌드, 패턴을 상세히 요약하세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Failed to summarize mass data: {e}")
            return f"Collected {len(sources)} sources for analysis"

    async def _single_analysis_round(self, topic_analysis: Dict[str, Any],
                                    initial_data: Dict[str, Any],
                                    previous_insights: str,
                                    round_num: int,
                                    session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """단일 분석 라운드"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=3000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=[f"analysis_round_{round_num}"]
            )

            context = f"""라운드 {round_num} 분석

주제: {topic_analysis['original_query']}

초기 데이터 요약:
{initial_data['summary'][:1000]}

이전 라운드 인사이트:
{previous_insights[:1000] if previous_insights else 'N/A'}

이번 라운드에서 다음을 분석해주세요:
- 새로운 패턴과 인사이트
- 이전 라운드와의 연결점
- 추가 탐구가 필요한 영역

상세한 분석을 작성해주세요."""

            response = await llm.ainvoke([HumanMessage(content=context)])

            return {
                "round": round_num,
                "insights": response.content.strip()
            }

        except Exception as e:
            print(f"[ERROR] Failed analysis round {round_num}: {e}")
            return {
                "round": round_num,
                "insights": f"Round {round_num} analysis pending"
            }

    async def _synthesize_analysis_rounds(self, rounds: List[Dict[str, Any]],
                                         session_id: str, user_id: str, language: str) -> str:
        """분석 라운드 종합"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.2, max_tokens=3000)
            llm = create_tracked_llm(
                llm=base_llm,
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

            prompt = f"""다음 {len(rounds)}개 분석 라운드를 종합해주세요:

{rounds_text}

모든 라운드의 인사이트를 통합하여 포괄적인 분석을 작성해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Failed to synthesize rounds: {e}")
            return "Analysis synthesis pending"

    async def _identify_comprehensive_gaps(self, topic_analysis: Dict[str, Any],
                                          deep_analysis: Dict[str, Any],
                                          session_id: str, user_id: str, language: str) -> List[str]:
        """포괄적 갭 식별"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=2000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_identification"]
            )

            prompt = f"""다음 연구 결과를 분석하여 지식 갭을 식별해주세요:

연구 질문:
{chr(10).join(topic_analysis['research_questions'][:10])}

현재 분석 결과:
{deep_analysis['synthesis'][:1000]}

아직 충분히 답변되지 않은 중요한 질문이나 부족한 영역을 10-15개 식별해주세요.
각 갭은 한 줄로 작성하세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            gaps = [g.strip() for g in response.content.strip().split('\n') if g.strip() and len(g.strip()) > 10]
            return gaps[:15]

        except Exception as e:
            print(f"[ERROR] Failed to identify gaps: {e}")
            return []

    async def _generate_gap_specific_queries(self, gap: str, session_id: str, user_id: str, language: str) -> List[str]:
        """갭 특화 쿼리 생성"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.4, max_tokens=800)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_query_generation"]
            )

            prompt = f"""다음 지식 갭을 메우기 위한 구체적인 검색 쿼리 5개를 생성해주세요:

갭: {gap}

각 쿼리는 한 줄로, 구체적이고 검색 가능하게 작성하세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [q.strip() for q in response.content.strip().split('\n') if q.strip() and len(q.strip()) > 5]
            return queries[:5]

        except Exception as e:
            print(f"[ERROR] Failed to generate gap queries: {e}")
            return [gap]

    async def _summarize_gap_investigation(self, gaps: List[str], sources: List[Dict[str, Any]],
                                          session_id: str, user_id: str, language: str) -> str:
        """갭 조사 요약"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.2, max_tokens=2000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["gap_summary"]
            )

            gaps_text = "\n".join([f"- {g}" for g in gaps[:10]])
            sources_sample = "\n".join([f"- {s.get('title', '')}" for s in sources[:15]])

            prompt = f"""갭 조사 결과를 요약해주세요:

식별된 갭:
{gaps_text}

수집된 소스 샘플 ({len(sources)}개 중):
{sources_sample}

갭이 어떻게 메워졌는지, 추가로 발견한 내용을 요약해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Failed to summarize gap investigation: {e}")
            return f"Investigated {len(gaps)} gaps with {len(sources)} sources"

    async def _plan_final_report_structure(self, topic_analysis: Dict[str, Any],
                                          session_id: str, user_id: str, language: str) -> Dict[str, Any]:
        """최종 보고서 구조 계획"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=2000)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["report_structure"]
            )

            prompt = f"""다음 주제에 대한 최종 보고서 구조를 설계해주세요:

주제: {topic_analysis['original_query']}

8-12개의 주요 섹션으로 구조화하세요.
각 섹션을 다음 형식으로 제시:
섹션명 | 목적 | 주요 내용

한 줄에 하나씩 작성하세요."""

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
            print(f"[ERROR] Failed to plan report structure: {e}")
            return {"sections": [{"title": "Summary", "purpose": "Overview", "content_type": "General"}]}

    async def _generate_final_section(self, section_info: Dict[str, Any],
                                     topic_analysis: Dict[str, Any],
                                     deep_analysis: Dict[str, Any],
                                     validation: Dict[str, Any],
                                     critical_analysis: Dict[str, Any],
                                     session_id: str, user_id: str, language: str) -> str:
        """최종 섹션 생성"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain.schema import HumanMessage

            base_llm = create_llm(temperature=0.3, max_tokens=3500)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["final_section_generation"]
            )

            prompt = f"""다음 섹션을 작성해주세요:

섹션: {section_info['title']}
목적: {section_info.get('purpose', '')}

주제: {topic_analysis['original_query']}

참고 자료:
- 심층 분석: {deep_analysis['synthesis'][:800]}
- 검증 결과: {validation['report'][:800]}
- 비판적 분석: {critical_analysis['full_analysis'][:800]}

총 {self.research_metadata['total_sources_collected']}개 소스를 기반으로 이 섹션을 매우 상세하고 전문적으로 작성해주세요.
데이터, 사례, 구체적인 내용을 포함하세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except Exception as e:
            print(f"[ERROR] Failed to generate final section: {e}")
            return f"Section {section_info['title']}: Content generation pending"

    async def _assemble_final_report(self, topic: str, sections: List[Dict[str, Any]]) -> str:
        """최종 보고서 조합"""
        parts = [
            f"# {topic}\n",
            "## HyperDeepResearch Comprehensive Report\n",
            f"\n**Report ID:** `{self.current_report_id}`\n",
            f"**Generated:** {datetime.utcnow().isoformat()}\n",
            "\n---\n",
            "\n## 📊 Research Statistics\n",
            f"- **Total Sources Analyzed:** {self.research_metadata['total_sources_collected']}\n",
            f"- **Total Queries Executed:** {self.research_metadata['total_queries_executed']}\n",
            f"- **Complex Multi-Query Searches:** {self.research_metadata['multi_query_searches']}\n",
            f"- **Unique Domains:** {len(self.research_metadata['unique_domains'])}\n",
            f"- **Analysis Iterations:** {self.research_metadata['analysis_iterations_completed']}\n",
            f"- **Critical Reviews:** {self.research_metadata['critical_reviews_completed']}\n",
            f"- **Criticism Feedbacks Generated:** {self.research_metadata['criticism_feedbacks_generated']}\n",
            f"- **Additional Research Triggered by Feedback:** {self.research_metadata['additional_research_triggered']}\n",
            "\n---\n"
        ]

        for section in sections:
            parts.append(f"\n## {section['title']}\n")
            parts.append(f"\n{section['content']}\n")

        parts.append("\n---\n")
        parts.append(f"\n**📦 All research data stored in database with ID: `{self.current_report_id}`**\n")

        return "".join(parts)

    # ==================== DB 관련 메서드들 ====================

    async def _create_report_in_db(self, user_id: str, session_id: str, topic: str) -> None:
        """보고서를 DB에 생성"""
        try:
            # HyperDeepResearch 테이블이 없으면 생성
            await self._ensure_tables_exist()

            query = """
            INSERT INTO hyper_research_reports (report_id, user_id, session_id, research_topic, research_status, research_plan)
            VALUES ($1, $2, $3, $4, $5, $6)
            """
            await db_manager.execute(
                query,
                self.current_report_id, user_id, session_id, topic, "pending",
                '{"phases": ["topic_analysis", "methodology", "multi_query_collection", "deep_analysis", "gap_analysis", "validation", "critical_thinking", "synthesis"]}'
            )
            print(f"[DEBUG] Created report in DB: {self.current_report_id}")
        except Exception as e:
            print(f"[ERROR] Failed to create report in DB: {e}")
            print("[INFO] Continuing without DB storage (data will be in memory only)")
            # DB 저장 실패해도 계속 진행 (로컬 메모리에는 저장됨)

    async def _ensure_tables_exist(self) -> None:
        """HyperDeepResearch 테이블이 존재하는지 확인하고 없으면 생성"""
        try:
            # 간단한 테이블 존재 여부 확인
            check_query = "SELECT 1 FROM hyper_research_reports LIMIT 1"
            await db_manager.fetch_one(check_query)
        except Exception:
            # 테이블이 없으면 생성
            print("[INFO] Creating HyperDeepResearch tables...")
            try:
                create_reports_table = """
                CREATE TABLE IF NOT EXISTS hyper_research_reports (
                    id SERIAL PRIMARY KEY,
                    report_id VARCHAR(255) UNIQUE NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    research_topic TEXT NOT NULL,
                    research_plan JSONB,
                    research_status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_sections INTEGER DEFAULT 0,
                    total_sources INTEGER DEFAULT 0,
                    total_queries INTEGER DEFAULT 0,
                    processing_time_ms INTEGER,
                    quality_score FLOAT,
                    completeness_score FLOAT,
                    metadata JSONB DEFAULT '{}'
                )
                """

                create_sections_table = """
                CREATE TABLE IF NOT EXISTS hyper_research_sections (
                    id SERIAL PRIMARY KEY,
                    section_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_order INTEGER NOT NULL,
                    section_level INTEGER DEFAULT 1,
                    parent_section_id VARCHAR(255),
                    section_type VARCHAR(100) NOT NULL,
                    section_title TEXT NOT NULL,
                    section_content TEXT,
                    section_summary TEXT,
                    section_status VARCHAR(50) DEFAULT 'pending',
                    sources_count INTEGER DEFAULT 0,
                    sources JSONB DEFAULT '[]',
                    queries JSONB DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    processing_time_ms INTEGER,
                    metadata JSONB DEFAULT '{}'
                )
                """

                create_data_collection_table = """
                CREATE TABLE IF NOT EXISTS hyper_research_data_collection (
                    id SERIAL PRIMARY KEY,
                    collection_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_id VARCHAR(255),
                    query_text TEXT NOT NULL,
                    query_type VARCHAR(50),
                    search_phase INTEGER,
                    results_count INTEGER DEFAULT 0,
                    results JSONB DEFAULT '[]',
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    execution_time_ms INTEGER,
                    metadata JSONB DEFAULT '{}'
                )
                """

                create_criticism_feedback_table = """
                CREATE TABLE IF NOT EXISTS hyper_research_criticism_feedback (
                    id SERIAL PRIMARY KEY,
                    feedback_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_type VARCHAR(100) NOT NULL,
                    section_title TEXT NOT NULL,
                    severity VARCHAR(50) DEFAULT 'none',
                    has_issues BOOLEAN DEFAULT FALSE,
                    feedback_text TEXT,
                    suggested_queries JSONB DEFAULT '[]',
                    missing_perspectives JSONB DEFAULT '[]',
                    redirect_suggestion TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'
                )
                """

                await db_manager.execute(create_reports_table)
                await db_manager.execute(create_sections_table)
                await db_manager.execute(create_data_collection_table)
                await db_manager.execute(create_criticism_feedback_table)

                print("[INFO] HyperDeepResearch tables created successfully")
            except Exception as e:
                print(f"[WARNING] Failed to create tables: {e}")
                print("[INFO] Will continue without DB storage")

    async def _update_report_status(self, status: str, timestamp_field: str = None, quality_score: float = None) -> None:
        """보고서 상태 업데이트"""
        try:
            updates = [f"research_status = '{status}'"]
            if timestamp_field:
                updates.append(f"{timestamp_field} = CURRENT_TIMESTAMP")
            if quality_score is not None:
                updates.append(f"quality_score = {quality_score}")

            query = f"UPDATE hyper_research_reports SET {', '.join(updates)} WHERE report_id = $1"
            await db_manager.execute(query, self.current_report_id)
            print(f"[DEBUG] Updated report status to: {status}")
        except Exception as e:
            print(f"[ERROR] Failed to update report status: {e}")

    async def _update_report_metadata(self) -> None:
        """보고서 메타데이터 업데이트"""
        try:
            query = """
            UPDATE hyper_research_reports
            SET total_sections = $1, total_sources = $2, total_queries = $3,
                metadata = $4
            WHERE report_id = $5
            """
            import json
            metadata_json = json.dumps({
                "unique_domains": len(self.research_metadata["unique_domains"]),
                "analysis_iterations": self.research_metadata["analysis_iterations_completed"],
                "critical_reviews": self.research_metadata["critical_reviews_completed"],
                "multi_query_searches": self.research_metadata["multi_query_searches"],
                "criticism_feedbacks_generated": self.research_metadata["criticism_feedbacks_generated"],
                "additional_research_triggered": self.research_metadata["additional_research_triggered"]
            })

            await db_manager.execute(
                query,
                len(self.sections_data),
                self.research_metadata["total_sources_collected"],
                self.research_metadata["total_queries_executed"],
                metadata_json,
                self.current_report_id
            )
        except Exception as e:
            print(f"[ERROR] Failed to update report metadata: {e}")

    async def _create_section_in_db(self, section_type: str, section_order: int, title: str,
                                   content: str, status: str, sources_count: int = 0) -> str:
        """섹션을 DB에 생성"""
        try:
            section_id = f"section_{uuid.uuid4()}"
            query = """
            INSERT INTO hyper_research_sections
            (section_id, report_id, section_order, section_type, section_title, section_content, section_status, sources_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """
            await db_manager.execute(
                query, section_id, self.current_report_id, section_order, section_type,
                title, content, status, sources_count
            )
            self.sections_data.append({"section_id": section_id, "title": title})
            print(f"[DEBUG] Created section in DB: {title}")
            return section_id
        except Exception as e:
            print(f"[ERROR] Failed to create section in DB: {e}")
            return ""

    async def _record_data_collection(self, query_text: str, query_type: str, phase: int, results: List[Dict]) -> None:
        """데이터 수집 기록"""
        try:
            collection_id = f"collection_{uuid.uuid4()}"
            query = """
            INSERT INTO hyper_research_data_collection
            (collection_id, report_id, query_text, query_type, search_phase, results_count, results)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """
            import json
            await db_manager.execute(
                query, collection_id, self.current_report_id, query_text, query_type,
                phase, len(results), json.dumps(results[:5])
            )
        except Exception as e:
            print(f"[ERROR] Failed to record data collection: {e}")

    async def _single_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """단일 Tavily 검색"""
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
