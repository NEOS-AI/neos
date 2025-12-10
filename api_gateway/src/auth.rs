//! 인증 모듈
//!
//! JWT 토큰 및 API 키 검증 기능을 제공합니다.

use anyhow::{Context, Result};
use chrono::Utc;
use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::{debug, warn};

use crate::config::{ApiKeyConfig, AuthConfig, JwtConfig};
use crate::db::{ApiKeyInfo, Database, UserInfo};

/// 인증 에러
#[derive(Debug, Error)]
pub enum AuthError {
    #[error("Missing authorization header")]
    MissingAuthHeader,

    #[error("Invalid authorization header format")]
    InvalidAuthHeader,

    #[error("Invalid JWT token: {0}")]
    InvalidJwt(String),

    #[error("JWT token expired")]
    JwtExpired,

    #[error("Invalid API key")]
    InvalidApiKey,

    #[error("API key expired")]
    ApiKeyExpired,

    #[error("User not found: {0}")]
    UserNotFound(String),

    #[error("User is not active")]
    UserNotActive,

    #[error("Database error: {0}")]
    DatabaseError(String),
}

/// JWT 클레임 구조체
/// neos 백엔드의 JWT 토큰 구조와 일치해야 함
#[derive(Debug, Serialize, Deserialize)]
pub struct JwtClaims {
    /// 사용자 ID
    pub user_id: String,
    /// 이메일 (선택)
    pub email: Option<String>,
    /// 역할 (선택)
    pub role: Option<String>,
    /// 토큰 유형 (access/refresh)
    #[serde(rename = "type")]
    pub token_type: Option<String>,
    /// 발급 시간
    pub iat: Option<i64>,
    /// 만료 시간
    pub exp: Option<i64>,
}

/// 인증 결과
#[derive(Debug, Clone)]
pub struct AuthResult {
    /// 인증된 사용자 ID
    pub user_id: String,
    /// 인증 방식 (jwt, api_key)
    pub auth_method: AuthMethod,
    /// 사용자 정보 (DB에서 조회된 경우)
    pub user_info: Option<UserInfo>,
}

/// 인증 방식
#[derive(Debug, Clone, PartialEq)]
pub enum AuthMethod {
    Jwt,
    ApiKey,
}

/// 인증 서비스
pub struct AuthService {
    jwt_config: JwtConfig,
    auth_config: AuthConfig,
    api_key_config: ApiKeyConfig,
    db: Database,
    public_path_patterns: Vec<Regex>,
}

impl AuthService {
    /// 새 인증 서비스 생성
    pub fn new(
        jwt_config: JwtConfig,
        auth_config: AuthConfig,
        api_key_config: ApiKeyConfig,
        db: Database,
    ) -> Result<Self> {
        // public_paths를 정규식으로 컴파일
        let public_path_patterns: Vec<Regex> = auth_config
            .public_paths
            .iter()
            .filter_map(|pattern| match Regex::new(pattern) {
                Ok(re) => Some(re),
                Err(e) => {
                    warn!("Invalid public path pattern '{}': {}", pattern, e);
                    None
                }
            })
            .collect();

        debug!(
            "Compiled {} public path patterns",
            public_path_patterns.len()
        );

        Ok(Self {
            jwt_config,
            auth_config,
            api_key_config,
            db,
            public_path_patterns,
        })
    }

    /// 경로가 공개 경로(인증 불필요)인지 확인
    pub fn is_public_path(&self, path: &str) -> bool {
        for pattern in &self.public_path_patterns {
            if pattern.is_match(path) {
                debug!("Path '{}' matches public pattern", path);
                return true;
            }
        }
        false
    }

    /// 요청 인증
    ///
    /// Authorization 헤더 또는 X-API-Key 헤더를 확인하여 사용자를 인증합니다.
    pub async fn authenticate(
        &self,
        auth_header: Option<&str>,
        api_key_header: Option<&str>,
        client_ip: Option<&str>,
    ) -> Result<AuthResult, AuthError> {
        // 1. Bearer 토큰(JWT) 확인
        if let Some(auth) = auth_header {
            if let Some(token) = auth.strip_prefix("Bearer ") {
                return self.verify_jwt(token).await;
            }
        }

        // 2. API 키 확인
        if let Some(api_key) = api_key_header {
            return self.verify_api_key(api_key, client_ip).await;
        }

        Err(AuthError::MissingAuthHeader)
    }

    /// JWT 토큰 검증
    async fn verify_jwt(&self, token: &str) -> Result<AuthResult, AuthError> {
        let algorithm = match self.jwt_config.algorithm.as_str() {
            "HS256" => Algorithm::HS256,
            "HS384" => Algorithm::HS384,
            "HS512" => Algorithm::HS512,
            _ => Algorithm::HS256,
        };

        let mut validation = Validation::new(algorithm);
        validation.validate_exp = self.jwt_config.validate_exp;
        validation.leeway = self.jwt_config.leeway_secs;
        // 필수 클레임 설정하지 않음 (유연성)
        validation.required_spec_claims.clear();

        let decoding_key = DecodingKey::from_secret(self.jwt_config.secret_key.as_bytes());

        let token_data = decode::<JwtClaims>(token, &decoding_key, &validation).map_err(|e| {
            debug!("JWT decode error: {:?}", e);
            match e.kind() {
                jsonwebtoken::errors::ErrorKind::ExpiredSignature => AuthError::JwtExpired,
                _ => AuthError::InvalidJwt(e.to_string()),
            }
        })?;

        let claims = token_data.claims;
        let user_id = claims.user_id.clone();

        // 사용자 존재 및 활성화 확인 (선택적)
        let user_info = self
            .db
            .get_user_by_id(&user_id)
            .await
            .map_err(|e| AuthError::DatabaseError(e.to_string()))?;

        if let Some(ref user) = user_info {
            if !user.is_active {
                return Err(AuthError::UserNotActive);
            }
        }

        debug!("JWT authentication successful for user: {}", user_id);

        Ok(AuthResult {
            user_id,
            auth_method: AuthMethod::Jwt,
            user_info,
        })
    }

    /// API 키 검증
    async fn verify_api_key(
        &self,
        api_key: &str,
        client_ip: Option<&str>,
    ) -> Result<AuthResult, AuthError> {
        // API 키 prefix 추출 (예: neos_abc123...)
        let key_prefix = if api_key.len() >= 12 {
            format!("{}...", &api_key[..12])
        } else {
            api_key.to_string()
        };

        // prefix로 후보 조회
        let candidates = self
            .db
            .get_api_key_candidates(&key_prefix)
            .await
            .map_err(|e| AuthError::DatabaseError(e.to_string()))?;

        if candidates.is_empty() {
            debug!("No API key candidates found for prefix: {}", key_prefix);
            return Err(AuthError::InvalidApiKey);
        }

        // bcrypt로 검증
        let mut matched_key: Option<ApiKeyInfo> = None;

        for candidate in &candidates {
            if self.verify_api_key_hash(api_key, &candidate.key_hash) {
                matched_key = Some(candidate.clone());
                // 타이밍 공격 방어를 위해 모든 후보 검증 (하지만 첫 매치만 저장)
            }
        }

        let api_key_info = matched_key.ok_or(AuthError::InvalidApiKey)?;

        // 만료 확인
        if let Some(expires_at) = api_key_info.expires_at {
            if expires_at < Utc::now() {
                return Err(AuthError::ApiKeyExpired);
            }
        }

        // 사용자 조회
        let user_info = self
            .db
            .get_user_by_id(&api_key_info.user_id)
            .await
            .map_err(|e| AuthError::DatabaseError(e.to_string()))?;

        if let Some(ref user) = user_info {
            if !user.is_active {
                return Err(AuthError::UserNotActive);
            }
        } else {
            return Err(AuthError::UserNotFound(api_key_info.user_id.clone()));
        }

        // 사용 통계 업데이트 (비동기로 처리, 에러 무시)
        let db = self.db.clone();
        let api_key_id = api_key_info.id;
        let ip = client_ip.map(|s| s.to_string());
        tokio::spawn(async move {
            let _ = db.update_api_key_usage(api_key_id, ip.as_deref()).await;
        });

        debug!(
            "API key authentication successful for user: {}",
            api_key_info.user_id
        );

        Ok(AuthResult {
            user_id: api_key_info.user_id,
            auth_method: AuthMethod::ApiKey,
            user_info,
        })
    }

    /// API 키 bcrypt 해시 검증
    ///
    /// 타이밍 공격 방어를 위해 상수 시간에 검증 수행
    fn verify_api_key_hash(&self, api_key: &str, hash: &str) -> bool {
        // bcrypt::verify는 내부적으로 상수 시간 비교를 수행
        bcrypt::verify(api_key, hash).unwrap_or(false)
    }
    /// 헤더 이름 getter
    pub fn user_id_header(&self) -> &str {
        &self.auth_config.user_id_header
    }

    pub fn authorization_header(&self) -> &str {
        &self.auth_config.authorization_header
    }

    pub fn api_key_header(&self) -> &str {
        &self.auth_config.api_key_header
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_jwt_claims_deserialize() {
        let json = r#"{
            "user_id": "user_abc123",
            "email": "test@example.com",
            "role": "user",
            "type": "access",
            "iat": 1700000000,
            "exp": 1700001000
        }"#;

        let claims: JwtClaims = serde_json::from_str(json).unwrap();
        assert_eq!(claims.user_id, "user_abc123");
        assert_eq!(claims.email, Some("test@example.com".to_string()));
        assert_eq!(claims.role, Some("user".to_string()));
    }
}
