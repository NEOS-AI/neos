import type { WorkspaceDiff } from "@/features/coding/workspace/types";

export function CodingDiffViewer({ diff }: { diff: WorkspaceDiff | null }) {
  if (!diff) {
    return (
      <p className="p-4 text-muted-foreground text-xs">Loading changes…</p>
    );
  }
  return (
    <div className="h-full overflow-auto bg-black/15">
      <pre className="min-w-max p-4 font-mono text-[11px] text-foreground leading-5">
        {diff.content || "No uncommitted changes."}
      </pre>
      {diff.truncated ? (
        <p className="sticky bottom-0 border-amber-400/30 border-t bg-background/95 px-4 py-2 text-amber-300 text-xs">
          Diff truncated to the workspace safety limit.
        </p>
      ) : null}
    </div>
  );
}
