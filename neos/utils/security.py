"""
보안 관련 유틸리티 함수
- 비밀번호 해싱 및 검증
- API 키 생성 및 해싱
- 토큰 해싱
"""
import hashlib
import secrets
import re
import bcrypt
from typing import Tuple

from neos.config.settings import settings


def hash_password(password: str) -> str:
    """
    비밀번호를 bcrypt로 해싱

    Args:
        password: 평문 비밀번호

    Returns:
        해시된 비밀번호
    """
    # bcrypt는 72 bytes까지만 지원하므로 truncate
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    비밀번호 검증

    Args:
        plain_password: 평문 비밀번호
        hashed_password: 해시된 비밀번호

    Returns:
        일치 여부
    """
    # bcrypt는 72 bytes까지만 지원하므로 truncate
    password_bytes = plain_password.encode('utf-8')[:72]
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    비밀번호 강도 검증

    Args:
        password: 검증할 비밀번호

    Returns:
        (유효성 여부, 에러 메시지)
    """
    password_bytes = len(password.encode('utf-8'))
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"비밀번호는 최소 {settings.PASSWORD_MIN_LENGTH}자 이상이어야 합니다."

    # bcrypt has a 72-byte maximum password length
    if password_bytes > settings.PASSWORD_MAX_LENGTH:
        print(f"[DEBUG] Password too long: {password_bytes} bytes > {settings.PASSWORD_MAX_LENGTH} bytes")
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
        - 해시: DB에 저장 (bcrypt)
        - prefix: UI에 표시용
    """
    # 랜덤 바이트 생성
    random_bytes = secrets.token_bytes(settings.API_KEY_LENGTH)

    # hex로 변환
    key_hex = random_bytes.hex()

    # prefix 추가
    full_key = f"{settings.API_KEY_PREFIX}{key_hex}"

    # 해시 생성 (bcrypt로 변경 - 보안 강화)
    # bcrypt는 자동으로 salt를 생성하고 느린 해싱을 사용하여 brute-force 공격 방지
    key_hash = bcrypt.hashpw(full_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # prefix (표시용, 처음 12자)
    key_prefix = full_key[:12] + "..."

    return full_key, key_hash, key_prefix


def hash_api_key(api_key: str) -> str:
    """
    API 키를 bcrypt로 해싱

    Note: 이 함수는 새로운 해시 생성용이 아닌,
    기존 해시와 비교를 위한 용도입니다.
    실제 검증은 verify_api_key()를 사용하세요.

    Args:
        api_key: API 키

    Returns:
        해시된 API 키 (bcrypt)
    """
    return bcrypt.hashpw(api_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """
    API 키 검증 (bcrypt 사용)

    Args:
        api_key: 평문 API 키
        key_hash: bcrypt로 해시된 키

    Returns:
        일치 여부
    """
    try:
        return bcrypt.checkpw(api_key.encode('utf-8'), key_hash.encode('utf-8'))
    except Exception:
        # bcrypt 검증 실패 (잘못된 해시 형식 등)
        return False


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
