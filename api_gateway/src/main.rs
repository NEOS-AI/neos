//! NEOS API Gateway
//!
//! Pingora 기반의 고성능 API 게이트웨이
//! JWT 토큰 및 API 키 인증을 처리하고 X-User-ID 헤더를 추가하여
//! 백엔드 API 서버로 요청을 전달합니다.

mod auth;
mod config;
mod db;
mod proxy;

use pingora_core::prelude::*;
use pingora_proxy::http_proxy_service;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::{fmt, EnvFilter};

use auth::AuthService;
use config::Config;
use db::Database;
use proxy::ApiGatewayProxy;

/// 로깅 초기화
fn init_logging(config: &Config) {
    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(&config.logging.level));

    fmt()
        .with_env_filter(filter)
        .with_target(true)
        .with_thread_ids(true)
        .with_file(true)
        .with_line_number(true)
        .init();
}

fn main() {
    // 설정 로드
    let config = Config::load().expect("Failed to load configuration");

    // 로깅 초기화
    init_logging(&config);

    info!("Starting NEOS API Gateway...");
    info!(
        "Listening on {}:{}",
        config.server.listen_addr, config.server.listen_port
    );
    info!(
        "Upstream: {}:{}",
        config.upstream.host, config.upstream.port
    );

    // Pingora 서버 생성
    let mut server = Server::new(None).unwrap();
    server.bootstrap();

    // 비동기 런타임에서 초기화 수행
    let rt = tokio::runtime::Runtime::new().unwrap();

    let (auth_service, upstream_config) = rt.block_on(async {
        // 데이터베이스 연결
        let db = Database::new(&config.database)
            .await
            .expect("Failed to connect to database");

        info!("Database connection established");

        // 인증 서비스 생성
        let auth_service = AuthService::new(
            config.jwt.clone(),
            config.auth.clone(),
            config.api_key.clone(),
            db,
        )
        .expect("Failed to create auth service");

        (Arc::new(auth_service), config.upstream.clone())
    });

    // 프록시 서비스 생성
    let proxy = ApiGatewayProxy::new(auth_service, upstream_config);

    // HTTP 프록시 서비스 생성 및 등록
    let listen_addr = format!(
        "{}:{}",
        config.server.listen_addr, config.server.listen_port
    );
    let mut http_service = http_proxy_service(&server.configuration, proxy);
    http_service.add_tcp(&listen_addr);

    server.add_service(http_service);

    info!("API Gateway started successfully");

    // 서버 실행
    server.run_forever();
}
