"""
FastAPI 인증 의존성
- JWT 토큰 검증
- API 키 검증
- 현재 사용자 가져오기
"""
from typing import Optional, Union
from fastapi import Depends, HTTPException, Header, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from neos.database.connection import get_db
from neos.database.models import User, APIKey
from neos.api.services.auth_service import AuthService
from neos.utils.jwt import verify_token


# HTTP Bearer 스키마
security = HTTPBearer(auto_error=False)


async def get_current_user_from_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    JWT 토큰으로 현재 사용자 가져오기

    Args:
        credentials: HTTP Bearer 인증 정보
        db: 데이터베이스 세션

    Returns:
        User 객체 또는 None
    """
    if not credentials:
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
    jwt_user: Optional[User] = Depends(get_current_user_from_jwt),
    api_key_result: Optional[tuple] = Depends(get_current_user_from_api_key),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    JWT 또는 API 키로 현재 사용자 가져오기 (필수)

    Args:
        jwt_user: JWT로 인증된 사용자
        api_key_result: API 키로 인증된 결과
        db: 데이터베이스 세션

    Returns:
        User 객체

    Raises:
        HTTPException: 인증 실패 시
    """
    # JWT 인증 우선
    if jwt_user:
        return jwt_user

    # API 키 인증
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
    db: AsyncSession = Depends(get_db)
) -> tuple[APIKey, User]:
    """
    API 키 인증 필수 (JWT 허용 안 함)

    Args:
        request: FastAPI Request 객체 (IP 주소 추출용)
        x_api_key: API 키 헤더
        db: 데이터베이스 세션

    Returns:
        (APIKey, User) 튜플

    Raises:
        HTTPException: API 키가 유효하지 않은 경우
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

    return api_key_obj, user


async def get_optional_user(
    jwt_user: Optional[User] = Depends(get_current_user_from_jwt),
    api_key_result: Optional[tuple] = Depends(get_current_user_from_api_key),
) -> Optional[User]:
    """
    선택적 인증 (인증 안 해도 됨)

    Args:
        jwt_user: JWT로 인증된 사용자
        api_key_result: API 키로 인증된 결과

    Returns:
        User 객체 또는 None
    """
    if jwt_user:
        return jwt_user

    if api_key_result:
        _, user = api_key_result
        return user

    return None
