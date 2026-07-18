/**
 * 진행 중인 deep_analysis run 포인터 저장소 (순수 모듈, 스토리지 주입 가능)
 *
 * 감사 §6 차단요인 2 — "run_id를 담을 곳이 없다. 새로고침하면 진행 중 job으로
 * 되돌아갈 방법이 없다." 이 모듈이 그 자리다.
 *
 * 저장하는 것은 **run_id 하나(+ 어시스턴트 메시지 id)**뿐이다. 진행 상태는
 * 저장하지 않는다 — 새로고침 후에는 `after=0` 전체 재생으로 복원하는 것이
 * 정확하기 때문이다(`./subscription.ts` 주석 참조).
 *
 * ⚠️ 여기 저장된 값은 **재구독에만** 쓰인다. 이 포인터를 근거로 job을 다시
 * 제출하는 코드는 절대 있어서는 안 된다(감사 §4.2의 재과금 사고).
 */

type PointerStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const ACTIVE_RUN_PREFIX = "neos:deep-analysis:run:";

function browserStorage(): PointerStorage | undefined {
  if (typeof window === "undefined") {
    return;
  }
  try {
    return window.sessionStorage;
  } catch {
    // Safari 프라이빗 모드 등에서 접근 자체가 던질 수 있다.
    return;
  }
}

export type ActiveDeepAnalysisRun = {
  runId: string;
  assistantMessageId?: string;
};

function key(chatId: string): string {
  return `${ACTIVE_RUN_PREFIX}${chatId}`;
}

export function rememberActiveRun(
  chatId: string,
  run: ActiveDeepAnalysisRun,
  storage: PointerStorage | undefined = browserStorage()
): void {
  if (!(chatId && run.runId)) {
    return;
  }
  try {
    storage?.setItem(key(chatId), JSON.stringify(run));
  } catch {
    // 저장 실패는 치명적이지 않다 — 같은 마운트 안에서는 메모리로 동작한다.
  }
}

export function readActiveRun(
  chatId: string,
  storage: PointerStorage | undefined = browserStorage()
): ActiveDeepAnalysisRun | null {
  if (!chatId) {
    return null;
  }
  let raw: string | null | undefined;
  try {
    raw = storage?.getItem(key(chatId));
  } catch {
    return null;
  }
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as { runId?: unknown }).runId !== "string" ||
      (parsed as { runId: string }).runId.length === 0
    ) {
      return null;
    }
    const messageId = (parsed as { assistantMessageId?: unknown })
      .assistantMessageId;
    return {
      runId: (parsed as { runId: string }).runId,
      assistantMessageId:
        typeof messageId === "string" && messageId.length > 0
          ? messageId
          : undefined,
    };
  } catch {
    return null;
  }
}

export function forgetActiveRun(
  chatId: string,
  storage: PointerStorage | undefined = browserStorage()
): void {
  if (!chatId) {
    return;
  }
  try {
    storage?.removeItem(key(chatId));
  } catch {
    // no-op
  }
}
