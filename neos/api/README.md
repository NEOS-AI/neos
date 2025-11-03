# API Architecture

이 디렉토리는 3계층 아키텍처로 리팩토링되었습니다.

## 디렉토리 구조

```
neos/api/
├── models/              # Pydantic 모델 (요청/응답 스키마)
│   ├── query_models.py
│   ├── document_models.py
│   └── multimodal_models.py
│
├── services/            # 비즈니스 로직 레이어
│   ├── query_service.py
│   ├── document_service.py
│   └── multimodal_service.py
│
├── handlers/            # API 핸들러 (얇은 라우팅 레이어)
│   ├── query_handlers.py
│   ├── document_handlers.py
│   ├── multimodal_handlers.py
│   └── analytics_handlers.py
│
├── routes.py            # 메인 라우터 (query)
├── document_routes.py   # 문서 라우터
├── multimodal_routes.py # 멀티모달 라우터
└── web_search_analytics_routes.py # 분석 라우터
```

## 아키텍처 설명

### 1. Models (`models/`)
- **책임**: 데이터 검증 및 직렬화
- **내용**: Pydantic 모델 정의
- **특징**:
  - 요청/응답 스키마만 포함
  - 비즈니스 로직 없음
  - API 문서 자동 생성 지원

### 2. Services (`services/`)
- **책임**: 비즈니스 로직 처리
- **내용**:
  - 데이터베이스 작업
  - 워크플로우 실행
  - 외부 서비스 호출
  - 데이터 변환 및 가공
- **특징**:
  - 재사용 가능한 메서드
  - 핸들러와 독립적
  - 테스트 용이

### 3. Handlers (`handlers/`)
- **책임**: HTTP 요청/응답 처리
- **내용**:
  - FastAPI 라우트 정의
  - 요청 파라미터 파싱
  - 서비스 레이어 호출
  - 에러 핸들링
- **특징**:
  - 얇은 레이어 (thin layer)
  - 비즈니스 로직 최소화
  - HTTP 관련 로직만 포함

## 사용 예시

### 새로운 엔드포인트 추가하기

1. **모델 정의** (`models/`)
```python
# models/my_models.py
from pydantic import BaseModel

class MyRequest(BaseModel):
    query: str
    limit: int = 10

class MyResponse(BaseModel):
    success: bool
    data: list
```

2. **서비스 로직 구현** (`services/`)
```python
# services/my_service.py
class MyService:
    @staticmethod
    async def process_request(query: str, limit: int):
        # 비즈니스 로직 구현
        result = await some_database_operation(query, limit)
        return {"success": True, "data": result}
```

3. **핸들러 작성** (`handlers/`)
```python
# handlers/my_handlers.py
from fastapi import APIRouter
from neos.api.models.my_models import MyRequest, MyResponse
from neos.api.services.my_service import MyService

router = APIRouter()

@router.post("/my-endpoint", response_model=MyResponse)
async def my_endpoint(request: MyRequest):
    result = await MyService.process_request(request.query, request.limit)
    return MyResponse(**result)
```

## 장점

### 유지보수성
- 각 레이어가 명확히 분리되어 있어 코드 수정이 용이
- 비즈니스 로직이 서비스 레이어에 집중되어 있어 재사용 가능

### 테스트 용이성
- 각 레이어를 독립적으로 테스트 가능
- 서비스 레이어는 HTTP 없이 직접 테스트 가능
- Mock 객체 생성이 쉬움

### 확장성
- 새로운 엔드포인트 추가가 간단
- 여러 핸들러가 같은 서비스 로직 재사용 가능
- 레이어별로 독립적인 확장 가능

### 가독성
- 파일 크기 감소 (기존 734줄 → 각 파일 100-300줄)
- 명확한 책임 분리로 코드 이해가 쉬움
- 일관된 구조로 새로운 개발자도 빠르게 적응 가능

## 마이그레이션 가이드

기존 코드는 다음과 같이 변경되었습니다:

### Before (기존)
```python
# routes.py (734줄)
class QueryRequest(BaseModel):
    query: str

async def get_or_create_user(user_id: str):
    # DB 로직...

@router.post("/query")
async def process_query(request: QueryRequest):
    # 모든 로직이 여기에...
```

### After (리팩토링 후)
```python
# models/query_models.py
class QueryRequest(BaseModel):
    query: str

# services/query_service.py
class QueryService:
    @staticmethod
    async def get_or_create_user(user_id: str):
        # DB 로직...

# handlers/query_handlers.py
@router.post("/query")
async def process_query(request: QueryRequest):
    result = await QueryService.process_query_workflow(...)
    return QueryResponse(**result)
```

## 주의사항

- 모든 비즈니스 로직은 **서비스 레이어**에 작성
- 핸들러는 **HTTP 관련 로직만** 포함
- 모델은 **데이터 구조만** 정의
- 서비스 메서드는 가능한 **정적 메서드**로 작성
