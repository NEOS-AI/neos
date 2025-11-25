"use client";

import { useEffect, useCallback, useState } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import ErrorBoundary from "@/components/ErrorBoundary";
import { PageLoading } from "./LoadingStates";
import Header from "./Header";
import Sidebar from "./Sidebar";
import MessageList from "./MessageList";
import InputBox from "./InputBox";
import ChatModeSelector from "./ChatModeSelector";
import dynamic from "next/dynamic";
import { createLogger } from "@/lib/logger";

const logger = createLogger("ChatInterface");

// Dynamically import SettingsPanel for code splitting
const SettingsPanel = dynamic(() => import("./SettingsPanel"), {
  loading: () => <div className="text-xs text-claude-text-secondary">Loading settings...</div>,
  ssr: false,
});

function ChatInterfaceContent() {
  const { loadConversations, cleanupEventSource } = useChatStore();
  const [isInitializing, setIsInitializing] = useState(true);

  const initialize = useCallback(async () => {
    try {
      await loadConversations();

      const { conversations, currentConversationId, setCurrentConversation } = useChatStore.getState();

      // Don't auto-create conversations - let user start naturally by sending a message
      if (conversations.length > 0) {
        // If there are conversations but no current one is selected (or invalid),
        // select the first one to ensure the UI shows messages
        const currentExists = conversations.some(c => c.conversation_id === currentConversationId);
        if (!currentConversationId || !currentExists) {
          logger.debug("No valid conversation selected, selecting first one");
          setCurrentConversation(conversations[0].conversation_id);
        } else {
          logger.debug("Current conversation is valid", { currentConversationId });
          // Load messages for the current conversation if not loaded
          const currentConv = conversations.find(c => c.conversation_id === currentConversationId);
          if (currentConv && (!currentConv.messages || currentConv.messages.length === 0)) {
            const { loadMessages } = useChatStore.getState();
            await loadMessages(currentConversationId);
          }
        }
      }
    } catch (error) {
      logger.error("Failed to initialize chat", error);
    } finally {
      setIsInitializing(false);
    }
  }, [loadConversations]);

  useEffect(() => {
    initialize();

    // Cleanup on unmount: close any active EventSource connections
    return () => {
      logger.debug("ChatInterface unmounting, cleaning up EventSource");
      cleanupEventSource();
    };
  }, [initialize, cleanupEventSource]);

  if (isInitializing) {
    return <PageLoading />;
  }

  return (
    <div className="flex h-screen bg-claude-darker">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header with Mode Selector and Settings */}
        <div className="border-b border-claude-border bg-claude-dark">
          <div className="flex items-center justify-between px-6 py-3">
            <Header />
            <div className="flex items-center gap-3">
              <ChatModeSelector />
              <SettingsPanel />
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-hidden">
          <MessageList />
        </div>

        {/* Input */}
        <InputBox />
      </div>
    </div>
  );
}

export default function ChatInterface() {
  return (
    <ErrorBoundary>
      <ChatInterfaceContent />
    </ErrorBoundary>
  );
}
