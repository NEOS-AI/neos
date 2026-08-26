---
name: reddit
type: research
version: 1.0.0
description: Reddit 커뮤니티 토론·의견 검색
capabilities:
  - community_search
  - subreddit_search
  - opinion_gathering
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# Reddit Skill

## Description
Reddit 에서 커뮤니티 토론과 의견을 검색합니다. 1차 자료가 아니라 **의견 소스**이므로,
사실 검증이 필요한 주장에는 별도 출처가 함께 필요합니다.

## Capabilities
- 전체 검색
- 특정 서브레딧 내 검색
- 정렬·기간 필터

## Usage

### Parameters
- `action`: `"search"` · `"subreddit_search"`
- `query`: 검색 쿼리
- `subreddit`: 서브레딧 이름 (선택)
- `max_results`: 최대 결과 수 (선택, 기본값 10)
- `sort`: `"relevance"` · `"hot"` · `"new"` · `"top"` (선택)
- `time_filter`: `"hour"` · `"day"` · `"week"` · `"month"` · `"year"` · `"all"` (선택)

### Example

```python
params = {"action": "subreddit_search", "query": "vector database", "subreddit": "MachineLearning"}
result = await skill_manager.execute_skill("reddit", params)
```

## Requirements
- `httpx` 패키지
- `REDDIT_CLIENT_ID` · `REDDIT_CLIENT_SECRET` 환경 변수

## Version
1.0.0
