# 커스텀 워크플로우 빌더 (Custom Workflow Builder)

MCP(Model Context Protocol) 도구를 활용한 커스텀 워크플로우를 생성, 저장, 실행할 수 있는 기능입니다.

## 주요 기능

### 1. MCP 서버 관리
- MCP 서버 등록 및 관리
- 서버 타입별 분류 (web_search, file_processing, data_analysis 등)
- 서버 설정 및 capabilities 관리
- 활성화/비활성화 기능

### 2. 워크플로우 빌더
- 시각적/대화형 워크플로우 생성
- 노드 기반 워크플로우 설계
- 여러 MCP 도구를 조합한 복합 워크플로우
- 데이터베이스에 워크플로우 정의 저장

### 3. 워크플로우 실행
- 저장된 워크플로우 로드 및 실행
- 실행 기록 자동 저장
- 성능 메트릭 추적
- 오류 처리 및 로깅

## 빠른 시작

### 1. 데이터베이스 설정

```bash
# PostgreSQL에 마이그레이션 적용
psql -U your_user -d your_database -f migrations/add_workflow_tables.sql
```

### 2. MCP 서버 등록

```bash
uv run python -m neos.cli workflow-builder mcp register \
  --name "web_search" \
  --url "https://api.tavily.com" \
  --type "web_search" \
  --description "웹 검색 서버" \
  --capabilities "real_time_search"
```

### 3. 워크플로우 생성

```bash
uv run python -m neos.cli workflow-builder create \
  --name "my_first_workflow" \
  --description "첫 번째 워크플로우" \
  --interactive
```

### 4. 워크플로우 활성화 및 실행

```bash
# 활성화
uv run python -m neos.cli workflow-builder activate 1

# 실행
uv run python -m neos.cli workflow-builder execute 1 \
  --query "AI 산업 동향"
```

## 아키텍처

### 데이터베이스 스키마

```
mcp_servers
├── id (PK)
├── name (UNIQUE)
├── url
├── server_type
├── config (JSONB)
└── capabilities (JSONB)

custom_workflows
├── id (PK)
├── name (UNIQUE)
├── description
├── nodes (JSONB)
├── edges (JSONB)
├── status (ENUM)
└── execution_count

workflow_mcp_servers (관계 테이블)
├── workflow_id (FK)
├── mcp_server_id (FK)
└── tool_config (JSONB)

workflow_executions (실행 기록)
├── id (PK)
├── workflow_id (FK)
├── input_query
├── output (JSONB)
├── execution_time_ms
└── execution_steps (JSONB)
```

### 노드 타입

1. **mcp_tool**: MCP 서버의 도구 실행
2. **processor**: 결과 처리 및 변환
3. **agent**: 기존 에이전트 시스템과 통합

### 프로세서 타입

1. **result_integrator**: 여러 단계의 결과 통합
2. **response_generator**: 최종 응답 생성

## CLI 명령어

### MCP 서버 관리

```bash
# 서버 등록
uv run python -m neos.cli workflow-builder mcp register \
  --name "server_name" \
  --url "server_url" \
  --type "server_type"

# 서버 목록
uv run python -m neos.cli workflow-builder mcp list

# 서버 상세 정보
uv run python -m neos.cli workflow-builder mcp info <server_id>

# 서버 삭제
uv run python -m neos.cli workflow-builder mcp delete <server_id>
```

### 워크플로우 관리

```bash
# 워크플로우 생성
uv run python -m neos.cli workflow-builder create \
  --name "workflow_name" \
  --description "description" \
  --interactive

# 워크플로우 목록
uv run python -m neos.cli workflow-builder list
uv run python -m neos.cli workflow-builder list --status active

# 워크플로우 상세 정보
uv run python -m neos.cli workflow-builder info <workflow_id>

# 워크플로우 활성화/비활성화
uv run python -m neos.cli workflow-builder activate <workflow_id>
uv run python -m neos.cli workflow-builder deactivate <workflow_id>

# 워크플로우 실행
uv run python -m neos.cli workflow-builder execute <workflow_id> \
  --query "your query"

# 워크플로우 삭제
uv run python -m neos.cli workflow-builder delete <workflow_id>
```

## Python API 사용

### 워크플로우 생성

```python
import asyncio
from neos.workflow.builder import CustomWorkflowBuilder

async def create_workflow():
    builder = CustomWorkflowBuilder()

    # MCP 서버 추가
    builder.add_mcp_server("web_search", 1)

    # 노드 추가
    builder.add_node(
        name="search",
        node_type="mcp_tool",
        config={"max_results": 5},
        mcp_server_name="web_search"
    )

    builder.add_node(
        name="process",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 엣지 추가
    builder.add_edge("search", "process")
    builder.add_edge("process", "END")

    # 저장
    workflow_id = await builder.save(
        name="my_workflow",
        description="워크플로우 설명",
        created_by="user_id"
    )

    return workflow_id

asyncio.run(create_workflow())
```

### 워크플로우 실행

```python
import asyncio
from neos.workflow.builder import WorkflowExecutor

async def run_workflow(workflow_id: int):
    executor = WorkflowExecutor(workflow_id)

    result = await executor.execute({
        "query": "검색 쿼리",
        "user_id": "user123",
        "session_id": "session456"
    })

    if result["success"]:
        print(result["response"])
    else:
        print(f"Error: {result['error']}")

asyncio.run(run_workflow(1))
```

## 사용 예제

### 예제 1: 웹 검색 워크플로우

```python
builder = CustomWorkflowBuilder()
builder.add_mcp_server("web_search", 1)
builder.add_node("search", "mcp_tool", mcp_server_name="web_search")
builder.add_node("response", "processor", config={"processor_type": "response_generator"})
builder.add_edge("search", "response")
builder.add_edge("response", "END")

workflow_id = await builder.save(
    name="web_search_workflow",
    description="웹 검색 워크플로우",
    created_by="user"
)
```

### 예제 2: 복합 워크플로우

```python
builder = CustomWorkflowBuilder()
builder.add_mcp_server("web_search", 1)
builder.add_mcp_server("file_processing", 2)

# 검색 노드
builder.add_node("search", "mcp_tool", mcp_server_name="web_search")

# 통합 노드
builder.add_node("integrate", "processor",
                 config={"processor_type": "result_integrator"})

# 파일 저장 노드
builder.add_node("save", "mcp_tool",
                 config={"operation": "write"},
                 mcp_server_name="file_processing")

# 응답 생성 노드
builder.add_node("response", "processor",
                 config={"processor_type": "response_generator"})

# 엣지 연결
builder.add_edge("search", "integrate")
builder.add_edge("integrate", "save")
builder.add_edge("save", "response")
builder.add_edge("response", "END")

workflow_id = await builder.save(
    name="advanced_workflow",
    description="검색 → 통합 → 저장 → 응답",
    created_by="user"
)
```

## 주요 파일

- **neos/database/workflow_models.py**: 데이터베이스 모델
- **neos/workflow/builder.py**: 워크플로우 빌더 코어 로직
- **neos/tools/mcp_server_manager.py**: MCP 서버 관리
- **neos/cli_workflow_builder.py**: CLI 인터페이스
- **migrations/add_workflow_tables.sql**: 데이터베이스 마이그레이션

## 문서

자세한 사용법은 [워크플로우 빌더 가이드](workflow_builder_guide.md)를 참고하세요.

## 로드맵

- [ ] 조건부 엣지 고급 기능
- [ ] 시각적 워크플로우 편집기
- [ ] 워크플로우 템플릿 라이브러리
- [ ] 워크플로우 버전 관리
- [ ] 실행 결과 분석 대시보드
- [ ] 워크플로우 복제 및 공유 기능

## 문제 해결

### 데이터베이스 연결 오류

```bash
# 데이터베이스 상태 확인
uv run python -m neos.cli status
```

### MCP 서버 연결 실패

1. API 키가 올바르게 설정되었는지 확인
2. 서버가 활성화되어 있는지 확인
3. 네트워크 연결 확인

### 워크플로우 실행 실패

1. 워크플로우가 활성화되어 있는지 확인
2. 모든 노드가 올바르게 연결되어 있는지 확인
3. END 노드로 종료되는지 확인

## 라이선스

MIT License
