"""커스텀 워크플로우 빌더 클래스"""

from typing import Dict, Any, List, Optional
import logging

from neos.database.connection import db_manager
from neos.database.workflow_models import (
    CustomWorkflow,
    WorkflowMCPServer,
    WorkflowStatus
)
from .nodes import WorkflowNode, WorkflowEdge


logger = logging.getLogger(__name__)


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
