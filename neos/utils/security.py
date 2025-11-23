"""
보안 관련 유틸리티 함수
- 비밀번호 해싱 및 검증
- API 키 생성 및 해싱
- 토큰 해싱
"""
import hashlib
import secrets
import re
from passlib.context import CryptContext
from typing import Tuple

from neos.config.settings import settings


# bcrypt 컨텍스트 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    비밀번호를 bcrypt로 해싱

    Args:
        password: 평문 비밀번호

    Returns:
        해시된 비밀번호
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    비밀번호 검증

    Args:
        plain_password: 평문 비밀번호
        hashed_password: 해시된 비밀번호

    Returns:
        일치 여부
    """
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    비밀번호 강도 검증

    Args:
        password: 검증할 비밀번호

    Returns:
        (유효성 여부, 에러 메시지)
    """
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"비밀번호는 최소 {settings.PASSWORD_MIN_LENGTH}자 이상이어야 합니다."

    # bcrypt has a 72-byte maximum password length
    if len(password.encode('utf-8')) > settings.PASSWORD_MAX_LENGTH:
        return False, f"비밀번호는 최대 {settings.PASSWORD_MAX_LENGTH}바이트를 초과할 수 없습니다."

    if settings.PASSWORD_REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return False, "비밀번호에 대문자가 최소 1개 포함되어야 합니다."

    if settings.PASSWORD_REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return False, "비밀번호에 소문자가 최소 1개 포함되어야 합니다."

    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, "비밀번호에 숫자가 최소 1개 포함되어야 합니다."

    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "비밀번호에 특수문자가 최소 1개 포함되어야 합니다."

    return True, ""


def generate_api_key() -> Tuple[str, str, str]:
    """
    API 키 생성

    Returns:
        (전체 키, 해시, prefix) 튜플
        - 전체 키: 사용자에게 1회만 표시
        - 해시: DB에 저장
        - prefix: UI에 표시용
    """
    # 랜덤 바이트 생성
    random_bytes = secrets.token_bytes(settings.API_KEY_LENGTH)

    # hex로 변환
    key_hex = random_bytes.hex()

    # prefix 추가
    full_key = f"{settings.API_KEY_PREFIX}{key_hex}"

    # 해시 생성 (SHA-256)
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()

    # prefix (표시용, 처음 12자)
    key_prefix = full_key[:12] + "..."

    return full_key, key_hash, key_prefix


def hash_api_key(api_key: str) -> str:
    """
    API 키를 SHA-256으로 해싱

    Args:
        api_key: API 키

    Returns:
        해시된 API 키
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def hash_token(token: str) -> str:
    """
    토큰을 SHA-256으로 해싱 (Refresh Token용)

    Args:
        token: 토큰

    Returns:
        해시된 토큰
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_session_id() -> str:
    """
    세션 ID 생성

    Returns:
        랜덤 세션 ID
    """
    return secrets.token_urlsafe(32)
