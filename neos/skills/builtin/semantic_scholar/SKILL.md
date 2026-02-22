---
name: semantic_scholar
type: research
version: 1.0.0
description: Semantic Scholar 학술 논문 검색 - 인용 그래프, 오픈 액세스 PDF, 풍부한 메타데이터
capabilities:
  - academic_search
  - citation_graph
  - paper_metadata
  - open_access_pdf
  - research_support
  - author_search
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# Semantic Scholar Skill

## Description
Semantic Scholar API를 통해 학술 논문을 검색하고 인용 그래프를 탐색하는 스킬입니다. ArXiv보다 풍부한 메타데이터(인용 수, 오픈 액세스 PDF, 연구 분야)를 제공합니다.

## Capabilities
- 키워드 기반 학술 논문 검색
- 인용 그래프 탐색 (citing/cited papers)
- 논문 메타데이터 추출 (제목, 저자, 초록, 인용 수, 연구 분야)
- 오픈 액세스 PDF 링크 제공
- DOI, ArXiv ID 등 학술 식별자 추출
- 연도별 필터링

## Usage

### Parameters
- `action`: 수행할 작업 ("search", "get_citations", "get_references", "get_paper")
- `query`: 검색 쿼리 또는 Semantic Scholar Paper ID
- `max_results`: 최대 결과 수 (선택사항, 기본값: 10)
- `paper_id`: citation/reference 조회 시 사용
- `year`: 연도 필터 (예: "2020-2025")

### Example

```python
# 논문 검색
params = {"action": "search", "query": "large language models", "max_results": 10}
result = await skill_manager.execute_skill("semantic_scholar", params)

# 인용 그래프 탐색
params = {"action": "get_citations", "paper_id": "paper_id_here", "max_results": 20}
result = await skill_manager.execute_skill("semantic_scholar", params)
```

## Requirements
- `httpx` 패키지 (HTTP 클라이언트)
- Semantic Scholar API Key (선택사항, 무료 API도 사용 가능)

## Version
1.0.0
