# Analytics Backoffice

Clio-like 사용자 행동 패턴 분석 백오피스 시스템입니다. Anthropic의 [Clio](https://www.anthropic.com/research/clio)에서 영감을 받아 프라이버시를 보호하면서 대화 패턴을 분석합니다.

## 주요 기능

### 1. Facet 추출 (Facet Extraction)
- LLM 기반 대화 분석으로 다양한 특성(facet) 추출
- 토픽, 언어, 작업 유형, 의도, 도메인, 복잡도, 감정, 안전성 점수 등
- 자동 요약 및 키워드 생성

### 2. 시멘틱 클러스터링 (Semantic Clustering)
- Sentence Transformers를 사용한 임베딩 생성
- HDBSCAN 알고리즘으로 유사한 대화 자동 그룹화
- UMAP 차원 축소로 2D 시각화

### 3. 계층적 구조 (Hierarchical Structure)
- 재귀적 서브클러스터링으로 트리 형태의 탐색 구조
- LLM 기반 클러스터 이름 및 설명 자동 생성
- 드릴다운 탐색 지원

### 4. 프라이버시 보호 (Privacy Protection)
- K-anonymity: 최소 사용자/대화 수 임계값
- PII 탐지 및 마스킹: 이메일, 전화번호, API 키 등
- 집계 데이터만 노출, 개별 대화 보호

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    Analytics Backoffice                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐   │
│  │   Pipeline   │───▶│  Clustering  │───▶│ Privacy Filter  │   │
│  │  (Facet      │    │  (Embedding  │    │ (Aggregation &  │   │
│  │   Extraction)│    │   + HDBSCAN) │    │  Anonymization) │   │
│  └──────────────┘    └──────────────┘    └─────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    FastAPI Backend                        │   │
│  │  • Analysis Management  • Cluster Queries  • Statistics   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    React Dashboard                        │   │
│  │  • UMAP Visualization  • Cluster Tree  • Facet Charts    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 기술 스택

### Backend
- **FastAPI**: REST API 프레임워크
- **PostgreSQL + pgvector**: 벡터 데이터베이스
- **Celery + Redis**: 비동기 작업 처리
- **Sentence Transformers**: 텍스트 임베딩
- **HDBSCAN**: 클러스터링 알고리즘
- **UMAP**: 차원 축소

### Frontend
- **Next.js 14**: React 프레임워크
- **TypeScript**: 타입 안전성
- **Tailwind CSS**: 스타일링
- **Plotly.js**: 데이터 시각화
- **React Query**: 서버 상태 관리

## 시작하기

### 사전 요구사항
- Docker & Docker Compose
- Node.js 20+
- Python 3.11+
- Anthropic API Key (선택사항, LLM 기반 추출용)

### Docker Compose로 실행

```bash
cd backoffice

# 환경 변수 설정
export ANTHROPIC_API_KEY=your-api-key

# 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f
```

접속:
- 프론트엔드: http://localhost:3001
- 백엔드 API: http://localhost:8001
- API 문서: http://localhost:8001/docs

### 로컬 개발

#### Backend
```bash
cd backoffice/backend

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행
uvicorn main:app --reload --port 8001
```

#### Frontend
```bash
cd backoffice/frontend

# 의존성 설치
npm install

# 개발 서버 실행
npm run dev
```

## API 엔드포인트

### Analysis
- `POST /api/v1/analysis` - 새 분석 생성
- `GET /api/v1/analysis` - 분석 목록 조회
- `GET /api/v1/analysis/{run_id}` - 분석 상세 조회
- `GET /api/v1/analysis/{run_id}/statistics` - 통계 조회
- `DELETE /api/v1/analysis/{run_id}` - 분석 삭제

### Clusters
- `GET /api/v1/clusters/hierarchy/{analysis_run_id}` - 클러스터 계층 조회
- `GET /api/v1/clusters/{cluster_id}` - 클러스터 상세 조회
- `GET /api/v1/clusters/umap/{analysis_run_id}` - UMAP 데이터 조회
- `GET /api/v1/clusters/trending/{analysis_run_id}` - 트렌딩 토픽 조회
- `GET /api/v1/clusters/search/{analysis_run_id}` - 클러스터 검색
- `POST /api/v1/clusters/compare` - 클러스터 비교

## 프로젝트 구조

```
backoffice/
├── backend/
│   ├── app/
│   │   ├── api/              # API 엔드포인트
│   │   │   └── endpoints/
│   │   ├── core/             # 설정 및 데이터베이스
│   │   ├── models/           # SQLAlchemy 모델
│   │   ├── pipeline/         # 분석 파이프라인
│   │   │   ├── facet_extractor.py
│   │   │   ├── clustering.py
│   │   │   ├── hierarchy_builder.py
│   │   │   └── privacy_filter.py
│   │   ├── services/         # 비즈니스 로직
│   │   └── tasks/            # Celery 태스크
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/              # Next.js 앱
│       ├── components/       # React 컴포넌트
│       │   ├── analysis/
│       │   ├── clusters/
│       │   ├── ui/
│       │   └── visualization/
│       ├── hooks/            # 커스텀 훅
│       ├── services/         # API 클라이언트
│       └── types/            # TypeScript 타입
└── docker-compose.yml
```

## 설정

### 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis 연결 문자열 | `redis://localhost:6379/1` |
| `ANTHROPIC_API_KEY` | Anthropic API 키 | - |
| `LLM_MODEL` | 사용할 LLM 모델 | `claude-3-sonnet-20240229` |
| `EMBEDDING_MODEL` | 임베딩 모델 | `all-mpnet-base-v2` |
| `MIN_CLUSTER_SIZE` | 최소 클러스터 크기 | `10` |
| `PRIVACY_MIN_USERS_PER_CLUSTER` | 클러스터당 최소 사용자 | `1000` |

## 향후 계획

- [ ] 실시간 스트리밍 분석
- [ ] 커스텀 Facet 정의 UI
- [ ] 시계열 트렌드 분석
- [ ] 이상 탐지 (Anomaly Detection)
- [ ] 다국어 지원 강화
- [ ] 대시보드 커스터마이징
- [ ] 알림 시스템

## 참고 자료

- [Anthropic Clio Research](https://www.anthropic.com/research/clio)
- [OpenClio (오픈소스 구현)](https://github.com/Phylliida/OpenClio)
- [HDBSCAN Documentation](https://hdbscan.readthedocs.io/)
- [UMAP Documentation](https://umap-learn.readthedocs.io/)
