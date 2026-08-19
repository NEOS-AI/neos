"""표본 아티팩트와 이벤트 원장으로 진단자의 입력을 만든다.

이 모듈은 정답키를 로드하지 않는다. 스펙 §2 참조 -- 작성자가 정답을 안다는
사실이 프롬프트로 새는 경로를 구조로 막는다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

EventRow = tuple[str, int, str, str]

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "neos" / "workflow" / "deep_analysis" / "prompts" / "diagnose_bottleneck.md"
)
_MAX_CANDIDATES = 3

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


def score_sample(
    candidates,
    *,
    truth,
    contemporaneous,
    valid_event_ids,
) -> dict:
    kept, discarded = [], []
    for candidate in candidates:
        evidence = candidate.get("evidence") or []
        if evidence and all(e in valid_event_ids for e in evidence):
            kept.append(candidate["label"])
        else:
            discarded.append(candidate["label"])

    hits = [label for label in truth if label in kept]
    return {
        "recall": len(hits) / len(truth) if truth else 0.0,
        "hits": hits,
        "kept": kept,
        "discarded": discarded,
        "reproduced_contemporaneous": (
            not hits and any(label in kept for label in contemporaneous)
        ),
    }


def constant_best(key: dict, labels, k: int = 3) -> float:
    """정답을 읽지 않는 최선의 고정 예측이 받는 평균 recall.

    모든 k-라벨 조합을 훑는다. 표본 창이 한 병목을 해상도를 높여가며 쫓던
    구간이면 이 값이 높게 나오고, 그것이 관문의 기준이 되어야 한다.
    """
    best = 0.0
    for combo in combinations(sorted(labels), k):
        chosen = set(combo)
        total = 0.0
        for entry in key.values():
            truth = entry["truth"]
            total += len([t for t in truth if t in chosen]) / len(truth)
        best = max(best, total / len(key))
    return best


def render_prompt(summary: dict, labels: Sequence[str]) -> str:
    """진단 프롬프트를 렌더한다. 표본 요약과 닫힌 라벨 집합만 들어간다.

    이 함수는 정답키를 읽지 않는다 -- 인자로 받는 `summary`/`labels`가 전부다
    (스펙 §2, 모듈 docstring). 치환은 `str.replace`이며, 출력 형식 절의 JSON
    리터럴(`{"candidates": ...}`)은 소문자 식별자 자리표시자 패턴과 겹치지
    않으므로 이스케이프가 필요 없다.
    """
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    rendered = template.replace(
        "{labels}", "\n".join(f"- {label}" for label in labels)
    )
    return rendered.replace(
        "{summary}", json.dumps(summary, ensure_ascii=False, indent=2)
    )


async def diagnose(
    summary: dict, labels: Sequence[str], *, model: str, client=None
) -> dict:
    """표본 요약 하나로 병목 후보를 낸다. LLM 호출 1회.

    `retries=0`이다 -- 파싱될 때까지 다시 묻는 것은 점수를 부풀린다(스펙 §8).
    실패는 삼키지 않고 `failure`에 사유를 남긴다: `"unparseable"` (JSON이
    아니었다), `"truncated"` (상한에 잘렸고 확장 재시도도 잘렸다),
    `"off_label"` (닫힌 라벨 집합 밖의 라벨만 나왔다).

    `TruncatedResponseError`는 `JSONParseError`의 하위클래스다
    (`neos/workflow/deep_analysis/llm.py`) -- 그래서 반드시 그것을 먼저
    잡는다. 순서를 바꾸면 잘림도 조용히 "unparseable"로 잡힌다.
    """
    from neos.workflow.deep_analysis.llm import (
        JSONParseError,
        TruncatedResponseError,
        call_json,
    )

    prompt = render_prompt(summary, labels)
    try:
        data, response = await call_json(
            model,
            prompt,
            max_tokens=2000,
            temperature=0.0,
            client=client,
            retries=0,
            stage="diagnose",
        )
    except TruncatedResponseError:
        return {"candidates": [], "failure": "truncated"}
    except JSONParseError:
        return {"candidates": [], "failure": "unparseable"}

    allowed = set(labels)
    candidates: list[dict] = []
    off_label = False
    for raw in data.get("candidates", []) or []:
        label = raw.get("label")
        if label not in allowed:
            off_label = True
            continue
        candidates.append({
            "label": label,
            "evidence": list(raw.get("evidence") or []),
            "reason": str(raw.get("reason", "")),
        })

    truncated = candidates[:_MAX_CANDIDATES]
    failure = None
    if not truncated:
        failure = "off_label" if off_label else "unparseable"
    return {
        "candidates": truncated,
        "failure": failure,
        "output_tokens": getattr(response, "output_tokens", None),
    }
