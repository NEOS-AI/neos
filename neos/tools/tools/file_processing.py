"""File processing MCP tool implementation"""

import aiofiles
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import logging

from neos.tools.base import MCPTool, MCPToolResult, MCPToolType
from neos.tools.utils.validators import PathValidator


logger = logging.getLogger(__name__)


class FileProcessingMCPTool(MCPTool):
    """파일 처리 MCP 도구

    안전한 파일 읽기/쓰기/목록조회/삭제 기능을 제공합니다.

    Capabilities:
        - file_read: 파일 읽기
        - file_write: 파일 쓰기
        - file_analysis: 파일 분석
        - format_conversion: 포맷 변환
    """

    def __init__(self):
        super().__init__(
            name="file_processing_mcp",
            tool_type=MCPToolType.FILE_PROCESSING,
            description="MCP를 통한 파일 처리 도구",
            capabilities=[
                "file_read",
                "file_write",
                "file_analysis",
                "format_conversion",
            ],
        )
        self.work_dir = None
        self.validator = PathValidator()

    async def initialize(self) -> bool:
        """파일 처리 도구 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            self.work_dir = Path(os.getcwd())
            logger.info(
                f"FileProcessing MCP tool initialized with work directory: {self.work_dir}"
            )
            self.is_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize FileProcessing MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """파일 작업 실행

        Args:
            params: 작업 파라미터
                - operation (str, required): 작업 타입 (read/write/list/stat/delete)
                - file_path (str, required): 파일 경로
                - content (str, optional): 쓰기 내용 (write 작업 시)
                - mode (str, optional): 쓰기 모드 ('w' or 'a', 기본값: 'w')

        Returns:
            MCPToolResult: 작업 결과
        """
        start_time = datetime.now()

        try:
            # 파라미터 검증
            operation = params.get("operation", "")
            file_path = params.get("file_path", "")

            if not operation or not file_path:
                return MCPToolResult.from_error(
                    error="Operation and file_path parameters are required",
                    tool_name=self.name,
                )

            # 경로 검증
            validated_path = self.validator.validate_path(file_path, self.work_dir)
            if not validated_path:
                return MCPToolResult.from_error(
                    error="File path must be within the working directory",
                    tool_name=self.name,
                )

            # 파일 작업 수행
            result = await self._perform_file_operation(
                operation, validated_path, params
            )

            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            return MCPToolResult.from_success(
                data=result,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={
                    "operation": operation,
                    "source": "mcp_file_processing",
                    "file_path": str(validated_path),
                },
            )

        except FileNotFoundError as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            return MCPToolResult.from_error(
                error=f"File not found: {str(e)}",
                tool_name=self.name,
                execution_time_ms=execution_time,
            )

        except PermissionError as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            return MCPToolResult.from_error(
                error=f"Permission denied: {str(e)}",
                tool_name=self.name,
                execution_time_ms=execution_time,
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

    async def _perform_file_operation(
        self, operation: str, file_path: Path, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """파일 작업 수행

        Args:
            operation: 작업 타입
            file_path: 파일 경로
            params: 추가 파라미터

        Returns:
            작업 결과

        Raises:
            FileNotFoundError: 파일을 찾을 수 없음
            ValueError: 지원하지 않는 작업
        """
        if operation == "read":
            return await self._read_file(file_path)

        elif operation == "write":
            content = params.get("content", "")
            mode = params.get("mode", "w")
            return await self._write_file(file_path, content, mode)

        elif operation == "list":
            return await self._list_directory(file_path)

        elif operation == "stat":
            return await self._stat_file(file_path)

        elif operation == "delete":
            return await self._delete_file(file_path)

        else:
            raise ValueError(f"Unsupported operation: {operation}")

    async def _read_file(self, file_path: Path) -> Dict[str, Any]:
        """파일 읽기"""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()

        return {
            "operation": "read",
            "file_path": str(file_path),
            "content": content,
            "size": len(content),
            "exists": True,
        }

    async def _write_file(
        self, file_path: Path, content: str, mode: str
    ) -> Dict[str, Any]:
        """파일 쓰기"""
        # 디렉토리가 존재하지 않으면 생성
        file_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(file_path, mode, encoding="utf-8") as f:
            await f.write(content)

        return {
            "operation": "write",
            "file_path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
            "mode": mode,
        }

    async def _list_directory(self, file_path: Path) -> Dict[str, Any]:
        """디렉토리 목록 조회"""
        if not file_path.exists():
            raise FileNotFoundError(f"Directory not found: {file_path}")

        if not file_path.is_dir():
            raise ValueError(f"Path is not a directory: {file_path}")

        files = []
        for item in file_path.iterdir():
            files.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "modified": datetime.fromtimestamp(
                        item.stat().st_mtime
                    ).isoformat(),
                }
            )

        return {
            "operation": "list",
            "directory_path": str(file_path),
            "files": files,
            "count": len(files),
        }

    async def _stat_file(self, file_path: Path) -> Dict[str, Any]:
        """파일 정보 조회"""
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
            "is_directory": file_path.is_dir(),
        }

    async def _delete_file(self, file_path: Path) -> Dict[str, Any]:
        """파일/디렉토리 삭제"""
        if not file_path.exists():
            raise FileNotFoundError(f"Path not found: {file_path}")

        if file_path.is_file():
            file_path.unlink()
            return {
                "operation": "delete",
                "file_path": str(file_path),
                "deleted": True,
                "type": "file",
            }
        elif file_path.is_dir():
            shutil.rmtree(file_path)
            return {
                "operation": "delete",
                "file_path": str(file_path),
                "deleted": True,
                "type": "directory",
            }

    async def cleanup(self) -> None:
        """정리 (리소스 해제)"""
        pass
