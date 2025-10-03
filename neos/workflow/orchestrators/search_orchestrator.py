"""검색 오케스트레이터 모듈"""

from typing import Dict, Any, List
from datetime import datetime
import asyncio

from neos.utils.cache import cache_manager
from neos.tools.tool_selector import ToolContext

from ..state import AgentState


class SearchOrchestrator:
    """검색 에이전트들 오케스트레이션"""

    def __init__(self, agents: Dict[str, Any], config, tool_selector):
        self.agents = agents
        self.config = config
        self.tool_selector = tool_selector

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
        """검색 에이전트들 오케스트레이션 (MCP 통합)"""
        print("[DEBUG] Starting search orchestration with MCP integration...")
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

        # MCP 도구 선택기 초기화 (필요시)
        if not self.tool_selector.initialized:
            print("[DEBUG] Initializing tool selector...")
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

    async def _create_agent_tasks(self, state: AgentState, search_agents: List[str]) -> List:
        """기본 에이전트 태스크 생성"""
        agent_tasks = []

        for agent_name in search_agents:
            try:
                print(f"[DEBUG] Setting up task for agent: {agent_name}")
                agent = self.agents[agent_name]
                context = {
                    "user_id": state["user_id"],
                    "session_id": state["session_id"],
                    "query_embedding": state.get("query_embedding"),
                    "query_intent": state.get("query_intent"),
                    "detected_language": state.get("detected_language")
                }
                task = agent.execute(state["original_query"], context)
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
        """검색 실행 및 결과 처리"""
        print(f"[DEBUG] Executing {len(search_tasks)} search tasks...")

        try:
            print("[DEBUG] Starting asyncio.gather with 120s timeout...")
            search_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=120  # 2 minutes timeout for search
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
            print("[ERROR] Search orchestration timed out after 2 minutes")
            state["errors"].append("Search orchestration timed out after 2 minutes")
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
        """기본 에이전트 결과 처리"""
        agent_index = index - (1 if any("search" in agent for agent in search_agents) else 0)

        if agent_index < len(search_agents):
            agent_name = search_agents[agent_index]
            print(f"[DEBUG] Processing result {index+1} from agent {agent_name}")

        if isinstance(result, Exception):
            if agent_index < len(search_agents):
                print(f"[ERROR] Search agent {search_agents[agent_index]} failed: {str(result)}")
                state["errors"].append(f"Search agent {search_agents[agent_index]} failed: {str(result)}")
            return []
        elif result.get("success"):
            agent_results = result.get("result", [])
            if agent_index < len(search_agents):
                print(f"[DEBUG] Agent {search_agents[agent_index]} returned {len(agent_results)} results")
            return agent_results
        else:
            if agent_index < len(search_agents):
                print(f"[WARNING] Agent {search_agents[agent_index]} returned unsuccessful result: {result}")
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
