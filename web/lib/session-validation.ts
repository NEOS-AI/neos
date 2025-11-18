/**
 * 세션 검증 유틸리티
 * - API routes 및 Server Components에서 세션 유효성 검증
 */
import { cookies } from 'next/headers';
import { getSession, RedisConnectionError } from './redis';

export interface SessionData {
  accessToken: string;
  refreshToken: string;
  user: any;
  createdAt: string;
  lastRefreshed?: string;
}

export interface SessionValidationResult {
  isValid: boolean;
  session: SessionData | null;
  sessionId: string | null;
  error?: string;
}

/**
 * 현재 요청의 세션 검증
 *
 * @returns 세션 검증 결과
 */
export async function validateSession(): Promise<SessionValidationResult> {
  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    // 세션 쿠키가 없음
    if (!sessionId) {
      return {
        isValid: false,
        session: null,
        sessionId: null,
        error: '세션 쿠키가 없습니다.',
      };
    }

    // Redis에서 세션 가져오기
    let session;
    try {
      session = await getSession(sessionId);
    } catch (error) {
      // Redis 연결 오류 처리
      if (error instanceof RedisConnectionError) {
        console.error('Redis connection failed during session validation:', error);

        // Redis가 다운되었을 때는 503 Service Unavailable 에러를 반환하도록
        // 세션을 삭제하지 않음 (Redis 복구 후 계속 사용 가능)
        return {
          isValid: false,
          session: null,
          sessionId,
          error: 'Redis 서버에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해주세요.',
        };
      }

      // 기타 에러
      throw error;
    }

    // 세션이 Redis에 없음 (만료 또는 삭제됨)
    if (!session) {
      // 쿠키 삭제
      cookieStore.delete('neos_session');

      return {
        isValid: false,
        session: null,
        sessionId,
        error: '세션이 만료되었거나 존재하지 않습니다.',
      };
    }

    // 필수 필드 검증
    if (!session.accessToken || !session.refreshToken) {
      cookieStore.delete('neos_session');

      return {
        isValid: false,
        session: null,
        sessionId,
        error: '세션 데이터가 유효하지 않습니다.',
      };
    }

    // 세션 유효
    return {
      isValid: true,
      session,
      sessionId,
    };
  } catch (error) {
    console.error('Unexpected session validation error:', error);

    return {
      isValid: false,
      session: null,
      sessionId: null,
      error: '세션 검증 중 예기치 않은 오류가 발생했습니다.',
    };
  }
}

/**
 * 세션 필수 검증 (없으면 401 에러)
 *
 * @returns 유효한 세션 데이터
 * @throws 세션이 유효하지 않으면 에러
 */
export async function requireSession(): Promise<{
  session: SessionData;
  sessionId: string;
}> {
  const result = await validateSession();

  if (!result.isValid || !result.session || !result.sessionId) {
    throw new Error(result.error || '인증이 필요합니다.');
  }

  return {
    session: result.session,
    sessionId: result.sessionId,
  };
}
