/**
 * Tests for input validation utilities
 */

import {
  validateMessageLength,
  validateTitle,
  sanitizeInput,
  sanitizeMarkdown,
  checkForHarmfulPatterns,
  validateInput,
  RateLimiter,
  createMessageRateLimiter,
  INPUT_CONSTANTS,
} from '../input-validation';

describe('validateMessageLength', () => {
  it('should reject empty messages', () => {
    const result = validateMessageLength('');
    expect(result.isValid).toBe(false);
    expect(result.error).toBe('Message cannot be empty');
  });

  it('should reject whitespace-only messages', () => {
    const result = validateMessageLength('   \n\t  ');
    expect(result.isValid).toBe(false);
    expect(result.error).toBe('Message cannot be empty');
  });

  it('should accept valid messages', () => {
    const result = validateMessageLength('Hello, world!');
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('Hello, world!');
  });

  it('should trim whitespace', () => {
    const result = validateMessageLength('  Hello  ');
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('Hello');
  });

  it('should reject messages that exceed max length', () => {
    const longMessage = 'a'.repeat(INPUT_CONSTANTS.MAX_MESSAGE_LENGTH + 1);
    const result = validateMessageLength(longMessage);
    expect(result.isValid).toBe(false);
    expect(result.error).toContain('too long');
  });

  it('should accept messages at max length', () => {
    const maxMessage = 'a'.repeat(INPUT_CONSTANTS.MAX_MESSAGE_LENGTH);
    const result = validateMessageLength(maxMessage);
    expect(result.isValid).toBe(true);
  });
});

describe('validateTitle', () => {
  it('should reject empty titles', () => {
    const result = validateTitle('');
    expect(result.isValid).toBe(false);
    expect(result.error).toBe('Title cannot be empty');
  });

  it('should accept valid titles', () => {
    const result = validateTitle('My Conversation');
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('My Conversation');
  });

  it('should reject titles that exceed max length', () => {
    const longTitle = 'a'.repeat(INPUT_CONSTANTS.MAX_TITLE_LENGTH + 1);
    const result = validateTitle(longTitle);
    expect(result.isValid).toBe(false);
    expect(result.error).toContain('too long');
  });

  it('should trim whitespace', () => {
    const result = validateTitle('  Title  ');
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('Title');
  });
});

describe('sanitizeInput', () => {
  it('should remove null bytes', () => {
    const input = 'Hello\x00World';
    const result = sanitizeInput(input);
    expect(result).toBe('HelloWorld');
  });

  it('should limit consecutive newlines', () => {
    const input = 'Line1\n\n\n\n\n\nLine2';
    const result = sanitizeInput(input);
    expect(result).toBe('Line1\n\n\nLine2');
  });

  it('should remove control characters', () => {
    const input = 'Hello\x01\x02\x03World';
    const result = sanitizeInput(input);
    expect(result).toBe('HelloWorld');
  });

  it('should preserve tabs and newlines', () => {
    const input = 'Line1\nLine2\tTabbed';
    const result = sanitizeInput(input);
    expect(result).toBe('Line1\nLine2\tTabbed');
  });

  it('should trim whitespace', () => {
    const input = '  Content  ';
    const result = sanitizeInput(input);
    expect(result).toBe('Content');
  });
});

describe('sanitizeMarkdown', () => {
  it('should sanitize markdown content', () => {
    const markdown = '# Hello\nWorld';
    const result = sanitizeMarkdown(markdown);
    expect(result).toBeTruthy();
  });

  it('should handle empty strings', () => {
    const result = sanitizeMarkdown('');
    expect(result).toBe('');
  });
});

describe('checkForHarmfulPatterns', () => {
  it('should detect script tags', () => {
    const input = '<script>alert("XSS")</script>';
    const result = checkForHarmfulPatterns(input);
    expect(result.isValid).toBe(false);
    expect(result.error).toContain('harmful patterns');
  });

  it('should detect script tags with attributes', () => {
    const input = '<script src="evil.js"></script>';
    const result = checkForHarmfulPatterns(input);
    expect(result.isValid).toBe(false);
  });

  it('should detect excessive HTML tags', () => {
    const manyTags = '<div>'.repeat(60) + '</div>'.repeat(60);
    const result = checkForHarmfulPatterns(manyTags);
    expect(result.isValid).toBe(false);
    expect(result.error).toContain('excessive HTML tags');
  });

  it('should allow reasonable HTML', () => {
    const input = '<p>Hello <strong>world</strong></p>';
    const result = checkForHarmfulPatterns(input);
    expect(result.isValid).toBe(true);
  });

  it('should allow plain text', () => {
    const input = 'Just plain text';
    const result = checkForHarmfulPatterns(input);
    expect(result.isValid).toBe(true);
  });
});

describe('validateInput', () => {
  it('should validate and sanitize valid input', () => {
    const input = '  Hello World  ';
    const result = validateInput(input);
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('Hello World');
  });

  it('should reject empty input', () => {
    const result = validateInput('');
    expect(result.isValid).toBe(false);
  });

  it('should reject input with harmful patterns', () => {
    const input = '<script>alert("XSS")</script>';
    const result = validateInput(input);
    expect(result.isValid).toBe(false);
  });

  it('should reject input that is too long', () => {
    const longInput = 'a'.repeat(INPUT_CONSTANTS.MAX_MESSAGE_LENGTH + 1);
    const result = validateInput(longInput);
    expect(result.isValid).toBe(false);
  });

  it('should sanitize control characters', () => {
    const input = 'Hello\x00\x01World';
    const result = validateInput(input);
    expect(result.isValid).toBe(true);
    expect(result.sanitized).toBe('HelloWorld');
  });
});

describe('RateLimiter', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should allow actions within limit', () => {
    const limiter = new RateLimiter(3, 1000); // 3 calls per second

    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(true);
  });

  it('should block actions over limit', () => {
    const limiter = new RateLimiter(2, 1000);

    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(false); // Over limit
  });

  it('should reset after time window', () => {
    const limiter = new RateLimiter(2, 1000);

    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(true);
    expect(limiter.isAllowed()).toBe(false);

    // Advance time past window
    jest.advanceTimersByTime(1001);

    // Should be allowed again
    expect(limiter.isAllowed()).toBe(true);
  });

  it('should calculate time until reset', () => {
    const limiter = new RateLimiter(1, 1000);

    limiter.isAllowed(); // Use up the limit
    limiter.isAllowed(); // This will be blocked

    const timeRemaining = limiter.getTimeUntilReset();
    expect(timeRemaining).toBeGreaterThan(0);
    expect(timeRemaining).toBeLessThanOrEqual(1000);
  });

  it('should reset manually', () => {
    const limiter = new RateLimiter(1, 1000);

    limiter.isAllowed();
    expect(limiter.isAllowed()).toBe(false);

    limiter.reset();
    expect(limiter.isAllowed()).toBe(true);
  });
});

describe('createMessageRateLimiter', () => {
  it('should create a rate limiter with default settings', () => {
    const limiter = createMessageRateLimiter();
    expect(limiter).toBeInstanceOf(RateLimiter);
  });

  it('should allow 10 messages in 10 seconds', () => {
    const limiter = createMessageRateLimiter();

    // Should allow 10 calls
    for (let i = 0; i < 10; i++) {
      expect(limiter.isAllowed()).toBe(true);
    }

    // 11th should be blocked
    expect(limiter.isAllowed()).toBe(false);
  });
});

describe('INPUT_CONSTANTS', () => {
  it('should have all required constants', () => {
    expect(INPUT_CONSTANTS.MIN_MESSAGE_LENGTH).toBe(1);
    expect(INPUT_CONSTANTS.MAX_MESSAGE_LENGTH).toBe(32000);
    expect(INPUT_CONSTANTS.MAX_TITLE_LENGTH).toBe(200);
    expect(INPUT_CONSTANTS.DEBOUNCE_DELAY_MS).toBeDefined();
    expect(INPUT_CONSTANTS.MAX_TEXTAREA_HEIGHT_PX).toBeDefined();
    expect(INPUT_CONSTANTS.CONVERSATION_CREATION_DELAY_MS).toBeDefined();
  });
});
