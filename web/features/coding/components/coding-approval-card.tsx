"use client";

import { Clock3, ShieldAlert, Terminal } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { decideCodingApproval } from "@/features/coding/api/coding-api";
import type { CodingApprovalView } from "@/features/coding/types/projection";

export function CodingApprovalCard({
  taskId,
  approval,
  live,
}: {
  taskId: string;
  approval: CodingApprovalView;
  live: boolean;
}) {
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const questions = Array.isArray(approval.display_summary.questions)
    ? approval.display_summary.questions.filter(
        (item): item is string => typeof item === "string"
      )
    : [];
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ""));
  const disabled = !live || approval.status !== "pending" || submitting !== null;
  const command = approval.risk === "command";
  const asking = approval.tool_name === "ask_user.v1" || questions.length > 0;

  async function decide(decision: "approve" | "deny") {
    setSubmitting(decision);
    setError(null);
    try {
      await decideCodingApproval(
        taskId,
        approval.approval_id,
        decision,
        asking ? answers : []
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "승인 요청을 처리하지 못했습니다."
      );
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <article
      className={`border-l-2 bg-card/55 p-4 ${
        command ? "border-l-rose-400" : "border-l-amber-400"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <span className="mt-0.5 border border-border/80 bg-background/70 p-2">
            {command ? (
              <Terminal className="size-4 text-rose-400" />
            ) : (
              <ShieldAlert className="size-4 text-amber-400" />
            )}
          </span>
          <div className="min-w-0">
            <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-[0.18em]">
              {command ? "Command permission" : "Workspace permission"}
            </p>
            <h2 className="mt-1 truncate font-mono text-sm">
              {approval.tool_name}
            </h2>
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] text-muted-foreground">
          <Clock3 className="size-3" />
          {new Date(approval.expires_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {asking ? (
        <div className="mt-4 space-y-2">
          {questions.map((question, index) => (
            <label className="block" key={question}>
              <span className="font-mono text-[10px] text-muted-foreground">
                {question}
              </span>
              <input
                className="mt-1 w-full border border-border/70 bg-background px-2 py-1 font-mono text-xs"
                disabled={disabled}
                onChange={(event) => {
                  const next = [...answers];
                  next[index] = event.target.value;
                  setAnswers(next);
                }}
                value={answers[index] ?? ""}
              />
            </label>
          ))}
        </div>
      ) : (
        <dl className="mt-4 grid gap-px border border-border/60 bg-border/60 sm:grid-cols-2">
          {Object.entries(approval.display_summary).map(([label, value]) => (
            <div className="bg-background/90 px-3 py-2" key={label}>
              <dt className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider">
                {label.replaceAll("_", " ")}
              </dt>
              <dd className="mt-1 truncate font-mono text-xs">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">
          {live ? "Review this exact request before continuing." : "Reconnect to decide."}
        </p>
        <div className="flex gap-2">
          <Button
            aria-label="Deny tool request"
            disabled={disabled}
            onClick={() => decide("deny")}
            size="sm"
            type="button"
            variant="outline"
          >
            {submitting === "deny" ? "Denying…" : "Deny"}
          </Button>
          <Button
            aria-label="Approve tool request"
            disabled={disabled}
            onClick={() => decide("approve")}
            size="sm"
            type="button"
          >
            {submitting === "approve" ? "Approving…" : "Approve once"}
          </Button>
        </div>
      </div>
      {error ? (
        <p className="mt-3 text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}
