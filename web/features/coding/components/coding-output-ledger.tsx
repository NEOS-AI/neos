import type { CodingTextPartView } from "@/features/coding/types/projection";

const statusLabel = {
  streaming: "Writing",
  completed: "Completed",
  interrupted: "Interrupted",
} as const;

export function CodingOutputLedger({ parts }: { parts: CodingTextPartView[] }) {
  const visible = parts.filter((part) => part.content.length > 0);
  if (visible.length === 0) return null;

  return (
    <section aria-label="Model output" className="mb-5 space-y-2">
      {visible.map((part) => (
        <article className="border border-border/60 bg-card/25" key={part.part_id}>
          <div className="flex items-center justify-between border-border/50 border-b px-3 py-2">
            <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-[0.16em]">
              Model output
            </span>
            <span className="font-mono text-[10px] text-amber-300">
              {statusLabel[part.status]}
            </span>
          </div>
          <pre
            aria-live={part.status === "streaming" ? "polite" : undefined}
            className="whitespace-pre-wrap break-words p-3 font-sans text-sm leading-6"
          >
            {part.content}
          </pre>
        </article>
      ))}
    </section>
  );
}
