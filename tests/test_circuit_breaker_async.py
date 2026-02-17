"""
Circuit Breaker async_wrapper 통합 테스트

neos/utils/circuit_breaker.py의 async_wrapper가
neos/workflow/utils/circuit_breaker.py의 AsyncCircuitBreaker를 올바르게 사용하는지 검증합니다.

Tests cover:
- async 함수에 대해 AsyncCircuitBreaker 사용 확인
- 연속 실패 시 OPEN 전환 + degraded dict 반환
- OPEN → HALF_OPEN → CLOSED 복구 사이클
- CIRCUIT_BREAKER_ENABLED=False일 때 bypass
- sync 함수는 여전히 pybreaker 사용
- execute_with_circuit_breaker 함수도 동일 동작
"""

import asyncio
import pytest
from unittest.mock import patch

from neos.utils.circuit_breaker import (
    with_circuit_breaker,
    execute_with_circuit_breaker,
    _async_breakers,
    _get_async_breaker,
    AgentCircuitBreaker,
)


def _get_circuit_state_enum():
    """순환 import를 방지하기 위한 lazy import 헬퍼"""
    import importlib
    mod = importlib.import_module("neos.workflow.utils.circuit_breaker")
    return mod.CircuitState


@pytest.fixture(autouse=True)
def clear_breakers():
    """각 테스트 전후로 breaker 저장소를 초기화합니다."""
    _async_breakers.clear()
    AgentCircuitBreaker._breakers.clear()
    yield
    _async_breakers.clear()
    AgentCircuitBreaker._breakers.clear()


@pytest.mark.unit
class TestAsyncWrapperUsesAsyncBreaker:
    """async_wrapper가 AsyncCircuitBreaker를 사용하는지 검증"""

    @pytest.mark.asyncio
    async def test_async_decorated_function_succeeds(self):
        """async 함수가 circuit breaker를 통해 정상 실행됩니다"""
        @with_circuit_breaker("test_async_success")
        async def my_func():
            return {"success": True, "data": "hello"}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 5
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60
            result = await my_func()

        assert result == {"success": True, "data": "hello"}
        assert "test_async_success" in _async_breakers

    @pytest.mark.asyncio
    async def test_async_breaker_opens_after_consecutive_failures(self):
        """연속 실패 시 circuit이 OPEN되고 degraded dict를 반환합니다"""
        call_count = 0

        @with_circuit_breaker("test_async_fail")
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("API down")

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 3
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60

            # 3번 연속 실패하면 circuit이 열려야 함
            for _ in range(3):
                with pytest.raises(ConnectionError):
                    await failing_func()

            # 4번째 호출은 circuit OPEN으로 인해 즉시 degraded 반환 (func 실행 안 함)
            result = await failing_func()

        assert result["success"] is False
        assert result["degraded"] is True
        assert "Circuit breaker open" in result["error"]
        # 실제 func 호출은 3번만 (4번째는 circuit이 차단)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_breaker_recovers_after_timeout(self):
        """OPEN → HALF_OPEN → CLOSED 복구 사이클이 정상 동작합니다"""
        CircuitState = _get_circuit_state_enum()
        call_count = 0
        should_fail = True

        @with_circuit_breaker("test_async_recover")
        async def maybe_failing_func():
            nonlocal call_count
            call_count += 1
            if should_fail:
                raise ConnectionError("API down")
            return {"success": True}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 2
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 0.5  # 0.5초 후 복구 시도

            # 2번 실패 → OPEN
            for _ in range(2):
                with pytest.raises(ConnectionError):
                    await maybe_failing_func()

            breaker = _async_breakers["test_async_recover"]
            assert breaker.state == CircuitState.OPEN

            # timeout 대기
            await asyncio.sleep(0.6)

            # 이제 서비스가 복구됨
            should_fail = False
            result = await maybe_failing_func()

            assert result == {"success": True}
            # success_threshold(기본값 2)를 충족하면 CLOSED로 전환
            result2 = await maybe_failing_func()
            assert result2 == {"success": True}
            assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_disabled_bypasses(self):
        """CIRCUIT_BREAKER_ENABLED=False이면 circuit breaker를 건너뜁니다"""
        @with_circuit_breaker("test_disabled")
        async def my_func():
            return {"success": True}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = False
            result = await my_func()

        assert result == {"success": True}
        # breaker가 생성되지 않아야 함
        assert "test_disabled" not in _async_breakers


@pytest.mark.unit
class TestSyncWrapperUsesPybreaker:
    """sync_wrapper가 여전히 pybreaker를 사용하는지 검증"""

    def test_sync_decorated_function_succeeds(self):
        """동기 함수는 pybreaker를 통해 정상 실행됩니다"""
        @with_circuit_breaker("test_sync")
        def my_sync_func():
            return {"success": True}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 5
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60
            result = my_sync_func()

        assert result == {"success": True}
        # sync는 pybreaker breaker를 사용
        assert "test_sync" in AgentCircuitBreaker._breakers
        # async breaker는 생성되지 않아야 함
        assert "test_sync" not in _async_breakers


@pytest.mark.unit
class TestExecuteWithCircuitBreaker:
    """execute_with_circuit_breaker 함수 테스트"""

    @pytest.mark.asyncio
    async def test_async_func_uses_async_breaker(self):
        """async 함수에 대해 AsyncCircuitBreaker를 사용합니다"""
        async def my_async_func(x):
            return {"result": x * 2}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 5
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60
            result = await execute_with_circuit_breaker(
                "test_exec_async", my_async_func, 5
            )

        assert result == {"result": 10}
        assert "test_exec_async" in _async_breakers

    @pytest.mark.asyncio
    async def test_sync_func_uses_pybreaker(self):
        """동기 함수에 대해 pybreaker를 사용합니다"""
        def my_sync_func(x):
            return {"result": x * 3}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = True
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 5
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60
            result = await execute_with_circuit_breaker(
                "test_exec_sync", my_sync_func, 5
            )

        assert result == {"result": 15}
        assert "test_exec_sync" in AgentCircuitBreaker._breakers

    @pytest.mark.asyncio
    async def test_disabled_bypasses(self):
        """CIRCUIT_BREAKER_ENABLED=False이면 bypass"""
        async def my_func():
            return {"ok": True}

        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_ENABLED = False
            result = await execute_with_circuit_breaker("test_bypass", my_func)

        assert result == {"ok": True}


@pytest.mark.unit
class TestGetAllStates:
    """get_all_states가 async breaker 상태도 포함하는지 검증"""

    @pytest.mark.asyncio
    async def test_includes_both_sync_and_async_breakers(self):
        """sync와 async breaker 상태를 모두 반환합니다"""
        with patch("neos.utils.circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_FAIL_THRESHOLD = 5
            mock_settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60

            # sync breaker 생성
            AgentCircuitBreaker.get_breaker("sync_agent")

            # async breaker 생성
            _get_async_breaker("async_agent")

            states = AgentCircuitBreaker.get_all_states()

        assert "sync_agent" in states
        assert "async_agent" in states or "agent_async_agent" in states
