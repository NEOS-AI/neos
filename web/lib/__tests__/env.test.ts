/**
 * 환경 변수 검증 테스트
 */

describe('Environment Variable Validation', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  describe('validateRequiredEnvVar', () => {
    test('should throw error when JWT_SECRET_KEY is not set', () => {
      delete process.env.JWT_SECRET_KEY;

      expect(() => {
        require('../env');
      }).toThrow('필수 환경 변수 JWT_SECRET_KEY이(가) 설정되지 않았습니다');
    });

    test('should throw error when JWT_SECRET_KEY is empty string', () => {
      process.env.JWT_SECRET_KEY = '   ';

      expect(() => {
        require('../env');
      }).toThrow('필수 환경 변수 JWT_SECRET_KEY이(가) 설정되지 않았습니다');
    });

    test('should throw error for dangerous default values', () => {
      const dangerousValues = [
        'your-secret-key-change-this',
        'change-this',
        'secret',
        'password',
        'test',
      ];

      dangerousValues.forEach((dangerousValue) => {
        process.env.JWT_SECRET_KEY = dangerousValue;

        expect(() => {
          jest.resetModules();
          require('../env');
        }).toThrow('안전하지 않은 기본값을 사용하고 있습니다');
      });
    });

    test('should accept valid JWT_SECRET_KEY', () => {
      process.env.JWT_SECRET_KEY = 'valid-secure-key-with-sufficient-entropy-12345678';

      expect(() => {
        const env = require('../env');
        expect(env.JWT_SECRET_KEY).toBe('valid-secure-key-with-sufficient-entropy-12345678');
      }).not.toThrow();
    });
  });

  describe('Environment constants', () => {
    beforeEach(() => {
      process.env.JWT_SECRET_KEY = 'valid-test-key-12345678';
    });

    test('should use default BACKEND_URL when not set', () => {
      delete process.env.BACKEND_URL;
      jest.resetModules();
      const env = require('../env');

      expect(env.BACKEND_URL).toBe('http://localhost:8518');
    });

    test('should use custom BACKEND_URL when set', () => {
      process.env.BACKEND_URL = 'https://api.example.com';
      jest.resetModules();
      const env = require('../env');

      expect(env.BACKEND_URL).toBe('https://api.example.com');
    });

    test('should use default REDIS_URL when not set', () => {
      delete process.env.REDIS_URL;
      jest.resetModules();
      const env = require('../env');

      expect(env.REDIS_URL).toBe('redis://localhost:6379');
    });

    test('should detect production environment', () => {
      process.env.NODE_ENV = 'production';
      jest.resetModules();
      const env = require('../env');

      expect(env.IS_PRODUCTION).toBe(true);
      expect(env.IS_DEVELOPMENT).toBe(false);
    });

    test('should detect development environment', () => {
      process.env.NODE_ENV = 'development';
      jest.resetModules();
      const env = require('../env');

      expect(env.IS_PRODUCTION).toBe(false);
      expect(env.IS_DEVELOPMENT).toBe(true);
    });
  });

  describe('validateEnvironment', () => {
    test('should log success when all validations pass', () => {
      process.env.JWT_SECRET_KEY = 'valid-secure-key-12345678';
      const consoleSpy = jest.spyOn(console, 'log');
      jest.resetModules();
      const env = require('../env');

      env.validateEnvironment();

      expect(consoleSpy).toHaveBeenCalledWith('🔍 환경 변수 검증 중...');
      expect(consoleSpy).toHaveBeenCalledWith('✅ JWT_SECRET_KEY: 설정됨');
      expect(consoleSpy).toHaveBeenCalledWith('✅ 환경 변수 검증 완료\n');
    });

    test('should warn about missing BACKEND_URL in production', () => {
      process.env.JWT_SECRET_KEY = 'valid-secure-key-12345678';
      process.env.NODE_ENV = 'production';
      delete process.env.BACKEND_URL;

      const consoleWarnSpy = jest.spyOn(console, 'warn');
      jest.resetModules();
      const env = require('../env');

      env.validateEnvironment();

      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('BACKEND_URL이 설정되지 않았습니다')
      );
    });
  });
});
