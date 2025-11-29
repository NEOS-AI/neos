# NEOS 아키텍처 문서 (NEOS Architecture Documentation)

## 목차 (Table of Contents)

1. [시스템 개요](#시스템-개요-system-overview)
2. [기술 스택](#기술-스택-technology-stack)
3. [전체 아키텍처](#전체-아키텍처-overall-architecture)
4. [워크플로우 시스템](#워크플로우-시스템-workflow-system)
5. [에이전트 시스템](#에이전트-시스템-agent-system)
6. [데이터베이스 스키마](#데이터베이스-스키마-database-schema)
7. [API 구조](#api-구조-api-structure)
8. [핵심 설정](#핵심-설정-configuration)

---

## 시스템 개요 (System Overview)

**NEOS (Network of Expert Operating System)**는 다중 에이전트 기반의 지능형 AI 시스템으로, 복잡한 질의에 대해 전문화된 에이전트들이 협업하여 고품질의 답변을 생성합니다.

### 핵심 특징

- **Multi-Agent Collaboration**: 14개의 전문화된 에이전트가 협업
- **Graph-Based Workflow**: LangGraph 기반의 7단계 처리 파이프라인
- **Distributed State Management**: PostgreSQL 기반 체크포인터로 분산 환경 지원
- **Real-time Streaming**: WebSocket 및 SSE를 통한 실시간 진행 상황 전달
- **Vector Search**: pgvector를 활용한 의미론적 검색
- **Quality Assurance**: 자동 품질 검증 및 재생성 메커니즘

### 코드 규모

| 구분 | 규모 |
|------|------|
| Backend (Python) | ~57,878 LOC |
| Frontend (TypeScript) | 81 files |
| Database Models | 15+ SQLAlchemy models |
| API Endpoints | 50+ endpoints (10 routers) |
| Agents | 14 specialized agents |

---

## 기술 스택 (Technology Stack)

### Backend

```
Framework:
  - FastAPI 0.116.1 (Web framework)
  - LangGraph 0.6.6 (Workflow orchestration)
  - CrewAI 0.175.0 (Agent framework)

Database:
  - PostgreSQL (with asyncpg)
  - pgvector (1536-dim embeddings)
  - Redis 6.4.0 (caching)

AI/ML:
  - OpenAI GPT-4 (LLM)
  - Anthropic Claude Opus (LLM)
  - text-embedding-3-small (embeddings)
  - DALL-E 3 (image generation)

Search:
  - Tavily API (web search)
  - Playwright (web scraping)
```

### Frontend

```
Framework:
  - Next.js 14.2.33 (App Router)
  - React 18.3.1
  - TypeScript 5.9.3

State Management:
  - Zustand (global state)

Styling:
  - Tailwind CSS
  - Lucide React (icons)
  - Custom theme (#050d4d dark blue)
```

### Infrastructure

```
Database:
  - PostgreSQL (primary data store)
  - Redis (caching, session)

Connection Pools:
  - Database: 40 connections
  - Redis: 50 connections

Concurrency:
  - Max concurrent workflows: 100
```

---

## 전체 아키텍처 (Overall Architecture)

### 시스템 구성도

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Next.js App │  │   Zustand    │  │  API Client  │      │
│  │   (UI/UX)    │──│    Store     │──│  (HTTP/WS)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP/WebSocket/SSE
┌────────────────────────────┴────────────────────────────────┐
│                        API Layer (FastAPI)                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Routers (10):                                        │  │
│  │  Query | Chat | Deep Research | RAG | Similarity     │  │
│  │  Document | Multimodal | Analytics | Auth | Search   │  │
│  └──────────────────────┬───────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│                     Service Layer                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │QueryService  │  │ChatService   │  │ChatLLMService│       │
│  └──────┬───────┘  └──────────────┘  └──────────────┘       │
│         │                                                     │
│  ┌──────┴────────────────────────────────────────────────┐  │
│  │           MultiAgentWorkflow (LangGraph)              │  │
│  │                                                        │  │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐       │  │
│  │  │ Classify │ -> │  Search  │ -> │ Analysis │       │  │
│  │  │          │    │Orchestr. │    │Orchestr. │       │  │
│  │  └──────────┘    └──────────┘    └──────────┘       │  │
│  │                                                        │  │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐       │  │
│  │  │Generate  │ -> │Integrate │ -> │ Validate │       │  │
│  │  │Orchestr. │    │  Result  │    │ Quality  │       │  │
│  │  └──────────┘    └──────────┘    └────┬─────┘       │  │
│  │                                        │              │  │
│  │  ┌──────────────────────────────┐     │              │  │
│  │  │  Response Generator (END)    │ <───┘              │  │
│  │  └──────────────────────────────┘                    │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│                    Agent Layer (14 Agents)                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Search Agents (7):                                    │   │
│  │  Knowledge | Realtime Info | Realtime Data           │   │
│  │  Multi-Query | WebLookUp | Deep | HyperDeep          │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Analysis Agents (3):                                  │   │
│  │  Data Analysis | Comparative | Web Content           │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Generation Agents (4):                                │   │
│  │  Image | API Call | File Processing | Task Creation  │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│                      Data Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  PostgreSQL  │  │    Redis     │  │   pgvector   │       │
│  │  (Primary)   │  │  (Cache)     │  │  (Embeddings)│       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

### 디렉토리 구조

```
neos/
├── neos/                          # 메인 패키지
│   ├── agents/                    # 14개 에이전트 구현
│   │   ├── search_agents/         # 검색 에이전트 (7개)
│   │   ├── analysis_agents.py     # 분석 에이전트 (3개)
│   │   ├── generation_agents.py   # 생성 에이전트 (4개)
│   │   ├── planning_agent.py      # 쿼리 계획 에이전트
│   │   ├── autonomous_base.py     # 분산 환경용 에이전트
│   │   └── base.py                # 베이스 클래스
│   │
│   ├── workflow/                  # 워크플로우 오케스트레이션
│   │   ├── graph.py               # 메인 워크플로우 그래프
│   │   ├── distributed_graph.py   # 분산 버전
│   │   ├── state.py               # 상태 정의
│   │   ├── orchestrators/         # 에이전트 오케스트레이터
│   │   ├── processors/            # 결과 처리기
│   │   ├── checkpointer.py        # PostgreSQL 체크포인터
│   │   └── builder/               # 커스텀 워크플로우 빌더
│   │
│   ├── api/                       # FastAPI 애플리케이션
│   │   ├── handlers/              # 10개 라우터 그룹 (50+ endpoints)
│   │   ├── services/              # 비즈니스 로직 서비스
│   │   ├── models/                # Pydantic 모델
│   │   └── dependencies/          # 의존성 주입
│   │
│   ├── database/                  # 데이터 레이어
│   │   ├── models.py              # 15+ SQLAlchemy 모델
│   │   ├── repositories/          # 데이터 액세스 레이어
│   │   ├── connection.py          # DB 커넥션 풀
│   │   └── migrations/            # SQL 마이그레이션
│   │
│   ├── services/                  # 지원 서비스
│   │   ├── chat_llm_service.py    # 채팅 LLM 서비스
│   │   ├── similarity_search_service.py
│   │   └── context_optimizer.py   # 컨텍스트 최적화
│   │
│   ├── tools/                     # 도구 관리
│   │   ├── tool_selector.py       # MCP 도구 선택
│   │   ├── mcp_integration.py     # Model Context Protocol
│   │   └── tools/                 # 개별 도구 구현
│   │
│   ├── utils/                     # 유틸리티
│   │   ├── llm_factory.py         # LLM 생성
│   │   ├── embeddings.py          # 임베딩 관리
│   │   ├── cache.py               # 캐싱
│   │   └── circuit_breaker.py     # 복원력 패턴
│   │
│   ├── config/                    # 설정
│   │   └── settings.py            # 환경 기반 설정
│   │
│   ├── cli.py                     # CLI 도구 (94KB)
│   └── main.py                    # FastAPI 엔트리 포인트
│
├── web/                           # Next.js 프론트엔드
│   ├── app/                       # App Router
│   ├── components/                # React 컴포넌트
│   ├── lib/                       # 유틸리티 & 스토어
│   └── public/                    # 정적 자산
│
├── db/                            # 데이터베이스 설정
│   ├── migrations/                # SQL 마이그레이션
│   └── docker-compose.yml         # PostgreSQL + Redis
│
└── pyproject.toml                 # Python 의존성
```

---

## 워크플로우 시스템 (Workflow System)

### MultiAgentWorkflow 구조

NEOS의 핵심은 **LangGraph** 기반의 7단계 워크플로우입니다. 각 노드는 특정 역할을 수행하며, 조건부 엣지를 통해 동적으로 흐름이 결정됩니다.

```
┌─────────────────────────────────────────────────────────────┐
│                    MultiAgentWorkflow                        │
│                     (LangGraph-based)                        │
└─────────────────────────────────────────────────────────────┘

START
  │
  ├──> [1] Query Classifier
  │         └─ 쿼리 의도 분석 (검색, 분석, 생성)
  │         └─ 필요한 에이전트 타입 결정
  │
  ├──> [2] Search Orchestrator
  │         └─ 검색 에이전트 선택 및 실행 (7개 중)
  │         └─ 병렬/순차 검색 수행
  │         └─ 결과 정규화 및 집계
  │
  ├──> [3] Analysis Orchestrator
  │         └─ 분석 에이전트 선택 및 실행 (3개 중)
  │         └─ 검색 결과 분석
  │         └─ 패턴 발견 및 통찰 생성
  │
  ├──> [4] Generation Orchestrator
  │         └─ 생성 에이전트 선택 및 실행 (4개 중)
  │         └─ 이미지, API 호출, 파일 처리 등
  │
  ├──> [5] Result Integrator
  │         └─ 모든 에이전트 결과 통합
  │         └─ 중복 제거 및 우선순위 결정
  │         └─ 응답 구조 생성
  │
  ├──> [6] Quality Validator
  │         └─ 품질 점수 계산 (completeness, relevance, coherence)
  │         └─ 임계값 검증 (MIN_QUALITY_SCORE = 0.4)
  │         │
  │         ├──> [품질 OK] ──> Response Generator
  │         │
  │         └──> [품질 낮음] ──> 재생성 (max 2 retries)
  │                               └──> Analysis Orchestrator로 복귀
  │
  └──> [7] Response Generator
            └─ 최종 응답 포맷팅
            └─ 메타데이터 추가
            └─ 캐시 저장 (2시간 TTL)
            │
          END
```

### 상태 관리 (State Management)

워크플로우는 `AgentState` TypedDict를 통해 상태를 관리합니다:

```python
class AgentState(TypedDict):
    # 기본 정보
    user_id: str
    session_id: str
    query: str
    query_embedding: List[float]  # 1536-dim

    # 분류 결과
    classification: Dict[str, Any]  # 쿼리 의도 분류
    required_agents: List[str]       # 필요한 에이전트 목록

    # 검색 결과
    search_results: List[Dict[str, Any]]
    web_sources: List[str]

    # 분석 결과
    analysis_results: Dict[str, Any]
    insights: List[str]

    # 생성 결과
    generation_results: Dict[str, Any]
    generated_assets: List[Dict[str, Any]]

    # 통합 결과
    integrated_result: str
    final_response: str

    # 품질 검증
    quality_score: float
    quality_feedback: str
    retry_count: int  # 재생성 횟수

    # 메타데이터
    execution_time: float
    tokens_used: int
    cost: float
    message_history: List[Dict[str, str]]

    # 캐싱
    cache_key: str
    cached_response: Optional[str]
```

### 체크포인터 (Checkpointer)

분산 환경을 지원하기 위해 PostgreSQL 기반 체크포인터를 사용합니다:

- **용도**: 워크플로우 중간 상태 저장 및 복구
- **저장소**: PostgreSQL (checkpoints 테이블)
- **활용**: 장애 복구, 디버깅, 상태 추적

### 캐싱 전략

```
Level 1: Workflow Response Cache
  - TTL: 2시간 (7200초)
  - Key: query_hash + user_id
  - Storage: Redis

Level 2: Embedding Cache
  - TTL: 24시간
  - Key: text_hash
  - Storage: Redis

Level 3: Search Result Cache
  - TTL: 1시간
  - Key: query_hash + search_engine
  - Storage: Redis
```

---

## 에이전트 시스템 (Agent System)

NEOS는 **14개의 전문화된 에이전트**로 구성되어 있으며, 각 에이전트는 특정 도메인에 최적화되어 있습니다.

### 에이전트 계층 구조

```
BaseAgent (추상 클래스)
  ├── SearchAgent (검색 전문)
  │   ├── KnowledgeSearchAgent
  │   ├── RealtimeInfoSearchAgent
  │   ├── RealtimeDataSearchAgent
  │   ├── MultiQuerySearchAgent
  │   ├── WebLookUpAgent
  │   ├── DeepResearchAgent
  │   └── HyperDeepResearchAgent
  │
  ├── AnalysisAgent (분석 전문)
  │   ├── DataAnalysisAgent
  │   ├── ComparativeAnalysisAgent
  │   └── WebContentAnalysisAgent
  │
  └── GenerationAgent (생성 전문)
      ├── ImageGenerationAgent
      ├── ApiCallAgent
      ├── FileProcessingAgent
      └── TaskCreationAgent
```

### 1. 검색 에이전트 (Search Agents) - 7개

#### 1.1 KnowledgeSearchAgent
- **역할**: 내부 지식 베이스 검색
- **기술**: pgvector 기반 의미론적 검색
- **특징**:
  - 1536차원 임베딩 벡터 사용
  - 코사인 유사도 기반 순위 결정
  - Document, DocumentChunk 테이블 활용
  - 메타데이터 필터링 지원

#### 1.2 RealtimeInfoSearchAgent
- **역할**: 실시간 웹 검색
- **API**: Tavily Search API
- **특징**:
  - 최신 정보 검색 (뉴스, 트렌드 등)
  - 소스 신뢰도 평가
  - 자동 요약 생성
  - Rate limit 관리

#### 1.3 RealtimeDataSearchAgent
- **역할**: 실시간 데이터 조회
- **API**: OpenWeather, ExchangeRate, Stock APIs
- **데이터 타입**:
  - 날씨 정보
  - 환율
  - 주식 시세
  - 암호화폐 가격

#### 1.4 MultiQuerySearchAgent
- **역할**: 다각도 검색 및 분석
- **특징**:
  - 하나의 쿼리를 10+ 하위 쿼리로 분해
  - 병렬 검색 수행
  - 결과 통합 및 중복 제거
  - Dynamic N-task execution (동적 작업 수 결정)

#### 1.5 WebLookUpAgent
- **역할**: 특정 URL 콘텐츠 추출
- **기술**: Playwright (JavaScript 렌더링 지원)
- **특징**:
  - SPA(Single Page Application) 지원
  - 동적 콘텐츠 로딩 대기
  - HTML to Markdown 변환
  - 이미지/링크 추출

#### 1.6 DeepResearchAgent
- **역할**: 심층 연구 (4단계 프로세스)
- **처리 시간**: 15-30분
- **특징**:
  - Phase 1: 연구 계획 수립
  - Phase 2: 광범위한 검색 (30-50+ 소스)
  - Phase 3: 분석 및 통합
  - Phase 4: 최종 보고서 생성
  - Real-time SSE 스트리밍 지원
  - Dynamic N-phase execution

#### 1.7 HyperDeepResearchAgent
- **역할**: 초심층 연구 (8단계 프로세스)
- **처리 시간**: 30-60분
- **특징**:
  - 200+ 소스 분석
  - 다중 관점 연구
  - 교차 검증
  - 상세한 인용 및 참고문헌
  - 중간 결과 스트리밍

### 2. 분석 에이전트 (Analysis Agents) - 3개

#### 2.1 DataAnalysisAgent
- **역할**: 데이터 통계 분석
- **기능**:
  - 패턴 발견
  - 이상치 탐지
  - 트렌드 분석
  - 상관관계 계산

#### 2.2 ComparativeAnalysisAgent
- **역할**: 다중 소스 비교 분석
- **기능**:
  - 정보 일치성 검증
  - 차이점 강조
  - 편향성 탐지
  - 신뢰도 평가

#### 2.3 WebContentAnalysisAgent
- **역할**: 웹 페이지 콘텐츠 분석
- **기능**:
  - 주제 추출
  - 감정 분석
  - 핵심 정보 추출
  - 구조화된 데이터 변환

### 3. 생성 에이전트 (Generation Agents) - 4개

#### 3.1 ImageGenerationAgent
- **역할**: 이미지 생성
- **API**: DALL-E 3
- **특징**:
  - 프롬프트 최적화
  - 다양한 스타일 지원
  - 고해상도 출력 (1024x1024, 1792x1024 등)

#### 3.2 ApiCallAgent
- **역할**: 외부 API 호출 및 데이터 통합
- **지원 API**:
  - Weather (OpenWeather)
  - Currency (ExchangeRate)
  - Stocks (다양한 제공자)

#### 3.3 FileProcessingAgent
- **역할**: 파일 처리 및 분석
- **지원 형식**:
  - 문서: PDF, DOCX, TXT, MD
  - 데이터: CSV, JSON, XML
- **기능**:
  - 텍스트 추출
  - 메타데이터 파싱
  - 요약 생성
  - 청킹 (문서 분할)

#### 3.4 TaskCreationAgent
- **역할**: 자동 프로젝트 계획 생성
- **기능**:
  - 작업 분해
  - 의존성 분석
  - 우선순위 결정
  - 타임라인 제안

### 에이전트 실행 흐름

```
[Orchestrator]
      │
      ├──> Agent Selection
      │     └─ 쿼리 의도 기반 에이전트 선택
      │
      ├──> Parallel Execution
      │     └─ 독립적인 에이전트는 병렬 실행
      │     └─ 최대 동시 실행: 5개
      │
      ├──> Sequential Dependencies
      │     └─ 의존성 있는 에이전트는 순차 실행
      │     └─ 이전 에이전트 결과를 입력으로 사용
      │
      ├──> Timeout Management
      │     └─ 에이전트별 타임아웃: 300초 (5분)
      │     └─ 전체 워크플로우 타임아웃: 30분
      │
      └──> Result Aggregation
            └─ 모든 에이전트 결과 수집 및 정규화
```

---

## 데이터베이스 스키마 (Database Schema)

### 주요 테이블 (15+ Models)

#### 1. 사용자 및 인증

```sql
-- User (사용자 관리)
CREATE TABLE users (
    user_id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100),
    password_hash VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    preferences JSONB,
    api_keys JSONB,
    created_at TIMESTAMP,
    last_login TIMESTAMP
);

-- APIKey (API 키 관리)
CREATE TABLE api_keys (
    key_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100),
    scopes JSONB,
    rate_limit INTEGER,
    usage_stats JSONB,
    expires_at TIMESTAMP,
    created_at TIMESTAMP
);
```

#### 2. 대화 및 메시지

```sql
-- Conversation (대화 세션)
CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    session_id VARCHAR(255),
    title VARCHAR(500),
    mode VARCHAR(50),  -- standard, rag, similarity, deep_research
    status VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Message (채팅 메시지)
CREATE TABLE messages (
    message_id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(conversation_id),
    role VARCHAR(50),  -- user, assistant, system
    content TEXT,
    embedding VECTOR(1536),  -- pgvector
    tokens_used INTEGER,
    cost DECIMAL(10, 6),
    quality_score FLOAT,
    metadata JSONB,
    created_at TIMESTAMP
);

CREATE INDEX idx_message_embedding ON messages
USING ivfflat (embedding vector_cosine_ops);
```

#### 3. 쿼리 및 검색

```sql
-- QueryHistory (쿼리 추적)
CREATE TABLE query_history (
    query_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    session_id VARCHAR(255),
    query_text TEXT,
    query_embedding VECTOR(1536),
    intent VARCHAR(100),
    classification JSONB,
    quality_score FLOAT,
    execution_time FLOAT,
    tokens_used INTEGER,
    cost DECIMAL(10, 6),
    created_at TIMESTAMP
);

-- SearchSession (검색 세션)
CREATE TABLE search_sessions (
    session_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    session_intent VARCHAR(255),
    query_sequence JSONB,
    total_queries INTEGER,
    duration FLOAT,
    created_at TIMESTAMP
);

-- WebSearchQuery (웹 검색 로그)
CREATE TABLE web_search_queries (
    query_id UUID PRIMARY KEY,
    query_text TEXT,
    query_hash VARCHAR(255),
    search_engine VARCHAR(50),
    results_count INTEGER,
    execution_time FLOAT,
    cached BOOLEAN,
    created_at TIMESTAMP
);

CREATE INDEX idx_query_hash ON web_search_queries(query_hash);
```

#### 4. 문서 관리

```sql
-- Document (파일 관리)
CREATE TABLE documents (
    document_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    filename VARCHAR(500),
    storage_key VARCHAR(500),
    file_size BIGINT,
    mime_type VARCHAR(100),
    processing_status VARCHAR(50),
    embedding_status VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP,
    processed_at TIMESTAMP
);

-- DocumentChunk (문서 청크)
CREATE TABLE document_chunks (
    chunk_id UUID PRIMARY KEY,
    document_id UUID REFERENCES documents(document_id),
    chunk_index INTEGER,
    chunk_text TEXT,
    embedding VECTOR(1536),
    page_number INTEGER,
    heading_hierarchy JSONB,
    metadata JSONB,
    created_at TIMESTAMP
);

CREATE INDEX idx_chunk_embedding ON document_chunks
USING ivfflat (embedding vector_cosine_ops);

-- KnowledgeGraph (지식 그래프)
CREATE TABLE knowledge_graphs (
    entity_id UUID PRIMARY KEY,
    document_id UUID REFERENCES documents(document_id),
    entity_type VARCHAR(100),
    entity_name VARCHAR(500),
    relations JSONB,
    occurrence_locations JSONB,
    confidence FLOAT,
    created_at TIMESTAMP
);
```

#### 5. 심층 연구

```sql
-- HyperResearchReport (심층 연구 보고서)
CREATE TABLE hyper_research_reports (
    report_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id),
    query TEXT,
    status VARCHAR(50),  -- planning, researching, analyzing, completed, failed
    research_plan JSONB,
    sources JSONB,
    report_content TEXT,
    metadata JSONB,
    execution_time FLOAT,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

#### 6. 기타

```sql
-- SearchEngine (검색 엔진 설정)
CREATE TABLE search_engines (
    engine_id UUID PRIMARY KEY,
    engine_name VARCHAR(100),
    api_endpoint VARCHAR(500),
    capabilities JSONB,
    rate_limits JSONB,
    enabled BOOLEAN,
    created_at TIMESTAMP
);
```

### 인덱싱 전략

```sql
-- 벡터 검색 인덱스 (IVFFlat)
CREATE INDEX idx_message_embedding ON messages
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX idx_chunk_embedding ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- B-tree 인덱스
CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_conversation_user ON conversations(user_id);
CREATE INDEX idx_message_conversation ON messages(conversation_id);
CREATE INDEX idx_query_user ON query_history(user_id);
CREATE INDEX idx_document_user ON documents(user_id);

-- JSONB 인덱스 (GIN)
CREATE INDEX idx_message_metadata ON messages USING gin(metadata);
CREATE INDEX idx_query_classification ON query_history USING gin(classification);

-- Full-text 검색 인덱스
CREATE INDEX idx_chunk_fulltext ON document_chunks
USING gin(to_tsvector('english', chunk_text));
```

---

## API 구조 (API Structure)

NEOS는 **10개의 라우터 그룹**으로 구성된 50+ 엔드포인트를 제공합니다.

### 라우터 개요

| Router | 경로 | 엔드포인트 수 | 주요 기능 |
|--------|------|---------------|-----------|
| Query | `/api/v1` | 6 | 쿼리 처리, 관련 쿼리, 트렌딩 |
| Chat | `/api/v1` | 8 | 대화 관리, 메시지 전송/스트리밍 |
| Deep Research | `/api/v1` | 4 | 심층 연구 시작/진행/결과 |
| RAG Chat | `/api/v1/rag` | 5 | RAG 기반 대화 |
| Similarity Chat | `/api/v1/similarity` | 4 | 유사 메시지 검색 및 대화 |
| Document | `/api/v1/documents` | 7 | 파일 업로드, 처리, 관리 |
| Multimodal | `/api/v1/multimodal` | 6 | 이미지, 오디오, 비디오 처리 |
| Analytics | `/api/v1/analytics` | 5 | 사용 통계, 웹 검색 분석 |
| Auth | `/api/v1/auth` | 6 | 인증, JWT, API 키 관리 |
| Search Analytics | `/api/v1/search-analytics` | 4 | 검색 쿼리 로깅, 트렌딩 |

### 주요 엔드포인트 상세

#### 1. Query Router

```python
# 메인 쿼리 처리 (MultiAgentWorkflow 실행)
POST /api/v1/query
Request:
  {
    "query": "string",
    "user_id": "uuid",
    "session_id": "string (optional)",
    "context": "object (optional)"
  }
Response:
  {
    "query_id": "uuid",
    "result": "string",
    "sources": ["array"],
    "quality_score": "float",
    "execution_time": "float",
    "tokens_used": "int",
    "cost": "float"
  }

# WebSocket (실시간 업데이트)
WS /api/v1/ws/{session_id}
Events:
  - query_started
  - agent_started
  - agent_completed
  - result_ready
  - error

# 건강 상태 확인
GET /api/v1/health
Response:
  {
    "status": "healthy",
    "version": "0.11.0",
    "database": "connected",
    "redis": "connected"
  }

# 트렌딩 쿼리
GET /api/v1/trending
Response:
  [
    {
      "query": "string",
      "count": "int",
      "last_queried": "timestamp"
    }
  ]

# 관련 쿼리
GET /api/v1/related/{query_id}
Response:
  [
    {
      "query_id": "uuid",
      "query": "string",
      "similarity": "float"
    }
  ]
```

#### 2. Chat Router

```python
# 대화 생성
POST /api/v1/conversations
Request:
  {
    "user_id": "uuid",
    "title": "string (optional)",
    "mode": "standard|rag|similarity|deep_research"
  }
Response:
  {
    "conversation_id": "uuid",
    "session_id": "string",
    "mode": "string",
    "created_at": "timestamp"
  }

# 메시지 전송
POST /api/v1/conversations/{conversation_id}/messages
Request:
  {
    "role": "user",
    "content": "string"
  }
Response:
  {
    "message_id": "uuid",
    "role": "assistant",
    "content": "string",
    "tokens_used": "int",
    "cost": "float"
  }

# 스트리밍 응답
POST /api/v1/conversations/{conversation_id}/stream
Request: (same as messages)
Response: Server-Sent Events
  data: {"type": "token", "content": "..."}
  data: {"type": "done", "total_tokens": 150}

# 메시지 재생성
POST /api/v1/messages/{message_id}/regenerate

# 대화 조회
GET /api/v1/conversations/{conversation_id}

# 대화 목록
GET /api/v1/conversations?user_id={user_id}&limit=20&offset=0

# 대화 템플릿
POST /api/v1/templates
Request:
  {
    "name": "string",
    "system_prompt": "string",
    "initial_messages": ["array"]
  }
```

#### 3. Deep Research Router

```python
# 심층 연구 시작
POST /api/v1/deep-research/start
Request:
  {
    "query": "string",
    "user_id": "uuid",
    "research_type": "deep|hyper",
    "max_sources": "int (optional)"
  }
Response:
  {
    "report_id": "uuid",
    "status": "planning",
    "estimated_time": "float"
  }

# 진행 상황 스트리밍 (SSE)
GET /api/v1/deep-research/{report_id}/stream
Response: Server-Sent Events
  data: {"phase": "planning", "progress": 10, "message": "..."}
  data: {"phase": "searching", "progress": 30, "sources_found": 15}
  data: {"phase": "analyzing", "progress": 60, "insights": [...]}
  data: {"phase": "completed", "progress": 100, "report_url": "..."}

# 보고서 조회
GET /api/v1/deep-research/{report_id}
Response:
  {
    "report_id": "uuid",
    "query": "string",
    "status": "completed",
    "report_content": "markdown",
    "sources": ["array"],
    "metadata": "object"
  }

# 하이퍼 연구 목록
GET /api/v1/hyper-research?user_id={user_id}&limit=10
```

#### 4. Document Router

```python
# 파일 업로드
POST /api/v1/documents/upload
Request: multipart/form-data
  - file: binary
  - user_id: uuid
Response:
  {
    "document_id": "uuid",
    "filename": "string",
    "processing_status": "queued"
  }

# 문서 처리 상태
GET /api/v1/documents/{document_id}/status

# 문서 검색 (의미론적 검색)
POST /api/v1/documents/search
Request:
  {
    "query": "string",
    "user_id": "uuid",
    "top_k": "int (default: 5)"
  }
Response:
  [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "chunk_text": "string",
      "similarity": "float",
      "page_number": "int"
    }
  ]

# 문서 목록
GET /api/v1/documents?user_id={user_id}

# 문서 삭제
DELETE /api/v1/documents/{document_id}
```

#### 5. Auth Router

```python
# 회원가입
POST /api/v1/auth/register
Request:
  {
    "email": "string",
    "password": "string",
    "username": "string (optional)"
  }
Response:
  {
    "user_id": "uuid",
    "email": "string",
    "access_token": "jwt"
  }

# 로그인
POST /api/v1/auth/login
Request:
  {
    "email": "string",
    "password": "string"
  }
Response:
  {
    "access_token": "jwt",
    "refresh_token": "jwt",
    "user": "object"
  }

# API 키 생성
POST /api/v1/auth/api-keys
Request:
  {
    "name": "string",
    "scopes": ["read", "write"],
    "rate_limit": "int (optional)"
  }
Response:
  {
    "key_id": "uuid",
    "api_key": "string (only shown once)",
    "scopes": ["array"]
  }

# API 키 목록
GET /api/v1/auth/api-keys

# API 키 폐기
DELETE /api/v1/auth/api-keys/{key_id}
```

### 요청/응답 모델 (Pydantic)

```python
# 공통 Enums
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ChatMode(str, Enum):
    STANDARD = "standard"
    RAG = "rag"
    SIMILARITY = "similarity"
    DEEP_RESEARCH = "deep_research"

class ResearchStatus(str, Enum):
    PLANNING = "planning"
    RESEARCHING = "researching"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"

# 주요 요청/응답 모델 (30+ models)
QueryRequest
QueryResponse
ConversationCreate
ConversationResponse
MessageCreate
MessageResponse
DocumentUpload
DocumentSearchRequest
DeepResearchRequest
DeepResearchResponse
... (계속)
```

---

## 핵심 설정 (Configuration)

### 환경 변수 (settings.py)

```python
# LLM 설정
LLM_MODEL = "gpt-4-turbo-preview"
LLM_PROVIDER = "anthropic"  # or "openai"
ANTHROPIC_API_KEY = "sk-ant-..."
OPENAI_API_KEY = "sk-..."

# 임베딩
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

# 데이터베이스
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/neos"
DATABASE_POOL_SIZE = 40
DATABASE_MAX_OVERFLOW = 10

# Redis
REDIS_URL = "redis://localhost:6379/0"
REDIS_POOL_SIZE = 50

# 검색 API
TAVILY_API_KEY = "tvly-..."
OPENWEATHER_API_KEY = "..."
EXCHANGERATE_API_KEY = "..."

# 성능
MAX_CONCURRENT_WORKFLOWS = 100
AGENT_TIMEOUT = 300  # 5분
WORKFLOW_TIMEOUT = 1800  # 30분

# 캐싱
WORKFLOW_RESPONSE_CACHE_TTL = 7200  # 2시간
EMBEDDING_CACHE_TTL = 86400  # 24시간
SEARCH_RESULT_CACHE_TTL = 3600  # 1시간

# 품질 검증
MIN_QUALITY_SCORE = 0.4
MAX_QUALITY_RETRIES = 2
MAX_WORKFLOW_ITERATIONS = 10

# 로깅
LOG_LEVEL = "INFO"
LOG_FORMAT = "json"
```

### pyproject.toml (주요 의존성)

```toml
[project]
name = "neos"
version = "0.11.0"
description = "Network of Expert Operating System - Enterprise Edition"

[project.dependencies]
# Web Framework
fastapi = "^0.116.1"
uvicorn = "^0.34.0"

# AI/ML
langgraph = "^0.6.6"
langchain = "^0.3.15"
langchain-openai = "^0.2.14"
langchain-anthropic = "^0.3.9"
crewai = "^0.175.0"

# Database
sqlalchemy = "^2.0.43"
asyncpg = "^0.30.0"
psycopg2-binary = "^2.9.10"
pgvector = "^0.3.7"

# Caching
redis = "^6.4.0"
aioredis = "^2.0.1"

# Search & Scraping
tavily-python = "^0.5.0"
playwright = "^1.49.1"

# Utilities
pydantic = "^2.10.5"
pydantic-settings = "^2.7.0"
python-dotenv = "^1.0.1"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

---

## 최근 주요 개선 사항 (Recent Improvements)

### 2024년 11월

1. **실시간 진행 상황 스트리밍**
   - SSE (Server-Sent Events) 지원
   - Deep Research 진행 상황 실시간 전달
   - 자동 재연결 및 하트비트

2. **UI 리디자인**
   - 다크 블루 테마 (#050d4d)
   - 개선된 채팅 인터페이스
   - 대화 생성 전 모드 선택 기능

3. **데이터베이스 최적화**
   - JSONB 핸들링 개선
   - 중복 인덱스 제거
   - 쿼리 성능 향상

4. **분산 상태 관리**
   - PostgreSQL 체크포인터 도입
   - 엔터프라이즈급 안정성 향상

5. **동적 실행**
   - Deep Research의 Dynamic N-phase execution
   - Multi-Query Search의 Dynamic N-task execution

6. **연결 복원력**
   - 자동 재시도 로직
   - Circuit breaker 패턴
   - Graceful degradation

---

## 참고 자료 (References)

- **LangGraph**: https://python.langchain.com/docs/langgraph
- **CrewAI**: https://docs.crewai.com
- **FastAPI**: https://fastapi.tiangolo.com
- **pgvector**: https://github.com/pgvector/pgvector
- **Next.js**: https://nextjs.org/docs

---

**문서 버전**: 1.0
**작성일**: 2025-11-29
**다음 업데이트 예정**: 2026-01-29
