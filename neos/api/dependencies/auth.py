"""
FastAPI 인증 의존성
- JWT 토큰 검증
- API 키 검증
- API 게이트웨이 X-User-ID 헤더 검증
- 현재 사용자 가져오기
- API 키 Scope 검증
"""
from typing import Optional, List
from ipaddress import ip_address, ip_network, AddressValueError
from fastapi import Depends, HTTPException, Header, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from neos.database.connection import get_db
from neos.database.models import User, APIKey
from neos.api.services.auth_service import AuthService
from neos.utils.jwt import verify_token
from neos.utils.rate_limiter import rate_limiter
from neos.config.settings import settings


# 로거 설정
logger = logging.getLogger(__name__)


# HTTP Bearer 스키마
security = HTTPBearer(auto_error=False)


# ============================================================================
# API 게이트웨이 인증 (X-User-ID 헤더 기반)
# ============================================================================

def _is_ip_in_trusted_list(client_ip: str, trusted_ips: List[str]) -> bool:
    """
    클라이언트 IP가 신뢰할 수 있는 IP 목록에 있는지 확인
    CIDR 표기법과 단일 IP 모두 지원

    Args:
        client_ip: 검사할 클라이언트 IP
        trusted_ips: 신뢰할 수 있는 IP 또는 CIDR 목록

    Returns:
        신뢰할 수 있는 IP이면 True
    """
    try:
        client_addr = ip_address(client_ip)
    except (AddressValueError, ValueError):
        logger.warning(f"Invalid client IP address format: {client_ip}")
        return False

    for trusted in trusted_ips:
        try:
            # CIDR 표기법 (예: 10.0.0.0/8)
            if "/" in trusted:
                if client_addr in ip_network(trusted, strict=False):
                    return True
            else:
                # 단일 IP (예: 127.0.0.1)
                if client_addr == ip_address(trusted):
                    return True
        except (AddressValueError, ValueError) as e:
            logger.warning(f"Invalid trusted IP/CIDR format: {trusted}, error: {e}")
            continue

    return False


def _is_trusted_gateway_request(request: Request) -> bool:
    """
    요청이 신뢰할 수 있는 게이트웨이에서 왔는지 확인

    보안 주의: 게이트웨이 신뢰 확인 시에는 X-Forwarded-For, X-Real-IP 헤더를 사용하지 않습니다.
    이 헤더들은 클라이언트가 조작할 수 있으므로, 실제 TCP 연결 IP(request.client.host)만 신뢰합니다.

    Args:
        request: FastAPI Request 객체

    Returns:
        신뢰할 수 있는 요청이면 True
    """
    if not settings.API_GATEWAY_ENABLED:
        return False

    # 신뢰할 수 있는 IP 목록이 비어있으면 모든 IP 허용 (개발 환경용)
    if not settings.API_GATEWAY_TRUSTED_IPS:
        logger.warning(
            "API_GATEWAY_TRUSTED_IPS is empty - all IPs are trusted. "
            "This is insecure for production!"
        )
        return True

    # 보안: 실제 TCP 연결 IP만 사용 (헤더 조작 방지)
    # X-Forwarded-For, X-Real-IP 헤더는 게이트웨이 신뢰 확인에 사용하지 않음
    if not request.client:
        logger.warning("Cannot determine client IP for gateway trust check")
        return False

    client_ip = request.client.host

    is_trusted = _is_ip_in_trusted_list(client_ip, settings.API_GATEWAY_TRUSTED_IPS)
    if not is_trusted:
        logger.debug(f"Request from untrusted IP: {client_ip}")

    return is_trusted


def _get_gateway_user_id_header() -> str:
    """
    게이트웨이 User ID 헤더 이름 반환
    설정에서 동적으로 헤더 이름을 가져옵니다.
    """
    return getattr(settings, 'API_GATEWAY_USER_ID_HEADER', 'X-User-ID')


async def get_current_user_from_gateway(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    API 게이트웨이의 User-ID 헤더로 현재 사용자 가져오기

    게이트웨이 모드가 활성화되어 있고, 신뢰할 수 있는 IP에서 요청이 오면
    User-ID 헤더의 값을 신뢰하여 사용자를 조회합니다.

    Note:
        헤더 이름은 API_GATEWAY_USER_ID_HEADER 설정으로 변경 가능합니다.
        기본값: X-User-ID

    Args:
        request: FastAPI Request 객체
        db: 데이터베이스 세션

    Returns:
        User 객체 또는 None
    """
    # 게이트웨이 모드가 비활성화되어 있으면 None 반환
    if not settings.API_GATEWAY_ENABLED:
        return None

    # 동적으로 헤더 이름 가져오기
    header_name = _get_gateway_user_id_header()
    x_user_id = request.headers.get(header_name)

    # User-ID 헤더가 없으면 None 반환
    if not x_user_id:
        return None

    # 신뢰할 수 있는 게이트웨이 요청인지 확인
    if not _is_trusted_gateway_request(request):
        logger.warning(
            f"Untrusted gateway request with {header_name} header: "
            f"user_id={x_user_id}, client={request.client.host if request.client else 'unknown'}"
        )
        return None

    # 사용자 조회
    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(x_user_id)

    if user:
        logger.info(
            f"Gateway auth success: user_id={x_user_id}, "
            f"client={request.client.host if request.client else 'unknown'}"
        )
    else:
        logger.warning(
            f"Gateway auth failed - user not found: user_id={x_user_id}, "
            f"client={request.client.host if request.client else 'unknown'}"
        )

    return user


async def get_current_user_from_jwt(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    JWT 토큰으로 현재 사용자 가져오기

    Args:
        request: FastAPI Request 객체
        credentials: HTTP Bearer 인증 정보
        db: 데이터베이스 세션

    Returns:
        User 객체 또는 None
    """
    if not credentials:
        return None

    # 게이트웨이 모드에서는 JWT 검증 스킵 (게이트웨이에서 이미 검증됨)
    if settings.API_GATEWAY_ENABLED and _is_trusted_gateway_request(request):
        logger.debug("Skipping JWT verification - gateway mode enabled")
        return None

    token = credentials.credentials

    # JWT 토큰 검증
    payload = verify_token(token, token_type="access")
    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    # 사용자 조회
    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    return user


async def get_current_user_from_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db)
) -> Optional[tuple[APIKey, User]]:
    """
    API 키로 현재 사용자 가져오기

    Args:
        request: FastAPI Request 객체 (IP 주소 추출용)
        x_api_key: API 키 헤더
        db: 데이터베이스 세션

    Returns:
        (APIKey, User) 튜플 또는 None
    """
    if not x_api_key:
        return None

    # 게이트웨이 모드에서는 API 키 검증 스킵 (게이트웨이에서 이미 검증됨)
    if settings.API_GATEWAY_ENABLED and _is_trusted_gateway_request(request):
        logger.debug("Skipping API key verification - gateway mode enabled")
        return None

    # 클라이언트 IP 주소 추출
    client_ip = request.client.host if request.client else None

    auth_service = AuthService(db)
    is_valid, api_key_obj, user = await auth_service.verify_api_key(
        x_api_key,
        client_ip=client_ip
    )

    if not is_valid or not api_key_obj or not user:
        return None

    return api_key_obj, user


async def get_current_user(
    request: Request,
    gateway_user: Optional[User] = Depends(get_current_user_from_gateway),
    jwt_user: Optional[User] = Depends(get_current_user_from_jwt),
    api_key_result: Optional[tuple] = Depends(get_current_user_from_api_key),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    게이트웨이, JWT 또는 API 키로 현재 사용자 가져오기 (필수)

    인증 우선순위:
    1. API 게이트웨이 X-User-ID 헤더 (게이트웨이 모드 활성화 시)
    2. JWT 토큰
    3. API 키

    Args:
        request: FastAPI Request 객체
        gateway_user: 게이트웨이로 인증된 사용자
        jwt_user: JWT로 인증된 사용자
        api_key_result: API 키로 인증된 결과
        db: 데이터베이스 세션

    Returns:
        User 객체

    Raises:
        HTTPException: 인증 실패 시
    """
    # 1. 게이트웨이 인증 우선 (가장 빠름)
    if gateway_user:
        logger.debug(f"User authenticated via gateway: {gateway_user.user_id}")
        return gateway_user

    # 2. JWT 인증
    if jwt_user:
        return jwt_user

    # 3. API 키 인증
    if api_key_result:
        _, user = api_key_result
        return user

    # 인증 실패
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다. JWT 토큰 또는 API 키를 제공해주세요.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    활성화된 사용자만 허용

    Args:
        current_user: 현재 사용자

    Returns:
        User 객체

    Raises:
        HTTPException: 비활성화된 사용자인 경우
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다."
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    관리자만 허용

    Args:
        current_user: 현재 사용자

    Returns:
        User 객체

    Raises:
        HTTPException: 관리자가 아닌 경우
    """
    if not current_user.is_admin and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    return current_user


async def require_api_key(
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
    check_rate_limit: bool = True
) -> tuple[APIKey, User]:
    """
    API 키 인증 필수 (JWT 허용 안 함) + Rate Limiting

    Args:
        request: FastAPI Request 객체 (IP 주소 추출용)
        x_api_key: API 키 헤더
        db: 데이터베이스 세션
        check_rate_limit: Rate limiting 체크 여부 (기본값: True)

    Returns:
        (APIKey, User) 튜플

    Raises:
        HTTPException: API 키가 유효하지 않거나 rate limit 초과 시
    """
    # 클라이언트 IP 주소 추출
    client_ip = request.client.host if request.client else None

    auth_service = AuthService(db)
    is_valid, api_key_obj, user = await auth_service.verify_api_key(
        x_api_key,
        client_ip=client_ip
    )

    if not is_valid or not api_key_obj or not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 API 키입니다.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Rate Limiting 체크
    if check_rate_limit:
        allowed, metadata = await rate_limiter.check_api_key_rate_limit(
            api_key_id=str(api_key_obj.id),
            rate_limit_per_minute=api_key_obj.rate_limit,
            max_requests_per_day=api_key_obj.max_requests_per_day
        )

        if not allowed:
            # Rate limit 헤더 추가
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "API 키 요청 제한을 초과했습니다.",
                    "limit": metadata["limit"],
                    "current": metadata["current_requests"],
                    "retry_after": metadata["retry_after"]
                },
                headers={
                    "X-RateLimit-Limit": str(metadata["limit"]),
                    "X-RateLimit-Remaining": str(metadata["remaining"]),
                    "X-RateLimit-Reset": str(metadata["reset_at"]),
                    "Retry-After": str(metadata["retry_after"])
                }
            )

        # Rate limit 정보를 request.state에 저장 (로깅/모니터링용)
        request.state.rate_limit_metadata = metadata

    return api_key_obj, user


async def get_optional_user(
    request: Request,
    gateway_user: Optional[User] = Depends(get_current_user_from_gateway),
    jwt_user: Optional[User] = Depends(get_current_user_from_jwt),
    api_key_result: Optional[tuple] = Depends(get_current_user_from_api_key),
) -> Optional[User]:
    """
    선택적 인증 (인증 안 해도 됨)

    인증 우선순위:
    1. API 게이트웨이 X-User-ID 헤더
    2. JWT 토큰
    3. API 키

    Args:
        request: FastAPI Request 객체
        gateway_user: 게이트웨이로 인증된 사용자
        jwt_user: JWT로 인증된 사용자
        api_key_result: API 키로 인증된 결과

    Returns:
        User 객체 또는 None
    """
    # 1. 게이트웨이 인증 우선
    if gateway_user:
        return gateway_user

    # 2. JWT 인증
    if jwt_user:
        return jwt_user

    # 3. API 키 인증
    if api_key_result:
        _, user = api_key_result
        return user

    return None


# ============================================================================
# API 키 Scope 검증
# ============================================================================

class ScopeChecker:
    """
    API 키 Scope 검증 의존성 클래스

    Usage:
        @router.get("/data", dependencies=[Depends(ScopeChecker(["data:read"]))])
        async def get_data():
            return {"data": "..."}
    """

    def __init__(self, required_scopes: List[str]):
        """
        Args:
            required_scopes: 필요한 권한 목록 (예: ["query:read", "chat:write"])
        """
        self.required_scopes = required_scopes

    async def __call__(
        self,
        request: Request,
        gateway_user: Optional[User] = Depends(get_current_user_from_gateway),
        jwt_user: Optional[User] = Depends(get_current_user_from_jwt),
        api_key_result: Optional[tuple] = Depends(get_current_user_from_api_key),
    ):
        """
        Scope 검증 실행

        - 게이트웨이 인증: 모든 scope 허용 (게이트웨이에서 이미 검증됨)
        - JWT 인증: 모든 scope 허용 (관리자 권한)
        - API 키 인증: API 키의 scopes에 required_scopes가 모두 포함되어야 함

        Raises:
            HTTPException: 권한 부족 시
        """
        # 게이트웨이 인증 사용자는 모든 scope 허용 (게이트웨이에서 이미 검증됨)
        if gateway_user:
            logger.debug(
                f"Gateway user {gateway_user.user_id} granted access - "
                f"required_scopes: {self.required_scopes}"
            )
            return

        # JWT 인증 사용자는 모든 scope 허용 (사용자 본인이 직접 로그인)
        if jwt_user:
            logger.debug(
                f"JWT user {jwt_user.user_id} granted access - "
                f"required_scopes: {self.required_scopes}"
            )
            return

        # API 키 인증
        if api_key_result:
            api_key_obj, user = api_key_result

            # API 키의 scopes 확인
            api_key_scopes = set(api_key_obj.scopes or [])
            required_scopes_set = set(self.required_scopes)

            # 필요한 모든 scope가 API 키에 포함되어 있는지 확인
            if required_scopes_set.issubset(api_key_scopes):
                logger.debug(
                    f"API key {api_key_obj.id} granted access - "
                    f"required: {self.required_scopes}, "
                    f"available: {list(api_key_scopes)}"
                )
                return

            # 권한 부족
            missing_scopes = required_scopes_set - api_key_scopes

            # 실패 로깅 (보안 모니터링)
            logger.warning(
                f"API key scope verification failed - "
                f"key_id: {api_key_obj.id}, "
                f"user_id: {user.user_id}, "
                f"required_scopes: {self.required_scopes}, "
                f"available_scopes: {list(api_key_scopes)}, "
                f"missing_scopes: {list(missing_scopes)}, "
                f"client_ip: {request.client.host if request.client else 'unknown'}"
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": "API 키에 필요한 권한이 없습니다.",
                    "required_scopes": self.required_scopes,
                    "missing_scopes": list(missing_scopes)
                }
            )

        # 인증되지 않음
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_scopes(scopes: List[str]):
    """
    API 키 Scope 검증 의존성 생성 헬퍼 함수

    Args:
        scopes: 필요한 권한 목록

    Returns:
        ScopeChecker 인스턴스

    Usage:
        @router.post("/documents", dependencies=[Depends(require_scopes(["document:write"]))])
        async def upload_document():
            return {"status": "uploaded"}
    """
    return ScopeChecker(scopes)


async def get_api_key_with_scope(
    required_scopes: List[str],
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db)
) -> tuple[APIKey, User]:
    """
    Scope 검증이 포함된 API 키 인증 (함수형 접근)

    Args:
        required_scopes: 필요한 권한 목록
        request: FastAPI Request 객체
        x_api_key: API 키 헤더
        db: 데이터베이스 세션

    Returns:
        (APIKey, User) 튜플

    Raises:
        HTTPException: API 키가 유효하지 않거나 권한이 부족한 경우

    Usage:
        async def my_endpoint(
            auth: tuple[APIKey, User] = Depends(
                lambda req, key, db: get_api_key_with_scope(
                    ["data:read"],
                    req,
                    key,
                    db
                )
            )
        ):
            api_key, user = auth
    """
    # API 키 검증
    api_key_obj, user = await require_api_key(request, x_api_key, db)

    # Scope 검증
    api_key_scopes = set(api_key_obj.scopes or [])
    required_scopes_set = set(required_scopes)

    if not required_scopes_set.issubset(api_key_scopes):
        missing_scopes = required_scopes_set - api_key_scopes

        logger.warning(
            f"API key scope verification failed - "
            f"key_id: {api_key_obj.id}, "
            f"required: {required_scopes}, "
            f"missing: {list(missing_scopes)}"
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "insufficient_permissions",
                "message": "API 키에 필요한 권한이 없습니다.",
                "required_scopes": required_scopes,
                "missing_scopes": list(missing_scopes)
            }
        )

    return api_key_obj, user


# ============================================================================
# Rate Limiting 미들웨어
# ============================================================================

async def check_ip_rate_limit(
    request: Request,
    max_requests_per_minute: int = 60
):
    """
    IP 기반 Rate Limiting 의존성

    Args:
        request: FastAPI Request 객체
        max_requests_per_minute: 분당 최대 요청 수 (기본값: 60)

    Raises:
        HTTPException: Rate limit 초과 시

    Usage:
        @router.get("/public", dependencies=[Depends(check_ip_rate_limit)])
        async def public_endpoint():
            return {"message": "OK"}
    """
    client_ip = request.client.host if request.client else "unknown"

    allowed, metadata = await rate_limiter.check_ip_rate_limit(
        ip_address=client_ip,
        max_requests_per_minute=max_requests_per_minute
    )

    if not allowed:
        logger.warning(
            f"IP rate limit exceeded - "
            f"ip: {client_ip}, "
            f"requests: {metadata['current_requests']}/{metadata['limit']}"
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "요청 제한을 초과했습니다. 잠시 후 다시 시도해주세요.",
                "retry_after": metadata["retry_after"]
            },
            headers={
                "X-RateLimit-Limit": str(metadata["limit"]),
                "X-RateLimit-Remaining": str(metadata["remaining"]),
                "X-RateLimit-Reset": str(metadata["reset_at"]),
                "Retry-After": str(metadata["retry_after"])
            }
        )

    # Rate limit 정보 저장
    request.state.rate_limit_metadata = metadata


class RateLimitChecker:
    """
    커스텀 Rate Limiting 의존성 클래스

    Usage:
        @router.post("/data", dependencies=[Depends(RateLimitChecker(100, 60))])
        async def post_data():
            return {"status": "ok"}
    """

    def __init__(self, max_requests: int, window_seconds: int):
        """
        Args:
            max_requests: 최대 요청 수
            window_seconds: 시간 윈도우 (초)
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request):
        """Rate limit 체크 실행"""
        client_ip = request.client.host if request.client else "unknown"

        allowed, metadata = await rate_limiter.check_rate_limit(
            key=f"custom:{client_ip}",
            max_requests=self.max_requests,
            window_seconds=self.window_seconds
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "요청 제한을 초과했습니다.",
                    "retry_after": metadata["retry_after"]
                },
                headers={
                    "X-RateLimit-Limit": str(metadata["limit"]),
                    "X-RateLimit-Remaining": str(metadata["remaining"]),
                    "X-RateLimit-Reset": str(metadata["reset_at"]),
                    "Retry-After": str(metadata["retry_after"])
                }
            )

        request.state.rate_limit_metadata = metadata
