# Changelog

## v0.5.0 (2025-10-11)
- [x] WebLookupAgent 도입
  - [x] trafilatura 기반 웹 페이지 콘텐츠 추출
  - [x] 메타데이터 및 구조화된 데이터 추출
  - [x] 검색 결과의 신뢰성 평가 및 필터링

## v0.4.3 (2025-10-11)
- [x] 웹 검색 통계 분석 기능 추가
  - [x] 검색 로그 데이터베이스 스키마 개선
  - [x] 검색 성능 및 품질 메트릭 저장
  - [x] 웹 검색 분석 API 엔드포인트 추가

## v0.4.2 (2025-10-11)
- [x] 웹 검색 로깅 기능 개선
  - [x] Redis 메시지 큐 지원 추가
  - [x] 비동기 로깅 성능 최적화
  - [x] 데이터베이스 스키마 개선 및 인덱스 추가

## v0.4.1 (2025-10-10)
- [x] 🔬 HyperDeepResearch 모드 추가
  - [x] 계획 산출 → 순차적 조사 → 다중 쿼리 서치 → 반복적 심층 분석 → 보고서 섹션별 생성
  - [x] DB 스키마 확장 및 섹션 별 저장 처리
  - [x] HyperDeepResearch CLI 지원
  - [x] HyperDeepResearch API 지원
- [x] HyperDeepResearch 에서 'critical thinking' 기능 도입
- [x] 자기비판 피드백 에이전트 (Self-Criticism Feedback Agent)
  - [x] 피드백 분석 및 추가 연구 트리거링
  - [x] 개선된 보고서 품질 및 정확성

## v0.4 (2025-10-03)

- [x] 멀티 에이전트 LangGraph 워크플로우
- [x] OpenAI + Anthropic 멀티 Provider 지원
- [x] 다층 캐싱 시스템
- [x] 벡터 기반 의미적 검색
- [x] 실시간 WebSocket 통신
- [x] 품질 기반 자동 재처리
- [x] LLM 호출 데이터셋 자동 수집 및 저장
- [x] 🆕 복합검색 에이전트 (Multi-Query Search Agent)
  - [x] 쿼리 복잡도 자동 분석 시스템
  - [x] LLM 기반 다중 쿼리 생성 (2-5개)
  - [x] 병렬 검색 및 요약 처리
  - [x] 종합 분석 리포트 생성
- [x] 🔬 Deep Research 모드
  - [x] 4단계 심층 탐색 프로세스 (초기 탐색 → Gap 분석 → 검증 → 리포트)
  - [x] 체크포인트 시스템 및 진행 상황 추적
  - [x] 대량 소스 수집 (30-50개+)
  - [x] 전문가급 마크다운 리포트 생성
  - [x] CLI 명령어 지원 (`workflow deep-research`)
