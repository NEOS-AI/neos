import { create } from "zustand";
import { persist } from "zustand/middleware";
import { chatAPI, type MessageResponse, type ConversationResponse } from "@/lib/api/chat-api";
import type {
  ChatStore,
  Conversation,
  Message,
  ChatSettings,
  ChatMode,
  ResearchArtifact,
} from "@/lib/types";
import { logError, classifyError, getUserFriendlyMessage, ErrorType } from "@/lib/error-logger";
import { AI_SETTINGS, API } from "@/lib/constants";

const DEFAULT_USER_ID = "anonymous";

/**
 * Get the current user ID from auth or fall back to anonymous
 * Note: Returns default user ID as a synchronous fallback.
 * The actual user ID should be set through the store's currentUserId state.
 */
function getCurrentUserId(): string {
  return DEFAULT_USER_ID;
}

const DEFAULT_SETTINGS: ChatSettings = {
  mode: "standard",
  model_name: "claude-sonnet-4-5-20250929",
  temperature: 0.7,
  stream: true, // Changed to true for streaming by default

  // RAG defaults
  rag_enabled: true,
  rag_top_k: 3,
  rag_cross_conversation: false,

  // Similarity defaults
  similarity_top_k: 3,
  similarity_threshold: AI_SETTINGS.SIMILARITY_THRESHOLD_LOW,
  similarity_cross_conversation: false,
  enable_auto_embedding: true,
};

// Helper function to convert MessageResponse to Message
const toMessage = (response: MessageResponse): Message => {
  return {
    message_id: response.message_id,
    conversation_id: response.conversation_id,
    role: response.role,
    content: response.content,
    content_type: response.content_type,
    sequence_number: response.sequence_number,
    parent_message_id: response.parent_message_id,
    status: response.status,
    model_name: response.model_name,
    prompt_tokens: response.prompt_tokens,
    completion_tokens: response.completion_tokens,
    total_tokens: response.total_tokens,
    finish_reason: response.finish_reason,
    user_feedback: response.user_feedback,
    quality_score: response.quality_score,
    created_at: response.created_at,
    updated_at: response.updated_at,
    metadata: response.metadata,
  };
};

// Helper to convert ConversationResponse to Conversation
const toConversation = (response: ConversationResponse): Conversation => {
  return {
    ...response,
    messages: [],
  };
};

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      // ======================================================================
      // Initial State
      // ======================================================================
      conversations: [],
      currentConversationId: null,
      currentUserId: DEFAULT_USER_ID,
      isLoading: false,
      isStreaming: false,
      error: null,
      settings: DEFAULT_SETTINGS,
      activeEventSource: null,
      currentAbortController: null,
      sseReconnectAttempts: 0,
      sseReconnectTimeoutId: null,
      lastHeartbeatTimestamp: null,
      heartbeatTimeoutId: null,
      broadcastChannel: null,
      isOnline: typeof navigator !== "undefined" ? navigator.onLine : true,

      // ======================================================================
      // Computed Getters
      // ======================================================================
      get currentConversation() {
        const { conversations, currentConversationId } = get();
        const current = conversations.find((c) => c.conversation_id === currentConversationId) || null;
        console.log("[Store] currentConversation getter:", {
          currentConversationId,
          totalConversations: conversations.length,
          found: !!current,
          messagesCount: current?.messages?.length || 0,
        });
        return current;
      },

      get messages() {
        const { currentConversation } = get();
        const messages = currentConversation?.messages || [];
        console.log("[Store] Getting messages:", {
          conversationId: currentConversation?.conversation_id,
          messageCount: messages.length,
        });
        return messages;
      },

      // ======================================================================
      // Conversation Actions
      // ======================================================================
      loadConversations: async () => {
        set({ isLoading: true, error: null });

        try {
          const { currentUserId } = get();
          const response = await chatAPI.listConversations(currentUserId, {
            limit: API.MESSAGES_FETCH_LIMIT,
            include_archived: false,
          });

          // Filter out deleted conversations (extra safety check)
          const activeConversations = response.conversations
            .filter((c) => c.status !== "deleted")
            .map(toConversation);

          set({
            conversations: activeConversations,
            isLoading: false,
          });
        } catch (error) {
          logError(error, { context: "loadConversations", userId: get().currentUserId });
          const errorType = classifyError(error);
          const userMessage = getUserFriendlyMessage(errorType);
          set({ error: userMessage, isLoading: false });
        }
      },

      createConversation: async (title?: string, systemPrompt?: string, mode?: string) => {
        set({ isLoading: true, error: null });

        try {
          const { currentUserId, settings } = get();

          // Ensure we have a valid user ID
          const userId = currentUserId || getCurrentUserId();

          const conversationResponse = await chatAPI.createConversation({
            user_id: userId,
            title: title || "New Chat",
            model_name: settings.model_name,
            system_prompt: systemPrompt,
            temperature: settings.temperature,
            mode: mode as any || settings.mode,
          });

          // Add to conversations list with empty messages
          const newConversation = toConversation(conversationResponse);

          set((state) => ({
            conversations: [newConversation, ...state.conversations],
            currentConversationId: conversationResponse.conversation_id,
            isLoading: false,
          }));
        } catch (error) {
          logError(error, { context: "createConversation", userId: get().currentUserId });
          const errorType = classifyError(error);
          const userMessage = getUserFriendlyMessage(errorType);
          set({ error: userMessage, isLoading: false });
        }
      },

      setCurrentConversation: (conversationId: string) => {
        console.log("[Store] Setting current conversation:", conversationId);
        set({ currentConversationId: conversationId });

        // Load messages if not already loaded
        const { currentConversation } = get();
        if (currentConversation && (!currentConversation.messages || currentConversation.messages.length === 0)) {
          console.log("[Store] Loading messages for conversation...");
          get().loadMessages(conversationId);
        }
      },

      updateConversationTitle: async (conversationId: string, title: string) => {
        // Optimistically update title in UI
        const previousState = get().conversations;

        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === conversationId ? { ...c, title } : c
          ),
        }));

        try {
          await chatAPI.updateConversation(conversationId, { title });
          console.log("[Store] Conversation title updated successfully");
        } catch (error) {
          // Rollback on error
          console.error("[Store] Failed to update title, rolling back:", error);
          logError(error, { context: "updateConversationTitle", conversationId, title });

          set({
            conversations: previousState,
            error: "Failed to update conversation title. Please try again.",
          });
        }
      },

      archiveConversation: async (conversationId: string) => {
        // Optimistically archive conversation in UI
        const previousState = get().conversations;

        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === conversationId
              ? { ...c, status: "archived" as const }
              : c
          ),
        }));

        try {
          await chatAPI.archiveConversation(conversationId);
          console.log("[Store] Conversation archived successfully");
        } catch (error) {
          // Rollback on error
          console.error("[Store] Failed to archive conversation, rolling back:", error);
          logError(error, { context: "archiveConversation", conversationId });

          set({
            conversations: previousState,
            error: "Failed to archive conversation. Please try again.",
          });
        }
      },

      deleteConversation: async (conversationId: string) => {
        // Optimistically remove conversation from UI
        const previousState = get().conversations;
        const previousCurrentId = get().currentConversationId;

        set((state) => {
          const remainingConversations = state.conversations.filter(
            (c) => c.conversation_id !== conversationId
          );

          return {
            conversations: remainingConversations,
            currentConversationId:
              state.currentConversationId === conversationId
                ? remainingConversations[0]?.conversation_id || null
                : state.currentConversationId,
          };
        });

        try {
          await chatAPI.deleteConversation(conversationId);
          console.log("[Store] Conversation deleted successfully:", conversationId);
        } catch (error) {
          // Rollback on error
          console.error("[Store] Failed to delete conversation, rolling back:", error);
          logError(error, { context: "deleteConversation", conversationId });

          set({
            conversations: previousState,
            currentConversationId: previousCurrentId,
            error: "Failed to delete conversation. Please try again.",
          });
        }
      },

      // ======================================================================
      // Message Actions
      // ======================================================================
      loadMessages: async (conversationId: string) => {
        set({ isLoading: true, error: null });

        try {
          const messagesResponse = await chatAPI.getMessages(conversationId, { limit: API.MESSAGES_FETCH_LIMIT });
          const messages = messagesResponse.map(toMessage);

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId ? { ...c, messages } : c
            ),
            isLoading: false,
          }));

          // Check for ongoing deep research and reconnect if needed
          await get().checkAndReconnectDeepResearch(conversationId, messages);
        } catch (error) {
          logError(error, { context: "loadMessages", conversationId });
          const errorType = classifyError(error);
          const userMessage = getUserFriendlyMessage(errorType);
          set({ error: userMessage, isLoading: false });
        }
      },

      sendMessage: async (content: string) => {
        // Clean up any active EventSource and AbortController before sending a new message
        get().cleanupEventSource();
        get().stopGeneration(); // This will abort any ongoing request

        const { settings } = get();

        // Handle deep research mode separately (always streaming)
        if (settings.mode === "deep_research") {
          return get().sendDeepResearchMessage(content);
        }

        // Strategy Pattern: Choose streaming or non-streaming based on settings
        if (settings.stream) {
          return get()._sendMessageWithStreaming(content);
        } else {
          return get()._sendMessageWithoutStreaming(content);
        }
      },

      // Private method: Streaming strategy
      _sendMessageWithStreaming: async (content: string) => {
        const { settings } = get();
        let conversationId = get().currentConversationId;
        let currentConversation = get().currentConversation;

        // If we have a conversationId but currentConversation is not loaded yet,
        // wait a bit and try again (handles race condition with page initialization)
        if (conversationId && !currentConversation) {
          console.log("[Store] Waiting for conversation to load...");
          await new Promise((resolve) => setTimeout(resolve, 200));
          currentConversation = get().currentConversation;
        }

        // Create conversation if none exists or mode has changed
        if (!conversationId || (currentConversation && currentConversation.mode !== settings.mode)) {
          if (currentConversation && currentConversation.mode !== settings.mode) {
            console.log(`[Store] Mode changed from ${currentConversation.mode} to ${settings.mode}, creating new conversation...`);
          } else {
            console.log("[Store] No conversation exists, creating one for streaming...");
          }

          await get().createConversation(undefined, undefined, settings.mode);
          await new Promise((resolve) => setTimeout(resolve, 100));

          conversationId = get().currentConversationId;

          if (!conversationId) {
            set({ error: "No active conversation" });
            return;
          }
        }

        // Create AbortController for this request
        const abortController = new AbortController();
        set({ isStreaming: true, isLoading: true, error: null, currentAbortController: abortController });

        try {
          // Add user message optimistically
          const tempUserMessageId = `temp_user_${Date.now()}`;
          const tempAssistantMessageId = `temp_assistant_${Date.now()}`;

          const userMessage: Message = {
            message_id: tempUserMessageId,
            conversation_id: conversationId,
            role: "user",
            content,
            sequence_number: get().messages.length,
            status: "completed",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };

          // Add placeholder assistant message
          const assistantMessage: Message = {
            message_id: tempAssistantMessageId,
            conversation_id: conversationId,
            role: "assistant",
            content: "",
            sequence_number: get().messages.length + 1,
            status: "streaming",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: [...(c.messages || []), userMessage, assistantMessage],
                    // Update title from first message
                    title: c.message_count === 0 ? content.slice(0, 50) : c.title,
                  }
                : c
            ),
          }));

          // Get stream based on mode
          let stream: ReadableStream;
          switch (settings.mode) {
            case "rag":
              stream = await chatAPI.sendRAGMessageStream(conversationId, {
                content,
                enable_rag: settings.rag_enabled,
                rag_top_k: settings.rag_top_k,
                include_cross_conversation: settings.rag_cross_conversation,
              }, abortController.signal);
              break;

            case "similarity":
              stream = await chatAPI.sendSimilarityMessageStream(conversationId, {
                content,
                top_k: settings.similarity_top_k,
                similarity_threshold: settings.similarity_threshold,
                include_cross_conversation: settings.similarity_cross_conversation,
                enable_auto_embedding: settings.enable_auto_embedding,
              }, abortController.signal);
              break;

            case "standard":
            default:
              stream = await chatAPI.sendMessageStream(conversationId, { content }, abortController.signal);
              break;
          }

          // Process stream
          const reader = stream.getReader();
          const decoder = new TextDecoder();
          let accumulatedContent = "";
          let realUserMessageId = tempUserMessageId;
          let realAssistantMessageId = tempAssistantMessageId;
          let contextMetadata: any = null; // Store similarity/RAG context metadata

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");

            for (const line of lines) {
              if (line.startsWith("data: ")) {
                const data = line.slice(6);
                if (data === "[DONE]") continue;

                try {
                  const parsed = JSON.parse(data);

                  // Handle different event types
                  if (parsed.type === "start" && parsed.message_id) {
                    // Update with real message IDs from backend
                    realAssistantMessageId = parsed.message_id;
                  } else if (parsed.type === "context" && parsed.content) {
                    // Store context metadata (similarity scores, RAG info, etc.)
                    contextMetadata = parsed.content;
                  } else if (parsed.type === "content" && parsed.content) {
                    accumulatedContent += parsed.content;

                    // Update assistant message content
                    set((state) => ({
                      conversations: state.conversations.map((c) =>
                        c.conversation_id === conversationId
                          ? {
                              ...c,
                              messages: c.messages?.map((m) =>
                                m.message_id === tempAssistantMessageId || m.message_id === realAssistantMessageId
                                  ? {
                                      ...m,
                                      message_id: realAssistantMessageId,
                                      content: accumulatedContent,
                                      status: "streaming" as const,
                                    }
                                  : m
                              ),
                            }
                          : c
                      ),
                    }));
                  } else if (parsed.type === "complete") {
                    // Update message IDs with real ones from backend
                    if (parsed.user_message_id) {
                      realUserMessageId = parsed.user_message_id;
                    }
                    if (parsed.assistant_message_id) {
                      realAssistantMessageId = parsed.assistant_message_id;
                    }
                  }
                } catch (e) {
                  // Ignore parse errors
                  console.warn("[Store] Failed to parse streaming chunk:", e);
                }
              }
            }
          }

          // Mark messages as completed with real IDs and attach context metadata
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: c.messages?.map((m) => {
                      if (m.message_id === tempUserMessageId) {
                        return { ...m, message_id: realUserMessageId, status: "completed" as const };
                      }
                      if (m.message_id === tempAssistantMessageId || m.message_id === realAssistantMessageId) {
                        return {
                          ...m,
                          message_id: realAssistantMessageId,
                          status: "completed" as const,
                          metadata: contextMetadata ? { ...m.metadata, ...contextMetadata } : m.metadata,
                        };
                      }
                      return m;
                    }),
                    message_count: (c.message_count || 0) + 2,
                  }
                : c
            ),
            isStreaming: false,
            isLoading: false,
            currentAbortController: null,
          }));
        } catch (error) {
          console.error("[Store] Failed to send streaming message:", error);

          // Log the error
          logError(error, { context: "_sendMessageWithStreaming", conversationId });

          // Classify error type
          const errorType = classifyError(error);

          // Handle abort error specially (don't show error to user)
          if (errorType === ErrorType.ABORT_ERROR) {
            console.log("[Store] Stream was cancelled by user");
            set({
              isStreaming: false,
              isLoading: false,
              currentAbortController: null,
            });
            return;
          }

          // Get user-friendly message for other errors
          const userMessage = getUserFriendlyMessage(errorType);

          set({
            error: userMessage,
            isStreaming: false,
            isLoading: false,
            currentAbortController: null,
          });
        }
      },

      // Private method: Non-streaming strategy
      _sendMessageWithoutStreaming: async (content: string) => {
        const { settings } = get();
        let conversationId = get().currentConversationId;
        let currentConversation = get().currentConversation;

        // If we have a conversationId but currentConversation is not loaded yet,
        // wait a bit and try again (handles race condition with page initialization)
        if (conversationId && !currentConversation) {
          console.log("[Store] Waiting for conversation to load...");
          await new Promise((resolve) => setTimeout(resolve, 200));
          currentConversation = get().currentConversation;
        }

        // Create conversation if none exists or mode has changed
        if (!conversationId || (currentConversation && currentConversation.mode !== settings.mode)) {
          if (currentConversation && currentConversation.mode !== settings.mode) {
            console.log(`[Store] Mode changed from ${currentConversation.mode} to ${settings.mode}, creating new conversation...`);
          } else {
            console.log("[Store] No conversation exists, creating one...");
          }

          await get().createConversation(undefined, undefined, settings.mode);
          await new Promise((resolve) => setTimeout(resolve, 100));

          conversationId = get().currentConversationId;

          if (!conversationId) {
            console.error("[Store] Failed to create conversation");
            set({ error: "No active conversation" });
            return;
          }
        }

        console.log("[Store] Sending message to conversation:", conversationId);

        // Generate temporary IDs for optimistic update
        const tempUserMessageId = `temp_user_${Date.now()}`;
        const tempAssistantMessageId = `temp_assistant_${Date.now()}`;

        // Create optimistic user message
        const optimisticUserMessage: Message = {
          message_id: tempUserMessageId,
          conversation_id: conversationId,
          role: "user",
          content,
          sequence_number: get().messages.length,
          status: "completed",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };

        // Create placeholder assistant message (loading state)
        const placeholderAssistantMessage: Message = {
          message_id: tempAssistantMessageId,
          conversation_id: conversationId,
          role: "assistant",
          content: "",
          sequence_number: get().messages.length + 1,
          status: "pending",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };

        // Add optimistic messages immediately
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === conversationId
              ? {
                  ...c,
                  messages: [
                    ...(c.messages || []),
                    optimisticUserMessage,
                    placeholderAssistantMessage,
                  ],
                  title: c.message_count === 0 ? content.slice(0, 50) : c.title,
                }
              : c
          ),
          isLoading: true,
          error: null,
        }));

        try {
          let response;

          // Send based on chat mode (non-streaming endpoints)
          switch (settings.mode) {
            case "rag":
              console.log("[Store] Sending RAG message (non-streaming)...");
              response = await chatAPI.sendRAGMessage(conversationId, {
                content,
                enable_rag: settings.rag_enabled,
                rag_top_k: settings.rag_top_k,
                include_cross_conversation: settings.rag_cross_conversation,
              });
              break;

            case "similarity":
              console.log("[Store] Sending similarity message (non-streaming)...");
              const similarityResponse = await chatAPI.sendSimilarityMessage(conversationId, {
                content,
                top_k: settings.similarity_top_k,
                similarity_threshold: settings.similarity_threshold,
                include_cross_conversation: settings.similarity_cross_conversation,
                enable_auto_embedding: settings.enable_auto_embedding,
              });

              // Attach similarity metadata to assistant message
              if (!similarityResponse.assistant_message.metadata) {
                similarityResponse.assistant_message.metadata = {};
              }
              similarityResponse.assistant_message.metadata.context_enhanced = similarityResponse.context_enhanced;
              similarityResponse.assistant_message.metadata.relevant_message_count = similarityResponse.relevant_message_count;
              similarityResponse.assistant_message.metadata.similarity_scores = similarityResponse.similarity_scores;
              similarityResponse.assistant_message.metadata.search_config = similarityResponse.search_config;

              response = similarityResponse;
              break;

            case "standard":
            default:
              console.log("[Store] Sending standard message (non-streaming)...");
              response = await chatAPI.sendMessage(conversationId, { content });
              break;
          }

          console.log("[Store] Got response:", {
            userMessageId: response.user_message.message_id,
            assistantMessageId: response.assistant_message.message_id,
          });

          // Convert to Message type
          const userMessage = toMessage(response.user_message);
          const assistantMessage = toMessage(response.assistant_message);

          console.log("[Store] Replacing optimistic messages with real ones...");

          // Replace optimistic messages with real ones from server
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: (c.messages || []).map((m) => {
                      if (m.message_id === tempUserMessageId) return userMessage;
                      if (m.message_id === tempAssistantMessageId) return assistantMessage;
                      return m;
                    }),
                    message_count: (c.message_count || 0) + 2,
                  }
                : c
            ),
            isLoading: false,
          }));

          console.log("[Store] Message sent successfully (non-streaming)");
        } catch (error) {
          console.error("[Store] Failed to send message:", error);

          // Remove optimistic messages on error
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: (c.messages || []).filter(
                      (m) => m.message_id !== tempUserMessageId && m.message_id !== tempAssistantMessageId
                    ),
                  }
                : c
            ),
            error: error instanceof Error ? error.message : "Failed to send message",
            isLoading: false,
          }));
        }
      },

      // Handle deep research mode separately (always streaming)
      sendDeepResearchMessage: async (content: string) => {
        get().cleanupEventSource();

        let conversationId = get().currentConversationId;
        let currentConversation = get().currentConversation;

        // If we have a conversationId but currentConversation is not loaded yet,
        // wait a bit and try again (handles race condition with page initialization)
        if (conversationId && !currentConversation) {
          console.log("[Store] Waiting for conversation to load...");
          await new Promise((resolve) => setTimeout(resolve, 200));
          currentConversation = get().currentConversation;
        }

        // Only create a new conversation if:
        // 1. No conversation exists at all, OR
        // 2. Current conversation exists and its mode is NOT deep_research
        if (!conversationId || (currentConversation && currentConversation.mode !== "deep_research")) {
          console.log("[Store] Creating new deep_research conversation", {
            hasConversationId: !!conversationId,
            currentMode: currentConversation?.mode,
          });
          await get().createConversation(undefined, undefined, "deep_research");
          await new Promise((resolve) => setTimeout(resolve, 100));
          conversationId = get().currentConversationId;
          if (!conversationId) {
            set({ error: "No active conversation" });
            return;
          }
        }

        console.log("[Store] Starting deep research...");

        try {
          // Ensure we have a valid user ID
          const userId = get().currentUserId || getCurrentUserId();

          // Start deep research - backend will create messages
          const deepResearchResponse = await chatAPI.startDeepResearch({
            user_id: userId,
            conversation_id: conversationId,
            research_topic: content,
            session_id: `session_${Date.now()}`,
          });

          // Add the real messages from backend
          const realUserMessage: Message = {
            message_id: deepResearchResponse.user_message_id,
            conversation_id: conversationId,
            role: "user",
            content,
            sequence_number: get().messages.length,
            status: "completed",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };

          const realAssistantMessage: Message = {
            message_id: deepResearchResponse.assistant_message_id,
            conversation_id: conversationId,
            role: "assistant",
            content: `🔬 Deep research initiated...\n\n**Topic:** ${content}\n\n**Status:** Analyzing and planning research...`,
            sequence_number: get().messages.length + 1,
            status: "streaming",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            metadata: {
              deep_research_report_id: deepResearchResponse.report_id,
              research_status: "in_progress",
            },
          };

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: [...(c.messages || []), realUserMessage, realAssistantMessage],
                    title: c.message_count === 0 ? content.slice(0, 50) : c.title,
                  }
                : c
            ),
            isLoading: false,
          }));

          // Connect to SSE stream for updates
          const eventSource = chatAPI.connectDeepResearchStream(deepResearchResponse.report_id);
          const assistantMsgId = deepResearchResponse.assistant_message_id;
          let streamContent = `🔬 **Deep Research Report: ${content}**\n\n`;

          // Initialize research artifact for real-time progress tracking
          const researchArtifact: ResearchArtifact = {
            currentPhase: "Topic Analysis",
            phaseNumber: 0,
            phases: [
              { phaseNumber: 1, phaseName: "Topic Analysis", status: "pending" },
              { phaseNumber: 2, phaseName: "Research Planning", status: "pending" },
              { phaseNumber: 3, phaseName: "Data Collection", status: "pending" },
              { phaseNumber: 4, phaseName: "Deep Analysis", status: "pending" },
              { phaseNumber: 5, phaseName: "Gap Analysis", status: "pending" },
              { phaseNumber: 6, phaseName: "Cross-Validation", status: "pending" },
              { phaseNumber: 7, phaseName: "Critical Analysis", status: "pending" },
              { phaseNumber: 8, phaseName: "Report Synthesis", status: "pending" },
            ],
            currentQuery: "",
            searchProgress: 0,
            totalSources: 0,
            totalQueries: 0,
            currentActivity: "Initializing research...",
            isThinking: false,
            timeline: [],
            progressPercentage: 0,
          };

          // Helper function to update artifact
          const updateArtifact = (updates: Partial<ResearchArtifact>) => {
            Object.assign(researchArtifact, updates);

            // Update message metadata with artifact
            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.conversation_id === conversationId
                  ? {
                      ...c,
                      messages: (c.messages || []).map((m) =>
                        m.message_id === assistantMsgId
                          ? {
                              ...m,
                              metadata: {
                                ...m.metadata,
                                research_artifact: researchArtifact,
                              },
                            }
                          : m
                      ),
                    }
                  : c
              ),
            }));
          };

          set({ activeEventSource: eventSource });

          // Start heartbeat monitoring
          get().startHeartbeatMonitoring(deepResearchResponse.report_id, conversationId, assistantMsgId);

          // Broadcast that we started deep research
          const { broadcastChannel } = get();
          if (broadcastChannel) {
            broadcastChannel.postMessage({
              type: "deep_research_started",
              payload: {
                reportId: deepResearchResponse.report_id,
                conversationId,
              },
            });
          }

          eventSource.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);

              switch (data.event) {
                case "heartbeat":
                  // Heartbeat event - connection is alive, reset timeout monitoring
                  console.debug(`[Store] Heartbeat received (uptime: ${data.data.uptime_seconds}s)`);
                  get().resetHeartbeat(deepResearchResponse.report_id, conversationId, assistantMsgId);
                  break;

                // ===== Phase Events =====
                case "phase_started":
                  const phaseNum = data.data.phase_number || 0;
                  const phaseName = data.data.phase_name || data.data.message || "Unknown Phase";
                  streamContent += `\n## 🚀 Phase ${phaseNum}/8: ${phaseName}\n`;

                  // Update artifact
                  updateArtifact({
                    currentPhase: phaseName,
                    phaseNumber: phaseNum,
                    currentActivity: phaseName,
                    phases: researchArtifact.phases.map((p) =>
                      p.phaseNumber === phaseNum
                        ? { ...p, status: "in_progress", startedAt: new Date() }
                        : p.phaseNumber < phaseNum
                        ? { ...p, status: "completed" }
                        : p
                    ),
                    progressPercentage: (phaseNum / 8) * 100,
                  });

                  // Add to timeline
                  researchArtifact.timeline.push({
                    timestamp: new Date(),
                    activity: `Started: ${phaseName}`,
                    eventType: "phase_started",
                  });
                  break;

                case "phase_completed":
                  const completedPhaseNum = data.data.phase_number || 0;
                  const completedPhaseName = data.data.phase_name || data.data.message || "Phase";
                  const duration = data.data.duration_ms || 0;
                  streamContent += `✅ ${completedPhaseName} completed (${(duration / 1000).toFixed(1)}s)\n`;

                  // Update artifact
                  updateArtifact({
                    phases: researchArtifact.phases.map((p) =>
                      p.phaseNumber === completedPhaseNum
                        ? { ...p, status: "completed", completedAt: new Date(), duration }
                        : p
                    ),
                  });

                  // Add to timeline
                  researchArtifact.timeline.push({
                    timestamp: new Date(),
                    activity: `Completed: ${completedPhaseName} (${(duration / 1000).toFixed(1)}s)`,
                    eventType: "phase_completed",
                  });
                  break;

                // ===== Query/Search Events =====
                case "query_executing":
                  const query = data.data.query || "";
                  const batch = data.data.batch || 0;
                  const totalBatches = data.data.total_batches || 1;
                  streamContent += `🔍 Searching [${batch}/${totalBatches}]: "${query.substring(0, 60)}..."\n`;

                  updateArtifact({
                    currentQuery: query,
                    searchProgress: (batch / totalBatches) * 100,
                    currentActivity: `Searching batch ${batch}/${totalBatches}`,
                  });
                  break;

                case "query_executed":
                  streamContent += `📊 Query: "${data.data.query}" (${data.data.results_count} results)\n`;
                  break;

                // ===== Source Collection Events =====
                case "sources_collected":
                  const sourcesCount = data.data.sources_count || 0;
                  const totalSources = data.data.total_sources || 0;
                  streamContent += `📚 Collected ${sourcesCount} sources (Total: ${totalSources})\n`;

                  updateArtifact({
                    totalSources,
                    currentActivity: `Collected ${totalSources} sources`,
                  });

                  // Add to timeline
                  researchArtifact.timeline.push({
                    timestamp: new Date(),
                    activity: `Collected ${sourcesCount} sources`,
                    eventType: "sources_collected",
                  });
                  break;

                // ===== LLM Events =====
                case "llm_call_started":
                  const llmPurpose = data.data.purpose || "Analyzing";
                  streamContent += `🤖 ${llmPurpose}...\n`;

                  updateArtifact({
                    isThinking: true,
                    currentActivity: llmPurpose,
                  });
                  break;

                case "llm_call_completed":
                  updateArtifact({
                    isThinking: false,
                  });
                  break;

                // ===== Status Messages =====
                case "status_message":
                  const statusMsg = data.data.message || "";
                  const category = data.data.category || "info";
                  const icon = category === "success" ? "✅" : category === "warning" ? "⚠️" : "ℹ️";
                  streamContent += `${icon} ${statusMsg}\n`;

                  updateArtifact({
                    currentActivity: statusMsg,
                  });
                  break;

                // ===== Progress Update =====
                case "progress_update":
                  const progressPct = data.data.progress_percentage || 0;
                  const sourcesCollected = data.data.sources_collected || 0;
                  const completed = data.data.completed || 0;
                  const total = data.data.total || 0;
                  streamContent += `\n**Progress:** ${progressPct.toFixed(1)}% - ${sourcesCollected} sources collected\n`;

                  updateArtifact({
                    progressPercentage: progressPct,
                    totalSources: sourcesCollected,
                    currentActivity: data.data.message || `${completed}/${total} completed`,
                  });
                  break;

                // ===== Gap Events =====
                case "gap_identified":
                  const gap = data.data.gap || "";
                  streamContent += `🎯 Gap identified: ${gap}\n`;

                  // Add to timeline
                  researchArtifact.timeline.push({
                    timestamp: new Date(),
                    activity: `Gap: ${gap}`,
                    eventType: "gap_identified",
                  });
                  break;

                // ===== Analysis Events =====
                case "analysis_iteration":
                  const iteration = data.data.iteration || 0;
                  const totalIterations = data.data.total_iterations || 0;
                  const focus = data.data.focus || "";
                  streamContent += `🔬 Analysis iteration ${iteration}/${totalIterations}: ${focus}\n`;
                  break;

                // ===== Section Content =====
                case "section_content":
                  streamContent += data.data.content_chunk;
                  // Save partial results for crash recovery
                  get().savePartialResults(deepResearchResponse.report_id, streamContent, {
                    conversationId,
                    assistantMsgId,
                    status: "in_progress",
                  });
                  break;

                case "completed":
                  streamContent += `\n\n---\n\n✅ **Research Complete**\n`;
                  streamContent += `- Total sections: ${data.data.total_sections}\n`;
                  streamContent += `- Total sources: ${data.data.total_sources}\n`;
                  streamContent += `- Processing time: ${(data.data.processing_time_ms / 1000).toFixed(2)}s\n`;
                  eventSource.close();

                  // Clear partial results on completion
                  get().clearPartialResults(deepResearchResponse.report_id);

                  // Broadcast completion to other tabs
                  const { broadcastChannel: bc } = get();
                  if (bc) {
                    bc.postMessage({
                      type: "deep_research_completed",
                      payload: {
                        reportId: deepResearchResponse.report_id,
                        conversationId,
                      },
                    });
                  }

                  set((state) => ({
                    conversations: state.conversations.map((c) =>
                      c.conversation_id === conversationId
                        ? {
                            ...c,
                            messages: (c.messages || []).map((m) =>
                              m.message_id === assistantMsgId
                                ? {
                                    ...m,
                                    status: "completed" as const,
                                    metadata: {
                                      ...m.metadata,
                                      research_status: "completed",
                                    },
                                  }
                                : m
                            ),
                          }
                        : c
                    ),
                    activeEventSource: null,
                  }));
                  return;

                case "failed":
                  streamContent += `\n\n❌ **Research Failed**\n${data.data.error_message}\n`;
                  eventSource.close();

                  // Clear partial results on failure
                  get().clearPartialResults(deepResearchResponse.report_id);

                  // Broadcast failure to other tabs
                  const { broadcastChannel: bcFailed } = get();
                  if (bcFailed) {
                    bcFailed.postMessage({
                      type: "deep_research_failed",
                      payload: {
                        reportId: deepResearchResponse.report_id,
                        conversationId,
                      },
                    });
                  }

                  set((state) => ({
                    conversations: state.conversations.map((c) =>
                      c.conversation_id === conversationId
                        ? {
                            ...c,
                            messages: (c.messages || []).map((m) =>
                              m.message_id === assistantMsgId
                                ? {
                                    ...m,
                                    status: "failed" as const,
                                    metadata: {
                                      ...m.metadata,
                                      research_status: "failed",
                                    },
                                  }
                                : m
                            ),
                          }
                        : c
                    ),
                    activeEventSource: null,
                  }));
                  return;
              }

              // Update message content
              set((state) => ({
                conversations: state.conversations.map((c) =>
                  c.conversation_id === conversationId
                    ? {
                        ...c,
                        messages: (c.messages || []).map((m) =>
                          m.message_id === assistantMsgId
                            ? { ...m, content: streamContent }
                            : m
                        ),
                      }
                    : c
                ),
              }));
            } catch (e) {
              console.error("[Store] Failed to parse SSE event:", e);
            }
          };

          eventSource.onerror = (error) => {
            console.error("[Store] SSE error:", error);
            eventSource.close();

            // Attempt automatic reconnection with exponential backoff
            // Increased from 5 to 10 attempts to support long-running research
            const MAX_RECONNECT_ATTEMPTS = 10;
            const currentAttempts = get().sseReconnectAttempts;

            if (currentAttempts < MAX_RECONNECT_ATTEMPTS) {
              // Calculate backoff delay (2s, 4s, 8s, 16s, 32s)
              const backoffDelay = Math.min(2000 * Math.pow(2, currentAttempts), 32000);

              console.log(
                `[Store] SSE connection lost. Attempting reconnection ${currentAttempts + 1}/${MAX_RECONNECT_ATTEMPTS} in ${backoffDelay}ms...`
              );

              // Update UI to show reconnecting status
              set((state) => ({
                conversations: state.conversations.map((c) =>
                  c.conversation_id === conversationId
                    ? {
                        ...c,
                        messages: (c.messages || []).map((m) =>
                          m.message_id === assistantMsgId
                            ? {
                                ...m,
                                content: streamContent + `\n\n🔄 Connection lost. Reconnecting (${currentAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})...`,
                              }
                            : m
                        ),
                      }
                    : c
                ),
                activeEventSource: null,
                sseReconnectAttempts: currentAttempts + 1,
              }));

              // Schedule reconnection
              const timeoutId = setTimeout(() => {
                console.log(`[Store] Reconnecting to deep research stream (attempt ${currentAttempts + 1})...`);
                get().reconnectDeepResearch(conversationId, deepResearchResponse.report_id, assistantMsgId, streamContent);
              }, backoffDelay);

              set({ sseReconnectTimeoutId: timeoutId as any });
            } else {
              // Max attempts reached, mark as failed
              console.error("[Store] Max reconnection attempts reached. Marking as failed.");

              set((state) => ({
                conversations: state.conversations.map((c) =>
                  c.conversation_id === conversationId
                    ? {
                        ...c,
                        messages: (c.messages || []).map((m) =>
                          m.message_id === assistantMsgId
                            ? {
                                ...m,
                                status: "failed" as const,
                                content: streamContent + "\n\n❌ Connection lost after multiple reconnection attempts",
                              }
                            : m
                        ),
                      }
                    : c
                ),
                activeEventSource: null,
                error: "Deep research connection lost",
                sseReconnectAttempts: 0,
              }));
            }
          };
        } catch (error) {
          console.error("[Store] Failed to start deep research:", error);
          set({
            error: error instanceof Error ? error.message : "Failed to start deep research",
            isLoading: false,
          });
        }
      },

      // Check for ongoing deep research and reconnect if needed
      checkAndReconnectDeepResearch: async (conversationId: string, messages: Message[]) => {
        // Don't reconnect if we already have an active EventSource
        if (get().activeEventSource) {
          console.log("[Store] EventSource already active, skipping reconnection");
          return;
        }

        // Find the last assistant message with deep research metadata
        const lastAssistantMessage = [...messages]
          .reverse()
          .find((m) => m.role === "assistant" && m.metadata?.deep_research_report_id);

        if (!lastAssistantMessage) {
          return; // No deep research in progress
        }

        const reportId = lastAssistantMessage.metadata?.deep_research_report_id;
        const researchStatus = lastAssistantMessage.metadata?.research_status;

        console.log("[Store] Found deep research message:", {
          reportId,
          researchStatus,
          messageStatus: lastAssistantMessage.status,
        });

        // Only reconnect if the research is in progress or pending
        if (researchStatus === "in_progress" || researchStatus === "pending") {
          try {
            // Check the actual status from the backend
            const report = await chatAPI.getDeepResearchReport(reportId);
            console.log("[Store] Deep research report status:", report.research_status);

            if (report.research_status === "in_progress" || report.research_status === "pending") {
              console.log("[Store] Reconnecting to deep research stream:", reportId);
              await get().reconnectDeepResearch(
                conversationId,
                reportId,
                lastAssistantMessage.message_id,
                lastAssistantMessage.content
              );
            }
          } catch (error) {
            console.error("[Store] Failed to check deep research status:", error);
            // Don't throw, just log the error
          }
        }
      },

      // Reconnect to an existing deep research stream
      reconnectDeepResearch: async (
        conversationId: string,
        reportId: string,
        assistantMsgId: string,
        existingContent: string
      ) => {
        console.log("[Store] Reconnecting to deep research:", reportId);

        // Try to load partial results from localStorage
        const partialResults = get().loadPartialResults(reportId);
        let streamContent = existingContent || partialResults?.content || `🔬 **Deep Research Report**\n\n`;

        if (partialResults) {
          console.log("[Store] Restored partial results from localStorage");
        }

        // Connect to SSE stream for updates
        const eventSource = chatAPI.connectDeepResearchStream(reportId);

        set({ activeEventSource: eventSource });

        // Start heartbeat monitoring
        get().startHeartbeatMonitoring(reportId, conversationId, assistantMsgId);

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            // Reset reconnection counter on successful message
            if (get().sseReconnectAttempts > 0) {
              console.log("[Store] SSE connection stable, resetting reconnection counter");
              set({ sseReconnectAttempts: 0 });
            }

            switch (data.event) {
              case "heartbeat":
                // Heartbeat event - connection is alive, reset timeout monitoring
                console.debug(`[Store] Heartbeat received (uptime: ${data.data.uptime_seconds}s)`);
                get().resetHeartbeat(reportId, conversationId, assistantMsgId);
                break;

              case "phase_started":
                streamContent += `\n**Phase:** ${data.data.message}\n`;
                break;

              case "phase_completed":
                streamContent += `✓ ${data.data.message} (${data.data.duration_ms}ms)\n`;
                break;

              case "query_executed":
                streamContent += `📊 Query: "${data.data.query}" (${data.data.results_count} results)\n`;
                break;

              case "progress_update":
                streamContent += `\n**Progress:** ${data.data.progress_percentage.toFixed(1)}% - ${data.data.sources_collected} sources collected\n`;
                break;

              case "section_content":
                streamContent += data.data.content_chunk;
                // Save partial results for crash recovery
                get().savePartialResults(reportId, streamContent, {
                  conversationId,
                  assistantMsgId,
                  status: "in_progress",
                });
                break;

              case "completed":
                streamContent += `\n\n---\n\n✅ **Research Complete**\n`;
                streamContent += `- Total sections: ${data.data.total_sections}\n`;
                streamContent += `- Total sources: ${data.data.total_sources}\n`;
                streamContent += `- Processing time: ${(data.data.processing_time_ms / 1000).toFixed(2)}s\n`;
                eventSource.close();

                // Clear partial results on completion
                get().clearPartialResults(reportId);

                // Broadcast completion to other tabs
                const { broadcastChannel: bcComplete } = get();
                if (bcComplete) {
                  bcComplete.postMessage({
                    type: "deep_research_completed",
                    payload: {
                      reportId,
                      conversationId,
                    },
                  });
                }

                set((state) => ({
                  conversations: state.conversations.map((c) =>
                    c.conversation_id === conversationId
                      ? {
                          ...c,
                          messages: (c.messages || []).map((m) =>
                            m.message_id === assistantMsgId
                              ? {
                                  ...m,
                                  status: "completed" as const,
                                  metadata: {
                                    ...m.metadata,
                                    research_status: "completed",
                                  },
                                }
                              : m
                          ),
                        }
                      : c
                  ),
                  activeEventSource: null,
                }));
                return;

              case "failed":
                streamContent += `\n\n❌ **Research Failed**\n${data.data.error_message}\n`;
                eventSource.close();

                // Clear partial results on failure
                get().clearPartialResults(reportId);

                // Broadcast failure to other tabs
                const { broadcastChannel: bcFail } = get();
                if (bcFail) {
                  bcFail.postMessage({
                    type: "deep_research_failed",
                    payload: {
                      reportId,
                      conversationId,
                    },
                  });
                }

                set((state) => ({
                  conversations: state.conversations.map((c) =>
                    c.conversation_id === conversationId
                      ? {
                          ...c,
                          messages: (c.messages || []).map((m) =>
                            m.message_id === assistantMsgId
                              ? {
                                  ...m,
                                  status: "failed" as const,
                                  metadata: {
                                    ...m.metadata,
                                    research_status: "failed",
                                  },
                                }
                              : m
                          ),
                        }
                      : c
                  ),
                  activeEventSource: null,
                }));
                return;
            }

            // Update message content
            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.conversation_id === conversationId
                  ? {
                      ...c,
                      messages: (c.messages || []).map((m) =>
                        m.message_id === assistantMsgId
                          ? { ...m, content: streamContent }
                          : m
                      ),
                    }
                  : c
              ),
            }));
          } catch (e) {
            console.error("[Store] Failed to parse SSE event:", e);
          }
        };

        eventSource.onerror = (error) => {
          console.error("[Store] SSE reconnection error:", error);
          eventSource.close();

          // Attempt automatic reconnection with exponential backoff
          // Increased from 5 to 10 attempts to support long-running research
          const MAX_RECONNECT_ATTEMPTS = 10;
          const currentAttempts = get().sseReconnectAttempts;

          if (currentAttempts < MAX_RECONNECT_ATTEMPTS) {
            // Calculate backoff delay (2s, 4s, 8s, 16s, 32s)
            const backoffDelay = Math.min(2000 * Math.pow(2, currentAttempts), 32000);

            console.log(
              `[Store] SSE reconnection error. Attempting reconnection ${currentAttempts + 1}/${MAX_RECONNECT_ATTEMPTS} in ${backoffDelay}ms...`
            );

            // Update UI to show reconnecting status
            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.conversation_id === conversationId
                  ? {
                      ...c,
                      messages: (c.messages || []).map((m) =>
                        m.message_id === assistantMsgId
                          ? {
                              ...m,
                              content: streamContent + `\n\n🔄 Connection lost. Reconnecting (${currentAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})...`,
                            }
                          : m
                      ),
                    }
                  : c
              ),
              activeEventSource: null,
              sseReconnectAttempts: currentAttempts + 1,
            }));

            // Schedule reconnection
            const timeoutId = setTimeout(() => {
              console.log(`[Store] Retrying reconnection (attempt ${currentAttempts + 1})...`);
              get().reconnectDeepResearch(conversationId, reportId, assistantMsgId, streamContent);
            }, backoffDelay);

            set({ sseReconnectTimeoutId: timeoutId as any });
          } else {
            // Max attempts reached, mark as failed
            console.error("[Store] Max reconnection attempts reached. Marking as failed.");

            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.conversation_id === conversationId
                  ? {
                      ...c,
                      messages: (c.messages || []).map((m) =>
                        m.message_id === assistantMsgId
                          ? {
                              ...m,
                              status: "failed" as const,
                              content: streamContent + "\n\n❌ Connection lost after multiple reconnection attempts",
                            }
                          : m
                      ),
                    }
                  : c
              ),
              activeEventSource: null,
              error: "Deep research connection lost",
              sseReconnectAttempts: 0,
            }));
          }
        };
      },

      /**
       * @deprecated Use sendMessage() instead. It now automatically handles streaming based on settings.
       * This method is kept for backward compatibility and redirects to sendMessage().
       */
      sendStreamingMessage: async (content: string) => {
        console.warn("[Store] sendStreamingMessage is deprecated. Use sendMessage() instead.");

        // Temporarily enable streaming if not already enabled
        const { settings } = get();
        const wasStreamingEnabled = settings.stream;

        if (!wasStreamingEnabled) {
          get().updateSettings({ stream: true });
        }

        try {
          await get().sendMessage(content);
        } finally {
          // Restore original setting
          if (!wasStreamingEnabled) {
            get().updateSettings({ stream: false });
          }
        }
      },

      regenerateMessage: async (messageId: string) => {
        const { currentConversationId } = get();
        if (!currentConversationId) return;

        set({ isLoading: true, error: null });

        try {
          const newMessageResponse = await chatAPI.regenerateMessage(
            currentConversationId,
            messageId
          );

          const newMessage = toMessage(newMessageResponse);

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === currentConversationId
                ? {
                    ...c,
                    messages: c.messages?.map((m) =>
                      m.message_id === messageId ? newMessage : m
                    ),
                  }
                : c
            ),
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to regenerate message";
          set({ error: errorMessage, isLoading: false });
        }
      },

      editMessage: async (messageId: string, newContent: string) => {
        const { currentConversationId, currentUserId } = get();
        if (!currentConversationId) return;

        set({ isLoading: true, error: null });

        try {
          const updatedMessageResponse = await chatAPI.editMessage(messageId, newContent, {
            user_id: currentUserId,
          });

          const updatedMessage = toMessage(updatedMessageResponse);

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === currentConversationId
                ? {
                    ...c,
                    messages: c.messages?.map((m) =>
                      m.message_id === messageId ? updatedMessage : m
                    ),
                  }
                : c
            ),
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to edit message";
          set({ error: errorMessage, isLoading: false });
        }
      },

      addFeedback: async (
        messageId: string,
        feedback: "positive" | "negative" | "neutral",
        comment?: string
      ) => {
        try {
          const updatedMessageResponse = await chatAPI.addFeedback(
            messageId,
            feedback,
            comment
          );

          const updatedMessage = toMessage(updatedMessageResponse);
          const { currentConversationId } = get();
          if (!currentConversationId) return;

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === currentConversationId
                ? {
                    ...c,
                    messages: c.messages?.map((m) =>
                      m.message_id === messageId ? updatedMessage : m
                    ),
                  }
                : c
            ),
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to add feedback";
          set({ error: errorMessage });
        }
      },

      // ======================================================================
      // Settings Actions
      // ======================================================================
      updateSettings: (newSettings: Partial<ChatSettings>) => {
        set((state) => ({
          settings: { ...state.settings, ...newSettings },
        }));
      },

      setChatMode: (mode: ChatMode) => {
        set((state) => ({
          settings: { ...state.settings, mode },
        }));
      },

      /**
       * Update the current user ID (called when authentication changes)
       */
      setUserId: (userId: string) => {
        set({ currentUserId: userId });
        // Reload conversations for the new user
        get().loadConversations();
      },

      // ======================================================================
      // Utility Actions
      // ======================================================================
      clearError: () => {
        set({ error: null });
      },

      // ======================================================================
      // Connection Management - New Features
      // ======================================================================

      /**
       * Setup network online/offline listeners for automatic reconnection
       */
      setupNetworkListeners: () => {
        if (typeof window === "undefined") return;

        const handleOnline = () => {
          console.log("[Store] Network connection restored");
          set({ isOnline: true });

          // Attempt to reconnect to any ongoing deep research
          const { currentConversationId, currentConversation } = get();
          if (currentConversationId && currentConversation?.messages) {
            console.log("[Store] Attempting to reconnect after network restoration");
            get().checkAndReconnectDeepResearch(currentConversationId, currentConversation.messages);
          }
        };

        const handleOffline = () => {
          console.log("[Store] Network connection lost");
          set({ isOnline: false });
        };

        window.addEventListener("online", handleOnline);
        window.addEventListener("offline", handleOffline);

        console.log("[Store] Network listeners setup complete");

        // Return cleanup function
        return () => {
          window.removeEventListener("online", handleOnline);
          window.removeEventListener("offline", handleOffline);
        };
      },

      /**
       * Setup BroadcastChannel for multi-tab synchronization
       */
      setupBroadcastChannel: () => {
        if (typeof window === "undefined" || !("BroadcastChannel" in window)) {
          console.warn("[Store] BroadcastChannel not supported in this environment");
          return;
        }

        // Close existing channel if any
        const existingChannel = get().broadcastChannel;
        if (existingChannel) {
          existingChannel.close();
        }

        const channel = new BroadcastChannel("neos-deep-research");
        set({ broadcastChannel: channel });

        channel.onmessage = (event) => {
          const { type, payload } = event.data;

          switch (type) {
            case "deep_research_started":
              console.log("[Store] Another tab started deep research:", payload.reportId);
              // Check if we should close our connection to avoid duplicates
              const { activeEventSource } = get();
              if (activeEventSource && payload.reportId) {
                const currentMessages = get().currentConversation?.messages || [];
                const currentReport = currentMessages.find(
                  (m) => m.metadata?.deep_research_report_id === payload.reportId
                );
                if (currentReport) {
                  console.log("[Store] Closing duplicate connection in this tab");
                  activeEventSource.close();
                  set({ activeEventSource: null });
                }
              }
              break;

            case "deep_research_completed":
              console.log("[Store] Deep research completed in another tab:", payload.reportId);
              // Reload messages to get the completed result
              const { currentConversationId } = get();
              if (currentConversationId && payload.conversationId === currentConversationId) {
                get().loadMessages(currentConversationId);
              }
              break;

            case "deep_research_failed":
              console.log("[Store] Deep research failed in another tab:", payload.reportId);
              break;

            default:
              console.debug("[Store] Unknown broadcast message type:", type);
          }
        };

        console.log("[Store] BroadcastChannel setup complete");
      },

      /**
       * Start heartbeat timeout monitoring
       * Triggers reconnection if no heartbeat received within timeout period
       */
      startHeartbeatMonitoring: (reportId: string, conversationId: string, assistantMsgId: string) => {
        const HEARTBEAT_TIMEOUT_MS = 30000; // 30 seconds

        // Clear existing timeout
        const existingTimeoutId = get().heartbeatTimeoutId;
        if (existingTimeoutId) {
          clearTimeout(existingTimeoutId);
        }

        // Set new timestamp
        set({ lastHeartbeatTimestamp: Date.now() });

        // Schedule timeout check
        const timeoutId = setTimeout(() => {
          const { lastHeartbeatTimestamp, activeEventSource } = get();
          const timeSinceLastHeartbeat = Date.now() - (lastHeartbeatTimestamp || 0);

          if (timeSinceLastHeartbeat > HEARTBEAT_TIMEOUT_MS && activeEventSource) {
            console.warn(
              `[Store] No heartbeat received for ${timeSinceLastHeartbeat}ms. Triggering reconnection...`
            );

            // Close stale connection
            activeEventSource.close();
            set({ activeEventSource: null });

            // Get current content before reconnecting
            const currentMessages = get().currentConversation?.messages || [];
            const currentMessage = currentMessages.find((m) => m.message_id === assistantMsgId);
            const currentContent = currentMessage?.content || "";

            // Trigger reconnection
            get().reconnectDeepResearch(conversationId, reportId, assistantMsgId, currentContent);
          }
        }, HEARTBEAT_TIMEOUT_MS) as any;

        set({ heartbeatTimeoutId: timeoutId });
      },

      /**
       * Reset heartbeat timestamp (called when heartbeat received)
       */
      resetHeartbeat: (reportId: string, conversationId: string, assistantMsgId: string) => {
        set({ lastHeartbeatTimestamp: Date.now() });

        // Restart monitoring
        get().startHeartbeatMonitoring(reportId, conversationId, assistantMsgId);
      },

      /**
       * Save partial research results to localStorage for crash recovery
       */
      savePartialResults: (reportId: string, content: string, metadata: any) => {
        if (typeof window === "undefined") return;

        try {
          const partialData = {
            reportId,
            content,
            metadata,
            timestamp: Date.now(),
          };

          localStorage.setItem(`deep-research-partial-${reportId}`, JSON.stringify(partialData));
          console.debug("[Store] Saved partial results for report:", reportId);
        } catch (error) {
          console.warn("[Store] Failed to save partial results:", error);
        }
      },

      /**
       * Load partial research results from localStorage
       */
      loadPartialResults: (reportId: string): { content: string; metadata: any } | null => {
        if (typeof window === "undefined") return null;

        try {
          const stored = localStorage.getItem(`deep-research-partial-${reportId}`);
          if (stored) {
            const partialData = JSON.parse(stored);
            console.log("[Store] Loaded partial results for report:", reportId);
            return {
              content: partialData.content || "",
              metadata: partialData.metadata || {},
            };
          }
        } catch (error) {
          console.warn("[Store] Failed to load partial results:", error);
        }

        return null;
      },

      /**
       * Clear partial research results from localStorage
       */
      clearPartialResults: (reportId: string) => {
        if (typeof window === "undefined") return;

        try {
          localStorage.removeItem(`deep-research-partial-${reportId}`);
          console.debug("[Store] Cleared partial results for report:", reportId);
        } catch (error) {
          console.warn("[Store] Failed to clear partial results:", error);
        }
      },

      cleanupEventSource: () => {
        const { activeEventSource, sseReconnectTimeoutId, heartbeatTimeoutId } = get();
        if (activeEventSource) {
          console.log("[Store] Cleaning up active EventSource");
          activeEventSource.close();
          set({ activeEventSource: null });
        }
        if (sseReconnectTimeoutId) {
          console.log("[Store] Clearing SSE reconnection timeout");
          clearTimeout(sseReconnectTimeoutId);
          set({ sseReconnectTimeoutId: null, sseReconnectAttempts: 0 });
        }
        if (heartbeatTimeoutId) {
          console.log("[Store] Clearing heartbeat timeout");
          clearTimeout(heartbeatTimeoutId);
          set({ heartbeatTimeoutId: null, lastHeartbeatTimestamp: null });
        }
      },

      stopGeneration: () => {
        const { currentAbortController, isStreaming, activeEventSource } = get();

        console.log("[Store] Stop generation requested", {
          hasAbortController: !!currentAbortController,
          isStreaming,
          hasEventSource: !!activeEventSource,
        });

        // Abort ongoing fetch request
        if (currentAbortController) {
          console.log("[Store] Aborting current request");
          currentAbortController.abort();
          set({ currentAbortController: null });
        }

        // Close EventSource for deep research
        if (activeEventSource) {
          console.log("[Store] Closing EventSource");
          activeEventSource.close();
          set({ activeEventSource: null });
        }

        // Update state
        if (isStreaming) {
          set({
            isStreaming: false,
            isLoading: false,
          });
        }
      },
    }),
    {
      name: "neos-chat-storage",
      partialize: (state) => ({
        conversations: state.conversations
          // Filter out deleted and archived conversations from persistence
          .filter((c) => c.status !== "deleted" && c.status !== "archived")
          .map((c) => ({
            ...c,
            messages: undefined, // Don't persist messages
          })),
        currentConversationId: state.currentConversationId,
        currentUserId: state.currentUserId,
        settings: state.settings,
      }),
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<ChatStore>;

        // Ensure all loaded conversations have messages initialized as empty arrays
        const loadedConversations = (persisted.conversations || [])
          // Filter out deleted/archived conversations on load
          .filter((c) => c.status !== "deleted" && c.status !== "archived")
          .map((c) => ({
            ...c,
            messages: [], // Always start with empty messages (will be loaded from server)
          }));

        return {
          ...currentState,
          // Only merge data fields, preserve getters and functions from currentState
          conversations: loadedConversations,
          currentConversationId: persisted.currentConversationId || null,
          currentUserId: persisted.currentUserId || DEFAULT_USER_ID,
          settings: persisted.settings || DEFAULT_SETTINGS,
        };
      },
    }
  )
);
