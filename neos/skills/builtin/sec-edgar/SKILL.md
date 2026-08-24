---
name: sec-edgar
type: research
version: 1.0.0
description: SEC EDGAR 미국 상장사 공시·재무 보고서 검색
capabilities:
  - filing_search
  - company_filings
  - full_text_search
dependencies:
  - httpx>=0.24.0
allowed_tools: "WebFetch"
---

# SEC EDGAR Skill

## Description
SEC EDGAR 에서 미국 상장사의 공시 문서를 검색합니다. **1차 기관 출처**라 재무·기업
관련 주장의 근거로 쓸 수 있습니다.

## Capabilities
- 공시 전문 검색
- 기업별 공시 목록 조회
- 서식 유형·기간 필터

## Usage

### Parameters
- `action`: `"search_filings"` · `"company_filings"` · `"full_text_search"`
- `query`: 검색어 또는 회사 ticker/CIK
- `form_type`: `"10-K"` · `"10-Q"` · `"8-K"` 등 (선택)
- `max_results`: 최대 결과 수 (선택, 기본값 10)
- `date_from` / `date_to`: `"YYYY-MM-DD"` (선택)

### Example

```python
params = {"action": "company_filings", "query": "AAPL", "form_type": "10-K"}
result = await skill_manager.execute_skill("sec-edgar", params)
```

## Requirements
- `httpx` 패키지
- 환경 변수 없음 (SEC 는 User-Agent 헤더만 요구)

## Version
1.0.0
