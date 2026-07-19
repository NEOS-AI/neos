"use client";

import { PhaseCard } from "@/features/coding/components/phase-card";
import type { CodingPhaseView } from "@/features/coding/types/projection";

const PHASE_LABELS: Record<string, string> = {
  understand: "Understand",
  plan: "Plan",
  implement: "Implement",
  verify: "Verify",
  review: "Review",
};

export function PhaseTimeline({
  phases,
  selectedId,
  onSelect,
}: {
  phases: CodingPhaseView[];
  selectedId: string | null;
  onSelect: (phaseId: string) => void;
}) {
  if (phases.length === 0) {
    return (
      <div className="border border-border/80 border-dashed px-5 py-12 text-center">
        <p className="font-mono text-muted-foreground text-xs uppercase tracking-[0.18em]">
          Preparing Understand phase
        </p>
      </div>
    );
  }
  return (
    <ol aria-label="Coding task phases" className="relative space-y-2">
      <span
        aria-hidden="true"
        className="absolute top-8 bottom-8 left-7 w-px bg-gradient-to-b from-amber-400/60 via-border to-transparent"
      />
      {phases.map((phase, index) => (
        <li className="relative" key={phase.phase_id}>
          <PhaseCard
            index={index}
            label={`${PHASE_LABELS[phase.kind] ?? phase.kind}${
              phase.attempt > 1 ? ` #${phase.attempt}` : ""
            }`}
            onSelect={onSelect}
            phase={phase}
            selected={selectedId === phase.phase_id}
          />
        </li>
      ))}
    </ol>
  );
}
