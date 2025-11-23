/**
 * Redis 클라이언트 (세션 관리용)
 * - 에러 처리 개선: Redis 연결 실패와 세션 없음을 구분
 */
import Redis from 'ioredis';
import { REDIS_URL } from './env';

// Custom Errors
export class RedisConnectionError extends Error {
  constructor(message: string, public originalError?: any) {
    super(message);
    this.name = 'RedisConnectionError';
  }
}

export class SessionNotFoundError extends Error {
  constructor(sessionId: string) {
    super(`Session not found: ${sessionId}`);
    this.name = 'SessionNotFoundError';
  }
}

// Redis 클라이언트 싱글톤
let redisClient: Redis | null = null;

export function getRedisClient(): Redis {
  if (!redisClient) {
    const redisUrl = REDIS_URL;

    redisClient = new Redis(redisUrl, {
      maxRetriesPerRequest: 3,
      retryStrategy(times) {
        const delay = Math.min(times * 50, 2000);
        return delay;
      },
      lazyConnect: true,
    });

    redisClient.on('error', (err) => {
      console.error('Redis Client Error:', err);
    });

    redisClient.on('connect', () => {
      console.log('Redis Client Connected');
    });
  }

  return redisClient;
}

export async function connectRedis(): Promise<void> {
  const client = getRedisClient();
  // Only connect if the client is disconnected or ended
  if (client.status === 'wait' || client.status === 'end' || client.status === 'close') {
    await client.connect();
  }
  // If already connecting or ready, wait for it to be ready
  if (client.status === 'connecting') {
    await new Promise<void>((resolve) => {
      client.once('ready', () => resolve());
    });
  }
}

export async function disconnectRedis(): Promise<void> {
  if (redisClient) {
    await redisClient.quit();
    redisClient = null;
  }
}

// Redis에서 세션 데이터 가져오기
export async function getSession(sessionId: string): Promise<any | null> {
  try {
    await connectRedis();
    const client = getRedisClient();
    const data = await client.get(`session:${sessionId}`);

    if (!data) {
      // 세션이 없음 (정상적인 경우: 만료 또는 존재하지 않음)
      return null;
    }

    return JSON.parse(data);
  } catch (error: any) {
    // Redis 연결 오류 (비정상적인 경우)
    console.error('Redis connection error while getting session:', error);

    // Redis 연결 에러를 throw하여 상위에서 처리
    throw new RedisConnectionError(
      'Redis 서버에 연결할 수 없습니다.',
      error
    );
  }
}

// Redis에 세션 데이터 저장
export async function setSession(
  sessionId: string,
  data: any,
  expiresIn: number = 604800 // 7일 (초 단위)
): Promise<void> {
  try {
    await connectRedis();
    const client = getRedisClient();
    await client.setex(
      `session:${sessionId}`,
      expiresIn,
      JSON.stringify(data)
    );
  } catch (error) {
    console.error('Error setting session:', error);
    throw error;
  }
}

// Redis에서 세션 삭제
export async function deleteSession(sessionId: string): Promise<void> {
  try {
    await connectRedis();
    const client = getRedisClient();
    await client.del(`session:${sessionId}`);
  } catch (error) {
    console.error('Error deleting session:', error);
    throw error;
  }
}

// 세션 만료 시간 업데이트
export async function refreshSession(
  sessionId: string,
  expiresIn: number = 604800
): Promise<void> {
  try {
    await connectRedis();
    const client = getRedisClient();
    await client.expire(`session:${sessionId}`, expiresIn);
  } catch (error) {
    console.error('Error refreshing session:', error);
    throw error;
  }
}
