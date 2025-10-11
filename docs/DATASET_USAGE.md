# NEOS LLM 호출 데이터셋 시스템 사용 가이드

멀티 에이전트 워크플로우의 모든 LLM 호출을 추적하고 데이터셋으로 저장하는 시스템입니다.

## 📋 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [설치 및 설정](#설치-및-설정)
4. [사용 방법](#사용-방법)
5. [CLI 명령어](#cli-명령어)
6. [데이터 형식](#데이터-형식)
7. [통합 예제](#통합-예제)

## 개요

### 주요 기능

- **자동 추적**: LLM 호출을 자동으로 추적하고 기록
- **다양한 형식**: JSONL, JSON, CSV, OpenAI, Anthropic 형식 지원
- **필터링 내보내기**: 세션, 에이전트, 워크플로우 단계별 필터링
- **통계 및 분석**: 토큰 사용량, 레이턴시, 성공률 등 자동 계산
- **학습 데이터 변환**: Fine-tuning을 위한 형식으로 자동 변환

### 구성 요소

```
neos/dataset/
├── __init__.py          # 모듈 초기화
├── models.py            # 데이터 모델 (LLMCallRecord, DatasetMetadata)
├── collector.py         # 수집기 및 데코레이터
└── storage.py           # 저장 및 관리
```

## 아키텍처

### 1. 데이터 모델

#### LLMCallRecord
모든 LLM 호출 정보를 저장하는 기본 단위입니다.

```python
from neos.dataset import LLMCallRecord

record = LLMCallRecord(
    call_id="unique-id",
    timestamp="2024-01-01T00:00:00",
    session_id="session-123",
    user_id="user-456",
    workflow_step="query_classifier",
    agent_name="knowledge_search",
    provider="openai",
    model="gpt-4",
    temperature=0.7,
    input_messages=[{"role": "user", "content": "Hello"}],
    output_text="Response text",
    prompt_tokens=100,
    completion_tokens=50,
    total_tokens=150,
    latency_ms=1234.5,
    success=True
)
```

#### DatasetMetadata
데이터셋 전체의 메타데이터 및 통계를 관리합니다.

```python
from neos.dataset import DatasetMetadata

metadata = DatasetMetadata(
    name="my_dataset",
    description="Dataset description"
)
metadata.update_statistics(records)
```

### 2. 수집기 (Collector)

#### LLMCallCollector (싱글톤)
모든 LLM 호출을 메모리에 수집합니다.

```python
from neos.dataset import llm_call_collector

# 활성화/비활성화
llm_call_collector.enable()
llm_call_collector.disable()

# 레코드 조회
all_records = llm_call_collector.get_all_records()
session_records = llm_call_collector.get_records(session_id="session-123")

# 통계 확인
stats = llm_call_collector.get_statistics()

# 초기화
llm_call_collector.clear_records()
```

### 3. 저장 관리자 (Storage Manager)

#### DatasetManager
다양한 형식으로 데이터셋을 저장하고 관리합니다.

```python
from neos.dataset import dataset_manager

# JSONL 저장
filepath = dataset_manager.save_jsonl()

# JSON 저장 (메타데이터 포함)
filepath = dataset_manager.save_json(include_metadata=True)

# CSV 저장
filepath = dataset_manager.save_csv()

# 학습 데이터 형식으로 저장
filepath = dataset_manager.save_training_format(format_type="openai")
filepath = dataset_manager.save_training_format(format_type="anthropic")

# 필터링해서 내보내기
filepath = dataset_manager.export_by_session("session-123")
filepath = dataset_manager.export_by_agent("knowledge_search")
filepath = dataset_manager.export_by_workflow_step("search_orchestrator")
```

## 설치 및 설정

### 1. 모듈 임포트

```python
# 기본 임포트
from neos.dataset import (
    LLMCallRecord,
    DatasetMetadata,
    LLMCallCollector,
    llm_call_collector,
    DatasetManager,
    dataset_manager,
    track_llm_call,
    create_llm_call_record
)
```

### 2. 데이터셋 저장 경로 설정

기본 경로는 `datasets/`이며, 커스터마이징 가능합니다.

```python
from neos.dataset.storage import DatasetManager

# 커스텀 경로 사용
custom_manager = DatasetManager(base_path="my_custom_path/datasets")
```

## 사용 방법

### 방법 1: TrackedLLM 래퍼 사용 (권장)

가장 간단하고 자동화된 방법입니다.

```python
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm

# 기본 LLM 생성
base_llm = create_llm()

# 추적 가능한 LLM으로 래핑
tracked_llm = create_tracked_llm(
    llm=base_llm,
    session_id=state["session_id"],
    user_id=state["user_id"],
    workflow_step="search_orchestrator",
    agent_name="knowledge_search",
    tags=["search", "production"]
)

# 일반적인 LLM처럼 사용
response = await tracked_llm.ainvoke(messages)
# 또는
response = tracked_llm.invoke(messages)
```

### 방법 2: 데코레이터 사용

메서드에 데코레이터를 적용하여 자동 추적합니다.

```python
from neos.dataset.collector import track_llm_call

class MyAgent:
    @track_llm_call(
        workflow_step="query_classifier",
        agent_name="classifier",
        tags=["classification"]
    )
    async def classify_query(self, state):
        # LLM 호출
        response = await self.llm.ainvoke(messages)

        # 결과에 _llm_call_info 추가 (선택사항)
        return {
            "classification": result,
            "_llm_call_info": {
                "provider": "openai",
                "model": "gpt-4",
                "input_messages": [{"role": "user", "content": query}],
                "output_text": response.content,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
```

### 방법 3: 수동 기록

완전한 제어가 필요한 경우 수동으로 레코드를 생성합니다.

```python
from neos.dataset.collector import create_llm_call_record

# LLM 호출
response = await llm.ainvoke(messages)

# 수동으로 레코드 생성
record = create_llm_call_record(
    session_id=state["session_id"],
    user_id=state["user_id"],
    workflow_step="response_generator",
    agent_name=None,
    provider="openai",
    model="gpt-4",
    input_messages=[{"role": "user", "content": "Hello"}],
    output_text=response.content,
    usage={
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    },
    latency_ms=1234.5,
    temperature=0.7,
    success=True,
    tags=["custom"]
)
```

## CLI 명령어

### 데이터셋 상태 확인

```bash
python -m neos.cli dataset status
```

출력 예시:
```
📊 Dataset Collection Status
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Metric          ┃ Value   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ Enabled         │ ✅      │
│ Total Records   │ 150     │
│ Successful Calls│ 145     │
│ Failed Calls    │ 5       │
│ Success Rate    │ 96.7%   │
│ Total Tokens    │ 45,230  │
│ Avg Latency     │ 1,234ms │
└─────────────────┴─────────┘
```

### 데이터셋 내보내기

```bash
# 전체 내보내기 (JSONL 형식)
python -m neos.cli dataset export

# JSON 형식으로 내보내기
python -m neos.cli dataset export --format json

# CSV 형식으로 내보내기
python -m neos.cli dataset export --format csv

# OpenAI fine-tuning 형식
python -m neos.cli dataset export --format openai

# Anthropic 형식
python -m neos.cli dataset export --format anthropic

# 특정 세션만 내보내기
python -m neos.cli dataset export --session session-123

# 특정 에이전트만 내보내기
python -m neos.cli dataset export --agent knowledge_search

# 특정 워크플로우 단계만 내보내기
python -m neos.cli dataset export --step query_classifier
```

### 저장된 데이터셋 목록

```bash
python -m neos.cli dataset list-files
```

### 데이터셋 정보 확인

```bash
python -m neos.cli dataset info datasets/neos_llm_calls_20240101_120000.json
```

### 데이터 수집 제어

```bash
# 수집 활성화
python -m neos.cli dataset enable

# 수집 비활성화
python -m neos.cli dataset disable

# 수집된 데이터 초기화
python -m neos.cli dataset clear
```

## 데이터 형식

### 1. JSONL 형식

각 줄이 하나의 JSON 객체입니다.

```jsonl
{"call_id": "abc123", "timestamp": "2024-01-01T00:00:00", "session_id": "session-1", ...}
{"call_id": "def456", "timestamp": "2024-01-01T00:01:00", "session_id": "session-2", ...}
```

### 2. JSON 형식

전체가 하나의 JSON 객체로, 메타데이터와 레코드 배열을 포함합니다.

```json
{
  "metadata": {
    "dataset_id": "...",
    "name": "neos_llm_calls_20240101_120000",
    "total_records": 150,
    "total_tokens": 45230,
    ...
  },
  "records": [
    {"call_id": "abc123", ...},
    {"call_id": "def456", ...}
  ]
}
```

### 3. CSV 형식

기본 필드만 포함된 스프레드시트 형식입니다.

```csv
call_id,timestamp,session_id,user_id,workflow_step,agent_name,provider,model,temperature,prompt_tokens,completion_tokens,total_tokens,latency_ms,success,error_message
abc123,2024-01-01T00:00:00,session-1,user-1,query_classifier,classifier,openai,gpt-4,0.7,100,50,150,1234.5,True,
```

### 4. OpenAI Fine-tuning 형식

OpenAI의 fine-tuning API 형식입니다.

```jsonl
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "metadata": {...}}
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "metadata": {...}}
```

### 5. Anthropic 형식

Anthropic의 학습 데이터 형식입니다.

```jsonl
{"prompt": "user: ...", "completion": "...", "metadata": {...}}
{"prompt": "user: ...", "completion": "...", "metadata": {...}}
```

## 통합 예제

### 워크플로우에 통합

```python
# neos/workflow/utils/query_classifier.py
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm

class QueryClassifier:
    def __init__(self, config):
        self.config = config
        self.base_llm = create_llm(temperature=0.3)

    async def classify_query(self, state):
        # TrackedLLM 생성
        tracked_llm = create_tracked_llm(
            llm=self.base_llm,
            session_id=state["session_id"],
            user_id=state["user_id"],
            workflow_step="query_classifier",
            agent_name=None,
            tags=["classification", "query"]
        )

        # 일반 LLM처럼 사용
        response = await tracked_llm.ainvoke(messages)

        # 결과 반환
        return {"classification": result}
```

### 에이전트에 통합

```python
# neos/agents/search_agents.py
from neos.agents.base import SearchAgent
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm

class KnowledgeSearchAgent(SearchAgent):
    def __init__(self):
        super().__init__(
            name="knowledge_search",
            search_type="knowledge",
            llm=create_llm(),
            role="Knowledge Search Specialist",
            goal="Find relevant information",
            backstory="Expert searcher"
        )

    async def execute(self, query: str, context: dict):
        # TrackedLLM으로 래핑
        tracked_llm = create_tracked_llm(
            llm=self.llm,
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", ""),
            workflow_step="search_orchestrator",
            agent_name=self.name,
            tags=["search", "knowledge"]
        )

        # LLM 호출 (자동으로 추적됨)
        response = await tracked_llm.ainvoke(messages)

        return {"result": response.content}
```

### 프로그래매틱 사용

```python
# 예: 데이터 분석 스크립트
from neos.dataset import dataset_manager, llm_call_collector

# 1. 워크플로우 실행
# ... (여러 LLM 호출 발생)

# 2. 통계 확인
stats = llm_call_collector.get_statistics()
print(f"Total LLM calls: {stats['total_records']}")
print(f"Total tokens: {stats['total_tokens']}")

# 3. 데이터셋 저장
filepath = dataset_manager.save_json(include_metadata=True)
print(f"Dataset saved to: {filepath}")

# 4. Fine-tuning 데이터 생성
training_path = dataset_manager.save_training_format(format_type="openai")
print(f"Training data saved to: {training_path}")

# 5. 세션별 분석
session_records = llm_call_collector.get_records(session_id="session-123")
for record in session_records:
    print(f"Step: {record.workflow_step}, Tokens: {record.total_tokens}")
```

## 활용 사례

### 1. 비용 분석
```python
# 토큰 사용량 기반 비용 계산
records = llm_call_collector.get_all_records()

total_cost = 0
for record in records:
    if record.provider == "openai" and record.model == "gpt-4":
        prompt_cost = (record.prompt_tokens / 1000) * 0.03
        completion_cost = (record.completion_tokens / 1000) * 0.06
        total_cost += prompt_cost + completion_cost

print(f"Total cost: ${total_cost:.2f}")
```

### 2. 성능 분석
```python
# 에이전트별 평균 레이턴시
from collections import defaultdict

latencies = defaultdict(list)

for record in llm_call_collector.get_all_records():
    if record.agent_name and record.latency_ms:
        latencies[record.agent_name].append(record.latency_ms)

for agent, times in latencies.items():
    avg_latency = sum(times) / len(times)
    print(f"{agent}: {avg_latency:.1f}ms")
```

### 3. Fine-tuning 데이터 생성
```bash
# OpenAI fine-tuning을 위한 데이터 생성
python -m neos.cli dataset export --format openai

# 생성된 파일을 OpenAI에 업로드
openai api fine_tunes.create \
  -t datasets/neos_training_openai_20240101_120000.jsonl \
  -m gpt-3.5-turbo
```

### 4. 워크플로우 최적화
```python
# 워크플로우 단계별 토큰 사용량 분석
from neos.dataset.models import DatasetMetadata

records = llm_call_collector.get_all_records()
metadata = DatasetMetadata()
metadata.update_statistics(records)

print("Step-wise token usage:")
for step, count in metadata.step_counts.items():
    step_records = [r for r in records if r.workflow_step == step]
    total_tokens = sum(r.total_tokens or 0 for r in step_records)
    print(f"{step}: {total_tokens:,} tokens ({count} calls)")
```

## 주의사항

1. **메모리 사용**: 수집기는 모든 레코드를 메모리에 보관합니다. 장시간 실행 시 주기적으로 내보내고 초기화하세요.

2. **민감한 정보**: LLM 입력/출력에 민감한 정보가 포함될 수 있습니다. 적절한 보안 조치를 취하세요.

3. **성능 영향**: 추적 시스템은 최소한의 오버헤드를 가지지만, 대규모 운영 환경에서는 모니터링이 필요할 수 있습니다.

4. **비활성화**: 프로덕션 환경에서 데이터 수집이 필요없다면 `llm_call_collector.disable()`로 비활성화하세요.

## 문의 및 기여

- 이슈 리포트: GitHub Issues
- 기여: Pull Requests 환영

---

**NEOS Multi-Agent Workflow Engine**
LLM Call Dataset System v1.0