"""Search Strategy Patterns - 검색 전략 패턴

Strategy 패턴을 사용하여 다양한 검색 모드를 캡슐화
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from datetime import datetime
import logging
import asyncio

from neos.workflow.state import AgentState
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class SearchStrategy(ABC):
    """검색 전략 추상 클래스"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any],
        tool_selector: Any
    ) -> AgentState:
        """검색 전략 실행

        Args:
            state: 현재 에이전트 상태
            search_agents: 실행할 검색 에이전트 리스트
            agents: 사용 가능한 에이전트 딕셔너리
            tool_selector: 도구 선택기

        Returns:
            업데이트된 AgentState
        """
        pass

    @abstractmethod
    def is_applicable(self, state: AgentState) -> bool:
        """이 전략이 현재 상태에 적용 가능한지 판단

        Args:
            state: 현재 에이전트 상태

        Returns:
            적용 가능하면 True
        """
        pass


class IterativeSearchStrategy(SearchStrategy):
    """반복적 웹 탐색 전략"""

    def __init__(self):
        super().__init__("iterative_search")
        self.iterative_explorer = None
        self._init_explorer()

    def _init_explorer(self):
        """Iterative Explorer 초기화"""
        try:
            from neos.agents.search_agents import IterativeWebExplorerAgent
            self.iterative_explorer = IterativeWebExplorerAgent()
            logger.info("[IterativeStrategy] IterativeWebExplorer initialized")
        except Exception as e:
            logger.warning(f"[IterativeStrategy] Explorer init failed: {e}")

    def is_applicable(self, state: AgentState) -> bool:
        """반복적 탐색 적용 가능 여부 판단"""
        # Explorer 사용 가능 여부
        if not self.iterative_explorer:
            return False

        # 사용자 명시적 선호
        user_preference = state.get("use_iterative_search")
        if user_preference is not None:
            return user_preference

        # Query intent 기반 판단
        query_intent = state.get("query_intent", {})
        if not isinstance(query_intent, dict):
            query_intent = {}
        intent_type = query_intent.get("intent", "")

        if intent_type in ["research", "deep_analysis", "comparison", "comprehensive"]:
            return True

        # 쿼리 복잡도 기반 판단
        query = state.get("original_query", "")

        # 방어적 처리: query가 리스트인 경우 문자열로 변환
        if isinstance(query, list):
            query = ' '.join(str(q) for q in query)
        elif not isinstance(query, str):
            query = str(query) if query else ""

        complexity_keywords = [
            "비교", "분석", "조사", "연구", "compare", "analyze",
            "investigate", "research", "comprehensive", "thorough",
            "detailed", "in-depth", "차이", "장단점", "pros and cons"
        ]

        if query and any(keyword in query.lower() for keyword in complexity_keywords):
            return True

        return False

    async def execute(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any],
        tool_selector: Any
    ) -> AgentState:
        """반복적 웹 탐색 실행"""
        logger.info("[IterativeStrategy] Starting iterative exploration")

        # Context 구성
        context = {
            "user_id": state["user_id"],
            "session_id": state["session_id"],
            "query_embedding": state.get("query_embedding"),
            "query_intent": state.get("query_intent"),
            "detected_language": state.get("detected_language", "ko"),
            "max_depth": settings.ITERATIVE_EXPLORER_MAX_DEPTH,
            "max_pages": settings.ITERATIVE_EXPLORER_MAX_PAGES,
            "quality_threshold": settings.ITERATIVE_EXPLORER_MIN_QUALITY
        }

        try:
            # Iterative explorer 실행
            result = await self.iterative_explorer.execute(
                state["original_query"],
                context
            )

            if result.get("success"):
                exploration_results = result.get("result", [])
                state["search_results"].extend(exploration_results)

                metadata = result.get("metadata", {})
                state["exploration_depth_reached"] = metadata.get("depth_reached", 0)
                state["exploration_pages_visited"] = metadata.get("pages_visited", 0)

                state["execution_steps"].append({
                    "step": "iterative_search",
                    "result": f"completed - {len(exploration_results)} sources",
                    "timestamp": datetime.utcnow().isoformat()
                })

                logger.info(f"[IterativeStrategy] Completed: {len(exploration_results)} sources")
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"[IterativeStrategy] Failed: {error_msg}")
                state["errors"].append(f"Iterative search failed: {error_msg}")
                raise Exception(error_msg)

        except Exception as e:
            logger.error(f"[IterativeStrategy] Exception: {e}", exc_info=True)
            state["errors"].append(f"Iterative search exception: {str(e)}")
            raise

        return state


class StandardSearchStrategy(SearchStrategy):
    """표준 검색 전략 (기존 방식)"""

    def __init__(self):
        super().__init__("standard_search")

    def is_applicable(self, state: AgentState) -> bool:
        """항상 적용 가능 (폴백 전략)"""
        return True

    async def execute(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any],
        tool_selector: Any
    ) -> AgentState:
        """표준 검색 실행 (병렬 에이전트)"""
        logger.info("[StandardStrategy] Starting standard search")

        # 캐시 확인
        search_cache_key = self._generate_cache_key(state, search_agents)
        cached_results = await self._check_cache(search_cache_key, state)
        if cached_results:
            return state

        # 검색 실행
        search_tasks = await self._create_search_tasks(state, search_agents, agents, tool_selector)
        return await self._execute_and_process_results(
            search_tasks, search_agents, search_cache_key, state, agents
        )

    def _generate_cache_key(self, state: AgentState, search_agents: List[str]) -> str:
        """캐시 키 생성"""
        from neos.utils.cache import cache_manager

        detected_language = state.get("detected_language", "ko")
        return cache_manager.make_key(
            "search_results",
            hash(state["original_query"]),
            "-".join(sorted(search_agents)),
            detected_language
        )

    async def _check_cache(self, cache_key: str, state: AgentState) -> bool:
        """캐시된 결과 확인"""
        from neos.utils.cache import cache_manager

        cached_search_results = await cache_manager.get(cache_key, deserialize="pickle")
        if cached_search_results:
            state["search_results"].extend(cached_search_results)
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": f"completed (cached) - {len(cached_search_results)} results",
                "timestamp": datetime.utcnow().isoformat()
            })
            return True
        return False

    async def _create_search_tasks(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any],
        tool_selector: Any
    ) -> List:
        """검색 태스크 생성"""
        from neos.tools.tool_selector import ToolContext

        search_tasks = []

        # 도구 컨텍스트 생성
        tool_context = ToolContext(
            query=state["original_query"],
            user_id=state["user_id"],
            session_id=state["session_id"],
            intent=state.get("query_intent"),
            urgency="normal",
            quality_requirement="standard",
            mcp_preference=True,
            fallback_allowed=True
        )

        # MCP 웹 검색 도구 실행 시도
        if any("search" in agent for agent in search_agents):
            mcp_task = await self._create_mcp_search_task(state, tool_context, tool_selector)
            if mcp_task:
                search_tasks.append(mcp_task)

        # 기본 에이전트 태스크 생성
        agent_tasks = await self._create_agent_tasks(state, search_agents, agents)
        search_tasks.extend(agent_tasks)

        return search_tasks

    async def _create_mcp_search_task(
        self,
        state: AgentState,
        tool_context,
        tool_selector: Any
    ):
        """MCP 검색 태스크 생성"""
        try:
            mcp_search_params = {
                "query": state["original_query"],
                "max_results": 10
            }

            mcp_task = tool_selector.select_and_execute_tool(
                "web_search",
                mcp_search_params,
                tool_context
            )
            return mcp_task
        except Exception as e:
            logger.warning(f"[StandardStrategy] Failed to create MCP search task: {e}")
            return None

    async def _create_agent_tasks(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any]
    ) -> List:
        """기본 에이전트 태스크 생성"""
        agent_tasks = []

        for agent_name in search_agents:
            try:
                timeout = settings.AGENT_TIMEOUTS.get(agent_name, settings.AGENT_TIMEOUT)
                agent = agents[agent_name]
                context = {
                    "user_id": state["user_id"],
                    "session_id": state["session_id"],
                    "query_embedding": state.get("query_embedding"),
                    "query_intent": state.get("query_intent"),
                    "detected_language": state.get("detected_language")
                }
                # 개별 타임아웃이 적용된 래퍼 태스크 생성
                task = self._execute_with_timeout(
                    agent_name,
                    agent.execute(state["original_query"], context),
                    state,
                    timeout
                )
                agent_tasks.append(task)
            except Exception as e:
                logger.error(f"[StandardStrategy] Failed to create task for agent {agent_name}: {e}")
                state["errors"].append(f"Failed to create task for agent {agent_name}: {str(e)}")

        return agent_tasks

    async def _execute_with_timeout(
        self,
        agent_name: str,
        task: Any,
        state: AgentState,
        timeout: int
    ) -> Any:
        """개별 에이전트 타임아웃 적용하여 실행"""
        try:
            result = await asyncio.wait_for(task, timeout=timeout)
            logger.debug(f"[StandardStrategy] Agent {agent_name} completed (timeout: {timeout}s)")
            return result
        except asyncio.TimeoutError:
            error_msg = f"Agent {agent_name} timed out ({timeout}s)"
            logger.warning(error_msg)
            state["errors"].append(error_msg)
            return None
        except Exception as e:
            error_msg = f"Agent {agent_name} failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            state["errors"].append(error_msg)
            return e

    async def _execute_and_process_results(
        self,
        search_tasks: List,
        search_agents: List[str],
        cache_key: str,
        state: AgentState,
        agents: Dict[str, Any]
    ) -> AgentState:
        """검색 실행 및 결과 처리"""
        from neos.workflow.processors.search_result_synthesizer import SearchResultSynthesizer

        orchestration_timeout = settings.SEARCH_ORCHESTRATION_TIMEOUT

        try:
            # 검색 실행
            search_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=orchestration_timeout
            )

            # 결과 처리
            valid_results = await self._process_search_results(
                search_results, search_agents, state
            )

            # LLM 기반 검색 결과 종합 및 필터링
            synthesizer = SearchResultSynthesizer()
            synthesis_result = await synthesizer.synthesize_search_results(
                query=state["original_query"],
                search_results=state["search_results"],
                agent_errors=state["errors"],
                detected_language=state.get("detected_language", "ko"),
                session_id=state.get("session_id", ""),
                user_id=state.get("user_id", "")
            )

            # 정제된 결과로 교체
            state["search_results"] = synthesis_result["results"]
            state["search_synthesis"] = synthesis_result.get("synthesis")
            state["search_metadata"] = {
                "sources_checked": synthesis_result["sources_checked"],
                "sources_succeeded": synthesis_result["sources_succeeded"],
                "partial_success": synthesis_result.get("partial_success", False),
                "synthesis_performed": synthesis_result.get("synthesis_performed", False)
            }

            # 캐싱
            await self._cache_results(cache_key, synthesis_result["results"])

            # 실행 단계 기록
            self._record_execution_step(search_results, state)

        except asyncio.TimeoutError:
            logger.warning(f"[StandardStrategy] Orchestration timed out ({orchestration_timeout}s)")
            state["errors"].append(f"Search orchestration timed out after {orchestration_timeout} seconds")
            if state.get("search_metadata") is None:
                state["search_metadata"] = {
                    "sources_checked": len(search_agents),
                    "sources_succeeded": 0,
                    "partial_success": False,
                    "synthesis_performed": False
                }
        except Exception as e:
            logger.error(f"[StandardStrategy] Orchestration failed: {str(e)}")
            state["errors"].append(f"Search orchestration failed: {str(e)}")
            if state.get("search_metadata") is None:
                state["search_metadata"] = {
                    "sources_checked": len(search_agents),
                    "sources_succeeded": 0,
                    "partial_success": False,
                    "synthesis_performed": False
                }

        return state

    async def _process_search_results(
        self,
        search_results: List,
        search_agents: List[str],
        state: AgentState
    ) -> List:
        """검색 결과 처리 및 중복 제거"""
        valid_results = []
        seen_content = set()

        for i, result in enumerate(search_results):
            # MCP 결과인지 확인
            is_mcp_result = isinstance(result, tuple) and len(result) == 2

            if is_mcp_result:
                agent_results = self._process_mcp_result(result, state)
            else:
                agent_results = self._process_agent_result(
                    result, i, search_agents, state
                )

            if agent_results:
                unique_results = self._deduplicate_results(
                    agent_results, seen_content
                )
                state["search_results"].extend(unique_results)
                valid_results.extend(unique_results)

        return valid_results

    def _process_mcp_result(self, result: tuple, state: AgentState) -> List:
        """MCP 결과 처리"""
        mcp_result, selected_tool = result

        if mcp_result.success:
            mcp_data = mcp_result.data
            if isinstance(mcp_data, list):
                return mcp_data
            elif isinstance(mcp_data, dict) and "results" in mcp_data:
                return mcp_data["results"]
            else:
                return []
        else:
            state["errors"].append(f"MCP tool failed: {mcp_result.error}")
            return []

    def _process_agent_result(
        self,
        result: Any,
        index: int,
        search_agents: List[str],
        state: AgentState
    ) -> List:
        """기본 에이전트 결과 처리"""
        agent_index = index - (1 if any("search" in agent for agent in search_agents) else 0)

        if agent_index < len(search_agents):
            agent_name = search_agents[agent_index]
            logger.debug(f"[StandardStrategy] Processing result from: {agent_name}")

        if isinstance(result, Exception):
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                error_msg = f"Search agent {agent_name} failed: {str(result)}"
                logger.error(error_msg, exc_info=True)
                state["errors"].append(error_msg)
            return []

        elif result.get("success"):
            agent_results = result.get("result", [])
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                logger.info(f"[StandardStrategy] Agent {agent_name} succeeded: {len(agent_results)} results")
            return agent_results

        else:
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                error_detail = result.get("error", "Unknown error")
                logger.warning(f"[StandardStrategy] Agent {agent_name} unsuccessful: {error_detail}")
                state["errors"].append(f"Agent {agent_name} unsuccessful: {error_detail}")
            return []

    def _deduplicate_results(self, agent_results: List, seen_content: set) -> List:
        """결과 중복 제거"""
        unique_results = []

        for search_result in agent_results:
            title_raw = getattr(search_result, 'title', '')
            content_raw = getattr(search_result, 'content', '')

            # 방어적 처리
            if isinstance(title_raw, list):
                title = ' '.join(str(t) for t in title_raw).strip().lower()
            else:
                title = str(title_raw).strip().lower() if title_raw else ''

            if isinstance(content_raw, list):
                content = ' '.join(str(c) for c in content_raw)[:200].strip().lower()
            else:
                content = str(content_raw)[:200].strip().lower() if content_raw else ''

            content_hash = hash(title + content)

            if content_hash not in seen_content and title and content:
                seen_content.add(content_hash)
                unique_results.append(search_result)

        return unique_results

    async def _cache_results(self, cache_key: str, valid_results: List) -> None:
        """결과 캐싱"""
        from neos.utils.cache import cache_manager

        if valid_results:
            await cache_manager.set(cache_key, valid_results, ttl=3600, serialize="pickle")

    def _record_execution_step(
        self,
        search_results: List,
        state: AgentState
    ) -> None:
        """실행 단계 기록"""
        total_results = len(state["search_results"])
        successful_agents = len([r for r in search_results if not isinstance(r, Exception)])

        state["execution_steps"].append({
            "step": "search_orchestration",
            "result": f"completed - {successful_agents} agents/tools succeeded",
            "timestamp": datetime.utcnow().isoformat()
        })


class MultiHopSearchStrategy(SearchStrategy):
    """멀티홉 검색 전략

    복잡한 질문을 서브질문으로 분해하고 순차적 추론을 통해 답변 생성
    """

    def __init__(self):
        super().__init__("multi_hop_search")
        self.multi_hop_agent = None
        self._init_agent()

    def _init_agent(self):
        """MultiHopSearchAgent 초기화"""
        try:
            from neos.agents.search_agents.multi_hop_search import MultiHopSearchAgent
            self.multi_hop_agent = MultiHopSearchAgent()
            logger.info("[MultiHopStrategy] MultiHopSearchAgent initialized")
        except Exception as e:
            logger.warning(f"[MultiHopStrategy] Agent init failed: {e}")

    def is_applicable(self, state: AgentState) -> bool:
        """멀티홉 검색 적용 가능 여부 판단

        적용 조건:
        1. MultiHopSearchAgent 사용 가능
        2. 사용자 명시적 선호
        3. 복합 관계 키워드 포함 ("~의 ~", "~가 만든 ~" 등)
        4. 복잡한 추론이 필요한 질문
        """
        # Agent 사용 가능 여부
        if not self.multi_hop_agent:
            return False

        # 사용자 명시적 선호
        user_preference = state.get("use_multi_hop_search")
        if user_preference is not None:
            return user_preference

        # Query intent 기반 판단
        query_intent = state.get("query_intent", {})
        if not isinstance(query_intent, dict):
            query_intent = {}
        intent_type = query_intent.get("intent", "")

        # 복합 추론이 필요한 intent
        if intent_type in ["complex_reasoning", "multi_step", "relational"]:
            return True

        # 쿼리 복잡도 기반 판단
        query = state.get("original_query", "")

        # 방어적 처리: query가 리스트인 경우 문자열로 변환
        if isinstance(query, list):
            query = ' '.join(str(q) for q in query)
        elif not isinstance(query, str):
            query = str(query)

        # 멀티홉 검색 트리거 키워드
        multi_hop_keywords = [
            # 한국어
            "의 ",  # "X의 Y"
            "가 만든",
            "이 만든",
            "가 창업한",
            "이 창업한",
            "의 창립자",
            "의 설립자",
            "의 CEO",
            "의 대표",
            "의 모교",
            "의 출신",
            "이전에",
            "다음에",
            "했던",
            "누가",
            "어디서",
            "언제",

            # 영어
            "who created",
            "who founded",
            "founder of",
            "CEO of",
            "creator of",
            "inventor of",
            "location of",
            "where is",
            "when did",
            "what is the",
            "'s founder",
            "'s CEO",
            "'s location",
            "made by",
            "created by",
            "founded by",
        ]

        # 키워드 매칭 (대소문자 무시)
        query_lower = query.lower()
        if any(keyword.lower() in query_lower for keyword in multi_hop_keywords):
            logger.info("[MultiHopStrategy] Multi-hop keyword detected in query")
            return True

        # 질문 구조 분석: 여러 개의 조건/관계가 포함된 경우
        # 예: "A를 B한 C의 D는?" - 여러 관계가 연쇄됨
        relationship_markers = ["의", "가", "이", "을", "를", "에서", "'s", "of", "by", "in"]
        relationship_count = sum(1 for marker in relationship_markers if marker in query_lower)

        if relationship_count >= 3:  # 3개 이상의 관계 마커
            logger.info(f"[MultiHopStrategy] Complex relationship structure detected ({relationship_count} markers)")
            return True

        return False

    async def execute(
        self,
        state: AgentState,
        search_agents: List[str],
        agents: Dict[str, Any],
        tool_selector: Any
    ) -> AgentState:
        """멀티홉 검색 실행"""
        logger.info("[MultiHopStrategy] Starting multi-hop search")

        try:
            # 컨텍스트 구성
            context = {
                "session_id": state.get("session_id", ""),
                "user_id": state.get("user_id", ""),
                "detected_language": state.get("detected_language", "ko"),
                "query_intent": state.get("query_intent"),
            }

            # MultiHopSearchAgent 실행
            result = await self.multi_hop_agent.execute(
                state["original_query"],
                context
            )

            if result.get("success"):
                # 검색 결과 추가
                multi_hop_results = result.get("result", [])
                state["search_results"].extend(multi_hop_results)

                # 메타데이터 저장
                metadata = result.get("metadata", {})
                state["multi_hop_metadata"] = metadata

                # 실행 단계 기록
                state["execution_steps"].append({
                    "step": "multi_hop_search",
                    "result": f"completed - {metadata.get('hop_count', 0)} hops, "
                             f"confidence: {metadata.get('total_confidence', 0):.2f}",
                    "timestamp": datetime.utcnow().isoformat()
                })

                logger.info(
                    f"[MultiHopStrategy] Completed: {len(multi_hop_results)} results, "
                    f"{metadata.get('hop_count', 0)} hops"
                )
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"[MultiHopStrategy] Failed: {error_msg}")
                state["errors"].append(f"Multi-hop search failed: {error_msg}")
                raise Exception(error_msg)

        except Exception as e:
            logger.error(f"[MultiHopStrategy] Exception: {e}", exc_info=True)
            state["errors"].append(f"Multi-hop search exception: {str(e)}")
            raise

        return state
