"""Pure metrics for the entailment discard-recall measurement.

No database, no network, no LLM. The caller supplies decoded event payloads
and grading outcomes; this module only reconstructs claims and does
arithmetic.
"""

from __future__ import annotations

import math
from typing import Any

from .models import ProposedClaim, ProposedEvidence

_EVIDENCE_FIELDS = ("source_url", "excerpt", "raw_ref")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def claim_from_event(payload: Any) -> ProposedClaim | None:
    """Rebuild a claim from a ``claim_discarded`` payload, or None if malformed."""
    if not isinstance(payload, dict):
        return None

    text = payload.get("text")
    confidence = payload.get("confidence")
    raw_evidence = payload.get("evidence")
    if not isinstance(text, str) or not text.strip():
        return None
    if not _is_number(confidence):
        return None
    if not isinstance(raw_evidence, list):
        return None

    evidence: list[ProposedEvidence] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            return None
        if any(not isinstance(item.get(f), str) for f in _EVIDENCE_FIELDS):
            return None
        evidence.append(
            ProposedEvidence(
                source_url=item["source_url"],
                excerpt=item["excerpt"],
                raw_ref=item["raw_ref"],
            )
        )

    return ProposedClaim(
        text=text,
        confidence=float(confidence),
        evidence=evidence,
    )


def value_est_from_event(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    value_est = payload.get("value_est")
    return float(value_est) if _is_number(value_est) else None


def wilson_interval(
    successes: int,
    total: int,
    z: float,
) -> tuple[float, float]:
    """Wilson score interval, clamped to [0, 1]. Empty denominator -> (0, 0)."""
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def false_discard_rate(verified: int, total: int) -> float:
    """Share of discarded claims the graders would have verified."""
    return verified / total if total else 0.0


def stopping_verdict(
    low: float,
    high: float,
    *,
    safe_upper: float,
    over_discard_lower: float,
) -> str:
    """Apply the pre-registered stopping rule to a Wilson interval.

    Fixed before data collection. Do not tune after seeing a result.
    """
    if high < safe_upper:
        return "safe"
    if low > over_discard_lower:
        return "over_discarding"
    return "inconclusive"


async def score_discards(
    events: list[Any],
    *,
    grade_fn,
    wilson_z: float,
    safe_upper: float,
    over_discard_lower: float,
) -> dict[str, Any]:
    """Grade every discarded claim and summarise the recall loss.

    ``grade_fn(claim, value_est)`` must return True when the graders would
    have verified the claim. Every claim is graded — the agentic sampling
    gate is deliberately bypassed so the denominator stays exact.
    """
    verified = 0
    total = 0
    malformed = 0
    for payload in events:
        claim = claim_from_event(payload)
        value_est = value_est_from_event(payload)
        if claim is None or value_est is None:
            malformed += 1
            continue
        total += 1
        if await grade_fn(claim, value_est):
            verified += 1

    low, high = wilson_interval(verified, total, wilson_z)
    # A zero-total interval degenerates to (0.0, 0.0), which would read as
    # "safe" under the pre-registered rule despite there being no data to
    # support that conclusion. Treat the no-data case as inconclusive
    # explicitly rather than let the degenerate interval imply safety.
    verdict = (
        "inconclusive"
        if total == 0
        else stopping_verdict(
            low,
            high,
            safe_upper=safe_upper,
            over_discard_lower=over_discard_lower,
        )
    )
    return {
        "total_discarded": total,
        "verified": verified,
        "malformed": malformed,
        "false_discard_rate": false_discard_rate(verified, total),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": verdict,
    }
