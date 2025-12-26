---
name: pubmed
type: research
version: 1.0.0
description: PubMed 의학/생물학 논문 검색 - 의학, 생명과학, 바이오메디컬 분야
capabilities:
  - medical_research
  - biomedical_search
  - pubmed_query
  - paper_search
  - metadata_extraction
  - research_support
dependencies:
  - langchain-community>=0.0.1
allowed_tools: "WebFetch"
---

# PubMed Skill

## Description
PubMed에서 의학 및 생물학 분야의 학술 논문을 검색하는 스킬입니다. 의학, 생명과학, 바이오메디컬 분야의 문헌을 검색할 수 있습니다.

## Capabilities
- 키워드 기반 의학 논문 검색
- 논문 메타데이터 추출 (제목, 저자, 초록, 출판일)
- PMID (PubMed ID)로 특정 논문 조회
- PubMed 링크 제공
- 의학 및 바이오메디컬 리서치 지원

## Usage
이 스킬은 langchain_community의 PubMedAPIWrapper를 사용하여 PubMed API와 통신합니다.

### Parameters
- `action`: 수행할 작업 ("search", "get_by_pmid")
- `query`: 검색 쿼리 또는 PMID
- `max_results`: 최대 결과 수 (선택사항, 기본값: 5)

### Example

#### 논문 검색
```python
params = {
    "action": "search",
    "query": "covid-19 vaccine efficacy",
    "max_results": 10
}

result = await skill_manager.execute_skill("pubmed", params)

# 결과 구조:
# {
#   "papers": [
#     {
#       "title": "논문 제목",
#       "authors": "저자 목록",
#       "published": "출판일",
#       "pmid": "12345678",
#       "summary": "논문 초록 (요약)",
#       "full_summary": "논문 전체 초록",
#       "pubmed_url": "PubMed 페이지 링크"
#     },
#     ...
#   ],
#   "total_results": 10,
#   "query": "covid-19 vaccine efficacy"
# }
```

#### PMID로 특정 논문 조회
```python
params = {
    "action": "get_by_pmid",
    "query": "12345678"
}

result = await skill_manager.execute_skill("pubmed", params)

# 결과 구조: 단일 논문 정보 (papers 배열 없이 직접 반환)
```

## Search Tips
- **질병 검색**: "diabetes", "cancer", "alzheimer's disease"
- **치료법 검색**: "immunotherapy", "gene therapy", "vaccine"
- **약물 검색**: "aspirin", "metformin", "remdesivir"
- **저자 검색**: "Smith J[Author]"
- **최근 논문**: "covid-19 AND 2024[PDAT]" (출판 연도 필터)
- **임상 시험**: "clinical trial", "randomized controlled trial"
- **메타 분석**: "meta-analysis", "systematic review"

## Use Cases
- 의학 연구 문헌 조사
- 질병 및 치료법에 대한 최신 연구 동향 파악
- 임상 가이드라인 및 증거 기반 의학 자료 수집
- 약물 효능 및 안전성 연구 조사
- 생명과학 연구 배경 지식 습득
- HyperDeepResearch에서 의학 소스 수집

## Integration with HyperDeepResearch
이 스킬은 HyperDeepResearchAgent와 함께 사용되어 의학/생물학 분야의 리서치를 수행할 수 있습니다:
- Phase 1: 의학 주제 이해를 위한 관련 논문 검색
- Phase 3: 의학 학술 소스 수집 및 품질 평가
- Phase 4: 심층 분석을 위한 의학 논문 데이터 활용
- Phase 7: 최종 리포트 작성 시 의학 참고문헌 제공

## PubMed vs ArXiv
- **PubMed**: 의학, 생명과학, 바이오메디컬 분야 전문
- **ArXiv**: 물리학, 수학, 컴퓨터 과학, AI/ML 분야 전문

리서치 주제에 따라 적절한 스킬을 선택하세요.

## Requirements
- `langchain-community` 패키지

설치:
```bash
pip install langchain-community
```

## Version
1.0.0
