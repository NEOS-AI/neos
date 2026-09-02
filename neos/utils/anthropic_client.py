"""Anthropic 클라이언트를 짓는 단 한 곳.

이 모듈이 생긴 이유는 identity-linked API 키다. 그런 키는 요청마다
`anthropic-workspace-id` 헤더를 요구하고, 없으면 **모든 호출이 400** 이다:

    anthropic-workspace-id is required when authenticating with an
    identity-linked API key; send the id of the workspace this request acts in.

그 헤더를 달아야 할 자리가 저장소에 아홉 곳 있었다 -- deep_analysis 의 LLM
콜러, 코딩 런타임, 챗·아티팩트 서비스, 문서 파이프라인, 비전 파이프라인,
그리고 LangChain 프로바이더. 아홉 곳을 각자 고치는 것은 **같은 사실을 아홉
번 적는 것**이고, 이 저장소는 그 드리프트를 CA12 로 이미 추적 중이다
(`anthropic_features.py` 의 모델 접두사 하드코딩). 그래서 팩토리를 먼저 두고
아홉 곳이 그것을 부른다.

**워크스페이스가 없으면 동작은 이전과 같다.** 헤더를 빈 값으로 보내는 것이
아니라 `default_headers` 자체를 넘기지 않는다 -- 빈 문자열 헤더는 identity 가
아닌 키에 대해 **새 실패를 만든다.** 기존 배포에 무해하다는 주장 전부가
그 한 가지에 걸려 있고, 테스트가 그것을 직접 단언한다.
"""

from __future__ import annotations

from collections.abc import Mapping

from anthropic import AsyncAnthropic

from neos.config.settings import settings

#: API 가 오류 문구에서 부른 이름 그대로. 추측하지 않는다 -- 틀린 이름은
#: 조용히 무시되고 400 은 그대로라, 증상이 "고치기 전" 과 구별되지 않는다.
WORKSPACE_HEADER = "anthropic-workspace-id"


def _configured_workspace_id() -> str | None:
    # `Settings.__getattr__` 는 모르는 이름에 AttributeError 를 낸다. 워크스페이스를
    # 안 쓰는 배포가 이 모듈 하나로 통째로 멈추지 않도록 기본값을 준다.
    return getattr(settings, "ANTHROPIC_WORKSPACE_ID", None)


def anthropic_default_headers(
    workspace_id: str | None = None,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """이 배포가 Anthropic 에 늘 실어야 하는 헤더.

    `workspace_id` 를 주지 않으면 설정에서 읽는다. 비어 있으면 **빈 dict** 를
    돌려준다 -- 호출자는 그것을 그대로 넘기지 말고 생략해야 한다.
    """
    headers = dict(extra or {})
    resolved = workspace_id if workspace_id is not None else _configured_workspace_id()
    if resolved and resolved.strip():
        headers[WORKSPACE_HEADER] = resolved.strip()
    return headers


def build_async_anthropic(
    *,
    api_key: str | None = None,
    workspace_id: str | None = None,
    default_headers: Mapping[str, str] | None = None,
    **kwargs,
) -> AsyncAnthropic:
    """`AsyncAnthropic` 하나. 전 저장소가 여기를 지난다.

    `api_key` 를 명시하면 그것이 이긴다 -- `neos/coding/runtime.py` 는 자기
    시크릿 원천에서 키를 가져오고, 팩토리가 전역 설정을 강제하면 관리형
    샌드박스가 조용히 틀린 키로 돈다.

    워크스페이스는 계정 사실이라 키를 바꿔도 따라온다.
    """
    headers = anthropic_default_headers(workspace_id, extra=default_headers)
    resolved_key = (
        api_key if api_key is not None
        else getattr(settings, "ANTHROPIC_API_KEY", None)
    )
    if headers:
        kwargs["default_headers"] = headers
    return AsyncAnthropic(api_key=resolved_key, **kwargs)
