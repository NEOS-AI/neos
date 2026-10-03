"use client";

import { Play, Radio, Square, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CodingApprovalCard } from "@/features/coding/components/coding-approval-card";
import { CodingDetailPanel } from "@/features/coding/components/coding-detail-panel";
import { CodingOutputLedger } from "@/features/coding/components/coding-output-ledger";
import { CodingRunSignals } from "@/features/coding/components/coding-run-signals";
import { CodingSandboxStatus } from "@/features/coding/components/coding-sandbox-status";
import { CodingSteerComposer } from "@/features/coding/components/coding-steer-composer";
import { PhaseTimeline } from "@/features/coding/components/phase-timeline";
import { CodingWorkspaceDock } from "@/features/coding/components/workspace/coding-workspace-dock";
import {
  resumeCodingTask,
  stopCodingTask,
} from "@/features/coding/api/coding-api";
import { useSandboxStatus } from "@/features/coding/sandbox/use-sandbox-status";
import { useCodingStream } from "@/features/coding/stream/use-coding-stream";
import type { CodingProjectionState } from "@/features/coding/types/projection";

const TERMINAL_TASK_STATUSES = new Set([
  "cancelled",
  "completed",
  "failed",
  "expired",
  "archived",
]);

const connectionMessages = {
  unauthorized: "Authorization expired. Reopen this task.",
  not_found: "This coding task is no longer accessible.",
  protocol_error: "The coding stream could not be restored.",
} as const;

export function CodingTaskWorkspace({ taskId }: { taskId: string }) {
  const { projection, connection } = useCodingStream(taskId);
  const sandbox = useSandboxStatus(taskId);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const canStop =
    projection.taskStatus != null &&
    !TERMINAL_TASK_STATUSES.has(projection.taskStatus) &&
    connection !== "unauthorized" &&
    connection !== "not_found";

  async function cancelRun() {
    if (!canStop || stopping) {
      return;
    }
    setStopping(true);
    setStopError(null);
    try {
      await stopCodingTask(taskId);
    } catch (cause) {
      setStopError(
        cause instanceof Error ? cause.message : "Could not stop coding task"
      );
    } finally {
      setStopping(false);
    }
  }

  // 트랙 Q10b -- 예산 봉투가 멈춘 태스크. 재개는 사람만 한다. 다시 넘어 있으면
  // 다음 모델 턴 전에 또 멈춘다.
  const paused = projection.taskStatus === "paused";

  async function resumeRun() {
    if (!paused || resuming) {
      return;
    }
    setResuming(true);
    setStopError(null);
    try {
      await resumeCodingTask(taskId);
    } catch (cause) {
      setStopError(
        cause instanceof Error ? cause.message : "Could not resume coding task"
      );
    } finally {
      setResuming(false);
    }
  }

  useEffect(() => {
    const active = projection.phases.find((phase) => phase.status === "active");
    if (active) {
      setSelectedPhase(active.phase_id);
    }
  }, [projection.phases]);
  const connectionMessage =
    connection in connectionMessages
      ? connectionMessages[connection as keyof typeof connectionMessages]
      : null;
  const pendingApprovals = Object.values(projection.approvalsById).filter(
    (approval) => approval.status === "pending"
  );
  const waitingApproval = projection.taskStatus === "waiting_approval";
  const todos = projection.todos.filter(
    (todo) =>
      typeof todo.content === "string" || typeof todo.status === "string"
  );

  return (
    <main className="flex min-h-dvh flex-1 flex-col bg-background">
      <header className="flex h-14 items-center justify-between border-border/70 border-b px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <TerminalSquare className="size-4 shrink-0 text-amber-400" />
          <span className="truncate font-mono text-sm">{taskId}</span>
          {projection.activeRun ? (
            <span className="hidden border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground md:inline">
              RUN {projection.activeRun.attempt}
            </span>
          ) : null}
          {waitingApproval ? (
            <span className="border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 font-mono text-[10px] text-amber-300 uppercase tracking-wider">
              waiting_approval
            </span>
          ) : null}
          {paused ? (
            <span
              className="border border-sky-400/40 bg-sky-400/10 px-2 py-0.5 font-mono text-[10px] text-sky-300 uppercase tracking-wider"
              data-testid="coding-paused-badge"
            >
              paused
            </span>
          ) : null}
          <UsageBadge projection={projection} />
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]">
          <Radio
            className={
              connection === "live"
                ? "size-3 text-emerald-400"
                : "size-3 text-amber-400"
            }
          />
          {projection.connectionBasis === "live"
            ? "Live"
            : "Checkpoint restored"}
          <CodingSandboxStatus status={sandbox} />
          {paused ? (
            <Button
              data-testid="coding-resume-button"
              disabled={resuming}
              onClick={() => {
                resumeRun().catch((cause) => {
                  setStopError(
                    cause instanceof Error
                      ? cause.message
                      : "Could not resume coding task"
                  );
                });
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              <Play className="mr-1 size-3.5" />
              Resume
            </Button>
          ) : null}
          <Button
            data-testid="coding-stop-button"
            disabled={!canStop || stopping}
            onClick={() => {
              cancelRun().catch((cause) => {
                setStopError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not stop coding task"
                );
              });
            }}
            size="sm"
            type="button"
            variant="destructive"
          >
            <Square className="mr-1 size-3.5" />
            Cancel
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto border-border/70 p-4 lg:p-6">
          <div className="mx-auto max-w-3xl">
            <div className="mb-5 flex items-end justify-between border-border/60 border-b pb-3">
              <div>
                <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.22em]">
                  Execution ledger
                </p>
                <h1 className="mt-2 font-medium text-xl">Coding phases</h1>
              </div>
              <span className="font-mono text-[10px] text-muted-foreground">
                SEQ {projection.appliedSeq}
              </span>
            </div>
            {todos.length > 0 ? (
              <section aria-label="Todos" className="mb-5 space-y-1">
                <p className="font-mono text-[10px] text-amber-400 uppercase tracking-[0.22em]">
                  Todos
                </p>
                <ul className="space-y-1">
                  {todos.map((todo, index) => {
                    const content =
                      typeof todo.content === "string" ? todo.content : "";
                    const status =
                      typeof todo.status === "string" ? todo.status : "";
                    const key =
                      typeof todo.id === "string"
                        ? todo.id
                        : `${content}:${index}`;
                    return (
                      <li
                        className="flex items-center justify-between gap-3 border border-border/70 px-3 py-2"
                        key={key}
                      >
                        <span className="min-w-0 truncate text-sm">
                          {content}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]">
                          {status}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}
            <CodingRunSignals projection={projection} />
            <CodingOutputLedger
              parts={projection.orderedTextPartIds.map(
                (partId) => projection.textPartsById[partId]
              )}
            />
            <PhaseTimeline
              onSelect={setSelectedPhase}
              phases={projection.phases}
              selectedId={selectedPhase}
              waitingApproval={waitingApproval}
            />
            <div className="mt-5">
              <CodingDetailPanel
                phaseId={selectedPhase}
                projection={projection}
              />
            </div>
            {pendingApprovals.length > 0 ? (
              <section
                aria-label="Tool approval requests"
                className="mt-5 space-y-2"
              >
                {pendingApprovals.map((approval) => (
                  <CodingApprovalCard
                    approval={approval}
                    key={approval.approval_id}
                    live={connection === "live"}
                    taskId={taskId}
                  />
                ))}
              </section>
            ) : null}
            <div className="mt-5">
              {/*
                실행만 막고 초안은 그대로 둔다. `CodingSteerComposer` 는
                disabled 여도 입력값을 자기 상태로 들고 있으므로, 샌드박스가
                돌아오면 사용자가 쓰던 문장이 그 자리에 남아 있다 -- 여기서
                컴포넌트를 언마운트하면 그 초안이 사라진다.
                게이팅 근거는 서버 불리언(`sandbox.canRun`)이지 상태 이름이
                아니다.
              */}
              <CodingSteerComposer
                disabled={
                  connection === "unauthorized" ||
                  connection === "not_found" ||
                  !sandbox.canRun
                }
                taskId={taskId}
              />
            </div>
            {stopError ? (
              <p className="mt-3 border-red-400/30 border-l-2 bg-red-400/5 px-3 py-2 text-destructive text-xs">
                {stopError}
              </p>
            ) : null}
            {connectionMessage ? (
              <p className="mt-3 border-red-400/30 border-l-2 bg-red-400/5 px-3 py-2 text-destructive text-xs">
                {connectionMessage}
              </p>
            ) : null}
          </div>
        </section>
        {/*
          독은 그대로 둔다 -- 파일·diff 읽기는 샌드박스가 아파도 계속
          제공한다. 막는 것은 실행 표면(제출·PTY 생성)뿐이다.
        */}
        <CodingWorkspaceDock
          canOpenTerminal={sandbox.canOpenTerminal}
          codingConnection={connection}
          projection={projection}
          taskId={taskId}
        />
      </div>
    </main>
  );
}

function formatMicros(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(2)}`;
}

function UsageBadge({ projection }: { projection: CodingProjectionState }) {
  const parts: string[] = [];
  if (typeof projection.costMicros === "number") {
    const cost = formatMicros(projection.costMicros);
    parts.push(
      typeof projection.maxCostMicros === "number"
        ? `${cost} / ${formatMicros(projection.maxCostMicros)}`
        : cost
    );
  }
  if (
    typeof projection.inputTokens === "number" ||
    typeof projection.outputTokens === "number"
  ) {
    parts.push(
      `${projection.inputTokens ?? 0}+${projection.outputTokens ?? 0} tok`
    );
  }
  if (parts.length === 0) return null;
  return (
    <span className="hidden border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground md:inline">
      {parts.join(" · ")}
    </span>
  );
}
