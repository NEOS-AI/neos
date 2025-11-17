/**
 * Input validation and sanitization utilities
 */

import { INPUT_VALIDATION, PERFORMANCE, UI_DIMENSIONS } from './constants';

/**
 * Input validation constants
 * @deprecated Use INPUT_VALIDATION, PERFORMANCE, and UI_DIMENSIONS from './constants' instead
 */
export const INPUT_CONSTANTS = {
  MIN_MESSAGE_LENGTH: INPUT_VALIDATION.MIN_MESSAGE_LENGTH,
  MAX_MESSAGE_LENGTH: INPUT_VALIDATION.MAX_MESSAGE_LENGTH,
  MAX_TITLE_LENGTH: INPUT_VALIDATION.MAX_TITLE_LENGTH,
  DEBOUNCE_DELAY_MS: PERFORMANCE.DEBOUNCE_DELAY_MS,
  MAX_TEXTAREA_HEIGHT_PX: UI_DIMENSIONS.INPUT_MAX_HEIGHT_PX,
  CONVERSATION_CREATION_DELAY_MS: PERFORMANCE.CONVERSATION_CREATION_DELAY_MS,
} as const;

/**
 * Validation result
 */
export interface ValidationResult {
  isValid: boolean;
  error?: string;
  sanitized?: string;
}

/**
 * Validate message length
 */
export function validateMessageLength(content: string): ValidationResult {
  const trimmed = content.trim();

  if (trimmed.length < INPUT_CONSTANTS.MIN_MESSAGE_LENGTH) {
    return {
      isValid: false,
      error: "Message cannot be empty",
    };
  }

  if (trimmed.length > INPUT_CONSTANTS.MAX_MESSAGE_LENGTH) {
    return {
      isValid: false,
      error: `Message is too long. Maximum ${INPUT_CONSTANTS.MAX_MESSAGE_LENGTH.toLocaleString()} characters allowed (currently ${trimmed.length.toLocaleString()})`,
    };
  }

  return {
    isValid: true,
    sanitized: trimmed,
  };
}

/**
 * Validate conversation title
 */
export function validateTitle(title: string): ValidationResult {
  const trimmed = title.trim();

  if (trimmed.length === 0) {
    return {
      isValid: false,
      error: "Title cannot be empty",
    };
  }

  if (trimmed.length > INPUT_CONSTANTS.MAX_TITLE_LENGTH) {
    return {
      isValid: false,
      error: `Title is too long. Maximum ${INPUT_CONSTANTS.MAX_TITLE_LENGTH} characters allowed`,
    };
  }

  return {
    isValid: true,
    sanitized: trimmed,
  };
}

/**
 * Sanitize user input to prevent XSS attacks
 *
 * Note: This is a basic sanitization for display purposes.
 * The markdown renderer (react-markdown) should also have its own security measures.
 * For production, consider using a library like DOMPurify.
 */
export function sanitizeInput(input: string): string {
  // Trim whitespace
  let sanitized = input.trim();

  // Remove null bytes
  sanitized = sanitized.replace(/\0/g, "");

  // Limit consecutive newlines (max 3)
  sanitized = sanitized.replace(/\n{4,}/g, "\n\n\n");

  // Remove other control characters except newlines and tabs
  sanitized = sanitized.replace(/[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]/g, "");

  return sanitized;
}

/**
 * Sanitize markdown content before rendering
 *
 * This is a basic implementation. For production use, integrate with DOMPurify:
 *
 * ```typescript
 * import DOMPurify from 'isomorphic-dompurify';
 *
 * export function sanitizeMarkdown(markdown: string): string {
 *   return DOMPurify.sanitize(markdown, {
 *     ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'u', 'code', 'pre', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'],
 *     ALLOWED_ATTR: ['href', 'title', 'target', 'rel'],
 *   });
 * }
 * ```
 */
export function sanitizeMarkdown(markdown: string): string {
  // For now, just use basic sanitization
  // In production, integrate with DOMPurify (see comment above)
  return sanitizeInput(markdown);
}

/**
 * Check if content might contain harmful patterns
 */
export function checkForHarmfulPatterns(content: string): ValidationResult {
  // Check for potential script injection attempts
  const scriptPattern = /<script[\s\S]*?>[\s\S]*?<\/script>/gi;
  if (scriptPattern.test(content)) {
    return {
      isValid: false,
      error: "Content contains potentially harmful patterns",
    };
  }

  // Check for excessive HTML tags (might be injection attempt)
  const htmlTagCount = (content.match(/<[^>]+>/g) || []).length;
  if (htmlTagCount > 50) {
    return {
      isValid: false,
      error: "Content contains excessive HTML tags",
    };
  }

  return {
    isValid: true,
  };
}

/**
 * Comprehensive input validation
 */
export function validateInput(content: string): ValidationResult {
  // First, validate length
  const lengthValidation = validateMessageLength(content);
  if (!lengthValidation.isValid) {
    return lengthValidation;
  }

  // Check for harmful patterns
  const harmfulPatternCheck = checkForHarmfulPatterns(content);
  if (!harmfulPatternCheck.isValid) {
    return harmfulPatternCheck;
  }

  // Sanitize the input
  const sanitized = sanitizeInput(lengthValidation.sanitized!);

  return {
    isValid: true,
    sanitized,
  };
}

/**
 * Rate limiting helper (client-side)
 */
export class RateLimiter {
  private lastCallTime: number = 0;
  private callCount: number = 0;
  private readonly windowMs: number;
  private readonly maxCalls: number;

  constructor(maxCalls: number, windowMs: number) {
    this.maxCalls = maxCalls;
    this.windowMs = windowMs;
  }

  /**
   * Check if action is allowed
   */
  isAllowed(): boolean {
    const now = Date.now();

    // Reset if window has passed
    if (now - this.lastCallTime > this.windowMs) {
      this.callCount = 0;
      this.lastCallTime = now;
    }

    // Check if we've exceeded the limit
    if (this.callCount >= this.maxCalls) {
      return false;
    }

    this.callCount++;
    this.lastCallTime = now;
    return true;
  }

  /**
   * Get time until next allowed call (in ms)
   */
  getTimeUntilReset(): number {
    const timeSinceLastCall = Date.now() - this.lastCallTime;
    const timeRemaining = Math.max(0, this.windowMs - timeSinceLastCall);
    return timeRemaining;
  }

  /**
   * Reset the rate limiter
   */
  reset(): void {
    this.callCount = 0;
    this.lastCallTime = 0;
  }
}

/**
 * Create a rate limiter for message sending
 * Allows 10 messages per 10 seconds (prevents spam)
 */
export function createMessageRateLimiter(): RateLimiter {
  return new RateLimiter(10, 10000); // 10 messages per 10 seconds
}
