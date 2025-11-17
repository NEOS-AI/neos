/**
 * Tests for ChatInterface component
 */

import { render, screen, waitFor } from '@testing-library/react';
import ChatInterface from '../ChatInterface';
import { useChatStore } from '@/lib/stores/chat-store';

// Mock all child components
jest.mock('../Header', () => {
  return function Header() {
    return <div data-testid="header">Header</div>;
  };
});

jest.mock('../Sidebar', () => {
  return function Sidebar() {
    return <div data-testid="sidebar">Sidebar</div>;
  };
});

jest.mock('../MessageList', () => {
  return function MessageList() {
    return <div data-testid="message-list">MessageList</div>;
  };
});

jest.mock('../InputBox', () => {
  return function InputBox() {
    return <div data-testid="input-box">InputBox</div>;
  };
});

jest.mock('../ChatModeSelector', () => {
  return function ChatModeSelector() {
    return <div data-testid="chat-mode-selector">ChatModeSelector</div>;
  };
});

jest.mock('../SettingsPanel', () => {
  return function SettingsPanel() {
    return <div data-testid="settings-panel">SettingsPanel</div>;
  };
});

jest.mock('./LoadingStates', () => ({
  PageLoading: () => <div data-testid="page-loading">Loading...</div>,
}));

// Mock the chat store
jest.mock('@/lib/stores/chat-store');

describe('ChatInterface', () => {
  const mockLoadConversations = jest.fn();
  const mockSetCurrentConversation = jest.fn();
  const mockLoadMessages = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    // Default mock implementation
    (useChatStore as unknown as jest.Mock).mockReturnValue({
      loadConversations: mockLoadConversations,
    });

    // Mock getState
    (useChatStore as any).getState = jest.fn().mockReturnValue({
      conversations: [],
      currentConversationId: null,
      setCurrentConversation: mockSetCurrentConversation,
      loadMessages: mockLoadMessages,
    });

    mockLoadConversations.mockResolvedValue(undefined);
  });

  describe('Initialization', () => {
    it('should show loading state initially', () => {
      render(<ChatInterface />);
      expect(screen.getByTestId('page-loading')).toBeInTheDocument();
    });

    it('should load conversations on mount', async () => {
      render(<ChatInterface />);

      await waitFor(() => {
        expect(mockLoadConversations).toHaveBeenCalledTimes(1);
      });
    });

    it('should render all main components after initialization', async () => {
      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      expect(screen.getByTestId('header')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('message-list')).toBeInTheDocument();
      expect(screen.getByTestId('input-box')).toBeInTheDocument();
      expect(screen.getByTestId('chat-mode-selector')).toBeInTheDocument();
      expect(screen.getByTestId('settings-panel')).toBeInTheDocument();
    });
  });

  describe('Conversation selection', () => {
    it('should select first conversation if no current conversation exists', async () => {
      const conversations = [
        { conversation_id: 'conv-1', messages: [] },
        { conversation_id: 'conv-2', messages: [] },
      ];

      (useChatStore as any).getState = jest.fn().mockReturnValue({
        conversations,
        currentConversationId: null,
        setCurrentConversation: mockSetCurrentConversation,
        loadMessages: mockLoadMessages,
      });

      render(<ChatInterface />);

      await waitFor(() => {
        expect(mockSetCurrentConversation).toHaveBeenCalledWith('conv-1');
      });
    });

    it('should not change conversation if valid current conversation exists', async () => {
      const conversations = [
        { conversation_id: 'conv-1', messages: [{ message_id: 'msg-1' }] },
        { conversation_id: 'conv-2', messages: [] },
      ];

      (useChatStore as any).getState = jest.fn().mockReturnValue({
        conversations,
        currentConversationId: 'conv-1',
        setCurrentConversation: mockSetCurrentConversation,
        loadMessages: mockLoadMessages,
      });

      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      expect(mockSetCurrentConversation).not.toHaveBeenCalled();
    });

    it('should load messages for current conversation if not loaded', async () => {
      const conversations = [
        { conversation_id: 'conv-1', messages: [] },
      ];

      (useChatStore as any).getState = jest.fn().mockReturnValue({
        conversations,
        currentConversationId: 'conv-1',
        setCurrentConversation: mockSetCurrentConversation,
        loadMessages: mockLoadMessages,
      });

      render(<ChatInterface />);

      await waitFor(() => {
        expect(mockLoadMessages).toHaveBeenCalledWith('conv-1');
      });
    });

    it('should select first conversation if current conversation is invalid', async () => {
      const conversations = [
        { conversation_id: 'conv-1', messages: [] },
        { conversation_id: 'conv-2', messages: [] },
      ];

      (useChatStore as any).getState = jest.fn().mockReturnValue({
        conversations,
        currentConversationId: 'invalid-id',
        setCurrentConversation: mockSetCurrentConversation,
        loadMessages: mockLoadMessages,
      });

      render(<ChatInterface />);

      await waitFor(() => {
        expect(mockSetCurrentConversation).toHaveBeenCalledWith('conv-1');
      });
    });
  });

  describe('Error handling', () => {
    it('should handle initialization errors gracefully', async () => {
      const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
      mockLoadConversations.mockRejectedValue(new Error('Failed to load'));

      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Failed to initialize chat:',
        expect.any(Error)
      );

      consoleErrorSpy.mockRestore();
    });

    it('should still render UI after error', async () => {
      jest.spyOn(console, 'error').mockImplementation();
      mockLoadConversations.mockRejectedValue(new Error('Failed to load'));

      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('input-box')).toBeInTheDocument();
    });
  });

  describe('Layout', () => {
    it('should render with correct layout structure', async () => {
      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      // Check main container exists
      const container = screen.getByTestId('sidebar').parentElement;
      expect(container).toHaveClass('flex', 'h-screen');

      // Check header is in correct position
      const header = screen.getByTestId('header');
      expect(header).toBeInTheDocument();
    });
  });

  describe('Empty state', () => {
    it('should handle empty conversations array', async () => {
      (useChatStore as any).getState = jest.fn().mockReturnValue({
        conversations: [],
        currentConversationId: null,
        setCurrentConversation: mockSetCurrentConversation,
        loadMessages: mockLoadMessages,
      });

      render(<ChatInterface />);

      await waitFor(() => {
        expect(screen.queryByTestId('page-loading')).not.toBeInTheDocument();
      });

      expect(mockSetCurrentConversation).not.toHaveBeenCalled();
      expect(screen.getByTestId('message-list')).toBeInTheDocument();
    });
  });
});
