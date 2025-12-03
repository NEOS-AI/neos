# NEOS 백엔드 구현 문서 (NEOS Backend Implementation)

## 목차 (Table of Contents)

1. [기술 스택](#기술-스택-technology-stack)
2. [프로젝트 구조](#프로젝트-구조-project-structure)
3. [데이터베이스 구현](#데이터베이스-구현-database-implementation)
4. [워크플로우 구현](#워크플로우-구현-workflow-implementation)
5. [에이전트 구현](#에이전트-구현-agent-implementation)
6. [API 엔드포인트](#api-엔드포인트-api-endpoints)
7. [서비스 레이어](#서비스-레이어-service-layer)
8. [캐싱 전략](#캐싱-전략-caching-strategy)
9. [인증 및 보안](#인증-및-보안-authentication-and-security)
10. [배포 및 모니터링](#배포-및-모니터링-deployment-and-monitoring)
11. [⚠️ Breaking Changes (v0.12.0)](#-breaking-changes-v0120)

---

## 기술 스택 (Technology Stack)

### 핵심 프레임워크

```python
# Web Framework
fastapi = "^0.116.1"
uvicorn = "^0.34.0"
pydantic = "^2.10.5"
pydantic-settings = "^2.7.0"

# AI/ML Framework
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
alembic = "^1.14.0"

# Caching & Queue
redis = "^6.4.0"
aioredis = "^2.0.1"

# Search & Scraping
tavily-python = "^0.5.0"
playwright = "^1.49.1"
beautifulsoup4 = "^4.12.3"

# Utilities
python-dotenv = "^1.0.1"
python-multipart = "^0.0.20"
aiofiles = "^24.1.0"
```

### 개발 도구

```python
# Testing
pytest = "^8.3.4"
pytest-asyncio = "^0.25.2"
pytest-cov = "^6.0.0"

# Code Quality
ruff = "^0.8.4"
mypy = "^1.14.0"
black = "^24.11.0"

# Logging & Monitoring
structlog = "^24.4.0"
sentry-sdk = "^2.19.2"
```

---

## 프로젝트 구조 (Project Structure)

```
neos/
├── neos/                          # 메인 패키지 (~20,334 LOC)
│   ├── __init__.py
│   ├── main.py                    # FastAPI 엔트리 포인트
│   ├── cli.py                     # CLI 도구
│   ├── cli_workflow_builder.py    # Workflow 빌더 CLI
│   │
│   ├── agents/                    # 에이전트 구현 (15+ agents)
│   │   ├── __init__.py
│   │   ├── base.py                # BaseAgent, SearchAgent, AnalysisAgent, GenerationAgent
│   │   ├── autonomous_base.py     # AutonomousAgent (분산 환경)
│   │   ├── planning_agent.py      # QueryPlanningAgent
│   │   ├── criticism_feedback_agent.py  # 품질 검증 에이전트
│   │   │
│   │   ├── search_agents/         # 검색 에이전트 (8개)
│   │   │   ├── knowledge_search.py
│   │   │   ├── realtime_info_search.py
│   │   │   ├── realtime_data_search.py
│   │   │   ├── multi_query_search.py
│   │   │   ├── web_lookup.py
│   │   │   ├── deep_research.py
│   │   │   └── hyper_deep_research/  # 모듈화된 HyperDeepResearch
│   │   │       ├── agent.py
│   │   │       ├── prompts/
│   │   │       ├── utils/
│   │   │       └── repository/
│   │   │
│   │   ├── analysis_agents.py     # DataAnalysisAgent, ComparativeAnalysisAgent, WebContentAnalysisAgent
│   │   └── generation_agents.py   # ImageGenerationAgent, ApiCallAgent, FileProcessingAgent, TaskCreationAgent
│   │
│   ├── workflow/                  # 워크플로우 오케스트레이션
│   │   ├── __init__.py
│   │   ├── state.py               # AgentState TypedDict
│   │   ├── graph.py               # MultiAgentWorkflow (471 LOC)
│   │   ├── distributed_graph.py   # DistributedMultiAgentWorkflow (242 LOC)
│   │   ├── checkpointer.py        # PostgreSQLCheckpointer (414 LOC)
│   │   ├── scheduler.py           # 워크플로우 스케줄링 (184 LOC)
│   │   ├── multimodal_workflow.py # 멀티모달 워크플로우 (245 LOC)
│   │   │
│   │   ├── orchestrators/         # 오케스트레이터
│   │   │   ├── search_orchestrator.py
│   │   │   ├── analysis_orchestrator.py
│   │   │   └── generation_orchestrator.py
│   │   │
│   │   ├── processors/            # 프로세서
│   │   │   ├── result_processor.py
│   │   │   ├── quality_validator.py
│   │   │   └── response_generator.py
│   │   │
│   │   ├── pipelines/             # 문서 처리 파이프라인
│   │   │   ├── document_pipeline.py
│   │   │   ├── multimodal_pipeline.py
│   │   │   ├── pdf_parser.py
│   │   │   ├── word_parser.py
│   │   │   ├── excel_parser.py
│   │   │   ├── csv_parser.py
│   │   │   ├── image_pipeline.py
│   │   │   ├── audio_pipeline.py
│   │   │   └── unified_context.py
│   │   │
│   │   └── builder/               # 커스텀 워크플로우 빌더
│   │       ├── workflow_builder.py
│   │       ├── workflow_executor.py
│   │       ├── workflow_manager.py
│   │       ├── executors.py
│   │       └── nodes.py
│   │
│   ├── api/                       # FastAPI 애플리케이션
│   │   ├── __init__.py
│   │   ├── routes.py              # 메인 라우트 등록
│   │   │
│   │   ├── handlers/              # 라우터 (10개)
│   │   │   ├── query_handlers.py  # 쿼리 처리
│   │   │   ├── chat_handlers.py   # 채팅
│   │   │   ├── deep_research_handlers.py  # 심층 연구
│   │   │   ├── rag_chat_handlers.py       # RAG 채팅
│   │   │   ├── similarity_chat_handlers.py # 유사도 채팅
│   │   │   ├── document_handlers.py       # 문서 관리
│   │   │   ├── multimodal_handlers.py     # 멀티모달
│   │   │   ├── analytics_handlers.py      # 분석
│   │   │   ├── skills_handlers.py         # Skills API (NEW)
│   │   │   └── auth.py                    # 인증
│   │   │
│   │   ├── routes/                # 개별 라우트 정의
│   │   │   ├── chat_routes.py
│   │   │   ├── deep_research_routes.py
│   │   │   ├── query_routes.py
│   │   │   ├── multimodal_routes.py
│   │   │   └── web_search_analytics_routes.py
│   │   │
│   │   ├── services/              # 비즈니스 로직
│   │   │   ├── query_service.py
│   │   │   ├── chat_service.py
│   │   │   ├── document_service.py
│   │   │   └── analytics_service.py
│   │   │
│   │   ├── models/                # Pydantic 모델
│   │   │   ├── request_models.py
│   │   │   ├── response_models.py
│   │   │   └── enums.py
│   │   │
│   │   ├── dependencies/          # 의존성 주입
│   │   │   ├── auth.py            # 인증 의존성
│   │   │   ├── database.py        # DB 세션
│   │   │   └── rate_limit.py      # Rate limiting
│   │   │
│   │   └── middleware/            # 미들웨어
│   │       ├── cors.py
│   │       ├── error_handler.py
│   │       └── logging.py
│   │
│   ├── database/                  # 데이터 레이어
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy 모델 (15+)
│   │   ├── connection.py          # DB 커넥션 풀
│   │   ├── base.py                # Base 클래스
│   │   │
│   │   ├── repositories/          # 리포지토리 패턴
│   │   │   ├── user_repository.py
│   │   │   ├── conversation_repository.py
│   │   │   ├── message_repository.py
│   │   │   ├── document_repository.py
│   │   │   └── query_repository.py
│   │   │
│   │   └── migrations/            # Alembic 마이그레이션
│   │       ├── env.py
│   │       └── versions/
│   │
│   ├── services/                  # 지원 서비스
│   │   ├── chat_llm_service.py    # LLM 서비스
│   │   ├── rag_chat_llm_service.py
│   │   ├── similarity_search_service.py
│   │   ├── context_optimizer.py   # 컨텍스트 최적화 (NEW v0.12.0)
│   │   └── message_embedding_service.py
│   │
│   ├── skills/                    # Skills 시스템 (NEW)
│   │   ├── __init__.py
│   │   ├── base.py                # BaseSkill 추상 클래스
│   │   ├── manager.py             # SkillManager
│   │   ├── registry.py            # SkillRegistry
│   │   └── builtin/               # 내장 스킬 (7개)
│   │       ├── bigquery_skill.py
│   │       ├── docx_skill.py
│   │       ├── pdf_skill.py
│   │       ├── arxiv_skill.py
│   │       ├── pubmed_skill.py
│   │       ├── wikipedia_skill.py
│   │       └── research_assistant_skill.py
│   │
│   ├── tools/                     # 도구 관리
│   │   ├── __init__.py
│   │   ├── tool_selector.py       # 지능형 도구 선택
│   │   ├── tool_selector_base.py  # 베이스 클래스
│   │   ├── mcp_integration.py     # Model Context Protocol (26,812 bytes)
│   │   ├── mcp_server_manager.py  # MCP 서버 관리
│   │   └── tools/                 # 개별 도구
│   │       ├── web_search.py
│   │       ├── calculator.py
│   │       └── weather.py
│   │
│   ├── observability/             # 모니터링 및 추적 (NEW)
│   │   ├── core.py
│   │   ├── collectors.py
│   │   ├── metrics.py
│   │   ├── integration.py
│   │   ├── middleware.py
│   │   ├── phoenix_client.py
│   │   └── decorators.py
│   │
│   ├── pipelines/                 # Tool/MCP 통합
│   ├── dataset/                   # 데이터셋 관리
│   ├── storage/                   # 파일 저장소 추상화
│   │
│   ├── utils/                     # 유틸리티
│   │   ├── llm_factory.py         # LLM 생성 팩토리
│   │   ├── llm_wrapper.py         # 추적 가능한 LLM 래퍼
│   │   ├── embeddings.py          # 임베딩 관리
│   │   ├── cache.py               # Redis 캐시 관리
│   │   ├── semantic_cache.py      # 시맨틱 캐싱
│   │   ├── semantic_deduplicator.py  # 중복 제거
│   │   ├── token_counter.py       # tiktoken 토큰 카운팅
│   │   ├── circuit_breaker.py     # Circuit Breaker
│   │   ├── cost_calculator.py     # LLM 비용 계산
│   │   ├── security.py            # 보안 유틸리티
│   │   ├── jwt.py                 # JWT 처리
│   │   ├── csrf.py                # CSRF 보호
│   │   ├── message_queue.py       # 메시지 큐
│   │   ├── search_fallback.py     # 검색 폴백 전략
│   │   ├── language_detection.py  # 다국어 지원
│   │   └── url_detector.py        # URL 추출
│   │
│   └── config/                    # 설정
│       ├── __init__.py
│       └── settings.py            # Pydantic Settings (13,169 bytes)
│
├── tests/                         # 테스트
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── scripts/                       # 유틸리티 스크립트
│   ├── setup_db.py
│   └── seed_data.py
│
├── alembic.ini                    # Alembic 설정
├── pyproject.toml                 # 프로젝트 메타데이터
├── .env.example                   # 환경 변수 예시
└── README.md
```

---

## 데이터베이스 구현 (Database Implementation)

### SQLAlchemy 모델 (database/models.py)

#### 1. User 모델

```python
from sqlalchemy import Column, String, DateTime, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100))
    password_hash = Column(String(255))
    role = Column(String(50), default="user")
    preferences = Column(JSON)  # {"theme": "dark", "language": "en"}
    api_keys = Column(JSON)  # {"openai": "sk-...", "anthropic": "sk-ant-..."}
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

    # 관계
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    api_keys_rel = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, email={self.email})>"
```

#### 2. Conversation & Message 모델

```python
class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    session_id = Column(String(255), unique=True, index=True)
    title = Column(String(500))
    mode = Column(String(50))  # standard, rag, similarity, deep_research
    status = Column(String(50), default="active")  # active, archived, deleted
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Conversation(id={self.conversation_id}, mode={self.mode})>"


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.conversation_id"), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536))  # pgvector
    tokens_used = Column(Integer)
    cost = Column(Numeric(10, 6))
    quality_score = Column(Float)
    metadata = Column(JSON)  # sources, execution_time, etc.
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 관계
    conversation = relationship("Conversation", back_populates="messages")

    # 인덱스
    __table_args__ = (
        Index('idx_message_embedding', 'embedding', postgresql_using='ivfflat', postgresql_ops={'embedding': 'vector_cosine_ops'}),
    )

    def __repr__(self):
        return f"<Message(id={self.message_id}, role={self.role})>"
```

#### 3. Document & DocumentChunk 모델

```python
class Document(Base):
    __tablename__ = "documents"

    document_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    storage_key = Column(String(500))  # S3 키 또는 로컬 경로
    file_size = Column(BigInteger)
    mime_type = Column(String(100))
    processing_status = Column(String(50), default="pending")  # pending, processing, completed, failed
    embedding_status = Column(String(50), default="pending")
    metadata = Column(JSON)  # {"pages": 10, "author": "...", "title": "..."}
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)

    # 관계
    user = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.document_id}, filename={self.filename})>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    chunk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.document_id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536))
    page_number = Column(Integer)
    heading_hierarchy = Column(JSON)  # {"h1": "Chapter 1", "h2": "Section 1.1"}
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계
    document = relationship("Document", back_populates="chunks")

    # 인덱스
    __table_args__ = (
        Index('idx_chunk_embedding', 'embedding', postgresql_using='ivfflat', postgresql_ops={'embedding': 'vector_cosine_ops'}),
        Index('idx_chunk_fulltext', 'chunk_text', postgresql_using='gin', postgresql_ops={'chunk_text': 'gin_trgm_ops'}),
    )
```

#### 4. QueryHistory 모델

```python
class QueryHistory(Base):
    __tablename__ = "query_history"

    query_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), index=True)
    session_id = Column(String(255), index=True)
    query_text = Column(Text, nullable=False)
    query_embedding = Column(Vector(1536))
    intent = Column(String(100))  # search, analysis, generation
    classification = Column(JSON)  # {"primary": "search", "secondary": ["web", "knowledge"]}
    quality_score = Column(Float)
    execution_time = Column(Float)  # 초
    tokens_used = Column(Integer)
    cost = Column(Numeric(10, 6))
    result = Column(Text)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 인덱스
    __table_args__ = (
        Index('idx_query_embedding', 'query_embedding', postgresql_using='ivfflat'),
    )
```

#### 5. HyperResearchReport 모델

```python
class HyperResearchReport(Base):
    __tablename__ = "hyper_research_reports"

    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), index=True)
    query = Column(Text, nullable=False)
    status = Column(String(50), default="planning")  # planning, researching, analyzing, completed, failed
    research_plan = Column(JSON)  # {"phases": [...], "sources": [...]}
    sources = Column(JSON)  # [{"url": "...", "title": "...", "relevance": 0.95}]
    report_content = Column(Text)  # Markdown 형식
    metadata = Column(JSON)  # {"total_sources": 50, "execution_time": 1800}
    execution_time = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
```

### Repository 패턴 (database/repositories/)

#### ConversationRepository

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from ..models import Conversation, Message

class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, mode: str, title: Optional[str] = None) -> Conversation:
        """새 대화 생성"""
        conversation = Conversation(
            user_id=user_id,
            mode=mode,
            title=title or f"Conversation {datetime.utcnow().isoformat()}",
            session_id=str(uuid.uuid4())
        )
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """대화 조회"""
        result = await self.session.execute(
            select(Conversation).where(Conversation.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str, limit: int = 20, offset: int = 0) -> List[Conversation]:
        """사용자의 대화 목록"""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .where(Conversation.status == "active")
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def add_message(self, conversation_id: str, role: str, content: str, **kwargs) -> Message:
        """메시지 추가"""
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            **kwargs
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)

        # 대화 업데이트 시간 갱신
        await self.session.execute(
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(updated_at=datetime.utcnow())
        )
        await self.session.commit()

        return message

    async def get_messages(self, conversation_id: str, limit: int = 100) -> List[Message]:
        """대화의 메시지 조회"""
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def update_title(self, conversation_id: str, title: str):
        """대화 제목 업데이트"""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(title=title)
        )
        await self.session.commit()

    async def archive(self, conversation_id: str):
        """대화 아카이브"""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(status="archived")
        )
        await self.session.commit()
```

#### DocumentRepository

```python
from sqlalchemy import select, func
from pgvector.sqlalchemy import Vector

class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, filename: str, storage_key: str, **kwargs) -> Document:
        """문서 생성"""
        document = Document(
            user_id=user_id,
            filename=filename,
            storage_key=storage_key,
            **kwargs
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def add_chunk(self, document_id: str, chunk_index: int, chunk_text: str, embedding: List[float], **kwargs) -> DocumentChunk:
        """청크 추가"""
        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            embedding=embedding,
            **kwargs
        )
        self.session.add(chunk)
        await self.session.commit()
        return chunk

    async def semantic_search(self, query_embedding: List[float], user_id: str, top_k: int = 5) -> List[DocumentChunk]:
        """의미론적 검색 (코사인 유사도)"""
        # pgvector의 코사인 거리 연산자 사용 (<=>)
        result = await self.session.execute(
            select(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.document_id)
            .where(Document.user_id == user_id)
            .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        return result.scalars().all()

    async def update_processing_status(self, document_id: str, status: str):
        """처리 상태 업데이트"""
        await self.session.execute(
            update(Document)
            .where(Document.document_id == document_id)
            .values(processing_status=status, processed_at=datetime.utcnow())
        )
        await self.session.commit()
```

### 데이터베이스 연결 (database/connection.py)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from neos.config.settings import settings

# 엔진 생성
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,  # 40
    max_overflow=10,
    pool_pre_ping=True,  # 연결 검증
    pool_recycle=3600,  # 1시간마다 연결 재생성
)

# 세션 팩토리
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

# 의존성 주입용
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

---

## 워크플로우 구현 (Workflow Implementation)

### AgentState 정의 (workflow/state.py)

```python
from typing import TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    # 기본 정보
    user_id: str
    session_id: str
    query: str
    query_embedding: List[float]

    # 분류 결과
    classification: Dict[str, Any]
    required_agents: List[str]

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
    retry_count: int

    # 메타데이터
    execution_time: float
    tokens_used: int
    cost: float
    message_history: List[Dict[str, str]]

    # 캐싱
    cache_key: str
    cached_response: Optional[str]
```

### MultiAgentWorkflow 그래프 (workflow/graph.py)

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from .state import AgentState
from .orchestrators import SearchOrchestrator, AnalysisOrchestrator, GenerationOrchestrator
from .processors import ResultProcessor, QualityValidator, ResponseGenerator

class MultiAgentWorkflow:
    def __init__(self, checkpointer=None):
        self.checkpointer = checkpointer
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """7단계 워크플로우 그래프 구축"""
        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("query_classifier", self._classify_query)
        workflow.add_node("search_orchestrator", SearchOrchestrator().orchestrate)
        workflow.add_node("analysis_orchestrator", AnalysisOrchestrator().orchestrate)
        workflow.add_node("generation_orchestrator", GenerationOrchestrator().orchestrate)
        workflow.add_node("result_integrator", ResultProcessor().integrate)
        workflow.add_node("quality_validator", QualityValidator().validate)
        workflow.add_node("response_generator", ResponseGenerator().generate)

        # 엣지 추가 (순차 실행)
        workflow.set_entry_point("query_classifier")
        workflow.add_edge("query_classifier", "search_orchestrator")
        workflow.add_edge("search_orchestrator", "analysis_orchestrator")
        workflow.add_edge("analysis_orchestrator", "generation_orchestrator")
        workflow.add_edge("generation_orchestrator", "result_integrator")
        workflow.add_edge("result_integrator", "quality_validator")

        # 조건부 엣지 (품질 검증)
        workflow.add_conditional_edges(
            "quality_validator",
            self._should_retry,
            {
                "retry": "analysis_orchestrator",  # 재생성
                "continue": "response_generator",  # 통과
            }
        )

        workflow.add_edge("response_generator", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def _classify_query(self, state: AgentState) -> AgentState:
        """쿼리 분류"""
        from neos.agents.planning_agent import QueryPlanningAgent

        planner = QueryPlanningAgent()
        classification = await planner.classify(state["query"])

        state["classification"] = classification
        state["required_agents"] = classification.get("agents", [])
        return state

    def _should_retry(self, state: AgentState) -> str:
        """품질 검증 후 재시도 여부 결정"""
        MAX_RETRIES = 2
        MIN_QUALITY_SCORE = 0.4

        if state["quality_score"] < MIN_QUALITY_SCORE and state["retry_count"] < MAX_RETRIES:
            state["retry_count"] += 1
            return "retry"
        return "continue"

    async def execute(self, query: str, user_id: str, session_id: str) -> Dict[str, Any]:
        """워크플로우 실행"""
        # 초기 상태
        initial_state: AgentState = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "query_embedding": await self._get_embedding(query),
            "retry_count": 0,
            "message_history": [],
        }

        # 실행
        final_state = await self.graph.ainvoke(initial_state)

        return {
            "response": final_state["final_response"],
            "quality_score": final_state["quality_score"],
            "execution_time": final_state["execution_time"],
            "tokens_used": final_state["tokens_used"],
            "cost": final_state["cost"],
        }

    async def _get_embedding(self, text: str) -> List[float]:
        """임베딩 생성"""
        from neos.utils.embeddings import EmbeddingManager
        manager = EmbeddingManager()
        return await manager.get_embedding(text)
```

### SearchOrchestrator (workflow/orchestrators/search_orchestrator.py)

```python
import asyncio
from typing import List, Dict, Any
from neos.agents.search_agents import (
    KnowledgeSearchAgent,
    RealtimeInfoSearchAgent,
    MultiQuerySearchAgent,
    DeepResearchAgent,
)

class SearchOrchestrator:
    def __init__(self):
        self.agents = {
            "knowledge": KnowledgeSearchAgent(),
            "realtime_info": RealtimeInfoSearchAgent(),
            "multi_query": MultiQuerySearchAgent(),
            "deep_research": DeepResearchAgent(),
        }

    async def orchestrate(self, state: AgentState) -> AgentState:
        """검색 에이전트 오케스트레이션"""
        required_agents = state["required_agents"]
        search_tasks = []

        # 필요한 에이전트만 실행
        for agent_type in required_agents:
            if agent_type in self.agents:
                agent = self.agents[agent_type]
                task = agent.execute(state["query"], state)
                search_tasks.append(task)

        # 병렬 실행
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # 결과 집계
        all_results = []
        for result in results:
            if isinstance(result, Exception):
                # 에러 처리
                continue
            all_results.extend(result.get("results", []))

        state["search_results"] = all_results
        return state
```

### QualityValidator (workflow/processors/quality_validator.py)

```python
from neos.utils.llm_factory import LLMFactory

class QualityValidator:
    def __init__(self):
        self.llm = LLMFactory.create_llm(model="gpt-4-turbo-preview")

    async def validate(self, state: AgentState) -> AgentState:
        """품질 검증"""
        response = state["integrated_result"]
        query = state["query"]

        # LLM으로 품질 평가
        prompt = f"""
        Query: {query}
        Response: {response}

        Evaluate the quality of this response on a scale of 0-1 based on:
        1. Completeness (0-0.33): Does it fully answer the query?
        2. Relevance (0-0.33): Is the information relevant?
        3. Coherence (0-0.34): Is it well-structured and clear?

        Return JSON:
        {{
            "completeness": <score>,
            "relevance": <score>,
            "coherence": <score>,
            "total": <sum>,
            "feedback": "<improvement suggestions>"
        }}
        """

        evaluation = await self.llm.ainvoke(prompt)
        eval_data = json.loads(evaluation.content)

        state["quality_score"] = eval_data["total"]
        state["quality_feedback"] = eval_data["feedback"]

        return state
```

---

## 에이전트 구현 (Agent Implementation)

### BaseAgent (agents/base.py)

```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from crewai import Agent, Task, Crew
from neos.utils.llm_factory import LLMFactory

class BaseAgent(ABC):
    def __init__(self, name: str, role: str, goal: str):
        self.name = name
        self.role = role
        self.goal = goal
        self.llm = LLMFactory.create_llm()

    @abstractmethod
    async def execute(self, query: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """에이전트 실행"""
        pass

    def _create_crew_agent(self, backstory: str = "") -> Agent:
        """CrewAI Agent 생성"""
        return Agent(
            role=self.role,
            goal=self.goal,
            backstory=backstory or f"I am a {self.role} specialized in {self.goal}",
            llm=self.llm,
            verbose=True,
        )

    async def _run_task(self, agent: Agent, task_description: str) -> str:
        """태스크 실행"""
        task = Task(
            description=task_description,
            agent=agent,
            expected_output="Detailed results based on the task description",
        )

        crew = Crew(
            agents=[agent],
            tasks=[task],
            verbose=True,
        )

        result = await crew.kickoff_async()
        return result
```

### DeepResearchAgent (agents/search_agents/deep_research.py)

```python
import asyncio
from typing import List, Dict, Any
from neos.agents.base import SearchAgent
from neos.utils.embeddings import EmbeddingManager

class DeepResearchAgent(SearchAgent):
    """4단계 심층 연구 에이전트"""

    def __init__(self):
        super().__init__(
            name="DeepResearch",
            role="Deep Research Specialist",
            goal="Conduct comprehensive research on complex topics"
        )
        self.embedding_manager = EmbeddingManager()

    async def execute(self, query: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """4단계 연구 프로세스"""
        results = {
            "phases": [],
            "sources": [],
            "insights": [],
            "report": "",
        }

        # Phase 1: 연구 계획 수립
        plan = await self._create_research_plan(query)
        results["phases"].append({"phase": 1, "name": "Planning", "status": "completed", "data": plan})

        # Phase 2: 광범위한 검색 (30-50+ 소스)
        sources = await self._broad_search(query, plan)
        results["sources"] = sources
        results["phases"].append({"phase": 2, "name": "Searching", "status": "completed", "sources_count": len(sources)})

        # Phase 3: 분석 및 통합
        insights = await self._analyze_sources(sources, query)
        results["insights"] = insights
        results["phases"].append({"phase": 3, "name": "Analyzing", "status": "completed", "insights_count": len(insights)})

        # Phase 4: 최종 보고서 생성
        report = await self._generate_report(query, sources, insights)
        results["report"] = report
        results["phases"].append({"phase": 4, "name": "Reporting", "status": "completed"})

        return results

    async def _create_research_plan(self, query: str) -> Dict[str, Any]:
        """연구 계획 수립"""
        agent = self._create_crew_agent(
            backstory="I create comprehensive research plans that guide thorough investigations"
        )

        task_description = f"""
        Create a detailed research plan for the query: "{query}"

        The plan should include:
        1. Key questions to investigate (5-10 questions)
        2. Search strategies (keywords, sources)
        3. Expected outcomes

        Return as structured JSON.
        """

        result = await self._run_task(agent, task_description)
        return json.loads(result)

    async def _broad_search(self, query: str, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """광범위한 검색 (병렬)"""
        from neos.tools.tools.web_search import TavilySearch

        search_tool = TavilySearch()
        questions = plan.get("questions", [])

        # 각 질문에 대해 검색
        search_tasks = [
            search_tool.search(question, max_results=5)
            for question in questions
        ]

        results = await asyncio.gather(*search_tasks)

        # 결과 통합 및 중복 제거
        all_sources = []
        seen_urls = set()

        for result_set in results:
            for source in result_set:
                url = source.get("url")
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_sources.append(source)

        return all_sources

    async def _analyze_sources(self, sources: List[Dict[str, Any]], query: str) -> List[str]:
        """소스 분석 및 인사이트 추출"""
        agent = self._create_crew_agent(
            backstory="I analyze large amounts of information to extract key insights"
        )

        # 소스를 배치로 나누어 분석 (한 번에 10개씩)
        batch_size = 10
        all_insights = []

        for i in range(0, len(sources), batch_size):
            batch = sources[i:i+batch_size]
            task_description = f"""
            Analyze these sources related to "{query}":

            {json.dumps(batch, indent=2)}

            Extract:
            1. Key findings
            2. Common themes
            3. Contradictions or disagreements
            4. Notable insights

            Return as a list of insights.
            """

            insights = await self._run_task(agent, task_description)
            all_insights.extend(json.loads(insights))

        return all_insights

    async def _generate_report(self, query: str, sources: List[Dict[str, Any]], insights: List[str]) -> str:
        """최종 보고서 생성 (Markdown)"""
        agent = self._create_crew_agent(
            backstory="I create comprehensive research reports with proper citations"
        )

        task_description = f"""
        Create a comprehensive research report on: "{query}"

        Based on:
        - {len(sources)} sources
        - Key insights: {json.dumps(insights[:10])}  # 상위 10개

        Structure:
        # {query}

        ## Executive Summary
        [2-3 paragraphs]

        ## Key Findings
        [Detailed findings with citations]

        ## Analysis
        [In-depth analysis]

        ## Conclusion
        [Summary and implications]

        ## Sources
        [Numbered list with proper citations]

        Use Markdown formatting.
        """

        report = await self._run_task(agent, task_description)
        return report
```

### MultiQuerySearchAgent (agents/search_agents/multi_query_search.py)

```python
class MultiQuerySearchAgent(SearchAgent):
    """다각도 검색 에이전트 (Dynamic N-task execution)"""

    async def execute(self, query: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """하나의 쿼리를 10+ 하위 쿼리로 분해하여 검색"""

        # 1. 하위 쿼리 생성
        sub_queries = await self._generate_sub_queries(query)

        # 2. 각 하위 쿼리 병렬 검색
        search_tasks = [
            self._search_single_query(sq)
            for sq in sub_queries
        ]

        results = await asyncio.gather(*search_tasks)

        # 3. 결과 통합 및 순위 결정
        integrated = await self._integrate_results(results, query)

        return {
            "sub_queries": sub_queries,
            "results": integrated,
        }

    async def _generate_sub_queries(self, query: str) -> List[str]:
        """동적으로 N개의 하위 쿼리 생성"""
        agent = self._create_crew_agent()

        task_description = f"""
        Break down this query into 10-15 sub-queries that explore different angles:

        Query: "{query}"

        Return as JSON array of strings.
        """

        result = await self._run_task(agent, task_description)
        return json.loads(result)
```

---

## API 엔드포인트 (API Endpoints)

### FastAPI 애플리케이션 (api/app.py)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neos.api.handlers import (
    query_handler,
    chat_handler,
    deep_research_handler,
    auth_handler,
    document_handler,
)

def create_app() -> FastAPI:
    app = FastAPI(
        title="NEOS API",
        version="0.11.0",
        description="Network of Expert Operating System",
    )

    # CORS 미들웨어
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 프로덕션에서는 특정 도메인만
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 라우터 등록
    app.include_router(query_handler.router, prefix="/api/v1", tags=["Query"])
    app.include_router(chat_handler.router, prefix="/api/v1", tags=["Chat"])
    app.include_router(deep_research_handler.router, prefix="/api/v1", tags=["DeepResearch"])
    app.include_router(auth_handler.router, prefix="/api/v1/auth", tags=["Auth"])
    app.include_router(document_handler.router, prefix="/api/v1/documents", tags=["Documents"])

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "0.11.0"}

    return app

app = create_app()
```

### ChatHandler (api/handlers/chat_handler.py)

```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from neos.database.connection import get_db
from neos.database.repositories import ConversationRepository
from neos.api.models.request_models import MessageCreate, ConversationCreate
from neos.api.services.chat_service import ChatService
from neos.api.dependencies.auth import get_current_user

router = APIRouter()

@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    request: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """새 대화 생성"""
    repo = ConversationRepository(db)
    conversation = await repo.create(
        user_id=current_user.user_id,
        mode=request.mode,
        title=request.title,
    )

    return {
        "conversation_id": str(conversation.conversation_id),
        "session_id": conversation.session_id,
        "mode": conversation.mode,
        "created_at": conversation.created_at.isoformat(),
    }

@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """대화 조회"""
    repo = ConversationRepository(db)
    conversation = await repo.get_by_id(conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await repo.get_messages(conversation_id)

    return {
        "conversation": {
            "conversation_id": str(conversation.conversation_id),
            "title": conversation.title,
            "mode": conversation.mode,
            "created_at": conversation.created_at.isoformat(),
        },
        "messages": [
            {
                "message_id": str(msg.message_id),
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
    }

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    request: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """메시지 전송 (일반 응답)"""
    service = ChatService(db)
    response = await service.send_message(
        conversation_id=conversation_id,
        user_message=request.content,
    )

    return response

@router.post("/conversations/{conversation_id}/stream")
async def stream_message(
    conversation_id: str,
    request: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """메시지 전송 (스트리밍 응답)"""
    service = ChatService(db)

    async def event_generator():
        async for chunk in service.stream_message(conversation_id, request.content):
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )

@router.get("/conversations")
async def list_conversations(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """대화 목록"""
    repo = ConversationRepository(db)
    conversations = await repo.list_by_user(
        user_id=current_user.user_id,
        limit=limit,
        offset=offset,
    )

    return {
        "conversations": [
            {
                "conversation_id": str(conv.conversation_id),
                "title": conv.title,
                "mode": conv.mode,
                "updated_at": conv.updated_at.isoformat(),
            }
            for conv in conversations
        ],
        "total": len(conversations),
        "limit": limit,
        "offset": offset,
    }
```

### DeepResearchHandler (api/handlers/deep_research_handler.py)

```python
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from neos.agents.search_agents.deep_research import DeepResearchAgent
from neos.database.repositories import HyperResearchRepository

router = APIRouter()

@router.post("/deep-research/start")
async def start_deep_research(
    query: str,
    research_type: str = "deep",  # deep | hyper
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """심층 연구 시작"""
    repo = HyperResearchRepository(db)
    report = await repo.create(
        user_id=current_user.user_id,
        query=query,
        status="planning",
    )

    # 백그라운드에서 연구 실행
    asyncio.create_task(
        execute_research(report.report_id, query, research_type, db)
    )

    return {
        "report_id": str(report.report_id),
        "status": "planning",
        "estimated_time": 1800 if research_type == "deep" else 3600,  # 초
    }

@router.get("/deep-research/{report_id}/stream")
async def stream_research_progress(report_id: str):
    """연구 진행 상황 스트리밍 (SSE)"""
    async def event_generator():
        # Redis Pub/Sub 또는 DB 폴링으로 진행 상황 전송
        import redis.asyncio as aioredis
        redis_client = await aioredis.from_url("redis://localhost")
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"research:{report_id}")

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                yield f"data: {json.dumps(data)}\n\n"

                if data.get("phase") == "completed":
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )

@router.get("/deep-research/{report_id}")
async def get_research_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """연구 보고서 조회"""
    repo = HyperResearchRepository(db)
    report = await repo.get_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "report_id": str(report.report_id),
        "query": report.query,
        "status": report.status,
        "report_content": report.report_content,
        "sources": report.sources,
        "metadata": report.metadata,
        "created_at": report.created_at.isoformat(),
        "completed_at": report.completed_at.isoformat() if report.completed_at else None,
    }
```

---

## 서비스 레이어 (Service Layer)

### ChatService (api/services/chat_service.py)

```python
from neos.database.repositories import ConversationRepository
from neos.services.chat_llm_service import ChatLLMService
from neos.utils.embeddings import EmbeddingManager

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)
        self.llm_service = ChatLLMService()
        self.embedding_manager = EmbeddingManager()

    async def send_message(self, conversation_id: str, user_message: str) -> Dict[str, Any]:
        """메시지 전송 및 응답 생성"""
        # 1. 사용자 메시지 저장
        user_msg = await self.repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            embedding=await self.embedding_manager.get_embedding(user_message),
        )

        # 2. 대화 기록 조회
        messages = await self.repo.get_messages(conversation_id, limit=20)
        message_history = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        # 3. LLM 응답 생성
        assistant_response = await self.llm_service.generate_response(
            messages=message_history,
            model="gpt-4-turbo-preview",
        )

        # 4. 어시스턴트 메시지 저장
        assistant_msg = await self.repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_response["content"],
            embedding=await self.embedding_manager.get_embedding(assistant_response["content"]),
            tokens_used=assistant_response["tokens_used"],
            cost=assistant_response["cost"],
        )

        return {
            "message_id": str(assistant_msg.message_id),
            "role": "assistant",
            "content": assistant_response["content"],
            "tokens_used": assistant_response["tokens_used"],
            "cost": float(assistant_response["cost"]),
        }

    async def stream_message(self, conversation_id: str, user_message: str):
        """메시지 스트리밍"""
        # 사용자 메시지 저장
        await self.repo.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )

        # 대화 기록 조회
        messages = await self.repo.get_messages(conversation_id, limit=20)
        message_history = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        # 스트리밍 응답
        full_response = ""
        async for chunk in self.llm_service.stream_response(message_history):
            full_response += chunk["content"]
            yield chunk

        # 최종 응답 저장
        await self.repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
        )
```

---

## 캐싱 전략 (Caching Strategy)

### CacheManager (utils/cache.py)

```python
import redis.asyncio as aioredis
from typing import Optional, Any
import json
import hashlib

class CacheManager:
    def __init__(self):
        self.redis = aioredis.from_url(
            "redis://localhost:6379",
            encoding="utf-8",
            decode_responses=True,
        )

    def _generate_key(self, prefix: str, **kwargs) -> str:
        """캐시 키 생성"""
        key_parts = [prefix]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        key_string = ":".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    async def get(self, prefix: str, **kwargs) -> Optional[Any]:
        """캐시 조회"""
        key = self._generate_key(prefix, **kwargs)
        value = await self.redis.get(key)
        return json.loads(value) if value else None

    async def set(self, prefix: str, value: Any, ttl: int = 3600, **kwargs):
        """캐시 저장"""
        key = self._generate_key(prefix, **kwargs)
        await self.redis.setex(
            key,
            ttl,
            json.dumps(value),
        )

    async def delete(self, prefix: str, **kwargs):
        """캐시 삭제"""
        key = self._generate_key(prefix, **kwargs)
        await self.redis.delete(key)

# 사용 예시
cache = CacheManager()

# 워크플로우 응답 캐싱
cached = await cache.get("workflow_response", query="what is AI", user_id="user123")
if cached:
    return cached

result = await workflow.execute(query)
await cache.set("workflow_response", result, ttl=7200, query="what is AI", user_id="user123")
```

---

## 인증 및 보안 (Authentication and Security)

### JWT 인증 (api/dependencies/auth.py)

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from neos.config.settings import settings

security = HTTPBearer()

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=24)) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자 조회"""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 사용자 조회
    from neos.database.repositories import UserRepository
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user
```

---

## 배포 및 모니터링 (Deployment and Monitoring)

### Docker Compose (docker-compose.yml)

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: neos
      POSTGRES_USER: neos
      POSTGRES_PASSWORD: neos_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  neos_api:
    build: .
    command: uvicorn neos.main:app --host 0.0.0.0 --port 8000 --workers 4
    environment:
      DATABASE_URL: postgresql+asyncpg://neos:neos_password@postgres:5432/neos
      REDIS_URL: redis://redis:6379/0
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis

volumes:
  postgres_data:
```

---

## ⚠️ Breaking Changes (v0.12.0)

### Phase 1-4 개선 사항 (2025-12-03)

#### Phase 1: 보안 강화 (Security Hardening)

**1. JWT_SECRET_KEY 필수화**
- ❌ **이전**: 빈 문자열 기본값 허용 (심각한 보안 취약점)
- ✅ **현재**: 환경 변수 필수 설정, 없으면 애플리케이션 시작 불가
- 📋 **마이그레이션**:
```bash
# JWT Secret Key 생성
python -c "import secrets; print(secrets.token_urlsafe(32))"

# .env 파일에 추가
JWT_SECRET_KEY=생성된_키_값
```

**2. API Key 해싱 알고리즘 변경**
- ❌ **이전**: SHA-256 (빠르지만 브루트포스 공격에 취약)
- ✅ **현재**: bcrypt (느리지만 안전, salt 자동 생성)
- ⚠️ **중요**: **기존 API Key는 모두 무효화됩니다!**
- 📋 **마이그레이션**: [배포 체크리스트 참조](/docs/checklist_20251203.md)

**3. CORS 정책 강화**
- ❌ **이전**: DEBUG 모드에서 `allow_origins=["*"]` 허용
- ✅ **현재**: DEBUG 모드에서도 특정 localhost 도메인만 허용
- 📋 **영향**: 프론트엔드가 허용 목록에 없으면 CORS 에러 발생

**4. SQL 보안 경고 추가**
- ✅ 모든 raw SQL 메서드에 보안 경고 추가 (ORM 사용 권장)
- ✅ 쿼리 로깅 시 일부만 기록 (민감 정보 보호)

#### Phase 2: 안정성 향상 (Stability Improvements)

**1. 데이터베이스 연결 풀 최적화**
- ❌ **이전**: `pool_size=40`, `max_overflow=10` (총 50개)
- ✅ **현재**: `pool_size=20`, `max_overflow=30` (총 50개, 더 탄력적)
- 📋 **근거**: PostgreSQL 기본 `max_connections=100`에 맞춰 조정
- 📋 **영향**: 연결 풀 고갈 시 더 유연하게 대응

**2. Session 누수 방지**
- ✅ `execute_in_transaction()` 메서드에 context manager 적용
- ✅ 자동 세션 정리로 메모리 누수 방지

**3. Circuit Breaker 패턴 도입**

- ✅ 외부 API 호출 실패 시 자동 차단
- ✅ 에이전트별 독립적인 Circuit Breaker 관리
- ✅ 시스템 안정성 향상 (장애 격리)
- 📋 **설정**: `.env`에서 `CIRCUIT_BREAKER_ENABLED=true` 설정

**4. 커스텀 예외 계층 구조**

- ✅ `neos/utils/exceptions.py` 신규 생성
- ✅ 4xx/5xx 예외를 명확하게 구분
- ✅ HTTP 상태 코드 자동 매핑
- ✅ 향상된 에러 로깅 및 디버깅

#### Phase 3: 코드 품질 (Code Quality) - 부분 완료

**1. 로깅 개선**
- ✅ `workflow/graph.py`의 `print()` → `logger.debug()` 변환
- 🔄 **진행 중**: 나머지 90+ 위치 변환 예정

**2. 타입 힌팅 및 문서화**
- 🔄 **예정**: 모든 함수에 완전한 타입 힌팅 추가

#### Phase 4: 성능 최적화 (Performance) - 부분 완료

**1. Semantic Cache 활성화**
- ❌ **이전**: `SEMANTIC_CACHE_ENABLED=false` (기본 비활성화)
- ✅ **현재**: `SEMANTIC_CACHE_ENABLED=true` (기본 활성화)
- ✅ **임계값 조정**: `0.95 → 0.90` (더 많은 캐시 히트)
- 📋 **효과**: LLM API 비용 절감, 응답 시간 단축

**2. Redis 연결 풀 설정 추가**
- ✅ `REDIS_POOL_SIZE=50` 설정 추가
- ✅ `REDIS_MIN_IDLE_CONNECTIONS=10` 설정 추가

**3. N+1 쿼리 최적화**
- 🔄 **예정**: `auth_service.py`의 N+1 쿼리 수정 예정

### 배포 시 필수 확인 사항

1. ✅ **JWT_SECRET_KEY 생성 및 설정** (필수!)
2. ✅ **API Key 재생성 계획 수립** ([체크리스트 참조](/docs/checklist_20251203.md))
3. ✅ **PostgreSQL max_connections 확인** (권장: 200 이상)
4. ✅ **CORS_ALLOWED_ORIGINS 업데이트** (프론트엔드 도메인)
5. ✅ **모니터링 설정** (에러율, 응답 시간, Circuit Breaker 상태)
