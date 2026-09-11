"""계층 어댑터 -- 정본 스키마 하나에 계층마다 어댑터 하나 (§9 D-8 = b안).

`LLMCallRecord` 가 정본이고(`models.py`), 이 모듈은 프레임워크마다 다른 usage
표현을 그 하나로 옮긴다. 로드맵 §11.1 이 지목한 상태 -- "서로 다른 usage
표현이 셋 있고 콜렉터는 그중 하나만 안다" -- 를 끝내기 위한 것이다.

- LangChain 계열: `neos/utils/llm_wrapper.py` 의 `TrackedLLM` (D1a 이후 형태
  판정만 한다)
- deep_analysis: 자체 `LLMResponse` -- `llm.py` 의 `_budgeted_dispatch` 한 곳이
  모든 호출을 지나간다
- coding 루프: `ModelUsage`/`ModelCompleted` -- `TrackedCodingModel` 이 감싼다

**규율 둘.** 어느 어댑터든 (1) 절대 던지지 않는다 -- 계측 실패는 데이터
손실이지만 예외를 올려보내면 그 LLM 호출이나 코딩 루프가 죽는다. (2) 토큰은
API 가 준 것만 옮긴다 -- 설계 §A5, 자체 추정 금지. 못 받았으면 `None` 이고,
0 을 지어내지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

_warned = False


def record_llm_call(
    *,
    provider: str,
    model: str,
    workflow_step: str,
    input_messages: List[Dict[str, Any]],
    output_text: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    latency_ms: Optional[float] = None,
    session_id: str = "",
    user_id: str = "",
    agent_name: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    tags: Optional[List[str]] = None,
    custom_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """한 번의 LLM 호출을 정본 레코드로 남긴다. 절대 던지지 않는다.

    `usage` 는 둘 다 있을 때만 만든다. 한쪽만 받았다고 나머지를 0 으로 채우면
    그것이 곧 자체 추정이고, 하류의 비용 집계가 조용히 틀어진다(§6 ③).
    """
    global _warned
    try:
        from .collector import create_llm_call_record

        usage = None
        if input_tokens is not None and output_tokens is not None:
            usage = {
                "prompt_tokens": int(input_tokens),
                "completion_tokens": int(output_tokens),
                "total_tokens": int(input_tokens) + int(output_tokens),
            }

        create_llm_call_record(
            session_id=session_id,
            user_id=user_id,
            workflow_step=workflow_step,
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_messages=input_messages,
            output_text=output_text,
            usage=usage,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
            tags=tags,
            custom_metadata=custom_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - 계측은 본업을 막지 않는다
        if not _warned:
            # 매 호출마다 로그를 쏟으면 진짜 신호가 묻힌다. 처음 한 번만.
            _warned = True
            logger.warning(
                "LLM call instrumentation failed (%s); collection degraded",
                type(exc).__name__,
            )


class TrackedCodingModel:
    """`CodingModel` 을 감싸 한 스트림당 레코드 하나를 남긴다.

    프로바이더 구현(`model/anthropic.py`)을 건드리지 않는 것이 요점이다 --
    계측이 전송 계층 밖에 있어야 D4(네이티브 SDK 전환)가 그 아래를 바꿔도
    함께 무너지지 않는다.

    `ModelCompleted` 가 usage 를 싣고 오는 유일한 이벤트이므로 그때 기록한다.
    스트림이 그것 없이 끝나면(예외·중단) 레코드도 남기지 않는다 -- 토큰을
    모르는 레코드를 남기느니 없는 편이 낫다.
    """

    def __init__(
        self,
        inner,
        *,
        provider: str = "anthropic",  # 기본값만. 런타임이 실제 벤더를 넘긴다.
        workflow_step: str = "coding_loop",
        session_id: str = "",
        user_id: str = "",
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._workflow_step = workflow_step
        self._session_id = session_id
        self._user_id = user_id

    def stream(self, request) -> AsyncIterator[Any]:
        return self._stream(request)

    async def _stream(self, request) -> AsyncIterator[Any]:
        text_parts: List[str] = []
        async for event in self._inner.stream(request):
            # 형태로만 판정한다 -- coding 패키지를 import 하지 않으므로
            # 이 어댑터가 그 계층에 역의존하지 않는다.
            fragment = getattr(event, "text", None)
            if isinstance(fragment, str):
                text_parts.append(fragment)
            usage = getattr(event, "usage", None)
            if usage is not None:
                record_llm_call(
                    provider=self._provider,
                    model=getattr(request, "model", "") or "",
                    workflow_step=self._workflow_step,
                    input_messages=_messages_of(request),
                    output_text="".join(text_parts),
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    session_id=self._session_id,
                    user_id=self._user_id,
                    custom_metadata={
                        "stop_reason": getattr(event, "stop_reason", "")
                    },
                )
            yield event


def _messages_of(request) -> List[Dict[str, Any]]:
    """요청의 메시지를 dict 목록으로. 모양이 어떻든 던지지 않는다."""
    try:
        messages = getattr(request, "messages", None) or []
        out: List[Dict[str, Any]] = []
        for message in messages:
            if isinstance(message, dict):
                out.append(message)
                continue
            role = getattr(message, "role", None) or "user"
            content = getattr(message, "content", "")
            out.append({"role": str(role), "content": content})
        return out
    except Exception:  # noqa: BLE001
        return []
