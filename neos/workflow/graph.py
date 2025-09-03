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
        
        # 쿼리 임베딩 생성
        if not state.get("query_embedding"):
            embedding = await embedding_manager.get_embedding(query)
            state["query_embedding"] = embedding
        
        # 쿼리 의도 분류
        intent = await self._classify_intent(query)
        state["query_intent"] = intent
        
        # 필요한 에이전트들 결정
        required_agents = self._determine_required_agents(query, intent)
        state["required_agents"] = required_agents
        
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
        required_agents = state["required_agents"]
        search_agents = [agent for agent in required_agents if agent in self.config.SEARCH_AGENTS]
        
        if not search_agents:
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
        search_tasks = []
        for agent_name in search_agents:
            agent = self.agents[agent_name]
            context = {
                "user_id": state["user_id"],
                "session_id": state["session_id"],
                "query_embedding": state.get("query_embedding"),
                "query_intent": state.get("query_intent")
            }
            task = agent.execute(state["original_query"], context)
            search_tasks.append(task)
        
        try:
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # 결과 처리 및 수집
            valid_results = []
            for i, result in enumerate(search_results):
                if isinstance(result, Exception):
                    state["errors"].append(f"Search agent {search_agents[i]} failed: {str(result)}")
                elif result.get("success"):
                    agent_results = result.get("result", [])
                    state["search_results"].extend(agent_results)
                    valid_results.extend(agent_results)
            
            # 유효한 결과가 있으면 캐싱 (30분)
            if valid_results:
                await cache_manager.set(search_cache_key, valid_results, ttl=1800, serialize="pickle")
            
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": f"completed - {len([r for r in search_results if not isinstance(r, Exception)])} agents succeeded",
                "timestamp": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
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
        
        if quality_score < self.config.MIN_QUALITY_SCORE:
            return "regenerate"
        else:
            return "proceed"
    
    async def _generate_response(self, state: AgentState) -> Dict[str, Any]:
        """최종 응답 생성"""
        # 모든 결과를 종합하여 응답 생성
        response_parts = []
        
        # 검색 결과 요약
        if state["search_results"]:
            search_summary = self._create_search_summary(state["search_results"])
            response_parts.append(search_summary)
        
        # 분석 결과 요약  
        if state["analysis_results"]:
            analysis_summary = self._create_analysis_summary(state["analysis_results"])
            response_parts.append(analysis_summary)
        
        # 생성 결과 요약
        if state["generation_results"]:
            generation_summary = self._create_generation_summary(state["generation_results"])
            response_parts.append(generation_summary)
        
        final_response = "\n\n".join(response_parts) if response_parts else "죄송합니다. 요청을 처리할 수 있는 정보를 찾지 못했습니다."
        
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
        
        top_results = sorted(results, key=lambda x: getattr(x, 'score', 0), reverse=True)[:3]
        summary_lines = ["## 검색 결과"]
        
        for i, result in enumerate(top_results, 1):
            title = getattr(result, 'title', '제목 없음')
            content = getattr(result, 'content', '')[:200] + "..." if len(getattr(result, 'content', '')) > 200 else getattr(result, 'content', '')
            summary_lines.append(f"{i}. **{title}**\n   {content}")
        
        return "\n".join(summary_lines)
    
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
