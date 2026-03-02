# Advanced Tool Search

> **상태**: 구현 완료 (Phase 1-3)
> **작성일**: 2026-02-28
> **설계 문서**: [DESIGN_ADVANCED_TOOL_SEARCH.md](DESIGN_ADVANCED_TOOL_SEARCH.md)

---

## 목차

1. [개요](#1-개요)
2. [아키텍처](#2-아키텍처)
3. [컴포넌트 상세](#3-컴포넌트-상세)
4. [DB 스키마](#4-db-스키마)
5. [설정 및 환경변수](#5-설정-및-환경변수)
6. [사용 가이드](#6-사용-가이드)
7. [테스트](#7-테스트)
8. [구현 결정 배경](#8-구현-결정-배경)

---

## 1. 개요

### 1.1 해결한 문제

기존 `SkillBasedToolSelector`는 **모든 등록된 스킬/도구 목록을 LLM 프롬프트에 텍스트로 주입**한 뒤 LLM이 선택하게 하는 방식이었다.

| 문제 | 영향 |
|------|------|
| 컨텍스트 윈도우 낭비 | 도구 50개 × 200토큰 = ~10K 토큰 소비 |
| 선택 정확도 저하 | 유사한 이름/기능 도구 간 LLM 혼동 |
| 프롬프트 캐싱 무효화 | 도구 목록이 프롬프트에 포함되어 캐시 히트율 저하 |
| 전용 LLM 호출 | 도구 선택만을 위한 추가 API 호출 1회 |

### 1.2 해결 방식

Anthropic의 **Advanced Tool Use 패턴**을 적용:

```
기존:  [전체 도구 목록 프롬프트 주입] → LLM 선택
새로운: [코어 도구 2-3개 + search_tools] → Claude가 필요 시 search_tools 호출
                                        → 하이브리드 검색 → 도구 동적 주입
```

- **토큰 절감**: 코어 도구 ~1.5K + search_tools ~0.3K ≈ 2K (기존 대비 80%+ 절감)
- **반복 검색**: 첫 검색이 부적합하면 Claude가 스스로 쿼리를 수정하여 재검색
- **선택 정확도**: Anthropic 내부 테스트 기준 49% → 74% (Opus 4 기준)

---

## 2. 아키텍처

### 2.1 전체 흐름

```
사용자 메시지
     │
     ▼
chat_handlers.py
  TOOL_SEARCH_ENABLED?
  ├─ NO  → generate_response_stream_with_tools()  (기존 방식, 하위 호환)
  └─ YES → generate_response_stream_with_tool_search()
               │
               ├─ 초기 tools: [createDocument, updateDocument, search_tools]
               │
               ▼
         Claude API 호출 (round 1)
               │
         ┌─────┴─────┐
         │           │
     텍스트만     tool_use 감지
         │           │
       완료      ┌───┴───┐
              search_  일반 도구
              tools    (artifact 등)
                 │
         SearchToolsHandler.handle()
                 │
         HybridSearchEngine.search()
                 │                    pgvector (벡터 유사도)
         ┌───────┴───────┐           +
         │   단일 SQL     │           PostgreSQL FTS (BM25)
         │   CTE 쿼리    │           + RRF 병합
         └───────┬───────┘
                 │
         검색된 도구를 active_tools에 추가
                 │
         Claude API 호출 (round 2)  ← 발견된 도구 포함
```

### 2.2 컴포넌트 구조

```
neos/tools/tool_search/
├── __init__.py
├── tool_metadata.py          ← 데이터 모델 (ToolDefinition, ToolSearchResult)
├── hybrid_search_engine.py   ← 벡터+BM25+RRF 검색 엔진
├── tool_registry_store.py    ← 도구 등록/검색/통계 저장소
├── search_tools_handler.py   ← search_tools 도구 정의 + 핸들러
└── sync.py                   ← 기존 스킬/MCP 도구 → Registry 동기화
```

**수정된 기존 파일**:
- `neos/services/chat_llm_service.py` — `generate_response_stream_with_tool_search()` 추가
- `neos/api/handlers/chat_handlers.py` — TOOL_SEARCH_ENABLED 분기 추가, 모듈 레벨 싱글톤(`_get_search_handler`, `_get_core_tools_cached`)
- `neos/database/models.py` — `ToolRegistry` ORM 모델 추가
- `neos/config/settings.py` — `TOOL_SEARCH_*` 설정 추가
- `neos/skills/base/skill.py` — `BaseSkill.get_input_schema()` classmethod 추가
- `neos/tools/base/tool.py` — `MCPTool.get_input_schema()` 메서드 추가

---

## 3. 컴포넌트 상세

### 3.1 `ToolDefinition` / `ToolSearchResult`

**파일**: [neos/tools/tool_search/tool_metadata.py](../neos/tools/tool_search/tool_metadata.py)

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    source_type: str        # 'skill' | 'mcp_tool' | 'artifact_tool' | 'custom'
    category: str = "general"
    tags: List[str] = field(default_factory=list)

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Anthropic API tools 파라미터 형식으로 변환"""

@dataclass
class ToolSearchResult:
    tool: ToolDefinition
    score: float            # 0.0 ~ 1.0 (RRF combined score)
    match_source: str       # 'vector' | 'bm25' | 'hybrid'
```

`to_anthropic_tool()`은 `name`, `description`, `input_schema`만 포함한다. `source_type`, `category`, `tags`는 내부 메타데이터이며 Anthropic API에 노출되지 않는다.

---

### 3.2 `HybridSearchEngine`

**파일**: [neos/tools/tool_search/hybrid_search_engine.py](../neos/tools/tool_search/hybrid_search_engine.py)

**검색 전략**: 단일 CTE SQL 쿼리로 벡터 검색과 BM25를 동시에 수행하여 DB 라운드트립을 최소화한다.

```
쿼리: "PDF 파일에서 텍스트 추출"

1) Dense Vector Search (pgvector, HNSW)
   임베딩 → 코사인 유사도 → 상위 20개 + 순위
   결과: [pdf_skill(rank=1), docx_skill(rank=2), ...]

2) BM25 Keyword Search (tsvector, websearch_to_tsquery)
   키워드 매칭 → ts_rank_cd → 상위 20개 + 순위
   결과: [pdf_skill(rank=1), pdf_converter(rank=2), ...]

3) Reciprocal Rank Fusion (RRF, k=60)
   RRF(d) = 1/(60 + vector_rank) + 1/(60 + bm25_rank)
   두 결과 목록에 모두 등장하는 도구가 높은 점수

4) 상위 top_k 반환, match_source 태깅
   'hybrid' = 양쪽 모두 등장 (가장 신뢰도 높음)
   'vector' = 벡터 검색에만 등장
   'bm25'   = BM25에만 등장
```

**폴백 전략**:
| 상황 | 동작 |
|------|------|
| 임베딩 생성 실패 | BM25 전용 검색으로 폴백 |
| BM25 매치 없음 (비영어 쿼리 등) | 벡터 전용 검색으로 폴백 |
| 둘 다 결과 없음 | 빈 리스트 반환 |

**파라미터**:
```python
engine = HybridSearchEngine(
    embedding_manager=embedding_manager,
    rrf_k=60,   # RRF 파라미터. 클수록 순위 차이 완화
)
```

---

### 3.3 `ToolRegistryStore`

**파일**: [neos/tools/tool_search/tool_registry_store.py](../neos/tools/tool_search/tool_registry_store.py)

중앙 저장소. 도구 등록, 코어 도구 조회, 검색, 사용 통계를 담당한다.

```python
store = ToolRegistryStore(embedding_manager=embedding_manager)

# 도구 등록 (upsert - 이름이 같으면 업데이트)
await store.register_tool(
    name="pdf_skill",
    description="Extract and analyze text from PDF documents...",
    schema={"type": "object", ...},
    source_type="skill",
    category="document",
    tags=["pdf", "extract", "text"],
    defer_loading=True,   # True = 검색 대상, False = 코어 도구
)

# 코어 도구 조회 (defer_loading=False인 도구만)
core_tools = await store.get_core_tools()   # List[ToolDefinition]

# 하이브리드 검색
results = await store.search("PDF에서 텍스트 추출", top_k=5)

# 사용 통계 업데이트
await store.update_usage("pdf_skill")
```

**`defer_loading` 플래그**:
- `False` → **코어 도구**: 항상 Claude에게 제공. `createDocument`, `updateDocument` 등
- `True` → **검색 대상 도구**: `search_tools` 호출 시 발견됨. 스킬, MCP 도구 등

---

### 3.4 `search_tools` 도구 및 `SearchToolsHandler`

**파일**: [neos/tools/tool_search/search_tools_handler.py](../neos/tools/tool_search/search_tools_handler.py)

Claude에게 제공되는 메타 도구. Claude는 이 도구를 통해 필요한 도구를 스스로 검색한다.

**도구 스키마**:
```json
{
  "name": "search_tools",
  "description": "Search for available tools and skills by describing what capability you need...",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language description of the capability needed..."
      },
      "category": {
        "type": "string",
        "enum": ["search", "analysis", "document", "data", "general"]
      }
    },
    "required": ["query"]
  }
}
```

**응답 형식**:
```json
{
  "type": "tool_result",
  "content": "Found 3 matching tools. You can now use any of these tools by calling them directly.",
  "found_tools": [
    {
      "name": "arxiv_search",
      "description": "Search academic papers on arXiv...",
      "input_schema": {"type": "object", ...},
      "relevance_score": 0.923,
      "category": "search"
    }
  ]
}
```

Claude는 `found_tools`의 `input_schema`를 읽고 즉시 해당 도구를 호출할 수 있다.

---

### 3.5 `generate_response_stream_with_tool_search()`

**파일**: [neos/services/chat_llm_service.py](../neos/services/chat_llm_service.py)

멀티턴 도구 호출 루프를 구현한 스트리밍 메서드.

```
라운드 1: tools = [createDocument, updateDocument, search_tools]
  Claude → search_tools("academic papers arxiv") 호출
  → SearchToolsHandler → arxiv_skill 발견
  → active_tools에 arxiv_skill 추가

라운드 2: tools = [createDocument, updateDocument, search_tools, arxiv_skill]
  Claude → arxiv_skill(query="LLM scaling") 호출
  → tool_executor 콜백으로 실행
  → 결과를 messages에 추가

라운드 3: 최종 텍스트 응답 생성
```

**핵심 파라미터**:
```python
async for chunk in chat_llm_service.generate_response_stream_with_tool_search(
    conversation_id=...,
    message_id=...,
    conversation_messages=...,
    core_tools=core_tools_dicts,      # ToolRegistryStore.get_core_tools()의 결과
    search_handler=search_handler,    # SearchToolsHandler 인스턴스
    tool_executor=tool_executor_fn,   # 일반 도구 실행 콜백 (name, input) → dict
    max_tool_rounds=3,                # 최대 라운드 수
):
    ...
```

**`tool_executor` 콜백**: 일반 도구(아티팩트 도구 등)의 실행을 외부에 위임한다. 이 콜백이 없으면 search_tools 외의 도구 호출 시 루프가 종료된다(단일 라운드 폴백).

**이벤트 형식** (기존 `generate_response_stream_with_tools()`와 동일):
```python
{"type": "start", "model": ..., "provider": "anthropic"}
{"type": "reasoning_start"}
{"type": "reasoning", "content": "..."}
{"type": "content", "content": "..."}
{"type": "tool_use", "tool_name": "...", "tool_input": {...}, "tool_id": "..."}
{"type": "complete", "full_content": "...", "usage": {...}, "tool_search_rounds": 2}
{"type": "error", "error": "..."}
```

`complete` 이벤트에 `tool_search_rounds` 필드가 추가된다.

---

### 3.6 동기화 스크립트 (`sync.py`)

**파일**: [neos/tools/tool_search/sync.py](../neos/tools/tool_search/sync.py)

기존 스킬과 MCP 도구를 Tool Registry에 등록한다.

```python
from neos.tools.tool_search.sync import sync_tool_registry

result = await sync_tool_registry()
# → {"artifact_tools": 2, "skills": 13, "mcp_tools": 6}
```

CLI 실행:
```bash
python -m neos.tools.tool_search.sync
```

**등록 우선순위**:
1. **아티팩트 도구** (`defer_loading=False`): `createDocument`, `updateDocument` → 코어 도구
2. **빌트인 스킬** (`defer_loading=True`): arxiv, pdf, wikipedia 등 13개
   - `input_schema`는 `skill_class.get_input_schema()`로 자동 추출 (기본값: `query` + `action` + `max_results`)
   - 스킬별로 `BaseSkill.get_input_schema()`를 오버라이드하면 더 정확한 스키마 제공 가능
3. **MCP 도구** (`defer_loading=True`): WebSearch, YouTube, Git 등 6개
   - `input_schema`는 `tool.get_input_schema()`로 추출
4. 누락된 임베딩 재생성 (`rebuild_index()`)

---

## 4. DB 스키마

**마이그레이션 파일**: [db/migrations/019_add_tool_registry.sql](../db/migrations/019_add_tool_registry.sql)

```sql
CREATE TABLE tool_registry (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) UNIQUE NOT NULL,
    display_name  VARCHAR(255),
    description   TEXT NOT NULL,
    schema        JSONB,                  -- Anthropic tool input_schema
    category      VARCHAR(100),           -- search | analysis | document | data | general
    tags          TEXT[],
    source_type   VARCHAR(50) NOT NULL,   -- skill | mcp_tool | artifact_tool | custom
    defer_loading BOOLEAN DEFAULT TRUE,   -- FALSE = 코어 도구
    is_active     BOOLEAN DEFAULT TRUE,
    embedding     vector(1536),           -- OpenAI text-embedding-3-small
    search_vector tsvector GENERATED ALWAYS AS (...) STORED,  -- BM25 자동 생성
    usage_count   INTEGER DEFAULT 0,
    last_used_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

**인덱스**:
| 인덱스 | 타입 | 용도 |
|--------|------|------|
| `idx_tool_registry_embedding` | HNSW (vector_cosine_ops) | 벡터 유사도 검색 |
| `idx_tool_registry_search_vector` | GIN | BM25 전문 검색 |
| `idx_tool_registry_defer_loading` | B-tree (partial, is_active=TRUE) | 코어 도구 조회 |
| `idx_tool_registry_category` | B-tree | 카테고리 필터링 |

**`search_vector` 갱신 방식**: `BEFORE INSERT OR UPDATE` 트리거

```sql
-- 트리거 함수 (tool_registry_update_search_vector)
NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(array_to_string(NEW.tags, ' '), '')), 'C');
```

> **`GENERATED ALWAYS AS` 미사용 이유**: PostgreSQL 18 이하에서 `to_tsvector` 가 generated column의 immutability 검사를 통과하지 못하는 버전 의존적 문제가 있다. 트리거 방식은 모든 PostgreSQL 버전에서 안정적으로 동작한다.

마이그레이션 적용:
```bash
psql $DATABASE_URL -f db/migrations/019_add_tool_registry.sql
```

---

## 5. 설정 및 환경변수

**파일**: [neos/config/settings.py](../neos/config/settings.py)

> **주의**: `TOOL_SEARCH_ENABLED=true`는 **`ARTIFACTS_ENABLED=true`일 때만 동작합니다.** 두 설정을 함께 활성화해야 합니다.

```bash
# .env 또는 환경변수로 설정

# 기능 활성화 (기본값: false, 점진적 적용 권장)
# ARTIFACTS_ENABLED=true 와 함께 설정해야 동작합니다.
ARTIFACTS_ENABLED=true
TOOL_SEARCH_ENABLED=true

# 검색 파라미터
TOOL_SEARCH_TOP_K=5         # search_tools 호출당 반환할 도구 수
TOOL_SEARCH_MAX_ROUNDS=3    # 멀티턴 최대 라운드 수 (초과 시 강제 종료)
TOOL_SEARCH_RRF_K=60        # Reciprocal Rank Fusion k 파라미터
```

> **제거된 설정**:
> - `TOOL_SEARCH_ALPHA`: HybridSearchEngine은 RRF 방식으로 구현되어 alpha 파라미터를 사용하지 않습니다.
> - `TOOL_SEARCH_CACHE_TTL`: 검색 결과 캐싱이 미구현 상태여서 제거했습니다. 필요 시 `SearchToolsHandler.handle()` 내부에 `(query, category)` 키 기반 캐시를 추가하세요.

**파라미터 튜닝 가이드**:

| 파라미터 | 낮게 설정 | 높게 설정 |
|---------|---------|---------|
| `TOOL_SEARCH_TOP_K` | 정확도 ↑, 선택지 ↓ | 다양성 ↑, 노이즈 ↑ |
| `TOOL_SEARCH_MAX_ROUNDS` | 지연시간 ↓, 도구 발견 기회 ↓ | 반복 검색 가능 |
| `TOOL_SEARCH_RRF_K` | 순위 차이 크게 반영 | 순위 차이 완화 |

---

## 6. 사용 가이드

### 6.1 빠른 시작

**1단계**: DB 마이그레이션 적용
```bash
psql $DATABASE_URL -f db/migrations/019_add_tool_registry.sql
```

**2단계**: 도구 등록 동기화
```bash
python -m neos.tools.tool_search.sync
```

**3단계**: 환경변수 설정 후 서버 재시작
```bash
TOOL_SEARCH_ENABLED=true uvicorn neos.main:app --reload
```

### 6.2 직접 도구 등록

```python
from neos.utils.embeddings import EmbeddingManager
from neos.tools.tool_search.tool_registry_store import ToolRegistryStore

store = ToolRegistryStore(EmbeddingManager())

# 커스텀 도구 등록
await store.register_tool(
    name="my_custom_tool",
    description=(
        "Search product catalog by keyword or category. "
        "Returns product name, price, and availability. "
        "Use when user asks about products or inventory."
    ),
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword"},
            "category": {"type": "string", "description": "Product category filter"},
        },
        "required": ["query"],
    },
    source_type="custom",
    category="data",
    tags=["product", "catalog", "inventory", "search"],
    defer_loading=True,  # 검색 대상으로 등록
)
```

### 6.3 코어 도구 지정

특정 도구를 항상 Claude에게 제공하려면 `defer_loading=False`로 등록한다.

```python
await store.register_tool(
    name="my_always_available_tool",
    ...
    defer_loading=False,  # 코어 도구로 등록
)
```

> **주의**: 코어 도구가 너무 많으면 컨텍스트 윈도우 절감 효과가 줄어든다. 3-5개를 권장한다.

### 6.4 사용 빈도 기반 코어 도구 후보 확인

```python
candidates = await store.auto_promote_core_tools(threshold=100)
# → ["pdf_skill", "arxiv_search", ...]  # usage_count >= 100인 도구 목록
# 수동으로 defer_loading=False로 업데이트하여 승격
```

### 6.5 도구 메타데이터 품질 가이드

검색 정확도는 **도구 설명의 품질**에 직접 의존한다.

**좋은 설명**:
```python
description = (
    "Search and retrieve academic papers from arXiv by topic, author, or paper ID. "
    "Returns title, abstract, authors, and PDF download link. "
    "Use when user asks about academic research, scientific papers, or preprints. "
    "Unlike web_search, this focuses exclusively on academic preprint archives."
)
tags = ["academic", "paper", "research", "arxiv", "preprint", "science"]
```

**나쁜 설명**:
```python
description = "ArXiv search tool."
tags = ["arxiv"]
```

체크리스트:
- [ ] 동사로 시작 ("Search...", "Extract...", "Analyze...")
- [ ] 반환 데이터 명시 ("Returns title, abstract, PDF link")
- [ ] 사용 시나리오 포함 ("Use when user asks about...")
- [ ] 유사 도구와의 차별점 ("Unlike web_search, ...")
- [ ] 태그에 동의어/관련어 포함

---

## 7. 테스트

### 7.1 단위 테스트 실행

```bash
# DB 연결 불필요 (mock 사용)
pytest tests/test_tool_search.py -v

# 특정 클래스만 실행
pytest tests/test_tool_search.py::TestSearchToolsHandler -v
```

**테스트 케이스**:
- `TestToolDefinition` — Anthropic 형식 변환
- `TestToolSearchResult` — 데이터 모델 생성
- `TestSearchToolsHandler` — 검색 쿼리 처리, 결과 없음, 카테고리 필터, 응답 포맷
- `TestHybridSearchEngine` — DB row 변환, BM25 폴백 동작
- `TestToolRegistryStore` — 카테고리 추론 로직

### 7.2 통합 테스트 실행

```bash
pytest tests/integration/test_tool_search_flow.py -v
```

**테스트 케이스**:
- `test_core_tool_direct_use` — 코어 도구 직접 사용 (검색 불필요)
- `test_search_then_discover_tools` — search_tools → 도구 발견 흐름
- `test_iterative_search` — 재검색 흐름
- `test_no_tools_found` — 존재하지 않는 기능 요청
- `test_tool_deduplication_in_active_tools` — active_tools 중복 추가 방지

### 7.3 수동 검증 시나리오

```bash
# TOOL_SEARCH_ENABLED=true로 서버 실행 후 채팅 API 테스트

# 시나리오 1: 일반 채팅 (search_tools 불필요)
curl -X POST /api/v1/chat/conversations/{id}/messages \
  -d '{"content": "안녕하세요"}'
# 기대: search_tools 호출 없이 바로 응답

# 시나리오 2: 도구 필요 (arxiv 검색)
curl -X POST /api/v1/chat/conversations/{id}/messages \
  -d '{"content": "LLM scaling law에 대한 최신 논문을 찾아줘"}'
# 기대: search_tools("search academic papers arxiv") → arxiv_skill 발견 → 실행

# 시나리오 3: 코어 도구 직접 사용 (문서 생성)
curl -X POST /api/v1/chat/conversations/{id}/messages \
  -d '{"content": "Python 퀵소트 코드를 작성해줘"}'
# 기대: createDocument 직접 호출 (search_tools 없이)
```

---

## 8. 구현 결정 배경

### 8.1 ivfflat 대신 HNSW 인덱스 선택

`ivfflat` 인덱스는 데이터가 충분히 많아야 효과적이다 (일반적으로 1,000개 이상). 초기 등록 도구 수가 ~20개에 불과하므로, 소수의 데이터에서도 효과적인 **HNSW(Hierarchical Navigable Small World)** 인덱스를 채택했다.

```sql
-- 채택: HNSW (소수 도구에서도 효과적)
CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);

-- 미채택: ivfflat (최소 수백 개 이상 필요)
-- CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
```

### 8.2 단일 CTE SQL로 벡터 + BM25 동시 수행

두 개의 SQL을 순차 실행하여 Python에서 병합하는 방식 대신, **단일 CTE 쿼리**로 두 검색을 동시에 실행한다.

- DB 라운드트립 2회 → 1회로 절감
- PostgreSQL 쿼리 플래너가 내부 최적화 적용 가능
- 트랜잭션 일관성 보장

### 8.3 비영어 쿼리 폴백 전략

`search_vector`는 `to_tsvector('english', ...)` 기반이므로 한국어/일본어 쿼리에서 BM25 매칭이 실패한다. 이 경우 **임베딩 기반 벡터 검색**이 폴백으로 동작하여 비영어 쿼리도 처리 가능하다.

```
한국어 쿼리: "PDF에서 텍스트 추출"
  → BM25 검색: 매치 없음 (영어 tsvector와 불일치)
  → 벡터 검색으로 폴백: 임베딩 유사도로 pdf_skill 발견
```

### 8.4 하위 호환성 (feature flag 방식)

`TOOL_SEARCH_ENABLED=false`(기본값)인 경우 기존 `generate_response_stream_with_tools()` 경로를 그대로 사용한다. 점진적으로 적용하거나 문제 발생 시 즉시 롤백 가능.

```python
# chat_handlers.py
if app_settings.TOOL_SEARCH_ENABLED and app_settings.ARTIFACTS_ENABLED:
    llm_stream = generate_response_stream_with_tool_search(...)
else:
    llm_stream = generate_response_stream_with_tools(...)  # 기존 방식 유지
```

### 8.5 `tool_executor` 콜백 패턴

멀티턴 루프 내에서 일반 도구(아티팩트 등) 실행을 **콜백으로 위임**한다. 이 설계 덕분에:
- `chat_llm_service.py`가 아티팩트 실행 로직을 포함하지 않아도 됨 (단일 책임 원칙)
- 호출자(chat_handlers.py)가 DB 세션, 사용자 ID 등 컨텍스트를 직접 관리
- 콜백 없이도 동작 (search_tools 단독 사용 가능)
