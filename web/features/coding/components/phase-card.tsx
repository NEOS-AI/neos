"use client";

import { Check, ChevronRight, CircleDashed, RotateCcw } from "lucide-react";
import type { CodingPhaseView } from "@/features/coding/types/projection";

const statusTone: Record<string, string> = {
  active: "border-amber-400/50 bg-amber-400/[0.06]",
  completed: "border-border/70 bg-card/30",
  failed: "border-red-400/40 bg-red-400/[0.05]",
  blocked: "border-orange-400/40 bg-orange-400/[0.05]",
};

export function PhaseCard({
  phase,
  label,
  index,
  selected,
  onSelect,
}: {
  phase: CodingPhaseView;
  label: string;
  index: number;
  selected: boolean;
  onSelect: (phaseId: string) => void;
}) {
  const completed = phase.status === "completed";
  const active = phase.status === "active";
  return (
    <button
      aria-current={active ? "step" : undefined}
      className={`group relative grid w-full grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-3 border px-3 py-3 text-left transition-colors hover:border-amber-400/35 ${
        statusTone[phase.status] ?? statusTone.completed
      } ${selected ? "ring-1 ring-amber-400/50" : ""}`}
      onClick={() => onSelect(phase.phase_id)}
      type="button"
    >
      <span
        className={`grid size-8 place-items-center border font-mono text-[11px] ${
          active
            ? "border-amber-400 bg-amber-400 text-black"
            : "border-border text-muted-foreground"
        }`}
      >
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="font-medium text-sm">{label}</span>
          {phase.attempt > 1 ? (
            <RotateCcw className="size-3 text-amber-400" />
          ) : null}
        </span>
        <span className="mt-1 block font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]">
          {phase.status}
        </span>
      </span>
      <span className="flex items-center gap-2">
        {completed ? (
          <Check className="size-4 text-emerald-400" />
        ) : (
          <CircleDashed
            className={`size-4 ${active ? "animate-spin text-amber-400" : "text-muted-foreground"}`}
          />
        )}
        <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </span>
    </button>
  );
}
