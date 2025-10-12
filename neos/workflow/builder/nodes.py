"""워크플로우 노드와 엣지 정의"""

from typing import Dict, Any, Optional, Callable


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
