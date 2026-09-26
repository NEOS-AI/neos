"""해석된 사고량(effort)을 프로바이더 요청 필드로 번역한다.

번역은 여기 한 곳에만 있다. LangChain 경로(create_llm)와 Anthropic SDK 경로
(chat 의 tool 경로)가 모두 이것을 부른다 -- 두 곳에 있으면 한쪽만 고쳐진다.

effort 가 None 이면 **키를 넣지 않는다.** `{"effort": None}` 은 SDK 에 따라
null 로 나가고, 그것은 "보내지 않음" 과 같은 뜻이라는 보장이 없다.
"""

from __future__ import annotations

from typing import Any


def effort_request_fields(provider: str, effort: str | None) -> dict[str, Any]:
    if effort is None:
        return {}
    if provider == "anthropic":
        return {"output_config": {"effort": effort}}
    if provider == "openai":
        return {"reasoning_effort": effort}
    raise ValueError(f"provider {provider!r} takes no effort, got {effort!r}")
