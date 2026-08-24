---
name: google-scholar
type: research
version: 1.0.0
description: Google Scholar 학술 검색 (SerpAPI 경유)
capabilities:
  - academic_search
  - citation_lookup
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# Google Scholar Skill

## Description
SerpAPI 를 경유해 Google Scholar 학술 문헌을 검색하고 인용 정보를 조회합니다.

## Capabilities
- 학술 문헌 검색 (연도 범위 필터)
- 인용 형식 조회

## Usage

### Parameters
- `action`: `"search"` · `"cite"`
- `query`: 검색 쿼리
- `max_results`: 최대 결과 수 (선택, 기본값 10)
- `year_from` / `year_to`: 연도 범위 (선택)

### Example

```python
params = {"action": "search", "query": "retrieval augmented generation", "year_from": 2023}
result = await skill_manager.execute_skill("google-scholar", params)
```

## Requirements
- `httpx` 패키지
- `SERPAPI_API_KEY` 환경 변수

## Version
1.0.0
