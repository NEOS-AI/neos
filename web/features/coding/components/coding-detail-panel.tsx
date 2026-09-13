import { FileCode2, GitCommitHorizontal, Wrench } from "lucide-react";
import type {
  CodingProjectionState,
  CodingToolView,
} from "@/features/coding/types/projection";

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
            tools.map((tool) => {
              const name = toolName(tool);
              const preview = toolPreview(tool);
              const deniedBy = toolDeniedBy(tool);
              const reasonCode = toolReasonCode(tool);
              return (
                <div
                  className="border border-border/70 px-3 py-2"
                  key={tool.tool_call_id}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-2 font-mono text-xs">
                      <Wrench className="size-3 shrink-0 text-amber-400" />
                      <span className="truncate">
                        {name}
                        {preview ? ` · ${preview}` : ""}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 text-muted-foreground text-xs">
                      {toolUnchanged(tool) ? (
                        <span className="rounded-sm border border-amber-400/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-300">
                          unchanged
                        </span>
                      ) : null}
                      {tool.status}
                    </span>
                  </div>
                  {tool.status === "denied" && (deniedBy || reasonCode) ? (
                    <p className="mt-1 font-mono text-[11px] text-rose-300">
                      {deniedBy ? `denied_by ${deniedBy}` : null}
                      {deniedBy && reasonCode ? " · " : null}
                      {reasonCode ? `reason_code ${reasonCode}` : null}
                    </p>
                  ) : null}
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                    {tool.tool_call_id}
                  </p>
                </div>
              );
            })
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

function asTrimmedString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function toolName(tool: CodingToolView): string {
  return (
    asTrimmedString(tool.name) ??
    asTrimmedString(tool.result?.name) ??
    asTrimmedString(tool.result?.tool_name) ??
    "tool"
  );
}

function toolPreview(tool: CodingToolView): string | null {
  const preview =
    asTrimmedString(tool.preview) ?? asTrimmedString(tool.result?.preview);
  return preview ? preview.slice(0, 200) : null;
}

function toolUnchanged(tool: CodingToolView): boolean {
  return tool.unchanged === true || tool.result?.unchanged === true;
}

function toolDeniedBy(tool: CodingToolView): string | null {
  return (
    asTrimmedString(tool.denied_by) ?? asTrimmedString(tool.result?.denied_by)
  );
}

function toolReasonCode(tool: CodingToolView): string | null {
  return (
    asTrimmedString(tool.reason_code) ??
    asTrimmedString(tool.result?.reason_code)
  );
}
