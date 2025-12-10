//! 프록시 서비스 모듈
//!
//! Pingora 기반의 리버스 프록시 서비스를 구현합니다.
//! JWT/API 키 인증 후 X-User-ID 헤더를 추가하여 업스트림으로 요청을 전달합니다.

use async_trait::async_trait;
use http::StatusCode;
use pingora_core::prelude::*;
use pingora_http::{RequestHeader, ResponseHeader};
use pingora_load_balancing::health_check::TcpHealthCheck;
use pingora_load_balancing::{selection::RoundRobin, LoadBalancer};
use pingora_proxy::{ProxyHttp, Session};
use std::sync::Arc;
use tracing::{debug, info, warn};

use crate::auth::{AuthError, AuthService};
use crate::config::UpstreamConfig;

/// API 게이트웨이 프록시 서비스
pub struct ApiGatewayProxy {
    /// 인증 서비스
    auth_service: Arc<AuthService>,
    /// 업스트림 로드밸런서
    lb: Arc<LoadBalancer<RoundRobin>>,
    /// User ID 헤더 이름 (저장용)
    user_id_header: String,
}

/// 요청 컨텍스트
pub struct RequestContext {
    /// 인증된 사용자 ID (인증 성공 시)
    pub user_id: Option<String>,
    /// 요청 경로
    pub path: String,
    /// 클라이언트 IP
    pub client_ip: Option<String>,
    /// 인증 건너뛰기 여부
    pub skip_auth: bool,
}

impl ApiGatewayProxy {
    /// 새 프록시 서비스 생성
    pub fn new(auth_service: Arc<AuthService>, upstream_config: UpstreamConfig) -> Self {
        // 업스트림 서버 설정
        let upstream_addr = upstream_config.addr();
        let mut upstreams = LoadBalancer::try_from_iter([upstream_addr.as_str()]).unwrap();

        // 헬스체크 설정
        let health_check = TcpHealthCheck::new();
        upstreams.set_health_check(health_check);
        upstreams.health_check_frequency = Some(std::time::Duration::from_secs(
            upstream_config.health_check_interval_secs,
        ));

        let user_id_header = auth_service.user_id_header().to_string();

        Self {
            auth_service,
            lb: Arc::new(upstreams),
            user_id_header,
        }
    }

    /// 로드밸런서 Arc 반환 (백그라운드 서비스용)
    pub fn lb(&self) -> Arc<LoadBalancer<RoundRobin>> {
        self.lb.clone()
    }

    /// 인증 실패 응답 생성
    fn create_error_response(status: StatusCode) -> ResponseHeader {
        let mut header = ResponseHeader::build(status, None).unwrap();
        header
            .insert_header("Content-Type", "application/json")
            .unwrap();
        header
    }

    /// 클라이언트 IP 추출
    fn get_client_ip(session: &Session) -> Option<String> {
        // X-Forwarded-For 헤더 확인
        if let Some(xff) = session.req_header().headers.get("X-Forwarded-For") {
            if let Ok(xff_str) = xff.to_str() {
                // 첫 번째 IP 반환
                return xff_str.split(',').next().map(|s| s.trim().to_string());
            }
        }

        // X-Real-IP 헤더 확인
        if let Some(real_ip) = session.req_header().headers.get("X-Real-IP") {
            if let Ok(ip) = real_ip.to_str() {
                return Some(ip.to_string());
            }
        }

        // 직접 연결된 클라이언트 주소
        session.client_addr().map(|addr| addr.to_string())
    }
}

#[async_trait]
impl ProxyHttp for ApiGatewayProxy {
    type CTX = RequestContext;

    /// 요청 컨텍스트 생성
    fn new_ctx(&self) -> Self::CTX {
        RequestContext {
            user_id: None,
            path: String::new(),
            client_ip: None,
            skip_auth: false,
        }
    }

    /// 요청 필터 (인증 처리)
    async fn request_filter(&self, session: &mut Session, ctx: &mut Self::CTX) -> Result<bool> {
        let req = session.req_header();
        ctx.path = req.uri.path().to_string();
        ctx.client_ip = Self::get_client_ip(session);

        debug!("Processing request: {} {}", req.method, ctx.path);

        // 공개 경로인지 확인
        if self.auth_service.is_public_path(&ctx.path) {
            debug!("Public path, skipping authentication: {}", ctx.path);
            ctx.skip_auth = true;
            return Ok(false); // 요청 계속 처리
        }

        // Authorization 헤더 추출
        let auth_header = req
            .headers
            .get(self.auth_service.authorization_header())
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());

        // X-API-Key 헤더 추출
        let api_key_header = req
            .headers
            .get(self.auth_service.api_key_header())
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());

        // 인증 수행
        match self
            .auth_service
            .authenticate(
                auth_header.as_deref(),
                api_key_header.as_deref(),
                ctx.client_ip.as_deref(),
            )
            .await
        {
            Ok(auth_result) => {
                ctx.user_id = Some(auth_result.user_id.clone());
                debug!("Authentication successful: user_id={}", auth_result.user_id);
                Ok(false) // 요청 계속 처리
            }
            Err(e) => {
                warn!("Authentication failed: {:?}", e);

                let (status, message) = match e {
                    AuthError::MissingAuthHeader => (
                        StatusCode::UNAUTHORIZED,
                        "Missing authentication credentials",
                    ),
                    AuthError::InvalidJwt(_) | AuthError::InvalidApiKey => (
                        StatusCode::UNAUTHORIZED,
                        "Invalid authentication credentials",
                    ),
                    AuthError::JwtExpired | AuthError::ApiKeyExpired => (
                        StatusCode::UNAUTHORIZED,
                        "Authentication credentials expired",
                    ),
                    AuthError::UserNotFound(_) | AuthError::UserNotActive => {
                        (StatusCode::FORBIDDEN, "User access denied")
                    }
                    AuthError::DatabaseError(_) => (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "Authentication service unavailable",
                    ),
                    _ => (StatusCode::UNAUTHORIZED, "Authentication failed"),
                };

                let error_body = serde_json::json!({
                    "error": message,
                    "status": status.as_u16()
                })
                .to_string();

                let header = Self::create_error_response(status);
                session
                    .write_response_header(Box::new(header), false)
                    .await?;
                session
                    .write_response_body(Some(error_body.into()), true)
                    .await?;

                Ok(true) // 요청 처리 중단
            }
        }
    }

    /// 업스트림 피어 선택
    async fn upstream_peer(
        &self,
        _session: &mut Session,
        _ctx: &mut Self::CTX,
    ) -> Result<Box<HttpPeer>> {
        let upstream = self.lb.select(b"", 256).unwrap();

        let peer = Box::new(HttpPeer::new(
            upstream,
            false, // TLS 사용 여부
            String::new(),
        ));

        Ok(peer)
    }

    /// 업스트림 요청 헤더 수정
    async fn upstream_request_filter(
        &self,
        _session: &mut Session,
        upstream_request: &mut RequestHeader,
        ctx: &mut Self::CTX,
    ) -> Result<()> {
        // 인증된 사용자 ID를 헤더에 추가
        if let Some(ref user_id) = ctx.user_id {
            let header_name = self.user_id_header.clone();
            upstream_request
                .insert_header(header_name, user_id)
                .unwrap();
            debug!("Added {} header: {}", self.user_id_header, user_id);
        }

        // 클라이언트 IP 전달
        if let Some(ref client_ip) = ctx.client_ip {
            upstream_request
                .insert_header("X-Forwarded-For", client_ip)
                .unwrap();
            upstream_request
                .insert_header("X-Real-IP", client_ip)
                .unwrap();
        }

        Ok(())
    }

    /// 로깅 필터
    async fn logging(
        &self,
        session: &mut Session,
        _error: Option<&pingora_core::Error>,
        ctx: &mut Self::CTX,
    ) {
        let response_code = session
            .response_written()
            .map(|r| r.status.as_u16())
            .unwrap_or(0);

        let user_id = ctx.user_id.as_deref().unwrap_or("-");
        let client_ip = ctx.client_ip.as_deref().unwrap_or("-");

        info!(
            "{} {} {} {} \"{}\"",
            client_ip,
            user_id,
            session.req_header().method,
            ctx.path,
            response_code
        );
    }
}
