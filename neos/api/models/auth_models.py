"""
인증 관련 Pydantic 모델
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
import re


class RegisterRequest(BaseModel):
    """회원가입 요청"""
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: Optional[str] = None

    @validator('password')
    def validate_password(cls, v):
        """비밀번호 기본 검증"""
        if len(v) < 8:
            raise ValueError('비밀번호는 최소 8자 이상이어야 합니다.')
        return v


class LoginRequest(BaseModel):
    """로그인 요청"""
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """토큰 갱신 요청"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """로그아웃 요청"""
    refresh_token: str


class UserResponse(BaseModel):
    """사용자 정보 응답"""
    user_id: str
    email: str
    username: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """토큰 응답"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Optional[dict] = None


class MessageResponse(BaseModel):
    """일반 메시지 응답"""
    success: bool
    message: str
    data: Optional[dict] = None


class CreateAPIKeyRequest(BaseModel):
    """API 키 생성 요청"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    scopes: Optional[List[str]] = Field(default_factory=list)
    rate_limit: int = Field(default=100, ge=1, le=10000)
    max_requests_per_day: Optional[int] = Field(None, ge=1)
    expires_days: Optional[int] = Field(None, ge=1, le=365)


class APIKeyResponse(BaseModel):
    """API 키 응답"""
    id: str
    key: Optional[str] = None  # 생성 시에만 포함
    prefix: str
    name: str
    scopes: List[str]
    rate_limit: int
    is_active: bool
    total_requests: int = 0
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str


class APIKeyListResponse(BaseModel):
    """API 키 목록 응답"""
    api_keys: List[APIKeyResponse]


# ============================================================================
# OAuth 관련 모델
# ============================================================================

class GoogleLoginRequest(BaseModel):
    """Google OAuth 로그인 요청"""
    google_token: str = Field(
        ...,
        description="Google ID Token from Google Sign-In",
        validation_alias="id_token"  # NextAuth에서 id_token으로 보내므로 호환성 지원
    )


class GoogleLinkRequest(BaseModel):
    """Google 계정 연결 요청"""
    google_token: str = Field(
        ...,
        description="Google ID Token from Google Sign-In",
        validation_alias="id_token"  # NextAuth에서 id_token으로 보내므로 호환성 지원
    )


class OAuthUnlinkRequest(BaseModel):
    """OAuth 계정 연결 해제 요청"""
    provider: str = Field(default="google", description="OAuth Provider (google, github, etc.)")


class OAuthAccountResponse(BaseModel):
    """OAuth 계정 정보 응답"""
    provider: str
    provider_account_email: Optional[str] = None
    linked_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OAuthAccountsListResponse(BaseModel):
    """연결된 OAuth 계정 목록 응답"""
    oauth_accounts: List[OAuthAccountResponse]
