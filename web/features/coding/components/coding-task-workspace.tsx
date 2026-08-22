"use client";

import { Radio, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { CodingApprovalCard } from "@/features/coding/components/coding-approval-card";
import { CodingDetailPanel } from "@/features/coding/components/coding-detail-panel";
import { CodingOutputLedger } from "@/features/coding/components/coding-output-ledger";
import { CodingSandboxStatus } from "@/features/coding/components/coding-sandbox-status";
import { CodingSteerComposer } from "@/features/coding/components/coding-steer-composer";
import { PhaseTimeline } from "@/features/coding/components/phase-timeline";
import { CodingWorkspaceDock } from "@/features/coding/components/workspace/coding-workspace-dock";
import { useSandboxStatus } from "@/features/coding/sandbox/use-sandbox-status";
import { useCodingStream } from "@/features/coding/stream/use-coding-stream";

const connectionMessages = {
  unauthorized: "Authorization expired. Reopen this task.",
  not_found: "This coding task is no longer accessible.",
  protocol_error: "The coding stream could not be restored.",
} as const;

export function CodingTaskWorkspace({ taskId }: { taskId: string }) {
  const { projection, connection } = useCodingStream(taskId);
  const sandbox = useSandboxStatus(taskId);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);
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
