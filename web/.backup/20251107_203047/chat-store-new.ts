import { create } from "zustand";
import { persist } from "zustand/middleware";
import { chatAPI } from "@/lib/api/chat-api";
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
        return (
          conversations.find((c) => c.conversation_id === currentConversationId) ||
          null
        );
      },

      get messages() {
        const { currentConversation } = get();
        return currentConversation?.messages || [];
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
            conversations: response.conversations,
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

          const conversation = await chatAPI.createConversation({
            user_id: currentUserId,
            title: title || "New Chat",
            model_name: settings.model_name,
            system_prompt: systemPrompt,
            temperature: settings.temperature,
          });

          // Add to conversations list with empty messages
          const newConversation: Conversation = {
            ...conversation,
            messages: [],
          };

          set((state) => ({
            conversations: [newConversation, ...state.conversations],
            currentConversationId: conversation.conversation_id,
            isLoading: false,
          }));
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Failed to create conversation";
          set({ error: errorMessage, isLoading: false });
        }
      },

      setCurrentConversation: (conversationId: string) => {
        set({ currentConversationId: conversationId });

        // Load messages if not already loaded
        const { currentConversation } = get();
        if (currentConversation && !currentConversation.messages) {
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
          const messages = await chatAPI.getMessages(conversationId, { limit: 100 });

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
          await get().createConversation();
          // Wait for conversation creation
          await new Promise((resolve) => setTimeout(resolve, 100));
        }

        const conversationId = get().currentConversationId;
        if (!conversationId) {
          set({ error: "No active conversation" });
          return;
        }

        set({ isLoading: true, error: null });

        try {
          let response;

          // Send based on chat mode
          switch (settings.mode) {
            case "rag":
              response = await chatAPI.sendRAGMessage(conversationId, {
                content,
                enable_rag: settings.rag_enabled,
                rag_top_k: settings.rag_top_k,
                include_cross_conversation: settings.rag_cross_conversation,
              });
              break;

            case "similarity":
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
              response = await chatAPI.sendMessage(conversationId, { content });
              break;
          }

          // Add messages to store
          const userMessage = response.user_message;
          const assistantMessage = response.assistant_message;

          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.conversation_id === conversationId
                ? {
                    ...c,
                    messages: [
                      ...(c.messages || []),
                      userMessage,
                      assistantMessage,
                    ],
                    // Update title from first message
                    title:
                      c.message_count === 0
                        ? content.slice(0, 50)
                        : c.title,
                  }
                : c
            ),
            isLoading: false,
          }));
        } catch (error) {
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
                        ? { ...m, status: "completed" }
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
          const newMessage = await chatAPI.regenerateMessage(
            currentConversationId,
            messageId
          );

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
          const updatedMessage = await chatAPI.editMessage(messageId, newContent, {
            user_id: currentUserId,
          });

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
          const updatedMessage = await chatAPI.addFeedback(
            messageId,
            feedback,
            comment
          );

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
    }
  )
);
