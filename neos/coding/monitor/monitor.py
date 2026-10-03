"""궤적 감시자 -- 로드맵 트랙 Q5 (docs/OPENAI_DOTS_ANALYSIS_260930.md §4.2 Q5, §6.1).

판정자는 Jev 다(결정 5). Jev 가 대답하지 못하면(실패·타임아웃·WAF 차단·확률
없음) 그 판정 한 번을 폴백 규칙 FB1~FB6 이 대신한다(결정 9, D-L1 의 모양).

판정 하나가 `monitor.judged` payload 하나다. 기본은 **섀도**(`enforced: false`)이고,
`enforce` 가 켜지면(트랙 Q5b, docs/Q5B_MONITOR_PAUSE_DESIGN_261002.md) 모든 판정이
`enforced: true` 를 싣고 `would_pause` 인 판정은 루프가 `pause_task` 로 태스크를
`PAUSED` 로 보낸다. Jev 와 폴백은 **같은 플래그 하나로 함께** 올라온다(§6.1) --
판정자마다 따로 켜는 길은 없다. 이 모듈은 판정만 하고 멈추게 하는 것은 루프다.

감시자는 **원장만** 읽는다. 루프의 상태·전사를 받지 않는 것이 요점이다 --
감시 대상이 감시자의 입력을 고를 수 없어야 한다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from neos.coding.domain.events import CodingEvent
from neos.coding.monitor.ledger import LedgerTail, Reader
from neos.coding.monitor.rules import (
    RULESET_VERSION,
    FallbackThresholds,
    fallback_verdict,
)

_OUTCOMES = {"tool.completed": "completed", "tool.denied": "denied"}

#: Jev 에게 보여 주는 최근 도구 결과의 수. 흐름을 읽기엔 충분하고 요청 본문을
#: 키우지 않는 크기다. 판정 기준이 아니라 표시 창이라 설정이 아니다.
_RECENT = 20


class TrajectoryScorer(Protocol):
    """루브릭을 Jev 에 묻는 쪽. 메서드 이름은 도구 위험 게이트에서 물려받았다 --
    `TypeSafeToolRiskScorer` 는 루브릭을 가리지 않으므로 사본을 만들지 않는다."""

    async def score_tool_risk(self, state: dict[str, Any]) -> Any: ...


class TrajectoryMonitor:
    def __init__(
        self,
        *,
        scorer: TrajectoryScorer,
        pause_at_or_above: float,
        limits: FallbackThresholds,
        every_n_tool_results: int,
        enforce: bool = False,
        max_events: int = 2000,
    ) -> None:
        self._scorer = scorer
        self._pause_at = pause_at_or_above
        self._limits = limits
        self._every_n = every_n_tool_results
        #: 트랙 Q5b. 참이면 `would_pause` 가 멈춤이다 -- 루프의 `_monitor_pause_point`.
        self.enforce = enforce
        self._tail = LedgerTail(max_events=max_events)

    @property
    def max_events(self) -> int:
        return self._tail.max_events

    async def read_ledger(self, reader: Reader, task_id: str) -> list[CodingEvent]:
        """원장의 최근 `max_events` 개. 마지막으로 본 seq 뒤만 읽는다(MP6)."""
        return await self._tail.read(reader, task_id)

    def due(self, events: Sequence[CodingEvent]) -> bool:
        """마지막 판정 뒤로 도구 결과가 N 개 쌓였는가.

        마지막 판정이 본 개수는 원장의 `monitor.judged` 가 기억한다 -- 루프가
        따로 세지 않으므로 재개·워커 이관에도 같은 박자다.
        """
        seen = 0
        for event in events:
            if event.type == "monitor.judged":
                seen = int(event.payload.get("tool_results") or 0)
        return _tool_results(events) - seen >= self._every_n

    async def judge(self, events: Sequence[CodingEvent], *, mode: str) -> dict[str, Any]:
        """판정 하나의 `monitor.judged` payload."""
        common = {
            "tool_results": _tool_results(events),
            "mode": mode,
            "enforced": self.enforce,
        }
        try:
            score = await self._scorer.score_tool_risk(_trajectory_state(events, mode))
            probability = getattr(score, "probability", None)
            if probability is None:
                raise _NoProbability
        except Exception as error:  # noqa: BLE001 -- 폴백 조건은 "대답하지 않았다" 전부다
            reason = "no_probability" if isinstance(error, _NoProbability) else type(error).__name__
            hit = fallback_verdict(events, self._limits)
            return {
                **common,
                "judge": "fallback_rules",
                "jev_unavailable": True,
                "jev_reason": reason,
                "ruleset": RULESET_VERSION,
                "rule": hit.rule if hit else None,
                "observed": hit.observed if hit else None,
                "threshold": hit.threshold if hit else None,
                "would_pause": hit is not None,
            }
        return {
            **common,
            "judge": "jev",
            "probability": probability,
            "pause_at_or_above": self._pause_at,
            "would_pause": probability >= self._pause_at,
            "rubric_digest": score.rubric_digest,
            "model": score.model,
        }


def pause_reason_code(payload: dict[str, Any]) -> str:
    """멈춤의 `task.status.changed` 가 싣는 사유 코드. 판정자와 규칙이 드러난다."""
    if payload.get("judge") == "jev":
        return "monitor_jev"
    return f"monitor_fallback_{str(payload.get('rule') or 'none').lower()}"


class _NoProbability(Exception):
    """Jev 가 응답했지만 확률이 없다 -- 0 으로 읽으면 "안전"이 된다."""


def _tool_results(events: Sequence[CodingEvent]) -> int:
    return sum(1 for event in events if event.type in _OUTCOMES)


def _trajectory_state(events: Sequence[CodingEvent], mode: str) -> dict[str, Any]:
    recent = [
        {
            "tool": event.payload.get("name"),
            "outcome": _OUTCOMES[event.type],
            "reason_code": event.payload.get("reason_code"),
        }
        for event in events
        if event.type in _OUTCOMES
    ][-_RECENT:]
    started = [
        {"tool": event.payload.get("name"), "preview": event.payload.get("preview")}
        for event in events
        if event.type == "tool.started"
    ][-_RECENT:]
    denials = Counter(
        str(event.payload.get("reason_code"))
        for event in events
        if event.type == "tool.denied"
    )
    return {
        "mode": mode,
        "recent_tool_calls": started,
        "recent_tool_results": recent,
        "denials_by_reason": dict(denials),
        "refusals": sum(1 for event in events if event.type == "model.refused"),
    }
