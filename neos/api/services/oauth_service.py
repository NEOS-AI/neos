"""
OAuth 서비스 - Google OAuth 2.0 통합

Google ID Token 검증, 로그인/가입 처리, 계정 연결 기능 제공
"""
import logging
import uuid
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from neos.database.models import User, UserOAuthAccount, Organization
from neos.config.settings import Settings
from neos.api.services.auth_service import AuthService
from neos.utils.jwt import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)
settings = Settings()


class OAuthService:
    """OAuth 인증 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.google_client_id = settings.GOOGLE_OAUTH_CLIENT_ID
        self.auth_service = AuthService(db)

    async def verify_google_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Google ID Token 검증

        Args:
            token: Google ID Token (credential from Google Sign-In)

        Returns:
            검증된 사용자 정보 또는 None
            {
                'google_id': str,  # Google sub (subject)
                'email': str,
                'email_verified': bool,
                'name': str,
                'picture': str,
            }
        """
        try:
            # Google ID Token 검증
            idinfo = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                self.google_client_id
            )

            # issuer 검증 (보안)
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                logger.warning(f"Invalid issuer: {idinfo.get('iss')}")
                return None

            # 사용자 정보 추출
            user_info = {
                'google_id': idinfo['sub'],  # Google 고유 ID
                'email': idinfo.get('email'),
                'email_verified': idinfo.get('email_verified', False),
                'name': idinfo.get('name'),
                'picture': idinfo.get('picture'),
                'locale': idinfo.get('locale'),
            }

            logger.info(f"Google token verified successfully for email: {user_info['email']}")
            return user_info

        except ValueError as e:
            logger.error(f"Google token verification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Google token verification: {e}", exc_info=True)
            return None

    async def login_or_register_with_google(
        self,
        google_token: str,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Google 계정으로 로그인 또는 자동 가입

        Flow:
        1. Google Token 검증
        2. OAuth 계정 조회
        3. 있으면 로그인, 없으면:
           - 동일 이메일 기존 사용자 있으면 에러 (수동 연결 필요)
           - 없으면 신규 사용자 생성 + OAuth 연결

        Args:
            google_token: Google ID Token
            device_info: User-Agent 정보
            ip_address: 클라이언트 IP 주소

        Returns:
            (success, message, token_data)
            token_data = {
                'access_token': str,
                'refresh_token': str,
                'token_type': 'bearer',
                'expires_in': int,
                'user': User dict
            }
        """
        # 1. Google Token 검증
        user_info = await self.verify_google_token(google_token)
        if not user_info:
            return False, "유효하지 않은 Google 토큰입니다.", None

        google_id = user_info['google_id']
        email = user_info['email']

        if not email:
            return False, "Google 계정에서 이메일 정보를 가져올 수 없습니다.", None

        try:
            # 2. OAuth 계정 조회 (google_id로)
            result = await self.db.execute(
                select(UserOAuthAccount)
                .options(selectinload(UserOAuthAccount.user))
                .where(
                    and_(
                        UserOAuthAccount.provider == 'google',
                        UserOAuthAccount.provider_account_id == google_id
                    )
                )
            )
            oauth_account = result.scalar_one_or_none()

            # 3a. 이미 연결된 계정 - 로그인 처리
            if oauth_account:
                user = oauth_account.user

                # 비활성화된 계정 체크
                if not user.is_active:
                    return False, "비활성화된 계정입니다. 고객센터에 문의해주세요.", None

                # OAuth 계정 마지막 사용 시간 업데이트
                oauth_account.last_used_at = datetime.utcnow()

                # 사용자 마지막 로그인 시간 업데이트
                user.last_login = datetime.utcnow()

                # 프로필 사진 업데이트 (변경된 경우)
                if user_info.get('picture') and user.profile_picture_url != user_info['picture']:
                    user.profile_picture_url = user_info['picture']

                await self.db.commit()

                # JWT 토큰 생성
                token_data = await self._create_tokens(user, device_info, ip_address)
                logger.info(f"Google login successful for user: {user.email}")
                return True, "로그인 성공", token_data

            # 3b. 동일 이메일 기존 사용자 확인
            existing_user_result = await self.db.execute(
                select(User).where(User.email == email)
            )
            existing_user = existing_user_result.scalar_one_or_none()

            if existing_user:
                # 이메일/비밀번호로 가입한 기존 사용자가 있음
                # 보안상 수동 연결을 강제
                return False, "이 이메일로 가입된 계정이 있습니다. 계정 설정에서 Google 계정을 연결해주세요.", None

            # 3c. 신규 사용자 생성
            user_id = f"user_{uuid.uuid4().hex[:16]}"
            username = await self._generate_unique_username(user_info.get('name') or email.split('@')[0])

            new_user = User(
                user_id=user_id,
                email=email,
                username=username,
                google_id=google_id,
                profile_picture_url=user_info.get('picture'),
                is_active=True,
                is_verified=user_info.get('email_verified', False),
                email_verified_at=datetime.utcnow() if user_info.get('email_verified') else None,
                role="user",
                subscription_tier="free",
                subscription_status="active",
                password_hash=None,  # OAuth 사용자는 비밀번호 없음
            )

            self.db.add(new_user)
            await self.db.flush()  # ID 생성

            # 엔터프라이즈 도메인 체크
            organization = await self._check_enterprise_domain(email)
            if organization:
                if organization.auto_join_enabled and not organization.require_approval:
                    # 자동 가입 허용
                    new_user.organization_id = organization.id
                    logger.info(f"User {email} automatically joined organization: {organization.name}")
                else:
                    logger.info(f"User {email} from enterprise domain {organization.domain}, but requires approval")

            # OAuth 계정 연결
            oauth_account = UserOAuthAccount(
                user_id=new_user.user_id,
                provider='google',
                provider_account_id=google_id,
                provider_account_email=email,
                profile_data={
                    'name': user_info.get('name'),
                    'picture': user_info.get('picture'),
                    'email': email,
                    'locale': user_info.get('locale'),
                }
            )

            self.db.add(oauth_account)
            await self.db.commit()

            # JWT 토큰 생성
            token_data = await self._create_tokens(new_user, device_info, ip_address)
            logger.info(f"Google registration successful for user: {new_user.email}")
            return True, "Google 계정으로 가입되었습니다.", token_data

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error during Google login/registration: {e}", exc_info=True)
            return False, "로그인 처리 중 오류가 발생했습니다.", None

    async def link_google_account(
        self,
        user_id: str,
        google_token: str
    ) -> Tuple[bool, str]:
        """
        기존 사용자에게 Google 계정 연결

        Args:
            user_id: 현재 로그인한 사용자 ID
            google_token: Google ID Token

        Returns:
            (success, message)
        """
        # Google Token 검증
        user_info = await self.verify_google_token(google_token)
        if not user_info:
            return False, "유효하지 않은 Google 토큰입니다."

        google_id = user_info['google_id']
        email = user_info['email']

        try:
            # 사용자 조회
            user_result = await self.db.execute(
                select(User).where(User.user_id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                return False, "사용자를 찾을 수 없습니다."

            # 이미 다른 Google 계정이 연결되어 있는지 확인
            existing_google_result = await self.db.execute(
                select(UserOAuthAccount).where(
                    and_(
                        UserOAuthAccount.user_id == user_id,
                        UserOAuthAccount.provider == 'google'
                    )
                )
            )
            existing_google = existing_google_result.scalar_one_or_none()

            if existing_google:
                return False, "이미 Google 계정이 연결되어 있습니다. 연결을 해제한 후 다시 시도해주세요."

            # 해당 Google 계정이 다른 사용자에게 연결되어 있는지 확인
            other_user_result = await self.db.execute(
                select(UserOAuthAccount).where(
                    and_(
                        UserOAuthAccount.provider == 'google',
                        UserOAuthAccount.provider_account_id == google_id
                    )
                )
            )
            other_user_oauth = other_user_result.scalar_one_or_none()

            if other_user_oauth:
                return False, "이 Google 계정은 이미 다른 사용자에게 연결되어 있습니다."

            # 이메일 일치 확인 (선택적 경고)
            if user.email and user.email != email:
                logger.warning(f"User {user_id} linking Google account with different email: {user.email} vs {email}")

            # Google 계정 연결
            oauth_account = UserOAuthAccount(
                user_id=user_id,
                provider='google',
                provider_account_id=google_id,
                provider_account_email=email,
                profile_data={
                    'name': user_info.get('name'),
                    'picture': user_info.get('picture'),
                    'email': email,
                    'locale': user_info.get('locale'),
                }
            )

            # google_id 업데이트 및 프로필 사진 설정
            if not user.google_id:
                user.google_id = google_id

            if not user.profile_picture_url and user_info.get('picture'):
                user.profile_picture_url = user_info['picture']

            # 이메일 검증 상태 업데이트
            if user_info.get('email_verified') and not user.email_verified_at:
                user.email_verified_at = datetime.utcnow()
                user.is_verified = True

            self.db.add(oauth_account)
            await self.db.commit()

            logger.info(f"Google account linked successfully for user: {user_id}")
            return True, "Google 계정이 연결되었습니다."

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error during Google account linking: {e}", exc_info=True)
            return False, "계정 연결 중 오류가 발생했습니다."

    async def unlink_oauth_account(
        self,
        user_id: str,
        provider: str = 'google'
    ) -> Tuple[bool, str]:
        """
        OAuth 계정 연결 해제

        Args:
            user_id: 사용자 ID
            provider: OAuth Provider ('google', 'github', etc.)

        Returns:
            (success, message)
        """
        try:
            # 사용자 조회 (비밀번호 있는지 확인)
            user_result = await self.db.execute(
                select(User).where(User.user_id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                return False, "사용자를 찾을 수 없습니다."

            # OAuth 계정 조회
            oauth_result = await self.db.execute(
                select(UserOAuthAccount).where(
                    and_(
                        UserOAuthAccount.user_id == user_id,
                        UserOAuthAccount.provider == provider
                    )
                )
            )
            oauth_account = oauth_result.scalar_one_or_none()

            if not oauth_account:
                return False, f"{provider.title()} 계정이 연결되어 있지 않습니다."

            # 안전성 검사: 비밀번호가 없고 OAuth 계정만 있는 경우 연결 해제 금지
            if not user.password_hash:
                # 다른 OAuth 계정이 있는지 확인
                other_oauth_result = await self.db.execute(
                    select(UserOAuthAccount).where(
                        and_(
                            UserOAuthAccount.user_id == user_id,
                            UserOAuthAccount.provider != provider
                        )
                    )
                )
                other_oauth = other_oauth_result.scalar_one_or_none()

                if not other_oauth:
                    return False, "비밀번호가 설정되지 않은 경우 마지막 로그인 수단을 제거할 수 없습니다. 먼저 비밀번호를 설정해주세요."

            # OAuth 계정 삭제
            await self.db.delete(oauth_account)

            # google_id 제거 (Google인 경우)
            if provider == 'google':
                user.google_id = None

            await self.db.commit()

            logger.info(f"{provider.title()} account unlinked for user: {user_id}")
            return True, f"{provider.title()} 계정 연결이 해제되었습니다."

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error during OAuth account unlinking: {e}", exc_info=True)
            return False, "연결 해제 중 오류가 발생했습니다."

    async def _create_tokens(
        self,
        user: User,
        device_info: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """JWT 토큰 생성 (AuthService 위임)"""
        # Access Token 생성
        access_token = create_access_token(
            data={
                "user_id": user.user_id,
                "email": user.email,
                "role": user.role
            }
        )

        # Refresh Token 생성 및 저장
        refresh_token = await self.auth_service._create_and_store_refresh_token(
            user_id=user.user_id,
            device_info=device_info,
            ip_address=ip_address
        )

        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': 'bearer',
            'expires_in': settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # 초 단위
            'user': {
                'user_id': user.user_id,
                'email': user.email,
                'username': user.username,
                'role': user.role,
                'is_active': user.is_active,
                'is_verified': user.is_verified,
                'profile_picture_url': user.profile_picture_url,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None,
            }
        }

    async def _generate_unique_username(self, base_username: str) -> str:
        """중복되지 않는 username 생성"""
        # 특수문자 제거 및 공백을 언더스코어로 변경
        username = base_username.replace(' ', '_').lower()
        username = ''.join(c for c in username if c.isalnum() or c == '_')

        # 빈 문자열이면 기본값
        if not username:
            username = "user"

        # 중복 체크
        original_username = username
        counter = 1

        while True:
            result = await self.db.execute(
                select(User).where(User.username == username)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                return username

            # 중복이면 숫자 추가
            username = f"{original_username}_{counter}"
            counter += 1

            # 무한 루프 방지 (1000번 시도 후 랜덤 ID 사용)
            if counter > 1000:
                username = f"{original_username}_{uuid.uuid4().hex[:8]}"
                break

        return username

    async def _check_enterprise_domain(self, email: str) -> Optional[Organization]:
        """
        회사 이메일 도메인 확인 및 조직 매칭

        Args:
            email: 사용자 이메일

        Returns:
            Organization 또는 None
        """
        domain = email.split('@')[1]

        # 무료 이메일 도메인 제외
        free_domains = {
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
            'naver.com', 'daum.net', 'kakao.com', 'icloud.com',
            'protonmail.com', 'mail.com', 'aol.com', 'zoho.com'
        }

        if domain in free_domains:
            return None

        # 조직 조회
        result = await self.db.execute(
            select(Organization).where(Organization.domain == domain)
        )
        organization = result.scalar_one_or_none()

        return organization
