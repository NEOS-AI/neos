"""
JWT 유틸리티 단위 테스트
"""
import pytest
from datetime import datetime, timedelta
import time
from neos.utils.jwt import (
    create_access_token,
    create_refresh_token,
    verify_token,
    decode_token_without_verification,
    is_token_expired,
    get_token_expiration
)


class TestAccessToken:
    """Access Token 테스트"""

    def test_create_access_token(self):
        """Access Token 생성 테스트"""
        data = {"user_id": "test_user_123", "email": "test@example.com"}
        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_access_token(self):
        """Access Token 검증 테스트"""
        data = {"user_id": "test_user_123", "email": "test@example.com"}
        token = create_access_token(data)

        payload = verify_token(token, token_type="access")

        assert payload is not None
        assert payload["user_id"] == "test_user_123"
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_verify_access_token_wrong_type(self):
        """잘못된 토큰 타입으로 검증"""
        data = {"user_id": "test_user_123"}
        token = create_access_token(data)

        # refresh 타입으로 검증 시도
        payload = verify_token(token, token_type="refresh")

        assert payload is None

    def test_verify_invalid_token(self):
        """유효하지 않은 토큰 검증"""
        invalid_token = "invalid.token.here"
        payload = verify_token(invalid_token, token_type="access")

        assert payload is None

    def test_access_token_with_custom_expiration(self):
        """커스텀 만료 시간 Access Token"""
        data = {"user_id": "test_user_123"}
        expires_delta = timedelta(minutes=30)

        token = create_access_token(data, expires_delta=expires_delta)
        payload = verify_token(token, token_type="access")

        assert payload is not None
        exp_time = datetime.fromtimestamp(payload["exp"])
        iat_time = datetime.fromtimestamp(payload["iat"])

        # 약 30분 차이인지 확인 (초 단위 오차 허용)
        time_diff = (exp_time - iat_time).total_seconds()
        assert 1790 <= time_diff <= 1810  # 30분 ± 10초


class TestRefreshToken:
    """Refresh Token 테스트"""

    def test_create_refresh_token(self):
        """Refresh Token 생성 테스트"""
        data = {"user_id": "test_user_123"}
        token = create_refresh_token(data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_refresh_token(self):
        """Refresh Token 검증 테스트"""
        data = {"user_id": "test_user_123"}
        token = create_refresh_token(data)

        payload = verify_token(token, token_type="refresh")

        assert payload is not None
        assert payload["user_id"] == "test_user_123"
        assert payload["type"] == "refresh"
        assert "jti" in payload  # JWT ID
        assert "exp" in payload
        assert "iat" in payload

    def test_refresh_token_has_jti(self):
        """Refresh Token은 JWT ID를 가져야 함"""
        data = {"user_id": "test_user_123"}
        token = create_refresh_token(data)

        payload = verify_token(token, token_type="refresh")

        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_different_refresh_tokens_have_different_jti(self):
        """각 Refresh Token은 다른 JWT ID를 가져야 함"""
        data = {"user_id": "test_user_123"}
        token1 = create_refresh_token(data)
        token2 = create_refresh_token(data)

        payload1 = verify_token(token1, token_type="refresh")
        payload2 = verify_token(token2, token_type="refresh")

        assert payload1["jti"] != payload2["jti"]


class TestTokenDecoding:
    """토큰 디코딩 테스트"""

    def test_decode_without_verification(self):
        """검증 없이 디코딩"""
        data = {"user_id": "test_user_123", "email": "test@example.com"}
        token = create_access_token(data)

        payload = decode_token_without_verification(token)

        assert payload is not None
        assert payload["user_id"] == "test_user_123"
        assert payload["email"] == "test@example.com"

    def test_decode_invalid_token(self):
        """유효하지 않은 토큰 디코딩"""
        invalid_token = "invalid.token.here"
        payload = decode_token_without_verification(invalid_token)

        assert payload is None

    def test_is_token_expired_valid(self):
        """유효한 토큰의 만료 여부 확인"""
        data = {"user_id": "test_user_123"}
        token = create_access_token(data)

        assert is_token_expired(token) is False

    def test_is_token_expired_invalid(self):
        """유효하지 않은 토큰"""
        invalid_token = "invalid.token.here"
        assert is_token_expired(invalid_token) is True

    def test_is_token_expired_actually_expired(self):
        """실제로 만료된 토큰"""
        from unittest.mock import patch
        data = {"user_id": "test_user_123"}

        # 과거 시간으로 mock
        past_time = datetime.utcnow() - timedelta(days=1)
        with patch('neos.utils.jwt.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = past_time
            mock_datetime.fromtimestamp = datetime.fromtimestamp
            token = create_access_token(data, expires_delta=timedelta(minutes=15))

        # 현재 시간에서 확인하면 만료되어야 함
        assert is_token_expired(token) is True

    def test_get_token_expiration(self):
        """토큰 만료 시간 가져오기"""
        data = {"user_id": "test_user_123"}
        token = create_access_token(data)

        exp_time = get_token_expiration(token)

        assert exp_time is not None
        assert isinstance(exp_time, datetime)
        assert exp_time > datetime.utcnow()

    def test_get_token_expiration_invalid(self):
        """유효하지 않은 토큰의 만료 시간"""
        invalid_token = "invalid.token.here"
        exp_time = get_token_expiration(invalid_token)

        assert exp_time is None


class TestTokenExpiration:
    """토큰 만료 테스트"""

    def test_expired_token_verification_fails(self):
        """만료된 토큰 검증 실패"""
        from unittest.mock import patch
        data = {"user_id": "test_user_123"}

        # 과거 시간으로 토큰 생성
        past_time = datetime.utcnow() - timedelta(days=1)
        with patch('neos.utils.jwt.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = past_time
            mock_datetime.fromtimestamp = datetime.fromtimestamp
            token = create_access_token(data, expires_delta=timedelta(minutes=15))

        # 현재 시간에 검증하면 실패해야 함
        payload = verify_token(token, token_type="access")
        assert payload is None

    def test_token_expiration_time_correct(self):
        """토큰 만료 시간이 정확한지 확인"""
        data = {"user_id": "test_user_123"}
        expires_delta = timedelta(minutes=15)

        token = create_access_token(data, expires_delta=expires_delta)

        payload = verify_token(token, token_type="access")

        # Check that expiration is in the future
        exp_time_timestamp = payload["exp"]
        iat_time_timestamp = payload["iat"]

        # Calculate the difference in seconds
        time_diff = exp_time_timestamp - iat_time_timestamp

        # Should be approximately 15 minutes (900 seconds), allow 60 second tolerance
        expected_seconds = expires_delta.total_seconds()
        assert abs(time_diff - expected_seconds) <= 60, f"Time difference {time_diff} should be close to {expected_seconds}"
