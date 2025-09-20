"""생성 오케스트레이터 모듈"""

from typing import Dict, Any, List
from datetime import datetime
import asyncio

from ..state import AgentState


class GenerationOrchestrator:
    """생성 에이전트들 오케스트레이션"""

    def __init__(self, agents: Dict[str, Any], config):
        self.agents = agents
        self.config = config

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
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

        print(f"[DEBUG] Starting generation orchestration with {len(generation_agents)} agents...")

        # 생성 태스크 생성
        generation_tasks = self._create_generation_tasks(state, generation_agents)

        # 생성 실행 및 결과 처리
        return await self._execute_and_process_results(
            generation_tasks, generation_agents, state
        )

    def _create_generation_tasks(self, state: AgentState, generation_agents: List[str]) -> List:
        """생성 태스크 생성"""
        generation_tasks = []

        for agent_name in generation_agents:
            try:
                print(f"[DEBUG] Setting up generation task for agent: {agent_name}")
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
                print(f"[DEBUG] Generation task created for agent: {agent_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create generation task for agent {agent_name}: {e}")
                state["errors"].append(f"Failed to create generation task for agent {agent_name}: {str(e)}")

        return generation_tasks

    async def _execute_and_process_results(
        self,
        generation_tasks: List,
        generation_agents: List[str],
        state: AgentState
    ) -> Dict[str, Any]:
        """생성 실행 및 결과 처리"""
        if not generation_tasks:
            print("[DEBUG] No generation tasks to execute")
            return state

        try:
            print(f"[DEBUG] Executing {len(generation_tasks)} generation tasks...")
            generation_results = await asyncio.gather(*generation_tasks, return_exceptions=True)
            print(f"[DEBUG] Generation execution completed, got {len(generation_results)} results")

            # 결과 처리
            successful_count = self._process_generation_results(
                generation_results, generation_agents, state
            )

            # 실행 단계 기록
            self._record_execution_step(successful_count, state)

        except Exception as e:
            print(f"[ERROR] Generation orchestration failed: {str(e)}")
            state["errors"].append(f"Generation orchestration failed: {str(e)}")

        return state

    def _process_generation_results(
        self,
        generation_results: List,
        generation_agents: List[str],
        state: AgentState
    ) -> int:
        """생성 결과 처리"""
        successful_count = 0

        for i, result in enumerate(generation_results):
            agent_name = generation_agents[i] if i < len(generation_agents) else f"agent_{i}"

            if isinstance(result, Exception):
                print(f"[ERROR] Generation agent {agent_name} failed: {str(result)}")
                state["errors"].append(f"Generation agent {agent_name} failed: {str(result)}")
            elif result and result.get("success"):
                print(f"[DEBUG] Generation agent {agent_name} succeeded")
                state["generation_results"].append(result.get("result"))
                successful_count += 1
            else:
                print(f"[WARNING] Generation agent {agent_name} returned unsuccessful result: {result}")
                state["errors"].append(f"Generation agent {agent_name} returned unsuccessful result")

        return successful_count

    def _record_execution_step(self, successful_count: int, state: AgentState) -> None:
        """실행 단계 기록"""
        print(f"[DEBUG] Generation orchestration completed, {successful_count} agents succeeded")

        state["execution_steps"].append({
            "step": "generation_orchestration",
            "result": f"completed - {successful_count} agents succeeded",
            "timestamp": datetime.utcnow().isoformat()
        })