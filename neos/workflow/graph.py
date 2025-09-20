from typing import Dict, Any, List
from datetime import datetime
import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from neos.agents.search_agents import (
    KnowledgeSearchAgent,
    RealtimeInfoSearchAgent, 
    RealtimeDataSearchAgent
)
from neos.agents.analysis_agents import (
    DataAnalysisAgent,
    ComparativeAnalysisAgent
)
from neos.agents.generation_agents import (
    ImageGenerationAgent,
    ApiCallAgent,
    FileProcessingAgent,
    TaskCreationAgent
)
from neos.utils.embeddings import embedding_manager
from neos.utils.cache import cache_manager

from .state import AgentState, WorkflowConfig


class MultiAgentWorkflow:
    """멀티 에이전트 워크플로우 관리 클래스"""
    
    def __init__(self):
        self.agents = self._initialize_agents()
        self.graph = self._create_workflow_graph()
        self.config = WorkflowConfig()
    
    def _initialize_agents(self) -> Dict[str, Any]:
        """에이전트 초기화"""
        return {
            # 검색 에이전트들
            "knowledge_search": KnowledgeSearchAgent(),
            "realtime_info_search": RealtimeInfoSearchAgent(),
            "realtime_data_search": RealtimeDataSearchAgent(),
            
            # 분석 에이전트들
            "data_analysis": DataAnalysisAgent(),
            "comparative_analysis": ComparativeAnalysisAgent(),
            
            # 생성 에이전트들
            "image_generation": ImageGenerationAgent(),
            "api_call": ApiCallAgent(),
            "file_processing": FileProcessingAgent(),
            "task_creation": TaskCreationAgent()
        }
    
    def _create_workflow_graph(self) -> StateGraph:
        """워크플로우 그래프 생성"""
        workflow = StateGraph(AgentState)
        
        # 노드 추가
        workflow.add_node("query_classifier", self._classify_query)
        workflow.add_node("search_orchestrator", self._orchestrate_search)
        workflow.add_node("analysis_orchestrator", self._orchestrate_analysis)
        workflow.add_node("generation_orchestrator", self._orchestrate_generation)
        workflow.add_node("result_integrator", self._integrate_results)
        workflow.add_node("quality_validator", self._validate_quality)
        workflow.add_node("response_generator", self._generate_response)
        
        # 엣지 정의
        workflow.set_entry_point("query_classifier")
        
        workflow.add_edge("query_classifier", "search_orchestrator")
        workflow.add_edge("search_orchestrator", "analysis_orchestrator") 
        workflow.add_edge("analysis_orchestrator", "generation_orchestrator")
        workflow.add_edge("generation_orchestrator", "result_integrator")
        workflow.add_edge("result_integrator", "quality_validator")
        
        # 조건부 엣지 (품질 검증 결과에 따라)
        workflow.add_conditional_edges(
            "quality_validator",
            self._should_regenerate,
            {
                "regenerate": "search_orchestrator",  # 품질이 낮으면 다시 검색
                "proceed": "response_generator"       # 품질이 좋으면 응답 생성
            }
        )
        
        workflow.add_edge("response_generator", END)
        
        return workflow.compile(checkpointer=MemorySaver())
    
    async def _classify_query(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 및 의도 파악"""
        query = state["original_query"]

        try:
            # 쿼리 임베딩 생성
            if not state.get("query_embedding"):
                print(f"[DEBUG] Generating embedding for query: {query[:50]}...")
                embedding = await embedding_manager.get_embedding(query)
                state["query_embedding"] = embedding
                print(f"[DEBUG] Embedding generated, length: {len(embedding) if embedding else 'None'}")

            # 쿼리 의도 분류
            print("[DEBUG] Classifying query intent...")
            intent = await self._classify_intent(query)
            state["query_intent"] = intent
            print(f"[DEBUG] Intent classified as: {intent}")

            # 필요한 에이전트들 결정
            print("[DEBUG] Determining required agents...")
            required_agents = self._determine_required_agents(query, intent)
            state["required_agents"] = required_agents
            print(f"[DEBUG] Required agents: {required_agents}")
        except Exception as e:
            print(f"[ERROR] Query classification failed: {e}")
            raise
        
        # 분류 결과 저장
        state["query_classification"] = {
            "intent": intent,
            "required_agents": required_agents,
            "confidence": 0.8,  # 실제로는 분류 모델의 신뢰도
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # 실행 단계 기록
        state["execution_steps"].append({
            "step": "query_classification",
            "result": "completed",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return state
    
    async def _classify_intent(self, query: str) -> str:
        """쿼리 의도 분류"""
        query_lower = query.lower()
        
        # 키워드 기반 의도 분류 (실제로는 ML 모델 사용)
        if any(word in query_lower for word in ["비교", "compare", "차이", "difference"]):
            return "comparison"
        elif any(word in query_lower for word in ["분석", "analyze", "통계", "statistics"]):
            return "data_analysis"
        elif any(word in query_lower for word in ["생성", "만들어", "create", "generate"]):
            return "generation"
        elif any(word in query_lower for word in ["최신", "현재", "실시간", "current", "latest"]):
            return "realtime_info"
        elif any(word in query_lower for word in ["작업", "계획", "task", "plan"]):
            return "task_execution"
        else:
            return "information_seeking"
    
    def _determine_required_agents(self, query: str, intent: str) -> List[str]:
        """필요한 에이전트 결정"""
        agents = []
        
        # 기본적으로 지식 검색은 항상 포함
        agents.append("knowledge_search")
        
        # 의도에 따른 에이전트 추가
        if intent == "realtime_info":
            agents.extend(["realtime_info_search", "realtime_data_search"])
        elif intent == "data_analysis":
            agents.extend(["data_analysis", "realtime_data_search"])
        elif intent == "comparison":
            agents.extend(["comparative_analysis", "realtime_info_search"])
        elif intent == "generation":
            if "이미지" in query or "image" in query:
                agents.append("image_generation")
            if "파일" in query or "file" in query:
                agents.append("file_processing")
            if "작업" in query or "task" in query:
                agents.append("task_creation")
            if "api" in query.lower() or "데이터" in query:
                agents.append("api_call")
        else:
            # 기본적인 정보 탐색
            agents.append("realtime_info_search")
        
        return list(set(agents))  # 중복 제거
    
    async def _orchestrate_search(self, state: AgentState) -> Dict[str, Any]:
        """검색 에이전트들 오케스트레이션"""
        print("[DEBUG] Starting search orchestration...")
        required_agents = state["required_agents"]
        search_agents = [agent for agent in required_agents if agent in self.config.SEARCH_AGENTS]
        print(f"[DEBUG] Search agents to execute: {search_agents}")

        if not search_agents:
            print("[DEBUG] No search agents required, skipping...")
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": "skipped - no search agents required",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state
        
        # 검색 결과 캐시 키 생성 (쿼리와 에이전트 조합 기반)
        search_cache_key = cache_manager.make_key(
            "search_results", 
            hash(state["original_query"]), 
            "-".join(sorted(search_agents))
        )
        
        # 캐시된 검색 결과 확인
        cached_search_results = await cache_manager.get(search_cache_key, deserialize="pickle")
        if cached_search_results:
            state["search_results"].extend(cached_search_results)
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": f"completed (cached) - {len(cached_search_results)} results",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state
        
        # 병렬 검색 실행
        print("[DEBUG] Creating search tasks...")
        search_tasks = []
        for agent_name in search_agents:
            try:
                print(f"[DEBUG] Setting up task for agent: {agent_name}")
                agent = self.agents[agent_name]
                context = {
                    "user_id": state["user_id"],
                    "session_id": state["session_id"],
                    "query_embedding": state.get("query_embedding"),
                    "query_intent": state.get("query_intent")
                }
                task = agent.execute(state["original_query"], context)
                search_tasks.append(task)
                print(f"[DEBUG] Task created for agent: {agent_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create task for agent {agent_name}: {e}")
                state["errors"].append(f"Failed to create task for agent {agent_name}: {str(e)}")

        print(f"[DEBUG] Executing {len(search_tasks)} search tasks...")
        try:
            print("[DEBUG] Starting asyncio.gather with 120s timeout...")
            search_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=120  # 2 minutes timeout for search
            )
            print(f"[DEBUG] Search execution completed, got {len(search_results)} results")

            # 결과 처리 및 수집
            valid_results = []
            seen_content = set()  # Track seen content for deduplication

            for i, result in enumerate(search_results):
                print(f"[DEBUG] Processing result {i+1}/{len(search_results)} from agent {search_agents[i]}")
                if isinstance(result, Exception):
                    print(f"[ERROR] Search agent {search_agents[i]} failed: {str(result)}")
                    state["errors"].append(f"Search agent {search_agents[i]} failed: {str(result)}")
                elif result.get("success"):
                    agent_results = result.get("result", [])
                    print(f"[DEBUG] Agent {search_agents[i]} returned {len(agent_results)} results")

                    # Deduplicate results based on title and content similarity
                    unique_results = []
                    for search_result in agent_results:
                        # Create a content hash for deduplication
                        title = getattr(search_result, 'title', '').strip().lower()
                        content = getattr(search_result, 'content', '')[:200].strip().lower()
                        content_hash = hash(title + content)

                        if content_hash not in seen_content and title and content:
                            seen_content.add(content_hash)
                            unique_results.append(search_result)
                        else:
                            print(f"[DEBUG] Skipping duplicate result: {title[:50]}...")

                    print(f"[DEBUG] After deduplication: {len(unique_results)} unique results from {len(agent_results)} total")
                    state["search_results"].extend(unique_results)
                    valid_results.extend(unique_results)
                else:
                    print(f"[WARNING] Agent {search_agents[i]} returned unsuccessful result: {result}")

            # 유효한 결과가 있으면 캐싱 (30분)
            if valid_results:
                print(f"[DEBUG] Caching {len(valid_results)} valid search results")
                await cache_manager.set(search_cache_key, valid_results, ttl=1800, serialize="pickle")

            print(f"[DEBUG] Search orchestration completed with {len(valid_results)} total results")
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": f"completed - {len([r for r in search_results if not isinstance(r, Exception)])} agents succeeded",
                "timestamp": datetime.utcnow().isoformat()
            })

        except asyncio.TimeoutError:
            print("[ERROR] Search orchestration timed out after 2 minutes")
            state["errors"].append("Search orchestration timed out after 2 minutes")
        except Exception as e:
            print(f"[ERROR] Search orchestration failed: {str(e)}")
            state["errors"].append(f"Search orchestration failed: {str(e)}")
        
        return state
    
    async def _orchestrate_analysis(self, state: AgentState) -> Dict[str, Any]:
        """분석 에이전트들 오케스트레이션"""
        required_agents = state["required_agents"]
        analysis_agents = [agent for agent in required_agents if agent in self.config.ANALYSIS_AGENTS]
        
        if not analysis_agents or not state["search_results"]:
            state["execution_steps"].append({
                "step": "analysis_orchestration", 
                "result": "skipped - no analysis agents required or no search results",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state
        
        # 분석 실행
        analysis_tasks = []
        for agent_name in analysis_agents:
            agent = self.agents[agent_name]
            context = {
                "user_id": state["user_id"],
                "session_id": state["session_id"],
                "search_results": state["search_results"],
                "query_intent": state.get("query_intent")
            }
            task = agent.execute(state["original_query"], context)
            analysis_tasks.append(task)
        
        try:
            analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            
            # 결과 처리
            for i, result in enumerate(analysis_results):
                if isinstance(result, Exception):
                    state["errors"].append(f"Analysis agent {analysis_agents[i]} failed: {str(result)}")
                elif result.get("success"):
                    state["analysis_results"].append(result.get("result"))
            
            state["execution_steps"].append({
                "step": "analysis_orchestration",
                "result": f"completed - {len([r for r in analysis_results if not isinstance(r, Exception)])} agents succeeded",
                "timestamp": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            state["errors"].append(f"Analysis orchestration failed: {str(e)}")
        
        return state
    
    async def _orchestrate_generation(self, state: AgentState) -> Dict[str, Any]:
        """생성 에이전트들 오케스트레이션"""
        required_agents = state["required_agents"]
        generation_agents = [agent for agent in required_agents if agent in self.config.GENERATION_AGENTS]
        
        if not generation_agents:
            state["execution_steps"].append({
                "step": "generation_orchestration",
                "result": "skipped - no generation agents required",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state
        
        # 생성 실행
        generation_tasks = []
        for agent_name in generation_agents:
            agent = self.agents[agent_name]
            context = {
                "user_id": state["user_id"],
                "session_id": state["session_id"],
                "search_results": state["search_results"],
                "analysis_results": state["analysis_results"],
                "query_intent": state.get("query_intent")
            }
            task = agent.execute(state["original_query"], context)
            generation_tasks.append(task)
        
        try:
            generation_results = await asyncio.gather(*generation_tasks, return_exceptions=True)
            
            # 결과 처리
            for i, result in enumerate(generation_results):
                if isinstance(result, Exception):
                    state["errors"].append(f"Generation agent {generation_agents[i]} failed: {str(result)}")
                elif result.get("success"):
                    state["generation_results"].append(result.get("result"))
            
            state["execution_steps"].append({
                "step": "generation_orchestration",
                "result": f"completed - {len([r for r in generation_results if not isinstance(r, Exception)])} agents succeeded",
                "timestamp": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            state["errors"].append(f"Generation orchestration failed: {str(e)}")
        
        return state
    
    async def _integrate_results(self, state: AgentState) -> Dict[str, Any]:
        """결과 통합"""
        integrated_data = {
            "search_summary": self._summarize_search_results(state["search_results"]),
            "analysis_summary": self._summarize_analysis_results(state["analysis_results"]),
            "generation_summary": self._summarize_generation_results(state["generation_results"]),
            "total_sources": len(state["search_results"]),
            "confidence_scores": []
        }
        
        # 신뢰도 점수 계산
        for analysis in state["analysis_results"]:
            if hasattr(analysis, 'confidence'):
                integrated_data["confidence_scores"].append(analysis.confidence)
        
        state["integrated_results"] = integrated_data
        
        state["execution_steps"].append({
            "step": "result_integration",
            "result": "completed",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return state
    
    def _summarize_search_results(self, results: List[Any]) -> Dict[str, Any]:
        """검색 결과 요약"""
        if not results:
            return {"count": 0, "sources": []}
        
        sources = list(set([r.source for r in results if hasattr(r, 'source')]))
        avg_score = sum([r.score for r in results if hasattr(r, 'score')]) / len(results)
        
        return {
            "count": len(results),
            "sources": sources,
            "avg_score": avg_score
        }
    
    def _summarize_analysis_results(self, results: List[Any]) -> Dict[str, Any]:
        """분석 결과 요약"""
        if not results:
            return {"count": 0, "types": []}
        
        types = list(set([r.analysis_type for r in results if hasattr(r, 'analysis_type')]))
        total_insights = sum([len(r.insights) for r in results if hasattr(r, 'insights')])
        
        return {
            "count": len(results),
            "types": types,
            "total_insights": total_insights
        }
    
    def _summarize_generation_results(self, results: List[Any]) -> Dict[str, Any]:
        """생성 결과 요약"""
        if not results:
            return {"count": 0, "types": []}
        
        types = list(set([r.content_type for r in results if hasattr(r, 'content_type')]))
        
        return {
            "count": len(results),
            "types": types
        }
    
    async def _validate_quality(self, state: AgentState) -> Dict[str, Any]:
        """품질 검증"""
        quality_metrics = {
            "completeness": self._calculate_completeness(state),
            "relevance": self._calculate_relevance(state),
            "coherence": self._calculate_coherence(state)
        }
        
        # 전체 품질 점수 계산
        overall_score = sum(quality_metrics.values()) / len(quality_metrics)
        
        state["quality_score"] = overall_score
        state["quality_feedback"] = self._generate_quality_feedback(quality_metrics)
        
        state["execution_steps"].append({
            "step": "quality_validation",
            "result": f"completed - score: {overall_score:.2f}",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return state
    
    def _calculate_completeness(self, state: AgentState) -> float:
        """완성도 계산"""
        required_agents = set(state["required_agents"])
        executed_agents = set()
        
        # 각 결과에서 실행된 에이전트 추출
        for result in state["search_results"] + state["analysis_results"] + state["generation_results"]:
            if hasattr(result, 'agent'):
                executed_agents.add(result.agent)
        
        if not required_agents:
            return 1.0
        
        return len(executed_agents.intersection(required_agents)) / len(required_agents)
    
    def _calculate_relevance(self, state: AgentState) -> float:
        """관련성 계산"""
        # 검색 결과의 평균 점수로 관련성 추정
        search_scores = [r.score for r in state["search_results"] if hasattr(r, 'score')]
        
        if not search_scores:
            return 0.5  # 기본값
        
        return sum(search_scores) / len(search_scores)
    
    def _calculate_coherence(self, state: AgentState) -> float:
        """일관성 계산"""
        # 에러 발생률로 일관성 추정
        total_steps = len(state["execution_steps"])
        errors = len(state["errors"])
        
        if total_steps == 0:
            return 0.0
        
        return max(0.0, 1.0 - (errors / total_steps))
    
    def _generate_quality_feedback(self, metrics: Dict[str, float]) -> str:
        """품질 피드백 생성"""
        feedback_parts = []
        
        if metrics["completeness"] < 0.7:
            feedback_parts.append("일부 필요한 에이전트가 실행되지 않았습니다.")
        
        if metrics["relevance"] < 0.6:
            feedback_parts.append("검색 결과의 관련성이 낮습니다.")
        
        if metrics["coherence"] < 0.8:
            feedback_parts.append("처리 과정에서 오류가 발생했습니다.")
        
        if not feedback_parts:
            return "품질이 우수합니다."
        
        return " ".join(feedback_parts)
    
    def _should_regenerate(self, state: AgentState) -> str:
        """재생성 여부 결정"""
        quality_score = state.get("quality_score", 0.0)
        retry_count = state.get("retry_count", 0)

        # Check if we've exceeded max retries
        if retry_count >= self.config.MAX_RETRIES:
            print(f"[DEBUG] Max retries ({self.config.MAX_RETRIES}) reached, proceeding to response generation")
            return "proceed"

        # Check quality score
        if quality_score < self.config.MIN_QUALITY_SCORE:
            print(f"[DEBUG] Quality score {quality_score} < {self.config.MIN_QUALITY_SCORE}, retry {retry_count + 1}/{self.config.MAX_RETRIES}")
            state["retry_count"] = retry_count + 1
            return "regenerate"
        else:
            print(f"[DEBUG] Quality score {quality_score} >= {self.config.MIN_QUALITY_SCORE}, proceeding")
            return "proceed"

    async def _generate_response(self, state: AgentState) -> Dict[str, Any]:
        """최종 응답 생성"""
        # 모든 결과를 종합하여 응답 생성
        response_parts = []

        # 검색 결과가 있는 경우에만 검색 결과 요약 추가
        if state["search_results"] and len(state["search_results"]) > 0:
            print(f"[DEBUG] Generating search summary from {len(state['search_results'])} results")
            search_summary = self._create_search_summary(state["search_results"])
            if search_summary and "검색된 고유한 결과가 없습니다" not in search_summary:
                response_parts.append(search_summary)
            else:
                print("[DEBUG] No unique search results found, skipping search summary")

        # 분석 결과 요약
        if state["analysis_results"] and len(state["analysis_results"]) > 0:
            print(f"[DEBUG] Generating analysis summary from {len(state['analysis_results'])} results")
            analysis_summary = self._create_analysis_summary(state["analysis_results"])
            if analysis_summary:
                response_parts.append(analysis_summary)

        # 생성 결과 요약
        if state["generation_results"] and len(state["generation_results"]) > 0:
            print(f"[DEBUG] Generating generation summary from {len(state['generation_results'])} results")
            generation_summary = self._create_generation_summary(state["generation_results"])
            if generation_summary:
                response_parts.append(generation_summary)

        # 응답 품질 개선
        if response_parts:
            final_response = "\n\n".join(response_parts)
        else:
            final_response = "죄송합니다. 요청하신 주제에 대한 관련 정보를 찾지 못했습니다. 다른 키워드로 다시 시도해 보시기 바랍니다."
        
        # 실행 시간 계산
        execution_time = int((datetime.utcnow() - state["execution_start"]).total_seconds() * 1000)
        
        state["final_response"] = final_response
        state["execution_time_ms"] = execution_time
        state["response_metadata"] = {
            "total_sources": len(state["search_results"]),
            "analysis_count": len(state["analysis_results"]),
            "generation_count": len(state["generation_results"]),
            "quality_score": state.get("quality_score", 0.0)
        }
        
        state["execution_steps"].append({
            "step": "response_generation",
            "result": "completed",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return state
    
    def _create_search_summary(self, results: List[Any]) -> str:
        """검색 결과 요약 생성"""
        if not results:
            return ""

        # Sort by score and deduplicate by title similarity
        sorted_results = sorted(results, key=lambda x: getattr(x, 'score', 0), reverse=True)

        # Categorize results by company/topic
        categorized_results = self._categorize_results_by_topic(sorted_results)

        if not any(categorized_results.values()):
            return "## 검색 결과\n검색된 고유한 결과가 없습니다."

        summary_lines = ["## 2025년 주요 IT 기업 주식 전망 분석"]

        # Company-specific sections with clear outlook statements
        company_sections = {
            'nvidia': '### 🔹 엔비디아 (NVIDIA) 주식 전망',
            'meta': '### 🔹 메타 (Meta) 주식 전망',
            'alphabet': '### 🔹 알파벳/구글 (Alphabet/Google) 주식 전망'
        }

        for company, section_title in company_sections.items():
            company_results = categorized_results.get(company, [])
            if company_results:
                summary_lines.append(f"\n{section_title}")

                # Show top 2 results for each company with full content
                for i, result in enumerate(company_results[:2]):
                    title = getattr(result, 'title', '제목 없음')
                    content = getattr(result, 'content', '')
                    url = getattr(result, 'url', '')

                    # Check if this is LLM-processed content (don't truncate it)
                    source = getattr(result, 'source', '')
                    if source == 'llm_processed_web':
                        # Don't process LLM content, use it as-is
                        processed_content = content
                        citation_info = ""  # LLM already includes citations
                    else:
                        # Use longer content for better analysis
                        processed_content = self._process_content_for_display(content, max_length=1200)
                        citation_info = self._format_citation(url)

                    summary_lines.append(f"**{title}**\n{processed_content}{citation_info}\n")

        # Add general results if any
        general_results = categorized_results.get('general', [])
        if general_results:
            summary_lines.append("\n### 🔹 추가 정보")
            for result in general_results[:2]:
                title = getattr(result, 'title', '제목 없음')
                content = getattr(result, 'content', '')
                url = getattr(result, 'url', '')

                processed_content = self._process_content_for_display(content, max_length=800)
                citation_info = self._format_citation(url)

                summary_lines.append(f"**{title}**\n{processed_content}{citation_info}\n")

        return "\n".join(summary_lines)

    def _format_citation(self, url: str) -> str:
        """Format citation information for search results"""
        if not url or url.strip() == "":
            return ""

        # Clean and validate URL
        url = url.strip()

        # Extract domain for display
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc

            # Clean domain (remove www. prefix)
            if domain.startswith('www.'):
                domain = domain[4:]

            return f"\n   *출처: {domain}* ([링크]({url}))"

        except Exception:
            # Fallback for invalid URLs
            return f"\n   *출처: [링크]({url})*"

    def _categorize_results_by_topic(self, results: List[Any]) -> Dict[str, List[Any]]:
        """Categorize search results by company/topic"""
        categories = {
            'nvidia': [],
            'meta': [],
            'alphabet': [],
            'general': []
        }

        seen_content = set()

        for result in results:
            title = getattr(result, 'title', '').lower()
            content = getattr(result, 'content', '').lower()
            combined_text = title + ' ' + content

            # Create content hash for deduplication
            content_hash = hash(title + content[:200])
            if content_hash in seen_content:
                continue
            seen_content.add(content_hash)

            # Categorize based on keywords
            if any(keyword in combined_text for keyword in ['엔비디아', 'nvidia', 'nvda']):
                categories['nvidia'].append(result)
            elif any(keyword in combined_text for keyword in ['메타', 'meta', '페이스북', 'facebook']):
                categories['meta'].append(result)
            elif any(keyword in combined_text for keyword in ['알파벳', 'alphabet', '구글', 'google', 'googl']):
                categories['alphabet'].append(result)
            else:
                categories['general'].append(result)

        # Sort each category by score
        for category in categories:
            categories[category] = sorted(categories[category],
                                        key=lambda x: getattr(x, 'score', 0),
                                        reverse=True)

        return categories

    def _process_content_for_display(self, content: str, max_length: int = 400) -> str:
        """Process content for better display with intelligent truncation"""
        if not content or content.strip() == "":
            return "내용이 없습니다."

        # Clean up the content
        content = content.strip()

        # Remove excessive whitespace and normalize
        content = ' '.join(content.split())

        # Remove common web artifacts
        artifacts_to_remove = [
            '*My Menu 닫기*',
            '본문 바로가기',
            '**본문 폰트 크기 조정**',
            'blog.naver',
            '.com',
            '>>>',
            '>>',
            '* *',
            '>'
        ]

        for artifact in artifacts_to_remove:
            content = content.replace(artifact, '').strip()

        # If content is short enough, return as is
        if len(content) <= max_length:
            return content

        # Try multiple approaches to find the best cut point
        best_content = self._find_best_truncation(content, max_length)

        print(f"[DEBUG] Content truncation: original={len(content)}, processed={len(best_content)}")
        return best_content

    def _find_best_truncation(self, content: str, max_length: int) -> str:
        """Find the best truncation point using multiple strategies"""

        # Strategy 1: Look for perfect sentence endings
        perfect_endings = ['다.', '요.', '습니다.', '합니다.', '됩니다.', '입니다.', '었습니다.', '았습니다.', '였습니다.', '있습니다.', '것입니다.']

        # Search for sentence endings in a reasonable range
        search_start = max(max_length // 2, max_length - 150)

        for end_pos in range(min(len(content), max_length + 50), search_start, -1):
            if end_pos <= len(content):
                for ending in perfect_endings:
                    if content[end_pos - len(ending):end_pos] == ending:
                        # Check if this is actually the end of a sentence
                        if end_pos == len(content) or content[end_pos:end_pos+1].isspace():
                            return content[:end_pos].strip()

        # Strategy 2: Look for punctuation followed by space
        truncated = content[:max_length]
        for i in range(len(truncated) - 1, max(0, len(truncated) - 100), -1):
            if i < len(truncated) - 1:
                char = truncated[i]
                next_char = truncated[i + 1]

                if char in '.!?' and (next_char.isspace() or next_char.isupper()):
                    return content[:i + 1].strip()

        # Strategy 3: Look for Korean verb/adjective endings
        korean_endings = ['다', '요', '니다', '습니다', '합니다', '됩니다', '입니다', '었다', '았다', '였다']

        for ending in korean_endings:
            for i in range(min(len(content), max_length), max(0, max_length - 100), -1):
                if content[i - len(ending):i] == ending:
                    # Check if followed by space, period, or end of text
                    if i == len(content) or content[i:i+1] in ' .,!?':
                        return content[:i].strip()

        # Strategy 4: Cut at word boundary
        truncated = content[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.7:
            return content[:last_space].strip() + "..."

        # Strategy 5: Last resort - cut cleanly without breaking words
        words = truncated.split()
        if len(words) > 1:
            return ' '.join(words[:-1]).strip() + "..."
        else:
            return truncated.rstrip() + "..."

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two text strings using Jaccard similarity"""
        if not text1 or not text2:
            return 0.0

        # Split into words and create sets
        words1 = set(text1.split())
        words2 = set(text2.split())

        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        if union == 0:
            return 0.0

        return intersection / union

    def _create_analysis_summary(self, results: List[Any]) -> str:
        """분석 결과 요약 생성"""
        if not results:
            return ""
        
        summary_lines = ["## 분석 결과"]
        
        for result in results:
            analysis_type = getattr(result, 'analysis_type', '분석')
            insights = getattr(result, 'insights', [])
            
            summary_lines.append(f"### {analysis_type}")
            for insight in insights[:3]:  # 최대 3개의 인사이트
                summary_lines.append(f"- {insight}")
        
        return "\n".join(summary_lines)
    
    def _create_generation_summary(self, results: List[Any]) -> str:
        """생성 결과 요약 생성"""
        if not results:
            return ""
        
        summary_lines = ["## 생성 결과"]
        
        for result in results:
            content_type = getattr(result, 'content_type', '콘텐츠')
            summary_lines.append(f"- {content_type} 생성 완료")
        
        return "\n".join(summary_lines)
    
    async def execute_workflow(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 실행"""
        # 초기 상태 생성
        initial_state = AgentState(
            user_id=user_input["user_id"],
            session_id=user_input["session_id"],
            original_query=user_input["query"],
            query_intent=None,
            query_embedding=None,
            query_classification=None,
            required_agents=[],
            search_results=[],
            analysis_results=[],
            generation_results=[],
            integrated_results=None,
            quality_score=None,
            quality_feedback=None,
            final_response=None,
            response_metadata=None,
            execution_start=datetime.utcnow(),
            execution_steps=[],
            errors=[],
            retry_count=0,
            execution_time_ms=None,
            tokens_used=None,
            api_calls_made=None
        )
        
        try:
            # 워크플로우 실행
            config = {"configurable": {"thread_id": user_input["session_id"]}}
            final_state = await self.graph.ainvoke(initial_state, config)
            
            return {
                "success": True,
                "response": final_state["final_response"],
                "metadata": final_state["response_metadata"],
                "execution_time_ms": final_state["execution_time_ms"],
                "quality_score": final_state.get("quality_score", 0.0),
                "errors": final_state["errors"]
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "partial_state": initial_state
            }


# 전역 워크플로우 인스턴스
multi_agent_workflow = MultiAgentWorkflow()
