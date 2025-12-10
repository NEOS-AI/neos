//! 데이터베이스 모듈
//!
//! PostgreSQL 연결 풀 및 사용자/API 키 조회 기능을 제공합니다.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use deadpool_postgres::{Config as PoolConfig, ManagerConfig, Pool, RecyclingMethod, Runtime};
use tokio_postgres::NoTls;
use tracing::{debug, error, info};
use uuid::Uuid;

use crate::config::DatabaseConfig;

/// 데이터베이스 연결 풀
#[derive(Clone)]
pub struct Database {
    pool: Pool,
}

/// 사용자 정보
#[derive(Debug, Clone)]
pub struct UserInfo {
    pub id: i32,
    pub user_id: String,
    pub email: Option<String>,
    pub username: Option<String>,
    pub is_active: bool,
    pub role: String,
}

/// API 키 정보
#[derive(Debug, Clone)]
pub struct ApiKeyInfo {
    pub id: Uuid,
    pub user_id: String,
    pub key_hash: String,
    pub key_prefix: String,
    pub scopes: Vec<String>,
    pub rate_limit: i32,
    pub max_requests_per_day: Option<i32>,
    pub is_active: bool,
    pub expires_at: Option<DateTime<Utc>>,
}

impl Database {
    /// 데이터베이스 연결 풀 생성
    pub async fn new(config: &DatabaseConfig) -> Result<Self> {
        let mut pool_config = PoolConfig::new();
        pool_config.host = Some(config.host.clone());
        pool_config.port = Some(config.port);
        pool_config.dbname = Some(config.database.clone());
        pool_config.user = Some(config.username.clone());
        pool_config.password = Some(config.password.clone());

        pool_config.manager = Some(ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        });

        let pool = pool_config
            .create_pool(Some(Runtime::Tokio1), NoTls)
            .with_context(|| "Failed to create database pool")?;

        // 연결 테스트
        let client = pool
            .get()
            .await
            .with_context(|| "Failed to connect to database")?;

        // 간단한 쿼리로 연결 확인
        client
            .query_one("SELECT 1", &[])
            .await
            .with_context(|| "Database connection test failed")?;

        info!("Database connection pool initialized successfully");

        Ok(Self { pool })
    }

    /// User ID로 사용자 조회
    pub async fn get_user_by_id(&self, user_id: &str) -> Result<Option<UserInfo>> {
        let client = self
            .pool
            .get()
            .await
            .with_context(|| "Failed to get database connection")?;

        let row = client
            .query_opt(
                r#"
                SELECT id, user_id, email, username, is_active, role
                FROM users
                WHERE user_id = $1
                "#,
                &[&user_id],
            )
            .await
            .with_context(|| "Failed to query user")?;

        match row {
            Some(row) => {
                debug!("Found user: {}", user_id);
                Ok(Some(UserInfo {
                    id: row.get("id"),
                    user_id: row.get("user_id"),
                    email: row.get("email"),
                    username: row.get("username"),
                    is_active: row.get("is_active"),
                    role: row.get("role"),
                }))
            }
            None => {
                debug!("User not found: {}", user_id);
                Ok(None)
            }
        }
    }

    /// API 키 prefix로 API 키 후보 조회
    ///
    /// bcrypt 해시 검증은 auth 모듈에서 수행합니다.
    pub async fn get_api_key_candidates(&self, key_prefix: &str) -> Result<Vec<ApiKeyInfo>> {
        let client = self
            .pool
            .get()
            .await
            .with_context(|| "Failed to get database connection")?;

        let rows = client
            .query(
                r#"
                SELECT 
                    id, user_id, key_hash, key_prefix, 
                    scopes, rate_limit, max_requests_per_day,
                    is_active, expires_at
                FROM api_keys
                WHERE key_prefix = $1 AND is_active = true
                "#,
                &[&key_prefix],
            )
            .await
            .with_context(|| "Failed to query API keys")?;

        let api_keys: Vec<ApiKeyInfo> = rows
            .iter()
            .map(|row| {
                let scopes: Vec<String> = row
                    .get::<_, Option<Vec<String>>>("scopes")
                    .unwrap_or_default();

                ApiKeyInfo {
                    id: row.get("id"),
                    user_id: row.get("user_id"),
                    key_hash: row.get("key_hash"),
                    key_prefix: row.get("key_prefix"),
                    scopes,
                    rate_limit: row.get("rate_limit"),
                    max_requests_per_day: row.get("max_requests_per_day"),
                    is_active: row.get("is_active"),
                    expires_at: row.get("expires_at"),
                }
            })
            .collect();

        debug!(
            "Found {} API key candidates for prefix: {}",
            api_keys.len(),
            key_prefix
        );
        Ok(api_keys)
    }

    /// API 키 사용 통계 업데이트
    pub async fn update_api_key_usage(
        &self,
        api_key_id: Uuid,
        client_ip: Option<&str>,
    ) -> Result<()> {
        let client = self
            .pool
            .get()
            .await
            .with_context(|| "Failed to get database connection")?;

        client
            .execute(
                r#"
                UPDATE api_keys 
                SET 
                    total_requests = total_requests + 1,
                    last_used_at = NOW(),
                    last_used_ip = $2
                WHERE id = $1
                "#,
                &[&api_key_id, &client_ip],
            )
            .await
            .with_context(|| "Failed to update API key usage")?;

        debug!("Updated API key usage for: {}", api_key_id);
        Ok(())
    }

    /// 헬스 체크
    pub async fn health_check(&self) -> Result<bool> {
        match self.pool.get().await {
            Ok(client) => match client.query_one("SELECT 1", &[]).await {
                Ok(_) => Ok(true),
                Err(e) => {
                    error!("Database health check failed: {}", e);
                    Ok(false)
                }
            },
            Err(e) => {
                error!("Failed to get database connection: {}", e);
                Ok(false)
            }
        }
    }
}
