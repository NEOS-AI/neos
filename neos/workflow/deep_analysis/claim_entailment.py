"""Atomic application of untrusted claim-entailment results."""

from __future__ import annotations

from typing import Any

from .models import ProposedClaim

_ACTIONS = {"keep", "narrow", "discard"}


def apply_entailment_results(
    claims: list[ProposedClaim],
    payload: Any,
) -> list[ProposedClaim] | None:
    if not isinstance(payload, dict):
        return None

    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(claims):
        return None

    by_index: dict[int, tuple[str, str | None]] = {}
    for item in results:
        if not isinstance(item, dict):
            return None
        index = item.get("index")
        verdict = item.get("verdict")
        if (
            type(index) is not int
            or index < 0
            or index >= len(claims)
            or index in by_index
            or not isinstance(verdict, str)
            or verdict not in _ACTIONS
        ):
            return None

        allowed_fields = {"index", "verdict"}
        if verdict == "narrow":
            allowed_fields.add("narrowed_claim")
        if set(item) != allowed_fields:
            return None

        narrowed_claim = item.get("narrowed_claim")
        if verdict == "narrow" and (
            not isinstance(narrowed_claim, str) or not narrowed_claim.strip()
        ):
            return None
        by_index[index] = (
            verdict,
            narrowed_claim.strip() if verdict == "narrow" else None,
        )

    if set(by_index) != set(range(len(claims))):
        return None

    refined: list[ProposedClaim] = []
    for index, claim in enumerate(claims):
        verdict, narrowed_claim = by_index[index]
        if verdict == "discard":
            continue
        if verdict == "keep":
            refined.append(claim)
            continue
        refined.append(
            ProposedClaim(
                text=narrowed_claim or "",
                confidence=claim.confidence,
                evidence=claim.evidence,
            )
        )
    return refined
