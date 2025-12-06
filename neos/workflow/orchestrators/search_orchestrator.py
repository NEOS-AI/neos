"""검색 오케스트레이터 모듈"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import logging

from neos.config.settings import settings
from neos.utils.cache import cache_manager
from neos.utils.circuit_breaker import AgentCircuitBreaker
from neos.tools.tool_selector import ToolContext

from ..state import AgentState

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    """검색 에이전트들 오케스트레이션"""

    def __init__(self, agents: Dict[str, Any], config, tool_selector):
        self.agents = agents
        self.config = config
        self.tool_selector = tool_selector

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
        """검색 에이전트들 오케스트레이션 (MCP 통합)"""
        logger.info("검색 오케스트레이션 시작 (MCP 통합)")
        required_agents = state["required_agents"]
        search_agents = [agent for agent in required_agents if agent in self.config.SEARCH_AGENTS]
        logger.info(f"실행할 검색 에이전트: {search_agents}")

        if not search_agents:
            logger.debug("검색 에이전트가 필요하지 않음, 건너뜀")
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": "skipped - no search agents required",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state

        # MCP 도구 선택기 초기화 (필요시)
        if not self.tool_selector.initialized:
            logger.debug("도구 선택기 초기화 중...")
            await self.tool_selector.initialize()

        # 캐시 확인
        search_cache_key = self._generate_cache_key(state, search_agents)
        cached_results = await self._check_cache(search_cache_key, state)
        if cached_results:
            return state

        # 검색 실행
        search_tasks = await self._create_search_tasks(state, search_agents)
        return await self._execute_and_process_results(
            search_tasks, search_agents, search_cache_key, state
        )

    def _generate_cache_key(self, state: AgentState, search_agents: List[str]) -> str:
        """캐시 키 생성"""
        return cache_manager.make_key(
            "search_results",
            hash(state["original_query"]),
            "-".join(sorted(search_agents))
        )

    async def _check_cache(self, cache_key: str, state: AgentState) -> bool:
        """캐시된 결과 확인"""
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

    async def _create_search_tasks(self, state: AgentState, search_agents: List[str]) -> List:
        """검색 태스크 생성"""
        print("[DEBUG] Creating search tasks with MCP integration...")
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
            mcp_task = await self._create_mcp_search_task(state, tool_context)
            if mcp_task:
                search_tasks.append(mcp_task)

        # 기본 에이전트 태스크 생성
        agent_tasks = await self._create_agent_tasks(state, search_agents)
        search_tasks.extend(agent_tasks)

        return search_tasks

    async def _create_mcp_search_task(self, state: AgentState, tool_context: ToolContext):
        """MCP 검색 태스크 생성"""
        try:
            print("[DEBUG] Attempting MCP web search...")
            mcp_search_params = {
                "query": state["original_query"],
                "max_results": 10
            }

            mcp_task = self.tool_selector.select_and_execute_tool(
                "web_search",
                mcp_search_params,
                tool_context
            )
            print("[DEBUG] MCP search task created")
            return mcp_task
        except Exception as e:
            print(f"[WARNING] Failed to create MCP search task: {e}")
            return None

    def _get_agent_timeout(self, agent_name: str) -> int:
        """에이전트별 타임아웃 값 조회 (성능 최적화)"""
        return settings.AGENT_TIMEOUTS.get(agent_name, settings.AGENT_TIMEOUT)

    async def _execute_with_timeout(
        self,
        agent_name: str,
        task: Any,
        state: AgentState
    ) -> Optional[Any]:
        """개별 에이전트 타임아웃 적용하여 실행"""
        timeout = self._get_agent_timeout(agent_name)
        try:
            result = await asyncio.wait_for(task, timeout=timeout)
            logger.debug(f"에이전트 {agent_name} 완료 (타임아웃: {timeout}초)")
            return result
        except asyncio.TimeoutError:
            error_msg = f"에이전트 {agent_name} 타임아웃 ({timeout}초 초과)"
            logger.warning(error_msg)
            state["errors"].append(error_msg)
            return None
        except Exception as e:
            error_msg = f"에이전트 {agent_name} 실행 실패: {str(e)}"
            logger.error(error_msg, exc_info=True)
            state["errors"].append(error_msg)
            return e

    async def _create_agent_tasks(self, state: AgentState, search_agents: List[str]) -> List:
        """기본 에이전트 태스크 생성 (개별 타임아웃 적용)"""
        agent_tasks = []

        for agent_name in search_agents:
            try:
                timeout = self._get_agent_timeout(agent_name)
                print(f"[DEBUG] Setting up task for agent: {agent_name} (timeout: {timeout}s)")
                agent = self.agents[agent_name]
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
                    state
                )
                agent_tasks.append(task)
                print(f"[DEBUG] Task created for agent: {agent_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create task for agent {agent_name}: {e}")
                state["errors"].append(f"Failed to create task for agent {agent_name}: {str(e)}")

        return agent_tasks

    async def _execute_and_process_results(
        self,
        search_tasks: List,
        search_agents: List[str],
        cache_key: str,
        state: AgentState
    ) -> Dict[str, Any]:
        """검색 실행 및 결과 처리 (최적화된 타임아웃 적용)"""
        orchestration_timeout = settings.SEARCH_ORCHESTRATION_TIMEOUT
        print(f"[DEBUG] Executing {len(search_tasks)} search tasks (timeout: {orchestration_timeout}s)...")

        try:
            print(f"[DEBUG] Starting asyncio.gather with {orchestration_timeout}s timeout...")
            # 개별 에이전트 타임아웃이 이미 적용되어 있으므로,
            # 전체 오케스트레이션 타임아웃은 백업 안전장치 역할
            search_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=orchestration_timeout  # 설정값 사용 (기본 20초)
            )
            print(f"[DEBUG] Search execution completed, got {len(search_results)} results")

            # 결과 처리
            valid_results, mcp_results_count = await self._process_search_results(
                search_results, search_agents, state
            )

            # 캐싱
            await self._cache_results(cache_key, valid_results)

            # 실행 단계 기록
            self._record_execution_step(search_results, mcp_results_count, state)

        except asyncio.TimeoutError:
            logger.warning(f"검색 오케스트레이션 타임아웃 ({orchestration_timeout}초)")
            print(f"[ERROR] Search orchestration timed out after {orchestration_timeout} seconds")
            state["errors"].append(f"Search orchestration timed out after {orchestration_timeout} seconds")
        except Exception as e:
            print(f"[ERROR] Search orchestration failed: {str(e)}")
            state["errors"].append(f"Search orchestration failed: {str(e)}")

        return state

    async def _process_search_results(
        self,
        search_results: List,
        search_agents: List[str],
        state: AgentState
    ) -> tuple[List, int]:
        """검색 결과 처리 및 중복 제거"""
        valid_results = []
        seen_content = set()
        mcp_results_count = 0

        for i, result in enumerate(search_results):
            # MCP 결과인지 확인
            is_mcp_result = isinstance(result, tuple) and len(result) == 2

            if is_mcp_result:
                agent_results, mcp_count = self._process_mcp_result(result, state)
                mcp_results_count += mcp_count
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

        return valid_results, mcp_results_count

    def _process_mcp_result(self, result: tuple, state: AgentState) -> tuple[List, int]:
        """MCP 결과 처리"""
        mcp_result, selected_tool = result
        print(f"[DEBUG] Processing MCP result from tool: {selected_tool}")

        if mcp_result.success:
            # MCP 결과를 기존 형식으로 변환
            mcp_data = mcp_result.data
            if isinstance(mcp_data, list):
                agent_results = mcp_data
            elif isinstance(mcp_data, dict) and "results" in mcp_data:
                agent_results = mcp_data["results"]
            else:
                agent_results = []

            print(f"[DEBUG] MCP tool {selected_tool} returned {len(agent_results)} results")
            return agent_results, len(agent_results)
        else:
            print(f"[ERROR] MCP tool failed: {mcp_result.error}")
            state["errors"].append(f"MCP tool failed: {mcp_result.error}")
            return [], 0

    def _process_agent_result(
        self,
        result: Any,
        index: int,
        search_agents: List[str],
        state: AgentState
    ) -> List:
        """
        기본 에이전트 결과 처리 (개선된 에러 처리)

        에러가 발생한 경우에도 적절하게 로깅하고 상태를 업데이트하며,
        Circuit Breaker 상태를 확인합니다.
        """
        agent_index = index - (1 if any("search" in agent for agent in search_agents) else 0)

        if agent_index < len(search_agents):
            agent_name = search_agents[agent_index]
            logger.debug(f"에이전트 결과 처리 중: {agent_name} (index={index+1})")

        if isinstance(result, Exception):
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                error_msg = f"Search agent {agent_name} failed: {str(result)}"

                logger.error(error_msg, exc_info=True)

                # 에러를 state에 추가 (기존 동작 유지)
                state["errors"].append(error_msg)

                # Circuit Breaker 상태 확인
                breaker_states = AgentCircuitBreaker.get_all_states()
                if agent_name in breaker_states:
                    breaker_state = breaker_states[agent_name]
                    if breaker_state != "closed":
                        logger.warning(
                            f"⚠️ Circuit Breaker 상태: {agent_name} = {breaker_state}"
                        )
                        state["errors"].append(
                            f"Circuit breaker for {agent_name} is {breaker_state}"
                        )

            # 에러 시에도 빈 배열 반환 (graceful degradation)
            return []

        elif result.get("success"):
            agent_results = result.get("result", [])
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                logger.info(f"에이전트 {agent_name} 성공: {len(agent_results)}개 결과 반환")
            return agent_results

        else:
            # 성공하지 않은 결과
            if agent_index < len(search_agents):
                agent_name = search_agents[agent_index]
                error_detail = result.get("error", "Unknown error")

                # Circuit breaker로 인한 graceful degradation인지 확인
                if result.get("degraded"):
                    logger.warning(
                        f"⚠️ 에이전트 {agent_name} Circuit Breaker로 인해 비활성화됨: {error_detail}"
                    )
                else:
                    logger.warning(
                        f"에이전트 {agent_name} 비성공 결과: {error_detail}"
                    )

                state["errors"].append(
                    f"Agent {agent_name} unsuccessful: {error_detail}"
                )

            return []

    def _deduplicate_results(self, agent_results: List, seen_content: set) -> List:
        """결과 중복 제거"""
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
        return unique_results

    async def _cache_results(self, cache_key: str, valid_results: List) -> None:
        """결과 캐싱"""
        if valid_results:
            print(f"[DEBUG] Caching {len(valid_results)} valid search results")
            await cache_manager.set(cache_key, valid_results, ttl=1800, serialize="pickle")

    def _record_execution_step(
        self,
        search_results: List,
        mcp_results_count: int,
        state: AgentState
    ) -> None:
        """실행 단계 기록"""
        total_results = len(state["search_results"])
        successful_agents = len([r for r in search_results if not isinstance(r, Exception)])

        print(f"[DEBUG] Search orchestration completed with {total_results} total results (including {mcp_results_count} MCP results)")

        state["execution_steps"].append({
            "step": "search_orchestration",
            "result": f"completed - {successful_agents} agents/tools succeeded, MCP results: {mcp_results_count}",
            "timestamp": datetime.utcnow().isoformat()
        })
