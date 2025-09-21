"""MCP (Model Context Protocol) 통합 관리자"""

from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import aiohttp
import aiofiles
import os
from pathlib import Path

from neos.config.settings import settings


logger = logging.getLogger(__name__)


class MCPToolType(Enum):
    """MCP 도구 타입"""
    WEB_SEARCH = "web_search"
    FILE_PROCESSING = "file_processing"
    DATA_ANALYSIS = "data_analysis"
    API_INTEGRATION = "api_integration"
    CODE_EXECUTION = "code_execution"
    IMAGE_PROCESSING = "image_processing"


@dataclass
class MCPToolResult:
    """MCP 도구 실행 결과"""
    success: bool
    data: Any
    error: Optional[str] = None
    tool_name: str = ""
    execution_time_ms: int = 0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MCPTool(ABC):
    """MCP 도구 기본 클래스"""

    def __init__(
        self,
        name: str,
        tool_type: MCPToolType,
        description: str = "",
        capabilities: List[str] = None
    ):
        self.name = name
        self.tool_type = tool_type
        self.description = description
        self.capabilities = capabilities or []
        self.is_available = False

    @abstractmethod
    async def initialize(self) -> bool:
        """도구 초기화"""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """도구 실행"""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """도구 정리"""
        pass

    async def check_availability(self) -> bool:
        """도구 사용 가능성 확인"""
        try:
            return await self.initialize()
        except Exception as e:
            logger.warning(f"MCP tool {self.name} not available: {e}")
            return False


class WebSearchMCPTool(MCPTool):
    """웹 검색 MCP 도구"""

    def __init__(self):
        super().__init__(
            name="web_search_mcp",
            tool_type=MCPToolType.WEB_SEARCH,
            description="MCP를 통한 웹 검색 도구",
            capabilities=["real_time_search", "multi_source_search", "structured_results"]
        )
        self.client = None


    async def initialize(self) -> bool:
        """MCP 웹 검색 클라이언트 초기화"""
        try:
            # Tavily API 키 확인
            if not settings.TAVILY_API_KEY:
                logger.warning("TAVILY_API_KEY not configured, WebSearch MCP tool will not be available")
                return False

            # HTTP 클라이언트 초기화
            self.client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.MCP_TIMEOUT)
            )

            logger.info("Initializing WebSearch MCP tool with Tavily API")
            self.is_available = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize WebSearch MCP tool: {e}")
            return False


    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """웹 검색 실행"""
        start_time = datetime.now()

        try:
            query = params.get("query", "")
            if not query:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error="Query parameter is required",
                    tool_name=self.name
                )

            if not self.client:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error="WebSearch client not initialized",
                    tool_name=self.name
                )

            # Tavily API를 통한 실제 웹 검색
            max_results = params.get("max_results", 5)
            search_depth = params.get("search_depth", "basic")

            search_payload = {
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": False
            }

            async with self.client.post(
                "https://api.tavily.com/search",
                json=search_payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error=f"Tavily API error {response.status}: {error_text}",
                        tool_name=self.name
                    )

                search_data = await response.json()

            # 결과 포맷팅
            results = []
            for item in search_data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "url": item.get("url", ""),
                    "score": item.get("score", 0.0),
                    "source": "tavily_mcp_search"
                })

            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPToolResult(
                success=True,
                data=results,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={
                    "source": "mcp_tavily",
                    "result_count": len(results),
                    "query": query,
                    "search_depth": search_depth,
                    "answer": search_data.get("answer")
                }
            )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def cleanup(self) -> None:
        """클라이언트 정리"""
        if self.client:
            try:
                await self.client.close()
                logger.info("WebSearch MCP tool client cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up WebSearch MCP tool: {e}")


class FileProcessingMCPTool(MCPTool):
    """파일 처리 MCP 도구"""

    def __init__(self):
        super().__init__(
            name="file_processing_mcp",
            tool_type=MCPToolType.FILE_PROCESSING,
            description="MCP를 통한 파일 처리 도구",
            capabilities=["file_read", "file_write", "file_analysis", "format_conversion"]
        )

    async def initialize(self) -> bool:
        try:
            # 파일 처리를 위한 기본 디렉토리 확인
            self.work_dir = Path(os.getcwd())
            logger.info(f"Initializing FileProcessing MCP tool with work directory: {self.work_dir}")
            self.is_available = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize FileProcessing MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        start_time = datetime.now()

        try:
            operation = params.get("operation", "")
            file_path = params.get("file_path", "")

            if not operation or not file_path:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error="Operation and file_path parameters are required",
                    tool_name=self.name
                )

            # 보안을 위한 경로 검증
            target_path = Path(file_path)
            if target_path.is_absolute():
                # 절대 경로의 경우 작업 디렉토리 내부인지 확인
                try:
                    target_path.resolve().relative_to(self.work_dir.resolve())
                except ValueError:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error="File path must be within the working directory",
                        tool_name=self.name
                    )
            else:
                target_path = self.work_dir / target_path

            # 실제 파일 처리 작업 수행
            result = await self._perform_file_operation(operation, target_path, params)

            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPToolResult(
                success=True,
                data=result,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={"operation": operation, "source": "mcp_file_processing", "file_path": str(target_path)}
            )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def _perform_file_operation(self, operation: str, file_path: Path, params: Dict[str, Any]) -> Dict[str, Any]:
        """파일 작업 수행"""

        if operation == "read":
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            return {
                "operation": "read",
                "file_path": str(file_path),
                "content": content,
                "size": len(content),
                "exists": True
            }

        elif operation == "write":
            content = params.get("content", "")
            mode = params.get("mode", "w")  # "w" or "a"

            # 디렉토리가 존재하지 않으면 생성
            file_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(file_path, mode, encoding='utf-8') as f:
                await f.write(content)

            return {
                "operation": "write",
                "file_path": str(file_path),
                "bytes_written": len(content.encode('utf-8')),
                "mode": mode
            }

        elif operation == "list":
            if not file_path.exists():
                raise FileNotFoundError(f"Directory not found: {file_path}")

            if not file_path.is_dir():
                raise ValueError(f"Path is not a directory: {file_path}")

            files = []
            for item in file_path.iterdir():
                files.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                })

            return {
                "operation": "list",
                "directory_path": str(file_path),
                "files": files,
                "count": len(files)
            }

        elif operation == "stat":
            if not file_path.exists():
                raise FileNotFoundError(f"Path not found: {file_path}")

            stat = file_path.stat()
            return {
                "operation": "stat",
                "file_path": str(file_path),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "is_file": file_path.is_file(),
                "is_directory": file_path.is_dir()
            }

        elif operation == "delete":
            if not file_path.exists():
                raise FileNotFoundError(f"Path not found: {file_path}")

            if file_path.is_file():
                file_path.unlink()
                return {
                    "operation": "delete",
                    "file_path": str(file_path),
                    "deleted": True,
                    "type": "file"
                }
            elif file_path.is_dir():
                import shutil
                shutil.rmtree(file_path)
                return {
                    "operation": "delete",
                    "file_path": str(file_path),
                    "deleted": True,
                    "type": "directory"
                }

        else:
            raise ValueError(f"Unsupported operation: {operation}")

    async def cleanup(self) -> None:
        pass


class DatabaseMCPTool(MCPTool):
    """데이터베이스 MCP 도구"""

    def __init__(self):
        super().__init__(
            name="database_mcp",
            tool_type=MCPToolType.DATA_ANALYSIS,
            description="MCP를 통한 데이터베이스 작업 도구",
            capabilities=["query_execution", "schema_inspection", "data_export"]
        )
        self.connection = None

    async def initialize(self) -> bool:
        try:
            # 데이터베이스 연결 확인
            from neos.database.connection import db_manager
            self.connection = db_manager
            logger.info("Initializing Database MCP tool")
            self.is_available = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Database MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        start_time = datetime.now()

        try:
            operation = params.get("operation", "")
            if not operation:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error="Operation parameter is required",
                    tool_name=self.name
                )

            if operation == "health_check":
                health = await self.connection.health_check()
                return MCPToolResult(
                    success=True,
                    data={"healthy": health, "timestamp": datetime.now().isoformat()},
                    tool_name=self.name,
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
                )

            elif operation == "query":
                query = params.get("query", "")
                if not query:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error="Query parameter is required for query operation",
                        tool_name=self.name
                    )

                # 안전한 읽기 전용 쿼리만 허용 (SELECT 및 CTE WITH 문)
                query_upper = query.strip().upper()
                is_safe_query = (
                    query_upper.startswith("SELECT") or
                    query_upper.startswith("WITH")
                )

                # WITH 문인 경우 최종적으로 SELECT를 포함하는지 확인
                if query_upper.startswith("WITH"):
                    # CTE에서는 마지막에 SELECT 문이 있어야 함
                    if "SELECT" not in query_upper:
                        return MCPToolResult(
                            success=False,
                            data=None,
                            error="WITH queries must contain a SELECT statement",
                            tool_name=self.name
                        )

                    # 위험한 키워드들이 포함되어 있는지 확인
                    dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"]
                    if any(keyword in query_upper for keyword in dangerous_keywords):
                        return MCPToolResult(
                            success=False,
                            data=None,
                            error="Query contains potentially dangerous operations",
                            tool_name=self.name
                        )

                if not is_safe_query:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error="Only SELECT and WITH (CTE) queries are allowed for security",
                        tool_name=self.name
                    )

                # 실제 쿼리 실행은 보안상 제한적으로 구현
                return MCPToolResult(
                    success=True,
                    data={"message": "Query execution would be performed here", "query": query},
                    tool_name=self.name,
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    metadata={"operation": "query", "safe_mode": True}
                )

            else:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error=f"Unsupported operation: {operation}",
                    tool_name=self.name
                )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def cleanup(self) -> None:
        pass


class GitMCPTool(MCPTool):
    """Git 작업 MCP 도구"""

    def __init__(self):
        super().__init__(
            name="git_mcp",
            tool_type=MCPToolType.CODE_EXECUTION,
            description="MCP를 통한 Git 작업 도구",
            capabilities=["status_check", "commit_info", "branch_info", "log_view"]
        )

    async def initialize(self) -> bool:
        try:
            # Git 설치 확인
            import subprocess
            result = subprocess.run(["git", "--version"], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("Git not found, Git MCP tool will not be available")
                return False

            logger.info("Initializing Git MCP tool")
            self.is_available = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Git MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        start_time = datetime.now()

        try:
            operation = params.get("operation", "")
            if not operation:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error="Operation parameter is required",
                    tool_name=self.name
                )

            if operation == "status":
                process = await asyncio.create_subprocess_exec(
                    "git", "status", "--porcelain",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error=stderr.decode('utf-8'),
                        tool_name=self.name
                    )

                status_lines = stdout.decode('utf-8').strip().split('\n')
                files = []
                for line in status_lines:
                    if line:
                        status_code = line[:2]
                        filename = line[3:]
                        files.append({"status": status_code, "file": filename})

                return MCPToolResult(
                    success=True,
                    data={"files": files, "clean": len(files) == 0},
                    tool_name=self.name,
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    metadata={"operation": "status", "file_count": len(files)}
                )

            elif operation == "branch":
                process = await asyncio.create_subprocess_exec(
                    "git", "branch", "--show-current",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    return MCPToolResult(
                        success=False,
                        data=None,
                        error=stderr.decode('utf-8'),
                        tool_name=self.name
                    )

                current_branch = stdout.decode('utf-8').strip()

                return MCPToolResult(
                    success=True,
                    data={"current_branch": current_branch},
                    tool_name=self.name,
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    metadata={"operation": "branch"}
                )

            else:
                return MCPToolResult(
                    success=False,
                    data=None,
                    error=f"Unsupported operation: {operation}",
                    tool_name=self.name
                )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def cleanup(self) -> None:
        pass


class MCPManager:
    """MCP 도구 관리자"""

    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self.available_tools: Dict[str, MCPTool] = {}
        self.initialization_complete = False
        self._register_default_tools()


    def _register_default_tools(self) -> None:
        """기본 MCP 도구들 등록"""
        tools = [
            WebSearchMCPTool(),
            FileProcessingMCPTool(),
            DatabaseMCPTool(),
            GitMCPTool(),
        ]

        for tool in tools:
            self.tools[tool.name] = tool


    async def initialize(self) -> Dict[str, bool]:
        """모든 등록된 MCP 도구 초기화"""
        logger.info("Initializing MCP tools...")
        initialization_results = {}

        for tool_name, tool in self.tools.items():
            try:
                is_available = await tool.check_availability()
                initialization_results[tool_name] = is_available

                if is_available:
                    self.available_tools[tool_name] = tool
                    logger.info(f"MCP tool {tool_name} is available")
                else:
                    logger.warning(f"MCP tool {tool_name} is not available")

            except Exception as e:
                logger.error(f"Error initializing MCP tool {tool_name}: {e}")
                initialization_results[tool_name] = False

        self.initialization_complete = True
        logger.info(f"MCP initialization complete. Available tools: {list(self.available_tools.keys())}")

        return initialization_results

    def get_available_tools(self, tool_type: Optional[MCPToolType] = None) -> List[MCPTool]:
        """사용 가능한 도구 목록 반환"""
        if not tool_type:
            return list(self.available_tools.values())

        return [
            tool for tool in self.available_tools.values()
            if tool.tool_type == tool_type
        ]

    def is_tool_available(self, tool_name: str) -> bool:
        """특정 도구 사용 가능성 확인"""
        return tool_name in self.available_tools

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> MCPToolResult:
        """MCP 도구 실행"""
        if not self.initialization_complete:
            await self.initialize()

        if tool_name not in self.available_tools:
            return MCPToolResult(
                success=False,
                data=None,
                error=f"MCP tool {tool_name} is not available",
                tool_name=tool_name
            )

        tool = self.available_tools[tool_name]
        return await tool.execute(params)

    async def execute_by_type(
        self,
        tool_type: MCPToolType,
        params: Dict[str, Any]
    ) -> List[MCPToolResult]:
        """특정 타입의 모든 도구 실행"""
        available_tools = self.get_available_tools(tool_type)

        if not available_tools:
            return [MCPToolResult(
                success=False,
                data=None,
                error=f"No MCP tools available for type {tool_type.value}",
                tool_name=f"type_{tool_type.value}"
            )]

        tasks = [
            tool.execute(params) for tool in available_tools
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(MCPToolResult(
                    success=False,
                    data=None,
                    error=str(result),
                    tool_name=available_tools[i].name
                ))
            else:
                processed_results.append(result)

        return processed_results

    def register_tool(self, tool: MCPTool) -> None:
        """새로운 MCP 도구 등록"""
        self.tools[tool.name] = tool
        logger.info(f"Registered MCP tool: {tool.name}")

    async def cleanup(self) -> None:
        """모든 MCP 도구 정리"""
        for tool in self.available_tools.values():
            try:
                await tool.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up MCP tool {tool.name}: {e}")

        self.available_tools.clear()
        logger.info("MCP tools cleanup complete")


# 전역 MCP 매니저 인스턴스
mcp_manager = MCPManager()
