//! 설정 모듈
//!
//! config.toml 파일을 로드하고 파싱하는 기능을 제공합니다.
//! 환경변수를 통한 설정 오버라이드를 지원합니다.

use anyhow::{Context, Result};
use serde::Deserialize;
use std::fs;
use std::path::Path;

/// 전체 설정 구조체
#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub server: ServerConfig,
    pub upstream: UpstreamConfig,
    pub jwt: JwtConfig,
    pub api_key: ApiKeyConfig,
    pub database: DatabaseConfig,
    pub auth: AuthConfig,
    pub rate_limit: RateLimitConfig,
    pub logging: LoggingConfig,
    pub cors: CorsConfig,
}

/// 서버 설정
#[derive(Debug, Clone, Deserialize)]
pub struct ServerConfig {
    pub listen_addr: String,
    pub listen_port: u16,
    pub threads: usize,
    pub work_stealing: bool,
}

/// 업스트림 (백엔드 API 서버) 설정
#[derive(Debug, Clone, Deserialize)]
pub struct UpstreamConfig {
    pub host: String,
    pub port: u16,
    pub health_check_interval_secs: u64,
    pub connect_timeout_secs: u64,
    pub read_timeout_secs: u64,
    pub write_timeout_secs: u64,
    pub pool_size: usize,
}

impl UpstreamConfig {
    /// 업스트림 주소 반환 (host:port 형식)
    pub fn addr(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

/// JWT 설정
#[derive(Debug, Clone, Deserialize)]
pub struct JwtConfig {
    pub secret_key: String,
    pub algorithm: String,
    pub validate_exp: bool,
    pub leeway_secs: u64,
}

/// API 키 설정
#[derive(Debug, Clone, Deserialize)]
pub struct ApiKeyConfig {
    pub prefix: String,
    pub bcrypt_cost: u32,
}

/// 데이터베이스 설정
#[derive(Debug, Clone, Deserialize)]
pub struct DatabaseConfig {
    pub host: String,
    pub port: u16,
    pub database: String,
    pub username: String,
    pub password: String,
    pub pool_size: usize,
    pub ssl_mode: String,
}

impl DatabaseConfig {
    /// PostgreSQL 연결 문자열 생성
    pub fn connection_string(&self) -> String {
        format!(
            "host={} port={} dbname={} user={} password={} sslmode={}",
            self.host, self.port, self.database, self.username, self.password, self.ssl_mode
        )
    }
}

/// 인증 설정
#[derive(Debug, Clone, Deserialize)]
pub struct AuthConfig {
    pub public_paths: Vec<String>,
    pub user_id_header: String,
    pub authorization_header: String,
    pub api_key_header: String,
}

/// 레이트 리미팅 설정
#[derive(Debug, Clone, Deserialize)]
pub struct RateLimitConfig {
    pub enabled: bool,
    pub default_rpm: u32,
    pub burst_size: u32,
}

/// 로깅 설정
#[derive(Debug, Clone, Deserialize)]
pub struct LoggingConfig {
    pub level: String,
    pub format: String,
    pub log_requests: bool,
    pub log_responses: bool,
}

/// CORS 설정
#[derive(Debug, Clone, Deserialize)]
pub struct CorsConfig {
    pub enabled: bool,
    pub allowed_origins: Vec<String>,
    pub allowed_methods: Vec<String>,
    pub allowed_headers: Vec<String>,
    pub max_age_secs: u64,
}

impl Config {
    /// 설정 파일 로드
    ///
    /// 기본 경로: config.toml
    /// 환경변수 CONFIG_PATH로 경로 오버라이드 가능
    pub fn load() -> Result<Self> {
        let config_path =
            std::env::var("CONFIG_PATH").unwrap_or_else(|_| "config.toml".to_string());

        Self::load_from_path(&config_path)
    }

    /// 특정 경로에서 설정 파일 로드
    pub fn load_from_path<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = fs::read_to_string(path.as_ref())
            .with_context(|| format!("Failed to read config file: {:?}", path.as_ref()))?;

        let mut config: Config =
            toml::from_str(&content).with_context(|| "Failed to parse config file")?;

        // 환경변수로 설정 오버라이드
        config.apply_env_overrides();
        config.validate()?;

        Ok(config)
    }

    /// 기동 전 필수 시크릿 검증
    ///
    /// config.toml은 시크릿 기본값을 담지 않으므로, 값이 비어 있으면
    /// 환경변수가 주입되지 않은 것이다. 빈 JWT 키로 기동하면 빈 키로 서명된
    /// 토큰이 통과하므로 조용히 넘어가지 않고 즉시 실패한다.
    pub fn validate(&self) -> Result<()> {
        if self.jwt.secret_key.trim().is_empty() {
            anyhow::bail!(
                "jwt.secret_key is empty: set the JWT_SECRET_KEY environment variable"
            );
        }

        Ok(())
    }

    /// 환경변수로 설정 오버라이드
    fn apply_env_overrides(&mut self) {
        // JWT Secret Key (필수)
        if let Ok(secret) = std::env::var("JWT_SECRET_KEY") {
            self.jwt.secret_key = secret;
        }

        // 데이터베이스 설정
        if let Ok(url) = std::env::var("DATABASE_URL") {
            // DATABASE_URL 형식: postgres://user:password@host:port/database
            if let Some(parsed) = Self::parse_database_url(&url) {
                self.database = parsed;
            }
        } else {
            // 개별 환경변수 오버라이드
            if let Ok(host) = std::env::var("DB_HOST") {
                self.database.host = host;
            }
            if let Ok(port) = std::env::var("DB_PORT") {
                if let Ok(port) = port.parse() {
                    self.database.port = port;
                }
            }
            if let Ok(db) = std::env::var("DB_NAME") {
                self.database.database = db;
            }
            if let Ok(user) = std::env::var("DB_USER") {
                self.database.username = user;
            }
            if let Ok(pass) = std::env::var("DB_PASSWORD") {
                self.database.password = pass;
            }
        }

        // 서버 설정
        if let Ok(port) = std::env::var("GATEWAY_PORT") {
            if let Ok(port) = port.parse() {
                self.server.listen_port = port;
            }
        }

        // 업스트림 설정
        if let Ok(host) = std::env::var("UPSTREAM_HOST") {
            self.upstream.host = host;
        }
        if let Ok(port) = std::env::var("UPSTREAM_PORT") {
            if let Ok(port) = port.parse() {
                self.upstream.port = port;
            }
        }

        // 로깅 레벨
        if let Ok(level) = std::env::var("LOG_LEVEL") {
            self.logging.level = level;
        }
    }

    /// DATABASE_URL 파싱
    fn parse_database_url(url: &str) -> Option<DatabaseConfig> {
        // postgres://user:password@host:port/database?sslmode=prefer
        let url = url
            .strip_prefix("postgres://")
            .or_else(|| url.strip_prefix("postgresql://"))?;

        let (auth_host, db_params) = url.split_once('/')?;
        let (auth, host_port) = auth_host.split_once('@')?;
        let (username, password) = auth.split_once(':')?;
        let (host, port_str) = host_port.split_once(':')?;
        let port: u16 = port_str.parse().ok()?;

        let (database, ssl_mode) = if let Some((db, params)) = db_params.split_once('?') {
            let ssl = params
                .split('&')
                .find(|p| p.starts_with("sslmode="))
                .map(|p| p.strip_prefix("sslmode=").unwrap_or("prefer"))
                .unwrap_or("prefer");
            (db.to_string(), ssl.to_string())
        } else {
            (db_params.to_string(), "prefer".to_string())
        };

        Some(DatabaseConfig {
            host: host.to_string(),
            port,
            database,
            username: username.to_string(),
            password: password.to_string(),
            pool_size: 10,
            ssl_mode,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 검증 테스트용 최소 설정. secret_key만 바꿔가며 쓴다.
    fn config_toml(secret_key: &str) -> String {
        format!(
            r#"
[server]
listen_addr = "0.0.0.0"
listen_port = 8080
threads = 0
work_stealing = true

[upstream]
host = "127.0.0.1"
port = 8518
health_check_interval_secs = 10
connect_timeout_secs = 5
read_timeout_secs = 60
write_timeout_secs = 60
pool_size = 100

[jwt]
secret_key = "{secret_key}"
algorithm = "HS256"
validate_exp = true
leeway_secs = 60

[api_key]
prefix = "neos_"
bcrypt_cost = 12

[database]
host = "localhost"
port = 5432
database = "neos"
username = "postgres"
password = ""
pool_size = 10
ssl_mode = "prefer"

[auth]
public_paths = []
user_id_header = "X-User-ID"
authorization_header = "Authorization"
api_key_header = "X-API-Key"

[rate_limit]
enabled = false
default_rpm = 100
burst_size = 20

[logging]
level = "info"
format = "pretty"
log_requests = true
log_responses = false

[cors]
enabled = true
allowed_origins = []
allowed_methods = []
allowed_headers = []
max_age_secs = 86400
"#
        )
    }

    #[test]
    fn validate_rejects_an_empty_jwt_secret() {
        let config: Config = toml::from_str(&config_toml("")).unwrap();

        let err = config
            .validate()
            .expect_err("empty JWT secret must not be accepted");

        assert!(
            err.to_string().contains("JWT_SECRET_KEY"),
            "error should name the env var to set, got: {err}"
        );
    }

    #[test]
    fn validate_accepts_a_configured_jwt_secret() {
        let config: Config = toml::from_str(&config_toml("set-from-environment")).unwrap();

        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_parse_database_url() {
        let url = "postgres://user:pass@localhost:5432/testdb?sslmode=require";
        let config = Config::parse_database_url(url).unwrap();

        assert_eq!(config.host, "localhost");
        assert_eq!(config.port, 5432);
        assert_eq!(config.username, "user");
        assert_eq!(config.password, "pass");
        assert_eq!(config.database, "testdb");
        assert_eq!(config.ssl_mode, "require");
    }

    #[test]
    fn test_upstream_addr() {
        let upstream = UpstreamConfig {
            host: "127.0.0.1".to_string(),
            port: 8000,
            health_check_interval_secs: 10,
            connect_timeout_secs: 5,
            read_timeout_secs: 60,
            write_timeout_secs: 60,
            pool_size: 100,
        };

        assert_eq!(upstream.addr(), "127.0.0.1:8000");
    }
}
