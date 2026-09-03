/**
 * 백엔드 메시지 메타데이터 → `HarnessMetadata` (런타임 검증)
 *
 * ## 왜 필요한가 — 스키마는 있었고 아무도 부르지 않았다
 *
 * `harnessMetadataSchema` 는 `lib/types.ts` 에 정확한 모양으로 선언돼 있지만
 * **타입 소스로만** 쓰였다(`z.infer`). 실제 파싱은 한 번도 하지 않았고,
 * `convertBackendMessagesToUI` 의 일반 통과 경로가 백엔드 `harness` 키를
 * 그대로 컴포넌트까지 옮겼다. 감사 §4.5 가 "백엔드 응답 무검증" 으로 적은
 * 자리이고, 이 저장소는 그 패턴을 알고 있다 -- SSE 이벤트(`events.ts`)와
 * 들어오는 요청에는 `safeParse` 가 이미 걸려 있다.
 *
 * ## 무엇이 실제로 깨졌나 (2026-09-03 실측)
 *
 * 잘못된 모양 여덟 중 **다섯이 렌더를 던진다**:
 *
 *     verdict: 5           → harness.verdict?.replaceAll is not a function
 *     checks: "nope"       → (harness.checks ?? []).filter is not a function
 *     failed_checks: "a"   → failedChecks.map is not a function
 *     repair_actions: 3    → repairActions.slice is not a function
 *     harness: null        → Cannot read properties of null
 *
 * `?.` 는 보호가 되지 않는다는 점이 요점이다 -- `verdict` 가 숫자면 nullish 가
 * 아니므로 옵셔널 체이닝을 통과한 뒤 `.replaceAll` 에서 터진다.
 *
 * 페이지가 죽지는 않는다. `message.tsx` 가 메시지마다 `ErrorBoundary` 를
 * 두르므로 **그 어시스턴트 응답 하나가 "Something went wrong" 카드로
 * 대체된다.** 즉 메타데이터 필드 하나 때문에 리포트 본문이 사라진다.
 *
 * ## 왜 컴포넌트를 방어적으로 만들지 않았나
 *
 * 그러면 필드마다 방어가 흩어지고, 새 필드를 쓸 때마다 같은 판단을 다시
 * 해야 한다. 경계에서 한 번 검증하면 컴포넌트는 자기 타입을 믿을 수 있다 --
 * `lib/deep-analysis/metadata.ts` 가 같은 이유로 같은 자리에 있다.
 */

import { type HarnessMetadata, harnessMetadataSchema } from "../types";

const HARNESS_KEY = "harness";

/**
 * 메시지 메타데이터에서 하네스 상태를 읽는다.
 *
 * @returns 계약을 벗어나면 `undefined` — 호출자는 **키를 지워야 한다**
 *   (아래 `applyHarnessMetadata` 참조).
 */
export function harnessFromMessageMetadata(
  metadata: Record<string, unknown> | undefined | null
): HarnessMetadata | undefined {
  if (!metadata) {
    return;
  }
  const parsed = harnessMetadataSchema.safeParse(metadata[HARNESS_KEY]);
  return parsed.success ? parsed.data : undefined;
}

/**
 * 검증 결과를 UI 메타데이터에 반영한다.
 *
 * ⚠️ **성공하면 넣고, 실패하면 지운다.** 넣기만 하면 소용이 없다 --
 * `convertBackendMessagesToUI` 의 일반 통과 경로가 이미 원본 `harness` 값을
 * 복사해 둔 뒤이므로, 검증에 실패했을 때 아무것도 하지 않으면 **검증하지 않은
 * 값이 그대로 남는다.** 이 함수가 존재하는 이유의 절반이 그 삭제다.
 */
export function applyHarnessMetadata(
  uiMetadata: Record<string, unknown>,
  backendMetadata: Record<string, unknown> | undefined | null
): void {
  const harness = harnessFromMessageMetadata(backendMetadata);
  if (harness) {
    uiMetadata[HARNESS_KEY] = harness;
    return;
  }
  delete uiMetadata[HARNESS_KEY];
}
