"use client";

import { Clock3, ShieldAlert, Terminal } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { decideCodingApproval } from "@/features/coding/api/coding-api";
import type { CodingApprovalView } from "@/features/coding/types/projection";

type ParsedQuestion = {
  prompt: string;
  options: string[];
  multiSelect: boolean;
};

export function CodingApprovalCard({
  taskId,
  approval,
  live,
}: {
  taskId: string;
  approval: CodingApprovalView;
  live: boolean;
}) {
  const [submitting, setSubmitting] = useState<
    "approve" | "deny" | "remember" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const questions = parseQuestions(approval.display_summary);
  const warnings = Array.isArray(approval.display_summary.warnings)
    ? approval.display_summary.warnings.filter(
        (item): item is string => typeof item === "string"
      )
    : [];
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ""));
  const [multiSelected, setMultiSelected] = useState<string[][]>(() =>
    questions.map(() => [])
  );
  const disabled = !live || approval.status !== "pending" || submitting !== null;
  const command = approval.risk === "command";
  const workspaceWrite = approval.risk === "workspace_write";
  const asking = approval.tool_name === "ask_user.v1" || questions.length > 0;
  const answersReady =
    !asking ||
    questions.every((question, index) =>
      questionAnswered(question, answers[index], multiSelected[index])
    );
  const approveDisabled = disabled || !answersReady;
  const planBody = implementPlanBody(approval);

  async function decide(decision: "approve" | "deny", remember = false) {
    setSubmitting(remember ? "remember" : decision);
    setError(null);
    try {
      await decideCodingApproval(
        taskId,
        approval.approval_id,
        decision,
        asking ? submitAnswers(questions, answers, multiSelected) : [],
        remember
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

      {warnings.length > 0 ? (
        <ul className="mt-3 space-y-1 border border-rose-400/40 bg-rose-500/10 px-3 py-2">
          {warnings.map((warning) => (
            <li
              className="font-mono text-[11px] text-rose-300"
              key={warning}
            >
              {warning.replaceAll("_", " ")}
            </li>
          ))}
        </ul>
      ) : null}

      {asking ? (
        <div className="mt-4 space-y-2">
          {questions.map((question, index) => {
            const choices = question.options;
            return (
            <div className="block" key={`${question.prompt}:${index}`}>
              <span className="font-mono text-[10px] text-muted-foreground">
                {question.prompt}
              </span>
              {choices.length >= 2 ? (
                <div className="mt-1 space-y-1">
                  {choices.map((choice) => (
                    <label className="flex items-center gap-2 font-mono text-xs" key={choice}>
                      <input
                        checked={
                          question.multiSelect
                            ? multiSelected[index]?.includes(choice)
                            : answers[index] === choice
                        }
                        disabled={disabled}
                        name={`ask-${approval.approval_id}-${index}`}
                        onChange={() => {
                          if (question.multiSelect) {
                            const current = multiSelected[index] ?? [];
                            const nextRow = current.includes(choice)
                              ? current.filter((item) => item !== choice)
                              : [...current, choice];
                            const next = [...multiSelected];
                            next[index] = nextRow;
                            setMultiSelected(next);
                            return;
                          }
                          const next = [...answers];
                          next[index] = choice;
                          setAnswers(next);
                        }}
                        type={question.multiSelect ? "checkbox" : "radio"}
                        value={choice}
                      />
                      {choice}
                    </label>
                  ))}
                  <input
                    aria-label="Other"
                    className="mt-1 w-full border border-border/70 bg-background px-2 py-1 font-mono text-xs"
                    disabled={disabled}
                    onChange={(event) => {
                      const next = [...answers];
                      next[index] = event.target.value;
                      setAnswers(next);
                    }}
                    placeholder="Other"
                    value={
                      question.multiSelect || !choices.includes(answers[index] ?? "")
                        ? answers[index] ?? ""
                        : ""
                    }
                  />
                </div>
              ) : (
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
              )}
            </div>
            );
          })}
        </div>
      ) : (
        <dl className="mt-4 grid gap-px border border-border/60 bg-border/60 sm:grid-cols-2">
          {Object.entries(approval.display_summary)
            .filter(([label]) => !hiddenSummaryKeys(planBody).has(label))
            .map(([label, value]) => (
            <div className="bg-background/90 px-3 py-2" key={label}>
              <dt className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider">
                {label.replaceAll("_", " ")}
              </dt>
              <dd className="mt-1 truncate font-mono text-xs">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {planBody ? (
        <div className="mt-4 space-y-2">
          {planBody.preview ? (
            <pre className="whitespace-pre-wrap break-words border border-border/60 bg-background/90 px-3 py-2 font-mono text-xs">
              {planBody.preview}
            </pre>
          ) : null}
          {planBody.plan ? (
            <pre className="whitespace-pre-wrap break-words border border-border/60 bg-background/90 px-3 py-2 font-mono text-xs">
              {planBody.plan}
            </pre>
          ) : null}
          {planBody.criticalFiles ? (
            <div className="border border-border/60 bg-background/90 px-3 py-2">
              <p className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider">
                critical files
              </p>
              <p className="mt-1 whitespace-pre-wrap font-mono text-xs">
                {planBody.criticalFiles}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

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
          {workspaceWrite ? (
            <Button
              aria-label="Approve tool for this run"
              disabled={approveDisabled}
              onClick={() => decide("approve", true)}
              size="sm"
              type="button"
              variant="outline"
            >
              {submitting === "remember" ? "Approving…" : "Approve for this run"}
            </Button>
          ) : null}
          <Button
            aria-label="Approve tool request"
            disabled={approveDisabled}
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

function asTrimmedString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function optionLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.length > 0) return [item];
    if (item && typeof item === "object" && "label" in item) {
      const label = asTrimmedString((item as { label?: unknown }).label);
      return label ? [label] : [];
    }
    return [];
  });
}

function parseQuestions(summary: Record<string, unknown>): ParsedQuestion[] {
  const raw = Array.isArray(summary.questions) ? summary.questions : [];
  const optionGroups = Array.isArray(summary.options) ? summary.options : [];
  const multiFlags = Array.isArray(summary.multi_select)
    ? summary.multi_select
    : typeof summary.multi_select === "boolean"
      ? raw.map(() => summary.multi_select)
      : [];
  return raw.flatMap((item, index): ParsedQuestion[] => {
    if (typeof item === "string") {
      return [
        {
          prompt: item,
          options: optionLabels(optionGroups[index]),
          multiSelect: multiFlags[index] === true,
        },
      ];
    }
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const prompt =
      asTrimmedString(record.prompt) ?? asTrimmedString(record.question);
    if (!prompt) return [];
    const options = optionLabels(record.options).length
      ? optionLabels(record.options)
      : optionLabels(optionGroups[index]);
    return [
      {
        prompt,
        options,
        multiSelect: record.multi_select === true || multiFlags[index] === true,
      },
    ];
  });
}

function questionAnswered(
  question: ParsedQuestion,
  answer: string | undefined,
  selected: string[] | undefined
): boolean {
  const other = (answer ?? "").trim();
  if (question.multiSelect) {
    return (selected?.length ?? 0) > 0 || other.length > 0;
  }
  return other.length > 0;
}

function submitAnswers(
  questions: ParsedQuestion[],
  answers: string[],
  multiSelected: string[][]
): string[] {
  return questions.map((question, index) => {
    const other = (answers[index] ?? "").trim();
    if (!question.multiSelect) return answers[index] ?? "";
    const picked = [...(multiSelected[index] ?? [])];
    if (other) picked.push(other);
    return picked.join(", ");
  });
}

function renderTextField(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (Array.isArray(value)) {
    const parts = value.filter(
      (item): item is string => typeof item === "string" && item.trim().length > 0
    );
    return parts.length ? parts.join("\n") : null;
  }
  return null;
}

function implementPlanBody(approval: CodingApprovalView): {
  preview: string | null;
  plan: string | null;
  criticalFiles: string | null;
} | null {
  if (approval.tool_name !== "set_phase.v1") return null;
  const phase =
    asTrimmedString(approval.display_summary.phase) ??
    asTrimmedString(approval.display_summary.target_phase);
  if (phase !== "implement") return null;
  const preview = renderTextField(approval.display_summary.plan_preview);
  const plan = renderTextField(approval.display_summary.plan);
  const criticalFiles = renderTextField(approval.display_summary.critical_files);
  if (!preview && !plan && !criticalFiles) return null;
  return { preview, plan, criticalFiles };
}

function hiddenSummaryKeys(
  planBody: ReturnType<typeof implementPlanBody>
): Set<string> {
  const keys = new Set(["warnings"]);
  if (planBody) {
    keys.add("plan_preview");
    keys.add("plan");
    keys.add("critical_files");
  }
  return keys;
}
