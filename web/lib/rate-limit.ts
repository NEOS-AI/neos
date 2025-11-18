/**
 * Rate Limiting 유틸리티
 * - Redis 기반 IP별 요청 횟수 제한
 * - Sliding Window 알고리즘 사용
 */
import { NextRequest } from 'next/server';
import { getRedisClient, connectRedis, RedisConnectionError } from './redis';

export interface RateLimitConfig {
  /**
   * 시간 윈도우 (초)
   */
  windowSeconds: number;

  /**
   * 윈도우당 최대 요청 수
   */
  maxRequests: number;
}

export interface RateLimitResult {
  /**
   * 요청 허용 여부
   */
  allowed: boolean;

  /**
   * 남은 요청 수
   */
  remaining: number;

  /**
   * 다음 윈도우까지 남은 시간 (초)
   */
  resetIn: number;

  /**
   * 현재 요청 수
   */
  current: number;
}

/**
 * IP 주소 가져오기
 */
export function getClientIp(request: NextRequest): string {
  // X-Forwarded-For 헤더 확인 (프록시/로드 밸런서 뒤에 있을 경우)
  const forwardedFor = request.headers.get('x-forwarded-for');
  if (forwardedFor) {
    return forwardedFor.split(',')[0].trim();
  }

  // X-Real-IP 헤더 확인
  const realIp = request.headers.get('x-real-ip');
  if (realIp) {
    return realIp;
  }

  // 직접 연결된 IP
  return request.ip || 'unknown';
}

/**
 * Rate Limiting 체크
 *
 * @param identifier 식별자 (IP 주소, 사용자 ID 등)
 * @param config Rate Limit 설정
 * @returns Rate Limit 결과
 */
export async function checkRateLimit(
  identifier: string,
  config: RateLimitConfig
): Promise<RateLimitResult> {
  try {
    await connectRedis();
    const client = getRedisClient();

    const key = `ratelimit:${identifier}`;
    const now = Date.now();
    const windowMs = config.windowSeconds * 1000;

    // Redis Pipeline 사용
    const pipeline = client.pipeline();

    // 1. 현재 윈도우 내의 요청만 유지 (오래된 요청 삭제)
    pipeline.zremrangebyscore(key, 0, now - windowMs);

    // 2. 현재 요청 수 카운트
    pipeline.zcard(key);

    // 3. 현재 요청 추가
    pipeline.zadd(key, now, `${now}`);

    // 4. TTL 설정 (자동 삭제)
    pipeline.expire(key, config.windowSeconds);

    const results = await pipeline.exec();

    if (!results) {
      throw new Error('Redis pipeline failed');
    }

    // zcard 결과 (현재 요청 수)
    const currentCount = (results[1][1] as number) || 0;

    // Rate Limit 체크
    const allowed = currentCount < config.maxRequests;
    const remaining = Math.max(0, config.maxRequests - currentCount - 1);

    // 가장 오래된 요청의 타임스탬프 가져오기 (resetIn 계산용)
    const oldestTimestamp = await client.zrange(key, 0, 0, 'WITHSCORES');
    const resetIn = oldestTimestamp.length > 1
      ? Math.ceil((parseInt(oldestTimestamp[1]) + windowMs - now) / 1000)
      : config.windowSeconds;

    return {
      allowed,
      remaining: allowed ? remaining : 0,
      resetIn: Math.max(0, resetIn),
      current: currentCount + 1,
    };
  } catch (error) {
    // Redis 연결 실패 시 요청 허용 (Fail Open)
    // 프로덕션에서는 다른 전략 사용 가능 (메모리 기반 Rate Limit 등)
    if (error instanceof RedisConnectionError) {
      console.error('Rate limit check failed due to Redis error, allowing request:', error);

      return {
        allowed: true,
        remaining: config.maxRequests,
        resetIn: config.windowSeconds,
        current: 0,
      };
    }

    // 기타 에러는 다시 throw
    throw error;
  }
}

/**
 * Rate Limit 체크 및 에러 응답 생성
 *
 * @param request NextRequest 객체
 * @param config Rate Limit 설정
 * @returns Rate Limit 결과 및 에러 Response (제한 초과 시)
 */
export async function rateLimitMiddleware(
  request: NextRequest,
  config: RateLimitConfig
): Promise<{ result: RateLimitResult; errorResponse?: Response }> {
  const ip = getClientIp(request);
  const result = await checkRateLimit(ip, config);

  if (!result.allowed) {
    const errorResponse = new Response(
      JSON.stringify({
        error: '요청 횟수 제한을 초과했습니다.',
        code: 'RATE_LIMIT_EXCEEDED',
        retryAfter: result.resetIn,
      }),
      {
        status: 429,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': result.resetIn.toString(),
          'X-RateLimit-Limit': config.maxRequests.toString(),
          'X-RateLimit-Remaining': '0',
          'X-RateLimit-Reset': result.resetIn.toString(),
        },
      }
    );

    return { result, errorResponse };
  }

  return { result };
}

/**
 * 기본 Rate Limit 설정
 */
export const RATE_LIMIT_CONFIGS = {
  // 로그인/회원가입: 15분에 5회
  auth: {
    windowSeconds: 900, // 15분
    maxRequests: 5,
  },

  // 일반 API: 1분에 60회
  api: {
    windowSeconds: 60,
    maxRequests: 60,
  },

  // CSRF 토큰: 1분에 10회
  csrf: {
    windowSeconds: 60,
    maxRequests: 10,
  },
};
