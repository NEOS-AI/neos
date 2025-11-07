"use client";

import { useEffect } from "react";
import { useChatStore } from "@/lib/stores/chat-store-new";
import Header from "./Header";
import Sidebar from "./SidebarNew";
import MessageList from "./MessageListNew";
import InputBox from "./InputBoxNew";
import ChatModeSelector from "./ChatModeSelector";
import SettingsPanel from "./SettingsPanel";

export default function ChatInterface() {
  const { currentConversation, loadConversations, createConversation } =
    useChatStore();

  useEffect(() => {
    // Initialize: load conversations and create one if none exist
    const initialize = async () => {
      await loadConversations();

      // Create initial conversation if none exist
      const { conversations } = useChatStore.getState();
      if (conversations.length === 0) {
        await createConversation();
      }
    };

    initialize();
  }, []);

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
