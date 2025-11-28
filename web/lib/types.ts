/**
 * Message role types
 */
export type MessageRole = "user" | "assistant" | "system" | "function" | "tool";

/**
 * Message status types
 */
export type MessageStatus = "pending" | "streaming" | "completed" | "failed" | "cancelled" | "edited";

/**
 * Conversation status types
 */
export type ConversationStatus = "active" | "archived" | "deleted";

/**
 * Chat mode types
 */
export type ChatMode = "standard" | "rag" | "similarity" | "deep_research";

/**
 * Deep Research Artifact Types
 */
export interface TimelineEvent {
  timestamp: Date;
  activity: string;
  eventType?: string;
}

export interface PhaseInfo {
  phaseNumber: number;
  phaseName: string;
  status: "pending" | "in_progress" | "completed";
  startedAt?: Date;
  completedAt?: Date;
  duration?: number;
}

export interface ResearchArtifact {
  currentPhase: string;
  phaseNumber: number;
  phases: PhaseInfo[];
  currentQuery: string;
  searchProgress: number;
  totalSources: number;
  totalQueries: number;
  currentActivity: string;
  isThinking: boolean;
  timeline: TimelineEvent[];
  progressPercentage: number;
}

/**
 * Message interface - Enhanced to match backend
 */
export interface Message {
  message_id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  content_type?: string;
  sequence_number: number;
  parent_message_id?: string;
  status: MessageStatus;

  // AI metadata
  model_name?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  finish_reason?: string;

  // User feedback
  user_feedback?: "positive" | "negative" | "neutral";
  feedback_comment?: string;
  quality_score?: number;

  // Timestamps
  created_at: string;
  updated_at: string;

  // Additional metadata
  metadata?: {
    execution_time?: number;
    agent_used?: string;
    sources?: string[];

    // RAG specific
    rag_enabled?: boolean;
    rag_context?: {
      retrieved_messages?: any[];
      total_retrieved?: number;
      avg_similarity?: number;
    };

    // Similarity specific
    context_enhanced?: boolean;
    relevant_message_count?: number;
    similarity_scores?: Array<{
      message_id: string;
      similarity_score: number;
      content_preview: string;
    }>;

    [key: string]: any;
  };
}

/**
 * Conversation interface - Enhanced to match backend
 */
export interface Conversation {
  conversation_id: string;
  user_id: string;
  title: string | null;
  summary?: string | null;
  model_name: string;
  system_prompt?: string | null;
  mode?: string; // Chat mode: standard, rag, similarity, deep_research
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  last_accessed_at?: string | null;

  // Stats
  message_count: number;
  participant_count: number;
  total_tokens: number;
  total_cost_usd: number;

  // Features
  is_pinned: boolean;
  tags: string[];

  // Local UI state
  messages?: Message[];

  metadata?: Record<string, any>;
}

/**
 * Chat settings for different modes
 */
export interface ChatSettings {
  mode: ChatMode;
  model_name: string;
  temperature: number;
  stream: boolean;

  // RAG settings
  rag_enabled?: boolean;
  rag_top_k?: number;
  rag_cross_conversation?: boolean;

  // Similarity settings
  similarity_top_k?: number;
  similarity_threshold?: number;
  similarity_cross_conversation?: boolean;
  enable_auto_embedding?: boolean;

  // Deep research settings
  deep_research_enabled?: boolean;
}

/**
 * Deep Research types
 */
export type ResearchStatus = "pending" | "in_progress" | "completed" | "failed";
export type ResearchPhase =
  | "topic_confirmation"
  | "planning"
  | "data_collection"
  | "analysis"
  | "report_generation";

export interface DeepResearchReport {
  report_id: string;
  research_topic: string;
  research_status: ResearchStatus;
  created_at: string;
  completed_at?: string;
  total_sections: number;
  total_sources: number;
  total_queries: number;
  quality_score?: number;
  processing_time_ms?: number;
}

export interface DeepResearchEvent {
  event: string;
  report_id: string;
  timestamp: string;
  data: Record<string, any>;
}

/**
 * Query preferences (legacy - for backward compatibility)
 */
export interface QueryPreferences {
  max_iterations?: number;
  agent_timeout?: number;
  response_format?: "text" | "json" | "markdown";
  include_sources?: boolean;
  stream?: boolean;
}

/**
 * Chat store state - Refactored for full backend integration
 */
export interface ChatStore {
  // State
  conversations: Conversation[];
  currentConversationId: string | null;
  currentUserId: string;
  isLoading: boolean;
  isStreaming: boolean;
  error: string | null;
  settings: ChatSettings;

  // Deep research EventSource tracking
  activeEventSource: EventSource | null;

  // Abort controller for request cancellation
  currentAbortController: AbortController | null;

  // SSE reconnection tracking
  sseReconnectAttempts: number;
  sseReconnectTimeoutId: number | null;

  // Heartbeat timeout detection
  lastHeartbeatTimestamp: number | null;
  heartbeatTimeoutId: number | null;

  // Multi-tab synchronization
  broadcastChannel: BroadcastChannel | null;

  // Network status
  isOnline: boolean;

  // Getters
  currentConversation: Conversation | null;
  messages: Message[];

  // Conversation Actions
  loadConversations: () => Promise<void>;
  createConversation: (title?: string, systemPrompt?: string, mode?: string) => Promise<void>;
  setCurrentConversation: (conversationId: string) => void;
  updateConversationTitle: (conversationId: string, title: string) => Promise<void>;
  archiveConversation: (conversationId: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;

  // Message Actions
  loadMessages: (conversationId: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  sendStreamingMessage: (content: string) => Promise<void>;
  sendDeepResearchMessage: (content: string) => Promise<void>;
  checkAndReconnectDeepResearch: (conversationId: string, messages: Message[]) => Promise<void>;
  reconnectDeepResearch: (conversationId: string, reportId: string, assistantMsgId: string, existingContent: string) => Promise<void>;
  _sendMessageWithStreaming: (content: string) => Promise<void>;
  _sendMessageWithoutStreaming: (content: string) => Promise<void>;
  regenerateMessage: (messageId: string) => Promise<void>;
  editMessage: (messageId: string, newContent: string) => Promise<void>;
  addFeedback: (messageId: string, feedback: "positive" | "negative" | "neutral", comment?: string) => Promise<void>;

  // Settings Actions
  updateSettings: (settings: Partial<ChatSettings>) => void;
  setChatMode: (mode: ChatMode) => void;
  setUserId: (userId: string) => void;

  // Utility Actions
  clearError: () => void;
  cleanupEventSource: () => void;
  stopGeneration: () => void;

  // Connection Management Actions
  setupNetworkListeners: () => (() => void) | undefined;
  setupBroadcastChannel: () => void;
  startHeartbeatMonitoring: (reportId: string, conversationId: string, assistantMsgId: string) => void;
  resetHeartbeat: (reportId: string, conversationId: string, assistantMsgId: string) => void;
  savePartialResults: (reportId: string, content: string, metadata: any) => void;
  loadPartialResults: (reportId: string) => { content: string; metadata: any } | null;
  clearPartialResults: (reportId: string) => void;
}
