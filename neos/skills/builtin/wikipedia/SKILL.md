---
name: wikipedia
type: research
version: 1.0.0
description: Wikipedia 일반 지식 검색 - 개념 정의, 배경 정보, 일반 지식
capabilities:
  - knowledge_search
  - concept_definition
  - background_research
  - general_information
  - research_support
dependencies:
  - wikipedia>=1.4.0
  - langchain-community>=0.0.1
---

# Wikipedia Skill

## Description
Wikipedia에서 일반 지식과 배경 정보를 검색하는 스킬입니다. 개념 정의, 역사적 배경, 일반 지식 등을 얻을 수 있습니다.

## Capabilities
- 키워드 기반 Wikipedia 문서 검색
- 개념 정의 및 설명 추출
- 배경 정보 및 일반 지식 수집
- 다국어 지원 (한국어, 영어 등)
- 전체 페이지 내용 가져오기
- 리서치 배경 지식 지원

## Usage
이 스킬은 langchain_community의 WikipediaAPIWrapper를 사용하여 Wikipedia API와 통신합니다.

### Parameters
- `action`: 수행할 작업 ("search", "get_page")
- `query`: 검색 쿼리 또는 페이지 제목
- `max_results`: 최대 결과 수 (선택사항, 기본값: 3)
- `load_all_summaries`: 모든 요약 로드 (선택사항, 기본값: False)
- `lang`: 언어 코드 (선택사항, 기본값: "en")

### Example

#### 문서 검색 (영어)
```python
params = {
    "action": "search",
    "query": "artificial intelligence",
    "max_results": 3,
    "lang": "en"
}

result = await skill_manager.execute_skill("wikipedia", params)

# 결과 구조:
# {
#   "articles": [
#     {
#       "title": "문서 제목",
#       "summary": "문서 요약",
#       "content": "문서 내용 (처음 1000자)",
#       "full_content": "문서 전체 내용",
#       "url": "Wikipedia 페이지 URL"
#     },
#     ...
#   ],
#   "total_results": 3,
#   "query": "artificial intelligence",
#   "lang": "en"
# }
```

#### 문서 검색 (한국어)
```python
params = {
    "action": "search",
    "query": "인공지능",
    "max_results": 3,
    "lang": "ko"
}

result = await skill_manager.execute_skill("wikipedia", params)
```

#### 특정 페이지 내용 가져오기
```python
params = {
    "action": "get_page",
    "query": "Machine Learning",
    "lang": "en"
}

result = await skill_manager.execute_skill("wikipedia", params)

# 결과 구조: 단일 문서 정보 (articles 배열 없이 직접 반환)
```

## Search Tips
- **기술 용어**: "machine learning", "neural network", "blockchain"
- **역사적 인물**: "Albert Einstein", "Marie Curie"
- **역사적 사건**: "World War II", "Industrial Revolution"
- **지리적 위치**: "Seoul", "Mount Everest"
- **과학 개념**: "quantum mechanics", "evolution", "photosynthesis"
- **문화**: "Renaissance", "Buddhism", "Jazz"

## Language Support
Wikipedia는 다양한 언어를 지원합니다:
- `"en"`: 영어 (English)
- `"ko"`: 한국어 (Korean)
- `"ja"`: 일본어 (Japanese)
- `"zh"`: 중국어 (Chinese)
- `"es"`: 스페인어 (Spanish)
- `"fr"`: 프랑스어 (French)
- `"de"`: 독일어 (German)

## Use Cases
- 리서치 주제에 대한 기본 지식 습득
- 개념 및 용어 정의 확인
- 역사적 배경 및 맥락 이해
- 일반 지식 수집
- 리서치 시작 단계에서 주제 탐색
- HyperDeepResearch에서 배경 지식 수집

## Integration with HyperDeepResearch
이 스킬은 HyperDeepResearchAgent와 함께 사용되어 일반 지식 기반 리서치를 수행할 수 있습니다:
- Phase 1: 주제에 대한 기본 지식 및 개념 이해
- Phase 2: 배경 정보 수집 및 리서치 범위 설정
- Phase 3: 일반 소스 수집
- Phase 4: 배경 지식을 바탕으로 심층 분석
- Phase 7: 최종 리포트에 배경 설명 추가

## Wikipedia vs ArXiv vs PubMed
- **Wikipedia**: 일반 지식, 개념 정의, 배경 정보
- **ArXiv**: 물리학, 수학, 컴퓨터 과학, AI/ML 학술 논문
- **PubMed**: 의학, 생명과학, 바이오메디컬 학술 논문

리서치 단계와 주제에 따라 적절한 스킬을 조합하여 사용하세요:
1. **초기 탐색**: Wikipedia로 기본 개념 이해
2. **학술 조사**: ArXiv 또는 PubMed로 심층 연구
3. **종합**: 여러 소스를 조합하여 comprehensive 리서치 수행

## Requirements
- `langchain-community` 패키지
- `wikipedia` 패키지 (WikipediaAPIWrapper 의존성)

설치:
```bash
pip install langchain-community wikipedia
```

## Version
1.0.0
