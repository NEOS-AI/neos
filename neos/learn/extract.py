"""Deterministic lesson extractors. No LLM, no executable code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from neos.learn.lessons import Lesson, new_lesson
from neos.learn.policy import clip_knowledge, namespace, should_capture_coding_signal

_FAILURE_MARKERS = (
    "tool_outcome_unknown",
    "tool.denied",
    "precondition_read_required",
    "FAILED",
    "AssertionError",
    "error_code",
)


def extract_coding_lesson(
    *,
    owner_id: str,
    task_id: str,
    outcome: str,
    events: Sequence[Mapping[str, object]],
) -> Lesson | None:
    if outcome not in {"failed", "error"} and not _events_look_failed(events):
        return None
    codes = []
    for event in events:
        code = event.get("error_code") or event.get("reason_code")
        if code:
            codes.append(str(code))
        kind = str(event.get("type") or event.get("event_type") or "")
        if kind:
            codes.append(kind)
    unique = list(dict.fromkeys(codes))[:8]
    detail = ", ".join(unique) if unique else outcome
    if not should_capture_coding_signal(outcome, detail, *unique):
        return None
    body = clip_knowledge(
        f"Coding run {task_id} ended {outcome}. Signals: {detail}."
    )
    return new_lesson(
        namespace=namespace(owner_id),
        title=f"coding-run-{task_id}",
        body=body,
        kind="coding",
    )


def extract_research_procedure(
    *,
    owner_id: str,
    pipeline: str,
    steps: Sequence[str],
) -> Lesson:
    description = clip_knowledge(f"{pipeline}: " + "; ".join(steps))
    if len(description) > 60:
        description = description[:60]
    body = clip_knowledge(
        "## Procedure\n" + "\n".join(f"- {step}" for step in steps)
    )
    return new_lesson(
        namespace=namespace(owner_id),
        title=pipeline,
        body=f"{description}\n\n{body}",
        kind="procedure",
    )


def _events_look_failed(events: Sequence[Mapping[str, object]]) -> bool:
    blob = " ".join(str(item) for item in events)
    return any(marker in blob for marker in _FAILURE_MARKERS)
