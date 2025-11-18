# NEOS 아키텍처 문서

## 목차
1. [개요](#개요)
2. [서버/웹 구조](#서버웹-구조)
3. [API 목록](#api-목록)
4. [코드 구성](#코드-구성)
5. [데이터베이스 구조](#데이터베이스-구조)
6. [워크플로우 및 에이전트](#워크플로우-및-에이전트)
7. [주요 기능](#주요-기능)

---

## 개요

NEOS는 고급 멀티 에이전트 AI 시스템으로, FastAPI 기반 백엔드와 Next.js 기반 프론트엔드로 구성되어 있습니다.

**핵심 기술 스택:**
- **백엔드**: FastAPI 0.116.1+, Python 3.10+
- **프론트엔드**: Next.js 14.2.33, React 18.3.1, TypeScript
- **데이터베이스**: PostgreSQL (pgvector, pg_trgm)
- **캐시**: Redis (Valkey)
- **AI 프레임워크**: LangGraph, CrewAI
- **상태 관리**: Zustand 4.5.7
- **세션 관리**: iron-session
- **스타일링**: Tailwind CSS

**버전**: 0.10.0

---

## 서버/웹 구조

### 1. 백엔드 서버 (FastAPI)

**위치**: `/home/user/neos/neos/main.py`
**포트**: 8518
**실행 방법**:
```bash
python3 -m neos.main
# 또는
uvicorn neos.main:app
```

**서버 구성:**
- CORS 미들웨어 (설정 가능한 오리진)
- GZip 압축 (1000바이트 이상 응답)
- 요청 로깅 및 성능 모니터링 미들웨어
- 전역 예외 핸들러
- 헬스 체크 및 시스템 정보 엔드포인트

**생명주기 관리:**
- 데이터베이스 연결 초기화 (PostgreSQL with asyncpg)
- Redis 캐시 연결 설정
- 우아한 종료 (Graceful shutdown) 및 리소스 정리

### 2. 프론트엔드 서버 (Next.js)

**위치**: `/home/user/neos/web/`
**프레임워크**: Next.js 14 (App Router)

**웹 라우트:**
- `/` - 홈페이지 (채팅 컴포저)
- `/chat/[id]` - 개별 채팅 대화 뷰
- `/login` - 인증 페이지
- `/api/auth/*` - 인증 API 라우트 (BFF 패턴)
- `/api/chat` - 채팅 API 프록시 라우트

**주요 컴포넌트:**
- 스트리밍 지원 채팅 인터페이스
- 마크다운 렌더링 메시지 버블
- 대화 기록 사이드바
- 설정 패널
- 인증 폼
- CSRF 보호

**보안 기능:**
- CSRF 토큰 검증
- iron-session 기반 세션 관리
- Redis 세션 스토어

---

## API 목록

모든 라우트는 `/api/v1` 접두사를 사용합니다 (API_V1_PREFIX로 설정 가능).

### 1. 인증 API (`/api/v1/auth`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/auth/register` | POST | 사용자 등록 |
| `/auth/login` | POST | 사용자 로그인 (JWT 토큰 반환) |
| `/auth/refresh` | POST | 액세스 토큰 갱신 |
| `/auth/logout` | POST | 리프레시 토큰 무효화 |
| `/auth/me` | GET | 현재 사용자 정보 조회 |
| `/auth/api-keys` | POST, GET | API 키 관리 |
| `/auth/api-keys/{id}` | DELETE | API 키 폐기 |

**인증 방식:**
- JWT 기반 인증 (액세스 토큰 + 리프레시 토큰)
- API 키 인증 (프로그래밍 방식 액세스)
- 세션 기반 인증 (웹 인터페이스)

### 2. 쿼리/워크플로우 API (`/api/v1`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/query` | POST | 메인 멀티 에이전트 워크플로우 실행 |
| `/health` | GET | 시스템 헬스 체크 |
| `/trending` | GET | 트렌딩 쿼리 조회 |
| `/related/{query_id}` | GET | 관련 쿼리 조회 |
| `/history/{user_id}` | GET | 사용자 쿼리 히스토리 |
| `/cache/{cache_key}` | DELETE | 특정 캐시 삭제 |
| `/stats/system` | GET | 시스템 통계 |
| `/ws/{session_id}` | WebSocket | 실시간 쿼리 처리 |
| `/hyper-research/{uuid}` | GET | HyperDeepResearch 리포트 조회 |
| `/hyper-research` | GET | 리서치 리포트 목록 |

### 3. 채팅 시스템 API (`/api/v1/chat`)

#### 대화 관리

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/conversations` | POST | 새 대화 생성 |
| `/conversations/{id}` | GET | 대화 상세 조회 |
| `/conversations/{id}/full` | GET | 메시지 포함 대화 조회 |
| `/conversations/{id}` | PATCH | 대화 업데이트 |
| `/conversations/{id}` | DELETE | 대화 삭제 |
| `/conversations/{id}/archive` | POST | 대화 보관 |
| `/users/{user_id}/conversations` | GET | 사용자 대화 목록 |

#### 메시지 관리

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/conversations/{id}/messages` | POST | 메시지 전송 (AI 응답 포함) |
| `/conversations/{id}/messages/stream` | POST | 스트리밍 메시지 (SSE) |
| `/conversations/{id}/messages` | GET | 메시지 목록 조회 |
| `/messages/{id}` | GET | 특정 메시지 조회 |
| `/messages/{id}` | PATCH | 메시지 수정 |
| `/messages/{id}` | DELETE | 메시지 삭제 |
| `/messages/{id}/regenerate` | POST | AI 응답 재생성 |
| `/messages/{id}/feedback` | POST | 피드백 추가 |

#### 유사도 검색

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/conversations/{id}/messages/similarity` | POST | 유사 메시지 검색 |
| `/conversations/{id}/messages/similarity/stream` | POST | 스트리밍 유사도 검색 |
| `/conversations/{id}/messages/similarity/cross-conversation` | POST | 대화간 검색 |
| `/conversations/{id}/messages/similarity/high-confidence` | POST | 높은 신뢰도 매칭 |

#### 기타

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/ws/{conversation_id}` | WebSocket | 실시간 채팅 스트리밍 |
| `/conversations/{id}/analytics` | GET | 대화 분석 |
| `/users/{user_id}/statistics` | GET | 사용자 통계 |
| `/templates` | POST, GET | 대화 템플릿 관리 |

### 4. 멀티모달 API (`/api/v1/multimodal`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/query` | POST | 파일 업로드와 함께 쿼리 처리 |
| `/image/analyze` | POST | 이미지 분석 |
| `/supported-types` | GET | 지원되는 파일 타입 목록 |

**지원 파일 타입:**
- 이미지: jpg, jpeg, png, gif, webp, bmp
- 문서: pdf, docx, xlsx, pptx, txt, md, csv
- 오디오: mp3, wav, ogg, flac, m4a, webm

### 5. 문서 관리 API (`/api/v1/documents`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/documents` | POST | 문서 업로드 |
| `/documents/{id}` | GET | 문서 조회 |
| `/documents/{id}` | DELETE | 문서 삭제 |
| `/documents/search` | POST | 문서 검색 |

**기능:**
- 문서 업로드 및 처리
- 청킹 및 임베딩
- 지식 그래프 추출
- 전문 검색

### 6. 딥 리서치 API (`/api/v1`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/deep-research/start` | POST | 딥 리서치 시작 |
| `/deep-research/{id}/stream` | GET | 리서치 진행상황 스트리밍 (SSE) |
| `/deep-research/{id}` | GET | 리서치 리포트 조회 |
| `/conversations/{id}/deep-research` | GET | 대화의 리서치 목록 |

### 7. 분석 API (`/api/v1/analytics`)

| 엔드포인트 | 메소드 | 설명 |
|----------|--------|------|
| `/analytics/web-search` | GET | 웹 검색 분석 |
| `/analytics/query-patterns` | GET | 쿼리 패턴 분석 |
| `/analytics/agent-performance` | GET | 에이전트 성능 메트릭 |

---

## 코드 구성

### 디렉토리 구조

```
/home/user/neos/
├── neos/                          # 메인 Python 패키지
│   ├── agents/                    # AI 에이전트 구현체 (36개 파일)
│   │   ├── search_agents/         # 검색 중심 에이전트
│   │   │   ├── hyper_deep_research/  # 고급 리서치 에이전트
│   │   │   ├── deep_research.py
│   │   │   ├── knowledge_search.py
│   │   │   ├── multi_query_search.py
│   │   │   ├── realtime_info_search.py
│   │   │   ├── realtime_data_search.py
│   │   │   └── web_lookup.py
│   │   ├── analysis_agents.py     # 데이터 및 비교 분석
│   │   ├── generation_agents.py   # 콘텐츠 생성 에이전트
│   │   ├── planning_agent.py
│   │   └── base.py                # 베이스 에이전트 클래스
│   │
│   ├── api/                       # FastAPI 라우트 및 핸들러
│   │   ├── handlers/              # 요청 핸들러 (얇은 레이어)
│   │   │   ├── auth.py
│   │   │   ├── chat_handlers.py
│   │   │   ├── query_handlers.py
│   │   │   ├── multimodal_handlers.py
│   │   │   ├── deep_research_handlers.py
│   │   │   ├── document_handlers.py
│   │   │   └── analytics_handlers.py
│   │   ├── services/              # 비즈니스 로직 서비스
│   │   │   ├── auth_service.py
│   │   │   ├── chat_service.py
│   │   │   ├── query_service.py
│   │   │   ├── multimodal_service.py
│   │   │   └── document_service.py
│   │   ├── models/                # Pydantic 요청/응답 모델
│   │   └── dependencies/          # FastAPI 의존성 (인증 등)
│   │
│   ├── workflow/                  # LangGraph 워크플로우 오케스트레이션
│   │   ├── graph.py               # 메인 워크플로우 그래프 (370 라인)
│   │   ├── state.py               # 에이전트 상태 정의
│   │   ├── orchestrators/         # 도메인 오케스트레이터
│   │   │   ├── search_orchestrator.py
│   │   │   ├── analysis_orchestrator.py
│   │   │   └── generation_orchestrator.py
│   │   ├── processors/            # 결과 처리
│   │   │   ├── result_processor.py
│   │   │   ├── quality_validator.py
│   │   │   └── response_generator.py
│   │   ├── utils/                 # 워크플로우 유틸리티
│   │   ├── builder/               # 커스텀 워크플로우 빌더
│   │   └── pipelines/             # 멀티모달 파이프라인
│   │
│   ├── database/                  # 데이터베이스 레이어
│   │   ├── models.py              # SQLAlchemy 모델
│   │   ├── connection.py          # DB 연결 관리
│   │   ├── repositories/          # 데이터 액세스 레이어
│   │   └── migrations/            # SQL 마이그레이션
│   │
│   ├── services/                  # 핵심 서비스
│   │   ├── chat_llm_service.py    # 채팅용 LLM 통합
│   │   ├── rag_chat_llm_service.py
│   │   ├── message_embedding_service.py
│   │   └── similarity_search_service.py
│   │
│   ├── tools/                     # 도구 통합
│   │   ├── tools/                 # 개별 도구
│   │   │   ├── web_search.py
│   │   │   ├── database.py
│   │   │   ├── file_processing.py
│   │   │   └── git.py
│   │   ├── base/                  # 베이스 도구 클래스
│   │   ├── manager/               # 도구 관리
│   │   ├── tool_selector.py
│   │   └── mcp_integration.py     # Model Context Protocol
│   │
│   ├── utils/                     # 유틸리티
│   │   ├── cache.py               # Redis 캐싱
│   │   ├── embeddings.py          # 임베딩 관리
│   │   ├── llm_factory.py         # LLM 프로바이더 추상화
│   │   ├── llm_wrapper.py         # LLM 호출 래퍼
│   │   ├── cost_calculator.py     # 토큰 비용 추적
│   │   ├── jwt.py                 # JWT 토큰 처리
│   │   ├── security.py            # 보안 유틸리티
│   │   ├── csrf.py                # CSRF 보호
│   │   └── logger.py              # 로깅 유틸리티
│   │
│   ├── config/                    # 설정
│   │   └── settings.py            # 중앙 설정 (196 라인)
│   │
│   ├── observability/             # 모니터링 및 추적
│   ├── storage/                   # 파일 스토리지 추상화
│   ├── dataset/                   # 데이터셋 수집
│   ├── pipelines/                 # 문서 처리
│   └── main.py                    # 애플리케이션 엔트리 포인트
│
├── web/                           # Next.js 프론트엔드
│   ├── app/                       # Next.js 앱 라우터
│   │   ├── page.tsx               # 홈페이지
│   │   ├── chat/[id]/page.tsx    # 채팅 페이지
│   │   ├── login/page.tsx        # 로그인 페이지
│   │   └── api/                   # API 라우트 (BFF 패턴)
│   ├── components/                # React 컴포넌트
│   │   ├── chat/                  # 채팅 UI 컴포넌트
│   │   ├── home/                  # 홈페이지 컴포넌트
│   │   ├── auth/                  # 인증 컴포넌트
│   │   └── providers/             # Context 프로바이더
│   ├── lib/                       # 유틸리티 및 헬퍼
│   │   ├── stores/                # Zustand 스토어
│   │   ├── contexts/              # React 컨텍스트
│   │   ├── api/                   # API 클라이언트
│   │   └── utils.ts               # 헬퍼 함수
│   └── middleware.ts              # Next.js 미들웨어
│
├── db/                            # 데이터베이스 스키마 (17개 SQL 파일)
│   ├── init.sql                   # 베이스 스키마
│   ├── chat_system.sql            # 채팅 테이블
│   ├── hyper_deep_research.sql   # 리서치 테이블
│   ├── chat_similarity_search.sql
│   ├── chat_cost_tracking.sql
│   └── migrations/                # 스키마 마이그레이션
│
├── docs/                          # 문서 (29개 파일)
├── tests/                         # 테스트 파일
├── resources/                     # 정적 리소스
└── examples/                      # 사용 예제
```

### 코드 메트릭

- **총 Python 파일**: 100개 이상
- **에이전트 구현체**: 36개 파일
- **데이터베이스 스키마**: 17개 SQL 파일
- **총 코드 라인 수**: ~15,232 라인 (workflow/utils 단독)
- **문서 파일**: 29개 마크다운 파일

### 아키텍처 패턴

**레이어드 아키텍처:**
1. **Handler Layer**: API 요청/응답 처리 (얇은 레이어)
2. **Service Layer**: 비즈니스 로직
3. **Repository Layer**: 데이터 액세스
4. **Model Layer**: 데이터 모델 (SQLAlchemy, Pydantic)

**설계 원칙:**
- 관심사의 분리 (Separation of Concerns)
- 의존성 주입 (Dependency Injection)
- 단일 책임 원칙 (Single Responsibility)
- 리포지토리 패턴 (Repository Pattern)
- BFF 패턴 (Backend for Frontend)

---

## 데이터베이스 구조

### 데이터베이스 기술

- **주 데이터베이스**: PostgreSQL
- **확장 기능**:
  - `pgvector` - 벡터 유사도 검색
  - `pg_trgm` - Trigram 텍스트 검색
- **캐시**: Redis (Valkey)
- **연결**: AsyncPG (커넥션 풀링)

### 핵심 테이블

#### 1. 사용자 관리

**users** - 사용자 계정
```sql
- id (SERIAL PRIMARY KEY)
- user_id (VARCHAR, UNIQUE)
- email, username, password_hash
- is_active, is_verified, is_admin
- role (user/admin/premium)
- preferences (JSONB)
- created_at, updated_at, last_login
```

**api_keys** - API 키 관리
```sql
- API 키 관리 (스코프 지원)
- 속도 제한 (Rate limiting)
- 사용량 추적
- 만료 지원
```

**refresh_tokens** - JWT 리프레시 토큰
```sql
- JWT 리프레시 토큰 저장
- 토큰 로테이션 지원
- 디바이스 및 IP 추적
- 폐기 메커니즘
```

#### 2. 쿼리 및 검색

**query_history** - 쿼리 히스토리
```sql
- 원본 및 처리된 쿼리
- 쿼리 벡터 (1536 차원)
- 쿼리 의도 분류
- 검색 결과 (JSONB)
- 응답 품질 점수
- 실행 메트릭
- 도구 사용 추적
```

**related_queries** - 관련 쿼리
```sql
- 쿼리 관계
- 유사도 점수
- 관계 타입 (semantic/sequential/collaborative)
```

**trending_queries** - 트렌딩 쿼리
```sql
- 쿼리 텍스트 및 벡터
- 검색 횟수
- 시간 구간 (hourly/daily/weekly)
- 카테고리
```

**search_sessions** - 검색 세션
```sql
- 세션 기반 쿼리 추적
- 쿼리 시퀀스 (JSONB)
- 세션 의도
- 지속 시간 메트릭
```

#### 3. 채팅 시스템

**conversations** - 대화
```sql
- 대화 메타데이터
- 모델 설정 (model_name, temperature, max_tokens)
- 시스템 프롬프트
- 상태 추적 (active/archived/deleted)
- 고정 및 공유
- 토큰 사용량 및 비용 추적
- 태그 및 메타데이터 (JSONB)
```

**messages** - 메시지
```sql
- 메시지 콘텐츠 및 역할 (user/assistant/system/function/tool)
- 메시지 시퀀스 및 계층 (parent_message_id)
- 상태 추적 (pending/streaming/completed/failed)
- AI 메타데이터 (model, tokens, finish_reason)
- 도구 호출 및 결과 (JSONB)
- 첨부 파일 (JSONB)
- 사용자 피드백
- 품질 점수
```

**message_edits** - 메시지 수정 기록
```sql
- 수정 히스토리 추적
- 버전 번호
- 수정 이유
```

**conversation_participants** - 대화 참여자
```sql
- 멀티 유저 대화 지원
- 참여자 역할
- 참여/퇴장 추적
```

**conversation_templates** - 대화 템플릿
```sql
- 재사용 가능한 대화 템플릿
- 기본 설정
- 초기 메시지
- Public/Private 템플릿
```

#### 4. 딥 리서치

**hyper_research_reports** - 리서치 리포트
```sql
- 리포트 ID 및 메타데이터
- 리서치 주제 및 상태
- 대화 연결 (conversation_id, initial_message_id)
- 리서치 계획 및 단계 (JSONB)
- 수집된 소스 (JSONB array)
- 생성된 리포트 섹션
- 품질 메트릭
- 처리 메타데이터
```

**hyper_research_sources** - 리서치 소스
```sql
- 소스 URL 및 콘텐츠
- 품질 점수
- 처리 상태
- 추출 메타데이터
```

#### 5. 문서 관리

**documents** - 문서
```sql
- 파일 메타데이터 (filename, size, mime_type, hash)
- 스토리지 정보 (provider, bucket, key, URL)
- 문서 메타데이터 (title, author, language, page_count)
- 처리 상태
- 지식 그래프 추출 상태
- 임베딩 처리 상태
- FTS 인덱싱 상태
```

**document_chunks** - 문서 청크
```sql
- 청크된 텍스트 콘텐츠
- 청크 인덱스 및 위치
- 페이지 번호 및 오프셋
- 임베딩 (vector 1536)
- 청크 타입 및 계층
- 메타데이터 (JSONB)
```

**knowledge_graphs** - 지식 그래프
```sql
- 엔티티 정보 (type, name, description)
- 엔티티 임베딩
- 엔티티 간 관계 (JSONB)
- 속성 (JSONB)
- 문서 내 출현
- 신뢰도 및 중요도 점수
```

#### 6. 분석 및 추적

**web_search_logs** - 웹 검색 로그
```sql
- 검색 쿼리 추적
- 검색 결과
- 프로바이더 정보
- 성능 메트릭
```

**llm_costs** - LLM 비용
```sql
- 메시지별 LLM 사용량 추적
- 토큰 수 (prompt/completion/total)
- 비용 계산
- 프로바이더 및 모델 추적
- 레이턴시 측정
```

**conversation_analytics** - 대화 분석
```sql
- 대화별 메트릭
- 메시지 수 및 패턴
- 응답 시간
- 품질 점수
- 비용 집계
```

### 데이터베이스 함수 및 뷰

**저장 함수:**
- `create_hyper_research_report()` - 리서치 리포트 생성
- `get_conversation_deep_research_reports()` - 대화의 리서치 목록 조회

**뷰:**
- `conversation_with_deep_research` - 리서치 통계가 포함된 대화

### 인덱스

**벡터 인덱스** (IVFFlat):
```sql
- query_history.query_vector
- trending_queries.query_vector
- document_chunks.embedding
- knowledge_graphs.entity_embedding
```

**텍스트 검색 인덱스** (GIN):
```sql
- 쿼리 텍스트의 Trigram 인덱스
- 문서 청크의 전문 검색
```

**성능 인덱스:**
```sql
- 사용자 ID, 대화 ID
- 시간 기반 쿼리용 타임스탬프
- 필터링용 상태 필드
```

---

## 워크플로우 및 에이전트

### 워크플로우 아키텍처

**LangGraph 기반 상태 머신:**
- `StateGraph` 사용 (체크포인팅: `MemorySaver`)
- 비동기 실행 (`ainvoke`)
- 품질 검증 기반 조건부 라우팅
- 재시도 메커니즘 (최대 2회)

### 워크플로우 노드

```
1. query_classifier      → 쿼리 분류 및 분석
2. search_orchestrator   → 검색 에이전트 조정
3. analysis_orchestrator → 분석 에이전트 조정
4. generation_orchestrator → 생성 에이전트 조정
5. result_integrator     → 모든 결과 통합
6. quality_validator     → 응답 품질 검증
7. response_generator    → 최종 응답 생성
```

### 에이전트 타입

#### 검색 에이전트 (7종)

**1. KnowledgeSearchAgent** - 지식 검색
- 지식 베이스 기반 검색
- 벡터 유사도 검색
- 캐시된 결과 활용

**2. RealtimeInfoSearchAgent** - 실시간 정보 검색
- Tavily API를 통한 실시간 웹 검색
- 뉴스 및 현재 이벤트
- 소스 검증

**3. RealtimeDataSearchAgent** - 실시간 데이터 검색
- 실시간 데이터 조회
- API 통합
- 구조화된 데이터

**4. MultiQuerySearchAgent** - 다중 쿼리 검색
- 복잡한 쿼리 처리
- 다각도 분석
- 2-5개의 병렬 쿼리
- 병렬 요약
- 최종 합성

**5. DeepResearchAgent** - 딥 리서치
- 전문가 수준 리서치 (15-30분)
- 4단계 프로세스:
  1. 초기 탐색 (8-10개 쿼리)
  2. 갭 분석
  3. 검증
  4. 리포트 생성
- 30-50개 이상의 소스
- 품질 검증

**6. HyperDeepResearchAgent** - 하이퍼 딥 리서치
- 고급 리서치 (30-60분)
- 200개 이상의 소스 수집
- 8단계 체계적 프로세스
- 편향 감지
- 팩트 체킹
- 의미론적 클러스터링
- 비용 최적화
- 복잡도 평가

**7. WebLookUpAgent** - 웹 조회
- 직접 URL 콘텐츠 추출
- 정적 HTML 처리 (1-3초)
- Playwright를 이용한 동적 렌더링 (10-30초)
- 병렬 URL 처리
- LLM 기반 콘텐츠 분석

#### 분석 에이전트 (3종)

**1. DataAnalysisAgent** - 데이터 분석
- 통계 분석
- 패턴 발견
- 데이터 시각화 준비
- 트렌드 식별

**2. ComparativeAnalysisAgent** - 비교 분석
- 다중 소스 비교
- 유사점/차이점 분석
- 장단점 평가
- 랭킹 및 점수화

**3. WebContentAnalysisAgent** - 웹 콘텐츠 분석
- 웹 페이지 콘텐츠 분석
- 구조 추출
- 의미론적 이해

#### 생성 에이전트 (4종)

**1. ImageGenerationAgent** - 이미지 생성
- OpenAI DALL-E 3 통합
- 프롬프트 최적화
- 이미지 생성 및 저장

**2. ApiCallAgent** - API 호출
- 외부 API 통합:
  - 날씨 (OpenWeatherMap)
  - 환율 (ExchangeRate API)
  - 주식 시장 (Yahoo Finance / FinancialDatasets)
- 자연어 파라미터 추출
- 160개 이상의 통화 지원

**3. FileProcessingAgent** - 파일 처리
- 문서 분석
- 포맷 변환
- 콘텐츠 요약
- 메타데이터 추출

**4. TaskCreationAgent** - 작업 생성
- 자동 프로젝트 계획
- 작업 분해
- 의존성 관리
- 타임라인 생성

### 에이전트 베이스 클래스

**BaseAgent** (ABC)
- LLM 통합 (설정 가능한 프로바이더)
- CrewAI 에이전트 생성
- 작업 생성 및 실행
- 입력 검증
- 출력 포맷팅

**SearchAgent** (BaseAgent 확장)
- 검색 특화 메소드
- 결과 캐싱
- 소스 검증

**AnalysisAgent** (BaseAgent 확장)
- 데이터 분석 메소드
- 통계 처리
- 인사이트 생성

**GenerationAgent** (BaseAgent 확장)
- 콘텐츠 생성 메소드
- 템플릿 처리
- 품질 검증

### 오케스트레이터

**SearchOrchestrator** - 검색 조정
- 병렬 검색 실행
- MCP 도구 통합
- 결과 중복 제거
- 캐시 관리 (30분 TTL)
- 복잡도 기반 에이전트 선택

**AnalysisOrchestrator** - 분석 조정
- 순차적 분석 실행
- 데이터 전처리
- 결과 집계

**GenerationOrchestrator** - 생성 조정
- 생성 작업 관리
- 리소스 할당
- 품질 관리

### 워크플로우 기능

**캐싱 전략:**
```
- 워크플로우 응답: 24시간
- 검색 결과: 30분
- 임베딩: 24시간
- 세션: 1시간
```

**품질 검증:**
```
- 최소 품질 점수: 0.4
- 낮은 품질 시 자동 재시도
- 최대 재시도 횟수: 2회
- 피드백 기반 개선
```

**성능 추적:**
```
- 실행 시간 모니터링
- 토큰 사용량 추적
- API 호출 카운팅
- 비용 계산
```

**다국어 지원:**
```
- 자동 언어 감지
- 감지된 언어로 응답
- 한국어 및 영어 주 지원
```

### 멀티모달 파이프라인

**비전 처리:**
- GPT-4o Vision 통합
- Claude Vision 통합
- 가용성 기반 자동 선택
- 컨텍스트와 함께 이미지 분석

**문서 처리:**
- PDF 파싱 (PyPDF2)
- Word 문서 (python-docx)
- Excel 파일 (openpyxl)
- PowerPoint (python-pptx)
- 마크다운 및 텍스트 파일

**오디오 처리:**
- 다중 포맷 지원
- 트랜스크립션 기능

### 도구 통합

**MCP (Model Context Protocol):**
- 동적 도구 발견
- 네이티브 도구로 폴백
- 성능 모니터링
- 품질 임계값: 0.7

**도구 선택 전략:**
- `always` - 항상 MCP 도구 사용
- `mcp_available` - MCP 가용 시 사용
- `mcp_fallback` - MCP 시도 후 네이티브로 폴백
- `preference_based` - 사용자 선호도 기반

---

## 주요 기능

### 1. 인증 및 보안

**인증 방식:**
- JWT 기반 인증 (액세스 토큰 + 리프레시 토큰)
- API 키 인증
- 세션 기반 인증 (iron-session)

**보안 기능:**
- CSRF 보호
- 비밀번호 해싱 (bcrypt)
- 토큰 로테이션
- Rate limiting
- CORS 설정

### 2. 실시간 스트리밍

**지원 프로토콜:**
- WebSocket (양방향 통신)
- Server-Sent Events (SSE, 단방향 스트리밍)

**스트리밍 지원:**
- AI 응답 스트리밍
- 딥 리서치 진행상황 스트리밍
- 유사도 검색 스트리밍

### 3. 벡터 검색 및 유사도

**기능:**
- pgvector 기반 고속 벡터 검색
- 코사인 유사도 계산
- 하이브리드 검색 (벡터 + 전문 검색)
- 크로스 대화 검색
- 높은 신뢰도 매칭

### 4. 비용 추적

**추적 항목:**
- LLM API 호출당 토큰 사용량
- 프롬프트 토큰 vs 완료 토큰
- 프로바이더별 비용 계산
- 대화별 비용 집계
- 사용자별 비용 통계

### 5. 캐싱 전략

**Redis 캐싱:**
- 워크플로우 응답 캐싱
- 검색 결과 캐싱
- 임베딩 캐싱
- 세션 캐싱
- TTL 기반 자동 만료

### 6. 관찰 가능성 (Observability)

**모니터링:**
- 요청/응답 로깅
- 성능 메트릭
- 에러 추적
- LLM 호출 추적

**분석:**
- 웹 검색 분석
- 쿼리 패턴 분석
- 에이전트 성능 메트릭

### 7. 확장성

**수평 확장:**
- Stateless 서버 설계
- Redis 기반 세션 공유
- 데이터베이스 커넥션 풀링

**수직 확장:**
- 비동기 처리 (AsyncIO)
- 병렬 에이전트 실행
- 효율적인 리소스 관리

---

## 요약

NEOS는 다음과 같은 특징을 가진 정교한 멀티 에이전트 AI 시스템입니다:

- **2개의 서버 컴포넌트**: FastAPI 백엔드 (포트 8518) + Next.js 프론트엔드 (포트 3000)
- **40개 이상의 API 엔드포인트**: 8개 주요 카테고리
- **14개의 전문 AI 에이전트**: 검색, 분석, 생성
- **복잡한 LangGraph 워크플로우**: 품질 검증 및 재시도 로직
- **포괄적인 PostgreSQL 스키마**: 벡터 검색을 포함한 20개 이상의 테이블
- **고급 기능**: 실시간 스트리밍, 멀티모달 처리, 딥 리서치, 유사도 검색
- **프로덕션 준비**: 인증, CSRF 보호, Rate limiting, 비용 추적, 관찰 가능성

이 아키텍처는 깔끔한 관심사의 분리를 따르며, 얇은 핸들러, 서비스 레이어 비즈니스 로직, 데이터 액세스를 위한 리포지토리 패턴을 사용합니다. 시스템은 모듈화되어 있고, 확장 가능하며, 성능과 확장성 모두에 최적화되어 있습니다.
