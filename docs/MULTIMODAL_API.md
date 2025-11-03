# Multimodal API Documentation

NEOS의 멀티모달 API는 이미지, 문서, 오디오 등 다양한 파일과 텍스트를 함께 처리할 수 있는 강력한 기능을 제공합니다.

## 목차

- [개요](#개요)
- [지원 기능](#지원-기능)
- [API 엔드포인트](#api-엔드포인트)
- [사용 예시](#사용-예시)
- [응답 형식](#응답-형식)
- [에러 처리](#에러-처리)

---

## 개요

멀티모달 API는 Vision Language Model (VLM)을 활용하여 이미지와 텍스트를 함께 이해하고 처리합니다.

### 지원하는 Vision 모델

- **GPT-4o Vision** (OpenAI)
- **Claude 3.5 Sonnet Vision** (Anthropic)

### 주요 기능

- 🖼️ 이미지 콘텐츠 분석 및 설명
- 🔍 객체 감지 (Object Detection)
- 📝 OCR (광학 문자 인식)
- 💬 이미지에 대한 질의응답
- 📊 여러 파일 동시 처리
- 🌐 한국어/영어 지원

---

## 지원 기능

### 파일 형식

| 타입 | 지원 확장자 | 최대 크기 |
|------|------------|----------|
| **이미지** | `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.bmp` | 20MB |
| **문서** | `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.csv` | 50MB |
| **오디오** | `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`, `.webm` | 100MB |

### Vision 분석 기능

- **이미지 설명**: 이미지의 전반적인 내용을 자연어로 설명
- **객체 감지**: 이미지에서 감지된 물체 목록
- **OCR**: 이미지 내의 텍스트 추출
- **품질 평가**: 이미지 해상도 및 품질 분석
- **메타데이터**: 이미지 크기, 포맷, MIME 타입 등

---

## API 엔드포인트

### 1. 멀티모달 쿼리

**`POST /api/v1/multimodal/query`**

이미지와 텍스트를 함께 업로드하여 전체 워크플로우를 실행합니다.

#### 요청

```http
POST /api/v1/multimodal/query
Content-Type: multipart/form-data

files: [파일들]
query: "사용자 질문"
user_id: "user123" (optional)
session_id: "session456" (optional)
language: "ko" (optional, default: "ko")
```

#### 응답

```json
{
  "success": true,
  "response": "AI가 생성한 최종 응답",
  "session_id": "abc123",
  "input_type": "image",
  "metadata": {
    "agent_types": ["vision", "analysis"],
    "processing_stages": ["vision_analysis", "agent_workflow"]
  },
  "processing_time_ms": 2500.5,
  "vision_analysis": {
    "description": "이미지 설명",
    "objects": ["사람", "자동차", "건물"],
    "ocr_text": "추출된 텍스트",
    "provider": "gpt4o",
    "confidence": 0.95
  },
  "extracted_text": "전체 추출된 텍스트",
  "errors": [],
  "warnings": []
}
```

---

### 2. 이미지 분석 (빠른 분석)

**`POST /api/v1/multimodal/image/analyze`**

이미지만 빠르게 분석합니다 (전체 워크플로우 제외).

#### 요청

```http
POST /api/v1/multimodal/image/analyze
Content-Type: multipart/form-data

image: [이미지 파일]
query: "이미지에 대한 질문" (optional)
user_id: "user123" (optional)
language: "ko" (optional)
```

#### 응답

```json
{
  "success": true,
  "filename": "photo.jpg",
  "description": "햇살 가득한 공원에서 아이들이 뛰어노는 모습",
  "objects": ["어린이", "나무", "잔디", "벤치"],
  "ocr_text": null,
  "image_metadata": {
    "width": 1920,
    "height": 1080,
    "format": "JPEG",
    "mime_type": "image/jpeg",
    "file_size": 245678
  },
  "vision_provider": "claude",
  "confidence": 0.92,
  "processing_time_ms": 1200.3
}
```

---

### 3. 지원 타입 조회

**`GET /api/v1/multimodal/supported-types`**

지원하는 파일 형식과 Vision 모델 정보를 조회합니다.

#### 응답

```json
{
  "supported_types": {
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
    "document": [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv"],
    "audio": [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm"]
  },
  "vision_enabled": true,
  "vision_providers": ["gpt4o", "claude"]
}
```

---

### 4. 헬스 체크

**`GET /api/v1/multimodal/health`**

멀티모달 API 및 Vision 모델의 상태를 확인합니다.

#### 응답

```json
{
  "status": "healthy",
  "multimodal_workflow": "available",
  "vision_enabled": true,
  "vision_models": {
    "primary": {
      "available": true,
      "provider": "GPT4oVision"
    }
  }
}
```

---

## 사용 예시

### Python (requests)

#### 1. 이미지 + 텍스트 쿼리

```python
import requests

url = "http://localhost:8518/api/v1/multimodal/query"

# 파일과 데이터 준비
files = [
    ("files", ("photo.jpg", open("photo.jpg", "rb"), "image/jpeg"))
]

data = {
    "query": "이 사진에서 무엇을 볼 수 있나요?",
    "user_id": "user123",
    "language": "ko"
}

# 요청 전송
response = requests.post(url, files=files, data=data)

# 응답 확인
result = response.json()
print(f"Response: {result['response']}")
print(f"Vision Analysis: {result['vision_analysis']}")
```

#### 2. 여러 이미지 동시 업로드

```python
files = [
    ("files", ("image1.jpg", open("image1.jpg", "rb"), "image/jpeg")),
    ("files", ("image2.jpg", open("image2.jpg", "rb"), "image/jpeg")),
    ("files", ("document.pdf", open("doc.pdf", "rb"), "application/pdf"))
]

data = {
    "query": "이 파일들을 종합적으로 분석해주세요",
    "language": "ko"
}

response = requests.post(url, files=files, data=data)
```

#### 3. 빠른 이미지 분석

```python
url = "http://localhost:8518/api/v1/multimodal/image/analyze"

files = {
    "image": ("photo.jpg", open("photo.jpg", "rb"), "image/jpeg")
}

data = {
    "query": "이 사진의 주요 특징을 설명해주세요"
}

response = requests.post(url, files=files, data=data)
result = response.json()

print(f"Description: {result['description']}")
print(f"Objects: {', '.join(result['objects'])}")
```

---

### cURL

#### 멀티모달 쿼리

```bash
curl -X POST "http://localhost:8518/api/v1/multimodal/query" \
  -F "files=@photo.jpg" \
  -F "query=이 이미지를 분석해주세요" \
  -F "language=ko"
```

#### 이미지 분석

```bash
curl -X POST "http://localhost:8518/api/v1/multimodal/image/analyze" \
  -F "image=@photo.jpg" \
  -F "query=이 사진에 무엇이 있나요?"
```

---

### JavaScript (Fetch API)

```javascript
const formData = new FormData();
formData.append('files', imageFile);
formData.append('query', '이 이미지를 설명해주세요');
formData.append('language', 'ko');

const response = await fetch('http://localhost:8518/api/v1/multimodal/query', {
  method: 'POST',
  body: formData
});

const result = await response.json();
console.log('Response:', result.response);
console.log('Vision Analysis:', result.vision_analysis);
```

---

## 응답 형식

### 성공 응답

모든 성공 응답은 다음 공통 필드를 포함합니다:

| 필드 | 타입 | 설명 |
|------|------|------|
| `success` | boolean | 요청 성공 여부 |
| `processing_time_ms` | float | 처리 시간 (밀리초) |

### Vision 분석 정보

`vision_analysis` 객체는 다음 정보를 포함합니다:

```json
{
  "description": "이미지에 대한 자연어 설명",
  "objects": ["감지된", "객체", "목록"],
  "ocr_text": "추출된 텍스트 (있을 경우)",
  "provider": "gpt4o" | "claude",
  "confidence": 0.95
}
```

---

## 에러 처리

### HTTP 상태 코드

| 코드 | 의미 | 설명 |
|------|------|------|
| 200 | OK | 요청 성공 |
| 400 | Bad Request | 잘못된 요청 (파일 형식, 크기 등) |
| 422 | Unprocessable Entity | 필수 필드 누락 |
| 500 | Internal Server Error | 서버 내부 오류 |

### 에러 응답 예시

```json
{
  "detail": "File photo.jpg exceeds maximum size of 20MB"
}
```

### 일반적인 에러 원인

1. **파일 크기 초과**
   - 이미지: 20MB 제한
   - 문서: 50MB 제한
   - 오디오: 100MB 제한

2. **지원하지 않는 파일 형식**
   - 지원 형식 목록 확인: `/api/v1/multimodal/supported-types`

3. **Vision API 키 누락**
   - 환경 변수 설정 필요:
     - `OPENAI_API_KEY` (GPT-4o)
     - `ANTHROPIC_API_KEY` (Claude)

4. **필수 필드 누락**
   - `query`: 사용자 질문 (필수)
   - `files` 또는 `image`: 파일 (필수)

---

## 환경 변수 설정

멀티모달 API를 사용하려면 다음 환경 변수를 설정해야 합니다:

```bash
# Vision 모델 설정
VISION_ENABLED=true
VISION_PROVIDER=auto  # "gpt4o", "claude", "auto"
VISION_MAX_TOKENS=1000
VISION_IMAGE_DETAIL=auto  # "auto", "low", "high"

# API 키 (최소 하나 필요)
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key

# 기본 LLM 제공자 (Vision 자동 선택에 영향)
LLM_PROVIDER=openai  # "openai" or "anthropic"
```

---

## 성능 최적화

### 권장사항

1. **이미지 크기 최적화**
   - 4096x4096 이상은 자동으로 리사이즈됨
   - 적절한 해상도로 미리 조정하면 처리 속도 향상

2. **적절한 엔드포인트 선택**
   - 빠른 분석만 필요: `/image/analyze` 사용
   - 전체 워크플로우 필요: `/query` 사용

3. **배치 처리**
   - 여러 파일을 한 번에 업로드하여 처리 시간 단축

4. **캐싱 활용**
   - 동일한 이미지 재요청 시 캐시 사용

---

## 제한 사항

1. **파일 개수**: 요청당 최대 10개 파일 (권장)
2. **동시 요청**: 서버 리소스에 따라 제한
3. **Vision API 할당량**: 각 제공자의 API 할당량에 따름
4. **타임아웃**: 기본 120초 (설정 가능)

---

## 예제 코드

전체 예제 코드는 다음 파일을 참조하세요:

- **Python 예제**: `examples/multimodal_api_example.py`
- **API 테스트**: `tests/test_multimodal_api.py`

실행 방법:

```bash
# 서버 실행
python -m neos.main

# 예제 실행
python examples/multimodal_api_example.py

# 테스트 실행
pytest tests/test_multimodal_api.py -v
```

---

## 문제 해결

### Vision 분석이 작동하지 않을 때

1. API 키 확인:
   ```bash
   echo $OPENAI_API_KEY
   echo $ANTHROPIC_API_KEY
   ```

2. Vision 설정 확인:
   ```bash
   curl http://localhost:8518/api/v1/multimodal/health
   ```

3. 지원 타입 확인:
   ```bash
   curl http://localhost:8518/api/v1/multimodal/supported-types
   ```

### 일반적인 해결 방법

- 로그 확인: 서버 콘솔에서 상세 에러 메시지 확인
- 파일 형식 확인: MIME 타입이 올바른지 확인
- 네트워크 확인: API 서버 연결 상태 확인
- 메모리 확인: 큰 파일 처리 시 충분한 메모리 필요

---

## 추가 리소스

- [NEOS 문서](../README.md)
- [Vision 모델 구현](../neos/workflow/pipelines/vision_models.py)
- [이미지 파이프라인](../neos/workflow/pipelines/image_pipeline.py)
- [멀티모달 워크플로우](../neos/workflow/multimodal_workflow.py)

---

## 라이센스

이 프로젝트는 NEOS 라이센스를 따릅니다.
