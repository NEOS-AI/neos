# NEOS Skills System

Skills는 AI 에이전트에게 특정 도메인의 전문성을 부여하는 확장 모듈 시스템입니다.

## 개념

Skills는 본질적으로 **AI를 사람의 업무 환경에 맞게 학습시키는 방법**입니다. Anthropic은 이를 "AI에게 온보딩(Onboarding)을 시키는 방식"으로 표현합니다. 즉, 새로 입사한 직원에게 회사의 규칙, 문서 스타일, 절차 등을 교육하듯, LLM에게도 그런 정보를 'Skills' 형태로 전달할 수 있습니다.

### 기존 프롬프트 방식과의 차이

- **프롬프트 방식**: 매번 AI에게 지시를 반복해야 함
- **Skills 방식**: 지속적이고 일관된 맥락(Context)을 제공하여 특정 도메인의 전문가처럼 행동

## 아키텍처

Skills 시스템은 NEOS의 기존 패턴을 따릅니다:

```
neos/skills/
├── base/
│   ├── skill.py          # BaseSkill 추상 클래스
│   ├── result.py         # SkillResult 클래스
│   └── types.py          # SkillType enum
├── manager/
│   ├── skill_manager.py  # SkillManager 클래스
│   └── skill_registry.py # SkillRegistry 클래스
├── builtin/              # 내장 스킬들
│   ├── docx/
│   ├── pdf/
│   ├── arxiv/
│   ├── pubmed/
│   └── ...
└── README.md
```

### 핵심 컴포넌트

1. **BaseSkill**: 모든 스킬의 기본 클래스
   - `initialize()`: 스킬 초기화
   - `execute()`: 스킬 실행
   - `cleanup()`: 리소스 정리

2. **SkillManager**: 스킬 라이프사이클 관리
   - 스킬 등록
   - 스킬 초기화
   - 스킬 실행

3. **SkillRegistry**: 스킬 검색 및 관리
   - 스킬 목록 조회
   - Capability 기반 검색
   - 타입별 필터링

## 내장 스킬 (2026-10-11)

`neos/skills/builtin/` 의 15개는 기동 때 자동 발견된다(`SkillManager.register_builtin_skills()`).
정본은 각 디렉터리의 `SKILL.md` 다 — 이 표는 요약이다.

| 스킬 | 자동 실행 | 비고 |
|---|---|---|
| arxiv · pubmed · wikipedia · openalex · semantic-scholar · google-scholar · sec-edgar · github-search · reddit · news-api | ✅ | 검색형. google-scholar 는 SerpAPI 키, news-api 는 NewsAPI 키가 있어야 초기화된다 |
| research-assistant | ✅ (2단계) | 검색형 결과를 `content` 로 받아 요약·분석한다 |
| docx · pdf | — | 채팅 첨부는 N8(`neos/services/attachment_blocks.py`)이 모델에 직접 붙인다 |
| cron · canvas | — | 각자 `TASK_SCHEDULING` · `UI_FRAME` 경로가 있다 |

## 메인 그래프에서의 실행

`workflow.skill_execution.enabled` 가 켜지면(development 기본) 셀렉터가
`skill_calls=[{name, params, reason}]` 를 내고 `SKILL_EXECUTOR` 노드가 실행한다.
후보는 `SKILL.md` 에 `auto_execute: true` 를 단 스킬뿐이다. 결과는 각 스킬의
`to_search_results()` 로 `search_results` 에 들어간다.
설계: `docs/superpowers/specs/2026-10-11-builtin-skill-executor-design.md`

새 스킬을 자동 실행 후보로 만들려면: `get_input_schema()` 가 `execute` 가 읽는 키와
같아야 하고(`tests/skills/test_skill_input_schemas.py`), `to_search_results()` 를
구현해야 한다(`tests/skills/test_skill_search_results.py`).

## Workflow 통합

Skills는 Workflow의 노드로 사용할 수 있습니다:

```python
from neos.workflow.builder import CustomWorkflowBuilder

builder = CustomWorkflowBuilder()

# Skill 노드 추가
builder.add_node(
    name="analyze_document",
    node_type="skill",
    config={
        "skill_name": "pdf",
        "params": {
            "action": "extract_text",
            "file_path": "${state.file_path}"
        }
    }
)
```

## HyperDeepResearch 통합

HyperDeepResearchAgent는 Research Assistant Skill을 사용하여 리서치 품질을 향상시킵니다:

```python
# 에이전트는 자동으로 스킬을 사용
agent = HyperDeepResearchAgent()

# 리서치 실행 시 스킬이 자동으로 활용됨
result = await agent.execute(query, context)
```

## API 엔드포인트

### 스킬 목록 조회
```http
GET /api/v1/skills
GET /api/v1/skills?skill_type=document
```

### 특정 스킬 정보
```http
GET /api/v1/skills/{skill_name}
```

### 스킬 초기화
```http
POST /api/v1/skills/{skill_name}/initialize
```

### 스킬 실행
```http
POST /api/v1/skills/{skill_name}/execute
Content-Type: application/json

{
  "skill_name": "pdf",
  "params": {
    "action": "extract_text",
    "file_path": "/path/to/document.pdf"
  }
}
```

### 모든 스킬 초기화
```http
POST /api/v1/skills/initialize-all
```

## 커스텀 스킬 개발

### 1. 스킬 클래스 작성

```python
from neos.skills.base import BaseSkill, SkillResult, SkillType

class MyCustomSkill(BaseSkill):
    def __init__(self, **kwargs):
        super().__init__(
            name="my_custom_skill",
            skill_type=SkillType.CUSTOM,
            description="My custom skill description",
            capabilities=["capability1", "capability2"],
            version="1.0.0",
            **kwargs
        )

    async def initialize(self) -> bool:
        # 초기화 로직
        self.is_available = True
        return True

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        # 실행 로직
        try:
            # 작업 수행
            result_data = {"message": "Success"}

            return SkillResult.success_result(
                data=result_data,
                skill_name=self.name
            )
        except Exception as e:
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name
            )

    async def cleanup(self) -> None:
        # 정리 로직
        self.is_available = False
```

### 2. 스킬 등록

```python
from neos.skills.manager import skill_manager, SkillInfo

skill_info = SkillInfo(
    name="my_custom_skill",
    skill_class=MyCustomSkill,
    skill_type=SkillType.CUSTOM,
    description="My custom skill",
    capabilities=["capability1", "capability2"],
    version="1.0.0"
)

skill_manager.register_custom_skill(skill_info)
```

### 3. 스킬 사용

```python
# 초기화
await skill_manager.initialize_skill("my_custom_skill")

# 실행
result = await skill_manager.execute_skill(
    "my_custom_skill",
    {"param1": "value1"}
)
```

## 스킬 디렉토리 구조

각 스킬은 다음과 같은 구조를 가집니다:

```
skills/builtin/my_skill/
├── SKILL.md          # 스킬 설명 및 사용법
├── __init__.py       # 스킬 export
├── skill.py          # 스킬 구현
└── [optional files]  # 추가 리소스 파일
```

### SKILL.md 예시

```markdown
# My Skill

## Description
스킬에 대한 설명

## Capabilities
- capability1
- capability2

## Usage
사용 방법

## Requirements
필요한 패키지나 설정

## Version
1.0.0
```

## 모범 사례

### 1. 에러 처리
항상 try-except를 사용하여 에러를 처리하고 SkillResult.error_result()를 반환합니다.

### 2. 리소스 관리
cleanup() 메서드에서 모든 리소스를 정리합니다.

### 3. 파라미터 검증
execute() 메서드 시작 부분에서 필수 파라미터를 검증합니다.

### 4. 로깅
중요한 작업에 대해 로깅을 추가합니다.

```python
import logging
logger = logging.getLogger(__name__)

logger.info(f"Executing skill with params: {params}")
logger.error(f"Skill execution failed: {e}")
```

### 5. 메타데이터
실행 결과에 유용한 메타데이터를 포함합니다.

```python
return SkillResult.success_result(
    data=result_data,
    skill_name=self.name,
    metadata={
        "execution_time_ms": execution_time,
        "source_count": len(sources),
        # ... 기타 메타데이터
    }
)
```

## 라이센스

이 프로젝트는 MIT 라이센스 하에 있습니다.
