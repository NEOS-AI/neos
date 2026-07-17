/**
 * 스트림 에러 분류 (순수 로직)
 *
 * 사용자가 정지(Stop)를 누르면 `AbortController.abort()`가 진행 중인
 * `reader.read()`를 `AbortError`로 거부시킨다. `AbortError`는 DOMException이지만
 * `instanceof Error === true`라서, 일반 에러 처리에 그대로 걸리면
 * `setStatus("error")` + 빨간 에러 토스트가 뜬다.
 *
 * **정지는 에러가 아니다.** 사용자가 의도한 정상 종료다.
 */

/**
 * 사용자/코드가 스트림을 취소해서 발생한 오류인지 판별한다.
 *
 * - `AbortError` — `AbortController.abort()`로 fetch/reader가 취소된 경우
 * - `ResponseAborted` / `AbortError` 이름을 쓰는 런타임 변종도 함께 수용한다
 */
export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }

  const name = (error as { name?: unknown }).name;
  return name === "AbortError" || name === "ResponseAborted";
}

/**
 * 이 오류를 사용자에게 에러로 표면화해야 하는가?
 *
 * 취소(abort)는 정상 종료이므로 토스트를 띄우면 안 된다.
 */
export function shouldSurfaceStreamError(error: unknown): boolean {
  return !isAbortError(error);
}
