/**
 * 환경 변수 검증 및 관리
 * - 필수 환경 변수가 없으면 서버 시작 실패
 */

/**
 * 필수 환경 변수 검증
 */
function validateRequiredEnvVar(name: string, value: string | undefined): string {
  if (!value || value.trim() === '') {
    throw new Error(
      `❌ 필수 환경 변수 ${name}이(가) 설정되지 않았습니다. ` +
      `.env.local 파일을 확인하세요.`
    );
  }

  // 기본값 경고
  const dangerousDefaults = [
    'your-secret-key-change-this',
    'change-this',
    'secret',
    'password',
    'test'
  ];

  if (dangerousDefaults.some(d => value.toLowerCase().includes(d))) {
    throw new Error(
      `❌ 환경 변수 ${name}이(가) 안전하지 않은 기본값을 사용하고 있습니다. ` +
      `프로덕션 환경에서는 안전한 값으로 변경하세요.`
    );
  }

  return value;
}

/**
 * JWT Secret Key (필수)
 * - CSRF 토큰 서명에도 사용
 */
export const JWT_SECRET_KEY = validateRequiredEnvVar(
  'JWT_SECRET_KEY',
  process.env.JWT_SECRET_KEY
);

/**
 * Backend API URL (기본값 허용)
 */
export const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8518';

/**
 * Redis URL (기본값 허용)
 */
export const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';

/**
 * 프로덕션 환경 여부
 */
export const IS_PRODUCTION = process.env.NODE_ENV === 'production';

/**
 * 개발 환경 여부
 */
export const IS_DEVELOPMENT = process.env.NODE_ENV === 'development';

/**
 * 환경 변수 검증 (서버 시작 시 호출)
 */
export function validateEnvironment(): void {
  console.log('🔍 환경 변수 검증 중...');

  // JWT Secret 검증
  try {
    validateRequiredEnvVar('JWT_SECRET_KEY', process.env.JWT_SECRET_KEY);
    console.log('✅ JWT_SECRET_KEY: 설정됨');
  } catch (error) {
    console.error(error);
    throw error;
  }

  // 프로덕션 환경 추가 검증
  if (IS_PRODUCTION) {
    if (!process.env.BACKEND_URL) {
      console.warn('⚠️  BACKEND_URL이 설정되지 않았습니다. 기본값 사용.');
    }

    if (!process.env.REDIS_URL) {
      console.warn('⚠️  REDIS_URL이 설정되지 않았습니다. 기본값 사용.');
    }
  }

  console.log('✅ 환경 변수 검증 완료\n');
}
