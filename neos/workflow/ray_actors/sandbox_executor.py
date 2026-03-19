"""RestrictedPythonExecutor: AST 수준 코드 실행 제한 Sandbox.

현재 HyperDeepResearchAgent는 임의 코드를 실행하지 않는다.
이 모듈은 향후 LLM이 생성한 분석 코드(pandas, json 파싱 등)를 실행할 때를 위한 예방적 설계.

사용 방법:
    executor = RestrictedPythonExecutor.remote()
    result = await asyncio.wrap_future(
        executor.execute_code.remote("result = sum([1, 2, 3])").future()
    )
    # result = {"success": True, "output": "6", "error": None}

의존성:
    RestrictedPython은 optional dependency:
    uv add --optional sandbox RestrictedPython

허용 import:
    math, statistics, json, re, datetime, collections, itertools, functools
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import ray

logger = logging.getLogger(__name__)

_ALLOWED_IMPORTS = frozenset([
    "math",
    "statistics",
    "json",
    "re",
    "datetime",
    "collections",
    "itertools",
    "functools",
])


@ray.remote(num_cpus=0.5, max_concurrency=4)
class RestrictedPythonExecutor:
    """AST 레벨 코드 실행 제한 Ray Actor.

    RestrictedPython을 사용하여 허용된 내장 함수와 import만 실행.
    asyncio.wait_for 기반 timeout (signal.SIGALRM 대신 — 크로스 플랫폼 안전).

    허용 목록:
    - 내장 함수: sum, len, range, list, dict, set, tuple, str, int, float, bool,
                  print, sorted, reversed, enumerate, zip, map, filter, abs, min, max, round
    - import: math, statistics, json, re, datetime, collections, itertools, functools
    차단 목록:
    - open, exec, eval, __import__ (화이트리스트 외), os, sys, subprocess
    """

    def __init__(self):
        try:
            import RestrictedPython
            self._available = True
            logger.info("[RestrictedPythonExecutor] RestrictedPython available")
        except ImportError:
            self._available = False
            logger.warning(
                "[RestrictedPythonExecutor] RestrictedPython not installed. "
                "Install with: uv add --optional sandbox RestrictedPython"
            )

    async def execute_code(
        self,
        code: str,
        input_data: Optional[Dict[str, Any]] = None,
        timeout_sec: int = 10,
    ) -> Dict[str, Any]:
        """코드를 제한된 환경에서 실행.

        Args:
            code: 실행할 Python 코드 문자열
            input_data: 코드에서 사용할 변수 dict (예: {"values": [1, 2, 3]})
            timeout_sec: 실행 타임아웃 (초)

        Returns:
            {
                "success": bool,
                "output": str,  # result 또는 output 변수값
                "error": str | None,
            }
        """
        if not self._available:
            return {
                "success": False,
                "output": "",
                "error": "RestrictedPython not installed (optional dependency)",
            }

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_restricted, code, input_data or {}),
                timeout=timeout_sec,
            )
            return result
        except asyncio.TimeoutError:
            return {
                "success": False,
                "output": "",
                "error": f"코드 실행이 {timeout_sec}초를 초과했습니다",
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"실행 오류: {str(e)}",
            }

    def _run_restricted(self, code: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """동기 방식 제한 코드 실행 (별도 스레드에서 실행)."""
        try:
            from RestrictedPython import compile_restricted, safe_globals
            from RestrictedPython.Guards import (
                safe_builtins,
                guarded_iter_unpack_sequence,
            )
        except ImportError:
            return {
                "success": False,
                "output": "",
                "error": "RestrictedPython not installed",
            }

        try:
            compiled = compile_restricted(code, filename="<sandbox>", mode="exec")
        except SyntaxError as e:
            return {"success": False, "output": "", "error": f"SyntaxError: {e}"}

        restricted_globals: Dict[str, Any] = {
            **safe_globals,
            "__builtins__": {
                **safe_builtins,
                "__import__": self._restricted_import,
            },
            "_getiter_": iter,
            "_getattr_": getattr,
            "_unpack_sequence_": guarded_iter_unpack_sequence,
        }

        if input_data:
            restricted_globals.update(input_data)

        local_vars: Dict[str, Any] = {}

        try:
            exec(compiled, restricted_globals, local_vars)
            # result 또는 output 변수에서 결과 추출
            output = local_vars.get("result", local_vars.get("output", ""))
            return {"success": True, "output": str(output), "error": None}
        except Exception as e:
            return {"success": False, "output": "", "error": f"RuntimeError: {e}"}

    def _restricted_import(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """허용 목록에 없는 import 차단."""
        if name not in _ALLOWED_IMPORTS:
            raise ImportError(
                f"'{name}' import는 sandbox에서 허용되지 않습니다. "
                f"허용 목록: {sorted(_ALLOWED_IMPORTS)}"
            )
        return __import__(name, *args, **kwargs)
