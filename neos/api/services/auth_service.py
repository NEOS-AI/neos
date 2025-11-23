"""
인증 서비스
- 사용자 등록, 로그인, 로그아웃
- JWT 토큰 발급 및 갱신
- API 키 관리
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import uuid

from neos.database.models import User, APIKey, RefreshToken
from neos.utils.security import (
    hash_password,
    verify_password,
    validate_password_strength,
    generate_api_key,
    hash_api_key,
    hash_token
)
from neos.utils.jwt import (
    create_access_token,
    create_refresh_token,
    verify_token
)
from neos.config.settings import settings


class AuthService:
    """인증 관련 비즈니스 로직"""

    def __init__(self, db: AsyncSession):
        self.db = db


    async def register_user(
        self,
        email: str,
        password: str,
        username: Optional[str] = None
    ) -> Tuple[bool, str, Optional[User]]:
        """
        사용자 등록

        Args:
            email: 이메일
            password: 비밀번호
            username: 사용자명 (선택)

        Returns:
            (성공 여부, 메시지, User 객체)
        """
        # 이메일 중복 체크
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        if result.scalar_one_or_none():
            return False, "이미 등록된 이메일입니다.", None

        # 사용자명 중복 체크
        if username:
            result = await self.db.execute(
                select(User).where(User.username == username)
            )
            if result.scalar_one_or_none():
                return False, "이미 사용 중인 사용자명입니다.", None

        # 비밀번호 강도 검증
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            return False, error_message, None

        # 사용자 생성
        user_id = f"user_{uuid.uuid4().hex[:16]}"
        hashed_password = hash_password(password)

        new_user = User(
            user_id=user_id,
            email=email,
            username=username or email.split("@")[0],
            password_hash=hashed_password,
            is_active=True,
            is_verified=False,
            role="user"
        )

        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)

        return True, "회원가입이 완료되었습니다.", new_user


    async def login_user(
        self,
        email: str,
        password: str,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        사용자 로그인

        Args:
            email: 이메일
            password: 비밀번호
            device_info: 디바이스 정보 (User-Agent)
            ip_address: IP 주소

        Returns:
            (성공 여부, 메시지, 토큰 정보)
        """
        # 사용자 조회
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user or not user.password_hash:
            return False, "이메일 또는 비밀번호가 올바르지 않습니다.", None

        # 비밀번호 검증
        if not verify_password(password, user.password_hash):
            return False, "이메일 또는 비밀번호가 올바르지 않습니다.", None

        # 계정 활성화 체크
        if not user.is_active:
            return False, "비활성화된 계정입니다.", None

        # Access Token 생성
        access_token = create_access_token(
            data={
                "user_id": user.user_id,
                "email": user.email,
                "role": user.role
            }
        )

        # Refresh Token 생성
        refresh_token = create_refresh_token(
            data={"user_id": user.user_id}
        )

        # Refresh Token DB에 저장
        refresh_token_hash = hash_token(refresh_token)
        expires_at = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        new_refresh_token = RefreshToken(
            user_id=user.user_id,
            token_hash=refresh_token_hash,
            device_info=device_info,
            ip_address=ip_address,
            expires_at=expires_at
        )

        self.db.add(new_refresh_token)

        # 마지막 로그인 시간 업데이트
        user.last_login = datetime.utcnow()

        await self.db.commit()

        return True, "로그인 성공", {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "user_id": user.user_id,
                "email": user.email,
                "username": user.username,
                "role": user.role
            }
        }

    async def refresh_access_token(
        self,
        refresh_token: str
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Access Token 갱신

        Args:
            refresh_token: Refresh Token

        Returns:
            (성공 여부, 메시지, 새 토큰 정보)
        """
        # Refresh Token 검증
        payload = verify_token(refresh_token, token_type="refresh")
        if not payload:
            return False, "유효하지 않은 Refresh Token입니다.", None

        user_id = payload.get("user_id")
        if not user_id:
            return False, "유효하지 않은 Refresh Token입니다.", None

        # DB에서 Refresh Token 확인
        token_hash = hash_token(refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.user_id == user_id,
                    not RefreshToken.is_revoked,
                    not RefreshToken.is_used,
                    RefreshToken.expires_at > datetime.utcnow()
                )
            )
        )
        db_token = result.scalar_one_or_none()

        if not db_token:
            return False, "유효하지 않거나 만료된 Refresh Token입니다.", None

        # 사용자 조회
        result = await self.db.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            return False, "유효하지 않은 사용자입니다.", None

        # 기존 Refresh Token을 사용됨으로 표시 (토큰 rotation)
        db_token.is_used = True
        db_token.used_at = datetime.utcnow()

        # 새 Access Token 생성
        new_access_token = create_access_token(
            data={
                "user_id": user.user_id,
                "email": user.email,
                "role": user.role
            }
        )

        # 새 Refresh Token 생성
        new_refresh_token = create_refresh_token(
            data={"user_id": user.user_id}
        )

        # 새 Refresh Token DB에 저장
        new_token_hash = hash_token(new_refresh_token)
        expires_at = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        new_db_refresh_token = RefreshToken(
            user_id=user.user_id,
            token_hash=new_token_hash,
            device_info=db_token.device_info,
            ip_address=db_token.ip_address,
            expires_at=expires_at
        )

        self.db.add(new_db_refresh_token)
        await self.db.commit()

        return True, "토큰 갱신 성공", {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }

    async def logout_user(
        self,
        refresh_token: str
    ) -> Tuple[bool, str]:
        """
        사용자 로그아웃 (Refresh Token 무효화)

        Args:
            refresh_token: Refresh Token

        Returns:
            (성공 여부, 메시지)
        """
        token_hash = hash_token(refresh_token)

        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        db_token = result.scalar_one_or_none()

        if db_token:
            db_token.is_revoked = True
            db_token.revoked_at = datetime.utcnow()
            await self.db.commit()

        return True, "로그아웃 성공"

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        User ID로 사용자 조회

        Args:
            user_id: 사용자 ID

        Returns:
            User 객체 또는 None
        """
        result = await self.db.execute(
            select(User).where(User.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        이메일로 사용자 조회

        Args:
            email: 이메일

        Returns:
            User 객체 또는 None
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    # ========================================================================
    # API 키 관리
    # ========================================================================

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        scopes: Optional[List[str]] = None,
        rate_limit: int = 100,
        max_requests_per_day: Optional[int] = None,
        expires_at: Optional[datetime] = None,
        description: Optional[str] = None
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        API 키 생성

        Args:
            user_id: 사용자 ID
            name: API 키 이름
            scopes: 권한 범위
            rate_limit: 분당 요청 제한
            max_requests_per_day: 일일 최대 요청 수
            expires_at: 만료 시간
            description: 설명

        Returns:
            (성공 여부, 메시지, API 키 정보)
        """
        # 사용자 존재 확인
        user = await self.get_user_by_id(user_id)
        if not user:
            return False, "존재하지 않는 사용자입니다.", None

        # API 키 생성
        full_key, key_hash, key_prefix = generate_api_key()

        new_api_key = APIKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=scopes or [],
            rate_limit=rate_limit,
            max_requests_per_day=max_requests_per_day,
            expires_at=expires_at,
            description=description
        )

        self.db.add(new_api_key)
        await self.db.commit()
        await self.db.refresh(new_api_key)

        return True, "API 키가 생성되었습니다.", {
            "id": str(new_api_key.id),
            "key": full_key,  # 1회만 표시
            "prefix": key_prefix,
            "name": name,
            "scopes": scopes or [],
            "rate_limit": rate_limit,
            "created_at": new_api_key.created_at.isoformat()
        }

    async def verify_api_key(
        self,
        api_key: str
    ) -> Tuple[bool, Optional[APIKey], Optional[User]]:
        """
        API 키 검증

        Args:
            api_key: API 키

        Returns:
            (유효 여부, APIKey 객체, User 객체)
        """
        key_hash = hash_api_key(api_key)

        result = await self.db.execute(
            select(APIKey).where(
                and_(
                    APIKey.key_hash == key_hash,
                    APIKey.is_active
                )
            )
        )
        api_key_obj = result.scalar_one_or_none()

        if not api_key_obj:
            return False, None, None

        # 만료 확인
        if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
            return False, None, None

        # 사용자 조회
        user = await self.get_user_by_id(api_key_obj.user_id)
        if not user or not user.is_active:
            return False, None, None

        # 사용 통계 업데이트
        api_key_obj.total_requests += 1
        api_key_obj.last_used_at = datetime.utcnow()

        await self.db.commit()

        return True, api_key_obj, user

    async def list_api_keys(self, user_id: str) -> List[dict]:
        """
        사용자의 API 키 목록 조회

        Args:
            user_id: 사용자 ID

        Returns:
            API 키 목록
        """
        result = await self.db.execute(
            select(APIKey).where(APIKey.user_id == user_id)
        )
        api_keys = result.scalars().all()

        return [
            {
                "id": str(key.id),
                "name": key.name,
                "prefix": key.key_prefix,
                "scopes": key.scopes,
                "rate_limit": key.rate_limit,
                "is_active": key.is_active,
                "total_requests": key.total_requests,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "created_at": key.created_at.isoformat()
            }
            for key in api_keys
        ]

    async def revoke_api_key(self, api_key_id: str, user_id: str) -> Tuple[bool, str]:
        """
        API 키 무효화

        Args:
            api_key_id: API 키 ID
            user_id: 사용자 ID

        Returns:
            (성공 여부, 메시지)
        """
        result = await self.db.execute(
            select(APIKey).where(
                and_(
                    APIKey.id == uuid.UUID(api_key_id),
                    APIKey.user_id == user_id
                )
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            return False, "API 키를 찾을 수 없습니다."

        api_key.is_active = False
        await self.db.commit()

        return True, "API 키가 무효화되었습니다."
