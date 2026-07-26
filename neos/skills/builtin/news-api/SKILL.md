---
name: news-api
type: research
version: 1.0.0
description: NewsAPI - 80,000+ 소스에서 실시간 뉴스 검색
capabilities:
  - news_search
  - realtime_news
  - top_headlines
  - news_by_topic
  - news_by_source
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# News API Skill

## Description
NewsAPI.org를 통해 80,000+ 뉴스 소스에서 실시간 뉴스를 검색하는 스킬입니다. realtime_info intent의 핵심 소스로 활용됩니다.

## Capabilities
- 키워드 기반 뉴스 검색
- 주요 뉴스(Top Headlines) 조회
- 국가/카테고리별 필터링
- 날짜 범위 지정 검색
- 인기도/관련성/최신순 정렬

## Usage

### Parameters
- `action`: 수행할 작업 ("search", "top_headlines")
- `query`: 검색 쿼리
- `max_results`: 최대 결과 수 (선택사항, 기본값: 10)
- `language`: 언어 코드 (선택사항, 기본값: "en")
- `sort_by`: 정렬 기준 ("publishedAt", "relevancy", "popularity")
- `from_date`: 시작 날짜 (ISO 8601 형식)
- `country`: top_headlines 전용, 국가 코드 (예: "us", "kr")
- `category`: top_headlines 전용 ("business", "technology", "science", 등)

### Example

```python
# 뉴스 검색
params = {"action": "search", "query": "AI regulation", "max_results": 10}
result = await skill_manager.execute_skill("news-api", params)

# 주요 뉴스
params = {"action": "top_headlines", "country": "us", "category": "technology"}
result = await skill_manager.execute_skill("news-api", params)
```

## Requirements
- `httpx` 패키지
- `NEWS_API_KEY` 환경 변수 (newsapi.org에서 발급)

## Version
1.0.0
