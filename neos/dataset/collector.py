"""
LLM 호출 수집 및 추적

데코레이터와 컨텍스트 매니저를 통해 LLM 호출을 자동으로 추적합니다.
"""

import time
import logging
import functools
from typing import Dict, Any, Optional, List, Callable
from contextlib import asynccontextmanager
import asyncio

from .models import LLMCallRecord

logger = logging.getLogger(__name__)


class LLMCallCollector:
    """LLM 호출 수집기 - 싱글톤 패턴"""

    _instance = None
    _records: List[LLMCallRecord] = []
    _enabled: bool = True

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """초기화"""
        if not hasattr(self, 'initialized'):
            self._records = []
            self._enabled = True
            self.initialized = True
            logger.info("LLM Call Collector initialized")

    def enable(self) -> None:
        """수집 활성화"""
        self._enabled = True
        logger.info("LLM Call Collector enabled")

    def disable(self) -> None:
        """수집 비활성화"""
        self._enabled = False
        logger.info("LLM Call Collector disabled")

    def is_enabled(self) -> bool:
        """활성화 여부 확인"""
        return self._enabled

    def add_record(self, record: LLMCallRecord) -> None:
        """레코드 추가"""
        if self._enabled:
            self._records.append(record)
            logger.debug(f"Added LLM call record: {record.call_id} (total: {len(self._records)})")


    def get_records(
        self,
        session_id: Optional[str] = None,
        workflow_step: Optional[str] = None,
        agent_name: Optional[str] = None
    ) -> List[LLMCallRecord]:
        """레코드 조회"""
        records = self._records

        if session_id:
            records = [r for r in records if r.session_id == session_id]

        if workflow_step:
            records = [r for r in records if r.workflow_step == workflow_step]

        if agent_name:
            records = [r for r in records if r.agent_name == agent_name]

        return records

    def get_all_records(self) -> List[LLMCallRecord]:
        """모든 레코드 반환"""
        return self._records.copy()

    def clear_records(self) -> int:
        """레코드 초기화"""
        count = len(self._records)
        self._records.clear()
        logger.info(f"Cleared {count} LLM call records")
        return count

    def get_statistics(self) -> Dict[str, Any]:
        """통계 정보"""
        if not self._records:
            return {
                "total_records": 0,
                "enabled": self._enabled
            }

        total_tokens = sum(r.total_tokens or 0 for r in self._records)
        successful = sum(1 for r in self._records if r.success)
        latencies = [r.latency_ms for r in self._records if r.latency_ms is not None]

        return {
            "total_records": len(self._records),
            "successful_calls": successful,
            "failed_calls": len(self._records) - successful,
            "success_rate": successful / len(self._records) if self._records else 0.0,
            "total_tokens": total_tokens,
            "average_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "enabled": self._enabled,
            "providers": list(set(r.provider for r in self._records if r.provider)),
            "models": list(set(r.model for r in self._records if r.model)),
            "workflow_steps": list(set(r.workflow_step for r in self._records if r.workflow_step)),
            "agents": list(set(r.agent_name for r in self._records if r.agent_name))
        }


# 전역 수집기 인스턴스
llm_call_collector = LLMCallCollector()


def track_llm_call(
    workflow_step: str,
    agent_name: Optional[str] = None,
    tags: Optional[List[str]] = None
):
    """
    LLM 호출 추적 데코레이터

    사용 예:
    @track_llm_call(workflow_step="query_classifier", agent_name="classifier")
    async def classify_query(self, state):
        llm_response = await self.llm.ainvoke(messages)
        return result
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not llm_call_collector.is_enabled():
                return await func(*args, **kwargs)

            # 시작 시간 기록
            start_time = time.time()

            # 컨텍스트 추출 (첫 번째 인자가 보통 self이고 두 번째가 state)
            context = {}
            if len(args) > 1 and isinstance(args[1], dict):
                state = args[1]
                context = {
                    "session_id": state.get("session_id", ""),
                    "user_id": state.get("user_id", ""),
                }

            try:
                # 함수 실행
                result = await func(*args, **kwargs)

                # 실행 시간 계산
                latency_ms = (time.time() - start_time) * 1000

                # LLM 호출 정보 추출 (result에서)
                if isinstance(result, dict):
                    # result에 LLM 호출 정보가 포함되어 있을 수 있음
                    llm_info = result.get("_llm_call_info", {})

                    record = LLMCallRecord(
                        session_id=context.get("session_id", ""),
                        user_id=context.get("user_id", ""),
                        workflow_step=workflow_step,
                        agent_name=agent_name,
                        provider=llm_info.get("provider", ""),
                        model=llm_info.get("model", ""),
                        temperature=llm_info.get("temperature", 0.7),
                        input_messages=llm_info.get("input_messages", []),
                        output_text=llm_info.get("output_text", ""),
                        output_metadata=llm_info.get("output_metadata", {}),
                        prompt_tokens=llm_info.get("prompt_tokens"),
                        completion_tokens=llm_info.get("completion_tokens"),
                        total_tokens=llm_info.get("total_tokens"),
                        latency_ms=latency_ms,
                        success=True,
                        tags=tags or [],
                        custom_metadata=llm_info.get("custom_metadata", {})
                    )

                    llm_call_collector.add_record(record)

                return result

            except Exception as e:
                # 에러 발생 시 실패 기록
                latency_ms = (time.time() - start_time) * 1000

                record = LLMCallRecord(
                    session_id=context.get("session_id", ""),
                    user_id=context.get("user_id", ""),
                    workflow_step=workflow_step,
                    agent_name=agent_name,
                    latency_ms=latency_ms,
                    success=False,
                    error_message=str(e),
                    tags=tags or []
                )

                llm_call_collector.add_record(record)
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not llm_call_collector.is_enabled():
                return func(*args, **kwargs)

            # 동기 함수는 비동기와 동일한 로직
            start_time = time.time()

            context = {}
            if len(args) > 1 and isinstance(args[1], dict):
                state = args[1]
                context = {
                    "session_id": state.get("session_id", ""),
                    "user_id": state.get("user_id", ""),
                }

            try:
                result = func(*args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000

                if isinstance(result, dict):
                    llm_info = result.get("_llm_call_info", {})

                    record = LLMCallRecord(
                        session_id=context.get("session_id", ""),
                        user_id=context.get("user_id", ""),
                        workflow_step=workflow_step,
                        agent_name=agent_name,
                        provider=llm_info.get("provider", ""),
                        model=llm_info.get("model", ""),
                        temperature=llm_info.get("temperature", 0.7),
                        input_messages=llm_info.get("input_messages", []),
                        output_text=llm_info.get("output_text", ""),
                        prompt_tokens=llm_info.get("prompt_tokens"),
                        completion_tokens=llm_info.get("completion_tokens"),
                        total_tokens=llm_info.get("total_tokens"),
                        latency_ms=latency_ms,
                        success=True,
                        tags=tags or []
                    )

                    llm_call_collector.add_record(record)

                return result

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000

                record = LLMCallRecord(
                    session_id=context.get("session_id", ""),
                    user_id=context.get("user_id", ""),
                    workflow_step=workflow_step,
                    agent_name=agent_name,
                    latency_ms=latency_ms,
                    success=False,
                    error_message=str(e),
                    tags=tags or []
                )

                llm_call_collector.add_record(record)
                raise

        # async 함수인지 확인
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


@asynccontextmanager
async def track_llm_context(
    workflow_step: str,
    agent_name: Optional[str] = None,
    session_id: str = "",
    user_id: str = "",
    tags: Optional[List[str]] = None
):
    """
    컨텍스트 매니저를 통한 LLM 호출 추적

    사용 예:
    async with track_llm_context(workflow_step="search", agent_name="knowledge_search",
                                  session_id=state["session_id"], user_id=state["user_id"]):
        response = await llm.ainvoke(messages)
        # 컨텍스트 내에서 LLM 호출 정보 수동 기록
        yield {"response": response, "_llm_call_info": {...}}
    """
    start_time = time.time()
    llm_info = {}

    try:
        yield llm_info

        # 성공적으로 완료
        latency_ms = (time.time() - start_time) * 1000

        if llm_call_collector.is_enabled() and llm_info:
            record = LLMCallRecord(
                session_id=session_id,
                user_id=user_id,
                workflow_step=workflow_step,
                agent_name=agent_name,
                provider=llm_info.get("provider", ""),
                model=llm_info.get("model", ""),
                temperature=llm_info.get("temperature", 0.7),
                input_messages=llm_info.get("input_messages", []),
                output_text=llm_info.get("output_text", ""),
                output_metadata=llm_info.get("output_metadata", {}),
                prompt_tokens=llm_info.get("prompt_tokens"),
                completion_tokens=llm_info.get("completion_tokens"),
                total_tokens=llm_info.get("total_tokens"),
                latency_ms=latency_ms,
                success=True,
                tags=tags or []
            )

            llm_call_collector.add_record(record)

    except Exception as e:
        # 에러 발생
        latency_ms = (time.time() - start_time) * 1000

        if llm_call_collector.is_enabled():
            record = LLMCallRecord(
                session_id=session_id,
                user_id=user_id,
                workflow_step=workflow_step,
                agent_name=agent_name,
                latency_ms=latency_ms,
                success=False,
                error_message=str(e),
                tags=tags or []
            )

            llm_call_collector.add_record(record)

        raise


def create_llm_call_record(
    session_id: str,
    user_id: str,
    workflow_step: str,
    agent_name: Optional[str],
    provider: str,
    model: str,
    input_messages: List[Dict[str, Any]],
    output_text: str,
    usage: Optional[Dict[str, int]] = None,
    latency_ms: Optional[float] = None,
    temperature: float = 0.7,
    success: bool = True,
    error_message: Optional[str] = None,
    tags: Optional[List[str]] = None,
    custom_metadata: Optional[Dict[str, Any]] = None
) -> LLMCallRecord:
    """
    LLM 호출 레코드를 수동으로 생성

    LLM 응답 객체에서 직접 정보를 추출할 때 사용
    """
    record = LLMCallRecord(
        session_id=session_id,
        user_id=user_id,
        workflow_step=workflow_step,
        agent_name=agent_name,
        provider=provider,
        model=model,
        temperature=temperature,
        input_messages=input_messages,
        output_text=output_text,
        prompt_tokens=usage.get("prompt_tokens") if usage else None,
        completion_tokens=usage.get("completion_tokens") if usage else None,
        total_tokens=usage.get("total_tokens") if usage else None,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
        tags=tags or [],
        custom_metadata=custom_metadata or {}
    )

    if llm_call_collector.is_enabled():
        llm_call_collector.add_record(record)

    return record
