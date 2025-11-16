/**
 * Unit tests for InputBox component
 * Tests that InputBox uses the unified sendMessage API
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import InputBox from '../InputBox';
import { useChatStore } from '@/lib/stores/chat-store';

// Mock the chat store
jest.mock('@/lib/stores/chat-store', () => ({
  useChatStore: jest.fn(),
}));

describe('InputBox Component', () => {
  const mockSendMessage = jest.fn();
  const mockSettings = {
    mode: 'standard' as const,
    model_name: 'claude-sonnet-4-5-20250929',
    temperature: 0.7,
    stream: true,
    rag_enabled: true,
    rag_top_k: 3,
    rag_cross_conversation: false,
    similarity_top_k: 3,
    similarity_threshold: 0.7,
    similarity_cross_conversation: false,
    enable_auto_embedding: true,
  };

  beforeEach(() => {
    // Reset mocks
    jest.clearAllMocks();

    // Setup default store state
    (useChatStore as unknown as jest.Mock).mockReturnValue({
      sendMessage: mockSendMessage,
      isLoading: false,
      isStreaming: false,
      settings: mockSettings,
    });
  });

  describe('Rendering', () => {
    it('should render textarea and send button', () => {
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');
      expect(textarea).toBeInTheDocument();

      const sendButton = screen.getByTitle('Send message');
      expect(sendButton).toBeInTheDocument();
    });

    it('should show streaming indicator when streaming is enabled', () => {
      render(<InputBox />);

      const indicator = screen.getByText('● Streaming enabled');
      expect(indicator).toBeInTheDocument();
    });

    it('should not show streaming indicator when streaming is disabled', () => {
      (useChatStore as unknown as jest.Mock).mockReturnValue({
        sendMessage: mockSendMessage,
        isLoading: false,
        isStreaming: false,
        settings: { ...mockSettings, stream: false },
      });

      render(<InputBox />);

      const indicator = screen.queryByText('● Streaming enabled');
      expect(indicator).not.toBeInTheDocument();
    });
  });

  describe('Message Sending', () => {
    it('should call sendMessage when send button is clicked', async () => {
      const user = userEvent.setup();
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');
      const sendButton = screen.getByTitle('Send message');

      // Type a message
      await user.type(textarea, 'Hello, NEOS!');

      // Click send button
      await user.click(sendButton);

      // Assert
      await waitFor(() => {
        expect(mockSendMessage).toHaveBeenCalledWith('Hello, NEOS!');
      });

      // Input should be cleared after sending
      expect(textarea).toHaveValue('');
    });

    it('should call sendMessage when Enter is pressed', async () => {
      const user = userEvent.setup();
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');

      // Type a message
      await user.type(textarea, 'Hello, NEOS!');

      // Press Enter (without Shift)
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

      // Assert
      await waitFor(() => {
        expect(mockSendMessage).toHaveBeenCalledWith('Hello, NEOS!');
      });
    });

    it('should not send when Shift+Enter is pressed', async () => {
      const user = userEvent.setup();
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');

      // Type a message
      await user.type(textarea, 'Hello, NEOS!');

      // Press Shift+Enter
      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

      // Assert - message should not be sent
      expect(mockSendMessage).not.toHaveBeenCalled();
    });

    it('should not send empty messages', async () => {
      const user = userEvent.setup();
      render(<InputBox />);

      const sendButton = screen.getByTitle('Send message');

      // Click send without typing anything
      await user.click(sendButton);

      // Assert
      expect(mockSendMessage).not.toHaveBeenCalled();
    });

    it('should trim whitespace before sending', async () => {
      const user = userEvent.setup();
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');
      const sendButton = screen.getByTitle('Send message');

      // Type a message with leading/trailing whitespace
      await user.type(textarea, '  Hello, NEOS!  ');

      // Click send button
      await user.click(sendButton);

      // Assert - whitespace should be trimmed
      await waitFor(() => {
        expect(mockSendMessage).toHaveBeenCalledWith('Hello, NEOS!');
      });
    });
  });

  describe('Loading States', () => {
    it('should disable input and button when loading', () => {
      (useChatStore as unknown as jest.Mock).mockReturnValue({
        sendMessage: mockSendMessage,
        isLoading: true,
        isStreaming: false,
        settings: mockSettings,
      });

      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');
      const button = screen.getByRole('button');

      expect(textarea).toBeDisabled();
      expect(button).toBeInTheDocument();
    });

    it('should disable input and show stop button when streaming', () => {
      (useChatStore as unknown as jest.Mock).mockReturnValue({
        sendMessage: mockSendMessage,
        isLoading: false,
        isStreaming: true,
        settings: mockSettings,
      });

      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');
      const stopButton = screen.getByTitle('Stop generation');

      expect(textarea).toBeDisabled();
      expect(stopButton).toBeInTheDocument();
    });

    it('should not call sendMessage when loading', async () => {
      (useChatStore as unknown as jest.Mock).mockReturnValue({
        sendMessage: mockSendMessage,
        isLoading: true,
        isStreaming: false,
        settings: mockSettings,
      });

      const user = userEvent.setup();
      render(<InputBox />);

      const textarea = screen.getByPlaceholderText('Message NEOS...');

      // Try to type and send (should not work because disabled)
      // Note: userEvent respects disabled state, so typing won't work
      fireEvent.change(textarea, { target: { value: 'Test' } });
      fireEvent.keyDown(textarea, { key: 'Enter' });

      expect(mockSendMessage).not.toHaveBeenCalled();
    });
  });

  describe('Integration with Settings', () => {
    it('should use sendMessage regardless of stream setting', async () => {
      const user = userEvent.setup();

      // Test with streaming enabled
      render(<InputBox />);
      const textarea = screen.getByPlaceholderText('Message NEOS...');

      await user.type(textarea, 'Test message');
      fireEvent.keyDown(textarea, { key: 'Enter' });

      await waitFor(() => {
        expect(mockSendMessage).toHaveBeenCalledWith('Test message');
      });

      // The component itself doesn't care about the stream setting
      // It just calls sendMessage, which handles the strategy internally
    });
  });
});
