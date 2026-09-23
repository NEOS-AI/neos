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
  // TODO(human)
  return null;
}
