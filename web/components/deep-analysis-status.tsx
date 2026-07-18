"use client";

/**
 * 챗 인라인 deep_analysis 진행 표시
 *
 * `harness-status.tsx`의 구조를 그대로 따른다(Tool/Badge/Progress).
 * 다른 점은 상태의 출처뿐이다 — 하네스는 챗 SSE로 밀려오지만,
 * deep_analysis는 이 컴포넌트가 **별도 job 스트림을 직접 구독**한다.
 */

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  LoaderIcon,
  MicroscopeIcon,
  PlugZapIcon,
} from "lucide-react";
import {
  type DeepAnalysisConnectionState,
  useDeepAnalysisStream,
} from "@/hooks/use-deep-analysis-stream";
import type { DeepAnalysisProgress } from "@/lib/deep-analysis/progress";
import type { DeepAnalysisMetadata } from "@/lib/types";
import { Tool, ToolContent, ToolHeader } from "./elements/tool";
import { Badge } from "./ui/badge";

const phaseLabel: Record<DeepAnalysisProgress["phase"], string> = {
  pending: "대기 중",
  running: "분석 중",
  completed: "완료",
  failed: "실패",
};

const connectionLabel: Partial<Record<DeepAnalysisConnectionState, string>> = {
  reconnecting: "재연결 중",
  unauthorized: "접근 권한 없음",
  not_found: "run을 찾을 수 없음",
};

const toolState = (phase: DeepAnalysisProgress["phase"]) => {
  if (phase === "failed") {
    return "output-error";
  }
  if (phase === "completed") {
    return "output-available";
  }
  return "input-available";
};

const PhaseIcon = ({ phase }: { phase: DeepAnalysisProgress["phase"] }) => {
  if (phase === "completed") {
    return <CheckCircle2Icon className="size-4 text-green-600" />;
  }
  if (phase === "failed") {
    return <AlertTriangleIcon className="size-4 text-red-600" />;
  }
  if (phase === "running") {
    return <LoaderIcon className="size-4 animate-spin text-purple-600" />;
  }
  return <MicroscopeIcon className="size-4 text-purple-600" />;
};

type Stat = { label: string; value: number };

const stats = (progress: DeepAnalysisProgress): Stat[] =>
  [
    { label: "질문", value: progress.questionsOpened },
    { label: "패스", value: progress.passesCompleted },
    { label: "검증 클레임", value: progress.claimsVerified },
    { label: "기각 클레임", value: progress.claimsRejected },
  ].filter((stat) => stat.value > 0);

export type DeepAnalysisStatusProps = {
  deepAnalysis: DeepAnalysisMetadata;
  /**
   * 리포트가 도착했을 때 호출된다. 호출자가 어시스턴트 메시지 본문을 채운다.
   * 백엔드도 리포트를 메시지에 영속화하므로, 새로고침 후에는 이 콜백 없이도
   * 리포트가 대화에 남는다.
   */
  onCompleted?: (reportMarkdown: string | null) => void;
  onFailed?: (error: string) => void;
};

export function DeepAnalysisStatus({
  deepAnalysis,
  onCompleted,
  onFailed,
}: DeepAnalysisStatusProps) {
  // 이미 종결된 run은 다시 구독하지 않는다 — 이력 재생 비용이 무의미하다.
  const alreadySettled =
    deepAnalysis.status === "completed" || deepAnalysis.status === "failed";

  const { progress, connection } = useDeepAnalysisStream({
    runId: deepAnalysis.run_id,
    enabled: !alreadySettled,
    onCompleted,
    onFailed,
  });

  const phase = alreadySettled
    ? (deepAnalysis.status as DeepAnalysisProgress["phase"])
    : progress.phase;
  const visibleStats = stats(progress);
  const connectionNote = connectionLabel[connection];

  return (
    <Tool
      className="border-purple-200/70 bg-purple-50/40 dark:border-purple-300/15 dark:bg-purple-950/20"
      defaultOpen={phase === "running" || phase === "pending"}
    >
      <ToolHeader
        state={toolState(phase) as never}
        title="Deep analysis"
        type={"workflow-deep-analysis" as never}
      />
      <ToolContent>
        <div
          className="space-y-3 p-4 text-sm"
          data-testid="deep-analysis-status"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="gap-1 rounded-full" variant="secondary">
              <PhaseIcon phase={phase} />
              {phaseLabel[phase]}
            </Badge>
            {progress.resumed && (
              <Badge className="rounded-full" variant="outline">
                재개됨
              </Badge>
            )}
            {connectionNote && (
              <Badge className="gap-1 rounded-full" variant="outline">
                <PlugZapIcon className="size-3" />
                {connectionNote}
              </Badge>
            )}
          </div>

          {progress.lastActivity && phase !== "completed" && (
            <div className="truncate text-muted-foreground text-xs">
              {progress.lastActivity}
            </div>
          )}

          {visibleStats.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {visibleStats.map((stat) => (
                <div
                  className="flex items-center justify-between rounded-md border bg-background/60 px-2.5 py-2 text-xs"
                  key={stat.label}
                >
                  <span className="truncate">{stat.label}</span>
                  <span className="ml-2 shrink-0 text-muted-foreground tabular-nums">
                    {stat.value}
                  </span>
                </div>
              ))}
            </div>
          )}

          {progress.error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-red-700 text-xs dark:border-red-500/20 dark:bg-red-950/30 dark:text-red-300">
              {progress.error}
            </div>
          )}
        </div>
      </ToolContent>
    </Tool>
  );
}
