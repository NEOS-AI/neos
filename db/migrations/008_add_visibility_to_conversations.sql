-- Migration: Add visibility field to conversations table
-- Description: Add visibility field to conversations table to match frontend Chat table structure
-- Date: 2025-12-24

-- Add visibility column to conversations table
ALTER TABLE conversations
ADD COLUMN visibility VARCHAR(20) DEFAULT 'private';

-- Update existing records based on is_shared field
UPDATE conversations
SET visibility = CASE
  WHEN is_shared = true THEN 'public'
  ELSE 'private'
END;

-- Add index for better query performance
CREATE INDEX idx_conversations_visibility ON conversations(visibility);

-- Add CHECK constraint to ensure valid values
ALTER TABLE conversations
ADD CONSTRAINT check_visibility_value
CHECK (visibility IN ('public', 'private'));

-- Add comment for documentation
COMMENT ON COLUMN conversations.visibility IS 'Visibility of the conversation: public or private';
