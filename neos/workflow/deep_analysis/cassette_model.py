"""LLM 을 카세트로 재생하는 `CodingModel` (로드맵 J3).

`CodingModel` 은 `stream(request)` 하나짜리 프로토콜이라 갈아끼우는 값이 싸다
-- `ToolPort` 와 같은 이유다. 들어가는 자리는
`build_research_runtime(port, *, session_factory, model=None)` 의 `model` 이고,
그 자리가 이미 열려 있었기 때문에 조사 경로를 고치지 않아도 된다.

## 키에서 무엇을 빼는가가 이 모듈의 전부다

`ChildStepper._run_model` 이 짓는 `ModelRequest` 에는 **매번 달라지는 것**이
셋 있다: `turn_id` 는 `f"sat_{uuid4().hex}"`, `task_id`·`run_id` 는 그 실행의
것이다. 셋을 키에 넣으면 재생이 **모든 호출에서 빗나가고**, 그 실패는
"카세트가 비었나?" 처럼 보여 원인을 엉뚱한 데서 찾게 된다.

키에 넣는 것은 **모델이 본 것**이다: system · messages · 도구 목록 · 모델
이름 · 출력 상한. 도구 문구를 고치면 빗나가는 것이 맞다 -- 그 녹음은 더 이상
지금 모델이 무슨 말을 할지에 대한 증거가 아니고, 옛 답을 새 프롬프트의
답인 양 돌려주면 섀도가 **존재하지 않는 실행**을 비교한다.

`neos.coding.loop.durable._request_fingerprint` 가 비슷한 모양을 만들지만
**다른 규칙**이다 -- 그쪽은 thinking 블록이 무엇에 묶이는가를 정하고 messages
를 보지 않는다. 둘을 한 함수로 묶지 않는 이유는 목적이 다르기 때문이고,
해시 자체는 `Cassette.key` 가 이미 갖고 있어 여기서 다시 만들지 않는다.

## 녹음은 턴을 모아서 저장한다

`Cassette.remember` 가 producer 를 받는 모양이라 한 턴을 전부 모은 뒤
저장하고, 그 다음 차례로 내보낸다. `ChildStepper` 에게는 같은 일이다 --
그쪽은 이벤트를 접어 `text_parts` 에 쌓고 스텝 끝에 **한 번** 체크포인트를
쓴다. 델타마다 지속화하는 소비자(`DurableCodingLoop`)에게는 같지 않으므로,
그 경로에 이 래퍼를 쓰려면 먼저 여기를 고쳐야 한다.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator

from neos.coding.model.base import (
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUsage,
    TextDelta,
    ThinkingCompleted,
    ToolCallCompleted,
    ToolInputDelta,
)

from .cassette import Cassette

#: 카세트 안의 종류 이름. `Cassette.key(kind, payload)` 의 첫 인자다.
MODEL_TURN = "subagent_model_turn"


def _encode_event(event: ModelEvent) -> dict[str, Any]:
    """타입 이름을 **같이** 싣는다.

    `asdict` 만 쓰면 필드 모양이 같은 두 종류가 구별되지 않는다. 재생에서
    종류가 바뀌면 `fold_model_event` 가 다른 자리에 접어 넣는다 -- 텍스트가
    도구 호출로, 도구 호출이 텍스트로.
    """
    if isinstance(event, ModelCompleted):
        return {
            "type": "ModelCompleted",
            "stop_reason": event.stop_reason,
            "stop_category": event.stop_category,
            "usage": None if event.usage is None else asdict(event.usage),
        }
    if isinstance(event, ToolCallCompleted):
        return {
            "type": "ToolCallCompleted",
            "tool_call_id": event.tool_call_id,
            "name": event.name,
            "input": dict(event.input),
        }
    if isinstance(event, ToolInputDelta):
        return {
            "type": "ToolInputDelta",
            "tool_call_id": event.tool_call_id,
            "name": event.name,
            "partial_json": event.partial_json,
        }
    if isinstance(event, ThinkingCompleted):
        return {
            "type": "ThinkingCompleted",
            "thinking": event.thinking,
            "signature": event.signature,
        }
    if isinstance(event, TextDelta):
        return {"type": "TextDelta", "text": event.text}
    # 종류가 늘었는데 여기 오지 않았다면 녹음이 그것을 **조용히 잃는다**.
    raise TypeError(f"카세트가 모르는 모델 이벤트: {type(event).__name__}")


def _decode_event(payload: dict[str, Any]) -> ModelEvent:
    kind = payload.get("type")
    if kind == "ModelCompleted":
        usage = payload.get("usage")
        return ModelCompleted(
            stop_reason=payload["stop_reason"],
            stop_category=payload.get("stop_category", ""),
            usage=None if usage is None else ModelUsage(**usage),
        )
    if kind == "ToolCallCompleted":
        return ToolCallCompleted(
            tool_call_id=payload["tool_call_id"],
            name=payload["name"],
            input=payload["input"],
        )
    if kind == "ToolInputDelta":
        return ToolInputDelta(
            tool_call_id=payload["tool_call_id"],
            name=payload["name"],
            partial_json=payload["partial_json"],
        )
    if kind == "ThinkingCompleted":
        return ThinkingCompleted(
            thinking=payload["thinking"], signature=payload["signature"]
        )
    if kind == "TextDelta":
        return TextDelta(text=payload["text"])
    raise TypeError(f"카세트가 모르는 모델 이벤트: {kind!r}")


def _encode_content(item: Any) -> Any:
    """메시지 내용도 타입 이름을 달고 간다 -- `_encode_event` 와 같은 이유.

    키를 만드는 데에만 쓰이므로 되돌릴 필요는 없다. 필요한 것은 **서로 다른
    내용이 서로 다른 문자열이 되는 것**뿐이다.
    """
    if is_dataclass(item):
        return {"type": type(item).__name__, **asdict(item)}
    return {"type": type(item).__name__, "value": str(item)}


def request_key_payload(request: ModelRequest) -> dict[str, Any]:
    """카세트 키의 재료. **모델이 본 것**만 담는다.

    빠진 것: `turn_id`(uuid4) · `task_id` · `run_id`. 실행마다 달라지는
    bookkeeping 이고, 넣으면 재생이 항상 빗나간다.
    """
    return {
        "system": request.system,
        "messages": [
            {
                "role": message.role,
                "content": [_encode_content(item) for item in message.content],
            }
            for message in request.messages
        ],
        "tools": [
            [tool.name, tool.description, dict(tool.input_schema)]
            for tool in request.tools
        ],
        "model": request.model,
        # 출력 상한은 모델이 무엇을 말할 수 있는지를 바꾼다 -- 잘린 답을
        # 안 잘린 답으로 재생하지 않기 위해 키에 넣는다.
        "max_output_tokens": request.limits.max_output_tokens,
    }


class CassetteModel:
    """`CodingModel` 자리. 카세트가 `off` 면 그대로 통과한다.

    통과 모드를 두는 이유는 경로를 하나로 두기 위해서다 -- 라이브와 섀도가
    서로 다른 래퍼를 타면 한쪽만 고쳐지는 날이 온다.
    """

    def __init__(self, cassette: Cassette, *, inner: Any = None) -> None:
        self._cassette = cassette
        self._inner = inner

    async def _collect(self, request: ModelRequest) -> list[dict[str, Any]]:
        if self._inner is None:
            # 조용히 빈 턴을 내지 않는다. 빈 턴은 "모델이 아무 말도 안 했다"
            # 이고, 녹음하면 카세트가 비어 있다는 사실이 답으로 굳는다.
            raise ValueError(
                "카세트가 재생 모드가 아니면 `inner` 모델이 있어야 한다"
            )
        return [_encode_event(event) async for event in self._inner.stream(request)]

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        payload = request_key_payload(request)
        recorded = await self._cassette.remember(
            MODEL_TURN, payload, lambda: self._collect(request)
        )
        for item in recorded:
            yield _decode_event(item)
