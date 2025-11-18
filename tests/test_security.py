"""
Security 유틸리티 단위 테스트
"""
import pytest
from neos.utils.security import (
    hash_password,
    verify_password,
    validate_password_strength,
    generate_api_key,
    hash_api_key,
    hash_token,
    generate_session_id
)


class TestPasswordHashing:
    """비밀번호 해싱 테스트"""

    def test_hash_password(self):
        """비밀번호 해싱 테스트"""
        password = "SecurePassword123!"
        hashed = hash_password(password)

        assert hashed is not None
        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt prefix

    def test_verify_password_correct(self):
        """올바른 비밀번호 검증 테스트"""
        password = "SecurePassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """잘못된 비밀번호 검증 테스트"""
        password = "SecurePassword123!"
        wrong_password = "WrongPassword123!"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_different_hashes_for_same_password(self):
        """같은 비밀번호라도 다른 해시 생성 (salt)"""
        password = "SecurePassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestPasswordValidation:
    """비밀번호 강도 검증 테스트"""

    def test_valid_password(self):
        """유효한 비밀번호"""
        valid, message = validate_password_strength("SecurePass123!")
        assert valid is True
        assert message == ""

    def test_password_too_short(self):
        """너무 짧은 비밀번호"""
        valid, message = validate_password_strength("Short1!")
        assert valid is False
        assert "최소 8자" in message

    def test_password_no_uppercase(self):
        """대문자 없음"""
        valid, message = validate_password_strength("securepass123!")
        assert valid is False
        assert "대문자" in message

    def test_password_no_lowercase(self):
        """소문자 없음"""
        valid, message = validate_password_strength("SECUREPASS123!")
        assert valid is False
        assert "소문자" in message

    def test_password_no_digit(self):
        """숫자 없음"""
        valid, message = validate_password_strength("SecurePass!")
        assert valid is False
        assert "숫자" in message

    def test_password_no_special(self):
        """특수문자 없음"""
        valid, message = validate_password_strength("SecurePass123")
        assert valid is False
        assert "특수문자" in message


class TestAPIKeyGeneration:
    """API 키 생성 테스트"""

    def test_generate_api_key(self):
        """API 키 생성 테스트"""
        full_key, key_hash, key_prefix = generate_api_key()

        assert full_key is not None
        assert key_hash is not None
        assert key_prefix is not None

        # prefix 확인
        assert full_key.startswith("neos_")
        assert key_prefix.startswith("neos_")
        assert key_prefix.endswith("...")

        # 길이 확인 (32 bytes hex = 64 chars + prefix)
        assert len(full_key) > 64

    def test_generate_unique_api_keys(self):
        """각 API 키는 유니크해야 함"""
        key1, hash1, prefix1 = generate_api_key()
        key2, hash2, prefix2 = generate_api_key()

        assert key1 != key2
        assert hash1 != hash2

    def test_hash_api_key(self):
        """API 키 해싱 테스트"""
        api_key = "neos_test_key_12345"
        hashed = hash_api_key(api_key)

        assert hashed is not None
        assert len(hashed) == 64  # SHA-256 hex
        assert hashed != api_key

    def test_hash_api_key_consistent(self):
        """같은 키는 같은 해시"""
        api_key = "neos_test_key_12345"
        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)

        assert hash1 == hash2


class TestTokenHashing:
    """토큰 해싱 테스트"""

    def test_hash_token(self):
        """토큰 해싱 테스트"""
        token = "some_refresh_token_12345"
        hashed = hash_token(token)

        assert hashed is not None
        assert len(hashed) == 64  # SHA-256 hex
        assert hashed != token

    def test_hash_token_consistent(self):
        """같은 토큰은 같은 해시"""
        token = "some_refresh_token_12345"
        hash1 = hash_token(token)
        hash2 = hash_token(token)

        assert hash1 == hash2


class TestSessionID:
    """세션 ID 생성 테스트"""

    def test_generate_session_id(self):
        """세션 ID 생성 테스트"""
        session_id = generate_session_id()

        assert session_id is not None
        assert len(session_id) > 0

    def test_generate_unique_session_ids(self):
        """각 세션 ID는 유니크해야 함"""
        id1 = generate_session_id()
        id2 = generate_session_id()

        assert id1 != id2
