# Changelog

## v0.18.0 (2025-12-26)
* Make chat stream API to use agent workflow
* Enhance the search orchestrator and it's agents
* Fix asyncio event loop conflict in workflow execution
  * Add LLM instance caching to prevent event loop capture issues
  * Implement singleton pattern for LLM instances (same provider + model + temperature)
  * Resolve "Task got Future attached to a different loop" errors during concurrent requests
  * Improve performance and memory usage by reusing LLM HTTP clients
  * Add `use_cache` parameter to `create_llm()` for explicit cache control
* Add markdown-it parser for document rendering in web UI
  * Replace previous markdown parser with `markdown-it` for better compatibility
  * Update editor functions to use `markdown-it` for parsing and rendering
  * Improve handling of complex markdown features (tables, code blocks, etc.)
  * Ensure consistent document display across different artifact types

## v0.17.1 (2025-12-24)
* Fix artifact generation streaming issue
* Ensure proper handling of artifact streaming events
* Correctly propagate artifact metadata and content during chat responses
* Migrate the history API and chat message list to use backend conversation ID
  * Update chat message retrieval to fetch messages using backendConversationId
  * Modify chat history API to support backend conversation ID mapping
  * Ensure seamless integration between frontend chat and backend conversation tracking

## v0.17.0 (2025-12-23)
* Fix up entitlements for regular users
* Implement automatic token refresh and auto-logout for web authentication
  * Add JWT access token expiration tracking (15-minute validity)
  * Implement automatic token refresh 5 minutes before expiration
  * Add SessionProvider auto-refresh (5-minute interval, on window focus)
  * Create useAuthMonitor hook for client-side session monitoring
  * Add AuthMonitor component for global authentication state tracking
  * Implement auto-logout when refresh token expires
  * Enhance auth.ts with refreshAccessToken function
  * Add session error propagation for expired tokens
* Migrate Artifacts functionality from Next.js to Python backend
  * Create ArtifactLLMService for AI-powered artifact generation (text, code, sheet)
  * Add Anthropic tool use API integration for createDocument and updateDocument
  * Implement streaming artifact generation with real-time content updates
  * Extend ChatStreamChunk model with artifact-specific fields (artifact_id, artifact_title, artifact_kind)
  * Add ChatLLMService.generate_response_stream_with_tools() for tool calling support
  * Integrate artifact streaming into chat handler with SSE event types (artifact_meta, artifact_delta, artifact_finish)
  * Add artifact configuration settings (ARTIFACTS_ENABLED, ARTIFACT_LLM_MODEL, ARTIFACTS_SYSTEM_PROMPT)
  * Implement artifact tool definitions and handlers for document creation/updates
  * Support version history for artifacts with composite primary key (id, created_at)
  * Enable seamless artifact generation during chat conversations
  * Default to Claude Haiku for cost-efficient artifact generation with configurable model selection
* Add JWT token refresh communication between BFF and backend services
* Add title generation based on user message content

## v0.16.0 (2025-12-20)
* Add Google Gemini support for LLM, Vision, and Embeddings
  * Implement GeminiProvider for chat/text generation using langchain-google-genai
  * Add GeminiVision for image analysis with vision-capable models
  * Create embedding provider abstraction layer supporting multiple providers
  * Add GeminiEmbeddingProvider with configurable dimensions (128-3072)
  * Configure Gemini embeddings to use 1536 dimensions for OpenAI compatibility
  * Add embedding provider metadata to database (provider, model columns)
  * Create database migration 006 for multi-provider embedding support
  * Update all services to track embedding provider information
  * Add fallback mechanisms for LLM, Vision, and Embedding providers
  * Support seamless switching between OpenAI, Anthropic, and Gemini
* Fix up skill selection management
* Update the session management in web component and BFF for auto token refresh
* Add RustFS (S3-compatible) on-premise storage support
  * Integrate MinIO-based rustfs service in docker-compose.enterprise.yml
  * Add rustfs storage provider configuration with S3-compatible API
  * Create rustfs-init service for automatic bucket creation
  * Add comprehensive storage provider abstraction (S3, RustFS, Local)
  * Update backend services with rustfs environment variables
  * Add storage volume management for persistent data
* Enhance multimodal document processing pipeline
  * Complete integration of storage service with document processor
  * Implement full document lifecycle: upload, process, chunk, embed, index
  * Add knowledge graph extraction support for uploaded documents
  * Enable semantic search across document chunks with pgvector
  * Support multiple storage backends (s3, rustfs, local) with easy switching
* Add integration testing
  * Create test_document_upload.py script for end-to-end testing
  * Add storage provider connection tests
  * Add document processing pipeline tests
  * Add semantic search validation tests
* Add support for Google OAuth2 authentication
  * Implement Google OAuth2 login flow in backend
  * Create database schema for OAuth2 users and tokens
  * Add configuration settings for Google OAuth2 client ID
  * Update user management to support OAuth2 users
* Enhance the Skill system
  * Add YAML-based skill configuration support
  * Update skill loader to parse SKILL.yaml files
  * Improve skill metadata management with YAML
  * Refactor builtin skills to use YAML configuration
  * Update skill documentation with YAML examples
* Renewal the FE

## v0.15.0 (2025-12-12)
* Add API Gateway support
  * Introduce API Gateway mode in Neos backend
  * Trust user identity from API Gateway via configurable header (default: X-User-ID)
  * Restrict access to trusted gateway IPs only
  * Bypass API key authentication when valid user ID is provided by trusted gateway
  * Update authentication dependency to handle gateway mode
  * Add configuration settings for gateway mode, header name, and trusted IPs
* Refactor HyperDeepResearch agent
* Fix minor bugs in DeepResearch agent
* Update web dependencies to protect against React2Shell vulnerability
* Fix thinking blocks max_tokens validation error
  * Automatically set max_tokens > thinking.budget_tokens when using extended thinking
  * Add validation and adjustment logic for max_tokens parameter
  * Prevent 400 Bad Request errors from Anthropic API
* Fix chat streaming error with thinking blocks
  * Fix "can only concatenate str (not "list") to str" error in streaming responses
  * Use extract_text_from_response() to properly handle thinking block content
  * Apply fix to both streaming and non-streaming chat responses
* Implement the missing HyperDeepResearch model
* Fix up the Chat Streaming Error

## v0.14.0 (2025-12-09)

* Implement smart caching strategy for backend
  * Add QueryCacheEntry and CacheStatistics models for persistent caching
  * Implement SmartCacheManager with dynamic TTL calculation based on query intent, complexity, and response quality
  * Integrate smart cache into workflow execution with semantic similarity search
  * Add PostgreSQL migration for query_cache and cache_statistics tables with pgvector indexes
  * Support configurable TTL by query type
  * Track cache statistics including hit rates, semantic vs exact hits, and performance metrics
* Add support for `thinking` block for Anthropic APIs
* Build user behavior analytics backoffice system
  * Launched Analytics Backoffice application with full dashboard for conversation analysis
  * Added analysis run management: create, list, monitor, and delete analysis runs
  * Introduced interactive cluster hierarchy visualization with drill-down exploration
  * Added UMAP 2D visualization with dynamic color-by options (task type, language, cluster)
  * Implemented trending topics and facet distribution analysis
  * Added cluster search, comparison, and detailed statistics views
  * Integrated privacy protections: PII detection, masking, and k-anonymity filtering

## v0.13.0 (2025-12-06)
* Implement Skills module for extensibility
* Add skill-based tool selection to agents
* Add research and workflow skills to neos
* Analyze and improve Neos backend code
  * Security hardening by forcing JWT secret key in .env
  * Update CORS policy
  * API key hashing algorithm update to bcrypt
  * Optimize DB connection pooling
  * Use context manager for session handling to prevent leaks
  * Introduce circuit breaker pattern for external API calls
  * Enable the semantic cache by default
  * Add Redis connection pool settings
* Redis-based Rate Limiting
* API Key Scope Management
* Fix up N+1 issues in backend code
* Fix pytest test suite configuration errors
  * Fix CORS_ALLOWED_ORIGINS parsing error preventing test collection
  * Fix extra environment variables validation error
  * Fix event loop conflicts in async tests with database manager reset
  * Create centralized conftest.py with proper fixture management
  * Implement automatic test data cleanup between tests
  * Fix foreign key constraint violations in test cleanup
  * Test suite now operational: 273/287 tests passing (95.1%), 0 errors
* Timeout Optimization
  * Reduce search orchestration timeout from 600s to 20s (configurable)
  * Add per-agent timeout settings (AGENT_TIMEOUTS dict)
  * Implement individual agent timeout wrapping for graceful handling
  * Search agents: 15-30s, Analysis agents: 45-60s, Generation agents: 30-120s
  * Deep research agents retain longer timeouts (300-600s)
* Streaming Response Implementation
  * Add SSE-based /query/stream endpoint for real-time workflow updates
  * Add WebSocket endpoints (/ws/query/{session_id}, /ws/query/detailed/{session_id})
  *Implement WorkflowStreamCallback for event-based progress tracking
  * Support heartbeat, node progress, agent progress, and partial content events
  * Add WorkflowStreamEvent and WorkflowStreamRequest models

## v0.12.0 (2025-11-30)
* Add context saving strategy
  * context optimization for deep research
  * context optimization for multi-agent workflows
* Fix up hard-coded plan in DeepResearchAgent and HyperDeepResearchAgent (only run 4 steps out of N steps)
* Update the UI styles
* Add support for connection loss on DeepResearch refresh
  * Heartbeat timeout detection (30s)
  * Multi-tab synchronization via BroadcastChannel
  * Online/offline network detection
  * Extended reconnection timeout (5 → 10 attempts)
  * Partial results persistence to localStorage
* Fix deep research content restoration on page refresh
  * Restore completed sections from backend when page refreshes
  * Properly rebuild research artifacts from backend data
  * Display completed/failed research status with full content
  * Maintain progress information during reconnection
* Fix event sequence number collision in concurrent deep research operations
  * Implement retry mechanism for unique constraint violations
  * Fetch next sequence number from database instead of using instance counter
  * Prevent duplicate key errors during concurrent LLM calls
* Fix conversation mode persistence on page refresh
  * Sync settings.mode with conversation.mode when loading conversations
  * Sync settings.mode when switching between conversations
  * Prevent deep research conversations from showing as 'standard' mode after refresh

## v0.11.0 (2025-11-23)
* Update HyperDeepResearch
* Add support for production deployment
* Add security features for user authentication and data protection
  * CSRF protection
  * BFF-based architecture
  * Rate limiting for API endpoints

## v0.10.0 (2025-11-14)
* Make the Deep Research API work with the web UI
  * Allow user to call the hyper deep research workflow from the web interface
  * Display progress and results in the web UI
  * Use the response streaming feature for real-time updates

## v0.9.0 (2025-11-07)
* Implement the web UI (alpha version)
* Add chat API with message history support (beta release)

## v0.8.1 (2025-11-03)
* Refactor API handlers
  * Move route definitions to dedicated handler modules
  * Improve modularity and maintainability of API code

## v0.8.0 (2025-11-03)
* Add image inference API
  * Implement image upload endpoint
  * Integrate GPT-4 Vision and Claude 3 for image analysis
  * Develop image-based question answering functionality
* Refactor the image processing module
  * Modularize image preprocessing and inference components
  * Optimize performance for large image files

## v0.7.0 (2025-11-02)
* Add WebLookupAgent to support advanced web content extraction
  * Integrate trafilatura for robust HTML parsing
  * Implement metadata extraction and structured data handling
  * Develop reliability scoring for search results
* Add Playwright support for dynamic web page rendering
  * Integrate Playwright for JavaScript-heavy SPA content extraction
  * Provide CLI option for dynamic rendering
  * Update documentation for Playwright setup and usage

## v0.6.2 (2025-11-02)
* Fix knowledge graph extractor to use the correct LLM instance
  * Replace `get_llm` with `create_llm` in `knowledge_graph.py`
  * Ensure proper logging setup for knowledge graph extraction
* Update tests to reflect changes in LLM instantiation
* Refactor codes for MCP manager
* Add S3-like storage support to document management pipeline
  * Integrate `boto3` for AWS S3 support
  * Implement `rustfs` support for S3-compatible storage
  * Update document processing pipeline to handle file uploads to S3/rustfs/local storage

## v0.6.1 (2025-10-26)
* change timeout of hyper-deep-research from 60 minutes to 120 minutes in CLI and agent code
* Make API-call agent to work with real API keys and endpoints

## v0.6.0 (2025-10-25)
* Hyper Deep Research 응답 시 언어 감지 및 사용자 쿼리와 동일 언어 사용 진행
  * Hyper Deep Research 응답 생성 시 감지된 언어로 출력

## v0.5.6 (2025-10-22)
* various refactorings (no functional changes)

## v0.5.5 (2025-10-15)
* PPT 파서 추가
  * python-pptx 라이브러리 도입
  * PPT 파일 텍스트 추출 및 전처리
* CSV 파서 추가
  * 대용량 CSV 파일 처리 최적화
  * 다양한 인코딩 지원 강화

## v0.5.4 (2025-10-15)
* 문서 파이프라인에 Word, Excel 파서 추가
  * python-docx, openpyxl 라이브러리 도입
  * Word, Excel 파일 텍스트 추출 및 전처리

## v0.5.3 (2025-10-14)
* Multimodal LLM 통합
  * GPT-4V, Claude Vision 지원
* 이미지 및 PDF 분석 에이전트 추가
  * 이미지 모델 통합
  * PDF 파싱 및 분석
* 멀티모달 워크플로우 파이프라인 기본 구조 구현

## v0.5.2 (2025-10-12)
* 에이전트 레지스트리 기능 추가
  * 커스텀 에이전트 등록/관리 기능
  * 워크플로우에서 커스텀 에이전트 사용 지원
  * 에이전트 레지스트리 CLI 명령어
* workflow builder 코드 리팩토링
  * 모듈화 및 구조 개선
  * 테스트 커버리지 향상

## v0.5.1 (2025-10-12)
* 워크플로우 빌더 CLI 개선
  * 워크플로우 생성 시 성공 메시지 출력
  * 워크플로우 구성 및 실행 데이터 저장을 위한 스키마 설계
  * 워크플로우 활성화/비활성화 시 피드백 메시지 개선
  * MCP 서버 삭제 시 피드백 메시지 개선

## v0.5.0 (2025-10-11)
* WebLookupAgent 도입
  * trafilatura 기반 웹 페이지 콘텐츠 추출
  * 메타데이터 및 구조화된 데이터 추출
  * 검색 결과의 신뢰성 평가 및 필터링

## v0.4.3 (2025-10-11)
* 웹 검색 통계 분석 기능 추가
  * 검색 로그 데이터베이스 스키마 개선
  * 검색 성능 및 품질 메트릭 저장
  * 웹 검색 분석 API 엔드포인트 추가

## v0.4.2 (2025-10-11)
* 웹 검색 로깅 기능 개선
  * Redis 메시지 큐 지원 추가
  * 비동기 로깅 성능 최적화
  * 데이터베이스 스키마 개선 및 인덱스 추가

## v0.4.1 (2025-10-10)
* 🔬 HyperDeepResearch 모드 추가
  * 계획 산출 → 순차적 조사 → 다중 쿼리 서치 → 반복적 심층 분석 → 보고서 섹션별 생성
  * DB 스키마 확장 및 섹션 별 저장 처리
  * HyperDeepResearch CLI 지원
  * HyperDeepResearch API 지원
* HyperDeepResearch 에서 'critical thinking' 기능 도입
* 자기비판 피드백 에이전트 (Self-Criticism Feedback Agent)
  * 피드백 분석 및 추가 연구 트리거링
  * 개선된 보고서 품질 및 정확성

## v0.4 (2025-10-03)

* 멀티 에이전트 LangGraph 워크플로우
* OpenAI + Anthropic 멀티 Provider 지원
* 다층 캐싱 시스템
* 벡터 기반 의미적 검색
* 실시간 WebSocket 통신
* 품질 기반 자동 재처리
* LLM 호출 데이터셋 자동 수집 및 저장
* 🆕 복합검색 에이전트 (Multi-Query Search Agent)
  * 쿼리 복잡도 자동 분석 시스템
  * LLM 기반 다중 쿼리 생성 (2-5개)
  * 병렬 검색 및 요약 처리
  * 종합 분석 리포트 생성
* 🔬 Deep Research 모드
  * 4단계 심층 탐색 프로세스 (초기 탐색 → Gap 분석 → 검증 → 리포트)
  * 체크포인트 시스템 및 진행 상황 추적
  * 대량 소스 수집 (30-50개+)
  * 전문가급 마크다운 리포트 생성
  * CLI 명령어 지원 (`workflow deep-research`)
