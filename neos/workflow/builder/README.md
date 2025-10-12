# 워크플로우 빌더 모듈 구조

커스텀 워크플로우 빌더가 기능별로 모듈화되어 관리하기 쉬워졌습니다.

## 📁 디렉토리 구조

```
neos/workflow/builder/
├── __init__.py              # 모듈 진입점 (모든 클래스 export)
├── nodes.py                 # 노드와 엣지 정의
├── workflow_builder.py      # 워크플로우 빌더 (생성 및 저장)
├── workflow_executor.py     # 워크플로우 실행기
├── workflow_manager.py      # 워크플로우 관리 (조회, 수정, 삭제)
├── executors.py             # 노드 타입별 실행 로직
└── README.md               # 이 파일
```

## 📄 파일별 설명

### 1. `nodes.py` (70 lines)
노드와 엣지의 기본 정의

**클래스:**
- `WorkflowNode`: 워크플로우 노드 (agent, mcp_tool, processor)
- `WorkflowEdge`: 노드 간 연결 (from, to, condition)

**주요 기능:**
- 노드/엣지를 딕셔너리로 변환 (`to_dict()`)
- 딕셔너리로부터 노드/엣지 생성 (`from_dict()`)

### 2. `workflow_builder.py` (150 lines)
워크플로우 생성 및 저장

**클래스:**
- `CustomWorkflowBuilder`: 워크플로우 빌더

**주요 메서드:**
- `add_node()`: 노드 추가
- `add_edge()`: 엣지 추가
- `add_mcp_server()`: MCP 서버 등록
- `save()`: 데이터베이스에 저장
- `to_dict()`: 워크플로우 정의를 딕셔너리로 변환

**사용 예:**
```python
builder = CustomWorkflowBuilder()
builder.add_node("search", "agent", config={"agent_name": "realtime_info_search"})
builder.add_edge("search", "END")
workflow_id = await builder.save("my_workflow", "설명", "user")
```

### 3. `workflow_executor.py` (280 lines)
워크플로우 실행 및 그래프 관리

**클래스:**
- `WorkflowExecutor`: 워크플로우 실행기

**주요 메서드:**
- `load_workflow()`: DB에서 워크플로우 로드
- `build_graph()`: LangGraph 그래프 빌드
- `execute()`: 워크플로우 실행
- `_create_node_handler()`: 각 노드의 핸들러 생성
- `_save_execution()`: 실행 기록 저장
- `_update_execution_count()`: 실행 횟수 업데이트

**사용 예:**
```python
executor = WorkflowExecutor(workflow_id=1)
result = await executor.execute({
    "query": "AI 동향",
    "user_id": "user123",
    "session_id": "session456"
})
```

### 4. `workflow_manager.py` (110 lines)
워크플로우 관리 (CRUD)

**클래스:**
- `WorkflowManager`: 정적 메서드로 구성된 관리자

**주요 메서드:**
- `list_workflows()`: 워크플로우 목록 조회
- `get_workflow()`: 특정 워크플로우 조회
- `update_workflow_status()`: 상태 변경 (draft, active, inactive, archived)
- `delete_workflow()`: 워크플로우 삭제

**사용 예:**
```python
# 목록 조회
workflows = await WorkflowManager.list_workflows(status=WorkflowStatus.ACTIVE)

# 상태 변경
success = await WorkflowManager.update_workflow_status(1, WorkflowStatus.ACTIVE)
```

### 5. `executors.py` (220 lines)
노드 타입별 실행 로직

**클래스:**
- `NodeExecutor`: 노드 실행기

**주요 메서드:**
- `execute_agent()`: 에이전트 노드 실행
  - 에이전트 레지스트리에서 로드
  - 언어 감지 및 컨텍스트 설정
  - 결과 포맷팅
- `execute_mcp_tool()`: MCP 도구 노드 실행
  - MCP 매니저를 통해 실행
- `execute_processor()`: 프로세서 노드 실행
  - result_integrator: 결과 통합
  - response_generator: 최종 응답 생성

### 6. `__init__.py` (30 lines)
모듈 진입점

**Export 목록:**
```python
__all__ = [
    "WorkflowNode",
    "WorkflowEdge",
    "CustomWorkflowBuilder",
    "WorkflowExecutor",
    "WorkflowManager",
    "NodeExecutor",
]
```

## 🔄 실행 흐름

### 워크플로우 생성
```
CustomWorkflowBuilder
  ↓
add_node() / add_edge()
  ↓
save() → DB 저장
```

### 워크플로우 실행
```
WorkflowExecutor
  ↓
load_workflow() → DB에서 로드
  ↓
build_graph() → LangGraph 생성
  ↓
execute()
  ├─ _create_node_handler()
  │   └─ NodeExecutor.execute_*()
  ↓
_save_execution() → 결과 저장
```

## 📊 모듈화 효과

### Before (1 파일)
```
builder.py (715 lines)
```

### After (6 파일)
```
nodes.py              (70 lines)   - 노드/엣지 정의
workflow_builder.py   (150 lines)  - 빌더
workflow_executor.py  (280 lines)  - 실행기
workflow_manager.py   (110 lines)  - 관리자
executors.py          (220 lines)  - 실행 로직
__init__.py          (30 lines)   - Export
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total                 (860 lines)
```

**장점:**
- ✅ 파일당 평균 140줄 (관리 용이)
- ✅ 기능별 명확한 분리
- ✅ 테스트 및 유지보수 쉬움
- ✅ 확장성 향상
- ✅ Import 경로는 동일 (`from neos.workflow.builder import ...`)

## 💡 사용법

### Import (변경 없음)
```python
# 이전과 동일하게 사용 가능
from neos.workflow.builder import (
    CustomWorkflowBuilder,
    WorkflowExecutor,
    WorkflowManager
)
```

### 개별 모듈 Import (선택사항)
```python
# 필요한 경우 개별 모듈에서 import 가능
from neos.workflow.builder.nodes import WorkflowNode
from neos.workflow.builder.executors import NodeExecutor
```

## 🧪 테스트

모든 기능이 정상 작동함을 확인:

```bash
# CLI 테스트
uv run python -m neos.cli workflow-builder --help
uv run python -m neos.cli workflow-builder agent list

# 예제 실행
uv run python examples/workflow_builder_example.py
uv run python examples/workflow_builder_with_agents_example.py
```

## 📝 향후 확장

모듈화 구조 덕분에 쉽게 추가 가능:

1. **새로운 노드 타입**: `executors.py`에 메서드 추가
2. **조건부 엣지**: `workflow_executor.py`의 `build_graph()` 수정
3. **커스텀 프로세서**: `executors.py`의 `execute_processor()` 확장
4. **워크플로우 템플릿**: 새 파일 `templates.py` 추가
5. **시각화 기능**: 새 파일 `visualizer.py` 추가

## 🔍 변경사항

### 기존 파일
- ✅ `neos/workflow/builder.py` → `neos/workflow/builder_old.py` (백업)

### 새로운 구조
- ✅ `neos/workflow/builder/` (디렉토리)
- ✅ 6개의 모듈 파일

### 영향 없음
- ✅ CLI (`neos/cli_workflow_builder.py`)
- ✅ 예제 파일들 (`examples/*.py`)
- ✅ Import 경로는 모두 동일

## 🎉 완료

워크플로우 빌더가 성공적으로 모듈화되었습니다!
