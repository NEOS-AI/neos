---
name: bigquery
type: database
version: 1.0.0
description: BigQuery 데이터베이스 조회 및 분석
capabilities:
  - sql_query
  - data_retrieval
  - data_analysis
  - bigquery
dependencies:
  - google-cloud-bigquery>=3.0.0
---

# BigQuery Skill

## Description
BigQuery 데이터베이스를 조회하고 분석하는 스킬입니다.

## Capabilities
- BigQuery 데이터 조회
- SQL 쿼리 실행
- 데이터 집계 및 분석
- 결과를 다양한 형식으로 변환

## Usage
이 스킬은 Google BigQuery에 연결하여 SQL 쿼리를 실행하고 결과를 반환합니다.

### Parameters
- `query`: 실행할 SQL 쿼리
- `project_id`: GCP 프로젝트 ID (선택사항)
- `dataset_id`: 데이터셋 ID (선택사항)
- `max_results`: 최대 결과 수 (기본값: 1000)

### Example
```python
params = {
    "query": "SELECT * FROM `project.dataset.table` LIMIT 10",
    "max_results": 100
}
result = await skill_manager.execute_skill("bigquery", params)
```

## Requirements
- Google Cloud SDK 설치
- 적절한 인증 정보 (서비스 계정 키 또는 애플리케이션 기본 자격 증명)
- BigQuery API 활성화

## Version
1.0.0
