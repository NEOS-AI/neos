/**
 * 로깅 유틸리티
 * - 프로덕션과 개발 환경에 맞는 로깅
 * - 민감 정보 마스킹
 */

export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  WARN = 'WARN',
  ERROR = 'ERROR',
}

interface LogEntry {
  level: LogLevel;
  message: string;
  context?: Record<string, any>;
  timestamp: string;
  environment: string;
}

/**
 * 민감한 필드 목록
 */
const SENSITIVE_FIELDS = [
  'password',
  'token',
  'accessToken',
  'refreshToken',
  'access_token',
  'refresh_token',
  'apiKey',
  'api_key',
  'secret',
  'authorization',
  'cookie',
];

/**
 * 민감 정보 마스킹
 */
function maskSensitiveData(data: any): any {
  if (typeof data !== 'object' || data === null) {
    return data;
  }

  if (Array.isArray(data)) {
    return data.map(maskSensitiveData);
  }

  const masked: Record<string, any> = {};

  for (const [key, value] of Object.entries(data)) {
    const lowerKey = key.toLowerCase();

    // 민감한 필드는 마스킹
    if (SENSITIVE_FIELDS.some(field => lowerKey.includes(field.toLowerCase()))) {
      masked[key] = typeof value === 'string' && value.length > 0
        ? `${value.substring(0, 3)}***`
        : '***';
    } else if (typeof value === 'object' && value !== null) {
      masked[key] = maskSensitiveData(value);
    } else {
      masked[key] = value;
    }
  }

  return masked;
}

/**
 * 로그 출력
 */
function log(level: LogLevel, message: string, context?: Record<string, any>): void {
  const entry: LogEntry = {
    level,
    message,
    context: context ? maskSensitiveData(context) : undefined,
    timestamp: new Date().toISOString(),
    environment: process.env.NODE_ENV || 'development',
  };

  // 프로덕션 환경에서는 구조화된 JSON 로그
  if (process.env.NODE_ENV === 'production') {
    console.log(JSON.stringify(entry));
  } else {
    // 개발 환경에서는 읽기 쉬운 형식
    const prefix = `[${entry.timestamp}] [${level}]`;

    switch (level) {
      case LogLevel.DEBUG:
        console.debug(prefix, message, context || '');
        break;
      case LogLevel.INFO:
        console.info(prefix, message, context || '');
        break;
      case LogLevel.WARN:
        console.warn(prefix, message, context || '');
        break;
      case LogLevel.ERROR:
        console.error(prefix, message, context || '');
        break;
    }
  }
}

/**
 * Logger 클래스
 */
export class Logger {
  private context: string;

  constructor(context: string = 'App') {
    this.context = context;
  }

  debug(message: string, data?: Record<string, any>): void {
    log(LogLevel.DEBUG, `[${this.context}] ${message}`, data);
  }

  info(message: string, data?: Record<string, any>): void {
    log(LogLevel.INFO, `[${this.context}] ${message}`, data);
  }

  warn(message: string, data?: Record<string, any>): void {
    log(LogLevel.WARN, `[${this.context}] ${message}`, data);
  }

  error(message: string, error?: Error | unknown, data?: Record<string, any>): void {
    const errorContext = {
      ...data,
      error: error instanceof Error ? {
        name: error.name,
        message: error.message,
        stack: process.env.NODE_ENV === 'development' ? error.stack : undefined,
      } : error,
    };

    log(LogLevel.ERROR, `[${this.context}] ${message}`, errorContext);
  }
}

/**
 * 기본 로거 인스턴스
 */
export const logger = new Logger('BFF');

/**
 * 특정 컨텍스트를 위한 로거 생성
 */
export function createLogger(context: string): Logger {
  return new Logger(context);
}
