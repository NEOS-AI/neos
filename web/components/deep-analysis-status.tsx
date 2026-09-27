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
  RotateCcwIcon,
} from "lucide-react";
import { useState } from "react";
import {
  type DeepAnalysisConnectionState,
  useDeepAnalysisStream,
} from "@/hooks/use-deep-analysis-stream";
import { degradationNotices } from "@/lib/deep-analysis/degradation";
import type { DeepAnalysisProgress } from "@/lib/deep-analysis/progress";
import { resumeDeepAnalysis } from "@/lib/deep-analysis/resume";
import type { DeepAnalysisMetadata } from "@/lib/types";
import { Tool, ToolContent, ToolHeader } from "./elements/tool";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

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

/** 접힌 카드가 보여줄 수 있는 유일한 상태다 — 본문과 어긋나면 안 된다. */
const headerState = (
  phase: DeepAnalysisProgress["phase"],
  connection: DeepAnalysisConnectionState
) => {
  // run 의 종결이 연결 상태를 이긴다. 끝난 run 은 어떤 소켓 상태에서도 끝났다.
  if (phase === "failed") {
    return "output-error";
  }
  if (phase === "completed") {
    return "output-available";
  }
  // 재시도해도 같은 답이 오는 실패(401/403/404)는 진행이 아니다. 이 분기가
  // 없을 때 헤더는 **영구히 "Running" 으로 맥동했다** -- 본문에 "접근 권한 없음"
  // 이 떠 있는 동안에도. 접힌 카드에서는 그 거짓말이 유일하게 보이는 정보다.
  if (connection === "unauthorized" || connection === "not_found") {
    return "output-error";
  }
  // pending 을 running 과 같은 상태로 접지 않는다. 접으면 헤더가 "Running",
  // 본문 배지가 "대기 중" 이 되어 같은 카드가 두 가지를 말한다.
  return phase === "running" ? "input-available" : "input-streaming";
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

/** `DeepAnalysisProgress` 의 숫자 필드 키. */
type NumericKey<T> = {
  [K in keyof T]-?: T[K] extends number ? K : never;
}[keyof T];

/** 그중 카운터인 것 — `cursor` 는 재구독 위치이지 세는 값이 아니다. */
type CounterKey = Exclude<NumericKey<DeepAnalysisProgress>, "cursor">;

type StatSpec = { label: string; hint?: string };

/**
 * 카운터 → 화면 문구. **`Record` 라 키 하나라도 빠지면 컴파일이 안 된다.**
 *
 * 이 표가 배열이던 시절 리듀서는 일곱을 셌고 화면은 넷만 그렸다 — 그리고
 * 어디에도 "일부러 뺐다"는 표시가 없어서 **판단인지 누락인지 구별되지
 * 않았다**(FE12). `claimsUnverified` 가 특히 그랬다: 기각과 형제인 품질
 * 신호인데 기각만 보여줬다. FE9 가 라벨에서 고친 것과 같은 결함이고,
 * 여기서는 타입이 그 역할을 한다 — 리듀서에 카운터를 더하면 `tsc --noEmit`
 * 이 막고, 그 `tsc` 는 이제 CI 에서 돈다(FE10).
 *
 * 안 그리기로 했다면 `null` 과 사유를 적는다. 지금은 일곱 다 그린다.
 * 카운터가 아닌 숫자 필드가 생기면 여기도 답을 요구하는데, 그때 `null` 을
 * 적는 것이 정확히 옳은 처리다.
 *
 * **선언 순서가 표시 순서다** — 파이프라인 순으로 둔다.
 */
const STAT_SPECS: Record<CounterKey, StatSpec | null> = {
  questionsOpened: { label: "질문" },
  splits: { label: "질문 분해" },
  passesCompleted: { label: "패스" },
  claimsVerified: { label: "검증 클레임" },
  claimsRejected: { label: "기각 클레임" },
  claimsUnverified: {
    label: "미검증 클레임",
    // 기각과 다르다. 기각은 판정자가 내린 결론이고 이쪽은 결론에 이르지
    // 못한 것이다 — 라벨만 보면 구별되지 않아 툴팁으로 갈라 준다.
    hint: "재시도 캡이 소진돼 검증도 기각도 하지 못한 클레임",
  },
  gradeAttempts: {
    label: "채점 시도",
    hint: "리포트를 조립하고 채점한 횟수. 1보다 크면 재조립이 있었다",
  },
};

type Stat = StatSpec & { value: number };

/** 값이 0인 항목은 빼므로, 표가 길어져도 조용한 run 은 조용하다. */
const stats = (progress: DeepAnalysisProgress): Stat[] =>
  (Object.entries(STAT_SPECS) as [CounterKey, StatSpec | null][]).flatMap(
    ([key, spec]) =>
      spec && progress[key] > 0 ? [{ ...spec, value: progress[key] }] : []
  );

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
  // 사람이 재개를 누른 횟수. 올라가면 구독이 처음부터 다시 붙는다 -- 종결된
  // run 이라도 그때부터는 저장된 상태가 아니라 스트림이 phase 를 말한다.
  const [resumes, setResumes] = useState(0);
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const { progress, connection } = useDeepAnalysisStream({
    runId: deepAnalysis.run_id,
    enabled: !alreadySettled || resumes > 0,
    subscriptionKey: resumes,
    onCompleted,
    onFailed,
  });

  const phase =
    alreadySettled && resumes === 0
      ? (deepAnalysis.status as DeepAnalysisProgress["phase"])
      : progress.phase;

  // 백엔드는 `running` 도 재개를 받지만 여기서는 `failed` 에만 연다 --
  // 실제로 도는 run 에 두 번째 워커를 붙일 이유가 화면에는 없다.
  const resume = async () => {
    if (resuming) {
      return;
    }
    setResuming(true);
    setResumeError(null);
    try {
      await resumeDeepAnalysis(deepAnalysis.run_id);
      setResumes((count) => count + 1);
    } catch (error) {
      setResumeError(
        error instanceof Error ? error.message : "Could not resume deep analysis"
      );
    } finally {
      setResuming(false);
    }
  };
  // 우선순위 판단이 아니라 "둘 중 채워진 쪽을 고른다"는 뜻이다. 라이브 세션에서는
  // 구독이 상태를 채우고, 새로고침 후에는 `alreadySettled`라 구독하지 않으므로
  // `progress.degradations`가 항상 비어 있다 — 둘 다 값을 갖는 경우는 없다.
  const notices = degradationNotices(
    progress.degradations.length > 0
      ? progress.degradations
      : (deepAnalysis.degradations ?? [])
  );
  const visibleStats = stats(progress);
  const connectionNote = connectionLabel[connection];

  // 보조기술에 안내할 한 가지. **아래 시각 줄의 게이트를 그대로 반영한다** --
  // 그래야 시각 줄에 `aria-hidden` 을 걸어도 잃는 것이 없다.
  //
  // 🔴 처음에는 연결 상태를 우선순위 맨 앞에 뒀는데 틀렸다. "재연결 중" 이
  // 활동 줄을 덮으면, 유휴 타임아웃이 난 run 의 마지막 활동("워커가 3라운드
  // 연속 실패 — 실행 종료")이 `aria-hidden` 뒤에서 **도달 불가**가 된다.
  // 연결 상태는 위 배지에 그대로 있고 그 배지는 읽을 수 있다.
  //
  // phase 를 접두사로 붙이지도 않는다 -- 이벤트마다 "분석 중" 이 반복돼
  // 소음이 된다. 활동 줄이 있다는 것 자체가 도는 중이라는 뜻이다.
  //
  // 안내 빈도가 감당되는 이유: 이력 재생(`after=0`)은 청크 하나의 이벤트를
  // 동기 루프로 dispatch 하므로 React 가 한 번의 렌더로 묶는다. 즉 재생 수백
  // 건이 안내 수백 번이 되지 않는다. 라이브 구간은 이벤트가 사람 속도로 와서
  // 그때의 갱신이 곧 진행 안내가 된다.
  const activityLine =
    progress.lastActivity && phase !== "completed"
      ? progress.lastActivity
      : null;
  const announcement = activityLine ?? phaseLabel[phase];

  return (
    <Tool
      className="border-purple-200/70 bg-purple-50/40 dark:border-purple-300/15 dark:bg-purple-950/20"
      defaultOpen={
        phase === "running" ||
        phase === "pending" ||
        // 실패한 run 은 할 수 있는 일(재개)이 있다. 접혀 열리면 버튼이 언마운트된다.
        phase === "failed" ||
        notices.length > 0
      }
    >
      <ToolHeader
        state={headerState(phase, connection) as never}
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
            {phase === "failed" && (
              <Button
                aria-label="Resume deep analysis"
                className="ml-auto h-7"
                disabled={resuming}
                onClick={() => {
                  resume().catch(() => undefined);
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                <RotateCcwIcon className="mr-1 size-3.5" />
                {resuming ? "재개 중…" : "이어서 분석"}
              </Button>
            )}
          </div>
          {resumeError && (
            <p className="text-destructive text-xs">{resumeError}</p>
          )}

          {/*
            보조기술용 라이브 영역. **항상 마운트돼 있어야 한다** — 아래 시각
            줄은 조건부라 마운트되는 순간의 내용이 안내되지 않는 스크린리더가
            있다. 저장소의 기존 관례(`submit-button.tsx` 의 `<output
            aria-live="polite" className="sr-only">`)와 같은 모양이다.

            시각 줄이 `aria-hidden` 인 이유: 같은 문장을 두 번 읽지 않게.
            그것이 안전한 이유는 `announcement` 가 그 줄의 게이트를 그대로
            반영해서다 — 줄이 그려지는 모든 경우에 같은 문장이 여기 있다.

            ⚠️ `ToolContent`(Radix CollapsibleContent)는 접히면 자식을
            **언마운트**한다. 즉 접힌 카드는 안내하지 않는다. 그것은 사용자가
            접었다는 뜻이므로 맞는 동작이고, 강등이 있으면 카드가 펼쳐진 채
            열리므로(`defaultOpen`) 놓치는 경로가 아니다.
          */}
          <output aria-live="polite" className="sr-only">
            {announcement}
          </output>

          {/*
            완료 후 활동 줄을 감추는 것은 의도다. 이 줄은 "지금 무슨 일이
            일어나는가"이고 완료 후엔 의미가 없다. 강등은 아래 경고 블록이
            영구히 맡으므로 이 게이트가 강등을 숨기지 않는다 — 게이트를
            없애면 같은 사실이 두 줄로 중복된다.
          */}
          {activityLine && (
            <div
              aria-hidden="true"
              className="truncate text-muted-foreground text-xs"
              // 한 줄로 자르므로 좁은 화면에서는 전문을 볼 방법이 없다.
              // 라벨 일부는 길다("하위질문 심사 실패 — 제안 5개를 ...").
              title={activityLine}
            >
              {activityLine}
            </div>
          )}

          {notices.length > 0 && (
            <ul
              // `role="alert"` 이 아니다. alert 는 assertive 라 진행 중인 낭독을
              // 끊는데 이것은 품질 경고이지 긴급 알림이 아니고, 게다가 alert 는
              // 목록 의미론을 덮어써 "3개 중 2번째" 를 잃는다. polite + 이름이
              // 맞는 조합이다.
              aria-label="리포트 품질 경고"
              aria-live="polite"
              className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-amber-800 text-xs dark:border-amber-500/20 dark:bg-amber-950/30 dark:text-amber-200"
              data-testid="deep-analysis-degradations"
            >
              {notices.map((notice) => (
                <li className="flex items-start gap-1.5" key={notice.kind}>
                  <AlertTriangleIcon className="mt-0.5 size-3 shrink-0" />
                  <span>{notice.text}</span>
                </li>
              ))}
            </ul>
          )}

          {visibleStats.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {visibleStats.map((stat) => (
                <div
                  className="flex items-center justify-between rounded-md border bg-background/60 px-2.5 py-2 text-xs"
                  key={stat.label}
                  // 라벨만으로 갈리지 않는 항목이 있다(미검증 ↔ 기각).
                  // `hint` 가 없으면 속성 자체가 붙지 않는다.
                  title={stat.hint}
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
