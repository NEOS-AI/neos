# NEOS Backend Architecture

## 목차

- [1. 개요](#1-개요)
- [2. 프로젝트 구조](#2-프로젝트-구조)
- [3. 핵심 컴포넌트](#3-핵심-컴포넌트)
- [4. 기술 스택](#4-기술-스택)
- [5. 아키텍처 패턴](#5-아키텍처-패턴)
- [6. 주요 기능](#6-주요-기능)
- [7. 워크플로우 시스템](#7-워크플로우-시스템)
- [8. API 설계](#8-api-설계)
- [9. 데이터베이스 스키마](#9-데이터베이스-스키마)
- [10. AI/에이전트 통합](#10-ai에이전트-통합)
- [11. 혁신적인 기술적 접근](#11-혁신적인-기술적-접근)
- [12. 아키텍처 강점](#12-아키텍처-강점)

---

## 1. 개요

NEOS는 엔터프라이즈급 AI 검색 및 분석 플랫폼으로, 최신 LangGraph 워크플로우 오케스트레이션과 CrewAI 멀티 에이전트 시스템을 결합한 고도로 모듈화된 백엔드 아키텍처를 특징으로 합니다.

### 주요 통계
- **총 코드 라인 수**: ~78,000 lines (Python)
- **모듈 수**: 49개 전문화된 디렉토리
- **아키텍처 패턴**: 계층형 + 모듈형 + 이벤트 주도형
- **AI 에이전트**: 15개 이상의 전문화된 에이전트
- **지원 LLM**: OpenAI GPT-4, Anthropic Claude 3/4, Google Gemini

### 핵심 설계 원칙
1. **수평적 확장성**: PostgreSQL 체크포인터를 통한 분산 상태 관리
2. **모듈성**: 명확한 관심사 분리와 플러그인 아키텍처
3. **성능 최적화**: pgvector 기반 스마트 캐싱 및 동적 TTL
4. **관찰 가능성**: Prometheus, OpenTelemetry, Arize Phoenix 통합
5. **확장 가능성**: Skills 및 MCP 도구 시스템

---

## 2. 프로젝트 구조

### 디렉토리 조직

```
neos/
├── agents/           # AI 에이전트 구현 (CrewAI 기반)
│   ├── search/       # 검색 에이전트 (8종)
│   ├── analysis/     # 분석 에이전트 (3종)
│   ├── generation/   # 생성 에이전트 (4종)
│   └── base/         # 베이스 에이전트 추상 클래스
│
├── api/              # REST API 계층 (FastAPI)
│   ├── handlers/     # 요청 핸들러 (thin layer)
│   ├── models/       # Pydantic 요청/응답 모델
│   ├── services/     # 비즈니스 로직 서비스
│   └── dependencies/ # 인증 및 의존성 주입
│
├── config/           # 설정 및 환경 변수
│   ├── settings.py   # Pydantic Settings
│   └── llm_config.py # LLM 제공자 설정
│
├── database/         # 데이터베이스 계층
│   ├── models.py     # SQLAlchemy 모델 (617 lines)
│   ├── connection.py # 연결 풀 관리
│   └── repository/   # Repository 패턴 구현
│
├── dataset/          # 데이터 수집 및 저장
│   └── collectors/   # LLM 상호작용 데이터 수집
│
├── observability/    # 모니터링 및 메트릭
│   ├── metrics.py    # Prometheus 메트릭
│   ├── tracing.py    # OpenTelemetry 추적
│   └── phoenix.py    # LLM 관찰 가능성
│
├── pipelines/        # 문서 처리 파이프라인
│   ├── image.py      # 이미지 분석 파이프라인
│   ├── audio.py      # 오디오 트랜스크립션
│   ├── document.py   # 문서 처리
│   └── multimodal.py # 멀티모달 통합
│
├── prompts/          # LLM 프롬프트 템플릿
│   ├── templates/    # 시스템 프롬프트
│   └── agents/       # 에이전트별 프롬프트
│
├── services/         # 비즈니스 로직 서비스
│   ├── chat.py       # 채팅 서비스 (50KB+)
│   ├── document.py   # 문서 관리
│   ├── auth.py       # 인증 서비스
│   └── analytics.py  # 분석 서비스
│
├── skills/           # 확장 가능한 스킬 시스템
│   ├── base/         # 스킬 추상 클래스
│   ├── manager/      # 스킬 라이프사이클 관리
│   └── builtin/      # 내장 스킬 (arxiv, wikipedia, etc.)
│
├── storage/          # 파일 스토리지 추상화
│   ├── s3.py         # AWS S3 스토리지
│   ├── local.py      # 로컬 파일 시스템
│   └── rustfs.py     # Rust 기반 스토리지
│
├── tools/            # MCP 도구 및 통합
│   ├── mcp_integration.py  # MCP 클라이언트
│   ├── manager/      # 도구 관리자
│   └── builtin/      # 내장 도구
│
├── utils/            # 유틸리티 함수
│   ├── llm_factory.py       # LLM 인스턴스 생성
│   ├── context_optimizer.py # 컨텍스트 최적화
│   └── token_counter.py     # 토큰 카운팅
│
└── workflow/         # LangGraph 워크플로우 오케스트레이션
    ├── graph.py      # 중앙 워크플로우 (809 lines)
    ├── state.py      # 타입 안전 상태 관리
    ├── checkpointer.py        # PostgreSQL 체크포인터
    └── orchestrators/ # 검색, 분석, 생성 오케스트레이터
```

### 코드 조직 원칙

1. **계층형 아키텍처**: API → Service → Workflow → Agent → Data
2. **모듈성**: 각 디렉토리는 단일 책임을 가짐
3. **의존성 역전**: 추상화에 의존, 구체적 구현에 의존하지 않음
4. **명확한 경계**: 각 계층 간 명확한 인터페이스

---

## 3. 핵심 컴포넌트

### 3.1 워크플로우 시스템 (LangGraph)

**위치**: `neos/workflow/`

**핵심 파일**:
- `graph.py` (809 lines) - 중앙 워크플로우 오케스트레이션
- `state.py` - TypedDict 기반 타입 안전 상태 관리
- `checkpointer.py` - PostgreSQL 기반 분산 체크포인팅

**주요 특징**:
- ✅ **StateGraph 기반 워크플로우**: 조건부 라우팅 및 동적 실행 경로
- ✅ **분산 체크포인팅**: 수평적 확장을 위한 PostgreSQL 기반 상태 지속성
- ✅ **세션 영속성**: 서버 재시작 후에도 워크플로우 복구 가능
- ✅ **이벤트 주도 아키텍처**: 워크플로우 콜백을 통한 실시간 피드백
- ✅ **스마트 캐싱**: pgvector 기반 시맨틱 유사도 캐싱

**워크플로우 노드**:
1. `conversation_context_processor` - 대화 히스토리 분석 및 쿼리 개선
2. `query_classifier` - 의도 감지 및 라우팅
3. `skill_tool_selector` - 동적 도구 선택
4. `search_orchestrator` - 멀티 에이전트 검색 조율
5. `analysis_orchestrator` - 데이터 분석 조율
6. `generation_orchestrator` - 콘텐츠 생성 조율
7. `result_integrator` - 결과 통합 및 중복 제거
8. `quality_validator` - 품질 보증 및 재시도 로직
9. `response_generator` - 최종 응답 포맷팅

### 3.2 에이전트 시스템 (CrewAI)

**위치**: `neos/agents/`

**아키텍처**: CrewAI 기반 멀티 에이전트 프레임워크

**에이전트 카테고리**:

#### 검색 에이전트 (Search Agents)
- **KnowledgeSearchAgent**: 내부 지식 베이스 쿼리
- **RealtimeInfoSearchAgent**: 실시간 웹 검색 (Tavily API)
- **RealtimeDataSearchAgent**: 실시간 데이터 API (날씨, 주식 등)
- **MultiQuerySearchAgent**: 다각도 쿼리 확장 및 병렬 검색
- **WebLookUpAgent**: 직접 URL 콘텐츠 추출 (Playwright 지원)
- **DeepResearchAgent**: 4단계 포괄적 연구 (30-50+ 소스)
- **HyperDeepResearchAgent**: 8단계 체계적 연구 (200+ 소스, 30-60분)
- **IterativeWebExplorerAgent**: 품질 기반 반복 탐색

#### 분석 에이전트 (Analysis Agents)
- **DataAnalysisAgent**: 통계 분석 및 패턴 발견
- **ComparativeAnalysisAgent**: 다중 소스 비교 분석
- **WebContentAnalysisAgent**: 웹 페이지 콘텐츠 분석

#### 생성 에이전트 (Generation Agents)
- **ImageGenerationAgent**: DALL-E 3 통합
- **ApiCallAgent**: 날씨, 환율, 주식 API
- **FileProcessingAgent**: 문서 처리 (PDF, DOCX, etc.)
- **TaskCreationAgent**: 자동 프로젝트 계획

**베이스 에이전트 아키텍처**:
```python
class BaseAgent(ABC):
    """
    모든 에이전트의 추상 베이스 클래스

    특징:
    - CrewAI Agent 래퍼
    - asyncio.to_thread()를 통한 비동기 실행
    - 입력 검증
    - 표준화된 출력 포맷
    - llm_factory를 통한 LLM 통합
    """

    @abstractmethod
    async def execute(self, query: str, context: Dict) -> Dict:
        """에이전트 실행 메서드"""
        pass
```

### 3.3 API 계층 (FastAPI)

**위치**: `neos/api/`

**구조**:
```
api/
├── handlers/        # 요청 핸들링 (thin layer)
├── models/          # Pydantic 요청/응답 모델
├── services/        # 비즈니스 로직
└── dependencies/    # 인증 및 의존성 주입
```

**주요 핸들러**:
- `query_handlers.py` - 메인 쿼리 엔드포인트
- `chat_handlers.py` (50KB+) - 포괄적인 채팅 API
- `deep_research_handlers.py` - 장시간 실행 연구 작업
- `workflow_stream_handlers.py` - SSE/WebSocket 스트리밍
- `multimodal_handlers.py` - 이미지/오디오/비디오 처리
- `auth.py` - JWT + OAuth2 (Google)
- `skills_handlers.py` - 스킬 관리 API
- `artifact_handlers.py` - 문서 아티팩트
- `vote_handlers.py` - 사용자 피드백

**인증 메커니즘**:
- ✅ JWT 토큰 (액세스 + 리프레시)
- ✅ OAuth2 (Google)
- ✅ API 키 인증
- ✅ 세션 관리
- ✅ 역할 기반 접근 제어 (RBAC)

### 3.4 데이터베이스 계층

**위치**: `neos/database/`

**모델** (`models.py` - 617 lines):

#### 사용자 관리
- **User**: 인증, OAuth, 구독 관리
- **APIKey**: 스코프 기반 API 키 관리
- **RefreshToken**: 토큰 로테이션 지원
- **UserOAuthAccount**: OAuth 제공자 연결
- **Organization**: 엔터프라이즈 멀티 테넌시
- **OrganizationAdmin**: 조직 역할 관리

#### 쿼리 & 검색
- **QueryHistory**: 임베딩과 함께 쿼리 로깅
- **RelatedQuery**: 쿼리 관계 추적
- **TrendingQuery**: 트렌드 쿼리 분석
- **SearchSession**: 세션 추적

#### 문서 관리
- **Document**: 파일 메타데이터 및 스토리지
- **DocumentChunk**: pgvector 임베딩을 포함한 텍스트 청크
- **KnowledgeGraph**: 엔티티 추출 및 관계

#### 스마트 캐싱 (pgvector)
- **QueryCacheEntry**: 동적 TTL을 가진 시맨틱 캐시
- **CacheStatistics**: 성능 모니터링

#### 웹 프론트엔드 통합
- **Vote**: 사용자 피드백 (upvote/downvote)
- **ArtifactDocument**: 생성된 문서
- **Suggestion**: 문서 개선 제안

**연결 관리**:
- AsyncPG를 통한 비동기 작업
- SQLAlchemy ORM
- 연결 풀링 (기본 20 + 오버플로우 30)
- 데이터 액세스를 위한 Repository 패턴

### 3.5 스킬 시스템

**위치**: `neos/skills/`

**아키텍처**: 플러그인 기반 확장 가능 스킬 시스템

**컴포넌트**:
- `base/skill.py` - 추상 베이스 클래스
- `manager/skill_manager.py` - 스킬 라이프사이클 관리
- `manager/auto_discovery.py` - 자동 스킬 감지
- `manager/dependency_checker.py` - 의존성 검증
- `base/metadata_parser.py` - SKILL.md frontmatter 파싱

**내장 스킬**:
- `arxiv` - ArXiv 논문 검색
- `wikipedia` - Wikipedia 통합
- `pubmed` - 의료 연구
- `pdf` - PDF 처리
- `docx` - Word 문서 처리
- `research-assistant` - 연구 워크플로우

**스킬 구조**:
```
skill-name/
├── SKILL.md         # 메타데이터 + 문서화
├── skill.py         # 구현
├── requirements.txt # 의존성
└── datasources.md   # 선택적 데이터 소스
```

### 3.6 도구 시스템 (MCP 통합)

**위치**: `neos/tools/`

**Model Context Protocol (MCP) 통합**:
- `mcp_integration.py` - MCP 클라이언트
- `manager/mcp_manager.py` - MCP 서버 관리
- `manager/tool_selector.py` - 동적 도구 선택

**내장 도구**:
- `database.py` - 데이터베이스 쿼리
- `file_processing.py` - 파일 작업
- `web_search.py` - 웹 검색
- `git.py` - Git 작업
- `link_follower.py` - 링크 추출 및 팔로우

**도구 선택 전략**:
- `always` - 항상 MCP 사용
- `mcp_available` - 가능한 경우 사용
- `mcp_fallback` - 내장 도구로 폴백
- `preference_based` - 품질 기반 선택

---

## 4. 기술 스택

### 4.1 프레임워크 & 라이브러리

#### 핵심 프레임워크
| 기술 | 버전 | 용도 |
|------|------|------|
| **FastAPI** | 0.118.0+ | 웹 프레임워크 |
| **LangGraph** | 0.6.6+ | 워크플로우 오케스트레이션 |
| **CrewAI** | 0.175.0+ | 멀티 에이전트 프레임워크 |
| **LangChain** | 0.3.27+ | LLM 통합 |

#### AI/LLM
| 기술 | 버전 | 용도 |
|------|------|------|
| **OpenAI** | 1.104.2+ | GPT-4, DALL-E 3, 임베딩 |
| **Anthropic** | 0.65.0+ | Claude 3/4 모델 |
| **Google Generative AI** | - | Gemini 통합 |
| **Tavily** | 0.7.11+ | 웹 검색 API |

#### 데이터베이스
| 기술 | 버전 | 용도 |
|------|------|------|
| **PostgreSQL** | 15+ | 주 데이터베이스 (pgvector 포함) |
| **AsyncPG** | 0.30.0+ | 비동기 PostgreSQL 드라이버 |
| **SQLAlchemy** | 2.0.43+ | ORM |
| **Alembic** | 1.13.0+ | 마이그레이션 |

#### 캐싱 & 큐
| 기술 | 버전 | 용도 |
|------|------|------|
| **Redis** | 6.4.0+ | 캐싱 및 pub/sub |
| **Celery** | 5.4.0+ | 작업 큐 |
| **aioredis** | 2.0.1+ | 비동기 Redis |

#### 문서 처리
| 기술 | 버전 | 용도 |
|------|------|------|
| **PyPDF2** | 3.0.1+ | PDF 파싱 |
| **python-docx** | 1.1.2+ | Word 문서 |
| **openpyxl** | 3.1.5+ | Excel |
| **python-pptx** | 1.0.2+ | PowerPoint |
| **trafilatura** | 2.0.0+ | 웹 스크래핑 |
| **Playwright** | 1.55.0+ | 동적 페이지 렌더링 |
| **PyMuPDF** | 1.26.7+ | 고급 PDF 처리 |

#### 관찰 가능성
| 기술 | 버전 | 용도 |
|------|------|------|
| **Prometheus Client** | 0.20.0+ | 메트릭 |
| **OpenTelemetry** | 1.20.0+ | 분산 추적 |
| **Arize Phoenix** | 5.5.0+ | LLM 관찰 가능성 |

#### 데이터 처리
| 기술 | 버전 | 용도 |
|------|------|------|
| **Pandas** | 2.3.2+ | 데이터 분석 |
| **tiktoken** | 0.5.0+ | 토큰 카운팅 |

#### 유틸리티
| 기술 | 버전 | 용도 |
|------|------|------|
| **httpx** | 0.28.1+ | 비동기 HTTP 클라이언트 |
| **pydantic** | 2.11.7+ | 데이터 검증 |
| **python-jose** | - | JWT 처리 |
| **bcrypt** | 4.0.0+ | 비밀번호 해싱 |
| **boto3** | 1.35.0+ | AWS S3 통합 |

### 4.2 기술 스택 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│                    애플리케이션 계층                      │
├─────────────────────────────────────────────────────────┤
│  FastAPI (웹 프레임워크)                                 │
│  ├─ LangGraph (워크플로우 오케스트레이션)                │
│  ├─ CrewAI (멀티 에이전트)                               │
│  └─ LangChain (LLM 통합)                                 │
└─────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│  AI/LLM 계층  │ │  데이터 계층 │ │  도구 계층  │
├──────────────┤ ├────────────┤ ├────────────┤
│ OpenAI       │ │ PostgreSQL │ │ MCP Tools  │
│ Anthropic    │ │ + pgvector │ │ Playwright │
│ Google AI    │ │ Redis      │ │ Tavily     │
│ Tavily       │ │ S3/Local   │ │ Built-in   │
└──────────────┘ └────────────┘ └────────────┘
```

---

## 5. 아키텍처 패턴

### 5.1 계층형 아키텍처

```
┌─────────────────────────────────────────────┐
│          API 계층 (FastAPI)                  │
│  - 라우트                                    │
│  - 핸들러 (thin)                             │
│  - 요청/응답 모델                            │
├─────────────────────────────────────────────┤
│          서비스 계층                          │
│  - 비즈니스 로직                             │
│  - 채팅 서비스                               │
│  - 문서 서비스                               │
│  - 인증 서비스                               │
├─────────────────────────────────────────────┤
│       워크플로우 계층 (LangGraph)             │
│  - 멀티 에이전트 오케스트레이션              │
│  - 상태 관리                                 │
│  - 품질 검증                                 │
├─────────────────────────────────────────────┤
│         에이전트 계층 (CrewAI)                │
│  - 검색 에이전트                             │
│  - 분석 에이전트                             │
│  - 생성 에이전트                             │
├─────────────────────────────────────────────┤
│           데이터 계층                         │
│  - Repository 패턴                           │
│  - 데이터베이스 모델                         │
│  - 스마트 캐싱                               │
└─────────────────────────────────────────────┘
```

### 5.2 핵심 디자인 패턴

#### Strategy 패턴 (검색 오케스트레이터)
```python
# 검색 전략 선택
class SearchOrchestrator:
    def select_strategy(self, query_intent: str) -> SearchStrategy:
        if query_intent in ["research", "analysis"]:
            return IterativeSearchStrategy()
        return StandardSearchStrategy()
```

**전략 종류**:
- `IterativeSearchStrategy` - 품질 기반 반복 탐색
- `StandardSearchStrategy` - 폴백이 있는 기본 검색

#### Repository 패턴 (데이터베이스)
```python
# 데이터 액세스 추상화
class ChatRepository:
    async def get_conversation(self, conversation_id: str) -> Conversation
    async def save_message(self, message: Message) -> None
    async def get_messages(self, conversation_id: str) -> List[Message]
```

**Repository 종류**:
- `ChatRepository` - 채팅 데이터 액세스
- `QueryRepository` - 쿼리 히스토리
- `AnalyticsRepository` - 분석 데이터

#### Factory 패턴 (LLM)
```python
# LLM 인스턴스 생성
def create_llm(
    model: str,
    temperature: float = 0.1,
    provider: str = None
) -> BaseLanguageModel:
    # 제공자 자동 감지 또는 지정된 제공자 사용
    return configured_llm_instance
```

#### Dependency Injection
```python
# 의존성 주입을 통한 느슨한 결합
class SearchOrchestrator:
    def __init__(
        self,
        tool_selector: ToolSelector,
        event_handler: EventHandler,
        agents: List[BaseAgent]
    ):
        self.tool_selector = tool_selector
        self.event_handler = event_handler
        self.agents = agents
```

#### Null Object 패턴
```python
# 성능을 위한 No-op 이벤트 핸들러
class NullEventHandler(EventHandler):
    async def on_node_start(self, node: str) -> None:
        pass  # No-op
```

#### Observer 패턴 (이벤트)
```python
# 워크플로우 라이프사이클 이벤트
class WorkflowEventHandler:
    async def on_workflow_start(self, state: AgentState) -> None
    async def on_node_start(self, node: str) -> None
    async def on_node_end(self, node: str, result: Any) -> None
    async def on_workflow_end(self, state: AgentState) -> None
```

**이벤트 구독자**:
- SSE/WebSocket 스트리밍 콜백
- 프로메테우스 메트릭 수집
- 로깅 및 추적

#### Builder 패턴 (워크플로우)
```python
# 워크플로우 구성을 위한 Fluent API
workflow = (
    WorkflowBuilder()
    .add_node("classifier", query_classifier)
    .add_node("search", search_orchestrator)
    .add_edge("classifier", "search")
    .add_conditional_edges("search", should_continue)
    .build()
)
```

#### Singleton 패턴
```python
# 전역 인스턴스
multi_agent_workflow = MultiAgentWorkflow()  # 전역 워크플로우 인스턴스
db_manager = DatabaseManager()               # 데이터베이스 연결 관리자
cache_manager = CacheManager()               # 캐시 관리자
skill_manager = SkillManager()               # 스킬 레지스트리
```

### 5.3 아키텍처 원칙

1. **관심사의 분리 (Separation of Concerns)**
   - 각 계층은 명확한 책임을 가짐
   - API는 HTTP 처리만, 비즈니스 로직은 서비스 계층에

2. **의존성 역전 (Dependency Inversion)**
   - 추상화에 의존, 구체적 구현에 의존하지 않음
   - 인터페이스를 통한 느슨한 결합

3. **단일 책임 원칙 (Single Responsibility)**
   - 각 클래스/모듈은 하나의 변경 이유만 가짐
   - 에이전트는 특정 작업에 전문화

4. **개방-폐쇄 원칙 (Open-Closed)**
   - 확장에는 열려있고 수정에는 닫혀있음
   - 스킬 및 도구 시스템을 통한 플러그인 아키텍처

---

## 6. 주요 기능

### 6.1 지능형 검색

#### 검색 유형
1. **지식 검색 (Knowledge Search)**
   - 내부 지식 베이스 쿼리
   - pgvector 기반 시맨틱 검색
   - 전체 텍스트 검색 (FTS) 폴백

2. **실시간 검색 (Realtime Search)**
   - Tavily API를 통한 웹 검색
   - 다중 검색 엔진 지원
   - 결과 품질 스코어링

3. **URL 분석 (URL Analysis)**
   - 직접 콘텐츠 추출 (정적)
   - Playwright를 통한 동적 렌더링
   - 구조화된 데이터 추출

4. **다중 쿼리 검색 (Multi-Query Search)**
   - LLM 기반 쿼리 확장
   - 병렬 검색 실행
   - 결과 통합 및 중복 제거

5. **딥 리서치 (Deep Research)**
   - **4단계 프로세스** (15-30분)
     1. 초기 검색 및 개요 구축
     2. 세부 정보 수집 (30-50+ 소스)
     3. 갭 분석 및 추가 검색
     4. 종합 및 리포트 생성
   - 비용 최적화 토큰 예산
   - 소스 품질 스코어링

6. **하이퍼 딥 리서치 (Hyper Deep Research)**
   - **8단계 체계적 프로세스** (30-60분)
     1. 주제 분석 - 범위 및 차원 이해
     2. 연구 계획 - 쿼리 생성 전략
     3. 초기 수집 - 광범위한 정보 수집 (50+ 소스)
     4. 갭 분석 - 누락된 정보 식별
     5. 심층 분석 - 갭에 대한 타겟 탐색
     6. 품질 평가 - 편향 감지, 사실 확인
     7. 종합 - 시맨틱 클러스터링 및 인사이트
     8. 리포트 생성 - 포괄적인 마크다운 리포트
   - 200+ 소스 처리
   - 편향 감지 및 다중 소스 사실 확인

7. **반복 웹 탐색기 (Iterative Web Explorer)**
   - 품질 기반 반복 탐색
   - 3차원 품질 평가:
     - 완전성 (40%)
     - 신뢰성 (30%)
     - 다양성 (30%)
   - 도메인 잠금으로 무한 루프 방지
   - 구성 가능한 도메인당 최대 페이지 수

### 6.2 고급 분석

#### 분석 유형
1. **데이터 분석 (Data Analysis)**
   - 통계 분석
   - 패턴 발견
   - 트렌드 식별
   - 시각화 생성

2. **비교 분석 (Comparative Analysis)**
   - 다중 소스 비교
   - 차이점 및 공통점 식별
   - 장단점 평가

3. **웹 콘텐츠 분석 (Web Content Analysis)**
   - 페이지 콘텐츠 추출
   - 구조 분석
   - 주요 정보 식별

### 6.3 콘텐츠 생성

#### 생성 기능
1. **이미지 생성 (Image Generation)**
   - OpenAI DALL-E 3 통합
   - 프롬프트 최적화
   - 다양한 크기 및 품질 옵션

2. **API 통합 (API Integration)**
   - 날씨 데이터 (OpenWeatherMap)
   - 환율 (Exchange Rate API)
   - 주식 데이터 (Yahoo Finance)

3. **문서 처리 (Document Processing)**
   - PDF 파싱 및 분석
   - DOCX, XLSX, PPTX 지원
   - 텍스트 추출 및 구조 분석

4. **작업 생성 (Task Creation)**
   - 자동 프로젝트 계획
   - 하위 작업 분해
   - 우선순위 지정

### 6.4 채팅 시스템

#### 기능
- ✅ **다중 턴 대화**: 대화 히스토리와 함께
- ✅ **컨텍스트 인식 응답**: 이전 메시지를 기반으로
- ✅ **스트리밍**: SSE + WebSocket
- ✅ **유사도 기반 검색**: 과거 대화에서 관련 메시지 찾기
- ✅ **크로스 대화 검색**: 모든 대화에서 검색
- ✅ **템플릿 시스템**: 사전 정의된 시스템 프롬프트
- ✅ **대화 분석**: 통계 및 인사이트
- ✅ **비용 추적**: 대화당 토큰 및 비용
- ✅ **제목 생성**: 자동 대화 제목 생성

#### 채팅 모드
1. **표준 채팅**: 직접 LLM 상호작용
2. **워크플로우 통합 채팅**: LangGraph 워크플로우를 통한 처리
3. **RAG (Retrieval-Augmented Generation)**: 문서 기반 응답
4. **유사도 기반 채팅**: 과거 대화에서 학습

### 6.5 문서 관리

#### 기능
- ✅ **파일 업로드**: PDF, DOCX, TXT, MD, CSV, XLSX, PPTX
- ✅ **자동 청킹**: 의미 기반 텍스트 분할
- ✅ **벡터 임베딩**: pgvector를 사용한 시맨틱 검색
- ✅ **지식 그래프 추출**: 엔티티 및 관계
- ✅ **전체 텍스트 검색** (FTS)
- ✅ **스토리지 추상화**: S3, 로컬, rustfs

#### 처리 파이프라인
```
업로드 → 파싱 → 청킹 → 임베딩 → 인덱싱 → 검색 가능
```

### 6.6 인증 & 권한

#### 인증 메커니즘
1. **JWT 기반 인증**
   - 액세스 토큰 (15분)
   - 리프레시 토큰 (7일)
   - 자동 토큰 로테이션

2. **OAuth2 (Google)**
   - Google 계정으로 로그인
   - 프로필 정보 동기화
   - 이메일 검증

3. **API 키 관리**
   - 스코프 기반 권한
   - 요청 제한
   - 만료 관리

4. **역할 기반 접근 제어 (RBAC)**
   - 사용자 역할 (user, admin, enterprise)
   - 조직 기반 권한
   - 리소스 레벨 권한

#### 보안 기능
- ✅ **비밀번호 해싱**: bcrypt
- ✅ **토큰 블랙리스트**: 로그아웃 처리
- ✅ **요청 제한**: API 키당 제한
- ✅ **CSRF 보호**: 쿠키 기반 인증
- ✅ **CORS 설정**: 구성 가능한 오리진

### 6.7 멀티모달 처리

#### 파이프라인
1. **ImagePipeline** - 이미지 분석
   - 비전 모델 (GPT-4 Vision, Claude 3 Vision, Gemini Vision)
   - OCR 및 텍스트 추출
   - 객체 감지

2. **AudioPipeline** - 오디오 트랜스크립션
   - Whisper API 통합
   - 다국어 지원
   - 타임스탬프 생성

3. **DocumentPipeline** - 문서 처리
   - 다양한 형식 지원
   - 구조 분석
   - 메타데이터 추출

4. **MultimodalPipeline** - 통합 처리
   - 다중 입력 유형 처리
   - 크로스 모달 분석
   - 통합 결과 생성

#### 비전 모델 선택
```python
def select_vision_model(image_type: str, task_complexity: str):
    if task_complexity == "high":
        return "claude-3-opus"       # 복잡한 추론
    elif image_type == "chart":
        return "gpt-4-vision"        # 차트 및 OCR
    else:
        return "auto"                # 비용 최적화
```

---

## 7. 워크플로우 시스템

### 7.1 그래프 아키텍처

**파일**: `neos/workflow/graph.py` (809 lines)

**핵심 클래스**: `MultiAgentWorkflow`

### 7.2 상태 관리

**AgentState** (TypedDict):
```python
class AgentState(TypedDict):
    # 기본 정보
    user_id: str
    session_id: str
    original_query: str

    # 쿼리 분석
    query_intent: str
    query_embedding: List[float]
    detected_language: str

    # 대화 컨텍스트
    chat_history: List[Message]
    conversation_context: str

    # 분류 및 선택
    query_classification: Dict
    required_agents: List[str]
    selected_skills: List[str]
    selected_tools: List[str]

    # 결과
    search_results: List[Dict]
    analysis_results: List[Dict]
    generation_results: List[Dict]
    search_synthesis: str  # LLM 생성 요약

    # 통합 및 품질
    integrated_results: Dict
    quality_score: float

    # 최종 응답
    final_response: str
    response_metadata: Dict

    # 실행 정보
    execution_steps: List[str]
    errors: List[str]
    retry_count: int

    # 성능 메트릭
    total_tokens: int
    api_calls: int
    execution_time: float
```

### 7.3 워크플로우 실행 흐름

```
START
  │
  ▼
[Should process context?]
  ├─ Yes → conversation_context_processor
  │         │
  │         └─→ query_classifier
  │
  └─ No  → query_classifier
             │
             ▼
       skill_tool_selector
             │
             ▼
       search_orchestrator
             │
             ▼
       analysis_orchestrator
             │
             ▼
       generation_orchestrator
             │
             ▼
       result_integrator
             │
             ▼
       quality_validator
             │
             ▼
       [Should regenerate?]
          ├─ Yes → (재시도 횟수 < 2) → search_orchestrator로 돌아가기
          │
          └─ No  → response_generator
                      │
                      ▼
                    END
```

### 7.4 체크포인팅 (엔터프라이즈 기능)

**PostgreSQLCheckpointer**:

#### 주요 특징
- ✅ **분산 상태 관리**: PostgreSQL에 워크플로우 상태 지속
- ✅ **수평적 확장성**: 여러 워커가 동일한 워크플로우 처리 가능
- ✅ **세션 복구**: 서버 재시작 후 워크플로우 재개
- ✅ **스레드 기반 격리**: 각 세션은 고유한 thread_id 보유
- ✅ **트랜잭션 안전성**: ACID 준수
- ✅ **효율적인 정리**: 만료된 체크포인트 백그라운드 정리

#### 구현
```python
class PostgreSQLCheckpointer(BaseCheckpointSaver):
    """
    LangGraph 체크포인트 인터페이스 구현
    - JSONB로 PostgreSQL에 체크포인트 저장
    - 스레드 기반 격리
    - 만료된 체크포인트 자동 정리
    """

    async def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata
    ) -> RunnableConfig:
        """체크포인트 저장"""

    async def get(
        self,
        config: RunnableConfig
    ) -> Optional[Checkpoint]:
        """체크포인트 검색"""
```

#### 데이터베이스 스키마
```sql
CREATE TABLE checkpoints (
    thread_id VARCHAR(255) PRIMARY KEY,
    checkpoint_ns VARCHAR(255),
    checkpoint JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

CREATE INDEX idx_checkpoints_expires
ON checkpoints(expires_at)
WHERE expires_at IS NOT NULL;
```

### 7.5 스마트 캐싱 (pgvector)

#### 2단계 캐싱

**Tier 1: 스마트 캐시 (PostgreSQL + pgvector)**
- 시맨틱 유사도 검색 (코사인 거리)
- 쿼리 의도 기반 동적 TTL
- 쿼리 분류 메타데이터
- 캐시 통계 및 분석

**TTL 전략**:
```python
def calculate_ttl(query_intent: str, quality_score: float, complexity: float):
    """
    동적 TTL 계산

    기본 TTL (쿼리 의도별):
    - 실시간 정보: 15분 - 1시간
    - 금융 데이터: 10분 - 1시간
    - 분석: 7일 - 90일
    - 연구: 30일 - 180일
    - 생성: 90일 - 365일

    조정 요소:
    - 품질 승수 = 0.5 + (quality_score * 1.5)
    - 복잡도 승수 = 1.0 + (complexity_score * 1.5)

    최종 TTL = base_ttl * quality_multiplier * complexity_multiplier
    """
```

**Tier 2: Redis 캐시 (폴백)**
- 빠른 정확한 매칭 캐싱
- 고정 TTL (기본 2시간)
- 메모리 효율적

#### 캐시 히트 프로세스
```
쿼리 수신
    │
    ▼
[Redis에서 정확한 매칭 확인]
    │
    ├─ 히트 → 즉시 반환
    │
    └─ 미스 → [pgvector에서 시맨틱 검색]
                │
                ├─ 유사도 > 0.95 → 반환
                │
                └─ 미스 → 워크플로우 실행
                            │
                            └─ 결과 캐시 (Redis + PostgreSQL)
```

### 7.6 오케스트레이터

#### SearchOrchestrator (Strategy 패턴)
```python
class SearchOrchestrator:
    """
    검색 에이전트 조율

    기능:
    - 전략 선택 (Iterative vs Standard)
    - 대화 컨텍스트 개선
    - 폴백 메커니즘
    - 도구 선택기 통합
    """

    async def execute(self, state: AgentState) -> AgentState:
        # 1. 전략 선택
        strategy = self.select_strategy(state["query_intent"])

        # 2. 대화 컨텍스트로 쿼리 개선
        if state.get("conversation_context"):
            enhanced_query = self.enhance_with_context(
                state["original_query"],
                state["conversation_context"]
            )

        # 3. 검색 실행
        results = await strategy.search(enhanced_query, state)

        # 4. 실패 시 폴백
        if not results:
            results = await StandardSearchStrategy().search(
                state["original_query"],
                state
            )

        return {**state, "search_results": results}
```

#### AnalysisOrchestrator
```python
class AnalysisOrchestrator:
    """
    분석 에이전트 조율

    기능:
    - 병렬 분석 실행
    - 결과 통합
    - 오류 처리
    """

    async def execute(self, state: AgentState) -> AgentState:
        # 필요한 분석 에이전트 결정
        required_analyses = self.determine_analyses(state)

        # 병렬 실행
        tasks = [
            agent.execute(state["search_results"])
            for agent in required_analyses
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 오류 필터링 및 통합
        valid_results = [r for r in results if not isinstance(r, Exception)]

        return {**state, "analysis_results": valid_results}
```

#### GenerationOrchestrator
```python
class GenerationOrchestrator:
    """
    생성 에이전트 조율

    기능:
    - 이미지 생성
    - API 호출
    - 파일 처리
    """

    async def execute(self, state: AgentState) -> AgentState:
        generation_results = []

        # 이미지 생성이 필요한지 확인
        if self.requires_image_generation(state):
            image_result = await self.image_agent.execute(state)
            generation_results.append(image_result)

        # API 호출이 필요한지 확인
        if self.requires_api_call(state):
            api_result = await self.api_agent.execute(state)
            generation_results.append(api_result)

        return {**state, "generation_results": generation_results}
```

### 7.7 품질 검증

```python
async def quality_validator(state: AgentState) -> AgentState:
    """
    결과 품질 검증 및 피드백 제공

    품질 차원:
    - 완전성 (40%): 쿼리의 모든 측면이 다루어졌는가?
    - 정확성 (30%): 정보가 정확하고 최신인가?
    - 관련성 (20%): 결과가 쿼리와 관련이 있는가?
    - 다양성 (10%): 다양한 관점이 포함되었는가?
    """

    # LLM을 사용한 품질 평가
    quality_prompt = f"""
    다음 결과의 품질을 0-1 스케일로 평가하세요:

    쿼리: {state["original_query"]}
    결과: {state["integrated_results"]}

    평가 기준:
    - 완전성 (40%)
    - 정확성 (30%)
    - 관련성 (20%)
    - 다양성 (10%)

    JSON 형식으로 응답: {{"score": 0.85, "feedback": "..."}}
    """

    response = await llm.ainvoke(quality_prompt)
    quality_data = json.loads(response.content)

    return {
        **state,
        "quality_score": quality_data["score"],
        "quality_feedback": quality_data["feedback"]
    }

def should_regenerate(state: AgentState) -> str:
    """
    재생성 필요 여부 결정
    """
    if state["quality_score"] < 0.4 and state["retry_count"] < 2:
        return "regenerate"
    return "finish"
```

---

## 8. API 설계

### 8.1 API 구조

**Base URL**: `/api/v1`

### 8.2 주요 엔드포인트

#### 쿼리 API
```
POST   /api/v1/query              # 쿼리 실행
GET    /api/v1/query/stream       # SSE 스트리밍
GET    /api/v1/health             # 헬스 체크
GET    /api/v1/trending           # 트렌드 쿼리
```

#### 채팅 API
```
POST   /api/v1/chat/conversations                    # 대화 생성
GET    /api/v1/chat/conversations                    # 대화 목록
GET    /api/v1/chat/conversations/{id}               # 대화 조회
PUT    /api/v1/chat/conversations/{id}               # 대화 업데이트
DELETE /api/v1/chat/conversations/{id}               # 대화 삭제
POST   /api/v1/chat/conversations/{id}/messages      # 메시지 전송
GET    /api/v1/chat/conversations/{id}/messages      # 메시지 조회
POST   /api/v1/chat/conversations/{id}/messages/stream  # 스트리밍 메시지
POST   /api/v1/chat/conversations/{id}/messages/regenerate  # 재생성
WS     /api/v1/chat/ws/{conversation_id}             # WebSocket
```

#### 딥 리서치 API
```
POST /api/v1/deep-research/start                     # 연구 시작
GET  /api/v1/deep-research/{report_id}/stream        # 진행 상황 스트리밍
GET  /api/v1/deep-research/{report_id}               # 리포트 조회
GET  /api/v1/conversations/{id}/deep-research        # 대화별 연구
```

#### 문서 API
```
POST   /api/v1/documents/upload       # 문서 업로드
GET    /api/v1/documents              # 문서 목록
GET    /api/v1/documents/{id}         # 문서 조회
DELETE /api/v1/documents/{id}         # 문서 삭제
POST   /api/v1/documents/search       # 문서 검색
```

#### 스킬 API
```
GET    /api/v1/skills                         # 스킬 목록
GET    /api/v1/skills/{skill_name}            # 스킬 조회
POST   /api/v1/skills/refresh                 # 스킬 새로고침
POST   /api/v1/skills/{skill_name}/execute    # 스킬 실행
GET    /api/v1/skills/{skill_name}/dependencies  # 의존성 확인
```

#### 인증 API
```
POST /api/v1/auth/register           # 사용자 등록
POST /api/v1/auth/login              # 로그인
POST /api/v1/auth/logout             # 로그아웃
POST /api/v1/auth/refresh            # 토큰 갱신
GET  /api/v1/auth/me                 # 현재 사용자
POST /api/v1/auth/google             # Google OAuth2
```

#### 멀티모달 API
```
POST /api/v1/multimodal/image        # 이미지 분석
POST /api/v1/multimodal/audio        # 오디오 트랜스크립션
POST /api/v1/multimodal/document     # 문서 처리
POST /api/v1/multimodal/combined     # 멀티모달 처리
```

### 8.3 요청/응답 모델

**Pydantic 모델 예시**:

```python
# 요청 모델
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    language: Optional[str] = "ko"
    options: Optional[Dict] = None

# 응답 모델
class QueryResponse(BaseModel):
    query_id: str
    original_query: str
    final_response: str
    sources: List[Source]
    metadata: ResponseMetadata
    execution_time: float

class ResponseMetadata(BaseModel):
    query_intent: str
    agents_used: List[str]
    total_tokens: int
    quality_score: float
```

### 8.4 미들웨어

**전역 미들웨어**:

1. **CORS 미들웨어**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 구성 가능
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

2. **GZip 압축**
```python
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000  # 1KB 이상만 압축
)
```

3. **요청 로깅**
```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    logger.info(f"Request {request_id}: {request.method} {request.url}")

    response = await call_next(request)

    logger.info(f"Response {request_id}: {response.status_code}")
    return response
```

4. **Prometheus 메트릭**
```python
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time
    http_request_duration.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code
    ).observe(duration)

    return response
```

### 8.5 예외 처리

**사용자 정의 예외**:
```python
class NEOSException(Exception):
    """베이스 예외 클래스"""
    pass

class QueryProcessingError(NEOSException):
    """쿼리 처리 오류"""
    pass

class AuthenticationError(NEOSException):
    """인증 오류"""
    pass

class ResourceNotFoundError(NEOSException):
    """리소스 없음"""
    pass
```

**전역 예외 핸들러**:
```python
@app.exception_handler(NEOSException)
async def neos_exception_handler(request: Request, exc: NEOSException):
    return JSONResponse(
        status_code=400,
        content={
            "error": exc.__class__.__name__,
            "message": str(exc),
            "request_id": request.state.request_id
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    logger.error(f"Internal error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred",
            "request_id": request.state.request_id
        }
    )
```

---

## 9. 데이터베이스 스키마

### 9.1 스키마 설계

#### 벡터 검색
- **pgvector 확장**: 임베딩을 위한 벡터 지원
- **IVFFlat 인덱스**: 빠른 유사도 검색
- **1536차원 벡터**: OpenAI text-embedding-3-small

### 9.2 주요 테이블

#### 사용자 & 인증
```sql
-- 사용자
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    organization_id UUID REFERENCES organizations(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- API 키
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    scopes TEXT[] DEFAULT '{}',
    rate_limit INTEGER DEFAULT 1000,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

-- 리프레시 토큰
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    token_hash VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- OAuth 계정
CREATE TABLE user_oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    provider VARCHAR(50) NOT NULL,
    provider_account_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(provider, provider_account_id)
);

-- 조직
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    subscription_tier VARCHAR(50) DEFAULT 'free',
    usage_quota JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 쿼리 & 검색
```sql
-- 쿼리 히스토리
CREATE TABLE query_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    original_query TEXT NOT NULL,
    query_vector VECTOR(1536),
    query_intent VARCHAR(100),
    detected_language VARCHAR(10),
    final_response TEXT,
    execution_time FLOAT,
    total_tokens INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 관련 쿼리
CREATE TABLE related_queries (
    source_query_id UUID REFERENCES query_history(id),
    related_query_id UUID REFERENCES query_history(id),
    similarity_score FLOAT,
    PRIMARY KEY (source_query_id, related_query_id)
);

-- 트렌드 쿼리
CREATE TABLE trending_queries (
    query_text TEXT PRIMARY KEY,
    query_vector VECTOR(1536),
    search_count INTEGER DEFAULT 1,
    last_searched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 검색 세션
CREATE TABLE search_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    query_sequence JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 스마트 캐시
```sql
-- 쿼리 캐시
CREATE TABLE query_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    query_hash VARCHAR(64) UNIQUE NOT NULL,
    query_vector VECTOR(1536),
    query_intent VARCHAR(100),
    complexity_score FLOAT,
    response_data JSONB NOT NULL,
    ttl_seconds INTEGER,
    expires_at TIMESTAMP,
    hit_count INTEGER DEFAULT 0,
    user_id UUID REFERENCES users(user_id),
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed_at TIMESTAMP DEFAULT NOW()
);

-- 벡터 인덱스
CREATE INDEX idx_query_cache_vector
ON query_cache
USING ivfflat (query_vector vector_cosine_ops)
WITH (lists = 100);

-- 캐시 통계
CREATE TABLE cache_statistics (
    time_bucket TIMESTAMP NOT NULL,
    query_intent VARCHAR(100),
    total_requests INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    semantic_hits INTEGER DEFAULT 0,
    avg_similarity_score FLOAT,
    PRIMARY KEY (time_bucket, query_intent)
);
```

#### 문서
```sql
-- 문서
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    filename VARCHAR(255) NOT NULL,
    storage_key VARCHAR(500) NOT NULL,
    file_size BIGINT,
    mime_type VARCHAR(100),
    processing_status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 문서 청크
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 벡터 인덱스
CREATE INDEX idx_document_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 지식 그래프
CREATE TABLE knowledge_graphs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    entity_type VARCHAR(100),
    entity_name VARCHAR(255),
    relations JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 채팅 시스템
```sql
-- 대화
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(user_id),
    model_name VARCHAR(100),
    title VARCHAR(500),
    system_prompt TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 메시지
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- user, assistant, system
    content TEXT NOT NULL,
    tool_calls JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 메시지 임베딩
CREATE TABLE message_embeddings (
    message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    embedding VECTOR(1536),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 벡터 인덱스
CREATE INDEX idx_message_embeddings_vector
ON message_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 대화 비용
CREATE TABLE conversation_costs (
    conversation_id UUID PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    total_tokens INTEGER DEFAULT 0,
    total_cost DECIMAL(10, 6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 웹 프론트엔드 통합
```sql
-- 투표
CREATE TABLE Vote_v2 (
    chatId TEXT NOT NULL,
    messageId TEXT NOT NULL,
    isUpvoted BOOLEAN NOT NULL,
    PRIMARY KEY (chatId, messageId)
);

-- 문서
CREATE TABLE Document (
    id TEXT NOT NULL,
    createdAt TIMESTAMP NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    kind VARCHAR(50) DEFAULT 'text',
    userId TEXT,
    PRIMARY KEY (id, createdAt)
);

-- 제안
CREATE TABLE Suggestion (
    id TEXT PRIMARY KEY,
    documentId TEXT NOT NULL,
    documentCreatedAt TIMESTAMP NOT NULL,
    originalText TEXT NOT NULL,
    suggestedText TEXT NOT NULL,
    description TEXT,
    isResolved BOOLEAN DEFAULT FALSE,
    userId TEXT NOT NULL,
    createdAt TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (documentId, documentCreatedAt)
        REFERENCES Document(id, createdAt)
);
```

### 9.3 인덱스

#### 성능 인덱스
```sql
-- B-tree 인덱스 (외래 키)
CREATE INDEX idx_query_history_user_id ON query_history(user_id);
CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);

-- 해시 인덱스 (쿼리 해시)
CREATE INDEX idx_query_cache_hash ON query_cache USING hash(query_hash);

-- 복합 인덱스
CREATE INDEX idx_cache_statistics_time_intent
ON cache_statistics(time_bucket, query_intent);

-- GIN 인덱스 (JSONB)
CREATE INDEX idx_documents_metadata ON documents USING gin(metadata);
CREATE INDEX idx_knowledge_graphs_relations
ON knowledge_graphs USING gin(relations);
```

#### 벡터 인덱스 (IVFFlat)
```sql
-- IVFFlat: 근사 최근접 이웃 검색을 위한 인덱스
-- lists 파라미터: 클러스터 수 (일반적으로 행 수 / 1000)

CREATE INDEX idx_query_cache_vector
ON query_cache
USING ivfflat (query_vector vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX idx_document_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX idx_message_embeddings_vector
ON message_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

## 10. AI/에이전트 통합

### 10.1 LLM 통합

#### LLM Factory 패턴
```python
def create_llm(
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    provider: str = None
) -> BaseLanguageModel:
    """
    LLM 인스턴스 생성

    Args:
        model: 모델 이름 (예: "gpt-4", "claude-3-opus", "gemini-pro")
        temperature: 0-2 범위의 온도
        max_tokens: 최대 토큰 수
        provider: 명시적 제공자 (없으면 자동 감지)

    Returns:
        구성된 LLM 인스턴스
    """

    # 제공자 자동 감지
    if not provider:
        if model.startswith("gpt"):
            provider = "openai"
        elif model.startswith("claude"):
            provider = "anthropic"
        elif model.startswith("gemini"):
            provider = "google"

    # LLM 인스턴스 생성
    if provider == "openai":
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    elif provider == "anthropic":
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    elif provider == "google":
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
```

#### 지원 LLM 제공자
| 제공자 | 모델 | 용도 |
|--------|------|------|
| **OpenAI** | GPT-4, GPT-4 Turbo, GPT-4o | 일반 목적, 비전, 임베딩 |
| **Anthropic** | Claude 3 Opus/Sonnet/Haiku, Claude 4.5 | 복잡한 추론, 긴 컨텍스트 |
| **Google** | Gemini Pro/Flash | 비용 최적화, 빠른 응답 |

#### LLM 래퍼 (추적)
```python
def create_tracked_llm(
    model: str,
    user_id: str,
    session_id: str,
    **kwargs
) -> BaseLanguageModel:
    """
    추적 기능이 있는 LLM 래퍼

    래핑 기능:
    - 토큰 카운팅
    - 비용 계산
    - 데이터셋 수집
    - 성능 메트릭
    """

    base_llm = create_llm(model, **kwargs)

    # 콜백 추가
    callbacks = [
        TokenCountingCallback(),
        CostCalculationCallback(),
        DatasetCollectionCallback(user_id, session_id),
        PerformanceMetricsCallback()
    ]

    return base_llm.with_config({"callbacks": callbacks})
```

### 10.2 에이전트 실행 패턴

#### 비동기 실행
```python
class BaseAgent(ABC):
    async def execute(self, query: str, context: Dict) -> Dict:
        """
        에이전트 비동기 실행

        프로세스:
        1. 입력 검증
        2. CrewAI 작업 생성
        3. 스레드 풀에서 crew 실행 (블로킹 방지)
        4. 출력 포맷팅
        5. 표준화된 결과 반환
        """

        # 1. 검증
        self.validate_input(query, context)

        # 2. CrewAI 작업 생성
        task = Task(
            description=query,
            agent=self.agent,
            expected_output="구조화된 결과"
        )

        crew = Crew(
            agents=[self.agent],
            tasks=[task],
            process=Process.sequential
        )

        # 3. 비동기 실행 (블로킹 작업을 스레드 풀로 오프로드)
        result = await asyncio.to_thread(crew.kickoff)

        # 4. 포맷팅
        formatted_result = self.format_output(result)

        # 5. 반환
        return {
            "agent_name": self.__class__.__name__,
            "result": formatted_result,
            "metadata": {
                "execution_time": ...,
                "tokens_used": ...,
            }
        }
```

#### 타임아웃 관리
```python
class AgentExecutor:
    async def execute_with_timeout(
        self,
        agent: BaseAgent,
        query: str,
        context: Dict,
        timeout: int = 300  # 5분
    ) -> Dict:
        """타임아웃이 있는 에이전트 실행"""

        try:
            result = await asyncio.wait_for(
                agent.execute(query, context),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Agent {agent.__class__.__name__} timed out")
            return {
                "error": "AgentTimeout",
                "message": f"Agent execution exceeded {timeout}s"
            }
```

### 10.3 도구 통합

#### MCP (Model Context Protocol)
```python
class MCPManager:
    """
    MCP 서버 및 도구 관리

    기능:
    - 동적 도구 발견
    - MCP 서버 라이프사이클 관리
    - 도구 실행
    - 오류 처리
    """

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict
    ) -> Dict:
        """도구 실행"""

        # 1. 도구 선택 (MCP vs 내장)
        tool = await self.select_tool(tool_name)

        # 2. 파라미터 검증
        validated_params = self.validate_params(tool, params)

        # 3. 타임아웃과 함께 실행
        try:
            result = await asyncio.wait_for(
                tool.execute(validated_params),
                timeout=self.tool_timeout
            )
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": str(e)}
```

#### 도구 실행
```python
async def execute_tool(tool_name: str, params: Dict):
    """
    도구 실행 워크플로우

    1. 도구 선택 (MCP vs 내장)
    2. 파라미터 검증
    3. 타임아웃과 함께 실행
    4. 오류 처리
    5. 구조화된 결과 반환
    """

    # 1. 선택
    if await mcp_manager.has_tool(tool_name):
        tool = await mcp_manager.get_tool(tool_name)
    else:
        tool = builtin_tools[tool_name]

    # 2. 검증
    try:
        validated_params = tool.validate_params(params)
    except ValidationError as e:
        return {"error": "InvalidParams", "details": str(e)}

    # 3. 실행
    try:
        result = await asyncio.wait_for(
            tool.execute(validated_params),
            timeout=60
        )
    except asyncio.TimeoutError:
        return {"error": "ToolTimeout"}
    except Exception as e:
        return {"error": "ExecutionError", "details": str(e)}

    # 4. 반환
    return {"success": True, "result": result}
```

### 10.4 임베딩

#### 벡터 임베딩 생성
```python
async def create_embedding(text: str) -> List[float]:
    """
    OpenAI text-embedding-3-small을 사용한 텍스트 임베딩 생성

    - 모델: text-embedding-3-small
    - 차원: 1536
    - 비용: $0.02 / 1M 토큰
    """

    client = AsyncOpenAI()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )

    return response.data[0].embedding
```

#### 시맨틱 검색
```python
async def semantic_search(
    query: str,
    table: str,
    limit: int = 10,
    similarity_threshold: float = 0.7
) -> List[Dict]:
    """
    pgvector를 사용한 시맨틱 검색

    Args:
        query: 검색 쿼리
        table: 검색할 테이블
        limit: 최대 결과 수
        similarity_threshold: 최소 유사도 (0-1)

    Returns:
        유사도 점수와 함께 결과 목록
    """

    # 1. 쿼리 임베딩 생성
    query_vector = await create_embedding(query)

    # 2. 벡터 유사도 검색
    sql = f"""
        SELECT *,
               1 - (embedding <=> :query_vector) AS similarity
        FROM {table}
        WHERE 1 - (embedding <=> :query_vector) > :threshold
        ORDER BY embedding <=> :query_vector
        LIMIT :limit
    """

    results = await db.fetch_all(
        sql,
        values={
            "query_vector": query_vector,
            "threshold": similarity_threshold,
            "limit": limit
        }
    )

    return results
```

---

## 11. 혁신적인 기술적 접근

### 11.1 하이퍼 딥 리서치 에이전트

#### 8단계 체계적 프로세스
```
1. 주제 분석 (Topic Analysis)
   - 범위 및 차원 이해
   - 핵심 질문 식별
   - 연구 목표 정의

2. 연구 계획 (Research Planning)
   - 쿼리 생성 전략
   - 소스 우선순위 지정
   - 타임라인 및 예산 설정

3. 초기 수집 (Initial Collection)
   - 광범위한 정보 수집 (50+ 소스)
   - 다양한 관점 탐색
   - 초기 인사이트 식별

4. 갭 분석 (Gap Analysis)
   - 누락된 정보 식별
   - 불일치 발견
   - 추가 연구 필요 영역 결정

5. 심층 분석 (Deep Dive)
   - 갭에 대한 타겟 탐색
   - 전문가 소스 검색
   - 세부 정보 수집

6. 품질 평가 (Quality Assessment)
   - 편향 감지
   - 다중 소스 사실 확인
   - 신뢰성 평가

7. 종합 (Synthesis)
   - 시맨틱 클러스터링
   - 인사이트 발견
   - 패턴 식별

8. 리포트 생성 (Report Generation)
   - 포괄적인 마크다운 리포트
   - 참조 및 인용
   - 시각화 및 차트
```

#### 주요 기능
- **비용 최적화**: 토큰 예산을 통한 비용 관리
- **소스 품질 스코어링**: 신뢰성 및 관련성 평가
- **편향 감지**: 다양한 관점 보장
- **사실 확인**: 다중 소스 검증
- **시맨틱 클러스터링**: 인사이트 발견을 위한 주제 그룹화
- **이벤트 로깅**: 재현성을 위한 상세 로그

### 11.2 동적 TTL을 가진 스마트 캐시

#### 혁신: 쿼리 의도 + 품질 기반 TTL 계산

```python
def calculate_dynamic_ttl(
    query_intent: str,
    quality_score: float,
    complexity_score: float
) -> int:
    """
    동적 TTL 계산

    공식:
    TTL = base_ttl * quality_multiplier * complexity_multiplier

    여기서:
      quality_multiplier = 0.5 + (quality_score * 1.5)
      complexity_multiplier = 1.0 + (complexity_score * 1.5)

    기본 TTL (쿼리 의도별):
      - realtime_info: 15분 - 1시간
      - financial_data: 10분 - 1시간
      - analysis: 7일 - 90일
      - research: 30일 - 180일
      - generation: 90일 - 365일
    """

    base_ttl_map = {
        "realtime_info": 900,      # 15분
        "financial_data": 600,     # 10분
        "analysis": 604800,        # 7일
        "research": 2592000,       # 30일
        "generation": 7776000      # 90일
    }

    base_ttl = base_ttl_map.get(query_intent, 3600)  # 기본 1시간

    quality_multiplier = 0.5 + (quality_score * 1.5)
    complexity_multiplier = 1.0 + (complexity_score * 1.5)

    ttl = int(base_ttl * quality_multiplier * complexity_multiplier)

    return ttl
```

#### 이점
- **고품질 연구 장기 캐싱**: 비싼 연구는 더 오래 캐시
- **복잡한 쿼리 장기 캐싱**: 계산 비용이 높은 쿼리 보존
- **실시간 데이터 단기 캐싱**: 신선도 보장
- **자동 캐시 최적화**: 수동 TTL 관리 불필요

### 11.3 대화 컨텍스트 처리

#### 다중 턴 컨텍스트 개선
```python
async def enhance_query_with_context(
    query: str,
    chat_history: List[Message]
) -> str:
    """
    대화 컨텍스트로 쿼리 개선

    예시:
      사용자: "iPhone 15에 대해 알려줘"
      어시스턴트: "iPhone 15는..."
      사용자: "그것의 가격은?"  # 모호한 참조

      개선된 쿼리: "iPhone 15의 가격"
    """

    # 최근 대화 히스토리 추출 (최대 20개 메시지)
    recent_history = chat_history[-20:]

    # 토큰 제한 (2000 토큰)
    context_text = ""
    for msg in reversed(recent_history):
        temp_context = f"{msg.role}: {msg.content}\n{context_text}"
        if count_tokens(temp_context) > 2000:
            break
        context_text = temp_context

    # LLM을 사용한 쿼리 개선
    prompt = f"""
    대화 히스토리:
    {context_text}

    현재 쿼리: {query}

    대화 컨텍스트를 고려하여 쿼리를 개선하세요.
    참조(대명사, "그것", "이것" 등)를 구체적인 엔티티로 대체하세요.
    주제 연속성을 유지하세요.

    개선된 쿼리만 반환하세요.
    """

    enhanced = await llm.ainvoke(prompt)
    return enhanced.content
```

#### 기능
- **참조 해결**: 대명사 및 지시어 해결
- **주제 연속성**: 턴 간 주제 유지
- **구성 가능한 히스토리 윈도우**: 최대 20개 메시지
- **토큰 제한 컨텍스트**: 2000 토큰

### 11.4 반복 웹 탐색기

#### 품질 기반 탐색
```python
async def iterative_explore(query: str, max_iterations: int = 3):
    """
    품질 기반 반복 웹 탐색

    프로세스:
    1. 초기 검색
    2. 품질 평가 (3차원)
    3. 품질 < 임계값이면, 더 많은 링크 추출
    4. 유망한 링크 팔로우
    5. 품질 재평가
    6. 만족할 때까지 또는 한계에 도달할 때까지 반복
    """

    results = []
    visited_domains = defaultdict(int)
    iteration = 0

    while iteration < max_iterations:
        # 1. 검색 실행
        search_results = await web_search(query)
        results.extend(search_results)

        # 2. 품질 평가
        quality = await evaluate_quality(results)

        if quality["score"] >= 0.7:
            break  # 품질 임계값 충족

        # 3. 더 많은 링크 추출
        links = extract_links(search_results)

        # 4. 도메인 잠금으로 필터링
        filtered_links = [
            link for link in links
            if visited_domains[get_domain(link)] < MAX_PAGES_PER_DOMAIN
        ]

        # 5. 유망한 링크 팔로우
        for link in filtered_links[:5]:  # 반복당 최대 5개
            content = await fetch_url(link)
            results.append(content)
            visited_domains[get_domain(link)] += 1

        iteration += 1

    return results

async def evaluate_quality(results: List[Dict]) -> Dict:
    """
    3차원 품질 평가

    차원:
    - 완전성 (40%): 쿼리의 모든 측면이 다루어졌는가?
    - 신뢰성 (30%): 소스가 신뢰할 수 있는가?
    - 다양성 (30%): 다양한 관점이 있는가?
    """

    prompt = f"""
    다음 검색 결과의 품질을 평가하세요:

    결과: {results}

    다음을 평가하세요:
    1. 완전성 (0-1): 모든 측면이 다루어졌는가?
    2. 신뢰성 (0-1): 소스가 신뢰할 수 있는가?
    3. 다양성 (0-1): 다양한 관점이 있는가?

    JSON 형식으로 응답:
    {{
        "completeness": 0.8,
        "credibility": 0.9,
        "diversity": 0.7,
        "score": 0.8,  # 가중 평균
        "feedback": "..."
    }}

    가중치: 완전성 40%, 신뢰성 30%, 다양성 30%
    """

    response = await llm.ainvoke(prompt)
    return json.loads(response.content)
```

#### 도메인 잠금
```python
MAX_PAGES_PER_DOMAIN = 5  # 도메인당 최대 페이지

visited_domains = defaultdict(int)

def should_visit(url: str) -> bool:
    """도메인 잠금으로 무한 루프 방지"""
    domain = get_domain(url)
    return visited_domains[domain] < MAX_PAGES_PER_DOMAIN
```

### 11.5 컨텍스트 최적화

**문제**: Claude Sonnet 4.5는 200K 컨텍스트를 가지지만 최적화가 필요

#### 해결책

1. **사고 블록 관리**
```python
def strip_thinking_blocks(content: str) -> str:
    """사고 블록 제거 또는 제한"""
    # <thinking>...</thinking> 블록 제거 또는 요약
    return re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL)
```

2. **토큰 카운팅**
```python
def count_tokens(text: str) -> int:
    """tiktoken 기반 정확한 토큰 카운팅"""
    encoding = tiktoken.encoding_for_model("gpt-4")
    return len(encoding.encode(text))
```

3. **오버플로우 감지**
```python
def check_context_overflow(messages: List[Message], max_tokens: int = 200000):
    """85% 용량에서 사전 예방적 경고"""
    total_tokens = sum(count_tokens(msg.content) for msg in messages)

    if total_tokens > max_tokens * 0.85:
        logger.warning(f"Context approaching limit: {total_tokens}/{max_tokens}")
        return True
    return False
```

4. **도구 결과 요약**
```python
async def summarize_tool_result(result: str, max_tokens: int = 500) -> str:
    """큰 도구 출력 압축"""
    if count_tokens(result) <= max_tokens:
        return result

    prompt = f"""
    다음 도구 결과를 {max_tokens} 토큰 이하로 요약하세요:

    {result}
    """

    summary = await llm.ainvoke(prompt)
    return summary.content
```

5. **메시지 압축**
```python
async def compress_old_messages(
    messages: List[Message],
    keep_recent: int = 10
) -> List[Message]:
    """30+ 턴에서 오래된 메시지 압축"""

    if len(messages) <= 30:
        return messages

    # 최근 메시지 유지
    recent = messages[-keep_recent:]
    old = messages[:-keep_recent]

    # 오래된 메시지 요약
    summary_prompt = f"""
    다음 대화 히스토리를 요약하세요:

    {old}
    """

    summary = await llm.ainvoke(summary_prompt)

    # 요약 + 최근 메시지 반환
    return [Message(role="system", content=summary.content)] + recent
```

6. **시맨틱 중복 제거**
```python
async def deduplicate_messages(messages: List[Message]) -> List[Message]:
    """92% 유사도로 중복 메시지 제거"""

    embeddings = [await create_embedding(msg.content) for msg in messages]

    unique_messages = []
    for i, msg in enumerate(messages):
        is_duplicate = False
        for j in range(len(unique_messages)):
            similarity = cosine_similarity(embeddings[i], embeddings[j])
            if similarity > 0.92:
                is_duplicate = True
                break

        if not is_duplicate:
            unique_messages.append(msg)

    return unique_messages
```

7. **워크플로우 토큰 예산**
```python
class WorkflowTokenBudget:
    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.used_tokens = 0

    def can_execute(self, estimated_tokens: int) -> bool:
        """예산 내에서 실행 가능한지 확인"""
        return self.used_tokens + estimated_tokens <= self.max_tokens

    def record_usage(self, tokens: int):
        """토큰 사용 기록"""
        self.used_tokens += tokens
```

### 11.6 LangGraph를 위한 PostgreSQL 체크포인터

**혁신**: 인메모리 MemorySaver를 PostgreSQL로 대체

#### 이점
- ✅ **수평적 확장**: 여러 워커가 동일한 상태에 액세스
- ✅ **영속성**: 서버 재시작 후에도 생존
- ✅ **복구**: 모든 체크포인트에서 워크플로우 재개
- ✅ **디버깅**: 데이터베이스에서 워크플로우 상태 검사
- ✅ **분석**: 워크플로우 실행 패턴 쿼리

#### 구현
```python
class PostgreSQLCheckpointer(BaseCheckpointSaver):
    """
    LangGraph 체크포인트 인터페이스 구현

    기능:
    - JSONB로 PostgreSQL에 체크포인트 저장
    - 스레드 기반 격리
    - 만료된 체크포인트 자동 정리
    - 트랜잭션 안전성
    """

    async def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata
    ) -> RunnableConfig:
        """
        체크포인트 저장

        1. thread_id 추출
        2. 체크포인트 직렬화 (JSONB)
        3. UPSERT (INSERT ... ON CONFLICT UPDATE)
        4. TTL 설정 (옵션)
        """
        thread_id = config["configurable"]["thread_id"]

        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT INTO checkpoints (thread_id, checkpoint, metadata)
                VALUES (:thread_id, :checkpoint, :metadata)
                ON CONFLICT (thread_id)
                DO UPDATE SET
                    checkpoint = EXCLUDED.checkpoint,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                {
                    "thread_id": thread_id,
                    "checkpoint": json.dumps(checkpoint),
                    "metadata": json.dumps(metadata)
                }
            )

        return config

    async def get(
        self,
        config: RunnableConfig
    ) -> Optional[Checkpoint]:
        """
        체크포인트 검색

        1. thread_id로 쿼리
        2. JSONB 역직렬화
        3. 만료 확인
        """
        thread_id = config["configurable"]["thread_id"]

        row = await self.db.fetch_one(
            """
            SELECT checkpoint, metadata
            FROM checkpoints
            WHERE thread_id = :thread_id
            AND (expires_at IS NULL OR expires_at > NOW())
            """,
            {"thread_id": thread_id}
        )

        if not row:
            return None

        return json.loads(row["checkpoint"])
```

### 11.7 스킬 자동 발견

**규약보다 설정 (Convention over Configuration)**:

```
skills/builtin/skill-name/
├── SKILL.md          # Frontmatter 메타데이터
├── skill.py          # 구현
└── requirements.txt  # 의존성 자동 설치
```

#### 자동 발견
```python
class SkillManager:
    async def discover_skills(self, directory: Path):
        """
        스킬 자동 발견

        1. SKILL.md를 위한 디렉토리 스캔
        2. 메타데이터를 위한 frontmatter 파싱
        3. 의존성 확인
        4. 사용 가능한 스킬 등록
        5. LLM 컨텍스트 자동 생성
        """

        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            # Frontmatter 파싱
            metadata = self.parse_frontmatter(skill_md)

            # 의존성 확인
            requirements = skill_dir / "requirements.txt"
            if requirements.exists():
                await self.check_dependencies(requirements)

            # 스킬 등록
            skill = self.load_skill(skill_dir, metadata)
            self.register(skill)
```

#### Frontmatter 예시
```markdown
---
name: arxiv
version: 1.0.0
description: ArXiv 논문 검색 및 분석
author: NEOS Team
tags: [research, academic, papers]
dependencies:
  - arxiv
  - PyPDF2
---

# ArXiv 스킬

이 스킬은 ArXiv에서 학술 논문을 검색하고 분석합니다...
```

### 11.8 멀티모달 비전 파이프라인

#### 자동 선택
```python
def select_vision_model(
    image_type: str,
    task_complexity: str,
    cost_priority: str = "balanced"
) -> str:
    """
    작업에 최적의 비전 모델 선택

    고려 사항:
    - 이미지 유형 (차트, 사진, 문서)
    - 작업 복잡도 (낮음, 중간, 높음)
    - 비용 우선순위 (비용, 균형, 품질)
    """

    if task_complexity == "high":
        return "claude-3-opus"       # 최고 품질
    elif image_type == "chart":
        return "gpt-4-vision"        # 차트 분석에 최적
    elif image_type == "document":
        return "gpt-4-vision"        # OCR에 우수
    elif cost_priority == "cost":
        return "gemini-pro-vision"   # 가장 저렴
    else:
        return "auto"                # 비용 최적화 선택
```

#### 비전 제공자
| 제공자 | 모델 | 강점 | 비용 |
|--------|------|------|------|
| **OpenAI** | GPT-4 Vision | 차트, OCR | 중간 |
| **Anthropic** | Claude 3 Vision | 복잡한 추론 | 높음 |
| **Google** | Gemini Vision | 비용 최적화 | 낮음 |

### 11.9 비용 추적 & 분석

#### 포괄적인 비용 추적
```python
class CostTracker:
    """
    대화 및 에이전트 전반에 걸친 비용 추적

    추적 항목:
    - 대화당 비용
    - 메시지당 토큰 사용
    - 에이전트당 비용 귀속
    - LLM 제공자 비용 계산
    - 비용 예산 및 알림
    """

    async def track_llm_call(
        self,
        conversation_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int
    ):
        """LLM 호출 비용 추적"""

        # 모델별 가격 (1M 토큰당)
        pricing = {
            "gpt-4": {"input": 30, "output": 60},
            "gpt-4-turbo": {"input": 10, "output": 30},
            "claude-3-opus": {"input": 15, "output": 75},
            "claude-3-sonnet": {"input": 3, "output": 15},
            "gemini-pro": {"input": 0.5, "output": 1.5}
        }

        model_pricing = pricing.get(model, {"input": 10, "output": 30})

        cost = (
            (input_tokens * model_pricing["input"]) +
            (output_tokens * model_pricing["output"])
        ) / 1_000_000

        # 데이터베이스에 저장
        await self.db.execute(
            """
            UPDATE conversation_costs
            SET total_tokens = total_tokens + :tokens,
                total_cost = total_cost + :cost,
                updated_at = NOW()
            WHERE conversation_id = :conversation_id
            """,
            {
                "conversation_id": conversation_id,
                "tokens": input_tokens + output_tokens,
                "cost": cost
            }
        )
```

#### 분석
```python
class CostAnalytics:
    async def get_conversation_analytics(
        self,
        user_id: str,
        period: str = "month"
    ) -> Dict:
        """
        사용자의 대화 분석

        반환:
        - 평균 메시지당 토큰
        - 대화당 총 비용
        - 가장 비싼 에이전트
        - 시간 경과에 따른 비용 추세
        """

        sql = """
        SELECT
            AVG(total_tokens / message_count) as avg_tokens_per_message,
            AVG(total_cost) as avg_cost_per_conversation,
            SUM(total_cost) as total_cost,
            COUNT(*) as conversation_count
        FROM conversation_costs
        JOIN conversations ON conversation_costs.conversation_id = conversations.id
        WHERE conversations.user_id = :user_id
        AND conversations.created_at >= NOW() - :period::INTERVAL
        """

        return await self.db.fetch_one(sql, {"user_id": user_id, "period": period})
```

### 11.10 관찰 가능성 & 모니터링

#### Prometheus 메트릭
```python
from prometheus_client import Counter, Histogram, Gauge

# HTTP 메트릭
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

# 에이전트 메트릭
agent_executions_total = Counter(
    'agent_executions_total',
    'Total agent executions',
    ['agent_name', 'status']
)

agent_execution_duration = Histogram(
    'agent_execution_duration_seconds',
    'Agent execution duration',
    ['agent_name']
)

# 워크플로우 메트릭
workflow_executions_total = Counter(
    'workflow_executions_total',
    'Total workflow executions',
    ['workflow_name', 'status']
)

workflow_node_duration = Histogram(
    'workflow_node_duration_seconds',
    'Workflow node execution duration',
    ['workflow_name', 'node_name']
)

# LLM 메트릭
llm_api_calls_total = Counter(
    'llm_api_calls_total',
    'Total LLM API calls',
    ['provider', 'model', 'status']
)

llm_tokens_used = Counter(
    'llm_tokens_used',
    'Total LLM tokens used',
    ['provider', 'model', 'type']  # type: input/output
)

# 캐시 메트릭
cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['cache_type']  # redis, pgvector
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses',
    ['cache_type']
)

# 데이터베이스 메트릭
db_connections_active = Gauge(
    'db_connections_active',
    'Active database connections'
)

db_query_duration = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['query_type']
)
```

#### OpenTelemetry 추적
```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# FastAPI 자동 계측
FastAPIInstrumentor.instrument_app(app)

# 사용자 정의 스팬
tracer = trace.get_tracer(__name__)

async def execute_workflow(query: str):
    with tracer.start_as_current_span("execute_workflow") as span:
        span.set_attribute("query", query)

        # 중첩 스팬
        with tracer.start_as_current_span("classify_query"):
            classification = await classify_query(query)

        with tracer.start_as_current_span("execute_agents"):
            results = await execute_agents(classification)

        return results
```

#### Arize Phoenix (LLM 관찰 가능성)
```python
import phoenix as px

# Phoenix 추적 시작
px.launch_app()

# LLM 호출 추적
@px.trace
async def llm_call(prompt: str):
    response = await llm.ainvoke(prompt)

    # 자동으로 추적됨:
    # - 프롬프트
    # - 응답
    # - 토큰 사용
    # - 레이턴시
    # - 모델 정보

    return response
```

---

## 12. 아키텍처 강점

### 12.1 엔터프라이즈 준비

1. **PostgreSQL 체크포인팅**
   - 수평적 확장성
   - 분산 상태 관리
   - 세션 영속성
   - 워크플로우 복구

2. **멀티 테넌시**
   - 조직 기반 격리
   - 사용자당 할당량
   - 역할 기반 접근 제어

3. **고가용성**
   - 연결 풀링
   - 자동 재시도
   - 서킷 브레이커
   - 그레이스풀 셧다운

### 12.2 지능형 캐싱

1. **pgvector 시맨틱 캐시**
   - 시맨틱 유사도 매칭
   - 동적 TTL 계산
   - 쿼리 의도 기반 최적화

2. **2단계 캐싱**
   - Redis (빠른 정확한 매칭)
   - PostgreSQL (시맨틱 검색)

3. **캐시 분석**
   - 히트율 추적
   - 성능 메트릭
   - 비용 절감 측정

### 12.3 포괄적인 AI 스택

1. **다중 LLM 제공자**
   - OpenAI (GPT-4, DALL-E)
   - Anthropic (Claude 3/4)
   - Google (Gemini)
   - 자동 폴백

2. **비전 모델**
   - GPT-4 Vision
   - Claude 3 Vision
   - Gemini Vision
   - 작업 기반 선택

3. **임베딩**
   - OpenAI text-embedding-3-small
   - 1536 차원
   - pgvector 통합

### 12.4 모듈형 설계

1. **명확한 관심사 분리**
   - API 계층 (HTTP 처리)
   - 서비스 계층 (비즈니스 로직)
   - 워크플로우 계층 (오케스트레이션)
   - 에이전트 계층 (AI 작업)
   - 데이터 계층 (영속성)

2. **플러그인 아키텍처**
   - 스킬 시스템
   - MCP 도구 통합
   - 사용자 정의 에이전트
   - 스토리지 백엔드

3. **확장 가능성**
   - 새 에이전트 추가 용이
   - 새 스킬 추가 용이
   - 새 도구 추가 용이
   - 새 LLM 제공자 추가 용이

### 12.5 강력한 인증

1. **다중 인증 방법**
   - JWT 토큰
   - OAuth2 (Google)
   - API 키
   - 세션 기반

2. **보안 기능**
   - 비밀번호 해싱 (bcrypt)
   - 토큰 로테이션
   - 요청 제한
   - CSRF 보호

3. **RBAC**
   - 역할 기반 권한
   - 조직 레벨 제어
   - 리소스 레벨 권한

### 12.6 고급 연구 기능

1. **딥 리서치**
   - 4단계 프로세스
   - 30-50+ 소스
   - 15-30분 실행 시간

2. **하이퍼 딥 리서치**
   - 8단계 체계적 프로세스
   - 200+ 소스
   - 30-60분 실행 시간
   - 편향 감지 및 사실 확인

3. **반복 탐색**
   - 품질 기반 반복
   - 도메인 잠금
   - 적응형 검색

### 12.7 컨텍스트 최적화

1. **다중 전략**
   - 사고 블록 관리
   - 토큰 카운팅
   - 오버플로우 감지
   - 도구 결과 요약
   - 메시지 압축
   - 시맨틱 중복 제거
   - 토큰 예산

2. **효율적인 컨텍스트 사용**
   - 200K 컨텍스트 윈도우
   - 85% 임계값에서 경고
   - 자동 정리

### 12.8 관찰 가능성

1. **Prometheus 메트릭**
   - HTTP 메트릭 (RED)
   - 에이전트 실행
   - 워크플로우 성능
   - LLM API 호출
   - 캐시 메트릭
   - 데이터베이스 풀

2. **OpenTelemetry 추적**
   - 분산 추적
   - 스팬 전파
   - LLM 호출 추적

3. **Arize Phoenix**
   - LLM 관찰 가능성
   - 프롬프트 추적
   - 응답 품질 모니터링

### 12.9 멀티모달 처리

1. **이미지 분석**
   - 다중 비전 모델
   - OCR
   - 객체 감지

2. **오디오 처리**
   - Whisper 통합
   - 다국어 지원
   - 타임스탬프

3. **문서 처리**
   - PDF, DOCX, XLSX, PPTX
   - 구조 분석
   - 메타데이터 추출

### 12.10 성능

1. **비동기/대기**
   - 전반적인 비동기 아키텍처
   - 논블로킹 I/O
   - 병렬 실행

2. **연결 풀링**
   - 50 총 연결 (20 기본 + 30 오버플로우)
   - 비동기 연결
   - 자동 재연결

3. **캐싱**
   - Redis + pgvector
   - 스마트 TTL
   - 높은 히트율

4. **병렬 에이전트 실행**
   - 독립 에이전트 병렬 실행
   - asyncio.gather()
   - 타임아웃 관리

---

## 결론

NEOS 백엔드는 최신 AI 기술, 엔터프라이즈급 아키텍처, 혁신적인 최적화를 결합한 정교하게 설계된 시스템입니다. 주요 강점은 다음과 같습니다:

1. **확장성**: PostgreSQL 체크포인팅 및 분산 상태 관리를 통한 수평적 확장
2. **지능**: 15개 이상의 전문화된 AI 에이전트와 다중 LLM 제공자
3. **효율성**: 시맨틱 캐싱 및 동적 TTL을 통한 스마트 최적화
4. **확장 가능성**: 플러그인 기반 스킬 및 도구 시스템
5. **관찰 가능성**: Prometheus, OpenTelemetry, Arize Phoenix를 통한 포괄적인 모니터링
6. **보안**: 다중 인증 방법 및 RBAC
7. **성능**: 비동기 아키텍처, 연결 풀링, 스마트 캐싱

이 아키텍처는 프로덕션 AI 애플리케이션에 적합하며 명확한 관심사 분리, 강력한 오류 처리, 포괄적인 테스트를 통해 유지보수 및 확장 가능합니다.

---

**문서 버전**: 1.0
**마지막 업데이트**: 2025-12-31
**작성자**: NEOS Architecture Team
