/**
 * CSRF 토큰을 자동으로 포함하는 fetch 래퍼
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
 * CSRF 토큰을 포함한 fetch
 */
export async function fetchWithCsrf(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const csrfToken = getCsrfTokenFromCookie();

  const headers = new Headers(options.headers || {});

  // GET 요청이 아닌 경우 CSRF 토큰 추가
  if (options.method && options.method !== 'GET' && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  return fetch(url, {
    ...options,
    headers,
    credentials: 'same-origin', // 쿠키 포함
  });
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
