"""
커스텀 예외 클래스 정의

애플리케이션 전반에서 사용할 예외 클래스들을 정의합니다.
각 예외는 적절한 HTTP 상태 코드와 함께 사용됩니다.
"""


class NeosBaseException(Exception):
    """
    네오스 기본 예외 클래스

    모든 커스텀 예외는 이 클래스를 상속받습니다.
    """
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# ============================================================================
# 4xx Client Errors
# ============================================================================

class BusinessLogicError(NeosBaseException):
    """
    비즈니스 로직 오류 (400 Bad Request)

    예: 잘못된 요청, 유효성 검증 실패
    """
    pass


class AuthenticationError(NeosBaseException):
    """
    인증 오류 (401 Unauthorized)

    예: 유효하지 않은 토큰, 로그인 필요
    """
    pass


class AuthorizationError(NeosBaseException):
    """
    권한 오류 (403 Forbidden)

    예: 권한 부족, 접근 거부
    """
    pass


class ResourceNotFoundError(NeosBaseException):
    """
    리소스 없음 오류 (404 Not Found)

    예: 존재하지 않는 사용자, 쿼리, 문서
    """
    pass


class ConflictError(NeosBaseException):
    """
    충돌 오류 (409 Conflict)

    예: 중복된 이메일, 이미 존재하는 리소스
    """
    pass


class ValidationError(NeosBaseException):
    """
    유효성 검증 오류 (422 Unprocessable Entity)

    예: 잘못된 형식의 데이터, 필수 필드 누락
    """
    pass


class RateLimitExceededError(NeosBaseException):
    """
    요청 제한 초과 (429 Too Many Requests)

    예: API 호출 횟수 초과, 로그인 시도 초과
    """
    pass


# ============================================================================
# 5xx Server Errors
# ============================================================================

class InternalServerError(NeosBaseException):
    """
    내부 서버 오류 (500 Internal Server Error)

    예: 예상치 못한 오류, 처리 실패
    """
    pass


class ExternalServiceError(NeosBaseException):
    """
    외부 서비스 오류 (502 Bad Gateway)

    예: OpenAI API 오류, Tavily API 오류, 외부 API 장애
    """
    pass


class ServiceUnavailableError(NeosBaseException):
    """
    서비스 이용 불가 (503 Service Unavailable)

    예: 유지보수 중, 과부하, Circuit Breaker 활성화
    """
    pass


class TimeoutError(NeosBaseException):
    """
    타임아웃 오류 (504 Gateway Timeout)

    예: 에이전트 실행 타임아웃, 외부 API 응답 지연
    """
    pass


# ============================================================================
# 도메인별 예외
# ============================================================================

class DatabaseError(InternalServerError):
    """
    데이터베이스 오류

    예: 연결 실패, 쿼리 오류, 트랜잭션 실패
    """
    pass


class CacheError(InternalServerError):
    """
    캐시 오류

    예: Redis 연결 실패, 캐시 읽기/쓰기 오류
    """
    pass


class AgentExecutionError(InternalServerError):
    """
    에이전트 실행 오류

    예: 에이전트 실패, 워크플로우 오류
    """
    pass


class LLMError(ExternalServiceError):
    """
    LLM API 오류

    예: OpenAI API 오류, Anthropic API 오류, 토큰 제한 초과
    """
    pass


class SearchAPIError(ExternalServiceError):
    """
    검색 API 오류

    예: Tavily API 오류, 검색 실패
    """
    pass


# ============================================================================
# 유틸리티 함수
# ============================================================================

def get_exception_status_code(exc: Exception) -> int:
    """
    예외에 해당하는 HTTP 상태 코드 반환

    Args:
        exc: 예외 객체

    Returns:
        int: HTTP 상태 코드
    """
    exception_map = {
        BusinessLogicError: 400,
        AuthenticationError: 401,
        AuthorizationError: 403,
        ResourceNotFoundError: 404,
        ConflictError: 409,
        ValidationError: 422,
        RateLimitExceededError: 429,
        InternalServerError: 500,
        ExternalServiceError: 502,
        ServiceUnavailableError: 503,
        TimeoutError: 504,
        DatabaseError: 500,
        CacheError: 500,
        AgentExecutionError: 500,
        LLMError: 502,
        SearchAPIError: 502,
    }

    for exc_class, status_code in exception_map.items():
        if isinstance(exc, exc_class):
            return status_code

    # 기본값: 500 Internal Server Error
    return 500


def is_client_error(exc: Exception) -> bool:
    """
    클라이언트 오류(4xx)인지 확인

    Args:
        exc: 예외 객체

    Returns:
        bool: 클라이언트 오류 여부
    """
    status_code = get_exception_status_code(exc)
    return 400 <= status_code < 500


def is_server_error(exc: Exception) -> bool:
    """
    서버 오류(5xx)인지 확인

    Args:
        exc: 예외 객체

    Returns:
        bool: 서버 오류 여부
    """
    status_code = get_exception_status_code(exc)
    return 500 <= status_code < 600
