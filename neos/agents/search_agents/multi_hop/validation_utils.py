"""Validation and Error Handling Utilities for Multi-Hop Search

입력 검증, 에러 처리, 안정성 보장을 위한 유틸리티 함수들
"""

import logging
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    error_message: Optional[str] = None
    sanitized_value: Optional[str] = None


class InputValidator:
    """입력 검증 유틸리티"""

    # 제한값
    MAX_QUERY_LENGTH = 500
    MIN_QUERY_LENGTH = 3
    MAX_HOP_COUNT = 10
    MIN_CONFIDENCE = 0.0
    MAX_CONFIDENCE = 1.0

    @staticmethod
    def validate_query(query: str) -> ValidationResult:
        """쿼리 검증 및 정제

        Args:
            query: 사용자 쿼리

        Returns:
            ValidationResult (검증 결과 및 정제된 쿼리)
        """
        # None 체크
        if query is None:
            return ValidationResult(
                is_valid=False,
                error_message="Query is None"
            )

        # 타입 체크
        if not isinstance(query, str):
            # 문자열로 변환 시도
            try:
                query = str(query)
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Cannot convert query to string: {e}"
                )

        # 공백 제거
        sanitized = query.strip()

        # 빈 문자열 체크
        if not sanitized:
            return ValidationResult(
                is_valid=False,
                error_message="Query is empty after stripping whitespace"
            )

        # 길이 체크
        if len(sanitized) < InputValidator.MIN_QUERY_LENGTH:
            return ValidationResult(
                is_valid=False,
                error_message=f"Query too short (minimum {InputValidator.MIN_QUERY_LENGTH} characters)"
            )

        if len(sanitized) > InputValidator.MAX_QUERY_LENGTH:
            logger.warning(f"Query too long ({len(sanitized)} chars), truncating to {InputValidator.MAX_QUERY_LENGTH}")
            sanitized = sanitized[:InputValidator.MAX_QUERY_LENGTH]

        # 특수문자 체크 (SQL injection, XSS 방지)
        dangerous_patterns = [
            "<script",
            "javascript:",
            "onerror=",
            "onclick=",
            "DROP TABLE",
            "DELETE FROM",
            "INSERT INTO",
            "UPDATE SET",
        ]

        query_lower = sanitized.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in query_lower:
                logger.warning(f"Potentially dangerous pattern detected: {pattern}")
                # 패턴 제거 (보안)
                sanitized = sanitized.replace(pattern, "")

        return ValidationResult(
            is_valid=True,
            sanitized_value=sanitized
        )

    @staticmethod
    def validate_confidence(confidence: float) -> ValidationResult:
        """신뢰도 값 검증

        Args:
            confidence: 신뢰도 (0.0 ~ 1.0)

        Returns:
            ValidationResult
        """
        # 타입 체크
        if not isinstance(confidence, (int, float)):
            return ValidationResult(
                is_valid=False,
                error_message=f"Confidence must be a number, got {type(confidence)}"
            )

        # 범위 체크
        if confidence < InputValidator.MIN_CONFIDENCE or confidence > InputValidator.MAX_CONFIDENCE:
            return ValidationResult(
                is_valid=False,
                error_message=f"Confidence must be between {InputValidator.MIN_CONFIDENCE} and {InputValidator.MAX_CONFIDENCE}, got {confidence}"
            )

        return ValidationResult(is_valid=True)

    @staticmethod
    def validate_hop_count(hop_count: int) -> ValidationResult:
        """Hop 수 검증

        Args:
            hop_count: Hop 수

        Returns:
            ValidationResult
        """
        # 타입 체크
        if not isinstance(hop_count, int):
            return ValidationResult(
                is_valid=False,
                error_message=f"Hop count must be an integer, got {type(hop_count)}"
            )

        # 범위 체크
        if hop_count < 0:
            return ValidationResult(
                is_valid=False,
                error_message=f"Hop count cannot be negative, got {hop_count}"
            )

        if hop_count > InputValidator.MAX_HOP_COUNT:
            return ValidationResult(
                is_valid=False,
                error_message=f"Hop count too large (maximum {InputValidator.MAX_HOP_COUNT}), got {hop_count}"
            )

        return ValidationResult(is_valid=True)


class ErrorHandler:
    """에러 처리 유틸리티"""

    @staticmethod
    def should_retry(exception: Exception, attempt: int, max_attempts: int) -> Tuple[bool, int]:
        """재시도 여부 결정

        Args:
            exception: 발생한 예외
            attempt: 현재 시도 횟수
            max_attempts: 최대 시도 횟수

        Returns:
            (재시도 여부, 대기 시간(초))
        """
        # 최대 시도 횟수 초과
        if attempt >= max_attempts:
            return False, 0

        # 재시도 불가능한 예외
        non_retryable_errors = [
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ]

        if any(isinstance(exception, err_type) for err_type in non_retryable_errors):
            logger.warning(f"Non-retryable error: {type(exception).__name__}")
            return False, 0

        # Exponential backoff 계산
        wait_time = min(2 ** attempt, 60)  # 최대 60초

        logger.info(f"Retryable error detected, will retry after {wait_time}s (attempt {attempt}/{max_attempts})")
        return True, wait_time

    @staticmethod
    def sanitize_error_message(error: Exception) -> str:
        """에러 메시지 정제 (민감정보 제거)

        Args:
            error: 예외 객체

        Returns:
            정제된 에러 메시지
        """
        error_msg = str(error)

        # API 키 같은 민감 정보 마스킹
        sensitive_patterns = [
            ("api_key=", "api_key=***"),
            ("token=", "token=***"),
            ("password=", "password=***"),
            ("secret=", "secret=***"),
        ]

        for pattern, replacement in sensitive_patterns:
            if pattern in error_msg.lower():
                # 패턴 이후 공백이나 &까지의 내용을 마스킹
                import re
                error_msg = re.sub(
                    f"{pattern}[^\\s&]*",
                    replacement,
                    error_msg,
                    flags=re.IGNORECASE
                )

        # 최대 길이 제한
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."

        return error_msg


class SafetyGuards:
    """안전 장치 (무한 루프, 리소스 고갈 방지)"""

    @staticmethod
    def check_timeout(start_time: float, timeout: float, operation_name: str) -> bool:
        """타임아웃 체크

        Args:
            start_time: 시작 시간 (time.time())
            timeout: 타임아웃 (초)
            operation_name: 작업 이름 (로깅용)

        Returns:
            타임아웃 발생 시 True
        """
        import time
        elapsed = time.time() - start_time

        if elapsed > timeout:
            logger.error(f"Operation '{operation_name}' timed out after {elapsed:.2f}s (limit: {timeout}s)")
            return True

        return False

    @staticmethod
    def validate_dag_acyclic(dependencies: dict) -> bool:
        """DAG 순환 참조 검증

        Args:
            dependencies: {node_id: [dependent_node_ids]}

        Returns:
            순환 참조 없으면 True
        """
        visited = set()
        rec_stack = set()

        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in dependencies.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    logger.error(f"Cycle detected: {node} -> {neighbor}")
                    return True

            rec_stack.remove(node)
            return False

        for node in dependencies:
            if node not in visited:
                if has_cycle(node):
                    return False

        return True
