/**
 * CSRF (Cross-Site Request Forgery) 보호 유틸리티
 */
import crypto from 'crypto';

/**
 * CSRF 토큰 생성
 */
export function generateCsrfToken(): string {
  return crypto.randomBytes(32).toString('base64url');
}

/**
 * CSRF 토큰 검증 (타이밍 공격 방지)
 */
export function verifyCsrfToken(token1: string, token2: string): boolean {
  if (!token1 || !token2) {
    return false;
  }

  if (token1.length !== token2.length) {
    return false;
  }

  // constant-time comparison
  return crypto.timingSafeEqual(
    Buffer.from(token1),
    Buffer.from(token2)
  );
}

/**
 * 서명된 CSRF 토큰 생성
 */
export function createSignedCsrfToken(sessionId: string, secret: string): string {
  const token = generateCsrfToken();
  const timestamp = Date.now().toString();

  const message = `${token}:${sessionId}:${timestamp}`;
  const signature = crypto
    .createHmac('sha256', secret)
    .update(message)
    .digest('hex');

  return `${token}:${timestamp}:${signature}`;
}

/**
 * 서명된 CSRF 토큰 검증
 */
export function verifySignedCsrfToken(
  csrfToken: string,
  sessionId: string,
  secret: string,
  maxAgeMs: number = 3600000 // 1시간
): boolean {
  try {
    const parts = csrfToken.split(':');
    if (parts.length !== 3) {
      return false;
    }

    const [token, timestamp, signature] = parts;

    // 타임스탬프 검증
    const tokenTime = parseInt(timestamp, 10);
    const currentTime = Date.now();

    if (currentTime - tokenTime > maxAgeMs) {
      return false; // 토큰 만료
    }

    // 서명 재생성
    const message = `${token}:${sessionId}:${timestamp}`;
    const expectedSignature = crypto
      .createHmac('sha256', secret)
      .update(message)
      .digest('hex');

    // 서명 비교 (타이밍 공격 방지)
    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expectedSignature)
    );
  } catch (error) {
    return false;
  }
}
