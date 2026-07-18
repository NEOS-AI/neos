"use client";

import { ArrowUpRight, GitBranch, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  createCodingTask,
  type CodingTask,
} from "@/features/coding/api/coding-api";


export function CodingShell() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [task, setTask] = useState<CodingTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = prompt.trim();
    if (!value || isSubmitting) {
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      const created = await createCodingTask(value);
      setTask(created);
      router.push(`/code/tasks/${created.task_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start task");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="relative flex min-h-dvh flex-1 items-center justify-center overflow-hidden bg-background px-5 py-12">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-400/70 to-transparent" />
      <section className="w-full max-w-3xl">
        <div className="mb-10 flex items-end justify-between gap-6 border-border/60 border-b pb-5">
          <div>
            <p className="mb-3 font-mono text-amber-400 text-xs uppercase tracking-[0.24em]">
              Isolated workspace
            </p>
            <h1 className="font-semibold text-3xl tracking-tight md:text-4xl">
              Give NEOS a code task.
            </h1>
          </div>
          <GitBranch className="hidden size-7 text-muted-foreground md:block" />
        </div>

        <form className="rounded-2xl border border-border/70 bg-card/55 p-2 shadow-2xl shadow-black/10 backdrop-blur-sm" onSubmit={onSubmit}>
          <label className="sr-only" htmlFor="coding-prompt">
            What should NEOS change?
          </label>
          <Textarea
            autoFocus
            className="min-h-40 resize-none border-0 bg-transparent px-4 py-4 text-base shadow-none focus-visible:ring-0"
            id="coding-prompt"
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="What should NEOS change? Include the behavior you expect and how to verify it."
            value={prompt}
          />
          <div className="flex items-center justify-between border-border/60 border-t px-3 py-2">
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <ShieldCheck className="size-3.5 text-amber-400" />
              Runs in an isolated workspace
            </div>
            <Button disabled={!prompt.trim() || isSubmitting} size="sm" type="submit">
              {isSubmitting ? "Starting…" : "Start task"}
              <ArrowUpRight className="ml-1 size-3.5" />
            </Button>
          </div>
        </form>

        {task ? (
          <div className="mt-4 flex items-center justify-between border-amber-400/30 border-l-2 bg-amber-400/5 px-4 py-3 text-sm">
            <span className="font-mono text-muted-foreground">{task.task_id}</span>
            <span className="uppercase tracking-wider">{task.status}</span>
          </div>
        ) : null}
        {error ? <p className="mt-3 text-destructive text-sm">{error}</p> : null}

        <div className="mt-5 grid gap-2 text-muted-foreground text-xs sm:grid-cols-3">
          <p>01 · Inspect the repository</p>
          <p>02 · Make bounded changes</p>
          <p>03 · Verify before handoff</p>
        </div>
      </section>
    </main>
  );
}
