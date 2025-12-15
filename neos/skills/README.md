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
│   ├── bigquery/
│   ├── docx/
│   ├── pdf/
│   └── research_assistant/
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

## 내장 스킬

NEOS는 총 7개의 내장 스킬을 제공합니다:
- **문서 처리**: BigQuery, DOCX, PDF
- **리서치**: Research Assistant, ArXiv, PubMed, Wikipedia

### 문서 처리 스킬

#### 1. BigQuery Skill
BigQuery 데이터베이스 조회 및 분석

```python
result = await skill_manager.execute_skill(
    "bigquery",
    {
        "query": "SELECT * FROM `project.dataset.table` LIMIT 10",
        "max_results": 100
    }
)
```

#### 2. DOCX Skill
Microsoft Word 문서 처리

```python
# 문서 읽기
result = await skill_manager.execute_skill(
    "docx",
    {
        "action": "read",
        "file_path": "/path/to/document.docx"
    }
)

# 문서 생성
result = await skill_manager.execute_skill(
    "docx",
    {
        "action": "create",
        "file_path": "/path/to/new_document.docx",
        "content": "Hello, World!",
        "options": {"heading": "Introduction"}
    }
)
```

#### 3. PDF Skill
PDF 문서 처리

```python
# PDF 텍스트 추출
result = await skill_manager.execute_skill(
    "pdf",
    {
        "action": "extract_text",
        "file_path": "/path/to/document.pdf",
        "page_numbers": [0, 1, 2]
    }
)
```

### 리서치 스킬

#### 4. Research Assistant Skill
리서치 작업 보조 - 소스 분석, 요약, 참고문헌 정리

```python
# 소스 분석
result = await skill_manager.execute_skill(
    "research_assistant",
    {
        "action": "analyze_source",
        "content": "...",
        "options": {
            "check_credibility": True,
            "extract_key_points": True
        }
    }
)
```

#### 5. ArXiv Skill
학술 논문 검색 - 물리학, 수학, 컴퓨터 과학, AI/ML

```python
# 논문 검색
result = await skill_manager.execute_skill(
    "arxiv",
    {
        "action": "search",
        "query": "large language models transformer",
        "max_results": 10
    }
)

# ArXiv ID로 특정 논문 조회
result = await skill_manager.execute_skill(
    "arxiv",
    {
        "action": "get_by_id",
        "query": "2301.12345"
    }
)
```

#### 6. PubMed Skill
의학/생물학 논문 검색 - 의학, 생명과학, 바이오메디컬

```python
# 의학 논문 검색
result = await skill_manager.execute_skill(
    "pubmed",
    {
        "action": "search",
        "query": "covid-19 vaccine efficacy",
        "max_results": 10
    }
)

# PMID로 특정 논문 조회
result = await skill_manager.execute_skill(
    "pubmed",
    {
        "action": "get_by_pmid",
        "query": "12345678"
    }
)
```

#### 7. Wikipedia Skill
일반 지식 및 배경 정보 검색

```python
# Wikipedia 문서 검색 (영어)
result = await skill_manager.execute_skill(
    "wikipedia",
    {
        "action": "search",
        "query": "artificial intelligence",
        "max_results": 3,
        "lang": "en"
    }
)

# Wikipedia 문서 검색 (한국어)
result = await skill_manager.execute_skill(
    "wikipedia",
    {
        "action": "search",
        "query": "인공지능",
        "lang": "ko"
    }
)
```

### 리서치 스킬 사용 가이드

리서치를 수행할 때 각 스킬의 특성에 맞게 활용하세요:

1. **초기 탐색 단계**
   - **Wikipedia**: 주제에 대한 기본 개념과 배경 지식 습득
   - 일반적인 정의, 역사, 관련 개념 파악

2. **학술 리서치 단계**
   - **ArXiv**: 물리학, 수학, CS, AI/ML 분야의 최신 연구 논문
   - **PubMed**: 의학, 생명과학, 바이오메디컬 분야의 학술 문헌

3. **종합 분석 단계**
   - **Research Assistant**: 수집한 소스들의 품질 평가, 요약, 참고문헌 정리

**추천 워크플로우**:
```
Wikipedia (개념 이해) → ArXiv/PubMed (학술 조사) → Research Assistant (분석 및 정리)
```

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
