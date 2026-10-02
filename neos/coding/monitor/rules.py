"""Q5 폴백 최소 규칙 FB1~FB6 -- Jev 가 대답하지 못할 때만 돈다.

정본: docs/OPENAI_DOTS_ANALYSIS_260930.md §6.1 (결정 9, 2026-09-30).

규칙은 **원장에 이미 있는 이벤트만** 읽는다. 폴백은 무언가가 이미 고장 난
때 돌기 때문에, 새 계측이 있어야 도는 규칙은 폴백이 될 수 없다. 결과는
"멈추게 할 이유"(`FallbackHit`) 하나이거나 없음이다 -- 규칙은 허용·완화·재개를
말하지 못한다(트랙 L 의 "좁히기만").

임계값은 여기 없다(§9 매직넘버 금지). `JevMonitorConfig` 가 싣고, 설정은
그것을 **더 엄하게만** 움직일 수 있다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from neos.coding.domain.events import CodingEvent

#: 규칙 집합의 버전. 규칙의 뜻이 바뀌면 올린다 -- 버전 없는 판정은 재현할 수 없다(§9).
RULESET_VERSION = "fb-1"

_OUTCOME_KINDS = frozenset({"tool.completed", "tool.denied"})


@dataclass(frozen=True, slots=True)
class FallbackThresholds:
    user_only: int
    mode_ceiling: int
    denial_window: int
    denials_in_window: int
    repeated_call: int
    refusals: int
    spend_multiple: float
    spend_warmup_turns: int


@dataclass(frozen=True, slots=True)
class FallbackHit:
    rule: str
    observed: float
    threshold: float


def fallback_verdict(
    events: Sequence[CodingEvent], limits: FallbackThresholds
) -> FallbackHit | None:
    """가장 엄한 규칙부터 본다. 먼저 걸린 규칙의 이름을 단다."""
    for check in (_fb1, _fb2, _fb3, _fb4, _fb5, _fb6):
        hit = check(events, limits)
        if hit is not None:
            return hit
    return None


def _denials(events: Sequence[CodingEvent], reason: str) -> int:
    return sum(
        1
        for event in events
        if event.type == "tool.denied" and event.payload.get("reason_code") == reason
    )


def _at_least(rule: str, observed: float, threshold: float) -> FallbackHit | None:
    return FallbackHit(rule, observed, threshold) if observed >= threshold else None


def _fb1(events, limits):
    """위임 불가 시도 -- USER_ONLY 판정이 난 호출."""
    return _at_least("FB1", _denials(events, "policy_user_only"), limits.user_only)


def _fb2(events, limits):
    """모드 천장 위반 -- background 태스크가 READ_ONLY 밖을 시도했다."""
    return _at_least("FB2", _denials(events, "policy_mode_ceiling"), limits.mode_ceiling)


def _fb3(events, limits):
    """반복 거절 -- 최근 도구 결과 창 안에서 거절이 몰린다."""
    outcomes = [event for event in events if event.type in _OUTCOME_KINDS]
    window = outcomes[-limits.denial_window :]
    denied = sum(1 for event in window if event.type == "tool.denied")
    return _at_least("FB3", denied, limits.denials_in_window)


def _fb4(events, limits):
    """같은 호출 반복 -- 같은 도구 + 같은 입력 요약이 되풀이된다.

    `tool.started` 는 입력 전문이 아니라 `preview` 를 싣는다. 요약이 같으면 같은
    호출로 센다 -- 원장에 있는 것만 읽는다는 규칙의 값이다.
    """
    counts = Counter(
        (event.payload.get("name"), event.payload.get("preview"))
        for event in events
        if event.type == "tool.started"
    )
    worst = max(counts.values(), default=0)
    return _at_least("FB4", worst, limits.repeated_call)


def _fb5(events, limits):
    """모델 거절 -- 주입된 지시를 만났을 가능성."""
    refused = sum(1 for event in events if event.type == "model.refused")
    return _at_least("FB5", refused, limits.refusals)


def _fb6(events, limits):
    """지출 급증 -- 한 턴의 토큰이 그 앞 턴들의 중앙값의 k 배를 넘는다.

    토큰을 싣지 않은 `model.completed`(이 규칙 이전의 원장)는 건너뛴다.
    없는 값은 0 이 아니다 -- 0 으로 읽으면 중앙값이 내려가 오탐이 난다.
    """
    turns = [
        int(event.payload["input_tokens"]) + int(event.payload.get("output_tokens") or 0)
        for event in events
        if event.type == "model.completed" and "input_tokens" in event.payload
    ]
    for index in range(limits.spend_warmup_turns, len(turns)):
        baseline = median(turns[:index])
        if baseline > 0 and turns[index] > limits.spend_multiple * baseline:
            return FallbackHit("FB6", turns[index] / baseline, limits.spend_multiple)
    return None
