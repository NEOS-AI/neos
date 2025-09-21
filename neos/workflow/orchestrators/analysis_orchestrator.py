"""분석 오케스트레이터 모듈"""

from typing import Dict, Any, List
from datetime import datetime
import asyncio

from ..state import AgentState


class AnalysisOrchestrator:
    """분석 에이전트들 오케스트레이션"""

    def __init__(self, agents: Dict[str, Any], config):
        self.agents = agents
        self.config = config

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
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

        print(f"[DEBUG] Starting analysis orchestration with {len(analysis_agents)} agents...")

        # 분석 태스크 생성
        analysis_tasks = self._create_analysis_tasks(state, analysis_agents)

        # 분석 실행 및 결과 처리
        return await self._execute_and_process_results(
            analysis_tasks, analysis_agents, state
        )

    def _create_analysis_tasks(self, state: AgentState, analysis_agents: List[str]) -> List:
        """분석 태스크 생성"""
        analysis_tasks = []

        for agent_name in analysis_agents:
            try:
                print(f"[DEBUG] Setting up analysis task for agent: {agent_name}")
                agent = self.agents[agent_name]
                context = {
                    "user_id": state["user_id"],
                    "session_id": state["session_id"],
                    "search_results": state["search_results"],
                    "query_intent": state.get("query_intent")
                }
                task = agent.execute(state["original_query"], context)
                analysis_tasks.append(task)
                print(f"[DEBUG] Analysis task created for agent: {agent_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create analysis task for agent {agent_name}: {e}")
                state["errors"].append(f"Failed to create analysis task for agent {agent_name}: {str(e)}")

        return analysis_tasks

    async def _execute_and_process_results(
        self,
        analysis_tasks: List,
        analysis_agents: List[str],
        state: AgentState
    ) -> Dict[str, Any]:
        """분석 실행 및 결과 처리"""
        if not analysis_tasks:
            print("[DEBUG] No analysis tasks to execute")
            return state

        try:
            print(f"[DEBUG] Executing {len(analysis_tasks)} analysis tasks...")
            analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            print(f"[DEBUG] Analysis execution completed, got {len(analysis_results)} results")

            # 결과 처리
            successful_count = self._process_analysis_results(
                analysis_results, analysis_agents, state
            )

            # 실행 단계 기록
            self._record_execution_step(successful_count, state)

        except Exception as e:
            print(f"[ERROR] Analysis orchestration failed: {str(e)}")
            state["errors"].append(f"Analysis orchestration failed: {str(e)}")

        return state

    def _process_analysis_results(
        self,
        analysis_results: List,
        analysis_agents: List[str],
        state: AgentState
    ) -> int:
        """분석 결과 처리"""
        successful_count = 0

        for i, result in enumerate(analysis_results):
            agent_name = analysis_agents[i] if i < len(analysis_agents) else f"agent_{i}"

            if isinstance(result, Exception):
                print(f"[ERROR] Analysis agent {agent_name} failed: {str(result)}")
                state["errors"].append(f"Analysis agent {agent_name} failed: {str(result)}")
            elif result and result.get("success"):
                print(f"[DEBUG] Analysis agent {agent_name} succeeded")
                state["analysis_results"].append(result.get("result"))
                successful_count += 1
            else:
                print(f"[WARNING] Analysis agent {agent_name} returned unsuccessful result: {result}")
                state["errors"].append(f"Analysis agent {agent_name} returned unsuccessful result")

        return successful_count

    def _record_execution_step(self, successful_count: int, state: AgentState) -> None:
        """실행 단계 기록"""
        print(f"[DEBUG] Analysis orchestration completed, {successful_count} agents succeeded")

        state["execution_steps"].append({
            "step": "analysis_orchestration",
            "result": f"completed - {successful_count} agents succeeded",
            "timestamp": datetime.utcnow().isoformat()
        })
