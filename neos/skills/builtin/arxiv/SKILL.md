---
name: arxiv
type: research
version: 1.0.0
description: ArXiv 학술 논문 검색 - 물리학, 수학, 컴퓨터 과학, AI/ML 등
capabilities:
  - paper_search
  - academic_research
  - arxiv_query
  - metadata_extraction
  - research_support
dependencies:
  - arxiv>=2.1.0
  - langchain-community>=0.0.1
allowed_tools: "WebFetch"
---

# ArXiv Skill

## Description
ArXiv에서 학술 논문을 검색하는 스킬입니다. 물리학, 수학, 컴퓨터 과학, AI/ML 등 다양한 분야의 프리프린트 논문을 검색할 수 있습니다.

## Capabilities
- 키워드 기반 논문 검색
- 논문 메타데이터 추출 (제목, 저자, 초록, 출판일)
- ArXiv ID로 특정 논문 조회
- PDF 링크 제공
- 학술 리서치 지원

## Usage
이 스킬은 langchain_community의 ArxivAPIWrapper를 사용하여 ArXiv API와 통신합니다.

### Parameters
- `action`: 수행할 작업 ("search", "get_by_id")
- `query`: 검색 쿼리 또는 ArXiv ID
- `max_results`: 최대 결과 수 (선택사항, 기본값: 5)
- `sort_by`: 정렬 기준 (선택사항)

### Example

#### 논문 검색
```python
params = {
    "action": "search",
    "query": "large language models transformer",
    "max_results": 10
}

result = await skill_manager.execute_skill("arxiv", params)

# 결과 구조:
# {
#   "papers": [
#     {
#       "title": "논문 제목",
#       "authors": "저자 목록",
#       "published": "출판일",
#       "arxiv_id": "2301.12345",
#       "summary": "논문 초록 (요약)",
#       "full_summary": "논문 전체 초록",
#       "pdf_url": "PDF 다운로드 링크",
#       "entry_url": "ArXiv 페이지 링크"
#     },
#     ...
#   ],
#   "total_results": 10,
#   "query": "large language models transformer"
# }
```

#### ArXiv ID로 특정 논문 조회
```python
params = {
    "action": "get_by_id",
    "query": "2301.12345"
}

result = await skill_manager.execute_skill("arxiv", params)

# 결과 구조: 단일 논문 정보 (papers 배열 없이 직접 반환)
```

## Search Tips
- **특정 분야**: "quantum computing", "machine learning", "natural language processing"
- **저자 검색**: "au:Bengio" (저자 이름)
- **제목 검색**: "ti:transformer" (제목에 포함)
- **초록 검색**: "abs:neural network" (초록에 포함)
- **복합 검색**: "ti:transformer AND au:Vaswani"

## Use Cases
- AI/ML 최신 연구 동향 파악
- 특정 주제에 대한 학술 문헌 조사
- 논문 레퍼런스 수집
- 리서치 프로젝트를 위한 배경 지식 습득
- HyperDeepResearch에서 학술 소스 수집

## Integration with HyperDeepResearch
이 스킬은 HyperDeepResearchAgent와 함께 사용되어 학술 논문 기반 리서치를 수행할 수 있습니다:
- Phase 1: 주제 이해를 위한 관련 논문 검색
- Phase 3: 학술 소스 수집 및 품질 평가
- Phase 4: 심층 분석을 위한 논문 데이터 활용
- Phase 7: 최종 리포트 작성 시 참고문헌 제공

## Requirements
- `langchain-community` 패키지
- `arxiv` 패키지 (ArxivAPIWrapper 의존성)

설치:
```bash
pip install langchain-community arxiv
```

## Version
1.0.0
