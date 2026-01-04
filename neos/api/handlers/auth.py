"""
인증 API 핸들러
- 회원가입, 로그인, 로그아웃
- 토큰 갱신
- API 키 관리
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from neos.database.connection import get_db
from neos.api.services.auth_service import AuthService
from neos.api.services.oauth_service import OAuthService
from neos.api.models.auth_models import (
    RegisterRequest,
    LoginRequest,
    RefreshTokenRequest,
    LogoutRequest,
    UserResponse,
    TokenResponse,
    MessageResponse,
    CreateAPIKeyRequest,
    APIKeyResponse,
    APIKeyListResponse,
    GoogleLoginRequest,
    GoogleLinkRequest,
    OAuthUnlinkRequest,
    OAuthAccountResponse,
    OAuthAccountsListResponse
)
from neos.api.dependencies.auth import (
    get_current_user,
    get_current_active_user
)
from neos.database.models import User


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    회원가입

    - **email**: 이메일 주소 (유니크)
    - **password**: 비밀번호 (최소 8자, 대소문자/숫자/특수문자 포함)
    - **username**: 사용자명 (선택, 기본값은 이메일 앞부분)
    """
    auth_service = AuthService(db)

    success, message, user = await auth_service.register_user(
        email=request.email,
        password=request.password,
        username=request.username
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(
        success=True,
        message=message,
        data={
            "user_id": user.user_id,
            "email": user.email,
            "username": user.username
        }
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    로그인

    - **email**: 이메일 주소
    - **password**: 비밀번호

    Returns:
    - **access_token**: JWT Access Token (15분 유효)
    - **refresh_token**: JWT Refresh Token (7일 유효)
    - **user**: 사용자 정보
    """
    auth_service = AuthService(db)

    # 디바이스 정보 및 IP 주소 수집
    device_info = http_request.headers.get("user-agent", "")
    ip_address = http_request.client.host if http_request.client else None

    success, message, tokens = await auth_service.login_user(
        email=request.email,
        password=request.password,
        device_info=device_info,
        ip_address=ip_address
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(**tokens)


@router.post("/guest", response_model=TokenResponse)
async def guest_login(
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Guest 사용자 생성 및 로그인

    임시 guest 사용자를 생성하고 토큰을 발급합니다.
    Guest 사용자는 제한된 기능 및 사용량 제한이 적용됩니다.

    Returns:
    - **access_token**: JWT Access Token
    - **refresh_token**: JWT Refresh Token
    - **user**: Guest 사용자 정보 (role: "guest")
    """
    auth_service = AuthService(db)

    # 디바이스 정보 및 IP 주소 수집
    device_info = http_request.headers.get("user-agent", "")
    ip_address = http_request.client.host if http_request.client else None

    success, message, tokens = await auth_service.create_guest_user(
        device_info=device_info,
        ip_address=ip_address
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message,
        )

    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Access Token 갱신

    - **refresh_token**: Refresh Token

    Returns:
    - **access_token**: 새 Access Token
    - **refresh_token**: 새 Refresh Token (토큰 rotation)
    """
    auth_service = AuthService(db)

    success, message, tokens = await auth_service.refresh_access_token(
        refresh_token=request.refresh_token
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(**tokens)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: LogoutRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    로그아웃 (Refresh Token 무효화)

    - **refresh_token**: Refresh Token
    """
    auth_service = AuthService(db)

    success, message = await auth_service.logout_user(
        refresh_token=request.refresh_token
    )

    return MessageResponse(success=success, message=message)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    현재 로그인한 사용자 정보 조회

    Requires: JWT Access Token 또는 API Key
    """
    return UserResponse.model_validate(current_user)


# ============================================================================
# API 키 관리
# ============================================================================

@router.post("/api-keys", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 생성

    - **name**: API 키 이름
    - **description**: 설명 (선택)
    - **scopes**: 권한 범위 (선택)
    - **rate_limit**: 분당 요청 제한 (기본값: 100)
    - **max_requests_per_day**: 일일 최대 요청 수 (선택)
    - **expires_days**: 만료 기간 (일 단위, 선택)

    **중요**: API 키는 생성 시 1회만 표시됩니다. 안전한 곳에 보관하세요.
    """
    auth_service = AuthService(db)

    expires_at = None
    if request.expires_days:
        expires_at = datetime.now() + timedelta(days=request.expires_days)

    success, message, api_key_data = await auth_service.create_api_key(
        user_id=current_user.user_id,
        name=request.name,
        scopes=request.scopes,
        rate_limit=request.rate_limit,
        max_requests_per_day=request.max_requests_per_day,
        expires_at=expires_at,
        description=request.description
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(
        success=True,
        message=message,
        data=api_key_data
    )


@router.get("/api-keys", response_model=APIKeyListResponse)
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    사용자의 API 키 목록 조회

    Requires: JWT Access Token
    """
    auth_service = AuthService(db)
    api_keys = await auth_service.list_api_keys(current_user.user_id)

    return APIKeyListResponse(
        api_keys=[APIKeyResponse(**key) for key in api_keys]
    )


@router.delete("/api-keys/{api_key_id}", response_model=MessageResponse)
async def revoke_api_key(
    api_key_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 무효화

    - **api_key_id**: API 키 ID

    Requires: JWT Access Token
    """
    auth_service = AuthService(db)

    success, message = await auth_service.revoke_api_key(
        api_key_id=api_key_id,
        user_id=current_user.user_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message
        )

    return MessageResponse(success=success, message=message)


# ============================================================================
# OAuth 로그인
# ============================================================================

@router.post("/oauth/google", response_model=TokenResponse)
async def google_oauth_login(
    request: GoogleLoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Google OAuth 로그인

    - **google_token**: Google ID Token (from Google Sign-In)

    Flow:
    1. Google Token 검증
    2. 연결된 계정이 있으면 로그인
    3. 없으면 신규 사용자 생성 (자동 가입)

    Returns:
    - **access_token**: JWT Access Token
    - **refresh_token**: JWT Refresh Token
    - **user**: 사용자 정보
    """
    oauth_service = OAuthService(db)

    # 디바이스 정보 및 IP 주소 수집
    device_info = http_request.headers.get("user-agent", "")
    ip_address = http_request.client.host if http_request.client else None

    success, message, tokens = await oauth_service.login_or_register_with_google(
        google_token=request.google_token,
        device_info=device_info,
        ip_address=ip_address
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(**tokens)


@router.post("/oauth/google/link", response_model=MessageResponse)
async def link_google_account(
    request: GoogleLinkRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Google 계정 연결

    현재 로그인한 사용자에게 Google 계정을 연결합니다.

    - **google_token**: Google ID Token

    Requires: JWT Access Token
    """
    oauth_service = OAuthService(db)

    success, message = await oauth_service.link_google_account(
        user_id=current_user.user_id,
        google_token=request.google_token
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(success=success, message=message)


@router.delete("/oauth/{provider}/unlink", response_model=MessageResponse)
async def unlink_oauth_account(
    provider: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    OAuth 계정 연결 해제

    - **provider**: OAuth Provider (google, github, etc.)

    Requires: JWT Access Token
    """
    oauth_service = OAuthService(db)

    success, message = await oauth_service.unlink_oauth_account(
        user_id=current_user.user_id,
        provider=provider
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return MessageResponse(success=success, message=message)


@router.get("/oauth/accounts", response_model=OAuthAccountsListResponse)
async def list_oauth_accounts(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    연결된 OAuth 계정 목록 조회

    Requires: JWT Access Token
    """
    from sqlalchemy import select
    from neos.database.models import UserOAuthAccount

    result = await db.execute(
        select(UserOAuthAccount).where(
            UserOAuthAccount.user_id == current_user.user_id
        )
    )
    oauth_accounts = result.scalars().all()

    return OAuthAccountsListResponse(
        oauth_accounts=[OAuthAccountResponse.model_validate(account) for account in oauth_accounts]
    )
