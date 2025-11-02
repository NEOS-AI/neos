"""Database MCP tool implementation"""

from datetime import datetime
from typing import Any, Dict
import logging

from neos.tools.base import MCPTool, MCPToolResult, MCPToolType


logger = logging.getLogger(__name__)


class DatabaseMCPTool(MCPTool):
    """데이터베이스 MCP 도구

    안전한 데이터베이스 작업 기능을 제공합니다. (읽기 전용)

    Capabilities:
        - query_execution: 쿼리 실행 (SELECT only)
        - schema_inspection: 스키마 조회
        - data_export: 데이터 내보내기
    """

    def __init__(self):
        super().__init__(
            name="database_mcp",
            tool_type=MCPToolType.DATA_ANALYSIS,
            description="MCP를 통한 데이터베이스 작업 도구 (읽기 전용)",
            capabilities=["query_execution", "schema_inspection", "data_export"],
        )
        self.connection = None

    async def initialize(self) -> bool:
        """데이터베이스 연결 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            from neos.database.connection import db_manager

            self.connection = db_manager
            logger.info("Database MCP tool initialized")
            self.is_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Database MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """데이터베이스 작업 실행

        Args:
            params: 작업 파라미터
                - operation (str, required): 작업 타입 (health_check/query)
                - query (str, optional): SQL 쿼리 (operation=query일 때)

        Returns:
            MCPToolResult: 작업 결과
        """
        start_time = datetime.now()

        try:
            operation = params.get("operation", "")
            if not operation:
                return MCPToolResult.from_error(
                    error="Operation parameter is required",
                    tool_name=self.name,
                )

            if operation == "health_check":
                return await self._health_check(start_time)

            elif operation == "query":
                return await self._execute_query(params, start_time)

            else:
                return MCPToolResult.from_error(
                    error=f"Unsupported operation: {operation}",
                    tool_name=self.name,
                )

        except Exception as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            return MCPToolResult.from_error(
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time,
            )

    async def _health_check(self, start_time: datetime) -> MCPToolResult:
        """데이터베이스 상태 확인"""
        health = await self.connection.health_check()
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return MCPToolResult.from_success(
            data={"healthy": health, "timestamp": datetime.now().isoformat()},
            tool_name=self.name,
            execution_time_ms=execution_time,
        )

    async def _execute_query(
        self, params: Dict[str, Any], start_time: datetime
    ) -> MCPToolResult:
        """쿼리 실행 (안전 모드)"""
        query = params.get("query", "")
        if not query:
            return MCPToolResult.from_error(
                error="Query parameter is required for query operation",
                tool_name=self.name,
            )

        # 안전한 읽기 전용 쿼리만 허용
        if not self._is_safe_query(query):
            return MCPToolResult.from_error(
                error="Only SELECT and WITH (CTE) queries are allowed for security",
                tool_name=self.name,
            )

        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # 실제 쿼리 실행은 보안상 제한적으로 구현
        return MCPToolResult.from_success(
            data={"message": "Query execution would be performed here", "query": query},
            tool_name=self.name,
            execution_time_ms=execution_time,
            metadata={"operation": "query", "safe_mode": True},
        )

    @staticmethod
    def _is_safe_query(query: str) -> bool:
        """안전한 쿼리인지 확인

        Args:
            query: SQL 쿼리

        Returns:
            안전 여부 (SELECT/WITH만 허용)
        """
        query_upper = query.strip().upper()

        # SELECT 또는 WITH로 시작하는 쿼리만 허용
        is_safe = query_upper.startswith("SELECT") or query_upper.startswith("WITH")

        # WITH 문인 경우 SELECT를 포함해야 함
        if query_upper.startswith("WITH") and "SELECT" not in query_upper:
            return False

        # 위험한 키워드 체크
        dangerous_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "CREATE",
            "ALTER",
            "TRUNCATE",
            "GRANT",
            "REVOKE",
        ]

        if any(keyword in query_upper for keyword in dangerous_keywords):
            return False

        return is_safe

    async def cleanup(self) -> None:
        """정리 (연결 해제)"""
        pass
