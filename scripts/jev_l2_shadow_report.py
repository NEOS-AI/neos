"""L2 섀도 판독기 -- 질문별 경계 **값**을 정할 재료를 원장에서 모은다 (로드맵 §12.12).

    .venv/bin/python -m scripts.jev_l2_shadow_report --since 2026-09-24
    .venv/bin/python -m scripts.jev_l2_shadow_report --since 2026-09-24 --try 0.2:0.9 --try 0.3:0.8

## 무엇을 내는가

- **질문별 확률 분포** -- 사분위와 0.1 폭 히스토그램. 경계는 여기서 고른다
- **`jev_unavailable` 비율** -- D-L1 이 감시 조건으로 적은 것. `provider_blocked` 는
  따로 센다(D-L3 이 받아들인 거짓 양성의 크기다)
- **불일치 건별 목록** -- Jev 가 정적 정책(R₀)보다 좁혔을 호출. L3 을 켜기 전에 사람이
  **한 건씩** 읽는다(§12.4). 개수만 보고 켜지 않는다
- **`--try LOW:HIGH`** -- 기록된 확률을 후보 경계로 **다시 밴딩**해 본다. 섀도는 확률을
  그대로 실으므로 경계를 바꿔도 표본을 다시 뜰 필요가 없다

## 하지 않는 것

경계를 **추천하지 않는다.** 분포와 건별 목록까지다. 어떤 거짓 양성을 받아들일지는
사람의 결정이다(D-L1·D-L3 과 같은 종류).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

EVENT_TYPES = ("jev_risk_scored", "jev_unavailable")


@dataclass(frozen=True)
class Bounds:
    low_below: float
    high_at_or_above: float

    @classmethod
    def parse(cls, text: str) -> "Bounds":
        low, high = (float(part) for part in text.split(":"))
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError(f"0 <= LOW <= HIGH <= 1 이어야 한다: {text}")
        return cls(low, high)

    def band(self, probability: float) -> str:
        # 게이트의 밴딩을 그대로 쓴다 -- 사본을 두면 경계 규칙이 한쪽만 바뀐다.
        from neos.jev.banding import RiskBandThresholds, band_for

        return str(band_for(probability, RiskBandThresholds(self.low_below, self.high_at_or_above)))


def question_probabilities(payload: dict[str, Any]) -> dict[str, float]:
    """쪼갠 루브릭은 `questions`, 질문 하나짜리는 최상위 `probability` 를 싣는다."""
    questions = payload.get("questions")
    if questions:
        return {str(q["name"]): float(q["probability"]) for q in questions}
    if payload.get("probability") is not None:
        return {"(single)": float(payload["probability"])}
    return {}


def histogram(values: list[float]) -> list[int]:
    bins = [0] * 10
    for value in values:
        bins[min(int(value * 10), 9)] += 1
    return bins


def summarize(
    rows: Iterable[dict[str, Any]], tries: Iterable[Bounds] = ()
) -> dict[str, Any]:
    """`rows` 는 `{"event_type", "task_id", "tool_call_id", "payload"}`."""
    rows = list(rows)
    scored = [r for r in rows if r["event_type"] == "jev_risk_scored"]
    unavailable = [r for r in rows if r["event_type"] == "jev_unavailable"]
    reasons = Counter(str(r["payload"].get("reason", "?")) for r in unavailable)

    per_question: dict[str, list[float]] = {}
    for row in scored:
        for name, probability in question_probabilities(row["payload"]).items():
            per_question.setdefault(name, []).append(probability)

    def quartiles(values: list[float]) -> list[float] | None:
        if len(values) < 2:
            return None
        return [round(v, 3) for v in statistics.quantiles(values, n=4)]

    disagreements = [
        {
            "task_id": r["task_id"],
            "tool_call_id": r["tool_call_id"],
            "tool": r["payload"].get("tool"),
            "static": r["payload"].get("static_outcome"),
            "jev": r["payload"].get("banded_outcome") or r["payload"].get("would_be_outcome"),
            "unattended": r["payload"].get("unattended"),
            "driver": r["payload"].get("driver"),
            "probabilities": question_probabilities(r["payload"]),
            "reason": r["payload"].get("reason"),
        }
        for r in scored + unavailable
        if (r["payload"].get("banded_outcome") or r["payload"].get("would_be_outcome"))
        not in (None, r["payload"].get("static_outcome"))
    ]

    rebanded = {}
    for bounds in tries:
        key = f"{bounds.low_below}:{bounds.high_at_or_above}"
        rebanded[key] = {
            name: dict(Counter(bounds.band(p) for p in values))
            for name, values in sorted(per_question.items())
        }

    total = len(rows)
    return {
        "calls": total,
        "scored": len(scored),
        "unavailable": len(unavailable),
        "unavailable_rate": round(len(unavailable) / total, 4) if total else None,
        "unavailable_reasons": dict(reasons),
        "provider_blocked_rate": (
            round(reasons.get("provider_blocked", 0) / total, 4) if total else None
        ),
        "enforced_calls": sum(1 for r in rows if r["payload"].get("enforced")),
        "questions": {
            name: {
                "n": len(values),
                "quartiles": quartiles(values),
                "histogram_0.1": histogram(values),
            }
            for name, values in sorted(per_question.items())
        },
        "disagreements": disagreements,
        "rebanded": rebanded,
    }


async def _load(since: datetime | None) -> list[dict[str, Any]]:
    from sqlalchemy import bindparam, text

    from neos.database.connection import get_session_ctx

    query = """
        SELECT event_type, task_id, tool_call_id, payload, created_at
        FROM coding_events
        WHERE event_type IN :event_types
    """
    params: dict[str, Any] = {"event_types": list(EVENT_TYPES)}
    if since is not None:
        query += " AND created_at >= :since"
        params["since"] = since
    query += " ORDER BY seq"
    async with get_session_ctx() as session:
        result = await session.execute(
            text(query).bindparams(bindparam("event_types", expanding=True)), params
        )
        rows = []
        for event_type, task_id, tool_call_id, payload, _created in result.all():
            if isinstance(payload, str):
                payload = json.loads(payload)
            rows.append(
                {
                    "event_type": event_type,
                    "task_id": task_id,
                    "tool_call_id": tool_call_id,
                    "payload": payload or {},
                }
            )
        return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=datetime.fromisoformat, default=None)
    parser.add_argument("--try", dest="tries", action="append", type=Bounds.parse, default=[])
    args = parser.parse_args()
    rows = asyncio.run(_load(args.since))
    report = summarize(rows, args.tries)
    if not report["calls"]:
        # 빈 원장을 "불일치 0" 으로 읽지 않는다 -- L4 에서 한 번 그럴 뻔했다.
        print("🔴 섀도 이벤트가 0 건이다. 섀도가 켜져 있었는가(jev.tool_risk_shadow_enabled)?")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
