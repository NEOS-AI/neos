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

/** 복구 액션은 마지막 몇 건만 그린다 — 그 수를 한 곳에서 정한다. */
const RECENT_REPAIR_ACTIONS = 3;

export function HarnessStatus({ harness }: { harness: HarnessMetadata }) {
  const completedChecks = (harness.checks ?? []).filter(
    (check) => check.status === "completed"
  );
  const failedChecks = harness.failed_checks ?? [];
  const score = scorePercent(harness.score);

  const repairActions = harness.repair_actions ?? [];
  const recentRepairActions = repairActions.slice(-RECENT_REPAIR_ACTIONS);
  const hiddenRepairActions = repairActions.length - recentRepairActions.length;

  return (
    <Tool
      className="border-blue-200/70 bg-blue-50/40 dark:border-blue-300/15 dark:bg-blue-950/20"
      // 실패한 검사가 있으면 펼친 채 연다. `false` 로 고정돼 있던 동안
      // **실패는 클릭해야만 보였다** -- 그리고 `ToolContent` 는 접히면 자식을
      // 언마운트하므로 보조기술에도 아무것도 가지 않았다. §2.2 의 S6("실패가
      // 사용자에게도 보인다")이 심층분석 카드에서는 이 규칙으로 충족돼 있고
      // (`deep-analysis-status.tsx` 의 `notices.length > 0`), `failed_checks`
      // 는 그것의 형제다.
      //
      // 진행 중(`validating`/`repairing`)에는 펼치지 않는다 -- 심층분석과
      // 다른 점이고 의도다. 하네스는 거의 모든 응답에 붙으므로 진행마다
      // 자동으로 펼치면 대화가 카드로 덮인다. S6 이 요구하는 것은 "실패가
      // 보인다" 이지 "항상 보인다" 가 아니다.
      defaultOpen={failedChecks.length > 0}
    >
      <ToolHeader
        state={statusState(harness.status) as any}
        title="Research harness"
        type={"workflow-research-harness" as any}
      />
      <ToolContent>
        <div className="space-y-3 p-4 text-sm" data-testid="harness-status">
          {/*
            상태 줄이 곧 라이브 영역이다. 심층분석 카드처럼 `sr-only` 영역을
            따로 두지 않는 이유는 구조가 달라서다 — 저쪽은 활동 줄이 **조건부**
            라 안정적인 영역이 따로 필요했지만, 이 줄은 항상 그려진다. 여기에
            직접 걸면 중복 낭독도 `aria-hidden` 도 필요 없다.

            ⚠️ 접히면 `ToolContent` 가 자식을 언마운트하므로 안내도 멈춘다.
            그래서 위 `defaultOpen` 이 실패 시 펼치는 것과 짝이다 — 둘 중
            하나만 있으면 실패는 여전히 전달되지 않는다.
          */}
          <div aria-live="polite" className="flex flex-wrap items-center gap-2">
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
              {/* role=progressbar 에 이름이 없으면 "progressbar 76%" 로만
                  읽힌다 -- 옆의 "Score" 라벨은 연결돼 있지 않다. */}
              <Progress
                aria-label="하네스 점수"
                className="h-2"
                value={score}
              />
            </div>
          )}

          {/*
            `div` 가 아니라 `ul` 이다. 두 번 배웠다 — 역할 없는 `div` 는
            role=generic 이라 **이름을 받지 못하고**(`aria-label` 을 달아도
            보조기술이 무시한다), 그렇다고 `role="group"` 을 붙이면 시맨틱
            요소를 쓰라는 지적을 받는다. 이건 실제로 목록이므로 `ul` 이 맞고,
            role=list 를 공짜로 얻으면서 심층분석 카드의 강등 블록과 같은
            모양이 된다.
          */}
          {failedChecks.length > 0 && (
            <ul
              aria-label="실패한 검사"
              aria-live="polite"
              className="flex list-none flex-wrap gap-1.5"
            >
              {failedChecks.map((check) => (
                <li key={check}>
                  <Badge
                    className="rounded-full border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-950/30 dark:text-red-300"
                    variant="outline"
                  >
                    {check}
                  </Badge>
                </li>
              ))}
            </ul>
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
                  {/* 한 줄로 자르므로 좁은 화면에서는 전문을 볼 방법이 없다. */}
                  <span className="truncate" title={check.check}>
                    {check.check}
                  </span>
                  <span className="ml-2 shrink-0 text-muted-foreground tabular-nums">
                    {check.score !== undefined
                      ? `${scorePercent(check.score)}%`
                      : check.severity}
                  </span>
                </div>
              ))}
            </div>
          )}

          {repairActions.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-medium text-muted-foreground text-xs">
                Repair actions
              </div>
              {/*
                생략된 수를 **말한다.** 예전에는 `slice(-3)` 이 나머지를 흔적
                없이 버려서, 복구를 7번 시도한 run 과 3번 시도한 run 이 화면에서
                똑같아 보였다. §3.2 가 이 저장소의 주제로 적은 조용한 절삭이고,
                심층분석 카드는 같은 문제를 횟수 표시로 풀었다(`(2회)`).

                자르는 것 자체는 유지한다 -- 인라인 카드가 복구 로그로 길어지면
                리포트를 밀어낸다. 문제는 자르는 것이 아니라 말하지 않는 것이었다.
              */}
              {hiddenRepairActions > 0 && (
                <div className="text-muted-foreground text-xs">
                  이전 {hiddenRepairActions}건은 표시하지 않음 (총{" "}
                  {repairActions.length}건)
                </div>
              )}
              {recentRepairActions.map((action, index) => (
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
