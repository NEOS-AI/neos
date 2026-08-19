"""표본 아티팩트와 이벤트 원장으로 진단자의 입력을 만든다.

이 모듈은 정답키를 로드하지 않는다. 스펙 §2 참조 -- 작성자가 정답을 안다는
사실이 프롬프트로 새는 경로를 구조로 막는다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence

EventRow = tuple[str, int, str, str]

_FOOTNOTE = re.compile(r"\[\d+\]")
_RAW_MARKER = re.compile(r"\[C:[0-9a-f]+\]")

_STOP_KINDS = (
    "token_budget_exhausted",
    "investigation_stopped_at_floor",
    "investigation_stopped_at_input_bound",
)


def build_summary(
    rows: Sequence[EventRow],
    *,
    report_markdown: str,
    config_fingerprint: dict,
) -> dict:
    events: dict[str, int] = defaultdict(int)
    by_stage: dict[str, dict[str, int]] = defaultdict(
        lambda: {"reserved": 0, "settled": 0, "calls": 0}
    )
    stage_of: dict[str, str] = {}
    clamp = {
        "exhausted": 0,
        "dropped_primary": 0,
        "primary_chars_after": 0,
        "anchor_chars_before": 0,
        "anchor_chars_after": 0,
        "distinct_claims_after": 0,
    }
    gate: dict[str, dict[str, int]] = {"codes": defaultdict(int),
                                       "judge_states": defaultdict(int)}
    uncited: list[float] = []
    passes = {"zero_token": 0, "productive": 0, "verified_total": 0}
    questions: dict[str, int] = defaultdict(int)
    evidence = {"candidates": 0, "tier1_selected": 0}
    stop_reasons: dict[str, int] = defaultdict(int)

    for _run_id, _seq, kind, payload_json in rows:
        events[kind] += 1
        payload = json.loads(payload_json)
        if kind in _STOP_KINDS:
            stop_reasons[kind] += 1
        elif kind == "token_budget_reserved":
            stage = payload.get("stage", "?")
            stage_of[payload["reservation_id"]] = stage
            by_stage[stage]["reserved"] += payload.get("reserved_tokens", 0)
            by_stage[stage]["calls"] += 1
        elif kind == "token_budget_settled":
            stage = stage_of.get(payload.get("reservation_id"), "?")
            by_stage[stage]["settled"] += payload.get("actual_tokens", 0)
        elif kind == "finalization_prompt_clamped":
            clamp["exhausted"] += int(bool(payload.get("exhausted")))
            for field in ("dropped_primary", "primary_chars_after",
                          "anchor_chars_before", "anchor_chars_after",
                          "distinct_claims_after"):
                clamp[field] += int(payload.get(field, 0) or 0)
        elif kind == "report_graded":
            gate["codes"][str(payload.get("code", "OK"))] += 1
            gate["judge_states"][str(payload.get("judge", "absent"))] += 1
            if payload.get("uncited_ratio") is not None:
                uncited.append(float(payload["uncited_ratio"]))
        elif kind == "pass_completed":
            if payload.get("tokens", 0) > 0:
                passes["productive"] += 1
            else:
                passes["zero_token"] += 1
            passes["verified_total"] += int(payload.get("verified", 0) or 0)
            evidence["candidates"] += int(payload.get("candidates", 0) or 0)
            evidence["tier1_selected"] += int(payload.get("tier1", 0) or 0)
        elif kind in ("question_opened", "resolved", "abandoned", "dead_end"):
            questions[kind] += 1

    total_pass = passes["productive"] + passes["zero_token"]
    return {
        "events": dict(events),
        "budget": {"by_stage": {k: dict(v) for k, v in by_stage.items()}},
        "clamp": clamp,
        "gate": {
            "codes": dict(gate["codes"]),
            "judge_states": dict(gate["judge_states"]),
            "uncited_ratio": {
                "n": len(uncited),
                "median": sorted(uncited)[len(uncited) // 2] if uncited else None,
            },
        },
        "stop_reasons": dict(stop_reasons),
        "passes": {
            **passes,
            "claims_per_pass": (
                passes["verified_total"] / passes["productive"]
                if passes["productive"] else 0.0
            ),
            "total": total_pass,
        },
        "questions": dict(questions),
        "evidence": {
            **evidence,
            "tier1_ratio": (
                evidence["tier1_selected"] / evidence["candidates"]
                if evidence["candidates"] else 0.0
            ),
        },
        "delivered": {
            "chars": len(report_markdown),
            "footnotes": len(set(int(m[1:-1]) for m in _FOOTNOTE.findall(report_markdown))) if _FOOTNOTE.findall(report_markdown) else 0,
            "raw_markers": len(_RAW_MARKER.findall(report_markdown)),
            "sources_section": "## 출처" in report_markdown,
        },
        "config": dict(config_fingerprint),
    }
