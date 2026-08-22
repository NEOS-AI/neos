"""하네스의 모델 역할 배정 -- `resolve_model` 을 부르는 유일한 지점.

이 파일이 생기기 전에는 역할 리터럴(`"everyday"`/`"powerful"`)이 9개 호출
지점에 하드코딩돼 있었고, 표본 스크립트의 `_resolved_models()` 가 열 번째
사본이었다. 그 함수의 docstring 이 위험을 직접 적어놨다 -- "A role guessed
here would put a lie in the one artifact that cannot be regenerated."

매니페스트(H1)가 "실제로 돈 모델"을 적으려면 사본이 하나여야 한다.
"""

from __future__ import annotations

from neos.config.model_routing import ModelResolution, resolve_model
from neos.config.settings import settings

# 프로바이더는 `"anthropic"` 고정이다 -- 이전 전 9개 호출 지점 전부가 그랬다.
# 이것을 설정으로 여는 것은 로드맵 §4.2 라우팅 불변식에 닿으므로 H1 범위 밖이다.
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
        provider=_PROVIDER,
        role=role,
        feature_override=override,
    )


def resolve_all() -> dict[str, ModelResolution]:
    return {name: resolve_harness_model(name) for name in HARNESS_ROLES}
