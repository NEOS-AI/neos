import type { MessageResponse, ConversationResponse } from "@/lib/api/chat-api";
import type { Message, Conversation } from "@/lib/types";

/**
 * Helper function to convert MessageResponse to Message
 */
export const toMessage = (response: MessageResponse): Message => {
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

/**
 * Helper to convert ConversationResponse to Conversation
 */
export const toConversation = (response: ConversationResponse): Conversation => {
  return {
    ...response,
    messages: [],
  };
};
