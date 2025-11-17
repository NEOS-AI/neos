/**
 * Tests for MessageBubble component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MessageBubble from '../MessageBubble';
import { Message } from '@/lib/types';
import { useChatStore } from '@/lib/stores/chat-store';

// Mock the chat store
jest.mock('@/lib/stores/chat-store');

// Mock clipboard API
Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn(() => Promise.resolve()),
  },
});

describe('MessageBubble', () => {
  const mockRegenerateMessage = jest.fn();
  const mockAddFeedback = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (useChatStore as unknown as jest.Mock).mockReturnValue({
      regenerateMessage: mockRegenerateMessage,
      addFeedback: mockAddFeedback,
    });
  });

  const createMessage = (overrides?: Partial<Message>): Message => ({
    message_id: 'msg-123',
    conversation_id: 'conv-123',
    role: 'assistant',
    content: 'Test message content',
    sequence_number: 1,
    status: 'completed',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  });

  describe('Rendering', () => {
    it('should render user message', () => {
      const message = createMessage({ role: 'user', content: 'User message' });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('You')).toBeInTheDocument();
      expect(screen.getByText('User message')).toBeInTheDocument();
    });

    it('should render assistant message', () => {
      const message = createMessage({ role: 'assistant', content: 'Assistant message' });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('NEOS')).toBeInTheDocument();
      expect(screen.getByText('Assistant message')).toBeInTheDocument();
    });

    it('should show RAG badge when RAG context exists', () => {
      const message = createMessage({
        metadata: { rag_enabled: true },
      });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('RAG')).toBeInTheDocument();
    });

    it('should show Similarity badge when similarity context exists', () => {
      const message = createMessage({
        metadata: { context_enhanced: true },
      });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('Similarity')).toBeInTheDocument();
    });

    it('should show streaming status', () => {
      const message = createMessage({ status: 'streaming' });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('Streaming')).toBeInTheDocument();
    });

    it('should show pending status', () => {
      const message = createMessage({ status: 'pending' });
      render(<MessageBubble message={message} />);

      expect(screen.getByText('Thinking')).toBeInTheDocument();
    });
  });

  describe('Copy functionality', () => {
    it('should copy message content to clipboard', async () => {
      const message = createMessage({ content: 'Content to copy' });
      render(<MessageBubble message={message} />);

      const copyButton = screen.getByTitle('Copy message');
      fireEvent.click(copyButton);

      await waitFor(() => {
        expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Content to copy');
      });
    });

    it('should show copied state temporarily', async () => {
      jest.useFakeTimers();
      const message = createMessage();
      render(<MessageBubble message={message} />);

      const copyButton = screen.getByTitle('Copy message');
      fireEvent.click(copyButton);

      await waitFor(() => {
        expect(screen.getByTitle('Copied!')).toBeInTheDocument();
      });

      // Fast-forward time
      jest.advanceTimersByTime(2000);

      await waitFor(() => {
        expect(screen.queryByTitle('Copied!')).not.toBeInTheDocument();
      });

      jest.useRealTimers();
    });
  });

  describe('Feedback functionality', () => {
    it('should call addFeedback with positive feedback', async () => {
      const message = createMessage();
      render(<MessageBubble message={message} />);

      const thumbsUpButton = screen.getByTitle('Good response');
      fireEvent.click(thumbsUpButton);

      await waitFor(() => {
        expect(mockAddFeedback).toHaveBeenCalledWith('msg-123', 'positive');
      });
    });

    it('should call addFeedback with negative feedback', async () => {
      const message = createMessage();
      render(<MessageBubble message={message} />);

      const thumbsDownButton = screen.getByTitle('Bad response');
      fireEvent.click(thumbsDownButton);

      await waitFor(() => {
        expect(mockAddFeedback).toHaveBeenCalledWith('msg-123', 'negative');
      });
    });
  });

  describe('Regenerate functionality', () => {
    it('should call regenerateMessage when regenerate button is clicked', async () => {
      const message = createMessage({ role: 'assistant' });
      render(<MessageBubble message={message} />);

      const regenerateButton = screen.getByTitle('Regenerate response');
      fireEvent.click(regenerateButton);

      await waitFor(() => {
        expect(mockRegenerateMessage).toHaveBeenCalledWith('msg-123');
      });
    });

    it('should not show regenerate button for user messages', () => {
      const message = createMessage({ role: 'user' });
      render(<MessageBubble message={message} />);

      expect(screen.queryByTitle('Regenerate response')).not.toBeInTheDocument();
    });
  });

  describe('Token information', () => {
    it('should display token counts when available', () => {
      const message = createMessage({
        prompt_tokens: 10,
        completion_tokens: 20,
        total_tokens: 30,
      });
      render(<MessageBubble message={message} />);

      // Click to show details
      const detailsButton = screen.getByRole('button', { name: /Show details/i });
      fireEvent.click(detailsButton);

      expect(screen.getByText(/10.*tokens/i)).toBeInTheDocument();
      expect(screen.getByText(/20.*tokens/i)).toBeInTheDocument();
    });
  });

  describe('User feedback display', () => {
    it('should show positive feedback indicator', () => {
      const message = createMessage({ user_feedback: 'positive' });
      render(<MessageBubble message={message} />);

      const thumbsUpButton = screen.getByTitle('Good response');
      expect(thumbsUpButton).toHaveClass('text-green-400');
    });

    it('should show negative feedback indicator', () => {
      const message = createMessage({ user_feedback: 'negative' });
      render(<MessageBubble message={message} />);

      const thumbsDownButton = screen.getByTitle('Bad response');
      expect(thumbsDownButton).toHaveClass('text-red-400');
    });
  });
});
