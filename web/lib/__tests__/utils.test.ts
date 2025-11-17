/**
 * Tests for utility functions
 */

import { cn, formatTimestamp, truncate, debounce, generateId } from '../utils';

describe('cn (className merger)', () => {
  it('should merge class names', () => {
    const result = cn('foo', 'bar');
    expect(result).toContain('foo');
    expect(result).toContain('bar');
  });

  it('should handle conditional classes', () => {
    const result = cn('foo', false && 'bar', 'baz');
    expect(result).toContain('foo');
    expect(result).toContain('baz');
    expect(result).not.toContain('bar');
  });

  it('should handle undefined and null', () => {
    const result = cn('foo', undefined, null, 'bar');
    expect(result).toContain('foo');
    expect(result).toContain('bar');
  });

  it('should merge Tailwind classes correctly', () => {
    const result = cn('p-4', 'p-8');
    // Should only include one padding class (the last one)
    expect(result).toContain('p-8');
  });

  it('should handle empty input', () => {
    const result = cn();
    expect(result).toBe('');
  });
});

describe('formatTimestamp', () => {
  beforeAll(() => {
    // Mock Date.now() to return a fixed timestamp
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2024-01-01T12:00:00Z'));
  });

  afterAll(() => {
    jest.useRealTimers();
  });

  it('should return "Just now" for very recent timestamps', () => {
    const now = new Date('2024-01-01T12:00:00Z');
    const result = formatTimestamp(now);
    expect(result).toBe('Just now');
  });

  it('should return minutes ago for recent timestamps', () => {
    const fiveMinutesAgo = new Date('2024-01-01T11:55:00Z');
    const result = formatTimestamp(fiveMinutesAgo);
    expect(result).toBe('5m ago');
  });

  it('should return hours ago for timestamps within 24 hours', () => {
    const twoHoursAgo = new Date('2024-01-01T10:00:00Z');
    const result = formatTimestamp(twoHoursAgo);
    expect(result).toBe('2h ago');
  });

  it('should return days ago for timestamps within a week', () => {
    const threeDaysAgo = new Date('2023-12-29T12:00:00Z');
    const result = formatTimestamp(threeDaysAgo);
    expect(result).toBe('3d ago');
  });

  it('should return formatted date for older timestamps', () => {
    const twoWeeksAgo = new Date('2023-12-15T12:00:00Z');
    const result = formatTimestamp(twoWeeksAgo);
    expect(result).toBeTruthy();
    expect(result).not.toContain('ago');
  });

  it('should handle string timestamps', () => {
    const timestamp = '2024-01-01T11:30:00Z';
    const result = formatTimestamp(timestamp);
    expect(result).toBe('30m ago');
  });

  it('should handle Date objects', () => {
    const date = new Date('2024-01-01T11:45:00Z');
    const result = formatTimestamp(date);
    expect(result).toBe('15m ago');
  });
});

describe('truncate', () => {
  it('should not truncate short text', () => {
    const text = 'Hello';
    const result = truncate(text, 10);
    expect(result).toBe('Hello');
  });

  it('should truncate long text', () => {
    const text = 'This is a very long text that should be truncated';
    const result = truncate(text, 20);
    expect(result).toBe('This is a very long ...');
    expect(result.length).toBe(23); // 20 + "..."
  });

  it('should handle text exactly at max length', () => {
    const text = 'Exactly twenty chars';
    const result = truncate(text, 20);
    expect(result).toBe(text);
  });

  it('should handle empty string', () => {
    const result = truncate('', 10);
    expect(result).toBe('');
  });

  it('should handle maxLength of 0', () => {
    const result = truncate('Hello', 0);
    expect(result).toBe('...');
  });

  it('should handle very short maxLength', () => {
    const result = truncate('Hello World', 3);
    expect(result).toBe('Hel...');
  });
});

describe('debounce', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should delay function execution', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn();
    expect(mockFn).not.toHaveBeenCalled();

    jest.advanceTimersByTime(499);
    expect(mockFn).not.toHaveBeenCalled();

    jest.advanceTimersByTime(1);
    expect(mockFn).toHaveBeenCalledTimes(1);
  });

  it('should only execute once for multiple rapid calls', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn();
    debouncedFn();
    debouncedFn();

    jest.advanceTimersByTime(500);
    expect(mockFn).toHaveBeenCalledTimes(1);
  });

  it('should reset timer on each call', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn();
    jest.advanceTimersByTime(400);
    debouncedFn(); // Reset timer
    jest.advanceTimersByTime(400);
    expect(mockFn).not.toHaveBeenCalled();

    jest.advanceTimersByTime(100);
    expect(mockFn).toHaveBeenCalledTimes(1);
  });

  it('should pass arguments to the debounced function', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn('arg1', 'arg2');
    jest.advanceTimersByTime(500);

    expect(mockFn).toHaveBeenCalledWith('arg1', 'arg2');
  });

  it('should preserve the latest arguments', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn('first');
    debouncedFn('second');
    debouncedFn('third');

    jest.advanceTimersByTime(500);
    expect(mockFn).toHaveBeenCalledWith('third');
    expect(mockFn).toHaveBeenCalledTimes(1);
  });

  it('should allow multiple executions after wait time', () => {
    const mockFn = jest.fn();
    const debouncedFn = debounce(mockFn, 500);

    debouncedFn();
    jest.advanceTimersByTime(500);
    expect(mockFn).toHaveBeenCalledTimes(1);

    debouncedFn();
    jest.advanceTimersByTime(500);
    expect(mockFn).toHaveBeenCalledTimes(2);
  });
});

describe('generateId', () => {
  it('should generate a unique ID', () => {
    const id = generateId();
    expect(id).toBeTruthy();
    expect(typeof id).toBe('string');
  });

  it('should generate different IDs on each call', () => {
    const id1 = generateId();
    const id2 = generateId();
    expect(id1).not.toBe(id2);
  });

  it('should generate ID with timestamp and random component', () => {
    const id = generateId();
    // Format: {timestamp}_{random}
    expect(id).toMatch(/^\d+_[a-z0-9]+$/);
  });

  it('should generate IDs that are reasonably unique', () => {
    const ids = new Set();
    for (let i = 0; i < 1000; i++) {
      ids.add(generateId());
    }
    // All IDs should be unique
    expect(ids.size).toBe(1000);
  });

  it('should generate ID with correct structure', () => {
    const id = generateId();
    const parts = id.split('_');
    expect(parts.length).toBe(2);

    const timestamp = parseInt(parts[0], 10);
    expect(timestamp).toBeGreaterThan(0);

    const random = parts[1];
    expect(random.length).toBeGreaterThan(0);
  });
});
