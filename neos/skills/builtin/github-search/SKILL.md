---
name: github-search
type: research
version: 1.0.0
description: GitHub 코드·레포지토리·이슈 검색
capabilities:
  - code_search
  - repository_search
  - issue_search
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# GitHub Search Skill

## Description
GitHub Search API 를 통해 코드·레포지토리·이슈를 검색하는 스킬입니다.

## Capabilities
- 코드 검색 (언어 필터 지원)
- 레포지토리 검색 (stars/forks/updated 정렬)
- 이슈 검색

## Usage

### Parameters
- `action`: `"search_repos"` · `"search_code"` · `"search_issues"`
- `query`: 검색 쿼리
- `max_results`: 최대 결과 수 (선택, 기본값 10)
- `language`: 프로그래밍 언어 필터 (선택)
- `sort`: `"stars"` · `"forks"` · `"updated"` (선택)

### Example

```python
params = {"action": "search_repos", "query": "langgraph", "sort": "stars"}
result = await skill_manager.execute_skill("github-search", params)
```

## Requirements
- `httpx` 패키지
- `GITHUB_API_TOKEN` 환경 변수

## Version
1.0.0
