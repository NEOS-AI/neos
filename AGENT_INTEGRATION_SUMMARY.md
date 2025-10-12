# Neos 에이전트 통합 완료 ✅

커스텀 워크플로우 빌더에 Neos의 기존 에이전트들을 완전히 통합했습니다!

## 🎯 주요 변경사항

### 1. **에이전트 레지스트리 시스템** ✅
- **파일**: `neos/workflow/agent_registry.py`
- 모든 Neos 에이전트를 중앙에서 관리
- 13개의 에이전트 자동 등록:
  - **검색 에이전트** (6개): knowledge_search, realtime_info_search, realtime_data_search, multi_query_search, deep_research, hyper_deep_research
  - **분석 에이전트** (3개): data_analysis, comparative_analysis, web_lookup
  - **생성 에이전트** (4개): image_generation, api_call, file_processing, task_creation

### 2. **워크플로우 빌더 코어 업데이트** ✅
- **파일**: `neos/workflow/builder.py`
- `_execute_agent()` 메서드 완전히 재구현
- 에이전트 실행 로직 추가:
  - 에이전트 레지스트리에서 동적으로 에이전트 로드
  - 언어 자동 감지
  - 컨텍스트 자동 설정
  - 결과 포맷팅 및 오류 처리

### 3. **CLI 명령어 추가** ✅
- **파일**: `neos/cli_workflow_builder.py`
- 새로운 명령어 그룹: `workflow-builder agent`
  - `agent list`: 사용 가능한 에이전트 목록 조회
  - `agent info <agent_name>`: 에이전트 상세 정보
- 대화형 워크플로우 생성 시 에이전트 선택 가능

### 4. **예제 코드** ✅
- **파일**: `examples/workflow_builder_with_agents_example.py`
- 5가지 실전 예제 포함:
  - 예제 1: 사용 가능한 에이전트 목록
  - 예제 2: 에이전트 워크플로우 생성
  - 예제 3: 복합 워크플로우 (에이전트 + MCP)
  - 예제 4: 심층 조사 워크플로우
  - 예제 5: 다중 쿼리 워크플로우

## 📋 사용 방법

### CLI로 에이전트 확인

```bash
# 모든 에이전트 목록
uv run python -m neos.cli workflow-builder agent list

# 카테고리별 필터링
uv run python -m neos.cli workflow-builder agent list --category search

# 특정 에이전트 상세 정보
uv run python -m neos.cli workflow-builder agent info realtime_info_search
```

### 대화형 워크플로우 생성

```bash
uv run python -m neos.cli workflow-builder create \
  --name "my_agent_workflow" \
  --description "에이전트를 사용하는 워크플로우" \
  --interactive
```

대화형 모드에서:
1. 노드 타입으로 "agent" 선택
2. 13개의 에이전트 중 선택 (카테고리별로 그룹화되어 표시)
3. 나머지 노드와 엣지 설정

### Python 코드로 에이전트 워크플로우 생성

```python
import asyncio
from neos.workflow.builder import CustomWorkflowBuilder

async def create_agent_workflow():
    builder = CustomWorkflowBuilder()

    # 1. 실시간 정보 검색 에이전트
    builder.add_node(
        name="search",
        node_type="agent",
        config={"agent_name": "realtime_info_search"}
    )

    # 2. 데이터 분석 에이전트
    builder.add_node(
        name="analyze",
        node_type="agent",
        config={"agent_name": "data_analysis"}
    )

    # 3. 최종 응답 생성
    builder.add_node(
        name="response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("search", "analyze")
    builder.add_edge("analyze", "response")
    builder.add_edge("response", "END")

    # 저장
    workflow_id = await builder.save(
        name="search_and_analyze",
        description="검색 후 분석하는 워크플로우",
        created_by="user"
    )

    return workflow_id

asyncio.run(create_agent_workflow())
```

### 복합 워크플로우 (에이전트 + MCP)

```python
builder = CustomWorkflowBuilder()

# MCP 서버 추가
builder.add_mcp_server("web_search_mcp", 1)

# MCP 웹 검색 노드
builder.add_node(
    name="mcp_search",
    node_type="mcp_tool",
    mcp_server_name="web_search_mcp"
)

# 에이전트 분석 노드
builder.add_node(
    name="agent_analyze",
    node_type="agent",
    config={"agent_name": "comparative_analysis"}
)

# 엣지 연결
builder.add_edge("mcp_search", "agent_analyze")
builder.add_edge("agent_analyze", "END")

workflow_id = await builder.save(
    name="mcp_plus_agent",
    description="MCP 검색 + 에이전트 분석",
    created_by="user"
)
```

## 🔍 사용 가능한 에이전트

### 검색 에이전트 (Search)

| 에이전트명 | 설명 | 실행 시간 | 주요 용도 |
|----------|------|---------|---------|
| `knowledge_search` | 벡터 DB 기반 지식 검색 | ~1초 | 기존 저장된 지식 검색 |
| `realtime_info_search` | 실시간 정보 검색 | ~2-5초 | 최신 뉴스, 정보 |
| `realtime_data_search` | 실시간 데이터 검색 | ~2-5초 | 통계, 수치 데이터 |
| `multi_query_search` | 다중 쿼리 검색 | ~10-20초 | 다각도 분석 |
| `deep_research` | 심층 조사 | 15-25분 | 종합적 리서치 |
| `hyper_deep_research` | 초심층 조사 | 30-60분 | 최고 품질 리서치 |

### 분석 에이전트 (Analysis)

| 에이전트명 | 설명 | 주요 용도 |
|----------|------|---------|
| `data_analysis` | 데이터 분석 및 인사이트 | 데이터 해석, 패턴 발견 |
| `comparative_analysis` | 비교 분석 | 여러 항목 비교 평가 |
| `web_lookup` | 웹 정보 조회 및 검증 | 사실 확인, 검증 |

### 생성 에이전트 (Generation)

| 에이전트명 | 설명 | 주요 용도 |
|----------|------|---------|
| `image_generation` | 이미지 생성 | DALL-E 등을 통한 이미지 생성 |
| `api_call` | 외부 API 호출 | 외부 서비스 통합 |
| `file_processing` | 파일 처리 | 파일 읽기/쓰기/변환 |
| `task_creation` | 작업 생성 및 분해 | 복잡한 작업 분해 |

## 💡 실전 예제

### 예제 1: 단순 검색 워크플로우

```python
# 실시간 정보 검색만 수행
builder.add_node("search", "agent",
                 config={"agent_name": "realtime_info_search"})
builder.add_node("response", "processor",
                 config={"processor_type": "response_generator"})
builder.add_edge("search", "response")
builder.add_edge("response", "END")
```

### 예제 2: 검색 + 분석 워크플로우

```python
# 검색 후 분석
builder.add_node("search", "agent",
                 config={"agent_name": "multi_query_search"})
builder.add_node("analyze", "agent",
                 config={"agent_name": "data_analysis"})
builder.add_node("compare", "agent",
                 config={"agent_name": "comparative_analysis"})
builder.add_node("response", "processor",
                 config={"processor_type": "response_generator"})

builder.add_edge("search", "analyze")
builder.add_edge("analyze", "compare")
builder.add_edge("compare", "response")
builder.add_edge("response", "END")
```

### 예제 3: 심층 조사 워크플로우

```python
# 실시간 검색 → 심층 조사 → 검증
builder.add_node("initial", "agent",
                 config={"agent_name": "realtime_info_search"})
builder.add_node("deep", "agent",
                 config={"agent_name": "deep_research"})
builder.add_node("verify", "agent",
                 config={"agent_name": "web_lookup"})
builder.add_node("response", "processor",
                 config={"processor_type": "response_generator"})

builder.add_edge("initial", "deep")
builder.add_edge("deep", "verify")
builder.add_edge("verify", "response")
builder.add_edge("response", "END")
```

## 🧪 테스트

### CLI 테스트

```bash
# 에이전트 목록 확인
uv run python -m neos.cli workflow-builder agent list

# 특정 에이전트 정보
uv run python -m neos.cli workflow-builder agent info deep_research

# 예제 실행
uv run python examples/workflow_builder_with_agents_example.py
```

### 실행 결과

```
=== 예제 1: 사용 가능한 에이전트 목록 ===

총 13개의 에이전트 사용 가능

[SEARCH] - 6개
  • knowledge_search
    벡터 데이터베이스 기반 지식 검색
    기능: vector_search, semantic_search, knowledge_retrieval

  • realtime_info_search
    실시간 정보 검색 (Tavily API)
    기능: real_time_search, web_search, current_events

  ...
```

## 📊 노드 타입 비교

| 노드 타입 | 설명 | 설정 방법 | 예시 |
|---------|------|---------|------|
| **agent** | Neos 에이전트 실행 | `config={"agent_name": "..."}` | realtime_info_search |
| **mcp_tool** | MCP 서버 도구 실행 | `mcp_server_name="..."` | web_search_mcp |
| **processor** | 결과 처리 | `config={"processor_type": "..."}` | response_generator |

## 🔄 워크플로우 실행 흐름

```
1. 워크플로우 로드
   ↓
2. 노드별 실행
   ├─ agent 노드: 에이전트 레지스트리에서 로드 → execute() 호출
   ├─ mcp_tool 노드: MCP 매니저를 통해 실행
   └─ processor 노드: 결과 처리 로직 실행
   ↓
3. 결과 통합 및 저장
   ↓
4. 최종 응답 반환
```

## 📁 변경된 파일

- ✅ `neos/workflow/agent_registry.py` - 새로 생성
- ✅ `neos/workflow/builder.py` - `_execute_agent()` 메서드 업데이트
- ✅ `neos/cli_workflow_builder.py` - `agent` 명령어 그룹 추가
- ✅ `examples/workflow_builder_with_agents_example.py` - 새로 생성

## 🎉 완성!

이제 다음이 가능합니다:

1. ✅ **13개의 Neos 에이전트**를 워크플로우에서 자유롭게 사용
2. ✅ **에이전트 + MCP 도구**를 조합한 복합 워크플로우 생성
3. ✅ **대화형 CLI**로 쉽게 에이전트 선택 및 워크플로우 생성
4. ✅ **Python API**로 프로그래매틱하게 워크플로우 구성
5. ✅ **실행 기록 자동 저장** 및 추적

## 📝 다음 단계

- [ ] 에이전트 간 결과 전달 최적화
- [ ] 에이전트 실행 순서 자동 최적화
- [ ] 조건부 에이전트 실행 (성공/실패에 따른 분기)
- [ ] 에이전트 실행 병렬화 (독립적인 에이전트는 동시 실행)
- [ ] 에이전트 성능 모니터링 대시보드

## 🚀 빠른 시작

```bash
# 1. 에이전트 목록 확인
uv run python -m neos.cli workflow-builder agent list

# 2. 워크플로우 생성 (대화형)
uv run python -m neos.cli workflow-builder create \
  --name "my_workflow" \
  --description "에이전트 워크플로우" \
  --interactive

# 3. 워크플로우 활성화
uv run python -m neos.cli workflow-builder activate 1

# 4. 워크플로우 실행
uv run python -m neos.cli workflow-builder execute 1 \
  --query "2024년 AI 산업 동향"

# 5. 예제 실행
uv run python examples/workflow_builder_with_agents_example.py
```

모든 기능이 정상 작동하며 테스트 완료! 🎊
