"""설정 → 실제 클라이언트. **"켜졌는가"를 판단하는 유일한 자리다.**

루프는 설정을 읽지 않는다 -- `JevToolRiskGate` 가 `None` 이면 off 이고, 그
객체를 만들지 말지는 여기서만 정한다. 판단하는 자리가 둘이 되면 "켜졌다고
믿는 자리"와 "실제로 켜진 자리"가 갈라지고, 이 저장소의 고장은 대개 조용하다.

**오설정은 조용히 off 가 되지 않는다.** D-L1 의 폴백은 런타임에 Jev 가
대답하지 않을 때의 이야기다. 키를 넣지 않았거나 모델을 핀하지 않은 것은
오설정이고, 그것이 "게이트 없음"으로 번역되면 §9 가 금지하는 조용한 변화다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neos.jev.banding import RiskBandThresholds
from neos.jev.gate import JevToolRiskGate
from neos.jev.rubric import load_rubric
from neos.jev.scorer import TypeSafeToolRiskScorer

if TYPE_CHECKING:
    from neos.config.schema import JevConfig


class MisconfiguredJev(RuntimeError):
    """켜라고 했는데 켤 수 없다. 조용히 끄는 대신 여기서 멈춘다."""


def build_tool_risk_gate(
    config: "JevConfig",
    *,
    api_key: str | None = None,
    client=None,
) -> JevToolRiskGate | None:
    """도구 위험 밴딩 게이트를 만든다. 꺼져 있으면 `None`.

    Args:
        config: `app.jev`.
        api_key: TypeSafe 키. 빈 문자열은 **통과가 아니라 실패**다. `None`
            이면 저장소 규칙대로 환경에서 찾는다 -- 꺼져 있을 때 키를 찾지
            않으려고 이 순서다(꺼진 배포가 키 없다고 기동에 실패하면 안 된다).
        client: 주입된 클라이언트(테스트용). 없으면 SDK 클라이언트를 만든다.
    """
    banding_on = config.tool_risk_shadow_enabled or config.tool_risk_gate_enabled
    if not (config.enabled and banding_on):
        return None

    if api_key is None:
        api_key = _key_from_environment()

    if not api_key or not api_key.strip():
        raise MisconfiguredJev(
            "jev 도구 위험 밴딩이 켜져 있는데 TYPESAFE_API_KEY 가 없다. "
            "오설정은 '게이트 off' 로 번역되지 않는다."
        )
    if not config.model:
        raise MisconfiguredJev(
            "jev.model 이 비어 있다. 적지 않으면 SDK 기본값 'jev-latest' 로 "
            "도는데, 별칭으로 돈 런은 어떤 모델이 답했는지 모른다."
        )
    if config.low_below is None or config.high_at_or_above is None:
        # `JevConfig` 가 이미 막지만, 이 팩토리는 설정 객체를 직접 받을 수도
        # 있으므로 한 번 더 본다. 임계값 없이 만들어진 게이트는 밴드가 없다.
        raise MisconfiguredJev("jev 밴드 임계값이 없다")

    if client is None:
        from typesafe_sdk import AsyncTypeSafeClient

        client = AsyncTypeSafeClient(
            api_key=api_key,
            model=config.model,
            timeout=config.timeout_sec,
        )

    return JevToolRiskGate(
        scorer=TypeSafeToolRiskScorer(
            client=client,
            model=config.model,
            rubric=load_rubric(config.tool_risk_rubric),
            question=_single_noul_question(config.tool_risk_rubric),
            timeout_sec=config.timeout_sec,
        ),
        thresholds=RiskBandThresholds(
            low_below=config.low_below,
            high_at_or_above=config.high_at_or_above,
        ),
        enforce=config.tool_risk_gate_enabled,
    )


def _key_from_environment() -> str:
    """찾지 못한 것을 빈 문자열로 돌려준다.

    여기서 던지지 않는 이유는 **시끄러운 실패가 한 곳에서 나야** 하기
    때문이다. 아래 검사가 "게이트를 켜라고 했는데 키가 없다"를 말한다.
    """
    from neos.jev.credentials import MissingTypeSafeKey, resolve_typesafe_key

    try:
        return resolve_typesafe_key()
    except MissingTypeSafeKey:
        return ""


def _single_noul_question(rubric_name: str) -> str:
    """지금은 Noul 질문이 **정확히 하나**여야 한다.

    여러 확률을 한 밴드로 합치는 규칙이 아직 없다(D-L2). 그 규칙 없이 여러
    질문을 받으면 어느 하나를 말없이 골라 쓰게 되고, 원장은 나머지를 물었다는
    사실조차 남기지 못한다. 그래서 고르지 않고 **거절한다**.
    """
    rubric = load_rubric(rubric_name)
    nouls = [
        name
        for name, question in rubric.questions.items()
        if question.get("type") == "noul"
    ]
    if len(nouls) != 1:
        raise MisconfiguredJev(
            f"루브릭 {rubric_name!r} 의 noul 질문이 {len(nouls)} 개다. "
            "여러 확률을 한 밴드로 합치는 규칙은 아직 없다(D-L2)."
        )
    return nouls[0]
