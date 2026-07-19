"use client";

import { Radio, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { CodingDetailPanel } from "@/features/coding/components/coding-detail-panel";
import { CodingSteerComposer } from "@/features/coding/components/coding-steer-composer";
import { PhaseTimeline } from "@/features/coding/components/phase-timeline";
import { useCodingStream } from "@/features/coding/stream/use-coding-stream";

const connectionMessages = {
  unauthorized: "Authorization expired. Reopen this task.",
  not_found: "This coding task is no longer accessible.",
  protocol_error: "The coding stream could not be restored.",
} as const;

export function CodingTaskWorkspace({ taskId }: { taskId: string }) {
  const { projection, connection } = useCodingStream(taskId);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);
  useEffect(() => {
    const active = projection.phases.find((phase) => phase.status === "active");
    if (active) {
      setSelectedPhase(active.phase_id);
    }
  }, [projection.phases]);
  const connectionMessage =
    connection in connectionMessages
      ? connectionMessages[connection as keyof typeof connectionMessages]
      : null;

  return (
    <main className="flex min-h-dvh flex-1 flex-col bg-background">
      <header className="flex h-14 items-center justify-between border-border/70 border-b px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <TerminalSquare className="size-4 shrink-0 text-amber-400" />
          <span className="truncate font-mono text-sm">{taskId}</span>
          {projection.activeRun ? (
            <span className="hidden border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground md:inline">
              RUN {projection.activeRun.attempt}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]">
          <Radio
            className={
              connection === "live"
                ? "size-3 text-emerald-400"
                : "size-3 text-amber-400"
            }
          />
          {projection.connectionBasis === "live"
            ? "Live"
            : "Checkpoint restored"}
        </div>
      </header>

      <div className="grid flex-1 lg:grid-cols-[minmax(0,1.65fr)_minmax(19rem,0.85fr)]">
        <section className="border-border/70 p-4 lg:border-r lg:p-6">
          <div className="mx-auto max-w-3xl">
            <div className="mb-5 flex items-end justify-between border-border/60 border-b pb-3">
              <div>
                <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.22em]">
                  Execution ledger
                </p>
                <h1 className="mt-2 font-medium text-xl">Coding phases</h1>
              </div>
              <span className="font-mono text-[10px] text-muted-foreground">
                SEQ {projection.appliedSeq}
              </span>
            </div>
            <PhaseTimeline
              onSelect={setSelectedPhase}
              phases={projection.phases}
              selectedId={selectedPhase}
            />
            <div className="mt-5">
              <CodingSteerComposer
                disabled={
                  connection === "unauthorized" || connection === "not_found"
                }
                taskId={taskId}
              />
            </div>
            {connectionMessage ? (
              <p className="mt-3 border-red-400/30 border-l-2 bg-red-400/5 px-3 py-2 text-destructive text-xs">
                {connectionMessage}
              </p>
            ) : null}
          </div>
        </section>
        <aside className="border-border/70 border-t bg-card/20 p-5 lg:border-t-0 lg:p-6">
          <div className="sticky top-6">
            <CodingDetailPanel
              phaseId={selectedPhase}
              projection={projection}
            />
          </div>
        </aside>
      </div>
    </main>
  );
}
