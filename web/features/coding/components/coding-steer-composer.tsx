"use client";

import { CornerDownRight, Octagon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { steerCodingTask } from "@/features/coding/api/coding-api";

export function CodingSteerComposer({
  taskId,
  disabled,
}: {
  taskId: string;
  disabled: boolean;
}) {
  const [instruction, setInstruction] = useState("");
  const [pending, setPending] = useState<"safe_point" | "interrupt_now" | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  async function submit(mode: "safe_point" | "interrupt_now") {
    const value = instruction.trim();
    if (!value || pending) {
      return;
    }
    setPending(mode);
    setError(null);
    try {
      await steerCodingTask(taskId, value, mode);
      setInstruction("");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not steer this run"
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <form
      className="border border-border/80 bg-card/45 p-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit("safe_point").catch((cause) => {
          setError(
            cause instanceof Error ? cause.message : "Could not steer this run"
          );
        });
      }}
    >
      <Textarea
        aria-label="Steer coding agent"
        className="min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        disabled={disabled}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder="Change direction, add a constraint, or ask for another check…"
        value={instruction}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-border/60 border-t px-2 pt-2">
        <p className="text-[10px] text-muted-foreground uppercase tracking-[0.15em]">
          Steer the active run
        </p>
        <div className="flex gap-2">
          <Button
            disabled={disabled || !instruction.trim() || Boolean(pending)}
            size="sm"
          >
            <CornerDownRight className="mr-1 size-3.5" />
            After current step
          </Button>
          <Button
            disabled={disabled || !instruction.trim() || Boolean(pending)}
            onClick={() =>
              submit("interrupt_now").catch((cause) => {
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not steer this run"
                );
              })
            }
            size="sm"
            type="button"
            variant="destructive"
          >
            <Octagon className="mr-1 size-3.5" />
            Interrupt now
          </Button>
        </div>
      </div>
      {error ? (
        <p className="px-2 pt-2 text-destructive text-xs">{error}</p>
      ) : null}
    </form>
  );
}
