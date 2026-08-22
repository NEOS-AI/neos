import type {
  CodingSandboxState,
  CodingSandboxStatus,
} from "@/features/coding/sandbox/types";

/**
 * 샌드박스 상태의 순수 리듀서.
 *
 * 두 가지 규율이 이 파일의 전부다.
 *
 * 1. **게이팅은 서버 불리언을 그대로 쓴다.** 상태 이름으로 다시 판정하지
 *    않는다 -- 두 번 해석하면 백엔드가 정책을 바꿔도 화면이 안 따라온다.
 *    유일한 예외가 규칙 2다.
 * 2. **모르는 상태는 실행을 막는다.** 백엔드가 상태를 추가했는데 프론트가
 *    모를 때 기본이 '실행 가능'이면, 정리 중인 샌드박스에서 명령이 도는
 *    사고가 조용히 열린다. 백엔드 투영이 화이트리스트를 쓰는 것과 같은
 *    이유이고, 같은 방향으로 틀린다(안전한 쪽).
 */

const COPY: Record<CodingSandboxState, string> = {
  preparing: "Preparing sandbox",
  ready: "Sandbox ready",
  suspended: "Sandbox suspended",
  provider_recovery_pending: "Provider recovery pending",
  operator_recovery_required: "Operator recovery required",
  cleaning_up: "Cleaning up sandbox",
  cleaned: "Sandbox cleaned up",
};

const UNKNOWN_COPY = "Sandbox status unavailable";

export type SandboxStatusView = {
  state: CodingSandboxState | "unknown";
  copy: string;
  canRun: boolean;
  canOpenTerminal: boolean;
  /** 마지막 응답 이후 폴링이 실패했다. **경고이지 차단이 아니다.** */
  stale: boolean;
  /** 복구 안내를 **이번 전이에서만** 참으로 둔다. */
  announceRestored: boolean;
  /** 한 번이라도 알렸는지 (sticky). `announceRestored`의 게이트다. */
  restoredSeen: boolean;
  updatedAt: string | null;
};

export function sandboxStatusCopy(state: CodingSandboxState): string {
  return COPY[state];
}

function isKnown(state: string): state is CodingSandboxState {
  return state in COPY;
}

export function initialSandboxStatus(): SandboxStatusView {
  // 서버가 답하기 전에는 실행을 막는다. 낙관적으로 열어 두면 첫 응답이
  // 오기 전 창에서 죽은 샌드박스에 제출이 들어간다.
  return {
    state: "unknown",
    copy: UNKNOWN_COPY,
    canRun: false,
    canOpenTerminal: false,
    stale: false,
    announceRestored: false,
    restoredSeen: false,
    updatedAt: null,
  };
}

export function reduceSandboxStatus(
  current: SandboxStatusView,
  next: CodingSandboxStatus
): SandboxStatusView {
  if (!isKnown(next.state)) {
    return {
      ...current,
      state: "unknown",
      copy: UNKNOWN_COPY,
      canRun: false,
      canOpenTerminal: false,
      stale: false,
      announceRestored: false,
      updatedAt: next.updated_at,
    };
  }
  return {
    state: next.state,
    copy: COPY[next.state],
    canRun: next.can_run,
    canOpenTerminal: next.can_open_terminal,
    stale: false,
    // 이미 알렸으면 다시 알리지 않는다 -- 폴링마다 같은 안내를 읽어 주면
    // 스크린리더 사용자에게는 5초마다 반복되는 소음이다.
    announceRestored:
      next.recovered_from_checkpoint && !current.restoredSeen,
    restoredSeen: current.restoredSeen || next.recovered_from_checkpoint,
    updatedAt: next.updated_at,
  };
}

/**
 * 폴링이 실패했다. **마지막으로 알던 것을 지우지 않는다** -- 지우면 사용자는
 * 방금까지 되던 것이 왜 안 되는지 알 수 없고, 실행 버튼이 요동친다.
 */
export function markSandboxStatusStale(
  current: SandboxStatusView
): SandboxStatusView {
  return { ...current, stale: true, announceRestored: false };
}
