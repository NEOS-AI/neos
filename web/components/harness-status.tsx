"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react";
import type { HarnessMetadata } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Tool, ToolContent, ToolHeader } from "./elements/tool";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";

const verdictLabel = (harness: HarnessMetadata) =>
  harness.verdict?.replaceAll("_", " ") ?? harness.status;

const scorePercent = (score: number | undefined) =>
  Math.round(Math.max(0, Math.min(1, score ?? 0)) * 100);

const statusState = (status: string) => {
  if (status === "failed") {
    return "output-error";
  }
  if (status === "passed") {
    return "output-available";
  }
  return "input-available";
};

const StatusIcon = ({ status }: { status: string }) => {
  if (status === "passed") {
    return <CheckCircle2Icon className="size-4 text-green-600" />;
  }
  if (status === "failed") {
    return <AlertTriangleIcon className="size-4 text-red-600" />;
  }
  if (status === "repairing") {
    return <RefreshCwIcon className="size-4 animate-spin text-amber-600" />;
  }
  return <ShieldCheckIcon className="size-4 text-blue-600" />;
};

export function HarnessStatus({ harness }: { harness: HarnessMetadata }) {
  const completedChecks = (harness.checks ?? []).filter(
    (check) => check.status === "completed"
  );
  const failedChecks = harness.failed_checks ?? [];
  const score = scorePercent(harness.score);

  return (
    <Tool
      className="border-blue-200/70 bg-blue-50/40 dark:border-blue-300/15 dark:bg-blue-950/20"
      defaultOpen={false}
    >
      <ToolHeader
        state={statusState(harness.status) as any}
        title="Research harness"
        type={"workflow-research-harness" as any}
      />
      <ToolContent>
        <div className="space-y-3 p-4 text-sm" data-testid="harness-status">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="gap-1 rounded-full" variant="secondary">
              <StatusIcon status={harness.status} />
              {verdictLabel(harness)}
            </Badge>
            {harness.mode && (
              <Badge className="rounded-full" variant="outline">
                {harness.mode}
              </Badge>
            )}
            <span className="text-muted-foreground text-xs">
              {completedChecks.length} checks
              {harness.repair_attempts
                ? ` · ${harness.repair_attempts} repair attempt${harness.repair_attempts === 1 ? "" : "s"}`
                : ""}
            </span>
          </div>

          {harness.score !== undefined && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Score</span>
                <span className="font-medium tabular-nums">{score}%</span>
              </div>
              <Progress className="h-2" value={score} />
            </div>
          )}

          {failedChecks.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {failedChecks.map((check) => (
                <Badge
                  className="rounded-full border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-950/30 dark:text-red-300"
                  key={check}
                  variant="outline"
                >
                  {check}
                </Badge>
              ))}
            </div>
          )}

          {completedChecks.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {completedChecks.map((check) => (
                <div
                  className={cn(
                    "flex items-center justify-between rounded-md border bg-background/60 px-2.5 py-2 text-xs",
                    check.passed === false &&
                      "border-red-200 dark:border-red-500/20"
                  )}
                  key={check.check}
                >
                  <span className="truncate">{check.check}</span>
                  <span className="ml-2 shrink-0 text-muted-foreground tabular-nums">
                    {check.score !== undefined
                      ? `${scorePercent(check.score)}%`
                      : check.severity}
                  </span>
                </div>
              ))}
            </div>
          )}

          {(harness.repair_actions ?? []).length > 0 && (
            <div className="space-y-1.5">
              <div className="font-medium text-muted-foreground text-xs">
                Repair actions
              </div>
              {(harness.repair_actions ?? []).slice(-3).map((action, index) => (
                <div
                  className="rounded-md bg-muted/50 px-2.5 py-2 text-xs"
                  key={`${String(action.action_type ?? "repair")}-${index}`}
                >
                  <span className="font-medium">
                    {String(action.action_type ?? "repair")}
                  </span>
                  {action.status !== undefined && (
                    <span className="text-muted-foreground">
                      {" "}
                      · {String(action.status)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </ToolContent>
    </Tool>
  );
}
