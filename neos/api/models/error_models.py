"""
표준화된 에러 응답 모델

모든 에이전트와 API에서 일관된 에러 응답 형식을 제공합니다.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class ErrorCode(str, Enum):
    """에러 코드 열거형"""

    # 일반 에러 (1000-1999)
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # 인증/인가 에러 (2000-2999)
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

    # 에이전트 에러 (3000-3999)
    AGENT_EXECUTION_FAILED = "AGENT_EXECUTION_FAILED"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    AGENT_DEGRADED = "AGENT_DEGRADED"

    # 워크플로우 에러 (4000-4999)
    WORKFLOW_EXECUTION_FAILED = "WORKFLOW_EXECUTION_FAILED"
    WORKFLOW_TIMEOUT = "WORKFLOW_TIMEOUT"
    INVALID_WORKFLOW_STATE = "INVALID_WORKFLOW_STATE"
    CHECKPOINT_ERROR = "CHECKPOINT_ERROR"

    # 외부 서비스 에러 (5000-5999)
    LLM_API_ERROR = "LLM_API_ERROR"
    SEARCH_API_ERROR = "SEARCH_API_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    CACHE_ERROR = "CACHE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

    # 리소스 에러 (6000-6999)
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    STORAGE_FULL = "STORAGE_FULL"


class ErrorSeverity(str, Enum):
    """에러 심각도"""
    LOW = "low"  # 경고, 일부 기능 저하
    MEDIUM = "medium"  # 에러, 요청 실패했지만 재시도 가능
    HIGH = "high"  # 심각한 에러, 시스템 일부 불가용
    CRITICAL = "critical"  # 치명적 에러, 시스템 전체 불가용


class ErrorDetail(BaseModel):
    """상세 에러 정보"""

    field: Optional[str] = Field(None, description="에러가 발생한 필드명")
    message: str = Field(..., description="에러 메시지")
    value: Optional[Any] = Field(None, description="에러를 발생시킨 값")


class ErrorResponse(BaseModel):
    """
    표준화된 에러 응답 모델

    모든 API 에러는 이 형식으로 반환됩니다.
    """

    success: bool = Field(False, description="성공 여부 (항상 False)")

    error_code: ErrorCode = Field(..., description="에러 코드")

    error_message: str = Field(..., description="사용자에게 표시할 에러 메시지")

    severity: ErrorSeverity = Field(
        ErrorSeverity.MEDIUM,
        description="에러 심각도"
    )

    details: Optional[List[ErrorDetail]] = Field(
        None,
        description="상세 에러 정보 목록"
    )

    retry_after: Optional[int] = Field(
        None,
        description="재시도까지 대기 시간 (초)"
    )

    support_reference: Optional[str] = Field(
        None,
        description="고객 지원 참조 ID"
    )

    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="에러 발생 시각 (UTC)"
    )

    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="추가 메타데이터"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error_code": "AGENT_EXECUTION_FAILED",
                "error_message": "검색 에이전트 실행 중 오류가 발생했습니다.",
                "severity": "medium",
                "details": [
                    {
                        "field": "query",
                        "message": "검색 쿼리가 너무 짧습니다",
                        "value": "AI"
                    }
                ],
                "retry_after": 5,
                "timestamp": "2025-01-19T10:30:00Z",
                "metadata": {
                    "agent": "multi_query_search",
                    "execution_time": 2.5
                }
            }
        }


class AgentErrorResponse(ErrorResponse):
    """
    에이전트 전용 에러 응답

    에이전트 실행 중 발생한 에러에 대한 추가 정보를 제공합니다.
    """

    agent_name: str = Field(..., description="에러가 발생한 에이전트 이름")

    degraded: bool = Field(
        False,
        description="Graceful degradation 여부 (Circuit Breaker 등)"
    )

    circuit_breaker_state: Optional[str] = Field(
        None,
        description="Circuit Breaker 상태 (open, half_open, closed)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error_code": "CIRCUIT_BREAKER_OPEN",
                "error_message": "에이전트가 일시적으로 비활성화되었습니다. 잠시 후 다시 시도해주세요.",
                "severity": "low",
                "agent_name": "hyper_deep_research",
                "degraded": True,
                "circuit_breaker_state": "open",
                "retry_after": 60,
                "timestamp": "2025-01-19T10:30:00Z"
            }
        }


def create_error_response(
    error_code: ErrorCode,
    error_message: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    details: Optional[List[ErrorDetail]] = None,
    retry_after: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> ErrorResponse:
    """
    에러 응답 생성 헬퍼 함수

    Args:
        error_code: 에러 코드
        error_message: 에러 메시지
        severity: 심각도
        details: 상세 정보
        retry_after: 재시도 대기 시간
        metadata: 메타데이터

    Returns:
        ErrorResponse: 표준화된 에러 응답
    """
    return ErrorResponse(
        error_code=error_code,
        error_message=error_message,
        severity=severity,
        details=details,
        retry_after=retry_after,
        metadata=metadata
    )


def create_agent_error_response(
    agent_name: str,
    error_code: ErrorCode,
    error_message: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    degraded: bool = False,
    circuit_breaker_state: Optional[str] = None,
    details: Optional[List[ErrorDetail]] = None,
    retry_after: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> AgentErrorResponse:
    """
    에이전트 에러 응답 생성 헬퍼 함수

    Args:
        agent_name: 에이전트 이름
        error_code: 에러 코드
        error_message: 에러 메시지
        severity: 심각도
        degraded: Graceful degradation 여부
        circuit_breaker_state: Circuit Breaker 상태
        details: 상세 정보
        retry_after: 재시도 대기 시간
        metadata: 메타데이터

    Returns:
        AgentErrorResponse: 에이전트 에러 응답
    """
    return AgentErrorResponse(
        agent_name=agent_name,
        error_code=error_code,
        error_message=error_message,
        severity=severity,
        degraded=degraded,
        circuit_breaker_state=circuit_breaker_state,
        details=details,
        retry_after=retry_after,
        metadata=metadata
    )


def exception_to_error_response(
    exception: Exception,
    default_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
    default_message: str = "예상치 못한 오류가 발생했습니다.",
    severity: ErrorSeverity = ErrorSeverity.HIGH
) -> ErrorResponse:
    """
    예외를 에러 응답으로 변환

    Args:
        exception: 발생한 예외
        default_code: 기본 에러 코드
        default_message: 기본 에러 메시지
        severity: 심각도

    Returns:
        ErrorResponse: 표준화된 에러 응답
    """
    # 예외 타입별 매핑
    error_mappings = {
        ValueError: (ErrorCode.VALIDATION_ERROR, "입력값이 올바르지 않습니다."),
        TimeoutError: (ErrorCode.AGENT_TIMEOUT, "작업 시간이 초과되었습니다."),
        ConnectionError: (ErrorCode.EXTERNAL_SERVICE_ERROR, "외부 서비스 연결에 실패했습니다."),
    }

    error_code, error_message = error_mappings.get(
        type(exception),
        (default_code, default_message)
    )

    return ErrorResponse(
        error_code=error_code,
        error_message=error_message,
        severity=severity,
        details=[
            ErrorDetail(
                message=str(exception)
            )
        ]
    )
