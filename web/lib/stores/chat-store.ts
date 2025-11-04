import { create } from "zustand";
import { persist } from "zustand/middleware";
import { nanoid } from "nanoid";
import type {
  ChatStore,
  ChatSession,
  Message,
  ChatResponse,
} from "@/lib/types";

const API_URL = "/api/chat";

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      // Initial state
      sessions: [],
      currentSessionId: null,
      isLoading: false,
      error: null,

      // Computed values
      get currentSession() {
        const { sessions, currentSessionId } = get();
        return sessions.find((s) => s.id === currentSessionId) || null;
      },

      get messages() {
        const { currentSession } = get();
        return currentSession?.messages || [];
      },

      // Actions
      createSession: () => {
        const newSession: ChatSession = {
          id: nanoid(),
          title: "New Chat",
          messages: [],
          createdAt: new Date(),
          updatedAt: new Date(),
        };

        set((state) => ({
          sessions: [newSession, ...state.sessions],
          currentSessionId: newSession.id,
        }));
      },

      setCurrentSession: (sessionId: string) => {
        set({ currentSessionId: sessionId });
      },

      addMessage: (message) => {
        const { currentSessionId, sessions } = get();
        if (!currentSessionId) return;

        const newMessage: Message = {
          ...message,
          id: nanoid(),
          timestamp: new Date(),
        };

        set({
          sessions: sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: [...session.messages, newMessage],
                  updatedAt: new Date(),
                  // Update title from first user message
                  title:
                    session.messages.length === 0 && message.role === "user"
                      ? message.content.slice(0, 50)
                      : session.title,
                }
              : session
          ),
        });
      },

      updateLastMessage: (content: string, metadata?: any) => {
        const { currentSessionId, sessions } = get();
        if (!currentSessionId) return;

        set({
          sessions: sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: session.messages.map((msg, idx) =>
                    idx === session.messages.length - 1
                      ? { ...msg, content, metadata: { ...msg.metadata, ...metadata } }
                      : msg
                  ),
                  updatedAt: new Date(),
                }
              : session
          ),
        });
      },

      sendMessage: async (content: string) => {
        const { currentSessionId, addMessage } = get();

        // Create a new session if none exists
        if (!currentSessionId) {
          get().createSession();
        }

        // Add user message
        addMessage({
          role: "user",
          content,
        });

        // Add temporary assistant message
        addMessage({
          role: "assistant",
          content: "...",
        });

        set({ isLoading: true, error: null });

        try {
          const response = await fetch(API_URL, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              query: content,
              session_id: get().currentSessionId,
              preferences: {
                max_iterations: 10,
                agent_timeout: 300,
                response_format: "text",
              },
            }),
          });

          if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || "Failed to send message");
          }

          const data: ChatResponse = await response.json();

          // Update the assistant message with the actual response
          get().updateLastMessage(data.response, data.metadata);
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "An error occurred";

          // Update the assistant message with error
          get().updateLastMessage(
            `Sorry, I encountered an error: ${errorMessage}`,
            { error: true }
          );

          set({ error: errorMessage });
        } finally {
          set({ isLoading: false });
        }
      },

      deleteSession: (sessionId: string) => {
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== sessionId),
          currentSessionId:
            state.currentSessionId === sessionId
              ? state.sessions[0]?.id || null
              : state.currentSessionId,
        }));
      },

      clearError: () => {
        set({ error: null });
      },
    }),
    {
      name: "neos-chat-storage",
      partialize: (state) => ({
        sessions: state.sessions,
        currentSessionId: state.currentSessionId,
      }),
    }
  )
);
