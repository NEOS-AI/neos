"use client";

import { Box, TriangleAlert } from "lucide-react";
import type { SandboxStatusView } from "@/features/coding/sandbox/sandbox-status-store";

/**
 * 태스크 단계 옆에 붙는 한 줄짜리 샌드박스 상태.
 *
 * `aria-live="polite"` 다 -- 상태 변화는 사용자가 하던 일을 끊을 만큼 급하지
 * 않다. `assertive` 로 두면 타이핑 중에 스크린리더가 끼어든다.
 *
 * 여기에 나오는 문구는 전부 `sandbox-status-store` 가 만든 것이다. 이
 * 컴포넌트는 provider·지역·할당 식별자를 **받지도 않는다** -- 받지 않으면
 * 실수로 그릴 수 없다.
 */
export function CodingSandboxStatus({ status }: { status: SandboxStatusView }) {
  const attention =
    status.state === "operator_recovery_required" ||
    status.state === "provider_recovery_pending" ||
    status.state === "unknown";

  return (
    <div className="flex flex-col gap-1">
      <p
        aria-live="polite"
        className={
          attention
            ? "flex items-center gap-1.5 font-mono text-[10px] text-amber-300 uppercase tracking-[0.14em]"
            : "flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground uppercase tracking-[0.14em]"
        }
      >
        <Box className="size-3 shrink-0" />
        {status.copy}
        {status.stale ? (
          <span
            className="flex items-center gap-1 text-muted-foreground"
            title="Could not refresh sandbox status"
          >
            <TriangleAlert className="size-3" />
            stale
          </span>
        ) : null}
      </p>
      {status.announceRestored ? (
        <p
          aria-live="polite"
          className="font-mono text-[10px] text-emerald-300 tracking-[0.08em]"
        >
          Restored in a new execution environment
        </p>
      ) : null}
    </div>
  );
}
