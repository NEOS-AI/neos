# BigQuery Datasources

## Available Datasets

### Public Datasets
- `bigquery-public-data.usa_names`: 미국 이름 통계
- `bigquery-public-data.covid19_open_data`: COVID-19 데이터
- `bigquery-public-data.stackoverflow`: Stack Overflow 데이터

### Custom Datasets
프로젝트에 따라 커스텀 데이터셋을 추가할 수 있습니다.

## Connection Information
- **Project ID**: 환경변수 `GCP_PROJECT_ID`에서 읽기
- **Credentials**: 환경변수 `GOOGLE_APPLICATION_CREDENTIALS`에서 읽기

## Best Practices
1. 비용 최적화를 위해 쿼리에 LIMIT 절 사용
2. 파티션 테이블 사용 시 WHERE 절로 파티션 필터링
3. 대용량 데이터 조회 시 페이지네이션 사용
