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
    nouls = _noul_questions(config.tool_risk_rubric)
    thresholds = _thresholds_for(config, nouls)

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
            question=nouls[0] if isinstance(thresholds, RiskBandThresholds) else None,
            questions=() if isinstance(thresholds, RiskBandThresholds) else nouls,
            timeout_sec=config.timeout_sec,
        ),
        thresholds=thresholds,
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


def build_trajectory_monitor(
    config: "JevConfig",
    *,
    api_key: str | None = None,
    client=None,
):
    """궤적 감시자(트랙 Q5)를 만든다. 꺼져 있으면 `None`.

    도구 위험 게이트와 같은 규율이다: 켜졌는지 판단하는 자리는 여기 하나이고,
    키 없음·모델 미핀은 "감시자 없음"이 아니라 기동 실패다.
    """
    from neos.coding.monitor.monitor import TrajectoryMonitor
    from neos.coding.monitor.rules import FallbackThresholds

    monitor = config.monitor
    if not (config.enabled and monitor.shadow_enabled):
        return None
    if monitor.pause_at_or_above is None:
        raise MisconfiguredJev("jev.monitor.pause_at_or_above 가 없다")
    if api_key is None:
        api_key = _key_from_environment()
    if not api_key or not api_key.strip():
        raise MisconfiguredJev(
            "궤적 감시자가 켜져 있는데 TYPESAFE_API_KEY 가 없다. "
            "오설정은 '감시자 없음' 으로 번역되지 않는다."
        )
    if not config.model:
        raise MisconfiguredJev("jev.model 이 비어 있다 -- 별칭으로 돈 판정은 재현할 수 없다.")
    nouls = _noul_questions(monitor.rubric)
    if len(nouls) != 1:
        raise MisconfiguredJev(
            f"궤적 루브릭 {monitor.rubric!r} 은 noul 질문이 하나여야 한다: {nouls}"
        )
    if client is None:
        from typesafe_sdk import AsyncTypeSafeClient

        client = AsyncTypeSafeClient(
            api_key=api_key, model=config.model, timeout=config.timeout_sec
        )
    return TrajectoryMonitor(
        scorer=TypeSafeToolRiskScorer(
            client=client,
            model=config.model,
            rubric=load_rubric(monitor.rubric),
            question=nouls[0],
            timeout_sec=config.timeout_sec,
        ),
        pause_at_or_above=monitor.pause_at_or_above,
        limits=FallbackThresholds(
            user_only=monitor.user_only,
            mode_ceiling=monitor.mode_ceiling,
            denial_window=monitor.denial_window,
            denials_in_window=monitor.denials_in_window,
            repeated_call=monitor.repeated_call,
            refusals=monitor.refusals,
            spend_multiple=monitor.spend_multiple,
            spend_warmup_turns=monitor.spend_warmup_turns,
        ),
        every_n_tool_results=monitor.every_n_tool_results,
    )


def _noul_questions(rubric_name: str) -> tuple[str, ...]:
    """루브릭의 noul 질문 이름들, 루브릭에 적힌 순서대로."""
    rubric = load_rubric(rubric_name)
    nouls = tuple(
        name
        for name, question in rubric.questions.items()
        if question.get("type") == "noul"
    )
    if not nouls:
        raise MisconfiguredJev(f"루브릭 {rubric_name!r} 에 noul 질문이 없다")
    return nouls


def _thresholds_for(
    config: "JevConfig", nouls: tuple[str, ...]
) -> "RiskBandThresholds | dict[str, RiskBandThresholds]":
    """루브릭의 질문과 설정의 경계를 **정확히** 맞춘다.

    질문이 하나면 단일 경계(`low_below`/`high_at_or_above`)를 쓴다. 둘 이상이면
    (D-L2, 2026-09-24 쪼개기로 결정) 질문마다 경계가 있어야 한다 -- 빠진
    질문을 기본 경계로 채우면 그 축의 임계값이 **아무도 정하지 않은 값**이 되고,
    남는 키는 루브릭이 바뀌었는데 설정이 따라오지 않았다는 신호다. 둘 다
    조용히 넘기지 않는다.

    합치는 규칙은 없다. 게이트가 질문마다 밴딩해 가장 엄한 결과를 취한다.
    """
    per_question = config.question_thresholds
    if len(nouls) == 1 and not per_question:
        if config.low_below is None or config.high_at_or_above is None:
            # `JevConfig` 가 이미 막지만, 설정 객체를 직접 받을 수도 있다.
            raise MisconfiguredJev("jev 밴드 임계값이 없다")
        return RiskBandThresholds(
            low_below=config.low_below,
            high_at_or_above=config.high_at_or_above,
        )
    missing = [name for name in nouls if name not in per_question]
    extra = sorted(set(per_question) - set(nouls))
    if missing or extra:
        raise MisconfiguredJev(
            f"루브릭 {config.tool_risk_rubric!r} 의 질문과 jev.question_thresholds 가 "
            f"맞지 않는다 -- 빠진 질문: {missing}, 루브릭에 없는 키: {extra}. "
            "질문마다 경계를 명시해야 한다(D-L2)."
        )
    return {
        name: RiskBandThresholds(
            low_below=per_question[name].low_below,
            high_at_or_above=per_question[name].high_at_or_above,
        )
        for name in nouls
    }
