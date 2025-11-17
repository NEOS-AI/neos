/**
 * Tests for error logging utilities
 */

import {
  ErrorType,
  classifyError,
  getUserFriendlyMessage,
  logError,
  retryWithBackoff,
  createErrorHandler,
} from '../error-logger';

describe('classifyError', () => {
  it('should classify AbortError', () => {
    const error = new Error('User aborted');
    error.name = 'AbortError';
    expect(classifyError(error)).toBe(ErrorType.ABORT_ERROR);
  });

  it('should classify timeout errors', () => {
    const error = new Error('Request timeout');
    expect(classifyError(error)).toBe(ErrorType.TIMEOUT_ERROR);
  });

  it('should classify network errors', () => {
    const error = new Error('Failed to fetch');
    expect(classifyError(error)).toBe(ErrorType.NETWORK_ERROR);
  });

  it('should classify auth errors from axios', () => {
    const error = {
      response: {
        status: 401,
      },
    };
    expect(classifyError(error)).toBe(ErrorType.AUTH_ERROR);
  });

  it('should classify forbidden errors', () => {
    const error = {
      response: {
        status: 403,
      },
    };
    expect(classifyError(error)).toBe(ErrorType.AUTH_ERROR);
  });

  it('should classify client errors', () => {
    const error = {
      response: {
        status: 400,
      },
    };
    expect(classifyError(error)).toBe(ErrorType.CLIENT_ERROR);
  });

  it('should classify server errors', () => {
    const error = {
      response: {
        status: 500,
      },
    };
    expect(classifyError(error)).toBe(ErrorType.SERVER_ERROR);
  });

  it('should classify validation errors', () => {
    const error = new Error('Validation failed');
    expect(classifyError(error)).toBe(ErrorType.VALIDATION_ERROR);
  });

  it('should classify network errors without response', () => {
    const error = {
      response: undefined,
      isAxiosError: true,
    };
    expect(classifyError(error)).toBe(ErrorType.NETWORK_ERROR);
  });

  it('should return UNKNOWN_ERROR for unclassified errors', () => {
    const error = new Error('Random error');
    expect(classifyError(error)).toBe(ErrorType.UNKNOWN_ERROR);
  });

  it('should handle null/undefined', () => {
    expect(classifyError(null)).toBe(ErrorType.UNKNOWN_ERROR);
    expect(classifyError(undefined)).toBe(ErrorType.UNKNOWN_ERROR);
  });
});

describe('getUserFriendlyMessage', () => {
  it('should return friendly message for network errors', () => {
    const message = getUserFriendlyMessage(ErrorType.NETWORK_ERROR);
    expect(message).toContain('Network');
    expect(message).toContain('internet');
  });

  it('should return friendly message for server errors', () => {
    const message = getUserFriendlyMessage(ErrorType.SERVER_ERROR);
    expect(message).toContain('Server');
    expect(message).toContain('later');
  });

  it('should return friendly message for client errors', () => {
    const message = getUserFriendlyMessage(ErrorType.CLIENT_ERROR);
    expect(message).toContain('Invalid');
  });

  it('should return friendly message for validation errors', () => {
    const message = getUserFriendlyMessage(ErrorType.VALIDATION_ERROR);
    expect(message).toContain('validation');
  });

  it('should return friendly message for auth errors', () => {
    const message = getUserFriendlyMessage(ErrorType.AUTH_ERROR);
    expect(message).toContain('Authentication');
  });

  it('should return friendly message for timeout errors', () => {
    const message = getUserFriendlyMessage(ErrorType.TIMEOUT_ERROR);
    expect(message).toContain('timeout');
  });

  it('should return friendly message for abort errors', () => {
    const message = getUserFriendlyMessage(ErrorType.ABORT_ERROR);
    expect(message).toContain('cancelled');
  });

  it('should return generic message for unknown errors', () => {
    const message = getUserFriendlyMessage(ErrorType.UNKNOWN_ERROR);
    expect(message).toContain('unexpected');
  });
});

describe('logError', () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it('should log error with context', () => {
    const error = new Error('Test error');
    const context = { context: 'testFunction', userId: 'user123' };

    logError(error, context);

    expect(consoleErrorSpy).toHaveBeenCalled();
    const loggedData = consoleErrorSpy.mock.calls[0][1];
    expect(loggedData.message).toBe('Test error');
    expect(loggedData.context.context).toBe('testFunction');
    expect(loggedData.context.userId).toBe('user123');
  });

  it('should include error stack', () => {
    const error = new Error('Test error');
    const context = { context: 'testFunction' };

    logError(error, context);

    const loggedData = consoleErrorSpy.mock.calls[0][1];
    expect(loggedData.stack).toBeDefined();
  });

  it('should handle non-Error objects', () => {
    const error = 'String error';
    const context = { context: 'testFunction' };

    logError(error, context);

    const loggedData = consoleErrorSpy.mock.calls[0][1];
    expect(loggedData.message).toBe('String error');
  });

  it('should include timestamp', () => {
    const error = new Error('Test error');
    const context = { context: 'testFunction' };

    logError(error, context);

    const loggedData = consoleErrorSpy.mock.calls[0][1];
    expect(loggedData.timestamp).toBeDefined();
    expect(loggedData.context.timestamp).toBeDefined();
  });
});

describe('retryWithBackoff', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should succeed on first try', async () => {
    const mockFn = jest.fn().mockResolvedValue('success');

    const result = await retryWithBackoff(mockFn);

    expect(result).toBe('success');
    expect(mockFn).toHaveBeenCalledTimes(1);
  });

  it('should retry on failure', async () => {
    const mockFn = jest
      .fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValue('success');

    const promise = retryWithBackoff(mockFn, { maxRetries: 3 });

    // Advance timers for retry delays
    await jest.advanceTimersByTimeAsync(1000);
    await jest.advanceTimersByTimeAsync(2000);

    const result = await promise;

    expect(result).toBe('success');
    expect(mockFn).toHaveBeenCalledTimes(2);
  });

  it('should throw after max retries', async () => {
    const error = new Error('Persistent error');
    const mockFn = jest.fn().mockRejectedValue(error);

    const promise = retryWithBackoff(mockFn, { maxRetries: 2 });

    // Advance timers for all retry attempts
    await jest.advanceTimersByTimeAsync(10000);

    await expect(promise).rejects.toThrow('Persistent error');
    expect(mockFn).toHaveBeenCalledTimes(3); // Initial + 2 retries
  });

  it('should not retry if shouldRetry returns false', async () => {
    const error = new Error('Client error');
    const mockFn = jest.fn().mockRejectedValue(error);

    const promise = retryWithBackoff(mockFn, {
      maxRetries: 3,
      shouldRetry: () => false,
    });

    await expect(promise).rejects.toThrow('Client error');
    expect(mockFn).toHaveBeenCalledTimes(1); // No retries
  });

  it('should use exponential backoff', async () => {
    const mockFn = jest
      .fn()
      .mockRejectedValueOnce(new Error('Error 1'))
      .mockRejectedValueOnce(new Error('Error 2'))
      .mockResolvedValue('success');

    const promise = retryWithBackoff(mockFn, {
      maxRetries: 3,
      baseDelay: 1000,
    });

    // First retry should be ~1000ms
    await jest.advanceTimersByTimeAsync(1500);
    expect(mockFn).toHaveBeenCalledTimes(2);

    // Second retry should be ~2000ms (exponential)
    await jest.advanceTimersByTimeAsync(2500);
    expect(mockFn).toHaveBeenCalledTimes(3);

    await promise;
  });
});

describe('createErrorHandler', () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it('should create error handler with base context', () => {
    const handler = createErrorHandler({ context: 'baseContext', userId: 'user123' });
    const error = new Error('Test error');

    const result = handler(error);

    expect(result.errorType).toBeDefined();
    expect(result.userMessage).toBeDefined();
    expect(result.originalError).toBe(error);
  });

  it('should merge additional context', () => {
    const handler = createErrorHandler({ context: 'baseContext' });
    const error = new Error('Test error');

    handler(error, { conversationId: 'conv123' });

    const loggedData = consoleErrorSpy.mock.calls[0][1];
    expect(loggedData.context.context).toBe('baseContext');
    expect(loggedData.context.conversationId).toBe('conv123');
  });

  it('should return classified error type', () => {
    const handler = createErrorHandler({ context: 'test' });
    const error = new Error('Failed to fetch');

    const result = handler(error);

    expect(result.errorType).toBe(ErrorType.NETWORK_ERROR);
    expect(result.userMessage).toContain('Network');
  });
});
