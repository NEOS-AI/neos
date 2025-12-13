"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useChatStore } from "@/lib/stores/chat-store";
import { useAuth } from "@/lib/contexts/auth-context";
import { chatAPI } from "@/lib/api/chat-api";
import ErrorBoundary from "@/components/ErrorBoundary";
import { PageLoading } from "@/components/chat/LoadingStates";
import Sidebar from "@/components/chat/Sidebar";
import MessageList from "@/components/chat/MessageList";
import InputBox from "@/components/chat/InputBox";
import ChatModeSelector from "@/components/chat/ChatModeSelector";
import SettingsPanel from "@/components/chat/SettingsPanel";


function ChatPageContent() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const chatId = params.id as string;
  const initialMessage = searchParams.get('initialMessage');
  const { isLoading: isAuthLoading } = useAuth();

  const {
    loadConversations,
    loadMessages,
    setCurrentConversation,
    currentConversationId,
    setupNetworkListeners,
    setupBroadcastChannel,
    sendMessage,
  } = useChatStore();
  const [isInitializing, setIsInitializing] = useState(true);

  // Track if initial message has been processed to prevent duplicates
  // (React Strict Mode causes useEffect to run twice in development)
  const hasProcessedInitialMessageRef = useRef(false);

  // Setup network listeners and broadcast channel on mount
  useEffect(() => {
    // Setup network listeners for online/offline detection
    const cleanupNetworkListeners = setupNetworkListeners();

    // Setup BroadcastChannel for multi-tab synchronization
    setupBroadcastChannel();

    console.log("[ChatPage] Connection management features initialized");

    // Cleanup on unmount
    return () => {
      if (cleanupNetworkListeners) {
        cleanupNetworkListeners();
      }
      // BroadcastChannel will be closed when store is cleaned up
    };
  }, [setupNetworkListeners, setupBroadcastChannel]);

  const initialize = useCallback(async () => {
    try {
      // Wait for auth to finish loading before initializing
      if (isAuthLoading) {
        console.log("[ChatPage] Waiting for auth to finish loading...");
        return;
      }

      // Load conversations first
      await loadConversations();

      let { conversations } = useChatStore.getState();

      // Check if the requested conversation exists in loaded conversations
      let conversation = conversations.find(c => c.conversation_id === chatId);

      // If not found in the list, try to load it directly from the server
      if (!conversation) {
        console.log(`[ChatPage] Conversation ${chatId} not found in list, trying direct load...`);

        try {
          // Try to fetch the conversation directly
          const conversationResponse = await chatAPI.getConversation(chatId);

          // Add it to the store
          useChatStore.setState((state) => ({
            conversations: [
              { ...conversationResponse, messages: [] },
              ...state.conversations,
            ],
          }));

          conversation = { ...conversationResponse, messages: [] };
          console.log(`[ChatPage] Successfully loaded conversation ${chatId} directly`);
        } catch (directLoadError) {
          console.error(`[ChatPage] Failed to load conversation ${chatId} directly:`, directLoadError);
          // Conversation truly doesn't exist, redirect to home
          console.error(`[ChatPage] Conversation ${chatId} not found`);
          router.push('/');
          return;
        }
      }

      // Set current conversation
      setCurrentConversation(chatId);

      // Load messages for this conversation
      await loadMessages(chatId);

      console.log(`[ChatPage] Initialized conversation: ${chatId}`);

      // Send initial message if provided via query parameter
      // Use ref to prevent duplicate sends (e.g., from React Strict Mode double-mounting)
      if (initialMessage && !hasProcessedInitialMessageRef.current) {
        console.log(`[ChatPage] Sending initial message: ${initialMessage}`);
        // Mark as processed immediately to prevent duplicates
        hasProcessedInitialMessageRef.current = true;
        // Remove the query parameter from URL
        router.replace(`/chat/${chatId}`, { scroll: false });
        // Send the message after a small delay to ensure everything is ready
        setTimeout(() => {
          sendMessage(initialMessage);
        }, 100);
      }
    } catch (error) {
      console.error("[ChatPage] Failed to initialize:", error);
      router.push('/');
    } finally {
      setIsInitializing(false);
    }
  }, [chatId, isAuthLoading, loadConversations, loadMessages, setCurrentConversation, router, initialMessage, sendMessage]);

  useEffect(() => {
    initialize();
  }, [initialize]);

  // Redirect if conversation ID changes unexpectedly
  useEffect(() => {
    if (!isInitializing && currentConversationId && currentConversationId !== chatId) {
      console.log(`[ChatPage] Conversation changed from ${chatId} to ${currentConversationId}, redirecting`);
      router.push(`/chat/${currentConversationId}`);
    }
  }, [currentConversationId, chatId, isInitializing, router]);

  if (isInitializing) {
    return <PageLoading />;
  }

  return (
    <div className="flex h-screen bg-bg-canvas">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header with Mode Selector and Settings */}
        <div className="border-b border-line-soft bg-bg-surface flex-shrink-0">
          <div className="flex items-center justify-between px-6 py-3">
            <div className="flex items-center gap-3">
              <ChatModeSelector />
              <SettingsPanel />
            </div>
          </div>
        </div>

        {/* Messages - This is where scroll should work */}
        <div className="flex-1 min-h-0">
          <MessageList />
        </div>

        {/* Input */}
        <div className="flex-shrink-0">
          <InputBox />
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <ErrorBoundary>
      <ChatPageContent />
    </ErrorBoundary>
  );
}
