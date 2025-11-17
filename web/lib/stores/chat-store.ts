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
  stream: true, // Changed to true for streaming by default

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
      activeEventSource: null,

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

          // Filter out deleted conversations (extra safety check)
          const activeConversations = response.conversations
            .filter((c) => c.status !== "deleted")
            .map(toConversation);

          set({
            conversations: activeConversations,
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
        // Clean up any active EventSource before sending a new message
        get().cleanupEventSource();

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

        // Create conversation if none exists
        if (!conversationId) {
          console.log("[Store] No conversation exists, creating one for streaming...");

          const currentState = get();
          if (!currentState.currentConversationId) {
            await get().createConversation();
            await new Promise((resolve) => setTimeout(resolve, 100));

            conversationId = get().currentConversationId;

            if (!conversationId) {
              set({ error: "No active conversation" });
              return;
            }
          } else {
            conversationId = currentState.currentConversationId;
          }
        }

        set({ isStreaming: true, isLoading: true, error: null });

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
          }));
        } catch (error) {
          console.error("[Store] Failed to send streaming message:", error);
          const errorMessage =
            error instanceof Error
              ? error.message
              : "Failed to send streaming message";
          set({ error: errorMessage, isStreaming: false, isLoading: false });
        }
      },

      // Private method: Non-streaming strategy
      _sendMessageWithoutStreaming: async (content: string) => {
        const { settings } = get();
        let conversationId = get().currentConversationId;

        // Create conversation if none exists
        if (!conversationId) {
          console.log("[Store] No conversation exists, creating one...");

          const currentState = get();
          if (!currentState.currentConversationId) {
            await get().createConversation();
            await new Promise((resolve) => setTimeout(resolve, 100));

            conversationId = get().currentConversationId;

            if (!conversationId) {
              console.error("[Store] Failed to create conversation");
              set({ error: "No active conversation" });
              return;
            }
          } else {
            conversationId = currentState.currentConversationId;
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

        if (!conversationId) {
          await get().createConversation();
          await new Promise((resolve) => setTimeout(resolve, 100));
          conversationId = get().currentConversationId;
          if (!conversationId) {
            set({ error: "No active conversation" });
            return;
          }
        }

        console.log("[Store] Starting deep research...");

        try {
          // Start deep research - backend will create messages
          const deepResearchResponse = await chatAPI.startDeepResearch({
            user_id: get().currentUserId,
            conversation_id: conversationId,
            initial_message_id: "",
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

          set({ activeEventSource: eventSource });

          eventSource.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);

              switch (data.event) {
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
                  break;

                case "completed":
                  streamContent += `\n\n---\n\n✅ **Research Complete**\n`;
                  streamContent += `- Total sections: ${data.data.total_sections}\n`;
                  streamContent += `- Total sources: ${data.data.total_sources}\n`;
                  streamContent += `- Processing time: ${(data.data.processing_time_ms / 1000).toFixed(2)}s\n`;
                  eventSource.close();

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
                              content: streamContent + "\n\n❌ Connection lost",
                            }
                          : m
                      ),
                    }
                  : c
              ),
              activeEventSource: null,
              error: "Deep research connection lost",
            }));
          };
        } catch (error) {
          console.error("[Store] Failed to start deep research:", error);
          set({
            error: error instanceof Error ? error.message : "Failed to start deep research",
            isLoading: false,
          });
        }
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

      // ======================================================================
      // Utility Actions
      // ======================================================================
      clearError: () => {
        set({ error: null });
      },

      cleanupEventSource: () => {
        const { activeEventSource } = get();
        if (activeEventSource) {
          console.log("[Store] Cleaning up active EventSource");
          activeEventSource.close();
          set({ activeEventSource: null });
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
