# Document Management System

NEOS의 문서 관리 시스템은 LLM을 활용한 지식 그래프 추출, 임베딩 기반 시맨틱 검색, 그리고 Full-Text Search(FTS)를 제공합니다.

## 목차

1. [기능 개요](#기능-개요)
2. [아키텍처](#아키텍처)
3. [설치 및 설정](#설치-및-설정)
4. [사용 방법](#사용-방법)
5. [API 레퍼런스](#api-레퍼런스)
6. [고급 기능](#고급-기능)

---

## 기능 개요

### 주요 기능

1. **문서 업로드 및 저장**
   - S3, rustfs, 로컬 스토리지 지원
   - 파일 해시 계산 및 중복 방지
   - 메타데이터 관리

2. **자동 텍스트 추출**
   - PDF, DOCX, TXT, MD, CSV, XLSX, PPTX 등 지원
   - 기존 multimodal pipeline 활용

3. **문서 청킹 (Chunking)**
   - 문장 경계 존중 청킹
   - 고정 크기 청킹
   - 헤딩 계층 구조 보존

4. **LLM 기반 지식 그래프 추출**
   - 엔티티 추출 (사람, 조직, 개념, 이벤트 등)
   - 관계 추출 (works_for, founded, located_in 등)
   - 신뢰도 점수 계산

5. **임베딩 및 시맨틱 검색**
   - OpenAI 임베딩 (1536차원)
   - pgvector를 활용한 벡터 유사도 검색
   - 배치 임베딩 처리

6. **Full-Text Search (FTS)**
   - PostgreSQL의 ts_vector 활용
   - 다국어 지원

---

## 아키텍처

### 데이터베이스 스키마

```
documents
├── id (PK)
├── user_id (FK → users.user_id)
├── filename
├── original_filename
├── file_size
├── mime_type
├── file_hash (SHA-256)
├── storage_provider (s3/rustfs/local)
├── storage_bucket
├── storage_key
├── storage_url
├── processing_status
├── kg_extracted
├── embedding_processed
├── fts_indexed
├── metadata (JSONB)
└── timestamps

document_chunks
├── id (PK)
├── document_id (FK → documents.id)
├── chunk_index
├── chunk_text
├── chunk_size
├── embedding (vector[1536])
├── page_number
├── chunk_type
├── heading_hierarchy
└── metadata (JSONB)

knowledge_graphs
├── id (PK)
├── document_id (FK → documents.id)
├── entity_id
├── entity_type
├── entity_name
├── entity_description
├── entity_embedding (vector[1536])
├── relations (JSONB)
├── properties (JSONB)
├── occurrences (JSONB)
├── confidence_score
└── importance_score
```

### 처리 파이프라인

```
1. 파일 업로드
   ↓
2. 파일 검증 (크기, 확장자)
   ↓
3. 해시 계산 (SHA-256)
   ↓
4. 스토리지 업로드 (S3/rustfs/local)
   ↓
5. 텍스트 추출 (multimodal pipeline)
   ↓
6. 문서 청킹
   ↓
7. 임베딩 생성 (병렬)
   ↓
8. 지식 그래프 추출 (LLM)
   ↓
9. DB 저장 (청크, 엔티티, 관계)
   ↓
10. 처리 완료
```

---

## 설치 및 설정

### 1. 의존성 설치

```bash
# boto3 (S3 지원)
pip install boto3

# aiofiles (비동기 파일 I/O)
pip install aiofiles
```

### 2. 환경 변수 설정

`.env` 파일에 다음 설정을 추가하세요:

```bash
# 스토리지 설정
STORAGE_PROVIDER=local  # s3, rustfs, local

# S3 설정 (AWS S3 사용 시)
S3_BUCKET_NAME=neos-documents
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# rustfs 설정 (S3-compatible 사용 시)
RUSTFS_BUCKET_NAME=neos-documents
RUSTFS_ENDPOINT_URL=https://your-rustfs-endpoint.com
RUSTFS_ACCESS_KEY=your_access_key
RUSTFS_SECRET_KEY=your_secret_key

# 로컬 스토리지 설정
LOCAL_STORAGE_PATH=storage/documents

# 문서 처리 설정
MAX_FILE_SIZE=52428800  # 50MB
CHUNK_SIZE=1000  # 문자 수
CHUNK_OVERLAP=200  # 문자 수

# 지식 그래프 추출 설정
KG_EXTRACTION_ENABLED=true
KG_EXTRACTION_MODEL=gpt-4-turbo-preview
KG_MIN_CONFIDENCE=0.7
```

### 3. 데이터베이스 마이그레이션

```bash
# Alembic을 사용한 마이그레이션 (권장)
alembic upgrade head

# 또는 직접 테이블 생성
python -c "from neos.database.connection import db_manager; import asyncio; asyncio.run(db_manager.create_tables())"
```

---

## 사용 방법

### Python API 사용

```python
import asyncio
from neos.pipelines.document.document_processor import DocumentProcessor

async def upload_document():
    # DocumentProcessor 초기화
    processor = DocumentProcessor(
        storage_provider="local",
        enable_kg_extraction=True,
    )

    # 문서 업로드
    with open("document.pdf", "rb") as f:
        document = await processor.process_document(
            file_obj=f,
            filename="document.pdf",
            user_id="user123",
            metadata={"category": "research"},
            mime_type="application/pdf",
        )

    print(f"Document ID: {document.id}")
    print(f"Status: {document.processing_status}")

asyncio.run(upload_document())
```

### REST API 사용

#### 1. 문서 업로드

```bash
curl -X POST "http://localhost:8518/api/v1/documents/upload" \
  -F "file=@document.pdf" \
  -F "user_id=user123" \
  -F 'metadata={"category":"research"}'
```

**응답:**
```json
{
  "document_id": 1,
  "filename": "document.pdf",
  "status": "processing",
  "message": "Document uploaded and processing started"
}
```

#### 2. 문서 목록 조회

```bash
curl "http://localhost:8518/api/v1/documents/?user_id=user123&limit=10"
```

#### 3. 문서 상세 정보

```bash
curl "http://localhost:8518/api/v1/documents/1"
```

#### 4. 청크 조회

```bash
curl "http://localhost:8518/api/v1/documents/1/chunks?limit=5"
```

#### 5. 지식 그래프 조회

```bash
curl "http://localhost:8518/api/v1/documents/1/knowledge-graph"
```

#### 6. 시맨틱 검색

```bash
curl -X POST "http://localhost:8518/api/v1/documents/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "인공지능의 역사",
    "top_k": 5,
    "user_id": "user123"
  }'
```

**응답:**
```json
{
  "query": "인공지능의 역사",
  "results": [
    {
      "chunk_id": 1,
      "document_id": 1,
      "document_name": "document.pdf",
      "chunk_text": "인공지능의 역사는...",
      "similarity_score": 0.92,
      "page_number": 1
    }
  ]
}
```

#### 7. 문서 삭제

```bash
curl -X DELETE "http://localhost:8518/api/v1/documents/1"
```

---

## API 레퍼런스

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/documents/upload` | 문서 업로드 |
| GET | `/api/v1/documents/` | 문서 목록 조회 |
| GET | `/api/v1/documents/{id}` | 문서 상세 정보 |
| DELETE | `/api/v1/documents/{id}` | 문서 삭제 |
| GET | `/api/v1/documents/{id}/chunks` | 청크 조회 |
| GET | `/api/v1/documents/{id}/knowledge-graph` | 지식 그래프 조회 |
| POST | `/api/v1/documents/search` | 시맨틱 검색 |

### Request/Response Models

자세한 스키마는 Swagger UI에서 확인하세요: `http://localhost:8518/docs`

---

## 고급 기능

### 1. 커스텀 청킹 전략

```python
from neos.pipelines.document.chunker import DocumentChunker

# 커스텀 청커 생성
chunker = DocumentChunker(
    chunk_size=1500,
    chunk_overlap=300,
    respect_sentence_boundaries=True,
)

# 헤딩 계층 구조 보존
chunks = chunker.chunk_with_hierarchy(
    text=text,
    headings=[
        {"level": 1, "text": "Chapter 1", "offset": 0},
        {"level": 2, "text": "Section 1.1", "offset": 100},
    ],
)
```

### 2. 지식 그래프 배치 추출

```python
from neos.pipelines.document.knowledge_graph import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

# 여러 텍스트 동시 처리
results = await extractor.extract_batch(
    texts=[text1, text2, text3],
    contexts=[{"source": "doc1"}, {"source": "doc2"}, {"source": "doc3"}],
)

# 결과 병합
merged = extractor.merge_results(results)
```

### 3. 임베딩 캐싱

임베딩은 자동으로 Redis에 캐싱됩니다:

```python
from neos.utils.embeddings import EmbeddingService

embedding_service = EmbeddingService()

# 첫 번째 호출: OpenAI API 호출
embedding1 = await embedding_service.embed("test text")

# 두 번째 호출: Redis에서 캐시 조회
embedding2 = await embedding_service.embed("test text")
```

### 4. 스토리지 프로바이더 전환

```python
# S3로 전환
processor = DocumentProcessor(storage_provider="s3")

# rustfs로 전환
processor = DocumentProcessor(storage_provider="rustfs")

# 로컬로 전환
processor = DocumentProcessor(storage_provider="local")
```

---

## 성능 최적화

### 1. 배치 처리

```python
# 여러 파일 동시 처리
import asyncio

async def process_multiple():
    processor = DocumentProcessor()

    tasks = []
    for file_path in file_list:
        with open(file_path, "rb") as f:
            task = processor.process_document(
                file_obj=f,
                filename=file_path.name,
                user_id="user123",
            )
            tasks.append(task)

    results = await asyncio.gather(*tasks)
    return results
```

### 2. 청크 크기 조정

- 작은 청크 (500-800자): 더 정확한 검색, 더 많은 결과
- 큰 청크 (1500-2000자): 더 많은 컨텍스트, 더 적은 결과

### 3. 지식 그래프 비활성화

처리 속도가 중요한 경우:

```python
processor = DocumentProcessor(enable_kg_extraction=False)
```

---

## 문제 해결

### 문제: 파일 업로드 실패

**원인**: 파일 크기 초과 또는 지원하지 않는 형식

**해결**:
```bash
# MAX_FILE_SIZE 증가
MAX_FILE_SIZE=104857600  # 100MB

# 지원 확장자 확인
ALLOWED_FILE_EXTENSIONS=[".pdf", ".docx", ".txt", ".md"]
```

### 문제: 지식 그래프 추출 오류

**원인**: LLM API 오류 또는 응답 형식 불일치

**해결**:
- API 키 확인
- 모델 변경: `KG_EXTRACTION_MODEL=gpt-4`
- 신뢰도 임계값 낮추기: `KG_MIN_CONFIDENCE=0.5`

### 문제: 시맨틱 검색 느림

**원인**: pgvector 인덱스 부재

**해결**:
```sql
-- 벡터 인덱스 생성
CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops);
```

---

## 예제 코드

자세한 예제는 다음 파일을 참조하세요:

- `examples/document_processing_example.py`: Python API 사용 예제
- `examples/document_api_example.py`: REST API 사용 예제

---

## 라이선스

이 문서 관리 시스템은 NEOS 프로젝트의 일부입니다.
