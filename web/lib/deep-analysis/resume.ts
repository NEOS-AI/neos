/**
 * 실패한 deep_analysis run 재개 -- **사람이 누른 버튼에서만** 부른다.
 *
 * 구독(`subscription.ts`)과 일부러 떨어뜨려 둔다. 감사 §4.2 재과금 사고는
 * 재연결이 **자동으로** `POST /api/chat` 을 다시 쳐서 워크플로우를 통째로
 * 재실행한 것이었다. 이 함수는 그 둘이 아니다:
 *
 * - 부르는 곳은 `components/deep-analysis-status.tsx` 의 클릭 핸들러 하나다
 *   (`tests/source/deep-analysis-resume.test.tsx` 가 호출부를 이름으로 고정한다).
 * - 백엔드 `POST /api/v1/deep-analysis/{run_id}/resume` 은 원장이 이미 쓴 토큰을
 *   기억해 중복 지출을 막고, 완료된 run 은 409 로 거절한다.
 */

import { backendErrorMessage } from "@/lib/backend-error";
import { DEEP_ANALYSIS_EVENTS_PROXY_BASE } from "./subscription";

export async function resumeDeepAnalysis(runId: string): Promise<void> {
  const response = await fetch(
    `${DEEP_ANALYSIS_EVENTS_PROXY_BASE}/${encodeURIComponent(runId)}/resume`,
    { method: "POST" }
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(backendErrorMessage(body, "Could not resume deep analysis"));
  }
}
