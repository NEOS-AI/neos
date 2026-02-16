# OpenResponses Specification 문서

> 출처: https://www.openresponses.org/specification

OpenResponses는 LLM 에이전트 API의 표준 응답 형식을 정의하는 스펙입니다.

## 1. 핵심 개념

### 1.1 Item 기반 아키텍처

OpenResponses는 **아이템(Items)** 기반 아키텍처를 사용합니다. 응답은 여러 아이템의 시퀀스로 구성되며, 각 아이템은 고유한 속성을 가집니다.

**필수 필드:**
- `id`: 아이템의 고유 식별자
- `type`: 아이템 유형 (`"message"`, `"function_call"`, `"reasoning"` 등)
- `status`: 상태 (`"in_progress"`, `"completed"`, `"incomplete"`, `"failed"`)

### 1.2 Items → Items 원칙

아이템은 모델 입력/출력의 기본 단위이며, 양방향으로 사용 가능합니다.

### 1.3 Agentic Loop

모델이 다음 순환 구조로 동작합니다:
1. 입력 인식
2. 추론
3. 도구 호출
4. 결과 반영

---

## 2. Output 타입

### 2.1 Message 아이템

텍스트 콘텐츠를 포함한 응답:

```json
{
  "type": "message",
  "role": "assistant",
  "status": "completed",
  "content": [
    {
      "type": "output_text",
      "text": "응답 텍스트..."
    }
  ]
}
```

### 2.2 Function Call 아이템

도구/함수 호출을 표현:

```json
{
  "type": "function_call",
  "name": "functionName",
  "call_id": "unique_call_id",
  "arguments": "{\"param1\": \"value1\"}"
}
```

### 2.3 Reasoning 아이템

모델의 사고 과정을 노출:

```json
{
  "type": "reasoning",
  "content": "원본 추론 내용",
  "encrypted_content": "암호화된 추론 (선택)",
  "summary": "사용자 친화적 요약"
}
```

### 2.4 확장 아이템

제공자별 커스텀 타입은 `provider_slug:type_name` 형식으로 접두사를 추가해야 합니다.

```json
{
  "type": "openai:computer_use",
  "action": "click",
  "coordinates": [100, 200]
}
```

---

## 3. Tool/Function 정의

### 3.1 외부 호스팅 도구 (Externally-Hosted Tools)

개발자가 실행하고 결과를 반환하는 도구:

```json
{
  "type": "function",
  "name": "get_weather",
  "description": "특정 위치의 날씨 정보를 가져옵니다",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "도시명"
      },
      "unit": {
        "type": "string",
        "enum": ["celsius", "fahrenheit"]
      }
    },
    "required": ["location"]
  }
}
```

### 3.2 내부 호스팅 도구 (Internally-Hosted Tools)

제공자 시스템 내에서 실행되는 도구 (예: 파일 검색, 코드 인터프리터).

### 3.3 tool_choice 제어

| 값 | 설명 |
|---|---|
| `"auto"` | 모델이 판단하여 도구 호출 여부 결정 |
| `"required"` | 반드시 도구를 호출해야 함 |
| `"none"` | 도구 호출 금지 |

### 3.4 allowed_tools

모델이 호출 가능한 도구 목록을 제한하면서 캐시 무효화를 방지합니다.

```json
{
  "allowed_tools": ["get_weather", "search_web"]
}
```

---

## 4. Request 파라미터

### 4.1 필수 파라미터

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `model` | string | 사용할 모델 ID |
| `input` | array | 메시지 배열 |

### 4.2 선택 파라미터

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `tools` | array | 도구 정의 배열 |
| `tool_choice` | string/object | 도구 호출 제어 |
| `previous_response_id` | string | 이전 응답과 연속 |
| `truncation` | string | `"auto"` 또는 `"disabled"` |
| `service_tier` | string | `"standard"`, `"priority"`, `"batch"` |
| `allowed_tools` | array | 호출 가능 도구 목록 |

### 4.3 HTTP 헤더

**필수 요청 헤더:**
- `Authorization`: 개발자 인증 토큰
- `Content-Type: application/json`

**필수 응답 헤더:**
- `Content-Type`: 응답 형식 지정

---

## 5. Streaming 스펙

### 5.1 Delta Events (변경 이벤트)

객체의 점진적 변경을 표현:

```json
{
  "type": "response.output_item.added",
  "sequence_number": 11,
  "item": {...}
}
```

### 5.2 텍스트 스트리밍 흐름

1. `response.content_part.added` - 콘텐츠 부분 추가
2. `response.output_text.delta` - 텍스트 증분 (반복)
3. `response.output_text.done` - 텍스트 완료
4. `response.content_part.done` - 부분 완료
5. `response.output_item.done` - 아이템 완료

### 5.3 State Machine Events

상태 전환 이벤트:
- `response.in_progress`
- `response.completed`
- `response.failed`

### 5.4 스트림 종료

마지막 이벤트는 리터럴 `[DONE]` 문자열입니다.

### 5.5 헤더 요구사항

- `Content-Type: text/event-stream`
- `event` 필드가 본문의 `type`과 일치해야 함

**SSE 형식 예시:**
```
event: response.output_text.delta
data: {"type": "response.output_text.delta", "delta": "Hello"}

event: response.output_text.done
data: {"type": "response.output_text.done", "text": "Hello World"}

data: [DONE]
```

---

## 6. Error 처리

### 6.1 에러 응답 구조

```json
{
  "error": {
    "message": "에러 설명",
    "type": "invalid_request",
    "param": "문제가 된 파라미터명",
    "code": "model_not_found"
  }
}
```

### 6.2 에러 타입별 HTTP 상태코드

| 타입 | HTTP 상태코드 | 설명 |
|---|---|---|
| `server_error` | 500 | 서버 내부 오류 |
| `invalid_request` | 400 | 잘못된 요청 |
| `not_found` | 404 | 리소스를 찾을 수 없음 |
| `model_error` | 500 | 모델 오류 |
| `too_many_requests` | 429 | 요청 제한 초과 |

### 6.3 스트리밍 중 에러

스트리밍 중 에러 발생 시 `response.failed` 이벤트가 전송됩니다.

---

## 7. Content 구조

### 7.1 User Content (입력)

- `input_text`: 텍스트 입력
- 이미지, 오디오, 비디오 등 멀티모달 지원

### 7.2 Model Content (출력)

- `output_text`: 텍스트 출력 (기본)

---

## 8. State Machine 설계

모든 객체는 정의된 상태 집합 내에서 전환하는 상태 머신으로 동작합니다.

```
                    ┌─────────────┐
                    │ in_progress │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │completed │    │incomplete│    │  failed  │
    └──────────┘    └──────────┘    └──────────┘
```

---

## 9. 전체 Response 예시

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
      "content": [
        {
          "type": "output_text",
          "text": "안녕하세요! 무엇을 도와드릴까요?"
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 10,
    "output_tokens": 15
  }
}
```

### Function Call 포함 예시

```json
{
  "id": "resp_abc124",
  "object": "response",
  "status": "completed",
  "output": [
    {
      "type": "function_call",
      "id": "fc_001",
      "call_id": "call_xyz",
      "name": "get_weather",
      "arguments": "{\"location\": \"Seoul\"}",
      "status": "completed"
    },
    {
      "type": "message",
      "id": "msg_002",
      "role": "assistant",
      "status": "completed",
      "content": [
        {
          "type": "output_text",
          "text": "서울의 현재 날씨는 맑음이며, 온도는 15°C입니다."
        }
      ]
    }
  ]
}
```
