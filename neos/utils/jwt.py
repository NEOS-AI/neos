"""
JWT 토큰 생성 및 검증 유틸리티
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from jwt.exceptions import InvalidTokenError

from neos.config.settings import settings


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    JWT Access Token 생성

    Args:
        data: 토큰에 포함할 데이터 (user_id, email 등)
        expires_delta: 만료 시간 (기본값: 15분)

    Returns:
        JWT 토큰
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    JWT Refresh Token 생성

    Args:
        data: 토큰에 포함할 데이터 (user_id)
        expires_delta: 만료 시간 (기본값: 7일)

    Returns:
        JWT Refresh 토큰
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    # 추가 랜덤성을 위한 jti (JWT ID)
    jti = secrets.token_urlsafe(32)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
        "jti": jti
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    JWT 토큰 검증 및 디코드

    Args:
        token: JWT 토큰
        token_type: 토큰 타입 ("access" 또는 "refresh")

    Returns:
        디코드된 페이로드 또는 None (유효하지 않은 경우)
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        # 토큰 타입 검증
        if payload.get("type") != token_type:
            return None

        return payload

    except InvalidTokenError:
        return None


def decode_token_without_verification(token: str) -> Optional[Dict[str, Any]]:
    """
    토큰 검증 없이 디코드 (만료된 토큰의 정보를 확인할 때 사용)

    Args:
        token: JWT 토큰

    Returns:
        디코드된 페이로드 또는 None
    """
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False}
        )
        return payload
    except Exception:
        return None


def is_token_expired(token: str) -> bool:
    """
    토큰 만료 여부 확인

    Args:
        token: JWT 토큰

    Returns:
        만료 여부
    """
    payload = decode_token_without_verification(token)
    if not payload:
        return True

    exp = payload.get("exp")
    if not exp:
        return True

    return datetime.utcnow().timestamp() > exp


def get_token_expiration(token: str) -> Optional[datetime]:
    """
    토큰 만료 시간 반환

    Args:
        token: JWT 토큰

    Returns:
        만료 시간 또는 None
    """
    payload = decode_token_without_verification(token)
    if not payload:
        return None

    exp = payload.get("exp")
    if not exp:
        return None

    return datetime.fromtimestamp(exp)
