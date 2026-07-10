"""Conflict resolution for the Deep Analysis Harness (M4, design §6.7).

Each node summary may report ``ConflictNote`` entries: two claims whose
evidence disagrees. ``resolve_conflicts`` compares the two claims' source
domain tiers (§6.7) and either adopts the higher-tier claim silently, or --
when the tiers are equal -- annotates the answer with a deterministic
"both-sides" clause so the contradiction isn't hidden from the reader.

See ``DECISIONS.md`` D16 for why the both-sides annotation is a deterministic
string insertion rather than the LLM re-summary the original design
describes.
"""

from __future__ import annotations

from urllib.parse import urlparse

from neos.config.settings import settings

from .models import NodeSummary


def _extract_host(url: str) -> str:
    text = url if "//" in url else f"//{url}"
    return (urlparse(text).hostname or "").lower()


def _domain_suffix_match(candidate: str, entry: str) -> bool:
    candidate = candidate.lower()
    entry = entry.lower()
    if not entry:
        return False
    if entry.startswith("."):
        return candidate.endswith(entry)
    return candidate == entry or candidate.endswith("." + entry)


def source_tier(url: str, source_tiers: dict) -> int:
    """Tier of a URL's source domain.

    Domain-suffix match against ``source_tiers["tier1"]`` (e.g.
    ``"arxiv.org"``, ``".gov"``, ``".edu"``, ``"github.com"``) -> tier 1;
    everything else defaults to tier 2. Entries may be a bare domain
    (matches the domain itself or any subdomain) or a dotted suffix like
    ``".gov"`` (matches any host ending in that suffix). The raw URL is
    also checked as a fallback in case host extraction fails.
    """
    tier1 = (source_tiers or {}).get("tier1") or []
    host = _extract_host(url)
    for entry in tier1:
        if _domain_suffix_match(host, entry) or _domain_suffix_match(url, entry):
            return 1
    return 2


async def _claim_urls(ledger, claim_id: str) -> list[str]:
    return await ledger.claim_source_urls(claim_id)


async def _claim_max_tier(ledger, source_tiers: dict, claim_id: str) -> int:
    urls = await _claim_urls(ledger, claim_id)
    if not urls:
        return 2
    return min(source_tier(url, source_tiers) for url in urls)


async def _claim_context(ledger, summary_question_id: str, claim_id: str) -> tuple[float, str]:
    """Return ``(value_est, question_id)`` for a claim.

    Production ``DAClaim`` rows don't carry ``value_est`` directly (it lives
    on the owning ``DAQuestion``), so we fall back to ``ledger.get_question``
    when the claim object doesn't expose it. Test doubles may hand back a
    bare claim-shaped stand-in with ``value_est`` set directly and no
    ``get_question`` at all -- both shapes are handled here.
    """
    claim = await ledger.get_claim(claim_id)
    if claim is None:
        return 0.0, summary_question_id

    question_id = getattr(claim, "question_id", None) or summary_question_id
    value_est = getattr(claim, "value_est", None)
    if value_est is None:
        get_question = getattr(ledger, "get_question", None)
        if get_question is not None:
            question = await get_question(question_id)
            value_est = getattr(question, "value_est", 0.0) if question else 0.0
        else:
            value_est = 0.0
    return float(value_est), question_id


async def resolve_conflicts(
    ledger,
    summary: NodeSummary,
    source_tiers: dict,
) -> tuple[NodeSummary, list[str]]:
    """Resolve each of ``summary.conflicts`` by source-domain tier (§6.7).

    - Equal tier -> deterministic both-sides annotation appended to
      ``summary.answer`` (AC-b), keeping both ``[C:claim_a]``/``[C:claim_b]``
      markers and the conflict's ``nature`` visible.
    - Tier difference -> the higher-tier claim is silently adopted (no
      both-sides clause); the lower-tier claim gets an optional footnote
      caveat appended to ``summary.caveats``.

    Returns the mutated summary and the deduplicated list of question ids
    whose conflicts involve a claim valued at/above
    ``conflict_value_threshold`` -- these need reinvestigation (acted on by
    the orchestrator, not here).
    """
    threshold = settings.config.deep_analysis.conflict_value_threshold
    reinvestigate_ids: list[str] = []
    seen_reinvestigate: set[str] = set()

    for conflict in summary.conflicts:
        tier_a = await _claim_max_tier(ledger, source_tiers, conflict.claim_a)
        tier_b = await _claim_max_tier(ledger, source_tiers, conflict.claim_b)

        if tier_a == tier_b:
            summary.answer += (
                f"\n\n(양론 병기) 상반된 근거: [C:{conflict.claim_a}] vs "
                f"[C:{conflict.claim_b}] — {conflict.nature}"
            )
        else:
            higher_id, lower_id = (
                (conflict.claim_a, conflict.claim_b)
                if tier_a < tier_b
                else (conflict.claim_b, conflict.claim_a)
            )
            caveat = (
                f"(하위 출처 각주) [C:{lower_id}]는 낮은 등급 출처이며 "
                f"[C:{higher_id}]를 채택 — {conflict.nature}"
            )
            if caveat not in summary.caveats:
                summary.caveats.append(caveat)

        for claim_id in (conflict.claim_a, conflict.claim_b):
            value_est, question_id = await _claim_context(
                ledger, summary.question_id, claim_id
            )
            if value_est >= threshold and question_id not in seen_reinvestigate:
                seen_reinvestigate.add(question_id)
                reinvestigate_ids.append(question_id)

    return summary, reinvestigate_ids
