/**
 * Unit tests for chat-store.ts
 * Tests the Strategy Pattern implementation for streaming/non-streaming messages
 */

import { useChatStore } from '../chat-store';
import { chatAPI } from '@/lib/api/chat-api';

// Mock the chat API
jest.mock('@/lib/api/chat-api', () => ({
  chatAPI: {
    createConversation: jest.fn(),
    sendMessage: jest.fn(),
    sendMessageStream: jest.fn(),
    sendRAGMessage: jest.fn(),
    sendRAGMessageStream: jest.fn(),
    sendSimilarityMessage: jest.fn(),
    sendSimilarityMessageStream: jest.fn(),
    startDeepResearch: jest.fn(),
    connectDeepResearchStream: jest.fn(),
  },
}));

describe('ChatStore - Strategy Pattern Tests', () => {
  beforeEach(() => {
    // Reset store state before each test
    const store = useChatStore.getState();
    useChatStore.setState({
      conversations: [],
      currentConversationId: null,
      currentUserId: 'test-user',
      isLoading: false,
      isStreaming: false,
      error: null,
      settings: {
        mode: 'standard',
        model_name: 'claude-sonnet-4-5-20250929',
        temperature: 0.7,
        stream: true, // Default is streaming
        rag_enabled: true,
        rag_top_k: 3,
        rag_cross_conversation: false,
        similarity_top_k: 3,
        similarity_threshold: 0.7,
        similarity_cross_conversation: false,
        enable_auto_embedding: true,
      },
      activeEventSource: null,
    });

    // Clear all mocks
    jest.clearAllMocks();
  });

  describe('Default Settings', () => {
    it('should have streaming enabled by default', () => {
      const { settings } = useChatStore.getState();
      expect(settings.stream).toBe(true);
    });
  });

  describe('sendMessage - Strategy Pattern Selection', () => {
    it('should call _sendMessageWithStreaming when stream is true', async () => {
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup: Create a conversation first
      useChatStore.setState({
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock streaming response
      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"start","message_id":"msg-123"}\n\n'),
          })
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"content","content":"Hello"}\n\n'),
          })
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"complete","user_message_id":"user-123","assistant_message_id":"msg-123"}\n\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
      };

      const mockStream = {
        getReader: jest.fn(() => mockReader),
      };

      (chatAPI.sendMessageStream as jest.Mock).mockResolvedValue(mockStream);

      // Act
      await store.sendMessage('Hello, world!');

      // Assert
      expect(chatAPI.sendMessageStream).toHaveBeenCalledWith(
        mockConversationId,
        { content: 'Hello, world!' }
      );
      expect(chatAPI.sendMessage).not.toHaveBeenCalled();
    });

    it('should call _sendMessageWithoutStreaming when stream is false', async () => {
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup: Disable streaming
      useChatStore.setState({
        settings: {
          ...store.settings,
          stream: false,
        },
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock non-streaming response
      (chatAPI.sendMessage as jest.Mock).mockResolvedValue({
        success: true,
        user_message: {
          message_id: 'user-123',
          conversation_id: mockConversationId,
          role: 'user',
          content: 'Hello, world!',
          content_type: 'text',
          sequence_number: 0,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        assistant_message: {
          message_id: 'assistant-123',
          conversation_id: mockConversationId,
          role: 'assistant',
          content: 'Hello! How can I help you?',
          content_type: 'text',
          sequence_number: 1,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        conversation_id: mockConversationId,
        errors: [],
      });

      // Act
      await store.sendMessage('Hello, world!');

      // Assert
      expect(chatAPI.sendMessage).toHaveBeenCalledWith(
        mockConversationId,
        { content: 'Hello, world!' }
      );
      expect(chatAPI.sendMessageStream).not.toHaveBeenCalled();
    });

    it('should call sendDeepResearchMessage for deep_research mode', async () => {
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup: Set deep research mode
      useChatStore.setState({
        settings: {
          ...store.settings,
          mode: 'deep_research',
        },
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock deep research response
      const mockEventSource = {
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        close: jest.fn(),
        onmessage: null,
        onerror: null,
      };

      (chatAPI.startDeepResearch as jest.Mock).mockResolvedValue({
        success: true,
        report_id: 'report-123',
        user_message_id: 'user-123',
        assistant_message_id: 'assistant-123',
        research_topic: 'AI research',
        research_status: 'in_progress',
        message: 'Research started',
        stream_url: '/api/v1/deep-research/report-123/stream',
      });

      (chatAPI.connectDeepResearchStream as jest.Mock).mockReturnValue(mockEventSource);

      // Act
      await store.sendMessage('Research AI trends');

      // Assert
      expect(chatAPI.startDeepResearch).toHaveBeenCalledWith({
        user_id: 'test-user',
        conversation_id: mockConversationId,
        initial_message_id: '',
        research_topic: 'Research AI trends',
        session_id: expect.stringContaining('session_'),
      });
      expect(chatAPI.sendMessage).not.toHaveBeenCalled();
      expect(chatAPI.sendMessageStream).not.toHaveBeenCalled();
    });
  });

  describe('RAG Mode', () => {
    it('should use RAG streaming endpoint when mode is rag and stream is true', async () => {
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup: Set RAG mode
      useChatStore.setState({
        settings: {
          ...store.settings,
          mode: 'rag',
          stream: true,
        },
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock streaming response
      const mockReader = {
        read: jest.fn().mockResolvedValue({ done: true }),
      };

      const mockStream = {
        getReader: jest.fn(() => mockReader),
      };

      (chatAPI.sendRAGMessageStream as jest.Mock).mockResolvedValue(mockStream);

      // Act
      await store.sendMessage('Test RAG message');

      // Assert
      expect(chatAPI.sendRAGMessageStream).toHaveBeenCalledWith(
        mockConversationId,
        {
          content: 'Test RAG message',
          enable_rag: true,
          rag_top_k: 3,
          include_cross_conversation: false,
        }
      );
    });

    it('should use RAG non-streaming endpoint when mode is rag and stream is false', async () => {
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup: Set RAG mode with streaming disabled
      useChatStore.setState({
        settings: {
          ...store.settings,
          mode: 'rag',
          stream: false,
        },
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock non-streaming response
      (chatAPI.sendRAGMessage as jest.Mock).mockResolvedValue({
        success: true,
        user_message: {
          message_id: 'user-123',
          conversation_id: mockConversationId,
          role: 'user',
          content: 'Test RAG message',
          content_type: 'text',
          sequence_number: 0,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        assistant_message: {
          message_id: 'assistant-123',
          conversation_id: mockConversationId,
          role: 'assistant',
          content: 'RAG response',
          content_type: 'text',
          sequence_number: 1,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        conversation_id: mockConversationId,
        errors: [],
        rag_enabled: true,
      });

      // Act
      await store.sendMessage('Test RAG message');

      // Assert
      expect(chatAPI.sendRAGMessage).toHaveBeenCalledWith(
        mockConversationId,
        {
          content: 'Test RAG message',
          enable_rag: true,
          rag_top_k: 3,
          include_cross_conversation: false,
        }
      );
    });
  });

  describe('Deprecated sendStreamingMessage', () => {
    it('should log deprecation warning and redirect to sendMessage', async () => {
      const consoleSpy = jest.spyOn(console, 'warn').mockImplementation();
      const store = useChatStore.getState();
      const mockConversationId = 'conv-123';

      // Setup
      useChatStore.setState({
        conversations: [{
          conversation_id: mockConversationId,
          user_id: 'test-user',
          title: 'Test',
          model_name: 'claude-sonnet-4-5-20250929',
          status: 'active' as const,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          participant_count: 1,
          total_tokens: 0,
          total_cost_usd: 0,
          is_pinned: false,
          tags: [],
          metadata: {},
          messages: [],
        }],
        currentConversationId: mockConversationId,
      });

      // Mock streaming response
      const mockReader = {
        read: jest.fn().mockResolvedValue({ done: true }),
      };

      const mockStream = {
        getReader: jest.fn(() => mockReader),
      };

      (chatAPI.sendMessageStream as jest.Mock).mockResolvedValue(mockStream);

      // Act
      await store.sendStreamingMessage('Test message');

      // Assert
      expect(consoleSpy).toHaveBeenCalledWith(
        '[Store] sendStreamingMessage is deprecated. Use sendMessage() instead.'
      );

      consoleSpy.mockRestore();
    });
  });

  describe('Conversation Creation', () => {
    it('should create conversation if none exists when sending a message', async () => {
      const store = useChatStore.getState();

      // Mock conversation creation
      (chatAPI.createConversation as jest.Mock).mockResolvedValue({
        conversation_id: 'new-conv-123',
        user_id: 'test-user',
        title: 'New Chat',
        model_name: 'claude-sonnet-4-5-20250929',
        status: 'active',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        message_count: 0,
        participant_count: 1,
        total_tokens: 0,
        total_cost_usd: 0,
        is_pinned: false,
        tags: [],
        metadata: {},
      });

      // Mock streaming response
      const mockReader = {
        read: jest.fn().mockResolvedValue({ done: true }),
      };

      const mockStream = {
        getReader: jest.fn(() => mockReader),
      };

      (chatAPI.sendMessageStream as jest.Mock).mockResolvedValue(mockStream);

      // Act
      await store.sendMessage('First message');

      // Assert - conversation should be created
      expect(chatAPI.createConversation).toHaveBeenCalled();
    });
  });
});
