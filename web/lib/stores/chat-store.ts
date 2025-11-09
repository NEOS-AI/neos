import { create } from "zustand";
import { persist } from "zustand/middleware";
import { chatAPI, type MessageResponse, type ConversationResponse } from "@/lib/api/chat-api";
import type {
  ChatStore,
  Conversation,
  Message,
  ChatSettings,
  ChatMode,
} from "@/lib/types";

const DEFAULT_USER_ID = "anonymous";

const DEFAULT_SETTINGS: ChatSettings = {
  mode: "standard",
  model_name: "claude-sonnet-4-5-20250929",
  temperature: 0.7,
  stream: false,

  // RAG defaults
  rag_enabled: true,
  rag_top_k: 3,
  rag_cross_conversation: false,

  // Similarity defaults
  similarity_top_k: 3,
  similarity_threshold: 0.7,
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
            limit: 100,
            include_archived: false,
          });

          set({
            conversations: response.conversations.map(toConversation),
            isLoading: false,
          });
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to load conversations";
          set({ error: errorMessage, isLoading: false });
        }
      },

      createConversation: async (title?: string, systemPrompt?: string) => {
        set({ isLoading: true, error: null });

        try {
          const { currentUserId, settings } = get();

          const conversationResponse = await chatAPI.createConversation({
            user_id: currentUserId,
            title: title || "New Chat",
            model_name: settings.model_name,
            system_prompt: systemPrompt,
            temperature: settings.temperature,
          });

          // Add to conversations list with empty messages
          const newConversation = toConversation(conversationResponse);

          set((state) => ({
            conversations: [newConversation, ...state.conversations],
            currentConversationId: conversationResponse.conversation_id,
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to create conversation";
          set({ error: errorMessage, isLoading: false });
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
        try {
          await chatAPI.updateConversation(conversationId, { title });

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId ? { ...c, title } : c
            ),
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error
              ? error.message
              : "Failed to update conversation title";
          set({ error: errorMessage });
        }
      },

      archiveConversation: async (conversationId: string) => {
        try {
          await chatAPI.archiveConversation(conversationId);

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? { ...c, status: "archived" }
                : c
            ),
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error
              ? error.message
              : "Failed to archive conversation";
          set({ error: errorMessage });
        }
      },

      deleteConversation: async (conversationId: string) => {
        try {
          await chatAPI.deleteConversation(conversationId);

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
        } catch (error) {
          const errorMessage =
            error instanceof Error
              ? error.message
              : "Failed to delete conversation";
          set({ error: errorMessage });
        }
      },

      // ======================================================================
      // Message Actions
      // ======================================================================
      loadMessages: async (conversationId: string) => {
        set({ isLoading: true, error: null });

        try {
          const messagesResponse = await chatAPI.getMessages(conversationId, { limit: 100 });
          const messages = messagesResponse.map(toMessage);

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId ? { ...c, messages } : c
            ),
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to load messages";
          set({ error: errorMessage, isLoading: false });
        }
      },

      sendMessage: async (content: string) => {
        const { currentConversationId, settings } = get();

        // Create conversation if none exists
        if (!currentConversationId) {
          console.log("[Store] No conversation exists, creating one...");
          await get().createConversation();
          // Wait for conversation creation
          await new Promise((resolve) => setTimeout(resolve, 100));
        }

        const conversationId = get().currentConversationId;
        if (!conversationId) {
          console.error("[Store] Failed to create conversation");
          set({ error: "No active conversation" });
          return;
        }

        console.log("[Store] Sending message to conversation:", conversationId);
        set({ isLoading: true, error: null });

        try {
          let response;

          // Send based on chat mode
          switch (settings.mode) {
            case "rag":
              console.log("[Store] Sending RAG message...");
              response = await chatAPI.sendRAGMessage(conversationId, {
                content,
                enable_rag: settings.rag_enabled,
                rag_top_k: settings.rag_top_k,
                include_cross_conversation: settings.rag_cross_conversation,
              });
              break;

            case "similarity":
              console.log("[Store] Sending similarity message...");
              response = await chatAPI.sendSimilarityMessage(conversationId, {
                content,
                top_k: settings.similarity_top_k,
                similarity_threshold: settings.similarity_threshold,
                include_cross_conversation: settings.similarity_cross_conversation,
                enable_auto_embedding: settings.enable_auto_embedding,
              });
              break;

            case "standard":
            default:
              console.log("[Store] Sending standard message...");
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

          console.log("[Store] Adding messages to store...");

          set((state) => {
            const targetConversation = state.conversations.find(c => c.conversation_id === conversationId);

            console.log("[Store] ===== BEFORE UPDATE =====");
            console.log("[Store] Target conversation exists:", !!targetConversation);
            console.log("[Store] Current messages count:", targetConversation?.messages?.length || 0);
            console.log("[Store] All conversation IDs:", state.conversations.map(c => c.conversation_id));

            const updatedConversations = state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: [
                      ...(c.messages || []),
                      userMessage,
                      assistantMessage,
                    ],
                    message_count: (c.message_count || 0) + 2,
                    // Update title from first message
                    title:
                      c.message_count === 0
                        ? content.slice(0, 50)
                        : c.title,
                  }
                : c
            );

            const updatedTarget = updatedConversations.find(c => c.conversation_id === conversationId);

            console.log("[Store] ===== AFTER UPDATE =====");
            console.log("[Store] Updated target exists:", !!updatedTarget);
            console.log("[Store] New messages count:", updatedTarget?.messages?.length || 0);
            console.log("[Store] Message IDs:", updatedTarget?.messages?.map(m => m.message_id.slice(0, 8)) || []);
            console.log("[Store] Full updated conversation:", updatedTarget);

            return {
              conversations: updatedConversations,
              isLoading: false,
            };
          });

          console.log("[Store] Message sent successfully");
        } catch (error) {
          console.error("[Store] Failed to send message:", error);
          const errorMessage =
            error instanceof Error ? error.message : "Failed to send message";
          set({ error: errorMessage, isLoading: false });
        }
      },

      sendStreamingMessage: async (content: string) => {
        const { currentConversationId, settings } = get();

        // Create conversation if none exists
        if (!currentConversationId) {
          await get().createConversation();
          await new Promise((resolve) => setTimeout(resolve, 100));
        }

        const conversationId = get().currentConversationId;
        if (!conversationId) {
          set({ error: "No active conversation" });
          return;
        }

        set({ isStreaming: true, isLoading: true, error: null });

        try {
          // Add user message optimistically
          const userMessage: Message = {
            message_id: `temp_${Date.now()}`,
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
            message_id: `temp_${Date.now() + 1}`,
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
              });
              break;

            case "similarity":
              stream = await chatAPI.sendSimilarityMessageStream(conversationId, {
                content,
                top_k: settings.similarity_top_k,
                similarity_threshold: settings.similarity_threshold,
                include_cross_conversation: settings.similarity_cross_conversation,
                enable_auto_embedding: settings.enable_auto_embedding,
              });
              break;

            case "standard":
            default:
              stream = await chatAPI.sendMessageStream(conversationId, { content });
              break;
          }

          // Process stream
          const reader = stream.getReader();
          const decoder = new TextDecoder();
          let accumulatedContent = "";

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
                  if (parsed.content) {
                    accumulatedContent += parsed.content;

                    // Update assistant message
                    set((state) => ({
                      conversations: state.conversations.map((c) =>
                        c.conversation_id === conversationId
                          ? {
                              ...c,
                              messages: c.messages?.map((m, idx) =>
                                idx === c.messages!.length - 1
                                  ? { ...m, content: accumulatedContent }
                                  : m
                              ),
                            }
                          : c
                      ),
                    }));
                  }
                } catch (e) {
                  // Ignore parse errors
                }
              }
            }
          }

          // Mark message as completed
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: c.messages?.map((m, idx) =>
                      idx === c.messages!.length - 1
                        ? { ...m, status: "completed" as const }
                        : m
                    ),
                  }
                : c
            ),
            isStreaming: false,
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error
              ? error.message
              : "Failed to send streaming message";
          set({ error: errorMessage, isStreaming: false, isLoading: false });
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

      // ======================================================================
      // Utility Actions
      // ======================================================================
      clearError: () => {
        set({ error: null });
      },
    }),
    {
      name: "neos-chat-storage",
      partialize: (state) => ({
        conversations: state.conversations.map((c) => ({
          ...c,
          messages: undefined, // Don't persist messages
        })),
        currentConversationId: state.currentConversationId,
        currentUserId: state.currentUserId,
        settings: state.settings,
      }),
      merge: (persistedState, currentState) => {
        // Ensure all loaded conversations have messages initialized as empty arrays
        const merged = {
          ...currentState,
          ...(persistedState as Partial<ChatStore>),
        };

        if (merged.conversations) {
          merged.conversations = merged.conversations.map((c) => ({
            ...c,
            messages: c.messages || [], // Initialize messages as empty array if undefined
          }));
        }

        return merged;
      },
    }
  )
);
