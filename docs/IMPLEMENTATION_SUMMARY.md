# 멀티모달 워크플로우 구현 요약

## 구현 완료 사항

### 1. 아키텍처 설계

다음과 같은 하이브리드 워크플로우 시스템을 구현했습니다:

```
입력 수신
  ↓
통합 라우터 (InputRouter)
  ├→ TextPipeline
  ├→ ImagePipeline
  ├→ DocumentPipeline
  ├→ AudioPipeline
  └→ MultiModalPipeline
      ↓
통합 컨텍스트 레이어 (UnifiedContextLayer)
      ↓
기존 워크플로우 (MultiAgentWorkflow)
```

### 2. 핵심 컴포넌트

#### 2.1 베이스 클래스 및 공통 인터페이스

**파일**: `neos/workflow/pipelines/base.py`

- `InputType`: 입력 타입 열거형 (TEXT, IMAGE, DOCUMENT, AUDIO, VIDEO, MULTIMODAL)
- `ProcessingStage`: 처리 단계 열거형
- `FileInput`: 파일 입력 데이터 클래스
- `PipelineContext`: 파이프라인 실행 컨텍스트
- `PipelineResult`: 파이프라인 결과
- `BasePipeline`: 모든 파이프라인의 추상 베이스 클래스
  - `validate()`: 입력 검증
  - `preprocess()`: 전처리
  - `extract()`: 정보 추출
  - `analyze()`: 분석
  - `process()`: 전체 파이프라인 실행 (템플릿 메서드)
- `PipelineRegistry`: 파이프라인 관리 싱글톤

#### 2.2 통합 라우터

**파일**: `neos/workflow/pipelines/router.py`

- 입력 타입 자동 분류 (MIME 타입, 파일 확장자 기반)
- 적절한 파이프라인 자동 라우팅
- 40+ 파일 형식 지원

#### 2.3 개별 파이프라인

**TextPipeline** (`text_pipeline.py`)
- 텍스트 정제 및 분석
- 한글/영어 언어 감지
- 쿼리 타입 분류 (질문, 비교, 분석, 생성 등)

**ImagePipeline** (`image_pipeline.py`)
- 이미지 전처리 (리사이징, RGB 변환)
- 메타데이터 추출
- Base64 인코딩 (Vision 모델 준비)
- 품질 평가

**DocumentPipeline** (`document_pipeline.py`)
- 다양한 문서 형식 지원 (PDF, DOCX, PPT, XLS, CSV, TXT, MD)
- 구조 분석 및 복잡도 평가
- 텍스트 추출 프레임워크
- TODO: PyPDF2, python-docx, openpyxl 통합

**AudioPipeline** (`audio_pipeline.py`)
- 오디오 포맷 지원 (MP3, WAV, OGG, FLAC, M4A)
- STT 변환 프레임워크
- 화자 분리 준비
- TODO: OpenAI Whisper, pyannote.audio 통합

**MultiModalPipeline** (`multimodal_pipeline.py`)
- 여러 타입의 입력 동시 처리
- 파일 타입별 자동 그룹핑
- 병렬 파이프라인 실행 (asyncio)
- 크로스 레퍼런스 분석
- 통합 품질 평가

#### 2.4 통합 컨텍스트 레이어

**파일**: `neos/workflow/pipelines/unified_context.py`

- 모든 파이프라인 결과를 통합 형식으로 변환
- 기존 `AgentState` 포맷과 호환
- 쿼리 향상 (extracted content 포함)
- 입력 타입별 특수 처리
- 히스토리 관리

#### 2.5 워크플로우 통합

**파일**: `neos/workflow/multimodal_workflow.py`

- 파이프라인 시스템과 기존 워크플로우 연결
- `MultiModalWorkflow` 클래스
- 편의 함수 `process_multimodal_query()`

### 3. 주요 특징

#### 3.1 느슨한 결합 (Loose Coupling)

- 각 파이프라인이 독립적으로 동작
- 공통 인터페이스를 통한 일관된 동작
- 새 파이프라인 추가가 용이

#### 3.2 높은 재사용성

- `BasePipeline`의 템플릿 메서드 패턴
- 상속을 통한 커스터마이징
- 공통 데이터 모델 재사용

#### 3.3 점진적 확장

- 레지스트리 패턴으로 동적 등록
- TODO 마크로 향후 확장 지점 명시
- 단계별 구현 가능

#### 3.4 병렬 처리

- MultiModalPipeline의 asyncio 활용
- 여러 파일 동시 처리로 성능 향상

## 파일 구조

```
neos/
  workflow/
    pipelines/
      __init__.py              # 패키지 초기화
      base.py                  # 베이스 클래스 및 공통 모델
      router.py                # 통합 라우터
      text_pipeline.py         # 텍스트 처리
      image_pipeline.py        # 이미지 처리
      document_pipeline.py     # 문서 처리
      audio_pipeline.py        # 음성 처리
      multimodal_pipeline.py   # 멀티모달 처리
      unified_context.py       # 통합 컨텍스트 레이어
    multimodal_workflow.py     # 워크플로우 통합

tests/
  test_pipelines.py            # 파이프라인 테스트

docs/
  MULTIMODAL_PIPELINES.md      # 상세 문서
  IMPLEMENTATION_SUMMARY.md    # 구현 요약 (본 문서)
```

## 사용 예시

### 기본 사용법

```python
from neos.workflow.multimodal_workflow import MultiModalWorkflow

workflow = MultiModalWorkflow()

# 텍스트만
result = await workflow.process(
    query="AI에 대해 설명해줘",
    user_id="user123"
)

# 이미지 포함
result = await workflow.process(
    query="이 이미지를 분석해줘",
    files=[{
        "file_path": "/path/to/image.jpg",
        "filename": "image.jpg"
    }],
    user_id="user123"
)

# 멀티모달 (이미지 + 문서)
result = await workflow.process(
    query="이 자료들을 종합 분석해줘",
    files=[
        {"file_path": "/path/to/image.jpg"},
        {"file_path": "/path/to/doc.pdf"},
    ],
    user_id="user123"
)
```

### 개별 파이프라인 사용

```python
from neos.workflow.pipelines import TextPipeline, PipelineContext, InputType

pipeline = TextPipeline()
context = PipelineContext(
    query="Hello, world!",
    input_type=InputType.TEXT
)

result = await pipeline.process(context)

if result.success:
    print(result.extracted_text)
    print(result.metadata)
```

### 커스텀 파이프라인 추가

```python
from neos.workflow.pipelines.base import BasePipeline, InputType

class VideoPipeline(BasePipeline):
    def __init__(self):
        super().__init__(name="VideoPipeline", input_type=InputType.VIDEO)

    async def validate(self, context):
        return True

    async def preprocess(self, context):
        return context

    async def extract(self, context):
        # 비디오 처리 로직
        ...

    async def analyze(self, result, context):
        # 분석 로직
        ...

# 등록
from neos.workflow.pipelines import PipelineRegistry
registry = PipelineRegistry()
registry.register(InputType.VIDEO, VideoPipeline())
```

## 향후 작업 (TODO)

### Phase 2: 실제 파싱 라이브러리 통합

1. **Vision 모델 통합**
   - OpenAI GPT-4V
   - Anthropic Claude Vision
   - Google Gemini Vision

2. **PDF 파싱**
   - PyPDF2 또는 pdfplumber
   - 텍스트, 이미지, 테이블 추출

3. **Office 문서 파싱**
   - python-docx (Word)
   - openpyxl (Excel)
   - python-pptx (PowerPoint)

4. **STT 통합**
   - OpenAI Whisper API
   - 로컬 Whisper 모델
   - Google Speech-to-Text

5. **화자 분리**
   - pyannote.audio
   - speechbrain

### Phase 3: 고급 기능

1. **비디오 처리 파이프라인**
   - 프레임 추출
   - 비디오 요약
   - 자막 추출

2. **실시간 스트리밍**
   - 점진적 처리
   - 실시간 피드백

3. **고급 크로스 레퍼런스**
   - 의미론적 유사도 분석
   - 엔티티 연결
   - 지식 그래프 구축

4. **자동 품질 평가**
   - 추출 품질 점수
   - 자동 재처리 트리거

## 설계 원칙

### 1. SOLID 원칙 준수

- **Single Responsibility**: 각 파이프라인은 하나의 입력 타입만 처리
- **Open/Closed**: 베이스 클래스 상속으로 확장, 수정 없이 기능 추가
- **Liskov Substitution**: 모든 파이프라인이 BasePipeline 대체 가능
- **Interface Segregation**: 명확한 인터페이스 분리
- **Dependency Inversion**: 추상화에 의존 (BasePipeline, Registry)

### 2. 디자인 패턴

- **템플릿 메서드**: `BasePipeline.process()`
- **전략 패턴**: 각 파이프라인이 전략 객체
- **레지스트리 패턴**: `PipelineRegistry`
- **팩토리 패턴**: `InputRouter`가 적절한 파이프라인 선택
- **싱글톤 패턴**: `PipelineRegistry`

### 3. 비동기 프로그래밍

- 모든 파이프라인 메서드가 `async`
- `asyncio.gather()`로 병렬 처리
- 블로킹 없는 파일 I/O

## 성능 고려사항

1. **병렬 처리**: MultiModalPipeline에서 여러 파이프라인 동시 실행
2. **지연 로딩**: 파이프라인 초기화는 필요 시에만
3. **메모리 관리**: 큰 파일은 스트리밍 처리 (향후 개선)
4. **캐싱**: 중복 처리 방지를 위한 캐싱 (향후 추가)

## 보안 고려사항

1. **파일 크기 제한**: 각 파이프라인에 최대 파일 크기 설정
2. **파일 타입 검증**: MIME 타입 및 확장자 검증
3. **경로 검증**: 파일 경로 정규화 및 검증
4. **입력 정제**: 악의적인 입력 필터링

## 확장성

현재 구조는 다음과 같은 확장을 쉽게 지원합니다:

1. **새 파이프라인 추가**: BasePipeline 상속 및 레지스트리 등록
2. **새 파일 타입**: InputType enum 추가 및 라우터 매핑
3. **커스텀 분석**: 기존 파이프라인 상속 및 analyze() 오버라이드
4. **통합 라이브러리**: 각 파이프라인의 TODO 섹션 구현

## 결론

멀티모달 파이프라인 시스템이 성공적으로 구현되었습니다. 이 시스템은:

- ✅ 느슨한 결합으로 유지보수성 향상
- ✅ 공통 인터페이스로 일관성 보장
- ✅ 점진적 확장 가능한 구조
- ✅ 병렬 처리로 성능 최적화
- ✅ 기존 워크플로우와 원활한 통합

향후 실제 파싱 라이브러리와 Vision/STT 모델을 통합하면 완전한 멀티모달 AI 시스템이 완성됩니다.
