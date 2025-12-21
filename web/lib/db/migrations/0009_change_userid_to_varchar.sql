-- Migration: Change userId from UUID to VARCHAR(255) to match backend User.user_id
-- This allows the artifact system to work with backend authentication

--> statement-breakpoint
-- Drop foreign key constraints first
DO $$ BEGIN
 ALTER TABLE "Document" DROP CONSTRAINT IF EXISTS "Document_userId_User_id_fk";
EXCEPTION
 WHEN undefined_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "Suggestion" DROP CONSTRAINT IF EXISTS "Suggestion_userId_User_id_fk";
EXCEPTION
 WHEN undefined_object THEN null;
END $$;

--> statement-breakpoint
-- Alter Document.userId column type
ALTER TABLE "Document" ALTER COLUMN "userId" TYPE VARCHAR(255) USING "userId"::TEXT;

--> statement-breakpoint
-- Alter Suggestion.userId column type
ALTER TABLE "Suggestion" ALTER COLUMN "userId" TYPE VARCHAR(255) USING "userId"::TEXT;
