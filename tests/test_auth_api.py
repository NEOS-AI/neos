"""
Auth API 통합 테스트
pytest-asyncio 필요
"""
import pytest
from httpx import AsyncClient
from fastapi import status

# 실제 테스트 시에는 test database를 사용해야 합니다
# 여기서는 테스트 구조만 제공합니다


class TestAuthAPIEndpoints:
    """Auth API 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        """회원가입 성공 테스트"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "SecurePass123!",
                "username": "testuser"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert "user_id" in data["data"]
        assert data["data"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient):
        """중복 이메일 회원가입 실패"""
        # 첫 번째 회원가입
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "SecurePass123!",
            }
        )

        # 두 번째 회원가입 (중복)
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "SecurePass123!",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_register_weak_password(self, client: AsyncClient):
        """약한 비밀번호 회원가입 실패"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "weak",
            }
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        """로그인 성공 테스트"""
        # 먼저 회원가입
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "login@example.com",
                "password": "SecurePass123!",
            }
        )

        # 로그인
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "login@example.com",
                "password": "SecurePass123!",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        """잘못된 비밀번호 로그인 실패"""
        # 먼저 회원가입
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "wrong@example.com",
                "password": "SecurePass123!",
            }
        )

        # 잘못된 비밀번호로 로그인
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "wrong@example.com",
                "password": "WrongPassword123!",
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_current_user(self, client: AsyncClient):
        """현재 사용자 정보 조회"""
        # 회원가입 및 로그인
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "current@example.com",
                "password": "SecurePass123!",
            }
        )

        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "current@example.com",
                "password": "SecurePass123!",
            }
        )

        access_token = login_response.json()["access_token"]

        # 사용자 정보 조회
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == "current@example.com"
        assert "user_id" in data

    @pytest.mark.asyncio
    async def test_get_current_user_no_auth(self, client: AsyncClient):
        """인증 없이 사용자 정보 조회 실패"""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient):
        """로그아웃 테스트"""
        # 회원가입 및 로그인
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logout@example.com",
                "password": "SecurePass123!",
            }
        )

        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "logout@example.com",
                "password": "SecurePass123!",
            }
        )

        refresh_token = login_response.json()["refresh_token"]

        # 로그아웃
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token}
        )

        assert response.status_code == status.HTTP_200_OK

        # 로그아웃 후 같은 refresh token으로 갱신 시도 (실패해야 함)
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )

        assert refresh_response.status_code == status.HTTP_401_UNAUTHORIZED


class TestAPIKeyManagement:
    """API 키 관리 테스트"""

    @pytest.mark.asyncio
    async def test_create_api_key(self, client: AsyncClient, auth_headers: dict):
        """API 키 생성 테스트"""
        response = await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={
                "name": "Test API Key",
                "description": "For testing",
                "rate_limit": 100
            }
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert "key" in data["data"]  # 1회만 표시
        assert data["data"]["name"] == "Test API Key"

    @pytest.mark.asyncio
    async def test_list_api_keys(self, client: AsyncClient, auth_headers: dict):
        """API 키 목록 조회 테스트"""
        # API 키 생성
        await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={"name": "Test Key 1"}
        )

        # 목록 조회
        response = await client.get(
            "/api/v1/auth/api-keys",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "api_keys" in data
        assert len(data["api_keys"]) > 0

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, client: AsyncClient, auth_headers: dict):
        """API 키 무효화 테스트"""
        # API 키 생성
        create_response = await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={"name": "Test Key to Revoke"}
        )

        api_key_id = create_response.json()["data"]["id"]

        # 무효화
        response = await client.delete(
            f"/api/v1/auth/api-keys/{api_key_id}",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_use_api_key_for_authentication(self, client: AsyncClient):
        """API 키로 인증 테스트"""
        # 회원가입 및 로그인
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "apikey@example.com",
                "password": "SecurePass123!",
            }
        )

        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "apikey@example.com",
                "password": "SecurePass123!",
            }
        )

        access_token = login_response.json()["access_token"]

        # API 키 생성
        create_response = await client.post(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Test API Key"}
        )

        api_key = create_response.json()["data"]["key"]

        # API 키로 사용자 정보 조회
        response = await client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == status.HTTP_200_OK
