/**
 * CSRF 토큰을 자동으로 포함하는 fetch 래퍼
 * - CSRF 토큰 만료 시 자동 갱신 및 재시도
 */

/**
 * 쿠키에서 CSRF 토큰 가져오기
 */
function getCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') {
    return null;
  }

  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'csrf_token') {
      return value;
    }
  }
  return null;
}

/**
 * CSRF 토큰을 포함한 fetch (자동 갱신 및 재시도 포함)
 *
 * @param url - 요청 URL
 * @param options - fetch 옵션
 * @param retryOnCsrfError - CSRF 에러 시 재시도 여부 (기본: true)
 * @returns fetch Response
 */
export async function fetchWithCsrf(
  url: string,
  options: RequestInit = {},
  retryOnCsrfError: boolean = true
): Promise<Response> {
  let csrfToken = getCsrfTokenFromCookie();

  // CSRF 토큰이 없으면 먼저 가져오기
  if (!csrfToken && options.method && options.method !== 'GET') {
    await refreshCsrfToken();
    csrfToken = getCsrfTokenFromCookie();
  }

  const headers = new Headers(options.headers || {});

  // GET 요청이 아닌 경우 CSRF 토큰 추가
  if (options.method && options.method !== 'GET' && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'same-origin', // 쿠키 포함
  });

  // CSRF 토큰 에러(403) 시 갱신 후 재시도
  if (response.status === 403 && retryOnCsrfError) {
    try {
      const errorData = await response.json();

      // CSRF 토큰 에러인 경우에만 재시도
      if (errorData.code === 'INVALID_CSRF_TOKEN') {
        console.log('CSRF token expired, refreshing...');

        // CSRF 토큰 갱신
        const newToken = await refreshCsrfToken();

        if (newToken) {
          // 갱신된 토큰으로 재시도 (재시도는 1회만)
          const newHeaders = new Headers(options.headers || {});
          if (options.method && options.method !== 'GET') {
            newHeaders.set('X-CSRF-Token', newToken);
          }

          return fetch(url, {
            ...options,
            headers: newHeaders,
            credentials: 'same-origin',
          });
        }
      }

      // CSRF 에러가 아니거나 갱신 실패 시 원래 응답 반환
      // (이미 json()을 호출했으므로 새 Response 생성)
      return new Response(JSON.stringify(errorData), {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (error) {
      // JSON 파싱 실패 시 원래 응답 반환
      return response;
    }
  }

  return response;
}

/**
 * CSRF 토큰 새로고침
 */
export async function refreshCsrfToken(): Promise<string | null> {
  try {
    const response = await fetch('/api/auth/csrf');
    if (!response.ok) {
      console.error('Failed to refresh CSRF token');
      return null;
    }

    const data = await response.json();
    return data.csrfToken;
  } catch (error) {
    console.error('Error refreshing CSRF token:', error);
    return null;
  }
}
