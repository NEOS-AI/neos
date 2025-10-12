"""커스텀 워크플로우 빌더"""

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session
from sqlalchemy import select

from neos.database.connection import db_manager
from neos.database.workflow_models import (
    CustomWorkflow,
    WorkflowMCPServer,
    WorkflowExecution,
    MCPServer,
    WorkflowStatus
)
from neos.workflow.state import AgentState
from neos.tools.mcp_integration import mcp_manager, MCPToolResult
from neos.workflow.agent_registry import agent_registry
from neos.utils.language_detection import detect_language


logger = logging.getLogger(__name__)


class WorkflowNode:
    """워크플로우 노드 정의"""

    def __init__(
        self,
        name: str,
        node_type: str,
        config: Dict[str, Any] = None,
        mcp_server_name: Optional[str] = None
    ):
        self.name = name
        self.node_type = node_type  # 'agent', 'mcp_tool', 'processor', 'conditional'
        self.config = config or {}
        self.mcp_server_name = mcp_server_name
        self.handler: Optional[Callable] = None

    def to_dict(self) -> Dict[str, Any]:
        """노드를 딕셔너리로 변환"""
        return {
            "name": self.name,
            "type": self.node_type,
            "config": self.config,
            "mcp_server": self.mcp_server_name
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        """딕셔너리로부터 노드 생성"""
        return cls(
            name=data["name"],
            node_type=data["type"],
            config=data.get("config", {}),
            mcp_server_name=data.get("mcp_server")
        )


class WorkflowEdge:
    """워크플로우 엣지 정의"""

    def __init__(
        self,
        from_node: str,
        to_node: str,
        condition: Optional[str] = None
    ):
        self.from_node = from_node
        self.to_node = to_node
        self.condition = condition  # 조건부 엣지인 경우 조건 함수명

    def to_dict(self) -> Dict[str, Any]:
        """엣지를 딕셔너리로 변환"""
        return {
            "from": self.from_node,
            "to": self.to_node,
            "condition": self.condition
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEdge":
        """딕셔너리로부터 엣지 생성"""
        return cls(
            from_node=data["from"],
            to_node=data["to"],
            condition=data.get("condition")
        )


class CustomWorkflowBuilder:
    """커스텀 워크플로우 빌더"""

    def __init__(self):
        self.nodes: List[WorkflowNode] = []
        self.edges: List[WorkflowEdge] = []
        self.mcp_servers: Dict[str, int] = {}  # {server_name: server_id}
        self.config: Dict[str, Any] = {}
        self.entry_point: Optional[str] = None

    def add_node(
        self,
        name: str,
        node_type: str,
        config: Dict[str, Any] = None,
        mcp_server_name: Optional[str] = None
    ) -> "CustomWorkflowBuilder":
        """노드 추가"""
        node = WorkflowNode(name, node_type, config, mcp_server_name)
        self.nodes.append(node)

        # 첫 번째 노드를 자동으로 entry point로 설정
        if not self.entry_point:
            self.entry_point = name

        logger.info(f"Added node: {name} (type: {node_type})")
        return self

    def add_edge(
        self,
        from_node: str,
        to_node: str,
        condition: Optional[str] = None
    ) -> "CustomWorkflowBuilder":
        """엣지 추가"""
        edge = WorkflowEdge(from_node, to_node, condition)
        self.edges.append(edge)
        logger.info(f"Added edge: {from_node} -> {to_node}")
        return self

    def set_entry_point(self, node_name: str) -> "CustomWorkflowBuilder":
        """엔트리 포인트 설정"""
        if not any(node.name == node_name for node in self.nodes):
            raise ValueError(f"Node {node_name} not found in workflow")
        self.entry_point = node_name
        logger.info(f"Set entry point: {node_name}")
        return self

    def add_mcp_server(
        self,
        server_name: str,
        server_id: int
    ) -> "CustomWorkflowBuilder":
        """MCP 서버 추가"""
        self.mcp_servers[server_name] = server_id
        logger.info(f"Added MCP server: {server_name} (ID: {server_id})")
        return self

    def set_config(self, config: Dict[str, Any]) -> "CustomWorkflowBuilder":
        """워크플로우 설정"""
        self.config = config
        return self

    async def save(
        self,
        name: str,
        description: str,
        created_by: str,
        tags: List[str] = None
    ) -> int:
        """워크플로우를 데이터베이스에 저장"""
        async with db_manager.get_session() as session:
            # 워크플로우 생성
            workflow = CustomWorkflow(
                name=name,
                description=description,
                created_by=created_by,
                config=self.config,
                nodes=[node.to_dict() for node in self.nodes],
                edges=[edge.to_dict() for edge in self.edges],
                status=WorkflowStatus.DRAFT,
                tags=tags or []
            )

            session.add(workflow)
            await session.flush()  # workflow.id를 얻기 위해

            # MCP 서버 연결 정보 저장
            for node in self.nodes:
                if node.mcp_server_name and node.mcp_server_name in self.mcp_servers:
                    workflow_server = WorkflowMCPServer(
                        workflow_id=workflow.id,
                        mcp_server_id=self.mcp_servers[node.mcp_server_name],
                        node_name=node.name,
                        tool_config=node.config
                    )
                    session.add(workflow_server)

            await session.commit()
            logger.info(f"Saved workflow: {name} (ID: {workflow.id})")
            return workflow.id

    def to_dict(self) -> Dict[str, Any]:
        """워크플로우 정의를 딕셔너리로 변환"""
        return {
            "config": self.config,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "entry_point": self.entry_point,
            "mcp_servers": self.mcp_servers
        }


class WorkflowExecutor:
    """커스텀 워크플로우 실행기"""

    def __init__(self, workflow_id: int):
        self.workflow_id = workflow_id
        self.workflow_data: Optional[CustomWorkflow] = None
        self.graph: Optional[StateGraph] = None
        self.node_handlers: Dict[str, Callable] = {}

    async def load_workflow(self) -> None:
        """워크플로우 데이터 로드"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == self.workflow_id)
            )
            self.workflow_data = result.scalar_one_or_none()

            if not self.workflow_data:
                raise ValueError(f"Workflow {self.workflow_id} not found")

            if self.workflow_data.status != WorkflowStatus.ACTIVE:
                logger.warning(f"Workflow {self.workflow_id} is not active (status: {self.workflow_data.status})")

            logger.info(f"Loaded workflow: {self.workflow_data.name}")

    async def build_graph(self) -> StateGraph:
        """워크플로우 그래프 빌드"""
        if not self.workflow_data:
            await self.load_workflow()

        # StateGraph 생성
        workflow = StateGraph(AgentState)

        # 노드 추가
        for node_data in self.workflow_data.nodes:
            node = WorkflowNode.from_dict(node_data)
            handler = await self._create_node_handler(node)
            self.node_handlers[node.name] = handler
            workflow.add_node(node.name, handler)
            logger.info(f"Added node to graph: {node.name}")

        # 엔트리 포인트 설정
        if self.workflow_data.nodes:
            first_node = self.workflow_data.nodes[0]["name"]
            workflow.set_entry_point(first_node)
            logger.info(f"Set entry point: {first_node}")

        # 엣지 추가
        for edge_data in self.workflow_data.edges:
            edge = WorkflowEdge.from_dict(edge_data)

            if edge.condition:
                # 조건부 엣지 (현재는 간단히 구현)
                logger.warning(f"Conditional edges not fully implemented: {edge.condition}")
                workflow.add_edge(edge.from_node, edge.to_node)
            else:
                # 일반 엣지
                if edge.to_node == "END":
                    workflow.add_edge(edge.from_node, END)
                else:
                    workflow.add_edge(edge.from_node, edge.to_node)

            logger.info(f"Added edge to graph: {edge.from_node} -> {edge.to_node}")

        self.graph = workflow.compile(checkpointer=MemorySaver())
        logger.info("Workflow graph built successfully")
        return self.graph

    async def _create_node_handler(self, node: WorkflowNode) -> Callable:
        """노드 핸들러 생성"""

        async def handler(state: AgentState) -> Dict[str, Any]:
            """실제 노드 실행 함수"""
            logger.info(f"Executing node: {node.name} (type: {node.node_type})")

            try:
                if node.node_type == "mcp_tool" and node.mcp_server_name:
                    # MCP 도구 실행
                    result = await self._execute_mcp_tool(node, state)
                    return {"execution_steps": state["execution_steps"] + [result]}

                elif node.node_type == "processor":
                    # 프로세서 노드 실행
                    result = await self._execute_processor(node, state)
                    return result

                elif node.node_type == "agent":
                    # 에이전트 노드 실행
                    result = await self._execute_agent(node, state)
                    return {"execution_steps": state["execution_steps"] + [result]}

                else:
                    logger.warning(f"Unknown node type: {node.node_type}")
                    return {}

            except Exception as e:
                logger.error(f"Error executing node {node.name}: {e}")
                return {
                    "errors": state["errors"] + [{"node": node.name, "error": str(e)}]
                }

        return handler

    async def _execute_mcp_tool(
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

    async def _execute_processor(
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
                    "workflow_name": self.workflow_data.name,
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


    async def _execute_agent(
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

    async def execute(
        self,
        user_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """워크플로우 실행"""
        start_time = datetime.utcnow()

        # 그래프 빌드 (아직 안 되어있으면)
        if not self.graph:
            await self.build_graph()

        # 초기 상태 생성
        initial_state = AgentState(
            user_id=user_input["user_id"],
            session_id=user_input["session_id"],
            original_query=user_input["query"],
            query_intent=None,
            query_embedding=None,
            detected_language=None,
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
            execution_start=start_time,
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

            # 실행 시간 계산
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # 실행 기록 저장
            await self._save_execution(
                user_input=user_input,
                final_state=final_state,
                execution_time_ms=execution_time_ms,
                success=True
            )

            # 워크플로우 실행 횟수 업데이트
            await self._update_execution_count()

            return {
                "success": True,
                "response": final_state.get("final_response", ""),
                "metadata": final_state.get("response_metadata", {}),
                "execution_time_ms": execution_time_ms,
                "workflow_id": self.workflow_id,
                "workflow_name": self.workflow_data.name,
                "errors": final_state.get("errors", [])
            }

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # 실패 기록 저장
            await self._save_execution(
                user_input=user_input,
                final_state=initial_state,
                execution_time_ms=execution_time_ms,
                success=False,
                error_message=str(e)
            )

            return {
                "success": False,
                "error": str(e),
                "execution_time_ms": execution_time_ms,
                "workflow_id": self.workflow_id
            }

    async def _save_execution(
        self,
        user_input: Dict[str, Any],
        final_state: AgentState,
        execution_time_ms: int,
        success: bool,
        error_message: Optional[str] = None
    ) -> None:
        """실행 기록 저장"""
        async with db_manager.get_session() as session:
            execution = WorkflowExecution(
                workflow_id=self.workflow_id,
                user_id=user_input["user_id"],
                session_id=user_input["session_id"],
                input_query=user_input["query"],
                output=final_state.get("final_response"),
                success=success,
                error_message=error_message,
                execution_time_ms=execution_time_ms,
                execution_steps=final_state.get("execution_steps", []),
                completed_at=datetime.utcnow()
            )
            session.add(execution)
            await session.commit()

    async def _update_execution_count(self) -> None:
        """워크플로우 실행 횟수 업데이트"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == self.workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if workflow:
                workflow.execution_count += 1
                workflow.last_executed_at = datetime.utcnow()
                await session.commit()


class WorkflowManager:
    """워크플로우 관리자"""

    @staticmethod
    async def list_workflows(
        status: Optional[WorkflowStatus] = None,
        created_by: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """워크플로우 목록 조회"""
        async with db_manager.get_session() as session:
            query = select(CustomWorkflow)

            if status:
                query = query.where(CustomWorkflow.status == status)
            if created_by:
                query = query.where(CustomWorkflow.created_by == created_by)

            result = await session.execute(query)
            workflows = result.scalars().all()

            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "status": w.status.value,
                    "created_by": w.created_by,
                    "execution_count": w.execution_count,
                    "created_at": w.created_at.isoformat(),
                    "nodes_count": len(w.nodes),
                    "tags": w.tags
                }
                for w in workflows
            ]

    @staticmethod
    async def get_workflow(workflow_id: int) -> Optional[Dict[str, Any]]:
        """특정 워크플로우 조회"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return None

            return {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status.value,
                "created_by": workflow.created_by,
                "config": workflow.config,
                "nodes": workflow.nodes,
                "edges": workflow.edges,
                "execution_count": workflow.execution_count,
                "last_executed_at": workflow.last_executed_at.isoformat() if workflow.last_executed_at else None,
                "created_at": workflow.created_at.isoformat(),
                "tags": workflow.tags
            }

    @staticmethod
    async def update_workflow_status(
        workflow_id: int,
        status: WorkflowStatus
    ) -> bool:
        """워크플로우 상태 업데이트"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return False

            workflow.status = status
            workflow.updated_at = datetime.utcnow()
            await session.commit()
            return True

    @staticmethod
    async def delete_workflow(workflow_id: int) -> bool:
        """워크플로우 삭제"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return False

            await session.delete(workflow)
            await session.commit()
            return True
