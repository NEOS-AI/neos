"""커스텀 워크플로우 데이터베이스 모델"""

from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from .connection import Base


class WorkflowStatus(enum.Enum):
    """워크플로우 상태"""
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class MCPServer(Base):
    """MCP 서버 정보"""
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    url = Column(String(512), nullable=False)
    description = Column(Text)
    server_type = Column(String(100))  # 'web_search', 'file_processing', 'database', etc.
    config = Column(JSONB, default=dict)  # 서버 설정 (API keys, credentials 등)
    capabilities = Column(JSONB, default=list)  # 서버가 제공하는 기능 목록
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    workflow_servers = relationship("WorkflowMCPServer", back_populates="mcp_server")


class CustomWorkflow(Base):
    """커스텀 워크플로우"""
    __tablename__ = "custom_workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    created_by = Column(String(255), nullable=False)  # user_id

    # 워크플로우 설정
    config = Column(JSONB, default=dict)  # 워크플로우 전체 설정
    nodes = Column(JSONB, default=list)  # 노드 정의 [{name, type, config}, ...]
    edges = Column(JSONB, default=list)  # 엣지 정의 [{from, to, condition}, ...]

    # 상태 및 메타데이터
    status = Column(SQLEnum(WorkflowStatus), default=WorkflowStatus.DRAFT)
    version = Column(Integer, default=1)
    tags = Column(JSONB, default=list)

    # 사용 통계
    execution_count = Column(Integer, default=0)
    last_executed_at = Column(TIMESTAMP)

    # 시간 정보
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    workflow_servers = relationship("WorkflowMCPServer", back_populates="workflow", cascade="all, delete-orphan")
    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowMCPServer(Base):
    """워크플로우와 MCP 서버 간의 관계"""
    __tablename__ = "workflow_mcp_servers"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("custom_workflows.id"), nullable=False)
    mcp_server_id = Column(Integer, ForeignKey("mcp_servers.id"), nullable=False)

    # 워크플로우 내에서 이 MCP 서버를 사용하는 설정
    node_name = Column(String(255))  # 어떤 노드에서 사용되는지
    tool_config = Column(JSONB, default=dict)  # 이 워크플로우에서 사용되는 특정 설정

    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    # 관계
    workflow = relationship("CustomWorkflow", back_populates="workflow_servers")
    mcp_server = relationship("MCPServer", back_populates="workflow_servers")


class WorkflowExecution(Base):
    """워크플로우 실행 기록"""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("custom_workflows.id"), nullable=False)

    # 실행 정보
    user_id = Column(String(255), nullable=False)
    session_id = Column(String(255), nullable=False)
    input_query = Column(Text, nullable=False)

    # 실행 결과
    output = Column(JSONB)
    success = Column(Boolean, default=False)
    error_message = Column(Text)

    # 성능 메트릭
    execution_time_ms = Column(Integer)
    tokens_used = Column(Integer)
    quality_score = Column(Integer)

    # 실행 세부사항
    execution_steps = Column(JSONB, default=list)  # 각 노드별 실행 정보
    mcp_calls = Column(JSONB, default=list)  # 호출된 MCP 서버 정보

    # 시간 정보
    started_at = Column(TIMESTAMP, default=datetime.utcnow)
    completed_at = Column(TIMESTAMP)

    # 관계
    workflow = relationship("CustomWorkflow", back_populates="executions")
