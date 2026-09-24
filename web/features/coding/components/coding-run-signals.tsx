import { Bot, OctagonX } from "lucide-react";
import type {
  CodingChildView,
  CodingProjectionState,
} from "@/features/coding/types/projection";

const LIVE_CHILD_STATUSES = new Set(["pending", "running"]);

// What the run is doing between the lines of the output ledger: the model's
// running note (K4a), a refusal that ended the run (K6), and the children it
// spawned (K3). All three used to reach the projection -- or not even that --
// and never the screen.
export function CodingRunSignals({
  projection,
}: {
  projection: CodingProjectionState;
}) {
  const children = Object.values(projection.childrenById);
  const { refusal, thinkingStatus } = projection;
  if (!refusal && !thinkingStatus && children.length === 0) return null;
  return (
    <div className="mb-5 space-y-2">
      {refusal ? (
        <p
          className="flex items-start gap-2 border-rose-400/40 border-l-2 bg-rose-400/5 px-3 py-2 text-rose-200 text-xs"
          data-testid="coding-refusal"
          role="status"
        >
          <OctagonX className="mt-0.5 size-3.5 shrink-0" />
          <span>
            The model declined this turn
            {refusal.stop_category ? ` (${refusal.stop_category})` : ""}. The
            run stopped and will not retry on its own.
          </span>
        </p>
      ) : null}
      {thinkingStatus ? (
        <p
          aria-live="polite"
          className="truncate font-mono text-[11px] text-muted-foreground italic"
          data-testid="coding-thinking-status"
        >
          {thinkingStatus}
        </p>
      ) : null}
      {children.length > 0 ? (
        <section aria-label="Subagents" className="space-y-1">
          <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.22em]">
            Subagents
          </p>
          <ul className="space-y-1">
            {children.map((child) => (
              <ChildRow child={child} key={child.run_id} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function ChildRow({ child }: { child: CodingChildView }) {
  const live = child.status != null && LIVE_CHILD_STATUSES.has(child.status);
  const counts = [
    child.turn_count != null ? `${child.turn_count} turns` : null,
    child.tool_count != null ? `${child.tool_count} tools` : null,
  ].filter(Boolean);
  return (
    <li
      className="flex items-center justify-between gap-3 border border-border/70 px-3 py-2"
      data-testid="coding-subagent"
    >
      <span className="flex min-w-0 items-center gap-2 font-mono text-xs">
        <Bot
          className={
            live
              ? "size-3 shrink-0 text-emerald-400"
              : "size-3 shrink-0 text-muted-foreground"
          }
        />
        <span className="truncate">
          {child.spec ?? "subagent"} · {child.run_id}
        </span>
      </span>
      <span className="shrink-0 font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]">
        {[child.status ?? "unknown", child.end_reason, ...counts]
          .filter(Boolean)
          .join(" · ")}
      </span>
    </li>
  );
}
