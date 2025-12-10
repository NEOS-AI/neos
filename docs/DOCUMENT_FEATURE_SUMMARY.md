# Document Management Feature Summary

NEOS에 새로 추가된 문서 관리 기능에 대한 요약입니다.

## 개요

이 기능을 통해 사용자는 문서를 업로드하고, LLM을 활용한 지식 그래프 추출, 임베딩 기반 시맨틱 검색, Full-Text Search를 수행할 수 있습니다.

---

## 추가된 파일

### 1. 데이터베이스 모델
- `neos/database/models.py` (수정)
  - `Document`: 문서 메타데이터 및 파일 정보
  - `DocumentChunk`: 문서 청크 (임베딩 포함)
  - `KnowledgeGraph`: 지식 그래프 엔티티 및 관계

### 2. 스토리지 서비스
- `neos/storage/`
  - `__init__.py`: 모듈 초기화
  - `storage_service.py`: S3/rustfs/로컬 스토리지 추상화
    - `StorageProvider`: 추상 인터페이스
    - `S3StorageProvider`: AWS S3 및 S3-compatible 스토리지
    - `LocalStorageProvider`: 로컬 파일 시스템
    - `StorageService`: 팩토리 및 유틸리티

### 3. 문서 처리 파이프라인
- `neos/pipelines/document/`
  - `__init__.py`: 모듈 초기화
  - `chunker.py`: 문서 청킹 유틸리티
    - `DocumentChunker`: 문장 경계 존중 청킹
    - 헤딩 계층 구조 보존
  - `knowledge_graph.py`: LLM 기반 지식 그래프 추출
    - `KnowledgeGraphExtractor`: 엔티티/관계 추출
    - 배치 처리 및 결과 병합
  - `document_processor.py`: 메인 처리 파이프라인
    - `DocumentProcessor`: 전체 파이프라인 오케스트레이션
    - 파일 업로드 → 텍스트 추출 → 청킹 → 임베딩 → 지식 그래프

### 4. API 엔드포인트
- `neos/api/document_routes.py`
  - `POST /api/v1/documents/upload`: 문서 업로드
  - `GET /api/v1/documents/`: 문서 목록
  - `GET /api/v1/documents/{id}`: 문서 상세
  - `DELETE /api/v1/documents/{id}`: 문서 삭제
  - `GET /api/v1/documents/{id}/chunks`: 청크 조회
  - `GET /api/v1/documents/{id}/knowledge-graph`: 지식 그래프
  - `POST /api/v1/documents/search`: 시맨틱 검색

- `neos/main.py` (수정): 라우터 등록

### 5. 설정
- `neos/config/settings.py` (수정)
  - 스토리지 설정 (S3, rustfs, local)
  - 문서 처리 설정 (청킹, 지식 그래프)
- `.env.template` (수정): 새 환경 변수 추가
- `pyproject.toml` (수정): boto3 의존성 추가

### 6. 문서
- `docs/DOCUMENT_MANAGEMENT.md`: 전체 기능 문서
- `docs/DOCUMENT_SETUP_GUIDE.md`: 설치 및 설정 가이드
- `docs/DOCUMENT_FEATURE_SUMMARY.md`: 이 파일

---

## 주요 기능

### 1. 다중 스토리지 지원
- **AWS S3**: 프로덕션 환경
- **rustfs**: S3-compatible 스토리지
- **로컬**: 개발 및 테스트

### 2. 지능형 문서 처리
- **자동 텍스트 추출**: PDF, DOCX, TXT, MD 등
- **스마트 청킹**: 문장 경계 존중, 헤딩 계층 보존
- **병렬 임베딩**: 배치 처리로 성능 최적화

### 3. LLM 기반 지식 그래프
- **엔티티 추출**: 사람, 조직, 개념, 이벤트 등
- **관계 추출**: works_for, founded, located_in 등
- **신뢰도 점수**: 각 엔티티/관계의 신뢰도

### 4. 시맨틱 검색
- **pgvector 활용**: 코사인 유사도 검색
- **임베딩 캐싱**: Redis 기반 자동 캐싱
- **빠른 검색**: 벡터 인덱스 지원

### 5. Full-Text Search
- **PostgreSQL FTS**: ts_vector 및 GIN 인덱스
- **다국어 지원**: 영어, 한국어 등

---

## 아키텍처

```
┌─────────────────┐
│   User/Client   │
└────────┬────────┘
         │
         │ HTTP/REST
         ▼
┌─────────────────────────────────────────────┐
│            FastAPI Application              │
│  ┌─────────────────────────────────────┐  │
│  │    Document Routes                   │  │
│  │  - Upload                            │  │
│  │  - List/Get/Delete                   │  │
│  │  - Search                            │  │
│  └──────────────┬──────────────────────┘  │
└─────────────────┼─────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│        Document Processor Pipeline          │
│  ┌────────────────────────────────────┐    │
│  │ 1. File Validation                 │    │
│  │ 2. Storage Upload (S3/rustfs/local)│    │
│  │ 3. Text Extraction                 │    │
│  │ 4. Document Chunking               │    │
│  │ 5. Embedding Generation            │    │
│  │ 6. Knowledge Graph Extraction (LLM)│    │
│  │ 7. Database Storage                │    │
│  └────────────────────────────────────┘    │
└─────────────────┬───────────────────────────┘
                  │
     ┌────────────┼────────────┐
     │            │            │
     ▼            ▼            ▼
┌─────────┐  ┌─────────┐  ┌──────────┐
│PostgreSQL│  │  Redis  │  │ S3/rustfs│
│+pgvector │  │ (Cache) │  │ (Storage)│
└─────────┘  └─────────┘  └──────────┘
```

---

## 데이터 흐름

### 문서 업로드
```
Client
  │
  ├─→ POST /api/v1/documents/upload
  │   (file, user_id, metadata)
  │
  ▼
DocumentProcessor
  │
  ├─→ 1. Validate file (size, type)
  ├─→ 2. Compute SHA-256 hash
  ├─→ 3. Generate storage key
  ├─→ 4. Upload to S3/rustfs/local
  ├─→ 5. Extract text (multimodal pipeline)
  ├─→ 6. Chunk text (DocumentChunker)
  ├─→ 7. Generate embeddings (batch)
  ├─→ 8. Extract knowledge graph (LLM)
  │
  ▼
Database
  ├─→ documents table
  ├─→ document_chunks table (with embeddings)
  └─→ knowledge_graphs table
```

### 시맨틱 검색
```
Client
  │
  ├─→ POST /api/v1/documents/search
  │   {"query": "...", "top_k": 5}
  │
  ▼
EmbeddingService
  │
  ├─→ Generate query embedding
  │   (cache if available)
  │
  ▼
PostgreSQL (pgvector)
  │
  ├─→ SELECT ... ORDER BY embedding <=> query_embedding
  │   (cosine similarity search)
  │
  ▼
Client
  └─← [{"chunk_text": "...", "similarity": 0.92}, ...]
```

---

## 설정 옵션

### 환경 변수

| 변수 | 기본값 | 설명 |
|-----|--------|------|
| `STORAGE_PROVIDER` | `local` | 스토리지 타입 (s3/rustfs/local) |
| `S3_BUCKET_NAME` | `neos-documents` | S3 버킷 이름 |
| `LOCAL_STORAGE_PATH` | `storage/documents` | 로컬 스토리지 경로 |
| `MAX_FILE_SIZE` | `52428800` | 최대 파일 크기 (50MB) |
| `CHUNK_SIZE` | `1000` | 청크 크기 (문자 수) |
| `CHUNK_OVERLAP` | `200` | 청크 오버랩 (문자 수) |
| `KG_EXTRACTION_ENABLED` | `true` | 지식 그래프 추출 활성화 |
| `KG_EXTRACTION_MODEL` | `gpt-4-turbo-preview` | 지식 그래프 추출 모델 |
| `KG_MIN_CONFIDENCE` | `0.7` | 최소 신뢰도 임계값 |

---

## 성능 특성

### 처리 시간 (예상)

| 문서 크기 | 텍스트 추출 | 청킹 | 임베딩 | 지식 그래프 | 총 시간 |
|---------|-----------|-----|-------|----------|--------|
| 1 페이지 | 1-2초 | <1초 | 2-3초 | 5-10초 | 10-15초 |
| 10 페이지 | 5-10초 | 1-2초 | 10-15초 | 30-60초 | 50-90초 |
| 100 페이지 | 30-60초 | 5-10초 | 60-90초 | 5-10분 | 7-12분 |

*참고: 실제 시간은 하드웨어, 네트워크, LLM API 속도에 따라 다름*

### 최적화 팁

1. **지식 그래프 비활성화**: 50-70% 시간 단축
2. **청크 크기 증가**: 임베딩 API 호출 감소
3. **배치 처리**: 여러 문서 동시 처리
4. **Redis 캐싱**: 임베딩 재사용

---

## 보안 고려사항

### 1. 파일 검증
- 파일 크기 제한
- 확장자 화이트리스트
- MIME 타입 검증

### 2. 접근 제어
- 사용자별 문서 격리
- API 엔드포인트 인증 (구현 필요)

### 3. 데이터 암호화
- S3 버킷 암호화 (서버/클라이언트)
- 전송 중 암호화 (HTTPS)

### 4. 입력 검증
- SQL 인젝션 방지 (SQLAlchemy ORM)
- XSS 방지 (FastAPI 자동 처리)

---

## 확장 가능성

### 단기 확장 (1-2주)
- [ ] 문서 버전 관리
- [ ] 사용자별 권한 관리
- [ ] 문서 태그 및 카테고리
- [ ] 배치 업로드

### 중기 확장 (1-2개월)
- [ ] 지식 그래프 시각화
- [ ] 문서 간 관계 분석
- [ ] 다국어 FTS
- [ ] OCR 지원 (이미지 문서)

### 장기 확장 (3-6개월)
- [ ] 실시간 문서 협업
- [ ] 자동 문서 요약
- [ ] 질문-답변 시스템
- [ ] 문서 추천 시스템

---

## 사용 예제

### Python API
```python
from neos.pipelines.document.document_processor import DocumentProcessor

processor = DocumentProcessor()
document = await processor.process_document(
    file_obj=open("doc.pdf", "rb"),
    filename="doc.pdf",
    user_id="user123",
)
```

### REST API
```bash
curl -X POST "http://localhost:8518/api/v1/documents/upload" \
  -F "file=@doc.pdf" \
  -F "user_id=user123"
```

### 시맨틱 검색
```bash
curl -X POST "http://localhost:8518/api/v1/documents/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "AI history", "top_k": 5}'
```

---

## 테스트

### 단위 테스트
```bash
pytest tests/test_document_processor.py
pytest tests/test_storage_service.py
pytest tests/test_knowledge_graph.py
```

### 통합 테스트
```bash
pytest tests/test_document_api.py
```

---

## 의존성

### 새로 추가된 의존성
- `boto3>=1.35.0`: AWS S3 SDK

### 기존 의존성 활용
- `aiofiles>=24.1.0`: 비동기 파일 I/O
- `pgvector>=0.4.1`: PostgreSQL 벡터 확장
- `sqlalchemy>=2.0.43`: ORM
- `fastapi>=0.116.1`: REST API 프레임워크
- `openai>=1.104.2`: 임베딩 및 LLM

---

## 참고 자료

### 문서
- [DOCUMENT_MANAGEMENT.md](./DOCUMENT_MANAGEMENT.md): 전체 기능 문서
- [DOCUMENT_SETUP_GUIDE.md](./DOCUMENT_SETUP_GUIDE.md): 설치 가이드

### 코드
- [document_processor.py](../neos/pipelines/document/document_processor.py): 메인 파이프라인
- [storage_service.py](../neos/storage/storage_service.py): 스토리지 추상화
- [knowledge_graph.py](../neos/pipelines/document/knowledge_graph.py): 지식 그래프 추출

---

## 다음 단계

1. **설치 가이드 읽기**: [DOCUMENT_SETUP_GUIDE.md](./DOCUMENT_SETUP_GUIDE.md)
2. **API 문서 확인**: `http://localhost:8518/docs`
3. **프로덕션 배포**: 환경 변수, 보안, 모니터링 설정

---

## 기여

이 기능에 대한 피드백이나 개선 제안은 GitHub Issues에 제출해주세요.

## 라이선스

NEOS 프로젝트 라이선스를 따릅니다.
