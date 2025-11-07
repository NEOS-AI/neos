#!/bin/bash
# NEOS Web - Complete Migration Script
# This script migrates from old store structure to new conversation-based structure

set -e  # Exit on error

echo "🚀 Starting NEOS Web Migration..."
echo ""

# Navigate to web directory
cd "$(dirname "$0")"

# Step 1: Backup
echo "📦 Step 1/6: Creating backup..."
BACKUP_DIR=".backup/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup old files (silently, some may not exist)
cp lib/stores/chat-store.ts "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  chat-store.ts not found (OK)"
cp lib/stores/chat-store-new.ts "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  chat-store-new.ts not found (OK)"
cp components/chat/ChatInterface.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  ChatInterface.tsx not found (OK)"
cp components/chat/ChatInterfaceNew.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  ChatInterfaceNew.tsx not found (OK)"
cp components/chat/Sidebar.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  Sidebar.tsx not found (OK)"
cp components/chat/Header.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  Header.tsx not found (OK)"
cp components/chat/MessageList.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  MessageList.tsx not found (OK)"
cp components/chat/InputBox.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  InputBox.tsx not found (OK)"
cp components/chat/MessageBubble.tsx "$BACKUP_DIR/" 2>/dev/null || echo "  ℹ️  MessageBubble.tsx not found (OK)"

echo "✅ Backup created at: $BACKUP_DIR"
echo ""

# Step 2: Remove old files
echo "🗑️  Step 2/6: Removing old incompatible files..."
rm -f lib/stores/chat-store.ts
rm -f lib/stores/chat-store-new.ts
rm -f components/chat/ChatInterface.tsx
rm -f components/chat/ChatInterfaceNew.tsx
rm -f components/chat/Sidebar.tsx
rm -f components/chat/Header.tsx
rm -f components/chat/MessageList.tsx
rm -f components/chat/InputBox.tsx
rm -f components/chat/MessageBubble.tsx
echo "✅ Old files removed"
echo ""

# Step 3: Rename fixed files to production names
echo "📝 Step 3/6: Renaming fixed files to production names..."

# Check if fixed files exist
if [ ! -f "lib/stores/chat-store-fixed.ts" ]; then
    echo "❌ Error: chat-store-fixed.ts not found!"
    exit 1
fi

mv lib/stores/chat-store-fixed.ts lib/stores/chat-store.ts
mv components/chat/ChatInterfaceFixed.tsx components/chat/ChatInterface.tsx
mv components/chat/SidebarNew.tsx components/chat/Sidebar.tsx
mv components/chat/MessageListNew.tsx components/chat/MessageList.tsx
mv components/chat/MessageBubbleNew.tsx components/chat/MessageBubble.tsx
mv components/chat/InputBoxNew.tsx components/chat/InputBox.tsx
mv components/chat/HeaderNew.tsx components/chat/Header.tsx

echo "✅ Files renamed successfully"
echo ""

# Step 4: Update imports
echo "🔄 Step 4/6: Updating import paths..."
# Update any remaining references to old store paths
find components app -type f -name "*.tsx" -o -name "*.ts" | while read file; do
    # Replace chat-store-new with chat-store
    sed -i '' 's/@\/lib\/stores\/chat-store-new/@\/lib\/stores\/chat-store/g' "$file" 2>/dev/null || true
    # Replace chat-store-fixed with chat-store
    sed -i '' 's/@\/lib\/stores\/chat-store-fixed/@\/lib\/stores\/chat-store/g' "$file" 2>/dev/null || true
done
echo "✅ Import paths updated"
echo ""

# Step 5: Type check
echo "🔍 Step 5/6: Running TypeScript check..."
if npx tsc --noEmit 2>&1 | tee /tmp/tsc-output.txt; then
    echo "✅ TypeScript check passed!"
else
    ERROR_COUNT=$(grep -c "error TS" /tmp/tsc-output.txt || echo "0")
    echo "❌ TypeScript errors found: $ERROR_COUNT"
    echo ""
    echo "Showing first 10 errors:"
    head -20 /tmp/tsc-output.txt
    echo ""
    echo "⚠️  Migration completed but with TypeScript errors."
    echo "    Review errors above and check MIGRATION_GUIDE_FINAL.md"
    exit 1
fi
echo ""

# Step 6: Build test
echo "🏗️  Step 6/6: Building project..."
if npm run build > /tmp/build-output.txt 2>&1; then
    echo "✅ Build successful!"
else
    echo "❌ Build failed. Check output:"
    tail -20 /tmp/build-output.txt
    exit 1
fi
echo ""

echo "🎉 Migration completed successfully!"
echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║                  MIGRATION SUMMARY                     ║"
echo "╠═══════════════════════════════════════════════════════╣"
echo "║ ✅ Backup created: $BACKUP_DIR"
echo "║ ✅ Old files removed: 9 files"
echo "║ ✅ Fixed files renamed: 7 files"
echo "║ ✅ TypeScript check: PASSED"
echo "║ ✅ Build: SUCCESS"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "📝 Next steps:"
echo "   1. npm run dev"
echo "   2. Test all features (see MIGRATION_GUIDE_FINAL.md)"
echo "   3. If everything works, delete backup:"
echo "      rm -rf $BACKUP_DIR"
echo ""
echo "📚 Documentation:"
echo "   - MIGRATION_GUIDE_FINAL.md"
echo "   - IMPLEMENTATION_ANALYSIS.md"
echo "   - FIXES_SUMMARY.md"
echo ""
