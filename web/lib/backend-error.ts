/**
 * 백엔드 오류 본문 → 사람이 읽을 문장.
 *
 * 서버(`lib/backend-api.ts`)와 브라우저(`features/coding/api/coding-api.ts`)가
 * **같은** 규칙을 쓰도록 여기 한 곳에 둔다. 서버 임포트가 없어야 한다.
 *
 * 백엔드 `detail` 의 세 모양:
 * 1. 문자열                    -- 일반 `HTTPException`
 * 2. `{code, message}`         -- 코딩 핸들러 `_error_detail()`
 * 3. `[{loc, msg, type}, ...]` -- FastAPI 422 검증 오류
 *
 * 예전에는 `detail` 을 그대로 `new Error(detail)` 에 넣어 2·3 이
 * `"[object Object]"` 로 사용자에게 보였다.
 */

type Loose = Record<string, unknown>;

function isObject(value: unknown): value is Loose {
  return typeof value === "object" && value !== null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function validationMessage(item: unknown): string | null {
  if (!isObject(item)) {
    return null;
  }
  const msg = nonEmptyString(item.msg);
  if (!msg) {
    return null;
  }
  // loc 의 첫 칸은 "body"/"query" 같은 위치라 필드명이 아니다.
  const loc = Array.isArray(item.loc) ? item.loc.slice(1) : [];
  const field = loc.filter((part) => typeof part === "string").join(".");
  return field ? `${field}: ${msg}` : msg;
}

function detailMessage(detail: unknown): string | null {
  const text = nonEmptyString(detail);
  if (text) {
    return text;
  }
  if (Array.isArray(detail)) {
    const parts = detail.map(validationMessage).filter(Boolean);
    return parts.length > 0 ? parts.join("; ") : null;
  }
  if (isObject(detail)) {
    return nonEmptyString(detail.message);
  }
  return null;
}

export function backendErrorMessage(body: unknown, fallback: string): string {
  if (!isObject(body)) {
    return fallback;
  }
  return (
    detailMessage(body.detail) ??
    nonEmptyString(body.error) ??
    nonEmptyString(body.message) ??
    fallback
  );
}

export function backendErrorCode(body: unknown): string | undefined {
  if (!isObject(body)) {
    return undefined;
  }
  const detail = body.detail;
  if (isObject(detail) && !Array.isArray(detail)) {
    const code = nonEmptyString(detail.code);
    if (code) {
      return code;
    }
  }
  return nonEmptyString(body.code) ?? undefined;
}
