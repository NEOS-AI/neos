# 커스텀 워크플로우 빌더 가이드

커스텀 워크플로우 빌더를 사용하면 MCP(Model Context Protocol) 도구들을 활용한 나만의 워크플로우를 생성하고 관리할 수 있습니다.

## 목차

1. [설치 및 설정](#설치-및-설정)
2. [MCP 서버 관리](#mcp-서버-관리)
3. [워크플로우 생성](#워크플로우-생성)
4. [워크플로우 실행](#워크플로우-실행)
5. [사용 예제](#사용-예제)

## 설치 및 설정

### 1. 데이터베이스 마이그레이션

먼저 워크플로우 관련 테이블을 생성해야 합니다:

```bash
# PostgreSQL에 접속
psql -U your_user -d your_database

# 마이그레이션 파일 실행
\i migrations/add_workflow_tables.sql
```

### 2. 환경 변수 설정

필요한 MCP 서버의 API 키를 설정합니다:

```bash
# .env 파일에 추가
TAVILY_API_KEY=your_tavily_api_key
```

## MCP 서버 관리

### MCP 서버 등록

워크플로우에서 사용할 MCP 서버를 등록합니다:

```bash
# Tavily 웹 검색 서버 등록
uv run python -m neos.cli workflow-builder mcp register \
  --name "tavily_search" \
  --url "https://api.tavily.com" \
  --type "web_search" \
  --description "Tavily 웹 검색 API" \
  --capabilities "real_time_search" \
  --capabilities "multi_source"
```

### MCP 서버 목록 조회

```bash
# 모든 MCP 서버 목록
uv run python -m neos.cli workflow-builder mcp list

# 특정 타입만 조회
uv run python -m neos.cli workflow-builder mcp list --type web_search

# 활성화된 서버만 조회
uv run python -m neos.cli workflow-builder mcp list --active-only
```

### MCP 서버 상세 정보

```bash
uv run python -m neos.cli workflow-builder mcp info 1
```

### MCP 서버 삭제

```bash
uv run python -m neos.cli workflow-builder mcp delete 1 --yes
```

## 워크플로우 생성

### 대화형 모드로 워크플로우 생성

```bash
uv run python -m neos.cli workflow-builder create \
  --name "web_search_workflow" \
  --description "웹 검색 후 결과를 정리하는 워크플로우" \
  --interactive
```

대화형 모드에서는:
1. 노드 추가 (agent, mcp_tool, processor)
2. 노드 간 연결 설정 (엣지)
3. 태그 및 메타데이터 입력

### 프로그래매틱 방식

Python 코드로 직접 워크플로우를 생성할 수도 있습니다:

```python
import asyncio
from neos.workflow.builder import CustomWorkflowBuilder

async def create_custom_workflow():
    builder = CustomWorkflowBuilder()

    # MCP 서버 추가
    builder.add_mcp_server("web_search_mcp", 1)  # server_id=1

    # 노드 추가
    builder.add_node(
        name="web_search",
        node_type="mcp_tool",
        config={"max_results": 5},
        mcp_server_name="web_search_mcp"
    )

    builder.add_node(
        name="result_integrator",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    builder.add_node(
        name="response_generator",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 추가
    builder.add_edge("web_search", "result_integrator")
    builder.add_edge("result_integrator", "response_generator")
    builder.add_edge("response_generator", "END")

    # 저장
    workflow_id = await builder.save(
        name="web_search_workflow",
        description="웹 검색 후 결과를 정리하는 워크플로우",
        created_by="user123",
        tags=["search", "web"]
    )

    print(f"Workflow created with ID: {workflow_id}")
    return workflow_id

# 실행
asyncio.run(create_custom_workflow())
```

## 워크플로우 관리

### 워크플로우 목록 조회

```bash
# 모든 워크플로우
uv run python -m neos.cli workflow-builder list

# 활성화된 워크플로우만
uv run python -m neos.cli workflow-builder list --status active

# 특정 사용자의 워크플로우
uv run python -m neos.cli workflow-builder list --created-by user123
```

### 워크플로우 상세 정보

```bash
uv run python -m neos.cli workflow-builder info 1
```

### 워크플로우 활성화/비활성화

```bash
# 활성화
uv run python -m neos.cli workflow-builder activate 1

# 비활성화
uv run python -m neos.cli workflow-builder deactivate 1
```

### 워크플로우 삭제

```bash
uv run python -m neos.cli workflow-builder delete 1 --yes
```

## 워크플로우 실행

### CLI로 실행

```bash
uv run python -m neos.cli workflow-builder execute 1 \
  --query "AI 반도체 시장의 최신 동향은?"
```

### 출력 형식 선택

```bash
# JSON 형식
uv run python -m neos.cli workflow-builder execute 1 \
  --query "AI 반도체 시장의 최신 동향은?" \
  --output json

# 텍스트 형식 (기본값)
uv run python -m neos.cli workflow-builder execute 1 \
  --query "AI 반도체 시장의 최신 동향은?" \
  --output text
```

### Python 코드로 실행

```python
import asyncio
from neos.workflow.builder import WorkflowExecutor

async def run_workflow():
    executor = WorkflowExecutor(workflow_id=1)

    result = await executor.execute({
        "query": "AI 반도체 시장의 최신 동향은?",
        "user_id": "user123",
        "session_id": "session_456"
    })

    if result["success"]:
        print("Response:", result["response"])
        print("Execution time:", result["execution_time_ms"], "ms")
    else:
        print("Error:", result["error"])

asyncio.run(run_workflow())
```

## 사용 예제

### 예제 1: 웹 검색 워크플로우

웹에서 정보를 검색하고 결과를 정리하는 간단한 워크플로우:

```bash
# 1. MCP 서버 등록 (이미 등록되어 있으면 생략)
uv run python -m neos.cli workflow-builder mcp register \
  --name "web_search_mcp" \
  --url "https://api.tavily.com" \
  --type "web_search" \
  --description "웹 검색 서버"

# 2. 워크플로우 생성
uv run python -m neos.cli workflow-builder create \
  --name "simple_web_search" \
  --description "웹 검색 워크플로우" \
  --interactive

# 대화형 모드에서:
# - 노드 1: web_search (mcp_tool, web_search_mcp 선택)
# - 노드 2: response_generator (processor, response_generator 선택)
# - 엣지: web_search -> response_generator
# - 엣지: response_generator -> END

# 3. 워크플로우 활성화
uv run python -m neos.cli workflow-builder activate 1

# 4. 워크플로우 실행
uv run python -m neos.cli workflow-builder execute 1 \
  --query "2024년 AI 산업 동향"
```

### 예제 2: 복합 분석 워크플로우

여러 단계를 거치는 복합 워크플로우:

```python
import asyncio
from neos.workflow.builder import CustomWorkflowBuilder

async def create_analysis_workflow():
    builder = CustomWorkflowBuilder()

    # MCP 서버들 추가
    builder.add_mcp_server("web_search_mcp", 1)
    builder.add_mcp_server("file_processing_mcp", 2)

    # 1단계: 웹 검색
    builder.add_node(
        name="initial_search",
        node_type="mcp_tool",
        config={"max_results": 10, "search_depth": "advanced"},
        mcp_server_name="web_search_mcp"
    )

    # 2단계: 결과 통합
    builder.add_node(
        name="integrate_results",
        node_type="processor",
        config={"processor_type": "result_integrator"}
    )

    # 3단계: 파일 저장
    builder.add_node(
        name="save_to_file",
        node_type="mcp_tool",
        config={"operation": "write", "file_path": "results/analysis.json"},
        mcp_server_name="file_processing_mcp"
    )

    # 4단계: 최종 응답 생성
    builder.add_node(
        name="generate_response",
        node_type="processor",
        config={"processor_type": "response_generator"}
    )

    # 엣지 연결
    builder.add_edge("initial_search", "integrate_results")
    builder.add_edge("integrate_results", "save_to_file")
    builder.add_edge("save_to_file", "generate_response")
    builder.add_edge("generate_response", "END")

    # 워크플로우 저장
    workflow_id = await builder.save(
        name="advanced_analysis",
        description="웹 검색 후 결과를 파일로 저장하고 응답 생성",
        created_by="admin",
        tags=["analysis", "advanced", "file_output"]
    )

    return workflow_id

# 워크플로우 생성 및 실행
workflow_id = asyncio.run(create_analysis_workflow())
print(f"Created workflow ID: {workflow_id}")
```

### 예제 3: 조건부 워크플로우 (고급)

현재 버전에서는 조건부 엣지가 기본적으로만 지원되지만, 향후 업데이트에서 더 복잡한 조건을 추가할 수 있습니다.

## 워크플로우 구조

### 노드 타입

1. **agent**: 기존 에이전트 시스템과 통합
2. **mcp_tool**: MCP 서버의 도구 실행
3. **processor**: 결과 처리 및 변환

### 프로세서 타입

1. **result_integrator**: 여러 단계의 결과를 통합
2. **response_generator**: 최종 응답 생성

### 워크플로우 상태

- **draft**: 작성 중 (기본값)
- **active**: 활성화됨 (실행 가능)
- **inactive**: 비활성화됨
- **archived**: 보관됨

## 데이터베이스 스키마

### 주요 테이블

1. **mcp_servers**: MCP 서버 정보
2. **custom_workflows**: 워크플로우 정의
3. **workflow_mcp_servers**: 워크플로우-MCP 서버 연결
4. **workflow_executions**: 실행 기록

## 모범 사례

1. **명확한 이름 사용**: 워크플로우와 노드에 의미 있는 이름 부여
2. **적절한 태그 활용**: 검색과 분류를 위한 태그 사용
3. **테스트 먼저**: draft 상태로 테스트 후 활성화
4. **실행 기록 모니터링**: workflow_executions 테이블로 성능 분석
5. **버전 관리**: 중요한 변경 시 새 워크플로우로 복사

## 문제 해결

### 워크플로우 실행 실패

1. MCP 서버가 활성화되어 있는지 확인
2. API 키가 올바르게 설정되었는지 확인
3. 노드 연결이 올바른지 확인 (END 노드로 종료)

### 데이터베이스 연결 오류

```bash
# 데이터베이스 상태 확인
uv run python -m neos.cli status
```

### 로그 확인

실행 중 문제가 발생하면 로그를 확인하세요:

```bash
# verbose 모드로 실행
uv run python -m neos.cli --verbose workflow-builder execute 1 --query "test"
```

## 다음 단계

- 더 많은 MCP 서버 통합
- 조건부 엣지 고급 기능
- 시각적 워크플로우 편집기
- 워크플로우 템플릿 라이브러리

## 참고 자료

- [MCP 공식 문서](https://modelcontextprotocol.io/)
- [LangGraph 문서](https://langchain-ai.github.io/langgraph/)
