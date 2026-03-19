"""SandboxedCodeExecutor: 통합 코드 실행 인터페이스.

RestrictedPythonExecutor에 대한 통합 API 레이어.
향후 Docker 컨테이너 또는 Pyodide WASM sandbox 추가 시 동일 인터페이스 유지.

사용 방법:
    executor = SandboxedCodeExecutor(sandbox_type="restricted")
    result = await executor.execute("result = sum([1, 2, 3])")
    # result.success == True, result.output == "6"

SANDBOX_ENABLED=false (기본) 시 모든 execute() 호출이 비활성화 메시지를 반환.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeExecutionResult:
    """코드 실행 결과."""
    success: bool
    output: str
    error: Optional[str] = None
    execution_time_ms: int = 0
    sandbox_type: str = "restricted"


class SandboxedCodeExecutor:
    """통합 코드 실행 인터페이스.

    sandbox_type:
    - "restricted": RestrictedPython 기반 (경량, 현재 권장)
    - "docker": Ray container runtime_env 기반 (강한 격리, Ray 2.8+ 필요)
    - "pyodide": WASM 기반 (완전 격리, 별도 서비스 필요 — 미구현)

    사용 예:
        executor = SandboxedCodeExecutor()
        result = await executor.execute(
            code="result = [x**2 for x in values]",
            input_data={"values": [1, 2, 3, 4, 5]},
            timeout_sec=10,
        )
        if result.success:
            print(result.output)  # "[1, 4, 9, 16, 25]"
    """

    def __init__(self, sandbox_type: str = "restricted"):
        from neos.config.settings import settings
        self._enabled = getattr(settings, "SANDBOX_ENABLED", False)
        self._sandbox_type = sandbox_type
        self._actor: Optional[Any] = None

        if self._enabled:
            self._initialize_actor(sandbox_type)

    def _initialize_actor(self, sandbox_type: str) -> None:
        """sandbox_type에 따라 Ray Actor 초기화."""
        try:
            if sandbox_type == "restricted":
                from neos.workflow.ray_actors.sandbox_executor import RestrictedPythonExecutor
                self._actor = RestrictedPythonExecutor.remote()
                logger.info("[SandboxedCodeExecutor] RestrictedPythonExecutor Actor created")
            else:
                logger.warning(
                    f"[SandboxedCodeExecutor] sandbox_type='{sandbox_type}' not yet implemented. "
                    f"Supported: 'restricted'"
                )
                self._enabled = False
        except Exception as e:
            logger.error(f"[SandboxedCodeExecutor] Actor initialization failed: {e}")
            self._enabled = False

    async def execute(
        self,
        code: str,
        input_data: Optional[Dict[str, Any]] = None,
        timeout_sec: Optional[int] = None,
    ) -> CodeExecutionResult:
        """코드를 sandbox에서 실행.

        Args:
            code: 실행할 Python 코드. result 또는 output 변수에 결과 할당.
            input_data: 코드에서 접근 가능한 변수 dict.
            timeout_sec: 실행 타임아웃. None이면 settings.SANDBOX_TIMEOUT_SEC 사용.

        Returns:
            CodeExecutionResult
        """
        if not self._enabled or self._actor is None:
            return CodeExecutionResult(
                success=False,
                output="",
                error="Sandbox 코드 실행이 비활성화되어 있습니다 (SANDBOX_ENABLED=false)",
                sandbox_type=self._sandbox_type,
            )

        from neos.config.settings import settings
        timeout = timeout_sec or getattr(settings, "SANDBOX_TIMEOUT_SEC", 30)

        start = time.monotonic()
        try:
            result: Dict[str, Any] = await asyncio.wrap_future(
                self._actor.execute_code.remote(code, input_data or {}, timeout).future()
            )
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return CodeExecutionResult(
                success=False,
                output="",
                error=f"Sandbox Actor 오류: {str(e)}",
                execution_time_ms=elapsed_ms,
                sandbox_type=self._sandbox_type,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return CodeExecutionResult(
            success=result.get("success", False),
            output=result.get("output", ""),
            error=result.get("error"),
            execution_time_ms=elapsed_ms,
            sandbox_type=self._sandbox_type,
        )
