-- Migration: Add backendConversationId to Chat table
-- Description: Add backendConversationId field to link frontend Chat with backend Conversation
-- Date: 2025-12-24

-- Add backendConversationId column to Chat table
ALTER TABLE "Chat"
ADD COLUMN "backendConversationId" VARCHAR(255);

-- Add index for better query performance
CREATE INDEX "Chat_backendConversationId_idx"
ON "Chat"("backendConversationId");

-- Add comment for documentation
COMMENT ON COLUMN "Chat"."backendConversationId" IS 'Backend conversation_id to link with backend Conversation table';
