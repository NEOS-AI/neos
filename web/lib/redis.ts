/**
 * Redis 클라이언트 (세션 관리용)
 */
import Redis from 'ioredis';

// Redis 클라이언트 싱글톤
let redisClient: Redis | null = null;

export function getRedisClient(): Redis {
  if (!redisClient) {
    const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379';

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
  if (client.status !== 'ready') {
    await client.connect();
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
      return null;
    }

    return JSON.parse(data);
  } catch (error) {
    console.error('Error getting session:', error);
    return null;
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
