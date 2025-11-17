/**
 * Application-wide constants
 * Consolidates all magic numbers and configuration values in one place
 */

/**
 * UI Component Dimensions
 */
export const UI_DIMENSIONS = {
  // Sidebar
  SIDEBAR_WIDTH_PX: 280,

  // Input Box
  INPUT_MIN_HEIGHT_PX: 24,
  INPUT_MAX_HEIGHT_PX: 200,

  // Message Display
  MESSAGE_FONT_SIZE_PX: 15,
  CODE_FONT_SIZE_PX: 13,
  MESSAGE_ESTIMATED_HEIGHT_PX: 150, // For virtualization
} as const;

/**
 * Input Validation Constants
 */
export const INPUT_VALIDATION = {
  MIN_MESSAGE_LENGTH: 1,
  MAX_MESSAGE_LENGTH: 32000, // 32K characters (reasonable limit for LLMs)
  MAX_TITLE_LENGTH: 200,
} as const;

/**
 * Performance & UX Constants
 */
export const PERFORMANCE = {
  // Debouncing & Delays
  DEBOUNCE_DELAY_MS: 300,
  CONVERSATION_CREATION_DELAY_MS: 100,

  // Virtualization
  VIRTUALIZATION_THRESHOLD: 50, // Number of messages before enabling virtualization
  VIRTUALIZATION_OVERSCAN: 5, // Number of items to render outside viewport

  // Rate Limiting
  RATE_LIMIT_MAX_CALLS: 10,
  RATE_LIMIT_WINDOW_MS: 10000, // 10 seconds
} as const;

/**
 * API & Data Fetching Constants
 */
export const API = {
  // Message Fetching
  MESSAGES_FETCH_LIMIT: 100,

  // Retry Configuration
  MAX_RETRIES: 3,
  RETRY_BASE_DELAY_MS: 1000, // 1 second
  RETRY_MAX_DELAY_MS: 10000, // 10 seconds

  // Timeouts
  DEFAULT_TIMEOUT_MS: 30000, // 30 seconds
  DEEP_RESEARCH_TIMEOUT_SEC: 300, // 5 minutes
} as const;

/**
 * AI Model & Search Constants
 */
export const AI_SETTINGS = {
  // Similarity Search
  SIMILARITY_THRESHOLD_LOW: 0.7,
  SIMILARITY_THRESHOLD_MEDIUM: 0.75,
  SIMILARITY_THRESHOLD_HIGH: 0.85,

  // Deep Research
  DEEP_RESEARCH_MAX_ITERATIONS: 10,
  DEEP_RESEARCH_DEFAULT_MAX_RESULTS: 20,
} as const;

/**
 * Export all constants as a single object for convenience
 */
export const CONSTANTS = {
  UI: UI_DIMENSIONS,
  INPUT: INPUT_VALIDATION,
  PERF: PERFORMANCE,
  API,
  AI: AI_SETTINGS,
} as const;

// Type exports for better TypeScript support
export type UIConstants = typeof UI_DIMENSIONS;
export type InputConstants = typeof INPUT_VALIDATION;
export type PerformanceConstants = typeof PERFORMANCE;
export type APIConstants = typeof API;
export type AIConstants = typeof AI_SETTINGS;
