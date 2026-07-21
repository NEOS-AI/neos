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
  waitingApproval,
}: {
  phases: CodingPhaseView[];
  selectedId: string | null;
  onSelect: (phaseId: string) => void;
  waitingApproval?: boolean;
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
    <div>
      {waitingApproval ? (
        <div className="mb-2 border border-amber-400/30 bg-amber-400/5 px-4 py-2 font-mono text-[10px] text-amber-300 uppercase tracking-[0.16em]">
          Paused at approval checkpoint
        </div>
      ) : null}
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
    </div>
  );
}
