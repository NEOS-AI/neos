"""Git operations MCP tool implementation"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Tuple
import logging

from neos.tools.base import MCPTool, MCPToolResult, MCPToolType


logger = logging.getLogger(__name__)


class GitMCPTool(MCPTool):
    """Git 작업 MCP 도구

    안전한 Git 정보 조회 기능을 제공합니다. (읽기 전용)

    Capabilities:
        - status_check: Git 상태 확인
        - commit_info: 커밋 정보 조회
        - branch_info: 브랜치 정보 조회
        - log_view: 로그 조회
    """

    def __init__(self):
        super().__init__(
            name="git_mcp",
            tool_type=MCPToolType.CODE_EXECUTION,
            description="MCP를 통한 Git 작업 도구 (읽기 전용)",
            capabilities=["status_check", "commit_info", "branch_info", "log_view"],
        )

    async def initialize(self) -> bool:
        """Git 도구 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            # Git 설치 확인
            import subprocess

            result = subprocess.run(
                ["git", "--version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.warning("Git not found, Git MCP tool will not be available")
                return False

            logger.info("Git MCP tool initialized")
            self.is_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Git MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """Git 작업 실행

        Args:
            params: 작업 파라미터
                - operation (str, required): 작업 타입 (status/branch/log)
                - limit (int, optional): 로그 개수 (operation=log일 때, 기본값: 10)

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

            if operation == "status":
                return await self._git_status(start_time)

            elif operation == "branch":
                return await self._git_branch(start_time)

            elif operation == "log":
                limit = params.get("limit", 10)
                return await self._git_log(limit, start_time)

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

    async def _git_status(self, start_time: datetime) -> MCPToolResult:
        """Git 상태 확인"""
        stdout, stderr, returncode = await self._run_git_command(
            ["git", "status", "--porcelain"]
        )

        if returncode != 0:
            return MCPToolResult.from_error(
                error=stderr,
                tool_name=self.name,
            )

        # 상태 파싱
        status_lines = stdout.strip().split("\n") if stdout.strip() else []
        files = []
        for line in status_lines:
            if line:
                status_code = line[:2]
                filename = line[3:]
                files.append({"status": status_code, "file": filename})

        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return MCPToolResult.from_success(
            data={"files": files, "clean": len(files) == 0},
            tool_name=self.name,
            execution_time_ms=execution_time,
            metadata={"operation": "status", "file_count": len(files)},
        )

    async def _git_branch(self, start_time: datetime) -> MCPToolResult:
        """현재 브랜치 확인"""
        stdout, stderr, returncode = await self._run_git_command(
            ["git", "branch", "--show-current"]
        )

        if returncode != 0:
            return MCPToolResult.from_error(
                error=stderr,
                tool_name=self.name,
            )

        current_branch = stdout.strip()
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return MCPToolResult.from_success(
            data={"current_branch": current_branch},
            tool_name=self.name,
            execution_time_ms=execution_time,
            metadata={"operation": "branch"},
        )

    async def _git_log(self, limit: int, start_time: datetime) -> MCPToolResult:
        """Git 로그 조회"""
        stdout, stderr, returncode = await self._run_git_command(
            [
                "git",
                "log",
                f"-{limit}",
                "--pretty=format:%H|%an|%ae|%ad|%s",
                "--date=iso",
            ]
        )

        if returncode != 0:
            return MCPToolResult.from_error(
                error=stderr,
                tool_name=self.name,
            )

        # 로그 파싱
        log_lines = stdout.strip().split("\n") if stdout.strip() else []
        commits = []
        for line in log_lines:
            if line:
                parts = line.split("|")
                if len(parts) == 5:
                    commits.append(
                        {
                            "hash": parts[0],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4],
                        }
                    )

        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return MCPToolResult.from_success(
            data={"commits": commits, "count": len(commits)},
            tool_name=self.name,
            execution_time_ms=execution_time,
            metadata={"operation": "log", "limit": limit},
        )

    async def _run_git_command(self, args: List[str]) -> Tuple[str, str, int]:
        """Git 명령 실행

        Args:
            args: Git 명령 인자 리스트

        Returns:
            (stdout, stderr, returncode) 튜플
        """
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return (
            stdout.decode("utf-8"),
            stderr.decode("utf-8"),
            process.returncode,
        )

    async def cleanup(self) -> None:
        """정리"""
        pass
