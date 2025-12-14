/**
 * Authentication utilities
 * - 실제 BFF API를 호출하여 인증 처리
 * - 쿠키 기반 세션 관리 (HTTP-only cookies)
 * - CSRF 보호
 */
import { fetchWithCsrf } from './fetch-with-csrf';

export interface User {
  user_id: string;
  email: string;
  username: string;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  last_login?: string;
}

/**
 * 로그인
 */
export async function login(email: string, password: string): Promise<User> {
  const response = await fetchWithCsrf('/api/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || '로그인에 실패했습니다.');
  }

  return data.user;
}

/**
 * 회원가입
 */
export async function register(
  email: string,
  password: string,
  username?: string
): Promise<{ user_id: string; email: string; username: string }> {
  const response = await fetchWithCsrf('/api/auth/register', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password, username }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || '회원가입에 실패했습니다.');
  }

  return data.data;
}

/**
 * 로그아웃
 */
export async function logout(): Promise<void> {
  const response = await fetchWithCsrf('/api/auth/logout', {
    method: 'POST',
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || '로그아웃에 실패했습니다.');
  }
}

/**
 * 현재 사용자 정보 가져오기
 */
export async function getCurrentUser(): Promise<User | null> {
  try {
    const response = await fetch('/api/auth/me', {
      method: 'GET',
    });

    if (!response.ok) {
      if (response.status === 401) {
        return null; // 인증되지 않음
      }
      throw new Error('사용자 정보를 가져올 수 없습니다.');
    }

    const data = await response.json();
    return data.user;
  } catch (error) {
    console.error('Get current user error:', error);
    return null;
  }
}

/**
 * 인증 여부 확인
 */
export async function isAuthenticated(): Promise<boolean> {
  const user = await getCurrentUser();
  return user !== null;
}

// 레거시 호환성을 위한 함수들 (기존 코드와의 호환성 유지)
export function getSession(): null {
  // 쿠키 기반 세션으로 변경되어 더 이상 localStorage 사용 안 함
  console.warn('getSession is deprecated. Use getCurrentUser() instead.');
  return null;
}

export function saveSession(): void {
  // 쿠키 기반 세션으로 변경되어 더 이상 사용 안 함
  console.warn('saveSession is deprecated. Session is managed via HTTP-only cookies.');
}

export function clearSession(): void {
  // 쿠키 기반 세션으로 변경되어 더 이상 사용 안 함
  console.warn('clearSession is deprecated. Use logout() instead.');
}

export function getAuthHeaders(): Record<string, string> {
  // BFF 패턴으로 변경되어 클라이언트에서 직접 토큰 관리하지 않음
  // 모든 요청은 /api 경로를 통해 BFF로 프록시됨
  return {};
}

/**
 * Google OAuth 로그인
 */
export async function loginWithGoogle(googleToken: string): Promise<User> {
  const response = await fetchWithCsrf('/api/auth/google', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ google_token: googleToken }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || 'Google 로그인에 실패했습니다.');
  }

  return data.user;
}
