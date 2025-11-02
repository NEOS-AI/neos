# NEOS 시스템 아키텍처

## 📐 개요

NEOS는 LangGraph 기반의 멀티 에이전트 AI 시스템으로, 복잡한 쿼리를 여러 전문 에이전트가 협력하여 처리합니다.

## 🏗️ 전체 시스템 구조

```mermaid
graph TB
    A[사용자 쿼리] --> B[쿼리 분류기<br/>+ 복잡도 분석<br/>+ URL 감지]

    B -->|URL 포함| C0[🔗 WebLookUp 에이전트]
    B -->|복잡도 >= 0.5| C[검색 오케스트레이터]
    B --> D[분석 오케스트레이터]
    B --> E[생성 오케스트레이터]

    C0 --> C0A[URL 추출]
    C0A --> C0B[병렬 콘텐츠 추출]
    C0B --> C0C[LLM 분석]

    C -->|간단한 쿼리| C1[지식 검색]
    C -->|간단한 쿼리| C2[실시간 정보 검색]
    C -->|간단한 쿼리| C3[실시간 데이터 검색]
    C -->|복잡한 쿼리| C4[복합검색 에이전트]
    C -->|Deep Research 모드| C5[Deep Research 에이전트]

    C4 --> C4A[다중 쿼리 생성<br/>2-5개]
    C4A --> C4B[병렬 검색 실행]
    C4B --> C4C[병렬 요약 생성]
    C4C --> C4D[최종 종합 분석]

    C5 --> C5A[Phase 1: 초기 탐색<br/>8-10 쿼리]
    C5A --> C5B[Phase 2: Gap 분석]
    C5B --> C5C[Phase 3: 검증]
    C5C --> C5D[Phase 4: 리포트 생성]

    D --> D1[데이터 분석]
    D --> D2[비교 분석]
    D --> D3[웹 콘텐츠 조회]

    E --> E1[이미지 생성]
    E --> E2[API 호출]
    E --> E3[파일 처리]
    E --> E4[작업 생성]

    C0C --> F[결과 통합기]
    C1 --> F
    C2 --> F
    C3 --> F
    C4D --> F
    C5D --> F
    D1 --> F
    D2 --> F
    D3 --> F
    E1 --> F
    E2 --> F
    E3 --> F
    E4 --> F

    F --> G[품질 검증기]
    G --> H[응답 생성기]
    G -->|품질 낮음| C
    H --> I[최종 응답]

    style C0 fill:#e8f5e9
    style C0A fill:#c8e6c9
    style C0B fill:#c8e6c9
    style C0C fill:#c8e6c9
    style C4 fill:#e1f5fe
    style C4A fill:#b3e5fc
    style C4B fill:#b3e5fc
    style C4C fill:#b3e5fc
    style C4D fill:#b3e5fc
    style C5 fill:#fff3e0
    style C5A fill:#ffe0b2
    style C5B fill:#ffe0b2
    style C5C fill:#ffe0b2
    style C5D fill:#ffe0b2
```

## 🎯 핵심 컴포넌트

### 1. 쿼리 분류기 (Query Classifier)
- **역할**: 사용자 쿼리 분석 및 적절한 에이전트 선택
- **기능**:
  - 언어 감지
  - 복잡도 분석 (0.0-1.0)
  - URL 감지 및 추출
  - 의도 분류
- **출력**: 필요한 에이전트 목록 및 메타데이터

### 2. 검색 오케스트레이터 (Search Orchestrator)
- **역할**: 검색 에이전트들의 병렬 실행 관리
- **지원 에이전트**:
  - Knowledge Search (지식 기반)
  - Realtime Info Search (실시간 정보)
  - Realtime Data Search (실시간 데이터)
  - Multi-Query Search (복합 검색)
  - Deep Research (심층 조사)
  - WebLookUp (URL 콘텐츠 추출)
- **최적화**:
  - MCP 도구 통합
  - 결과 중복 제거
  - 캐싱 (1800초 TTL)

### 3. 분석 오케스트레이터 (Analysis Orchestrator)
- **역할**: 수집된 데이터 분석
- **지원 에이전트**:
  - Data Analysis (데이터 분석)
  - Comparative Analysis (비교 분석)
  - Web Content Analysis (웹 콘텐츠 분석)

### 4. 생성 오케스트레이터 (Generation Orchestrator)
- **역할**: 콘텐츠 생성 및 API 호출
- **지원 에이전트**:
  - Image Generation (이미지 생성)
  - API Call (외부 API)
  - File Processing (파일 처리)
  - Task Creation (작업 생성)

### 5. 결과 통합기 (Result Processor)
- **역할**: 여러 에이전트 결과 통합
- **기능**:
  - 결과 병합 및 정규화
  - 중요도 기반 정렬
  - 메타데이터 통합

### 6. 품질 검증기 (Quality Validator)
- **역할**: 응답 품질 평가 및 재처리 트리거
- **평가 기준**:
  - 완전성
  - 관련성
  - 정확성
- **임계값**: 0.4 (최소 품질 점수)
- **재시도**: 최대 2회

### 7. 응답 생성기 (Response Generator)
- **역할**: 최종 사용자 응답 생성
- **기능**:
  - 자연어 응답 생성
  - 인용 및 소스 포함
  - 다국어 지원

## 🔄 워크플로우 실행 흐름

### 1. 간단한 정보 검색
```
사용자 쿼리 → 쿼리 분류 → 검색 실행 → 결과 통합 → 응답 생성
소요 시간: 2-5초
```

### 2. 복잡한 분석
```
사용자 쿼리 → 복잡도 분석 (≥0.5) → 복합검색 → 병렬 처리 → 종합 분석 → 응답
소요 시간: 10-30초
```

### 3. Deep Research
```
사용자 쿼리 → Deep Research 선택 → 4단계 탐색 → 검증 → 리포트 생성
소요 시간: 15-30분
```

### 4. URL 콘텐츠 분석
```
URL 쿼리 → URL 감지 → WebLookUp 선택 → 콘텐츠 추출 → LLM 분석 → 응답
소요 시간: 5-15초 (정적) / 10-30초 (동적)
```

## 🛠️ 기술 스택

### 핵심 프레임워크
- **FastAPI**: 비동기 웹 프레임워크
- **LangGraph**: 상태 기반 에이전트 워크플로우
- **CrewAI**: 협력적 AI 에이전트 시스템

### 데이터베이스 & 캐싱
- **PostgreSQL + pgvector**: 벡터 임베딩 지원
- **Redis**: 고성능 캐싱 (TTL 기반)

### AI 서비스
- **OpenAI GPT-4**: 언어 모델 및 임베딩
- **OpenAI DALL-E 3**: 이미지 생성
- **Tavily**: 실시간 웹 검색

### 도구 & 라이브러리
- **aiohttp**: 비동기 HTTP 클라이언트
- **BeautifulSoup4**: HTML 파싱
- **Playwright**: 동적 페이지 렌더링
- **SQLAlchemy**: 비동기 ORM
- **Pydantic**: 데이터 검증

## 📊 성능 특성

### 캐싱 전략
| 유형 | TTL | 용도 |
|------|-----|------|
| 검색 결과 | 30분 | 중복 검색 방지 |
| 임베딩 | 24시간 | 쿼리 임베딩 재사용 |
| 세션 | 1시간 | 사용자 세션 유지 |

### 타임아웃 설정
| 작업 | 타임아웃 |
|------|---------|
| 단일 검색 | 30초 |
| 복합 검색 | 10분 |
| Deep Research | 30분 |
| WebLookUp (정적) | 30초 |
| WebLookUp (동적) | 60초 |

### 병렬 처리
- 검색 에이전트: 동시 실행
- 요약 생성: asyncio.gather 사용
- URL 다운로드: 병렬 (정적) / 순차 (동적)

## 🔐 보안 고려사항

### API 키 관리
- 환경 변수로 관리
- 설정 파일 암호화
- 키 로테이션 지원

### 입력 검증
- 쿼리 길이 제한 (10,000자)
- URL 유효성 검증
- SQL 인젝션 방지
- XSS 공격 방지

### 데이터베이스 보안
- 연결 풀 관리
- 사용자별 권한 설정
- 민감 정보 암호화

## 📈 확장성

### 수평 확장
- Docker/Kubernetes 지원
- 상태 비저장 API 설계
- Redis를 통한 세션 공유

### 성능 최적화
- 연결 풀링
- 벡터 검색 인덱스
- 쿼리 결과 캐싱
- 비동기 I/O

## 🔗 관련 문서

- [WebLookUp Agent 상세](./WEB_LOOKUP_AGENT.md)
- [Deep Research 가이드](./DEEP_RESEARCH_GUIDE.md)
- [API 문서](./API_REFERENCE.md)
- [CLI 가이드](./CLI_GUIDE.md)
