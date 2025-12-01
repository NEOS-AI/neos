"""워크플로우 노드 실행기"""

from typing import Dict, Any, List
from datetime import datetime
import logging

from neos.workflow.state import AgentState
from neos.tools.mcp_integration import mcp_manager
from neos.workflow.agent_registry import agent_registry
from neos.utils.language_detection import detect_language
from neos.skills.manager import skill_manager
from .nodes import WorkflowNode


logger = logging.getLogger(__name__)


class NodeExecutor:
    """노드 실행기 - 각 노드 타입별 실행 로직"""

    def __init__(self, workflow_id: int = None, workflow_name: str = None):
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name

    async def execute_mcp_tool(
        self,
        node: WorkflowNode,
        state: AgentState
    ) -> Dict[str, Any]:
        """MCP 도구 실행"""
        # MCP 매니저를 통해 도구 실행
        tool_name = node.mcp_server_name
        params = node.config.copy()
        params["query"] = state.get("original_query", "")

        result = await mcp_manager.execute_tool(tool_name, params)

        return {
            "node": node.name,
            "type": "mcp_tool",
            "tool": tool_name,
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "execution_time_ms": result.execution_time_ms
        }

    async def execute_processor(
        self,
        node: WorkflowNode,
        state: AgentState
    ) -> Dict[str, Any]:
        """프로세서 노드 실행"""
        processor_type = node.config.get("processor_type", "")

        if processor_type == "result_integrator":
            # 결과 통합
            return {
                "integrated_results": {
                    "steps": state.get("execution_steps", []),
                    "timestamp": datetime.utcnow().isoformat()
                }
            }

        elif processor_type == "response_generator":
            # 최종 응답 생성
            steps = state.get("execution_steps", [])
            response = self._generate_response_from_steps(steps, state)
            return {
                "final_response": response,
                "response_metadata": {
                    "workflow_id": self.workflow_id,
                    "workflow_name": self.workflow_name,
                    "steps_count": len(steps)
                }
            }

        return {}

    def _generate_response_from_steps(
        self,
        steps: List[Dict[str, Any]],
        state: AgentState
    ) -> str:
        """실행 스텝으로부터 응답 생성"""
        response_parts = []

        for step in steps:
            if step.get("success") and step.get("data"):
                data = step["data"]
                if isinstance(data, list):
                    for item in data[:3]:  # 최대 3개만
                        if isinstance(item, dict):
                            response_parts.append(f"- {item.get('title', '')}: {item.get('content', '')[:200]}")
                elif isinstance(data, dict):
                    response_parts.append(f"- {data}")

        if not response_parts:
            return "워크플로우 실행이 완료되었지만 유효한 결과를 찾을 수 없습니다."

        return "\n".join(response_parts)

    async def execute_agent(
        self,
        node: WorkflowNode,
        state: AgentState
    ) -> Dict[str, Any]:
        """에이전트 노드 실행"""
        start_time = datetime.utcnow()

        # 노드 설정에서 에이전트 이름 가져오기
        agent_name = node.config.get("agent_name", "")

        if not agent_name:
            return {
                "node": node.name,
                "type": "agent",
                "success": False,
                "error": "agent_name not specified in node config",
                "execution_time_ms": 0
            }

        # 에이전트 레지스트리에서 에이전트 가져오기
        agent = agent_registry.get_agent(agent_name)

        if not agent:
            return {
                "node": node.name,
                "type": "agent",
                "agent_name": agent_name,
                "success": False,
                "error": f"Agent '{agent_name}' not found in registry",
                "execution_time_ms": 0
            }

        try:
            # 쿼리 준비
            query = state.get("original_query", "")

            # 언어 감지
            detected_language = state.get("detected_language")
            if not detected_language:
                detected_language = detect_language(query)

            # 에이전트 실행을 위한 컨텍스트 준비
            context = {
                "user_id": state.get("user_id", ""),
                "session_id": state.get("session_id", ""),
                "detected_language": detected_language,
                **node.config.get("context", {})  # 추가 컨텍스트
            }

            # 에이전트 실행
            logger.info(f"Executing agent '{agent_name}' with query: {query[:50]}...")
            agent_result = await agent.execute(query, context)

            # 실행 시간 계산
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # 결과 처리
            if agent_result.get("success"):
                results = agent_result.get("results", [])

                # 결과 포맷팅
                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "title": result.get("title", ""),
                        "content": result.get("content", ""),
                        "url": result.get("url", ""),
                        "score": result.get("score", 0.0),
                        "metadata": result.get("metadata", {})
                    })

                return {
                    "node": node.name,
                    "type": "agent",
                    "agent_name": agent_name,
                    "success": True,
                    "data": formatted_results,
                    "metadata": agent_result.get("metadata", {}),
                    "execution_time_ms": execution_time_ms
                }
            else:
                return {
                    "node": node.name,
                    "type": "agent",
                    "agent_name": agent_name,
                    "success": False,
                    "error": agent_result.get("error", "Unknown agent error"),
                    "execution_time_ms": execution_time_ms
                }

        except Exception as e:
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.error(f"Error executing agent '{agent_name}': {e}")
            return {
                "node": node.name,
                "type": "agent",
                "agent_name": agent_name,
                "success": False,
                "error": str(e),
                "execution_time_ms": execution_time_ms
            }

    async def execute_skill(
        self,
        node: WorkflowNode,
        state: AgentState
    ) -> Dict[str, Any]:
        """스킬 노드 실행"""
        start_time = datetime.utcnow()

        # 노드 설정에서 스킬 이름 가져오기
        skill_name = node.config.get("skill_name", "")

        if not skill_name:
            return {
                "node": node.name,
                "type": "skill",
                "success": False,
                "error": "skill_name not specified in node config",
                "execution_time_ms": 0
            }

        try:
            # 스킬 실행을 위한 파라미터 준비
            params = node.config.get("params", {})

            # state에서 동적 파라미터 가져오기
            if "query" in params and params["query"] == "${state.query}":
                params["query"] = state.get("original_query", "")

            if "content" in params and params["content"] == "${state.content}":
                params["content"] = state.get("content", "")

            # 스킬 실행
            logger.info(f"Executing skill '{skill_name}' with params: {params}")
            result = await skill_manager.execute_skill(skill_name, params)

            # 실행 시간 계산
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # 결과 처리
            if result.success:
                return {
                    "node": node.name,
                    "type": "skill",
                    "skill_name": skill_name,
                    "success": True,
                    "data": result.data,
                    "metadata": result.metadata,
                    "execution_time_ms": execution_time_ms
                }
            else:
                return {
                    "node": node.name,
                    "type": "skill",
                    "skill_name": skill_name,
                    "success": False,
                    "error": result.error,
                    "execution_time_ms": execution_time_ms
                }

        except Exception as e:
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.error(f"Error executing skill '{skill_name}': {e}")
            return {
                "node": node.name,
                "type": "skill",
                "skill_name": skill_name,
                "success": False,
                "error": str(e),
                "execution_time_ms": execution_time_ms
            }
