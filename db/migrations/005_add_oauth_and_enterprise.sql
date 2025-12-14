-- Migration 002: Add OAuth and Enterprise Support
-- Description: Add OAuth account linking, organization management, and subscription features
-- Date: 2025-01-14

-- ============================================================================
-- User 테이블 확장
-- ============================================================================

-- OAuth 지원 필드 추가
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS profile_picture_url VARCHAR(1000),
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP;

-- 조직 관계 필드 (FK는 Organization 테이블 생성 후 추가)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS organization_id UUID;

-- 구독 관련 필드
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(50) DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS subscription_start_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS subscription_end_date TIMESTAMP;

-- 사용량 관련 필드
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS usage_quota JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS usage_current JSONB DEFAULT '{}';

-- 결제 정보
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS billing_customer_id VARCHAR(255);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
CREATE INDEX IF NOT EXISTS idx_users_organization_id ON users(organization_id);
CREATE INDEX IF NOT EXISTS idx_users_subscription_tier ON users(subscription_tier);

-- ============================================================================
-- OAuth 계정 연결 테이블
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- OAuth Provider 정보
    provider VARCHAR(50) NOT NULL,
    provider_account_id VARCHAR(255) NOT NULL,
    provider_account_email VARCHAR(255),

    -- 프로필 정보 스냅샷
    profile_data JSONB DEFAULT '{}',

    -- 연결 정보
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,

    -- 제약조건: 한 Provider 계정은 하나의 NEOS 계정에만 연결 가능
    CONSTRAINT uq_provider_account UNIQUE(provider, provider_account_id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_oauth_user_id ON user_oauth_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_provider ON user_oauth_accounts(provider, provider_account_id);

-- 코멘트
COMMENT ON TABLE user_oauth_accounts IS 'OAuth Provider와 사용자 계정 연결 정보';
COMMENT ON COLUMN user_oauth_accounts.provider IS 'OAuth Provider: google, github, microsoft 등';
COMMENT ON COLUMN user_oauth_accounts.provider_account_id IS 'Provider에서 제공하는 고유 ID (Google sub, GitHub id 등)';
COMMENT ON COLUMN user_oauth_accounts.profile_data IS 'Provider에서 받은 프로필 정보 (name, picture, email 등)';

-- ============================================================================
-- Organizations 테이블 (엔터프라이즈 기능)
-- ============================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 조직 정보
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    logo_url VARCHAR(1000),

    -- 구독 정보 (조직 레벨)
    subscription_tier VARCHAR(50) DEFAULT 'enterprise',
    subscription_status VARCHAR(50) DEFAULT 'active',
    subscription_start_date TIMESTAMP,
    subscription_end_date TIMESTAMP,

    -- 사용량 풀링 (조직 전체)
    usage_quota JSONB DEFAULT '{}',
    usage_current JSONB DEFAULT '{}',

    -- 결제 정보
    billing_customer_id VARCHAR(255),
    billing_email VARCHAR(255),

    -- 설정
    auto_join_enabled BOOLEAN DEFAULT FALSE,
    require_approval BOOLEAN DEFAULT TRUE,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_organizations_domain ON organizations(domain);
CREATE INDEX IF NOT EXISTS idx_organizations_subscription_tier ON organizations(subscription_tier);

-- 코멘트
COMMENT ON TABLE organizations IS '회사/조직 정보 (엔터프라이즈 기능)';
COMMENT ON COLUMN organizations.domain IS '조직 이메일 도메인 (예: company.com)';
COMMENT ON COLUMN organizations.usage_quota IS '조직 전체 사용 가능 쿼터 (예: {"queries_per_month": 10000})';
COMMENT ON COLUMN organizations.usage_current IS '조직 현재 사용량 (예: {"queries_this_month": 523})';
COMMENT ON COLUMN organizations.auto_join_enabled IS '도메인 이메일로 자동 가입 허용 여부';
COMMENT ON COLUMN organizations.require_approval IS '신규 멤버 가입 시 관리자 승인 필요 여부';

-- ============================================================================
-- Organization Admins 테이블
-- ============================================================================

CREATE TABLE IF NOT EXISTS organization_admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    role VARCHAR(50) DEFAULT 'admin',
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 제약조건: 한 조직에 한 사용자는 한 번만 관리자로 등록 가능
    CONSTRAINT uq_org_admin UNIQUE(organization_id, user_id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_org_admins_organization_id ON organization_admins(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_admins_user_id ON organization_admins(user_id);

-- 코멘트
COMMENT ON TABLE organization_admins IS '조직 관리자 정보';
COMMENT ON COLUMN organization_admins.role IS '관리자 역할: admin (일반 관리자), owner (소유자)';

-- ============================================================================
-- User 테이블에 FK 추가 (Organization 테이블 생성 후)
-- ============================================================================

-- organization_id에 외래 키 제약조건 추가
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_users_organization'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT fk_users_organization
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ============================================================================
-- 기존 데이터 마이그레이션 (선택적)
-- ============================================================================

-- 기존 사용자의 구독 티어를 'free'로 설정 (이미 기본값이지만 명시적으로 업데이트)
UPDATE users
SET subscription_tier = 'free',
    subscription_status = 'active'
WHERE subscription_tier IS NULL;

-- ============================================================================
-- 함수: 자동 updated_at 업데이트
-- ============================================================================

-- organizations 테이블의 updated_at 자동 업데이트 트리거
CREATE OR REPLACE FUNCTION update_organization_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trigger_organizations_updated_at'
    ) THEN
        CREATE TRIGGER trigger_organizations_updated_at
        BEFORE UPDATE ON organizations
        FOR EACH ROW
        EXECUTE FUNCTION update_organization_updated_at();
    END IF;
END $$;

-- ============================================================================
-- 권한 설정 (선택적)
-- ============================================================================

-- 필요한 경우 특정 사용자에게 테이블 권한 부여
-- GRANT SELECT, INSERT, UPDATE, DELETE ON user_oauth_accounts TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON organizations TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON organization_admins TO your_app_user;

-- ============================================================================
-- 검증 쿼리
-- ============================================================================

-- 마이그레이션 완료 후 실행하여 확인
-- SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'users' AND column_name IN ('google_id', 'organization_id', 'subscription_tier');
-- SELECT table_name FROM information_schema.tables WHERE table_name IN ('user_oauth_accounts', 'organizations', 'organization_admins');
