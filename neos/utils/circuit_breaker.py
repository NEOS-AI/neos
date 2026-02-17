"""
Circuit Breaker 패턴 구현

에이전트 실패 시 자동으로 회로를 차단하여 시스템 안정성을 향상시킵니다.

동기 함수: pybreaker 라이브러리 사용
비동기 함수: neos.workflow.utils.circuit_breaker의 async-native CircuitBreaker 사용
(pybreaker는 sync-only이므로, async 함수에서는 asyncio.run() 중첩 문제가 발생합니다)
"""
import asyncio
import logging
from typing import Dict, Optional, Callable, Any
from functools import wraps
import pybreaker
from ..config.settings import settings

logger = logging.getLogger(__name__)

# async 함수용 circuit breaker 저장소
# (neos.workflow.utils.circuit_breaker의 AsyncCircuitBreaker 인스턴스)
_async_breakers: Dict[str, Any] = {}


def _get_async_breaker(name: str):
    """async 함수용 circuit breaker 인스턴스를 가져오거나 생성합니다.

    순환 import 방지를 위해 lazy import를 사용합니다.
    """
    if name not in _async_breakers:
        from ..workflow.utils.circuit_breaker import (
            CircuitBreaker as AsyncCircuitBreaker,
            CircuitBreakerConfig as AsyncCBConfig,
        )
        _async_breakers[name] = AsyncCircuitBreaker(
            name=f"agent_{name}",
            config=AsyncCBConfig(
                failure_threshold=settings.CIRCUIT_BREAKER_FAIL_THRESHOLD,
                timeout_seconds=float(settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT),
            )
        )
        logger.info(
            f"Async Circuit Breaker 생성: {name} "
            f"(failure_threshold={settings.CIRCUIT_BREAKER_FAIL_THRESHOLD}, "
            f"timeout={settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT}s)"
        )
    return _async_breakers[name]


class AgentCircuitBreaker:
    """
    에이전트별 Circuit Breaker 관리 클래스

    각 에이전트 타입별로 독립적인 Circuit Breaker를 관리하여
    특정 에이전트의 실패가 전체 시스템에 영향을 주지 않도록 합니다.
    """

    _breakers: Dict[str, pybreaker.CircuitBreaker] = {}

    @classmethod
    def get_breaker(cls, agent_name: str) -> pybreaker.CircuitBreaker:
        """
        에이전트별 Circuit Breaker 인스턴스를 가져오거나 생성합니다.

        Args:
            agent_name: 에이전트 이름 (예: "multi_query_search", "hyper_deep_research")

        Returns:
            pybreaker.CircuitBreaker: 해당 에이전트의 Circuit Breaker
        """
        if agent_name not in cls._breakers:
            cls._breakers[agent_name] = pybreaker.CircuitBreaker(
                fail_max=settings.CIRCUIT_BREAKER_FAIL_THRESHOLD,
                reset_timeout=settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
                name=f"agent_{agent_name}",
                listeners=[CircuitBreakerListener(agent_name)]
            )
            logger.info(
                f"Circuit Breaker 생성: {agent_name} "
                f"(fail_max={settings.CIRCUIT_BREAKER_FAIL_THRESHOLD}, "
                f"reset_timeout={settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT}s)"
            )

        return cls._breakers[agent_name]

    @classmethod
    def get_all_states(cls) -> Dict[str, str]:
        """
        모든 Circuit Breaker의 현재 상태를 반환합니다.

        Returns:
            Dict[str, str]: {agent_name: state} 형태의 딕셔너리
        """
        states = {
            name: breaker.current_state
            for name, breaker in cls._breakers.items()
        }
        # async-native circuit breaker 상태도 포함
        for name, breaker in _async_breakers.items():
            states[name] = breaker.state.value
        return states

    @classmethod
    def reset_breaker(cls, agent_name: str) -> bool:
        """
        특정 에이전트의 Circuit Breaker를 수동으로 리셋합니다.

        Args:
            agent_name: 에이전트 이름

        Returns:
            bool: 리셋 성공 여부
        """
        if agent_name in cls._breakers:
            cls._breakers[agent_name].call(lambda: None)
            logger.info(f"Circuit Breaker 수동 리셋: {agent_name}")
            return True
        return False

    @classmethod
    def reset_all(cls):
        """모든 Circuit Breaker를 리셋합니다."""
        for name, breaker in cls._breakers.items():
            try:
                breaker.call(lambda: None)
                logger.info(f"Circuit Breaker 리셋: {name}")
            except Exception as e:
                logger.error(f"Circuit Breaker 리셋 실패 ({name}): {e}")


class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """
    Circuit Breaker 상태 변경 이벤트를 로깅하는 리스너
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    def state_change(self, cb, old_state, new_state):
        """상태 변경 시 호출됩니다."""
        logger.warning(
            f"🔴 Circuit Breaker 상태 변경: {self.agent_name} "
            f"[{old_state.name} → {new_state.name}]"
        )

    def failure(self, cb, exc):
        """실패 시 호출됩니다."""
        logger.error(
            f"Circuit Breaker 실패 기록: {self.agent_name} "
            f"(fail_counter={cb.fail_counter}/{cb.fail_max}) - {exc}"
        )

    def success(self, cb):
        """성공 시 호출됩니다."""
        logger.debug(f"Circuit Breaker 성공: {self.agent_name}")


def with_circuit_breaker(agent_name: Optional[str] = None):
    """
    함수를 Circuit Breaker로 감싸는 데코레이터

    Args:
        agent_name: 에이전트 이름 (None이면 함수 이름 사용)

    Usage:
        @with_circuit_breaker("multi_query_search")
        async def execute_agent(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        breaker_name = agent_name or func.__name__

        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs) -> Any:
                if not settings.CIRCUIT_BREAKER_ENABLED:
                    return await func(*args, **kwargs)

                breaker = _get_async_breaker(breaker_name)

                try:
                    return await breaker.call(func, *args, **kwargs)
                except Exception as e:
                    from ..workflow.utils.circuit_breaker import CircuitBreakerError as AsyncCBError
                    if isinstance(e, AsyncCBError):
                        logger.error(
                            f"⚠️ Circuit Breaker OPEN: {breaker_name} - "
                            f"에이전트가 일시적으로 비활성화되었습니다."
                        )
                        return {
                            "success": False,
                            "error": f"Circuit breaker open for {breaker_name}",
                            "degraded": True
                        }
                    logger.error(f"Circuit Breaker 예외: {breaker_name} - {e}")
                    raise

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs) -> Any:
                if not settings.CIRCUIT_BREAKER_ENABLED:
                    return func(*args, **kwargs)

                breaker = AgentCircuitBreaker.get_breaker(breaker_name)

                try:
                    return breaker.call(func, *args, **kwargs)
                except pybreaker.CircuitBreakerError:
                    logger.error(
                        f"⚠️ Circuit Breaker OPEN: {breaker_name} - "
                        f"에이전트가 일시적으로 비활성화되었습니다."
                    )
                    return {
                        "success": False,
                        "error": f"Circuit breaker open for {breaker_name}",
                        "degraded": True
                    }
                except Exception as e:
                    logger.error(f"Circuit Breaker 예외: {breaker_name} - {e}")
                    raise

            return sync_wrapper

    return decorator


async def execute_with_circuit_breaker(
    agent_name: str,
    func: Callable,
    *args,
    **kwargs
) -> Any:
    """
    Circuit Breaker를 사용하여 함수를 실행합니다.

    데코레이터를 사용할 수 없는 경우에 사용합니다.

    Args:
        agent_name: 에이전트 이름
        func: 실행할 함수
        *args, **kwargs: 함수 인자

    Returns:
        함수 실행 결과
    """
    if not settings.CIRCUIT_BREAKER_ENABLED:
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    if asyncio.iscoroutinefunction(func):
        # 비동기 함수: async-native circuit breaker 사용
        breaker = _get_async_breaker(agent_name)
        try:
            return await breaker.call(func, *args, **kwargs)
        except Exception as e:
            from ..workflow.utils.circuit_breaker import CircuitBreakerError as AsyncCBError
            if isinstance(e, AsyncCBError):
                logger.error(
                    f"⚠️ Circuit Breaker OPEN: {agent_name} - "
                    f"에이전트가 일시적으로 비활성화되었습니다."
                )
                return {
                    "success": False,
                    "error": f"Circuit breaker open for {agent_name}",
                    "degraded": True
                }
            logger.error(f"Circuit Breaker 예외: {agent_name} - {e}")
            raise
    else:
        # 동기 함수: pybreaker 사용
        breaker = AgentCircuitBreaker.get_breaker(agent_name)
        try:
            return breaker.call(func, *args, **kwargs)
        except pybreaker.CircuitBreakerError:
            logger.error(
                f"⚠️ Circuit Breaker OPEN: {agent_name} - "
                f"에이전트가 일시적으로 비활성화되었습니다."
            )
            return {
                "success": False,
                "error": f"Circuit breaker open for {agent_name}",
                "degraded": True
            }
        except Exception as e:
            logger.error(f"Circuit Breaker 예외: {agent_name} - {e}")
            raise
