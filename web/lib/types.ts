/**
 * Message role types
 */
export type MessageRole = "user" | "assistant" | "system";

/**
 * Message interface
 */
export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  metadata?: {
    execution_time?: number;
    quality_score?: number;
    agent_used?: string;
    sources?: string[];
    [key: string]: any;
  };
}

/**
 * Chat session interface
 */
export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

/**
 * Query preferences
 */
export interface QueryPreferences {
  max_iterations?: number;
  agent_timeout?: number;
  response_format?: "text" | "json" | "markdown";
  include_sources?: boolean;
  stream?: boolean;
}

/**
 * API request interface
 */
export interface ChatRequest {
  query: string;
  user_id?: string;
  session_id?: string;
  preferences?: QueryPreferences;
}

/**
 * API response interface
 */
export interface ChatResponse {
  success: boolean;
  response: string;
  metadata?: {
    execution_time?: number;
    quality_score?: number;
    agent_used?: string;
    sources?: string[];
    session_id?: string;
    [key: string]: any;
  };
  session_id?: string;
  timestamp?: string;
  error?: string;
}

/**
 * Chat store state
 */
export interface ChatStore {
  // State
  sessions: ChatSession[];
  currentSessionId: string | null;
  isLoading: boolean;
  error: string | null;

  // Getters
  currentSession: ChatSession | null;
  messages: Message[];

  // Actions
  createSession: () => void;
  setCurrentSession: (sessionId: string) => void;
  addMessage: (message: Omit<Message, "id" | "timestamp">) => void;
  updateLastMessage: (content: string, metadata?: any) => void;
  sendMessage: (content: string) => Promise<void>;
  deleteSession: (sessionId: string) => void;
  clearError: () => void;
}
