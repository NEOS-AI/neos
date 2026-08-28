-- Migration: Add visibility field to conversations table
-- Description: Add visibility field to conversations table to match frontend Chat table structure
-- Date: 2025-12-24

-- Add visibility column to conversations table
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private';

-- Update existing records based on is_shared field
UPDATE conversations
SET visibility = CASE
  WHEN is_shared = true THEN 'public'
  ELSE 'private'
END;

-- Add index for better query performance
CREATE INDEX IF NOT EXISTS idx_conversations_visibility ON conversations(visibility);

-- Add CHECK constraint to ensure valid values
--
-- 제약에는 `IF NOT EXISTS` 가 없으므로 카탈로그를 직접 본다 (SCHEMA3).
-- `tests/conftest.py` 가 세션마다 마이그레이션을 전량 재적용하는데, 가드가
-- 없으면 여기서 죽고 **이 파일의 나머지가 미적용으로 남는다.**
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_visibility_value'
    ) THEN
        ALTER TABLE conversations
        ADD CONSTRAINT check_visibility_value
        CHECK (visibility IN ('public', 'private'));
    END IF;
END $$;

-- Add comment for documentation
COMMENT ON COLUMN conversations.visibility IS 'Visibility of the conversation: public or private';
