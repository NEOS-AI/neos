---
name: openalex
type: research
version: 1.0.0
description: OpenAlex 오픈 학술 메타데이터 검색 - 논문·저자·기관
capabilities:
  - academic_search
  - author_search
  - institution_search
  - open_access_filter
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# OpenAlex Skill

## Description
OpenAlex 의 오픈 학술 메타데이터를 검색합니다. **API 키가 필요 없습니다** — 공개
API 라 크리덴셜 없이 동작하는 몇 안 되는 학술 소스입니다.

## Capabilities
- 논문(work) 검색 및 단건 조회
- 저자 검색
- 기관 검색
- 오픈액세스 논문만 필터

## Usage

### Parameters
- `action`: `"search_works"` · `"search_authors"` · `"search_institutions"` · `"get_work"`
- `query`: 검색 쿼리
- `max_results`: 최대 결과 수 (선택, 기본값 10)
- `year_from` / `year_to`: 연도 범위 (선택)
- `open_access`: `True` 면 OA 논문만 (선택)
- `sort`: `"cited_by_count"` · `"publication_date"` · `"relevance_score"` (선택)

### Example

```python
params = {"action": "search_works", "query": "graph neural network", "open_access": True}
result = await skill_manager.execute_skill("openalex", params)
```

## Requirements
- `httpx` 패키지
- 환경 변수 없음

## Version
1.0.0
