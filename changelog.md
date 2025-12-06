# Changelog

## v0.13.0 (2025-12-06)
- [x] Implement Skills module for extensibility
- [x] Add skill-based tool selection to agents
- [x] Add research and workflow skills to neos
- [x] Analyze and improve Neos backend code
  - [x] Security hardening by forcing JWT secret key in .env
  - [x] Update CORS policy
  - [x] API key hashing algorithm update to bcrypt
  - [x] Optimize DB connection pooling
  - [x] Use context manager for session handling to prevent leaks
  - [x] Introduce circuit breaker pattern for external API calls
  - [x] Enable the semantic cache by default
  - [x] Add Redis connection pool settings
- [x] Redis-based Rate Limiting
- [x] API Key Scope Management
- [x] Fix up N+1 issues in backend code
- [x] Fix pytest test suite configuration errors
  - [x] Fix CORS_ALLOWED_ORIGINS parsing error preventing test collection
  - [x] Fix extra environment variables validation error
  - [x] Fix event loop conflicts in async tests with database manager reset
  - [x] Create centralized conftest.py with proper fixture management
  - [x] Implement automatic test data cleanup between tests
  - [x] Fix foreign key constraint violations in test cleanup
  - [x] Test suite now operational: 273/287 tests passing (95.1%), 0 errors
- [x] Timeout Optimization
  - [x] Reduce search orchestration timeout from 600s to 20s (configurable)
  - [x] Add per-agent timeout settings (AGENT_TIMEOUTS dict)
  - [x] Implement individual agent timeout wrapping for graceful handling
  - [x] Search agents: 15-30s, Analysis agents: 45-60s, Generation agents: 30-120s
  - [x] Deep research agents retain longer timeouts (300-600s)
- [x] Streaming Response Implementation
  - [x] Add SSE-based /query/stream endpoint for real-time workflow updates
  - [x] Add WebSocket endpoints (/ws/query/{session_id}, /ws/query/detailed/{session_id})
  - [x]Implement WorkflowStreamCallback for event-based progress tracking
  - [x] Support heartbeat, node progress, agent progress, and partial content events
  - [x] Add WorkflowStreamEvent and WorkflowStreamRequest models

## v0.12.0 (2025-11-30)
- [x] Add context saving strategy
  - [x] context optimization for deep research
  - [x] context optimization for multi-agent workflows
- [x] Fix up hard-coded plan in DeepResearchAgent and HyperDeepResearchAgent (only run 4 steps out of N steps)
- [x] Update the UI styles
- [x] Add support for connection loss on DeepResearch refresh
  - [x] Heartbeat timeout detection (30s)
  - [x] Multi-tab synchronization via BroadcastChannel
  - [x] Online/offline network detection
  - [x] Extended reconnection timeout (5 → 10 attempts)
  - [x] Partial results persistence to localStorage
- [x] Fix deep research content restoration on page refresh
  - [x] Restore completed sections from backend when page refreshes
  - [x] Properly rebuild research artifacts from backend data
  - [x] Display completed/failed research status with full content
  - [x] Maintain progress information during reconnection
- [x] Fix event sequence number collision in concurrent deep research operations
  - [x] Implement retry mechanism for unique constraint violations
  - [x] Fetch next sequence number from database instead of using instance counter
  - [x] Prevent duplicate key errors during concurrent LLM calls
- [x] Fix conversation mode persistence on page refresh
  - [x] Sync settings.mode with conversation.mode when loading conversations
  - [x] Sync settings.mode when switching between conversations
  - [x] Prevent deep research conversations from showing as 'standard' mode after refresh

## v0.11.0 (2025-11-23)
- [x] Update HyperDeepResearch
- [x] Add support for production deployment
- [x] Add security features for user authentication and data protection
  - [x] CSRF protection
  - [x] BFF-based architecture
  - [x] Rate limiting for API endpoints

## v0.10.0 (2025-11-14)
- [x] Make the Deep Research API work with the web UI
  - [x] Allow user to call the hyper deep research workflow from the web interface
  - [x] Display progress and results in the web UI
  - [x] Use the response streaming feature for real-time updates

## v0.9.0 (2025-11-07)
- [x] Implement the web UI (alpha version)
- [x] Add chat API with message history support (beta release)

## v0.8.1 (2025-11-03)
- [x] Refactor API handlers
  - [x] Move route definitions to dedicated handler modules
  - [x] Improve modularity and maintainability of API code

## v0.8.0 (2025-11-03)
- [x] Add image inference API
  - [x] Implement image upload endpoint
  - [x] Integrate GPT-4 Vision and Claude 3 for image analysis
  - [x] Develop image-based question answering functionality
- [x] Refactor the image processing module
  - [x] Modularize image preprocessing and inference components
  - [x] Optimize performance for large image files

## v0.7.0 (2025-11-02)
- [x] Add WebLookupAgent to support advanced web content extraction
  - [x] Integrate trafilatura for robust HTML parsing
  - [x] Implement metadata extraction and structured data handling
  - [x] Develop reliability scoring for search results
- [x] Add Playwright support for dynamic web page rendering
  - [x] Integrate Playwright for JavaScript-heavy SPA content extraction
  - [x] Provide CLI option for dynamic rendering
  - [x] Update documentation for Playwright setup and usage

## v0.6.2 (2025-11-02)
- [x] Fix knowledge graph extractor to use the correct LLM instance
  - [x] Replace `get_llm` with `create_llm` in `knowledge_graph.py`
  - [x] Ensure proper logging setup for knowledge graph extraction
- [x] Update tests to reflect changes in LLM instantiation
- [x] Refactor codes for MCP manager
- [x] Add S3-like storage support to document management pipeline
  - [x] Integrate `boto3` for AWS S3 support
  - [x] Implement `rustfs` support for S3-compatible storage
  - [x] Update document processing pipeline to handle file uploads to S3/rustfs/local storage

## v0.6.1 (2025-10-26)
- [x] change timeout of hyper-deep-research from 60 minutes to 120 minutes in CLI and agent code
- [x] Make API-call agent to work with real API keys and endpoints

## v0.6.0 (2025-10-25)
- [x] Hyper Deep Research 응답 시 언어 감지 및 사용자 쿼리와 동일 언어 사용 진행
  - [x] Hyper Deep Research 응답 생성 시 감지된 언어로 출력

## v0.5.6 (2025-10-22)
- [x] various refactorings (no functional changes)

## v0.5.5 (2025-10-15)
- [x] PPT 파서 추가
  - [x] python-pptx 라이브러리 도입
  - [x] PPT 파일 텍스트 추출 및 전처리
- [x] CSV 파서 추가
  - [x] 대용량 CSV 파일 처리 최적화
  - [x] 다양한 인코딩 지원 강화

## v0.5.4 (2025-10-15)
- [x] 문서 파이프라인에 Word, Excel 파서 추가
  - [x] python-docx, openpyxl 라이브러리 도입
  - [x] Word, Excel 파일 텍스트 추출 및 전처리

## v0.5.3 (2025-10-14)
- [x] Multimodal LLM 통합
  - [x] GPT-4V, Claude Vision 지원
- [x] 이미지 및 PDF 분석 에이전트 추가
  - [x] 이미지 모델 통합
  - [x] PDF 파싱 및 분석
- [x] 멀티모달 워크플로우 파이프라인 기본 구조 구현

## v0.5.2 (2025-10-12)
- [x] 에이전트 레지스트리 기능 추가
  - [x] 커스텀 에이전트 등록/관리 기능
  - [x] 워크플로우에서 커스텀 에이전트 사용 지원
  - [x] 에이전트 레지스트리 CLI 명령어
- [x] workflow builder 코드 리팩토링
  - [x] 모듈화 및 구조 개선
  - [x] 테스트 커버리지 향상

## v0.5.1 (2025-10-12)
- [x] 워크플로우 빌더 CLI 개선
  - [x] 워크플로우 생성 시 성공 메시지 출력
  - [x] 워크플로우 구성 및 실행 데이터 저장을 위한 스키마 설계
  - [x] 워크플로우 활성화/비활성화 시 피드백 메시지 개선
  - [x] MCP 서버 삭제 시 피드백 메시지 개선

## v0.5.0 (2025-10-11)
- [x] WebLookupAgent 도입
  - [x] trafilatura 기반 웹 페이지 콘텐츠 추출
  - [x] 메타데이터 및 구조화된 데이터 추출
  - [x] 검색 결과의 신뢰성 평가 및 필터링

## v0.4.3 (2025-10-11)
- [x] 웹 검색 통계 분석 기능 추가
  - [x] 검색 로그 데이터베이스 스키마 개선
  - [x] 검색 성능 및 품질 메트릭 저장
  - [x] 웹 검색 분석 API 엔드포인트 추가

## v0.4.2 (2025-10-11)
- [x] 웹 검색 로깅 기능 개선
  - [x] Redis 메시지 큐 지원 추가
  - [x] 비동기 로깅 성능 최적화
  - [x] 데이터베이스 스키마 개선 및 인덱스 추가

## v0.4.1 (2025-10-10)
- [x] 🔬 HyperDeepResearch 모드 추가
  - [x] 계획 산출 → 순차적 조사 → 다중 쿼리 서치 → 반복적 심층 분석 → 보고서 섹션별 생성
  - [x] DB 스키마 확장 및 섹션 별 저장 처리
  - [x] HyperDeepResearch CLI 지원
  - [x] HyperDeepResearch API 지원
- [x] HyperDeepResearch 에서 'critical thinking' 기능 도입
- [x] 자기비판 피드백 에이전트 (Self-Criticism Feedback Agent)
  - [x] 피드백 분석 및 추가 연구 트리거링
  - [x] 개선된 보고서 품질 및 정확성

## v0.4 (2025-10-03)

- [x] 멀티 에이전트 LangGraph 워크플로우
- [x] OpenAI + Anthropic 멀티 Provider 지원
- [x] 다층 캐싱 시스템
- [x] 벡터 기반 의미적 검색
- [x] 실시간 WebSocket 통신
- [x] 품질 기반 자동 재처리
- [x] LLM 호출 데이터셋 자동 수집 및 저장
- [x] 🆕 복합검색 에이전트 (Multi-Query Search Agent)
  - [x] 쿼리 복잡도 자동 분석 시스템
  - [x] LLM 기반 다중 쿼리 생성 (2-5개)
  - [x] 병렬 검색 및 요약 처리
  - [x] 종합 분석 리포트 생성
- [x] 🔬 Deep Research 모드
  - [x] 4단계 심층 탐색 프로세스 (초기 탐색 → Gap 분석 → 검증 → 리포트)
  - [x] 체크포인트 시스템 및 진행 상황 추적
  - [x] 대량 소스 수집 (30-50개+)
  - [x] 전문가급 마크다운 리포트 생성
  - [x] CLI 명령어 지원 (`workflow deep-research`)
