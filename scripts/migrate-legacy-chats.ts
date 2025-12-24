#!/usr/bin/env tsx

/**
 * Legacy Chat Migration Script
 *
 * This script migrates legacy Chat records (without backendConversationId)
 * to create corresponding Conversation records in the backend.
 *
 * Usage:
 *   npm run migrate:legacy-chats
 *   npm run migrate:legacy-chats -- --dry-run  # Test without making changes
 */

import { db } from "@/lib/db/queries";
import { chat } from "@/lib/db/schema";
import { callBackendAPI } from "@/lib/backend-api";
import { eq, isNull } from "drizzle-orm";

interface MigrationStats {
  total: number;
  migrated: number;
  failed: number;
  skipped: number;
}

async function migrateLegacyChats(dryRun: boolean = false) {
  const stats: MigrationStats = {
    total: 0,
    migrated: 0,
    failed: 0,
    skipped: 0,
  };

  console.log("🔍 Searching for legacy chats without backendConversationId...\n");

  try {
    // Find all chats without backendConversationId
    const legacyChats = await db
      .select()
      .from(chat)
      .where(isNull(chat.backendConversationId));

    stats.total = legacyChats.length;

    if (stats.total === 0) {
      console.log("✅ No legacy chats found. All chats are already migrated!");
      return stats;
    }

    console.log(`📊 Found ${stats.total} legacy chat(s) to migrate\n`);

    if (dryRun) {
      console.log("🔸 DRY RUN MODE - No actual changes will be made\n");
    }

    // Migrate each chat
    for (const legacyChat of legacyChats) {
      console.log(`\n📝 Processing chat: ${legacyChat.id}`);
      console.log(`   Title: ${legacyChat.title}`);
      console.log(`   User: ${legacyChat.userId}`);
      console.log(`   Created: ${legacyChat.createdAt.toISOString()}`);

      try {
        if (!dryRun) {
          // Create conversation in backend
          const conversationResponse = await callBackendAPI(
            "/api/v1/chat/conversations",
            {
              method: "POST",
              body: JSON.stringify({
                user_id: legacyChat.userId,
                title: legacyChat.title,
                model_name: "claude-opus-4-5-20251101",
                mode: "standard",
                temperature: 0.7,
                visibility: legacyChat.visibility || "private",
              }),
            }
          );

          if (!conversationResponse.ok) {
            const errorText = await conversationResponse.text();
            throw new Error(`Backend API error: ${errorText}`);
          }

          const conversationData = await conversationResponse.json();
          const conversationId = conversationData.conversation_id;

          if (!conversationId) {
            throw new Error("Backend did not return conversation_id");
          }

          // Update Chat table with backendConversationId
          await db
            .update(chat)
            .set({ backendConversationId: conversationId })
            .where(eq(chat.id, legacyChat.id));

          console.log(`   ✅ Migrated successfully`);
          console.log(`   Backend Conversation ID: ${conversationId}`);
          stats.migrated++;
        } else {
          console.log(`   🔸 Would create conversation (dry run)`);
          stats.migrated++;
        }
      } catch (error) {
        console.error(`   ❌ Migration failed:`, error);
        stats.failed++;
      }
    }

    console.log("\n" + "=".repeat(60));
    console.log("📊 Migration Summary:");
    console.log("=".repeat(60));
    console.log(`Total chats found:     ${stats.total}`);
    console.log(`Successfully migrated: ${stats.migrated}`);
    console.log(`Failed:                ${stats.failed}`);
    console.log(`Skipped:               ${stats.skipped}`);
    console.log("=".repeat(60));

    if (dryRun) {
      console.log("\n🔸 This was a dry run. Run without --dry-run to apply changes.");
    } else if (stats.failed > 0) {
      console.log("\n⚠️  Some migrations failed. Please review the errors above.");
    } else if (stats.migrated > 0) {
      console.log("\n✅ All legacy chats migrated successfully!");
    }

    return stats;
  } catch (error) {
    console.error("\n❌ Fatal error during migration:", error);
    throw error;
  }
}

// Main execution
async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");

  console.log("🚀 Legacy Chat Migration Script");
  console.log("=".repeat(60) + "\n");

  try {
    const stats = await migrateLegacyChats(dryRun);

    if (stats.failed > 0) {
      process.exit(1);
    }
  } catch (error) {
    console.error("\n💥 Migration script failed:", error);
    process.exit(1);
  }
}

// Run if executed directly
if (require.main === module) {
  main();
}

export { migrateLegacyChats };
