"""하네스의 모델 역할 배정 -- `resolve_model` 을 부르는 유일한 지점.

이 파일이 생기기 전에는 역할 리터럴(`"everyday"`/`"powerful"`)이 9개 호출
지점에 하드코딩돼 있었고, 표본 스크립트의 `_resolved_models()` 가 열 번째
사본이었다. 그 함수의 docstring 이 위험을 직접 적어놨다 -- "A role guessed
here would put a lie in the one artifact that cannot be regenerated."

매니페스트(H1)가 "실제로 돈 모델"을 적으려면 사본이 하나여야 한다.
"""

from __future__ import annotations

from neos.config.model_routing import (
    EffortResolution,
    ModelResolution,
    resolve_effort,
    resolve_model,
)
from neos.config.settings import settings

# 역할 기본값의 프로바이더. 이전 전 9개 호출 지점 전부가 anthropic 이었다.
#
# ⚠️ **설정으로 여는 것이 아니다.** 이 상수는 여전히 *역할 기본값*의
# 프로바이더이고, 바뀌는 것은 기능 오버라이드가 명시적으로 다른 프로바이더의
# 모델을 지목했을 때 **보고되는 값**뿐이다(아래 `resolve_harness_model`).
# 로드맵 §4.2 가 금지한 것은 크로스 프로바이더 **폴백**이지 운영자의 명시
# 선택이 아니며, "user → conversation → feature override → role default"
# 우선순위는 그대로다.
_PROVIDER = "anthropic"

HARNESS_ROLES: dict[str, str] = {
    "scout": "everyday",
    "dig": "powerful",
    "synth": "powerful",
    "judge": "everyday",
}


def resolve_harness_model(name: str) -> ModelResolution:
    """`name` 역할이 실제로 해석되는 모델.

    `feature_override` 는 테이블이 아니라 설정에서 읽는다 -- `None` = 역할
    기본값이라는 라우팅 계약의 소비 지점이 거기이고(로드맵 §6 ②),
    이 설계는 그것을 바꾸지 않는다.
    """
    role = HARNESS_ROLES[name]
    override = getattr(settings.config.deep_analysis.models, name)
    return resolve_model(
        config=settings.config.model_routing,
        provider=_provider_for(override),
        role=role,
        feature_override=override,
    )


def _provider_for(override: str | None) -> str:
    """오버라이드가 지목한 모델의 **실제** 프로바이더.

    `resolve_model` 은 오버라이드가 이겨도 넘겨받은 `provider` 를 그대로 되돌려
    준다. 그래서 `judge: gpt-5.6-sol` 같은 크로스 프로바이더 오버라이드에
    `_PROVIDER` 를 그냥 넘기면 `ModelResolution(model="gpt-5.6-sol",
    provider="anthropic")` 이 나온다 -- **이 모듈 독스트링이 경고한 바로 그
    거짓말**이고("A role guessed here would put a lie in the one artifact that
    cannot be regenerated"), H1 매니페스트가 그것을 재생성 불가능한 아티팩트에
    싣는다.

    실제 호출 경로는 이미 옳다 -- `llm.py` 의 `_is_anthropic_model` 이
    카탈로그로 클라이언트와 페이로드 형태를 고른다. 틀린 것은 **보고**뿐이었고,
    보고가 틀리면 판정할 때 무엇이 돌았는지 알 수 없다.

    카탈로그가 모르는 모델이면 `_PROVIDER` 로 둔다 -- 카탈로그는 allowlist 가
    아니므로(§ Model Catalog) 새 모델이 등재 전에도 돌아야 하고, 그 경우
    `_is_anthropic_model` 도 같은 방향으로 폴백한다.
    """
    if not override:
        return _PROVIDER
    from neos.config.model_config import provider_for_model

    return provider_for_model(override) or _PROVIDER


def resolve_all() -> dict[str, ModelResolution]:
    return {name: resolve_harness_model(name) for name in HARNESS_ROLES}


def _supported_levels(model: str) -> tuple[str, ...]:
    """이 모델이 받는 사고량 레벨. 카탈로그만 본다.

    함수로 빼 둔 이유는 테스트가 **카탈로그를 고치지 않고** 게이트 뒤쪽을
    볼 수 있게 하기 위해서다 -- 카탈로그는 모델 사실의 단일 원천이고,
    테스트가 거기에 없는 사실을 심으면 그 사실이 진짜처럼 보인다.
    """
    from neos.config.model_config import effort_levels_for

    return effort_levels_for(model)


def resolve_harness_effort(name: str) -> EffortResolution:
    """`name` 역할이 실제로 도는 **사고량** (로드맵 K5).

    `resolve_harness_model` 과 짝이고, 같은 이유로 여기가 유일한 지점이다 --
    사본이 생기면 매니페스트(H1)가 실제로 돈 것과 다른 값을 싣는다.

    ⚠️ DA 의 `Effort`(scout·dig·synth, 조사 깊이)와 다른 축이다. 설정에서도
    `deep_analysis.model_effort` 와 `deep_analysis.effort` 로 갈라 둔다.

    모델을 여기서 다시 해석하는 이유는 게이트 때문이다 -- 어느 모델로 도는지
    알아야 그 모델이 그 레벨을 받는지 물을 수 있다.
    """
    role = HARNESS_ROLES[name]
    resolved = resolve_harness_model(name)
    return resolve_effort(
        model=resolved.model,
        role=role,
        supported_levels=_supported_levels(resolved.model),
        feature_override=getattr(
            settings.config.deep_analysis.model_effort, name
        ),
        role_default=getattr(settings.config.model_routing.effort, role),
    )
