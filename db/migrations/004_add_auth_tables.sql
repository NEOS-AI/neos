-- Migration: Add Authentication Tables
-- Created: 2025-11-17
-- Description: User 테이블 확장 및 API 키, Refresh Token 테이블 추가

-- ============================================================================
-- 1. User 테이블 확장
-- ============================================================================

-- 기존 users 테이블에 인증 관련 컬럼 추가
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS username VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255),
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'user',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;

-- 인덱스 추가 (이미 존재할 수 있으므로 IF NOT EXISTS 사용)
CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- ============================================================================
-- 2. API Keys 테이블 생성
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- 키 정보
    name VARCHAR(255) NOT NULL,
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    key_prefix VARCHAR(20) NOT NULL,

    -- 권한 및 제한
    scopes TEXT[] DEFAULT '{}',
    rate_limit INTEGER DEFAULT 100,
    max_requests_per_day INTEGER,

    -- 사용 통계
    total_requests INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    last_used_ip VARCHAR(45),

    -- 상태 및 만료
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,

    -- 메타데이터
    description TEXT,
    metadata JSONB DEFAULT '{}',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API Keys 인덱스
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active);

-- ============================================================================
-- 3. Refresh Tokens 테이블 생성
-- ============================================================================

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- 토큰 정보
    token_hash VARCHAR(255) NOT NULL UNIQUE,

    -- 세션 정보
    session_id VARCHAR(255),
    device_info VARCHAR(500),
    ip_address VARCHAR(45),

    -- 상태
    is_revoked BOOLEAN DEFAULT FALSE,
    is_used BOOLEAN DEFAULT FALSE,

    -- 만료
    expires_at TIMESTAMP NOT NULL,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    used_at TIMESTAMP,
    revoked_at TIMESTAMP
);

-- Refresh Tokens 인덱스
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);

-- ============================================================================
-- 4. 트리거 생성 (updated_at 자동 업데이트)
-- ============================================================================

-- updated_at 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- users 테이블 트리거
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- api_keys 테이블 트리거
DROP TRIGGER IF EXISTS update_api_keys_updated_at ON api_keys;
CREATE TRIGGER update_api_keys_updated_at
    BEFORE UPDATE ON api_keys
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 5. 기본 데이터 (선택 사항)
-- ============================================================================

-- 기존 users에 기본값 설정 (email, username이 없는 경우)
-- UPDATE users
-- SET
--     email = user_id || '@neos.local',
--     username = user_id,
--     is_active = TRUE,
--     is_verified = FALSE,
--     role = 'user'
-- WHERE email IS NULL;

COMMENT ON TABLE api_keys IS 'API 키 관리 테이블';
COMMENT ON TABLE refresh_tokens IS 'JWT Refresh Token 관리 테이블';
COMMENT ON COLUMN users.password_hash IS 'bcrypt 해시된 비밀번호';
COMMENT ON COLUMN api_keys.key_hash IS 'SHA-256 해시된 API 키';
COMMENT ON COLUMN refresh_tokens.token_hash IS 'SHA-256 해시된 Refresh Token';
