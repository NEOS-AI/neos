import { FileCode2, GitCommitHorizontal, Wrench } from "lucide-react";
import type { CodingProjectionState } from "@/features/coding/types/projection";

export function CodingDetailPanel({
  phaseId,
  projection,
}: {
  phaseId: string | null;
  projection: CodingProjectionState;
}) {
  const phase = projection.phases.find((item) => item.phase_id === phaseId);
  if (phase) {
    const tools = Object.values(projection.toolsById).filter(
      (tool) => tool.run_id === phase.run_id
    );
    return (
      <div>
        <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.2em]">
          Phase detail
        </p>
        <h2 className="mt-3 font-medium text-xl capitalize">{phase.kind}</h2>
        <div className="mt-5 grid grid-cols-2 gap-px bg-border/70">
          <DetailMetric label="Attempt" value={String(phase.attempt)} />
          <DetailMetric label="Status" value={phase.status} />
        </div>
        <div className="mt-6 space-y-2">
          {tools.length ? (
            tools.map((tool) => (
              <div
                className="flex items-center justify-between border border-border/70 px-3 py-2"
                key={tool.tool_call_id}
              >
                <span className="flex items-center gap-2 font-mono text-xs">
                  <Wrench className="size-3 text-amber-400" />
                  {tool.tool_call_id}
                </span>
                <span className="text-muted-foreground text-xs">
                  {tool.status}
                </span>
              </div>
            ))
          ) : (
            <p className="text-muted-foreground text-sm">
              No tool activity recorded for this phase yet.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.2em]">
        Workspace checkpoint
      </p>
      <div className="mt-5 flex items-start gap-3 border-border/70 border-b pb-4">
        <GitCommitHorizontal className="mt-0.5 size-4 text-muted-foreground" />
        <div>
          <p className="font-mono text-xs">{projection.workspace.revision}</p>
          <p className="mt-1 text-muted-foreground text-xs">
            {projection.connectionBasis === "live"
              ? "Live workspace"
              : "Restored state"}
          </p>
        </div>
      </div>
      <div className="mt-5 space-y-2">
        {projection.workspace.changed_files.map((file) => (
          <div className="flex items-center gap-2 text-sm" key={file}>
            <FileCode2 className="size-3.5 text-amber-400" />
            <span className="font-mono text-xs">{file}</span>
          </div>
        ))}
        {projection.workspace.changed_files.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No changed files at this checkpoint.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-card px-3 py-3">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
        {label}
      </p>
      <p className="mt-1 font-mono text-xs capitalize">{value}</p>
    </div>
  );
}
