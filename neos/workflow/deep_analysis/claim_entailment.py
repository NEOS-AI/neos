"""Atomic application of untrusted claim-entailment results."""

from __future__ import annotations

from typing import Any

from .models import EntailmentOutcome, ProposedClaim

_ACTIONS = {"keep", "narrow", "discard"}


def apply_entailment_results(
    claims: list[ProposedClaim],
    payload: Any,
) -> EntailmentOutcome | None:
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
        action = item.get("action")
        if (
            type(index) is not int
            or index < 0
            or index >= len(claims)
            or index in by_index
            or not isinstance(action, str)
            or action not in _ACTIONS
        ):
            return None

        allowed_fields = {"index", "action"}
        if action == "narrow":
            allowed_fields.add("new_text")
        if set(item) != allowed_fields:
            return None

        new_text = item.get("new_text")
        if action == "narrow" and (
            not isinstance(new_text, str) or not new_text.strip()
        ):
            return None
        by_index[index] = (
            action,
            new_text.strip() if action == "narrow" else None,
        )

    if set(by_index) != set(range(len(claims))):
        return None

    refined: list[ProposedClaim] = []
    discarded: list[ProposedClaim] = []
    for index, claim in enumerate(claims):
        action, new_text = by_index[index]
        if action == "discard":
            discarded.append(claim)
            continue
        if action == "keep":
            refined.append(claim)
            continue
        refined.append(
            ProposedClaim(
                text=new_text or "",
                confidence=claim.confidence,
                evidence=claim.evidence,
            )
        )
    return EntailmentOutcome(refined=refined, discarded=discarded)
