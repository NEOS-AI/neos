/**
 * Chat API Client - Comprehensive client for all NEOS chat endpoints
 */

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8518";
const API_V1_PREFIX = "/api/v1";

// ============================================================================
// Types
// ============================================================================

export type MessageRole = "user" | "assistant" | "system" | "function" | "tool";
export type MessageStatus = "pending" | "streaming" | "completed" | "failed" | "cancelled" | "edited";
export type ConversationStatus = "active" | "archived" | "deleted";
export type ChatMode = "standard" | "rag" | "similarity";

export interface CreateConversationRequest {
  user_id: string;
  title?: string;
  model_name?: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  template_id?: string;
  metadata?: Record<string, any>;
}

export interface SendMessageRequest {
  content: string;
  role?: MessageRole;
  parent_message_id?: string;
  attachments?: Array<Record<string, any>>;
  metadata?: Record<string, any>;
}

export interface SendSimilarityMessageRequest extends SendMessageRequest {
  top_k?: number;
  similarity_threshold?: number;
  include_cross_conversation?: boolean;
  enable_auto_embedding?: boolean;
}

export interface SendRAGMessageRequest extends SendMessageRequest {
  enable_rag?: boolean;
  rag_top_k?: number;
  include_cross_conversation?: boolean;
}

export interface ConversationResponse {
  conversation_id: string;
  user_id: string;
  title: string;
  model_name: string;
  system_prompt?: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
  message_count: number;
  participant_count: number;
  total_tokens: number;
  total_cost_usd: number;
  is_pinned: boolean;
  tags: string[];
  metadata: Record<string, any>;
}

export interface MessageResponse {
  message_id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  content_type: string;
  sequence_number: number;
  parent_message_id?: string;
  status: MessageStatus;
  model_name?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  finish_reason?: string;
  user_feedback?: "positive" | "negative" | "neutral";
  quality_score?: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, any>;
}

export interface CreateMessageResponse {
  success: boolean;
  user_message: MessageResponse;
  assistant_message: MessageResponse;
  conversation_id: string;
  errors: string[];
}

export interface RAGMessageResponse extends CreateMessageResponse {
  rag_enabled: boolean;
  rag_context?: {
    retrieved_messages: any[];
    total_retrieved: number;
    avg_similarity: number;
  };
}

export interface SimilarityMessageResponse extends CreateMessageResponse {
  context_enhanced: boolean;
  relevant_message_count: number;
  similarity_scores: Array<{
    message_id: string;
    similarity_score: number;
    content_preview: string;
  }>;
  search_config: Record<string, any>;
}

// ============================================================================
// Chat API Client
// ============================================================================

class ChatAPI {
  private baseUrl: string;

  constructor() {
    this.baseUrl = `${BACKEND_URL}${API_V1_PREFIX}`;
  }

  // --------------------------------------------------------------------------
  // Conversation Management
  // --------------------------------------------------------------------------

  async createConversation(request: CreateConversationRequest): Promise<ConversationResponse> {
    const response = await fetch(`${this.baseUrl}/chat/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Failed to create conversation: ${response.statusText}`);
    }

    return response.json();
  }

  async getConversation(conversationId: string): Promise<ConversationResponse> {
    const response = await fetch(`${this.baseUrl}/chat/conversations/${conversationId}`);

    if (!response.ok) {
      throw new Error(`Failed to get conversation: ${response.statusText}`);
    }

    return response.json();
  }

  async listConversations(
    userId: string,
    options?: {
      limit?: number;
      offset?: number;
      status?: ConversationStatus;
      include_archived?: boolean;
    }
  ): Promise<{ conversations: ConversationResponse[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());
    if (options?.status) params.append("status", options.status);
    if (options?.include_archived !== undefined) {
      params.append("include_archived", options.include_archived.toString());
    }

    const response = await fetch(
      `${this.baseUrl}/chat/users/${userId}/conversations?${params.toString()}`
    );

    if (!response.ok) {
      throw new Error(`Failed to list conversations: ${response.statusText}`);
    }

    return response.json();
  }

  async updateConversation(
    conversationId: string,
    updates: {
      title?: string;
      system_prompt?: string;
      temperature?: number;
      is_pinned?: boolean;
      tags?: string[];
      metadata?: Record<string, any>;
    }
  ): Promise<ConversationResponse> {
    const response = await fetch(`${this.baseUrl}/chat/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });

    if (!response.ok) {
      throw new Error(`Failed to update conversation: ${response.statusText}`);
    }

    return response.json();
  }

  async archiveConversation(conversationId: string): Promise<ConversationResponse> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/archive`,
      { method: "POST" }
    );

    if (!response.ok) {
      throw new Error(`Failed to archive conversation: ${response.statusText}`);
    }

    return response.json();
  }

  async deleteConversation(conversationId: string): Promise<{ success: boolean }> {
    const response = await fetch(`${this.baseUrl}/chat/conversations/${conversationId}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      throw new Error(`Failed to delete conversation: ${response.statusText}`);
    }

    return response.json();
  }

  // --------------------------------------------------------------------------
  // Standard Chat Messages
  // --------------------------------------------------------------------------

  async sendMessage(
    conversationId: string,
    request: SendMessageRequest
  ): Promise<CreateMessageResponse> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send message: ${response.statusText}`);
    }

    return response.json();
  }

  async sendMessageStream(
    conversationId: string,
    request: SendMessageRequest
  ): Promise<ReadableStream> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send streaming message: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error("Response body is null");
    }

    return response.body;
  }

  async getMessages(
    conversationId: string,
    options?: { limit?: number; before_sequence?: number }
  ): Promise<MessageResponse[]> {
    const params = new URLSearchParams();
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.before_sequence) {
      params.append("before_sequence", options.before_sequence.toString());
    }

    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages?${params.toString()}`
    );

    if (!response.ok) {
      throw new Error(`Failed to get messages: ${response.statusText}`);
    }

    return response.json();
  }

  async regenerateMessage(
    conversationId: string,
    messageId: string,
    options?: { temperature?: number; model_name?: string }
  ): Promise<MessageResponse> {
    const response = await fetch(
      `${this.baseUrl}/chat/messages/${messageId}/regenerate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, ...options }),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to regenerate message: ${response.statusText}`);
    }

    return response.json();
  }

  async editMessage(
    messageId: string,
    newContent: string,
    options?: { edit_reason?: string; user_id?: string }
  ): Promise<MessageResponse> {
    const response = await fetch(`${this.baseUrl}/chat/messages/${messageId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_content: newContent, ...options }),
    });

    if (!response.ok) {
      throw new Error(`Failed to edit message: ${response.statusText}`);
    }

    return response.json();
  }

  async addFeedback(
    messageId: string,
    feedback: "positive" | "negative" | "neutral",
    comment?: string
  ): Promise<MessageResponse> {
    const response = await fetch(`${this.baseUrl}/chat/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback, comment }),
    });

    if (!response.ok) {
      throw new Error(`Failed to add feedback: ${response.statusText}`);
    }

    return response.json();
  }

  // --------------------------------------------------------------------------
  // RAG Chat Messages
  // --------------------------------------------------------------------------

  async sendRAGMessage(
    conversationId: string,
    request: SendRAGMessageRequest
  ): Promise<RAGMessageResponse> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages/rag`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send RAG message: ${response.statusText}`);
    }

    return response.json();
  }

  async sendRAGMessageStream(
    conversationId: string,
    request: SendRAGMessageRequest
  ): Promise<ReadableStream> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages/rag/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send RAG streaming message: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error("Response body is null");
    }

    return response.body;
  }

  // --------------------------------------------------------------------------
  // Similarity Chat Messages
  // --------------------------------------------------------------------------

  async sendSimilarityMessage(
    conversationId: string,
    request: SendSimilarityMessageRequest
  ): Promise<SimilarityMessageResponse> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages/similarity`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send similarity message: ${response.statusText}`);
    }

    return response.json();
  }

  async sendSimilarityMessageStream(
    conversationId: string,
    request: SendSimilarityMessageRequest
  ): Promise<ReadableStream> {
    const response = await fetch(
      `${this.baseUrl}/chat/conversations/${conversationId}/messages/similarity/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send similarity streaming message: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error("Response body is null");
    }

    return response.body;
  }

  // --------------------------------------------------------------------------
  // WebSocket Chat
  // --------------------------------------------------------------------------

  connectWebSocket(conversationId: string): WebSocket {
    const wsUrl = BACKEND_URL.replace(/^http/, "ws");
    return new WebSocket(`${wsUrl}${API_V1_PREFIX}/chat/ws/${conversationId}`);
  }
}

// Export singleton instance
export const chatAPI = new ChatAPI();
