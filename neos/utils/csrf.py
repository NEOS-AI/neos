"""
CSRF (Cross-Site Request Forgery) 보호 유틸리티
- CSRF 토큰 생성
- CSRF 토큰 검증
"""
import secrets
import hmac
import hashlib
from typing import Optional
from datetime import datetime, timedelta

from neos.config.settings import settings


def generate_csrf_token() -> str:
    """
    CSRF 토큰 생성 (URL-safe)

    Returns:
        32바이트 랜덤 토큰 (URL-safe base64)
    """
    return secrets.token_urlsafe(32)


def create_csrf_token_with_signature(session_id: str) -> str:
    """
    세션 ID와 연결된 CSRF 토큰 생성 (HMAC 서명 포함)

    Args:
        session_id: 세션 ID

    Returns:
        서명된 CSRF 토큰 (토큰:서명 형식)
    """
    # 랜덤 토큰 생성
    token = secrets.token_urlsafe(32)

    # 현재 시간 (토큰 만료 방지)
    timestamp = str(int(datetime.now().timestamp()))

    # 서명할 데이터: token:session_id:timestamp
    message = f"{token}:{session_id}:{timestamp}"

    # HMAC 서명 생성
    signature = hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    # 토큰:타임스탬프:서명 형식으로 반환
    return f"{token}:{timestamp}:{signature}"


def verify_csrf_token(
    csrf_token: str,
    session_id: str,
    max_age_seconds: int = 3600
) -> bool:
    """
    CSRF 토큰 검증

    Args:
        csrf_token: 검증할 CSRF 토큰
        session_id: 세션 ID
        max_age_seconds: 최대 유효 시간 (기본: 1시간)

    Returns:
        유효성 여부
    """
    try:
        # 토큰 파싱
        parts = csrf_token.split(":")
        if len(parts) != 3:
            return False

        token, timestamp, signature = parts

        # 타임스탬프 검증
        token_time = int(timestamp)
        current_time = int(datetime.now().timestamp())

        if current_time - token_time > max_age_seconds:
            return False  # 토큰 만료

        # 서명 재생성
        message = f"{token}:{session_id}:{timestamp}"
        expected_signature = hmac.new(
            settings.JWT_SECRET_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        # 서명 비교 (타이밍 공격 방지)
        return hmac.compare_digest(signature, expected_signature)

    except Exception as e:
        return False


def verify_csrf_token_simple(csrf_token: str, stored_token: str) -> bool:
    """
    간단한 CSRF 토큰 검증 (타이밍 공격 방지)

    Args:
        csrf_token: 요청에서 받은 토큰
        stored_token: 세션에 저장된 토큰

    Returns:
        일치 여부
    """
    if not csrf_token or not stored_token:
        return False

    return hmac.compare_digest(csrf_token, stored_token)
