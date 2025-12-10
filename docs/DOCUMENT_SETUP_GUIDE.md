# Document Management Setup Guide

NEOS 문서 관리 기능을 설치하고 설정하는 단계별 가이드입니다.

## 목차

1. [사전 요구사항](#사전-요구사항)
2. [설치](#설치)
3. [데이터베이스 설정](#데이터베이스-설정)
4. [환경 변수 설정](#환경-변수-설정)
5. [테스트](#테스트)
6. [문제 해결](#문제-해결)

---

## 사전 요구사항

### 필수 요구사항

- Python 3.12 이상
- PostgreSQL 14 이상 (pgvector 확장 지원)
- Redis (캐싱용)

### 선택 사항

- AWS S3 계정 (S3 스토리지 사용 시)
- rustfs 또는 기타 S3-compatible 스토리지

---

## 설치

### 1. 의존성 설치

```bash
# 프로젝트 루트 디렉토리에서
uv sync

# 또는 pip 사용
pip install -e .
```

새로 추가된 패키지:
- `boto3`: S3 스토리지 지원
- `aiofiles`: 비동기 파일 I/O (이미 설치됨)

### 2. PostgreSQL pgvector 확장 설치

```bash
# PostgreSQL에 연결
psql -U postgres -d your_database

# pgvector 확장 설치
CREATE EXTENSION IF NOT EXISTS vector;

# 확인
\dx
```

---

## 데이터베이스 설정

### 방법 1: Alembic 마이그레이션 (권장)

```bash
# 마이그레이션 생성
alembic revision --autogenerate -m "Add document management tables"

# 마이그레이션 적용
alembic upgrade head
```

### 방법 2: 직접 테이블 생성

```python
# create_tables.py
import asyncio
from neos.database.connection import db_manager

async def main():
    await db_manager.initialize()
    await db_manager.create_tables()
    print("✅ Tables created successfully!")
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

```bash
python create_tables.py
```

### 벡터 인덱스 생성 (성능 최적화)

```sql
-- document_chunks 테이블에 벡터 인덱스 생성
CREATE INDEX idx_document_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- knowledge_graphs 테이블에 벡터 인덱스 생성
CREATE INDEX idx_knowledge_graphs_embedding
ON knowledge_graphs
USING ivfflat (entity_embedding vector_cosine_ops)
WITH (lists = 100);
```

### FTS (Full-Text Search) 설정

```sql
-- document_chunks에 FTS 칼럼 추가
ALTER TABLE document_chunks
ADD COLUMN chunk_text_tsv tsvector;

-- FTS 자동 업데이트 트리거
CREATE OR REPLACE FUNCTION document_chunks_fts_trigger()
RETURNS trigger AS $$
BEGIN
  NEW.chunk_text_tsv := to_tsvector('english', COALESCE(NEW.chunk_text, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvector_update
BEFORE INSERT OR UPDATE ON document_chunks
FOR EACH ROW
EXECUTE FUNCTION document_chunks_fts_trigger();

-- FTS 인덱스 생성
CREATE INDEX idx_document_chunks_fts
ON document_chunks
USING gin(chunk_text_tsv);
```

---

## 환경 변수 설정

### 1. .env 파일 생성

```bash
cp .env.template .env
```

### 2. 문서 관리 설정 추가

`.env` 파일을 열고 다음 섹션을 확인/수정하세요:

```bash
# ============================================================================
# Document Management Configuration
# ============================================================================

# Storage Provider: s3, rustfs, local
STORAGE_PROVIDER=local

# S3 Configuration (for AWS S3)
S3_BUCKET_NAME=neos-documents
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key

# Local Storage Configuration
LOCAL_STORAGE_PATH=storage/documents

# Document Processing Configuration
MAX_FILE_SIZE=52428800  # 50MB
CHUNK_SIZE=1000
CHUNK_OVERLAP=200

# Knowledge Graph Extraction Configuration
KG_EXTRACTION_ENABLED=True
KG_EXTRACTION_MODEL=gpt-4-turbo-preview
KG_MIN_CONFIDENCE=0.7
```

### 3. 스토리지 옵션별 설정

#### 옵션 A: 로컬 스토리지 (기본)

```bash
STORAGE_PROVIDER=local
LOCAL_STORAGE_PATH=storage/documents
```

로컬 디렉토리 생성:
```bash
mkdir -p storage/documents
```

#### 옵션 B: AWS S3

```bash
STORAGE_PROVIDER=s3
S3_BUCKET_NAME=your-bucket-name
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
```

S3 버킷 생성:
```bash
aws s3 mb s3://your-bucket-name --region us-east-1
```

#### 옵션 C: rustfs (S3-compatible)

```bash
STORAGE_PROVIDER=rustfs
RUSTFS_BUCKET_NAME=your-bucket-name
RUSTFS_ENDPOINT_URL=https://your-rustfs-endpoint.com
RUSTFS_ACCESS_KEY=your_access_key
RUSTFS_SECRET_KEY=your_secret_key
```

---

## 문제 해결

### 문제 1: pgvector 확장이 없음

**에러**: `extension "vector" does not exist`

**해결**:
```bash
# PostgreSQL 버전 확인
psql --version

# pgvector 설치 (Ubuntu/Debian)
sudo apt-get install postgresql-14-pgvector

# pgvector 설치 (macOS with Homebrew)
brew install pgvector

# 확장 생성
psql -U postgres -d your_database -c "CREATE EXTENSION vector;"
```

### 문제 2: boto3 임포트 에러

**에러**: `ModuleNotFoundError: No module named 'boto3'`

**해결**:
```bash
uv add boto3
# 또는
pip install boto3
```

### 문제 3: 파일 업로드 크기 제한

**에러**: `File size exceeds maximum`

**해결**:
```bash
# .env 파일에서 크기 증가
MAX_FILE_SIZE=104857600  # 100MB

# FastAPI 설정도 조정 필요 시 neos/main.py에서:
# app.add_middleware(HTTPMiddleware, max_upload_size=100*1024*1024)
```

### 문제 4: 지식 그래프 추출 실패

**에러**: JSON 파싱 오류 또는 LLM 응답 오류

**해결**:
```bash
# 모델 변경
KG_EXTRACTION_MODEL=gpt-4

# 또는 지식 그래프 비활성화
KG_EXTRACTION_ENABLED=False

# 또는 신뢰도 임계값 낮추기
KG_MIN_CONFIDENCE=0.5
```

### 문제 5: 임베딩 생성 느림

**원인**: OpenAI API 속도 제한

**해결**:
- Redis 캐싱 활성화 확인
- 배치 크기 조정
- 또는 다른 임베딩 모델 사용

### 문제 6: 검색 성능 저하

**원인**: 벡터 인덱스 부재

**해결**:
```sql
-- 인덱스 생성 확인
\d document_chunks

-- 인덱스가 없으면 생성
CREATE INDEX idx_document_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops);
```

---

## 다음 단계

1. **프로덕션 배포**
   - Nginx/Traefik 리버스 프록시 설정
   - HTTPS 인증서 설정
   - 환경 변수 암호화

2. **모니터링**
   - Arize Phoenix 대시보드 확인: `http://localhost:6006`
   - 로그 분석
   - 성능 메트릭 추적

3. **고급 기능**
   - 커스텀 청킹 전략 구현
   - 다국어 FTS 설정
   - 지식 그래프 시각화

4. **확장**
   - 여러 문서 배치 업로드
   - 문서 버전 관리
   - 사용자별 권한 관리

---

## 참고 자료

- [DOCUMENT_MANAGEMENT.md](./DOCUMENT_MANAGEMENT.md): 전체 문서
- [pgvector GitHub](https://github.com/pgvector/pgvector): pgvector 문서

---

## 지원

문제가 발생하면 GitHub Issues에 보고해주세요.
