##  Vision 모델 통합 가이드

NEOS의 멀티모달 파이프라인에 GPT-4o와 Claude Vision이 통합되어 이미지 분석이 가능합니다!

## 🎯 개요

### 지원 모델

| 모델 | 프로바이더 | 특징 |
|-----|-----------|------|
| **GPT-4o** | OpenAI | 뛰어난 OCR, 객체 인식, 빠른 응답 |
| **Claude 4.5 Sonnet** | Anthropic | 높은 이해도, 상세한 설명, 맥락 파악 |

### 주요 기능

- ✅ **자동 이미지 분석**: 이미지 업로드 시 자동으로 Vision 모델 호출
- ✅ **다국어 지원**: 한국어/영어 프롬프트 자동 생성
- ✅ **OCR**: 이미지 내 텍스트 자동 추출
- ✅ **객체 인식**: 이미지 속 객체 및 장면 분석
- ✅ **자동 폴백**: Vision 에러 시에도 파이프라인 계속 진행
- ✅ **유연한 설정**: 프로바이더 선택, Vision 활성화/비활성화

## 🚀 빠른 시작

### 1. API 키 설정

`.env` 파일에 API 키를 추가하세요:

```bash
# OpenAI (GPT-4o 사용)
OPENAI_API_KEY=your_openai_api_key_here

# 또는 Anthropic (Claude 사용)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Vision 설정
VISION_ENABLED=true
VISION_PROVIDER=auto  # "gpt4o", "claude", "auto"
```

### 2. 기본 사용

```python
from neos.workflow.multimodal_workflow import MultiModalWorkflow

workflow = MultiModalWorkflow()

# 이미지 분석
result = await workflow.process(
    query="이 이미지에서 무엇이 보이나요?",
    files=[{
        "file_path": "/path/to/image.jpg",
        "filename": "image.jpg"
    }],
    user_id="user123"
)

# Vision 분석 결과 확인
if result["success"]:
    print(result["result"]["extracted_text"])  # Vision 모델의 이미지 설명
```

## 📋 상세 사용법

### ImagePipeline 직접 사용

```python
from neos.workflow.pipelines import (
    ImagePipeline,
    VisionProvider,
    PipelineContext,
    FileInput,
    InputType
)

# Vision 활성화된 파이프라인 생성
pipeline = ImagePipeline(
    vision_provider=VisionProvider.GPT4O,  # 또는 CLAUDE, AUTO
    enable_vision=True
)

# 이미지 파일 준비
with open("image.jpg", "rb") as f:
    image_content = f.read()

file = FileInput(
    filename="image.jpg",
    file_content=image_content,
    mime_type="image/jpeg"
)

# 컨텍스트 생성
context = PipelineContext(
    query="Describe this image in detail",
    input_type=InputType.IMAGE,
    files=[file],
    language="en"
)

# 파이프라인 실행
result = await pipeline.process(context)

# 결과 확인
print(f"Vision Analysis: {result.extracted_text}")
print(f"Provider: {result.analysis['vision_provider']}")
print(f"Confidence: {result.analysis['vision_confidence']}")
```

### Vision 모델 직접 사용

```python
from neos.workflow.pipelines import (
    GPT4oVision,
    ClaudeVision,
    VisionModelFactory,
    VisionProvider
)
import base64

# 방법 1: 특정 모델 사용
vision = GPT4oVision()

# 방법 2: 팩토리로 자동 선택
vision = VisionModelFactory.create(VisionProvider.AUTO)

# 이미지를 base64로 인코딩
with open("image.jpg", "rb") as f:
    image_data = base64.b64encode(f.read()).decode("utf-8")

# Vision 분석
result = await vision.analyze_image(
    image_data=image_data,
    prompt="What's in this image?",
    max_tokens=1000
)

print(f"Description: {result['description']}")
print(f"Confidence: {result['confidence']}")
```

## ⚙️ 설정 옵션

### 환경 변수

| 변수 | 설명 | 기본값 |
|-----|------|-------|
| `VISION_ENABLED` | Vision 모델 사용 여부 | `true` |
| `VISION_PROVIDER` | Vision 프로바이더 | `auto` |
| `VISION_MAX_TOKENS` | 최대 응답 토큰 수 | `1000` |
| `VISION_IMAGE_DETAIL` | GPT-4o 이미지 상세도 | `auto` |

### VISION_PROVIDER 옵션

- **`auto`**: LLM_PROVIDER 설정에 따라 자동 선택
- **`gpt4o`**: GPT-4o 사용 (OPENAI_API_KEY 필요)
- **`claude`**: Claude 4.5 Sonnet 사용 (ANTHROPIC_API_KEY 필요)

### VISION_IMAGE_DETAIL 옵션 (GPT-4o)

- **`auto`**: 자동 최적화 (권장)
- **`low`**: 저해상도 (빠르고 저렴)
- **`high`**: 고해상도 (상세하지만 느리고 비쌈)

## 📊 Vision 분석 결과 구조

```python
{
    "description": "이미지에 대한 상세 설명",
    "objects": [
        {"name": "객체명", "confidence": 0.95}
    ],
    "text": "OCR로 추출된 텍스트",
    "metadata": {
        "provider": "gpt4o",
        "model": "gpt-4o",
        "tokens_used": 150
    },
    "confidence": 0.85
}
```

## 🎨 사용 예시

### 1. 이미지 설명 생성

```python
result = await workflow.process(
    query="이 사진을 자세히 설명해주세요",
    files=[{"file_path": "photo.jpg"}]
)
```

### 2. OCR (텍스트 추출)

```python
result = await workflow.process(
    query="이 이미지에 있는 텍스트를 모두 추출해주세요",
    files=[{"file_path": "document_scan.jpg"}]
)

# OCR 결과
ocr_text = result["result"]["analysis"]["vision_analysis"]["text"]
```

### 3. 객체 인식

```python
result = await workflow.process(
    query="이 이미지에서 어떤 물체들이 보이나요?",
    files=[{"file_path": "scene.jpg"}]
)
```

### 4. 다중 이미지 분석

```python
result = await workflow.process(
    query="이 여러 이미지들을 비교 분석해주세요",
    files=[
        {"file_path": "image1.jpg"},
        {"file_path": "image2.jpg"},
        {"file_path": "image3.jpg"},
    ]
)
```

## 🔧 고급 설정

### Vision 비활성화

특정 경우에 Vision을 비활성화하려면:

```python
pipeline = ImagePipeline(enable_vision=False)
```

### 커스텀 프롬프트

ImagePipeline은 자동으로 프롬프트를 생성하지만, 더 구체적인 분석을 원하면 쿼리에 명시하세요:

```python
query = """
이 이미지를 분석하고 다음 사항을 포함해주세요:
1. 전체적인 분위기와 색감
2. 주요 구성 요소
3. 이미지에 포함된 모든 텍스트
4. 예상되는 맥락이나 용도
"""
```

### 여러 프로바이더 비교

```python
# GPT-4o로 분석
pipeline_gpt = ImagePipeline(vision_provider=VisionProvider.GPT4O)
result_gpt = await pipeline_gpt.process(context)

# Claude로 분석
pipeline_claude = ImagePipeline(vision_provider=VisionProvider.CLAUDE)
result_claude = await pipeline_claude.process(context)

# 결과 비교
print("GPT-4o:", result_gpt.extracted_text)
print("Claude:", result_claude.extracted_text)
```

## ⚠️ 에러 처리

Vision 모델 에러는 자동으로 처리되며 전체 파이프라인을 중단하지 않습니다:

```python
result = await pipeline.process(context)

if result.success:
    # 파이프라인은 성공
    if "vision_error" in result.analysis:
        # Vision 분석 실패
        print(f"Vision error: {result.analysis['vision_error']}")
        print(f"Warnings: {result.warnings}")
    else:
        # Vision 분석 성공
        print(f"Vision result: {result.extracted_text}")
```

## 💰 비용 최적화

### 1. 이미지 크기 최적화

ImagePipeline은 자동으로 큰 이미지를 리사이징합니다:
- 최대 크기: 4096 x 4096 픽셀

### 2. Detail 설정 조정 (GPT-4o)

```bash
# 비용 절감 (저해상도)
VISION_IMAGE_DETAIL=low

# 균형 (권장)
VISION_IMAGE_DETAIL=auto

# 최고 품질 (고비용)
VISION_IMAGE_DETAIL=high
```

### 3. 토큰 제한

```bash
# 짧은 응답으로 비용 절감
VISION_MAX_TOKENS=500

# 상세한 분석 (더 많은 비용)
VISION_MAX_TOKENS=2000
```

## 🧪 테스트

Vision 통합 테스트는 `tests/test_vision_integration.py`에 있습니다:

```bash
# Vision 통합 테스트 실행
pytest tests/test_vision_integration.py -v
```

## 📈 성능

### 처리 시간

| 단계 | 시간 |
|-----|------|
| 이미지 전처리 | ~100ms |
| Vision API 호출 | ~2-5초 |
| 총 처리 시간 | ~2-5초 |

### 지원 이미지 형식

- JPG/JPEG
- PNG
- GIF
- WebP
- BMP

### 크기 제한

- 최대 파일 크기: 20MB
- 최대 이미지 크기: 4096 x 4096 픽셀

## 🔍 문제 해결

### Q: "Vision model API key not configured" 에러

A: `.env` 파일에 API 키를 추가하세요:
```bash
OPENAI_API_KEY=your_key_here
# 또는
ANTHROPIC_API_KEY=your_key_here
```

### Q: Vision 분석이 너무 느려요

A: 이미지 상세도를 낮추세요:
```bash
VISION_IMAGE_DETAIL=low
```

### Q: Vision 응답이 너무 짧아요

A: 최대 토큰 수를 늘리세요:
```bash
VISION_MAX_TOKENS=2000
```

### Q: 특정 프로바이더를 강제하고 싶어요

A: VISION_PROVIDER를 직접 지정하세요:
```bash
VISION_PROVIDER=gpt4o  # 또는 claude
```

## 🚀 다음 단계

1. **PDF Vision 통합**: PDF 내 이미지를 Vision 모델로 분석
2. **배치 처리**: 여러 이미지를 동시에 처리
3. **캐싱**: 동일 이미지 재분석 방지
4. **스트리밍**: Vision 응답을 스트리밍으로 받기

## 📚 관련 문서

- [멀티모달 파이프라인 가이드](./MULTIMODAL_PIPELINES.md)
- [빠른 시작 가이드](./QUICKSTART_MULTIMODAL.md)
- [API 레퍼런스](./IMPLEMENTATION_SUMMARY.md)
