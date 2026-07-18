"use client";

import { Radio, TerminalSquare } from "lucide-react";
import { useCodingStream } from "@/features/coding/stream/use-coding-stream";

const connectionMessages = {
  unauthorized: "Your coding session authorization expired. Reopen this task.",
  not_found: "This coding task no longer exists or is not accessible.",
  protocol_error: "The coding stream protocol could not be negotiated.",
} as const;

export function CodingTaskWorkspace({ taskId }: { taskId: string }) {
  const { state, connection } = useCodingStream(taskId);
  const text = Object.values(state.partsById).join("");
  const connectionMessage =
    connection in connectionMessages
      ? connectionMessages[connection as keyof typeof connectionMessages]
      : null;

  return (
    <main className="flex min-h-dvh flex-1 flex-col bg-background">
      <header className="flex h-14 items-center justify-between border-border/70 border-b px-5">
        <div className="flex items-center gap-3">
          <TerminalSquare className="size-4 text-amber-400" />
          <span className="font-mono text-sm">{taskId}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-wider">
          <Radio
            className={
              connection === "live"
                ? "size-3 text-emerald-400"
                : "size-3 text-amber-400"
            }
          />
          {connection}
        </div>
      </header>
      <section className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,0.8fr)]">
        <div className="border-border/70 border-r p-6">
          <p className="mb-5 text-muted-foreground text-xs uppercase tracking-[0.2em]">
            Agent stream · seq {state.appliedSeq}
          </p>
          <div className="whitespace-pre-wrap text-sm leading-7">
            {text || "Waiting for the coding agent…"}
          </div>
          {state.gap ? (
            <p className="mt-4 text-amber-400 text-xs">
              Recovering events {state.gap.expected}–{state.gap.received - 1}
            </p>
          ) : null}
          {connectionMessage ? (
            <p className="mt-4 text-destructive text-xs">{connectionMessage}</p>
          ) : null}
        </div>
        <aside className="bg-card/25 p-6">
          <p className="text-muted-foreground text-xs uppercase tracking-[0.2em]">
            Workspace
          </p>
          <p className="mt-4 text-muted-foreground text-sm">
            Files, diff, and terminal become available when the sandbox is
            provisioned.
          </p>
        </aside>
      </section>
    </main>
  );
}
