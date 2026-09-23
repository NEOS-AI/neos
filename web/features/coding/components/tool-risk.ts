import type { CodingToolRiskView } from "@/features/coding/types/projection";

// The fixed part of a verdict's badge: what Jev measured. Always shown, so a
// verdict is never invisible even where `describeToolRisk` says nothing.
export function toolRiskBadge(risk: CodingToolRiskView): string {
  if (risk.kind === "unavailable") return "jev unavailable";
  return `jev ${risk.probability.toFixed(2)} · ${risk.band}`;
}

// Whether the verdict was acted on. Shadow (L2) records; the gate (L3) blocks.
export function toolRiskMode(risk: CodingToolRiskView): "shadow" | "enforced" {
  return risk.enforced ? "enforced" : "shadow";
}

// The one sentence under the badge: what this verdict *means* for this call.
//
// This is where the reviewer of L3 reads the shadow period, call by call
// (roadmap §12.5 L3: "L2 불일치 건별 리뷰"), and where an unattended DENY
// reaches the user (§12.4 ⚠️, S6). Return null to show the badge alone.
export function describeToolRisk(risk: CodingToolRiskView): string | null {
  if (risk.kind === "unavailable") {
    // Never silent (S12): falling back to R₀ is itself something to report.
    const why = risk.reason ? ` (${risk.reason})` : "";
    const stood = risk.static_outcome
      ? `the static policy's ${risk.static_outcome} stood`
      : "the static policy stood";
    return `Jev did not answer${why}; ${stood}.`;
  }

  const from = risk.static_outcome;
  // What Jev alone did, before the unattended fold. Events written before the
  // gate recorded it carry only the folded value.
  const jev = risk.banded_outcome ?? risk.would_be_outcome;
  const to = risk.would_be_outcome;
  // Jev narrowed nothing. A fold may still have denied the call, but it would
  // have done so without Jev -- crediting Jev with it overstates the gate.
  if (from === null || jev === null || to === null || from === jev) {
    return null;
  }
  const folded = to !== jev;

  if (!risk.enforced) {
    const would = folded
      ? `${outcomeWord(jev)} and, with no one to approve, been denied`
      : jev === "deny"
        ? "been denied"
        : outcomeWord(jev);
    return `Shadow: with the gate on, this call would have ${would} (static policy ${outcomeWord(from)} it).`;
  }

  const fold = folded ? `; unattended, so ${jev} → ${to}` : "";
  // A denial is the loud failure (§12.4 ⚠️): show the evidence, not just the verdict.
  const evidence = to === "deny" ? `: ${denialEvidence(risk)}` : "";
  return `Gate narrowed ${from} → ${jev}${fold}${evidence}.`;
}

const OUTCOME_WORDS: Record<string, string> = {
  allow: "allowed",
  require_approval: "required approval",
  deny: "denied",
};

// Unknown codes pass through raw: a new outcome should read oddly, not crash the row.
function outcomeWord(outcome: string): string {
  return OUTCOME_WORDS[outcome] ?? outcome;
}

// The threshold the probability crossed. A mid-band deny is the unattended
// fold (D-L1), so the boundary it crossed is `low_below`, not the high one.
function denialEvidence(
  risk: Extract<CodingToolRiskView, { kind: "scored" }>
): string {
  const p = `p=${risk.probability.toFixed(2)}`;
  const threshold =
    risk.band === "high"
      ? risk.high_at_or_above
      : risk.band === "mid"
        ? risk.low_below
        : null;
  return threshold === null ? p : `${p} ≥ ${threshold.toFixed(2)}`;
}
