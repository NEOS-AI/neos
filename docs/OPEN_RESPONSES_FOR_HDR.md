# HyperDeep Research Agent — OpenResponses 스펙 준수 분석

> 분석 기준: `docs/OPEN_RESPONSES_SPEC.md`
> 분석 대상: HyperDeep Research Agent (HDR) 및 관련 인프라
> 작성일: 2026-03-09

---

## 요약

| 카테고리 | 준수율 | 상태 |
|---|---|---|
| Response 객체 구조 | 40% | 🔴 모델은 존재하나 HDR에서 미사용 |
| Streaming 이벤트 | 60% | 🟡 SSE 포맷 준수, HDR Phase 이벤트 누락 |
| 에러 처리 | 50% | 🟡 레거시 어댑터 처리, Executor 포맷 불일치 |
| 토큰 Usage | 20% | 🔴 추적만 있고 응답에 미반영 |
| Reasoning 노출 | 10% | 🔴 모델 정의만 있고 실제 미사용 |
| **전체** | **~36%** | 🔴 **인프라와 HDR 사이 연결 단절** |

---

## 1. 준수 항목 (Compliant)

### 1.1 OpenResponses 모델 계층 — `neos/api/models/open_responses.py`

다음 모델들이 스펙을 완전히 준수하며 구현되어 있습니다.

| 스펙 항목 | 구현 클래스 | 코드 위치 |
|---|---|---|
| Response 객체 | `ResponseObject` | `open_responses.py:126-139` |
| Message 아이템 (§2.1) | `MessageItem` | `open_responses.py:70-83` |
| Function Call 아이템 (§2.2) | `FunctionCallItem` | `open_responses.py:85-93` |
| Reasoning 아이템 (§2.3) | `ReasoningItem` | `open_responses.py:95-103` |
| 상태 열거형 (§8) | `ItemStatus`, `ResponseStatus` | `open_responses.py:21-35` |
| 에러 구조 (§6.1) | `ErrorInfo` | `open_responses.py:118-124` |
| 확장 이벤트 prefix (§2.4) | `NeosArtifactMetaEvent` 등 `neos:*` | `open_responses.py:250-293` |

### 1.2 SSE 스트리밍 형식 — `neos/api/adapters/stream_adapter.py`

```
event: response.output_text.delta
data: {"type": "response.output_text.delta", "delta": "..."}

data: [DONE]
```

- `format_sse_event()` (`stream_adapter.py:244-258`): `event:` 줄과 `data:` 줄이 스펙 §5.5 형식과 일치
- `format_done_token()` (`stream_adapter.py:261-263`): `[DONE]` 종료 토큰 스펙 §5.4 준수
- 상태 머신 이벤트 (`stream_adapter.py:87-239`): `response.in_progress → response.completed/failed` 전환 구현

### 1.3 에러 타입 매핑 — `neos/api/models/open_responses.py:365-383`

`map_error_type()` 함수가 레거시 에러 타입을 OpenResponses 표준 타입으로 변환합니다.

| 레거시 타입 | OpenResponses 타입 | HTTP 상태코드 |
|---|---|---|
| `bad_request` | `invalid_request` | 400 |
| `rate_limit` | `too_many_requests` | 429 |
| `not_found` | `not_found` | 404 |
| `offline` | `server_error` | 500 |

---

## 2. 미준수 / 갭 항목 (Non-Compliant)

### 🔴 2.1 [심각] HDR `format_output()`이 OpenResponses `ResponseObject`를 반환하지 않음

**파일:** `neos/agents/base.py:115-124`

```python
# 현재 반환 형식 (OpenResponses 비준수)
def format_output(self, result: Any, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    return {
        "agent": self.name,
        "result": result,
        "results": result if isinstance(result, list) else [result],
        "metadata": metadata or {},
        "timestamp": datetime.now().isoformat(),
        "success": True
    }
```

**스펙 요구 형식 (§9):**
```json
{
  "id": "resp_abc123",
  "object": "response",
  "created_at": 1699000000,
  "status": "completed",
  "output": [
    {
      "type": "message",
      "id": "msg_001",
      "role": "assistant",
      "status": "completed",
      "content": [{"type": "output_text", "text": "..."}]
    }
  ],
  "usage": {"input_tokens": 10, "output_tokens": 15}
}
```

**영향:** `HyperDeepExecutor.execute()` (`hyper_deep/executor.py:101-154`)가 마크다운 문자열만 반환. ROMA 파이프라인에서 HDR 결과가 OpenResponses 형식과 완전히 단절됩니다.

---

### 🔴 2.2 [심각] HDR 내부 Phase 이벤트가 OpenResponses SSE로 노출되지 않음

**파일:** `neos/agents/search_agents/hyper_deep_research/agent.py` (Phase 0~8 메서드들)

HDR은 8개 Phase를 실행하며 각 Phase마다 `ResearchEventLogger`를 통해 이벤트를 기록합니다.

```python
# agent.py:451 — Phase 0 예시
await self.event_logger.log_phase_start(0, "Skill and Tool Selection")
# ...
await self.event_logger.log_phase_complete(0, "Skill and Tool Selection", duration)
```

**문제:** `ResearchEventLogger`는 DB 저장 및 CLI 출력만 담당합니다. 이 이벤트들이 `stream_adapter.py`의 `adapt_legacy_event()`를 거치지 않으므로 클라이언트는 8개 Phase 진행 상황을 실시간으로 수신할 수 없습니다.

**스펙 요구 (§2.2, §5.2):** 각 Phase는 `function_call` 아이템으로 표현되어야 합니다.

```json
// Phase 시작 시
{
  "type": "response.output_item.added",
  "item": {
    "type": "function_call",
    "name": "hyper_deep:phase_topic_analysis",
    "status": "in_progress"
  }
}

// Phase 완료 시
{
  "type": "response.output_item.done",
  "item": {
    "type": "function_call",
    "name": "hyper_deep:phase_topic_analysis",
    "status": "completed"
  }
}
```

**누락된 이벤트 매핑 목록:**

| HDR Phase | 기대 function_call 이름 |
|---|---|
| Phase 0: Skill Selection | `hyper_deep:phase_skill_selection` |
| Phase 1: Topic Analysis | `hyper_deep:phase_topic_analysis` |
| Phase 2: Research Planning | `hyper_deep:phase_research_planning` |
| Phase 3: Data Collection | `hyper_deep:phase_data_collection` |
| Phase 4: Deep Analysis | `hyper_deep:phase_deep_analysis` |
| Phase 5: Gap Analysis | `hyper_deep:phase_gap_analysis` |
| Phase 6: Cross-Validation | `hyper_deep:phase_cross_validation` |
| Phase 7: Critical Analysis | `hyper_deep:phase_critical_analysis` |
| Phase 8: Final Report | `hyper_deep:phase_final_report` |

---

### 🔴 2.3 [심각] `usage` 토큰 수가 응답에 미반영

**파일:** `neos/agents/search_agents/hyper_deep_research/agent.py:138-154` (메타데이터 정의)

HDR은 내부적으로 LLM 토큰을 추적합니다.

```python
self.research_metadata = {
    "estimated_total_tokens": 0,   # 추적 중
    "llm_calls": 0,
    ...
}
```

그러나 `execute()` 메서드의 `format_output()` 호출부 (`agent.py:319`)에서 이 값이 `UsageInfo`로 변환되지 않습니다.

**스펙 요구 (§9):**
```json
{
  "usage": {
    "input_tokens": 45200,
    "output_tokens": 8300
  }
}
```

---

### 🟡 2.4 [보통] `HyperDeepExecutor` 오류 반환 형식 불일치

**파일:** `neos/workflow/hyper_deep/executor.py:156-167`

```python
# 현재 오류 반환 (비준수)
except Exception as e:
    task.status = TaskStatus.FAILED
    return (
        f"[HyperDeep 실행 오류: {task.description[:40]}] "
        f"오류 내용: {str(e)[:100]}"
    )
```

오류 시 마크다운 문자열을 반환하며, 호출자가 오류와 정상 결과를 프로그래밍적으로 구분할 수 없습니다.

**스펙 요구 (§6.1):**
```json
{
  "error": {
    "type": "server_error",
    "message": "HyperDeep execution failed",
    "code": "hyper_deep_execution_error"
  }
}
```

---

### 🟡 2.5 [보통] `stream_adapter.py`가 HDR 전용 이벤트 타입 미지원

**파일:** `neos/api/adapters/stream_adapter.py:67-241`

현재 어댑터가 처리하는 레거시 이벤트 타입:
- `start`, `content`, `complete`, `error`
- `workflow_node_start`, `workflow_node_complete`
- `artifact_meta`, `artifact_delta`, `artifact_finish`
- `workflow_progress`

**누락된 HDR 전용 이벤트 타입:**
- `hyper_deep_phase_start` / `hyper_deep_phase_complete`
- `research_data_collected` (소스 수집 진행률)
- `research_analysis_iteration` (반복 분석 진행)

`stream_adapter.py`에 HDR 이벤트 브랜치가 없으므로 HDR을 워크플로우 내에서 실행하더라도 세부 진행 이벤트가 클라이언트에 전달되지 않습니다.

---

### 🟡 2.6 [보통] `ReasoningItem` 미활용

**파일:** `neos/api/models/open_responses.py:95-103`

`ReasoningItem` 모델이 완전히 구현되어 있고 `create_reasoning_start_events()` 등 헬퍼 함수도 `stream_adapter.py:389-461`에 준비되어 있습니다.

그러나 HDR의 핵심 추론 단계인 Phase 1(Topic Analysis), Phase 7(Critical Analysis)의 사고 과정이 `reasoning` 타입 아이템으로 노출되지 않습니다. 클라이언트는 HDR이 어떤 근거로 분석하는지 실시간으로 확인할 수 없습니다.

**스펙 요구 (§2.3):**
```json
{
  "type": "reasoning",
  "content": "주제 분석: 이 질문은 기술적 깊이와 역사적 맥락을 모두 요구하며...",
  "summary": "다각적 접근이 필요한 복합 주제로 판단"
}
```

---

### 🟢 2.7 [개선 권장] `tool_choice` / `allowed_tools` Request 파라미터 미지원

**파일:** `neos/api/handlers/async_research_handlers.py` (추정)

HDR은 Phase 0에서 내부적으로 스킬/도구를 선택하지만, API 요청 시 `tool_choice` 또는 `allowed_tools`로 외부에서 이를 제어할 수 없습니다.

**스펙 요구 (§3.3, §3.4):** 클라이언트가 특정 검색 도구만 허용하거나 강제 실행할 수 있어야 합니다.

---

### 🟢 2.8 [개선 권장] `previous_response_id` 연속 대화 미지원

HDR은 독립 실행(stateless)만 지원합니다. 이전 연구 결과를 이어받아 심화 분석하는 패턴이 없습니다.

**스펙 요구 (§4.2):** `previous_response_id`를 통해 이전 응답 컨텍스트를 재사용할 수 있어야 합니다.

---

## 3. 핵심 구조 문제: 인프라-HDR 연결 단절

아래 다이어그램은 현재 아키텍처의 단층을 시각화합니다.

```
[클라이언트]
    │
    ▼ SSE
[workflow_stream_handlers.py]
    │
    ▼ WorkflowStreamCallback (이벤트 큐)
[stream_adapter.py]  ◄── OpenResponses 변환 레이어
    │
    ▼ LangGraph 노드 이벤트
[HYPER_DEEP_ORCHESTRATOR 노드]
    │
    ▼ RecursiveOrchestrator.execute()
[HyperDeepExecutor.execute()]
    │
    ▼ HyperDeepResearchAgent.execute()
    │
    ├── ResearchEventLogger  ──► DB 저장 (OpenResponses 외부)
    │                             ↑ 클라이언트 도달 불가
    └── format_output()  ──► {"agent", "result", ...}  (비준수 포맷)
```

**문제의 본질:** `open_responses.py`와 `stream_adapter.py`는 일반 워크플로우를 위해 잘 설계되어 있습니다. 그러나 HDR은 내부에 독립적인 이벤트 시스템(`ResearchEventLogger`)을 보유하고 있어, 8개 Phase 이벤트가 OpenResponses 파이프라인을 우회합니다.

---

## 4. 개선 로드맵

### 우선순위 High (핵심 준수를 위해 필수)

1. **`HyperDeepExecutor.execute()` 반환 타입을 OpenResponses 형식으로 변경**
   - `base.py:format_output()`을 `ResponseObject`로 래핑하거나
   - `executor.py`에서 직접 `ResponseObject` 반환

2. **`ResearchEventLogger`를 OpenResponses SSE 브릿지로 연결**
   - Phase 시작/완료 시 `function_call` 아이템 이벤트를 `WorkflowStreamCallback`으로 전달
   - `stream_adapter.py`에 `hyper_deep_phase_*` 이벤트 타입 핸들러 추가

3. **`usage` 토큰 정보 응답 반영**
   - `research_metadata["estimated_total_tokens"]`를 `UsageInfo`로 변환
   - `agent.py:format_output()` 호출 시 전달

### 우선순위 Medium

4. **`HyperDeepExecutor` 오류를 구조화된 형식으로 반환**
   - 마크다운 오류 문자열 대신 `{"error": {...}}` 딕셔너리 반환

5. **Phase 1, 7의 LLM 추론을 `ReasoningItem`으로 노출**
   - `stream_adapter.py`의 `create_reasoning_start_events()` 활용 가능

### 우선순위 Low

6. `allowed_tools` / `tool_choice` API 파라미터 추가
7. `previous_response_id` 기반 연속 연구 지원

---

## 5. 결론

NEOS 프로젝트는 OpenResponses 표준을 위한 **인프라(모델, 어댑터)는 잘 갖추고 있습니다.** 문제는 HyperDeep Research Agent가 이 인프라를 사용하지 않고 독립적인 내부 이벤트 시스템으로만 동작한다는 점입니다.

전체 파이프라인에서 HDR 결과와 진행 이벤트가 OpenResponses 표준으로 노출되려면, **`ResearchEventLogger` ↔ `WorkflowStreamCallback` 브릿지** 구현과 **`format_output()` 반환 타입 교체**가 핵심 작업입니다.
