/**
 * Error logging and monitoring utilities
 */

/**
 * Error type classifications
 */
export enum ErrorType {
  NETWORK_ERROR = "NETWORK_ERROR",
  SERVER_ERROR = "SERVER_ERROR",
  CLIENT_ERROR = "CLIENT_ERROR",
  VALIDATION_ERROR = "VALIDATION_ERROR",
  AUTH_ERROR = "AUTH_ERROR",
  TIMEOUT_ERROR = "TIMEOUT_ERROR",
  ABORT_ERROR = "ABORT_ERROR",
  UNKNOWN_ERROR = "UNKNOWN_ERROR",
}

/**
 * Error context for logging
 */
export interface ErrorContext {
  context: string;
  conversationId?: string;
  messageId?: string;
  userId?: string;
  timestamp?: string;
  [key: string]: any;
}

/**
 * Classify error type based on error object
 */
export function classifyError(error: unknown): ErrorType {
  if (!error) return ErrorType.UNKNOWN_ERROR;

  // Check for AbortError (request cancellation)
  if (error instanceof Error && error.name === "AbortError") {
    return ErrorType.ABORT_ERROR;
  }

  // Check for timeout
  if (error instanceof Error && error.message.includes("timeout")) {
    return ErrorType.TIMEOUT_ERROR;
  }

  // Check for network errors
  if (
    error instanceof Error &&
    (error.message.includes("network") ||
      error.message.includes("fetch") ||
      error.message.includes("Failed to fetch"))
  ) {
    return ErrorType.NETWORK_ERROR;
  }

  // Check for Axios errors (if using axios)
  if (typeof error === "object" && error !== null && "response" in error) {
    const axiosError = error as any;

    if (!axiosError.response) {
      // No response means network error
      return ErrorType.NETWORK_ERROR;
    }

    const status = axiosError.response?.status;
    if (status >= 400 && status < 500) {
      if (status === 401 || status === 403) {
        return ErrorType.AUTH_ERROR;
      }
      return ErrorType.CLIENT_ERROR;
    }

    if (status >= 500) {
      return ErrorType.SERVER_ERROR;
    }
  }

  // Check for validation errors
  if (error instanceof Error && error.message.includes("validation")) {
    return ErrorType.VALIDATION_ERROR;
  }

  return ErrorType.UNKNOWN_ERROR;
}

/**
 * Get user-friendly error message based on error type
 */
export function getUserFriendlyMessage(errorType: ErrorType): string {
  switch (errorType) {
    case ErrorType.NETWORK_ERROR:
      return "Network connection error. Please check your internet connection and try again.";

    case ErrorType.SERVER_ERROR:
      return "Server error occurred. Please try again later.";

    case ErrorType.CLIENT_ERROR:
      return "Invalid request. Please check your input and try again.";

    case ErrorType.VALIDATION_ERROR:
      return "Input validation failed. Please check your message.";

    case ErrorType.AUTH_ERROR:
      return "Authentication error. Please log in again.";

    case ErrorType.TIMEOUT_ERROR:
      return "Request timed out. Please try again.";

    case ErrorType.ABORT_ERROR:
      return "Request was cancelled.";

    case ErrorType.UNKNOWN_ERROR:
    default:
      return "An unexpected error occurred. Please try again.";
  }
}

/**
 * Log error to console (can be extended to send to monitoring service)
 */
export function logError(error: unknown, context: ErrorContext): void {
  const errorType = classifyError(error);
  const timestamp = new Date().toISOString();

  const errorLog = {
    timestamp,
    errorType,
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : undefined,
    context: {
      ...context,
      timestamp,
    },
  };

  // Log to console (development)
  if (process.env.NODE_ENV === "development") {
    console.error("[Error Logger]", errorLog);
  }

  // TODO: Send to monitoring service (e.g., Sentry, LogRocket, etc.)
  // if (process.env.NODE_ENV === "production") {
  //   sendToMonitoringService(errorLog);
  // }
}

/**
 * Retry configuration
 */
export interface RetryConfig {
  maxRetries: number;
  baseDelay: number; // milliseconds
  maxDelay: number; // milliseconds
  shouldRetry?: (error: unknown) => boolean;
}

const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  baseDelay: 1000, // 1 second
  maxDelay: 10000, // 10 seconds
  shouldRetry: (error: unknown) => {
    const errorType = classifyError(error);
    // Only retry network errors and server errors
    return errorType === ErrorType.NETWORK_ERROR || errorType === ErrorType.SERVER_ERROR;
  },
};

/**
 * Exponential backoff delay calculation
 */
function calculateBackoffDelay(retryCount: number, config: RetryConfig): number {
  const exponentialDelay = config.baseDelay * Math.pow(2, retryCount);
  const jitter = Math.random() * 0.3 * exponentialDelay; // Add up to 30% jitter
  const delay = exponentialDelay + jitter;
  return Math.min(delay, config.maxDelay);
}

/**
 * Retry function with exponential backoff
 */
export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  config: Partial<RetryConfig> = {}
): Promise<T> {
  const retryConfig = { ...DEFAULT_RETRY_CONFIG, ...config };
  let lastError: unknown;

  for (let attempt = 0; attempt <= retryConfig.maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      // Don't retry if this is the last attempt
      if (attempt === retryConfig.maxRetries) {
        break;
      }

      // Check if we should retry this error
      const shouldRetry = retryConfig.shouldRetry
        ? retryConfig.shouldRetry(error)
        : true;

      if (!shouldRetry) {
        throw error;
      }

      // Calculate delay and wait
      const delay = calculateBackoffDelay(attempt, retryConfig);

      if (process.env.NODE_ENV === "development") {
        console.log(
          `[Retry] Attempt ${attempt + 1}/${retryConfig.maxRetries} failed. Retrying in ${delay.toFixed(0)}ms...`
        );
      }

      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  // All retries exhausted
  throw lastError;
}

/**
 * Create an error handler for a specific context
 */
export function createErrorHandler(baseContext: Partial<ErrorContext>) {
  return (error: unknown, additionalContext?: Partial<ErrorContext>) => {
    const fullContext = { ...baseContext, ...additionalContext } as ErrorContext;
    logError(error, fullContext);

    const errorType = classifyError(error);
    const userMessage = getUserFriendlyMessage(errorType);

    return {
      errorType,
      userMessage,
      originalError: error,
    };
  };
}
