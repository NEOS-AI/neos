"use client";

import { useEffect } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import Sidebar from "./Sidebar";
import MessageList from "./MessageList";
import InputBox from "./InputBox";
import Header from "./Header";

export default function ChatInterface() {
  const { currentSessionId, createSession } = useChatStore();

  // Create initial session if none exists
  useEffect(() => {
    if (!currentSessionId) {
      createSession();
    }
  }, [currentSessionId, createSession]);

  return (
    <div className="flex h-screen bg-claude-darker">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <Header />

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
