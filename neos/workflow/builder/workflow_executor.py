"""커스텀 워크플로우 실행기"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from neos.database.connection import db_manager
from neos.database.workflow_models import (
    CustomWorkflow,
    WorkflowExecution,
    WorkflowStatus
)
from neos.workflow.state import AgentState
from .nodes import WorkflowNode, WorkflowEdge
from .executors import NodeExecutor


logger = logging.getLogger(__name__)


def _is_custom_workflow_harness_blocked(final_state: Dict[str, Any] | None) -> bool:
    if not final_state:
        return False
    return (
        str(final_state.get("harness_mode") or "").lower() == "gate"
        and str(final_state.get("harness_verdict") or "").lower()
        in {"fail", "needs_repair"}
    )


class WorkflowExecutor:
    """커스텀 워크플로우 실행기"""

    def __init__(self, workflow_id: int):
        self.workflow_id = workflow_id
        self.workflow_data: Optional[CustomWorkflow] = None
        self.graph: Optional[StateGraph] = None
        self.node_handlers: Dict[str, Callable] = {}
        self.node_executor: Optional[NodeExecutor] = None

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

            # NodeExecutor 초기화
            self.node_executor = NodeExecutor(
                workflow_id=self.workflow_id,
                workflow_name=self.workflow_data.name
            )

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
                    result = await self.node_executor.execute_mcp_tool(node, state)
                    return {"execution_steps": state["execution_steps"] + [result]}

                elif node.node_type == "processor":
                    # 프로세서 노드 실행
                    result = await self.node_executor.execute_processor(node, state)
                    return result

                elif node.node_type == "agent":
                    # 에이전트 노드 실행
                    result = await self.node_executor.execute_agent(node, state)
                    return {"execution_steps": state["execution_steps"] + [result]}

                elif node.node_type == "skill":
                    # 스킬 노드 실행
                    result = await self.node_executor.execute_skill(node, state)
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

    async def execute(
        self,
        user_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """워크플로우 실행"""
        start_time = datetime.now()

        # 그래프 빌드 (아직 안 되어있으면)
        if not self.graph:
            await self.build_graph()

        # 초기 상태 생성
        initial_state = self._create_initial_state(user_input)

        try:
            # 워크플로우 실행
            config = {"configurable": {"thread_id": user_input["session_id"]}}
            final_state = await self.graph.ainvoke(initial_state, config)

            # 실행 시간 계산
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # 실행 기록 저장
            await self._save_execution(
                user_input=user_input,
                final_state=final_state,
                execution_time_ms=execution_time_ms,
                success=True
            )

            # 워크플로우 실행 횟수 업데이트
            await self._update_execution_count()

            if _is_custom_workflow_harness_blocked(final_state):
                return {
                    "success": False,
                    "response": "검증 중 일부 핵심 조건을 만족하지 못해 최종 결과로 확정하지 않았습니다.",
                    "blocked_response": final_state.get("final_response", ""),
                    "metadata": final_state.get("response_metadata", {}),
                    "execution_time_ms": execution_time_ms,
                    "workflow_id": self.workflow_id,
                    "workflow_name": self.workflow_data.name,
                    "errors": list(final_state.get("errors", []))
                    + ["research_harness_gate_failed"],
                }

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
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

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

    def _create_initial_state(self, user_input: Dict[str, Any]) -> AgentState:
        """Create the initial state for custom workflow execution."""
        initial_state = AgentState(
            user_id=user_input["user_id"],
            session_id=user_input["session_id"],
            original_query=user_input["query"],
            query_intent=None,
            query_embedding=None,
            detected_language=None,
            # 채팅 히스토리 관련 (하위 호환성 유지 - Optional)
            chat_history=user_input.get("chat_history"),
            conversation_context=None,  # Context Processor가 채울 예정
            enable_history_context=user_input.get("enable_history_context", False),
            history_metadata=None,
            query_classification=None,
            required_agents=[],
            search_results=[],
            analysis_results=[],
            generation_results=[],
            integrated_results=None,
            quality_score=None,
            quality_feedback=None,
            harness_mode=None,
            harness_contract={},
            harness_runs=[],
            harness_verdict=None,
            harness_score=None,
            harness_failed_checks=[],
            harness_repair_plan=None,
            harness_repair_attempts=0,
            harness_metadata={},
            final_response=None,
            response_metadata=None,
            execution_start=datetime.now(),
            execution_steps=[],
            errors=[],
            retry_count=0,
            execution_time_ms=None,
            tokens_used=None,
            api_calls_made=None
        )
        return initial_state

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
                completed_at=datetime.now()
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
                workflow.last_executed_at = datetime.now()
                await session.commit()
