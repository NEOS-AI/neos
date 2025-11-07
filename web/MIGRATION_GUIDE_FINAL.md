# NEOS Web - Final Migration Guide

## 🚨 Current Status

### Problem
- Old components (ChatInterface.tsx, Sidebar.tsx, Header.tsx, MessageList.tsx, InputBox.tsx) reference OLD store structure
- Old store (chat-store.ts) uses OLD type definitions (ChatSession, sessions)
- New store (chat-store-fixed.ts) uses NEW type definitions (Conversation, conversations)
- **Result**: 43 TypeScript errors

### Root Cause
Mixed old and new implementations coexist, causing type conflicts.

---

## ✅ Solution: Clean Migration

### Step 1: Backup Everything (SAFETY FIRST)
```bash
cd /Users/ywsung/Desktop/neos/web

# Create backup directory
mkdir -p .backup/$(date +%Y%m%d)

# Backup ALL old files
cp lib/stores/chat-store.ts .backup/$(date +%Y%m%d)/
cp lib/stores/chat-store-new.ts .backup/$(date +%Y%m%d)/
cp components/chat/ChatInterface.tsx .backup/$(date +%Y%m%d)/
cp components/chat/ChatInterfaceNew.tsx .backup/$(date +%Y%m%d)/
cp components/chat/Sidebar.tsx .backup/$(date +%Y%m%d)/
cp components/chat/Header.tsx .backup/$(date +%Y%m%d)/
cp components/chat/MessageList.tsx .backup/$(date +%Y%m%d)/
cp components/chat/InputBox.tsx .backup/$(date +%Y%m%d)/
cp components/chat/MessageBubble.tsx .backup/$(date +%Y%m%d)/
```

### Step 2: Remove Old Files
```bash
# Remove old incompatible files
rm lib/stores/chat-store.ts
rm lib/stores/chat-store-new.ts
rm components/chat/ChatInterface.tsx
rm components/chat/ChatInterfaceNew.tsx
rm components/chat/Sidebar.tsx
rm components/chat/Header.tsx
rm components/chat/MessageList.tsx
rm components/chat/InputBox.tsx
rm components/chat/MessageBubble.tsx
```

### Step 3: Rename Fixed Files to Production Names
```bash
# Use fixed versions as production files
mv lib/stores/chat-store-fixed.ts lib/stores/chat-store.ts
mv components/chat/ChatInterfaceFixed.tsx components/chat/ChatInterface.tsx
mv components/chat/SidebarNew.tsx components/chat/Sidebar.tsx
mv components/chat/MessageListNew.tsx components/chat/MessageList.tsx
mv components/chat/MessageBubbleNew.tsx components/chat/MessageBubble.tsx
mv components/chat/InputBoxNew.tsx components/chat/InputBox.tsx
```

### Step 4: Update Header Component
The Header component needs to be updated to use new store structure.
(Will be created in next step)

### Step 5: Verify
```bash
# Check TypeScript
npx tsc --noEmit

# Should show: 0 errors

# Build
npm run build

# Should complete successfully
```

---

## 📁 File Mapping

### What Gets Removed
```
❌ lib/stores/chat-store.ts (OLD - sessions-based)
❌ lib/stores/chat-store-new.ts (TRANSITION - incomplete)
❌ components/chat/ChatInterface.tsx (OLD)
❌ components/chat/ChatInterfaceNew.tsx (TRANSITION)
❌ components/chat/Sidebar.tsx (OLD)
❌ components/chat/Header.tsx (OLD)
❌ components/chat/MessageList.tsx (OLD)
❌ components/chat/InputBox.tsx (OLD)
❌ components/chat/MessageBubble.tsx (OLD)
```

### What Gets Renamed (Fixed → Production)
```
✅ chat-store-fixed.ts → chat-store.ts
✅ ChatInterfaceFixed.tsx → ChatInterface.tsx
✅ SidebarNew.tsx → Sidebar.tsx
✅ MessageListNew.tsx → MessageList.tsx
✅ MessageBubbleNew.tsx → MessageBubble.tsx
✅ InputBoxNew.tsx → InputBox.tsx
```

### What Gets Created
```
✅ components/chat/Header.tsx (NEW - conversations-based)
```

---

## 🔄 Automated Migration Script

```bash
#!/bin/bash
# File: migrate.sh

set -e  # Exit on error

echo "🚀 Starting NEOS Web Migration..."

# Navigate to web directory
cd /Users/ywsung/Desktop/neos/web

# Step 1: Backup
echo "📦 Creating backup..."
BACKUP_DIR=".backup/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup old files
cp lib/stores/chat-store.ts "$BACKUP_DIR/" 2>/dev/null || true
cp lib/stores/chat-store-new.ts "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/ChatInterface.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/ChatInterfaceNew.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/Sidebar.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/Header.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/MessageList.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/InputBox.tsx "$BACKUP_DIR/" 2>/dev/null || true
cp components/chat/MessageBubble.tsx "$BACKUP_DIR/" 2>/dev/null || true

echo "✅ Backup created at: $BACKUP_DIR"

# Step 2: Remove old files
echo "🗑️  Removing old files..."
rm -f lib/stores/chat-store.ts
rm -f lib/stores/chat-store-new.ts
rm -f components/chat/ChatInterface.tsx
rm -f components/chat/ChatInterfaceNew.tsx
rm -f components/chat/Sidebar.tsx
rm -f components/chat/Header.tsx
rm -f components/chat/MessageList.tsx
rm -f components/chat/InputBox.tsx
rm -f components/chat/MessageBubble.tsx

# Step 3: Rename fixed files
echo "📝 Renaming fixed files to production names..."
mv lib/stores/chat-store-fixed.ts lib/stores/chat-store.ts
mv components/chat/ChatInterfaceFixed.tsx components/chat/ChatInterface.tsx
mv components/chat/SidebarNew.tsx components/chat/Sidebar.tsx
mv components/chat/MessageListNew.tsx components/chat/MessageList.tsx
mv components/chat/MessageBubbleNew.tsx components/chat/MessageBubble.tsx
mv components/chat/InputBoxNew.tsx components/chat/InputBox.tsx

echo "✅ Files renamed successfully"

# Step 4: Type check
echo "🔍 Running TypeScript check..."
if npx tsc --noEmit; then
    echo "✅ TypeScript check passed!"
else
    echo "❌ TypeScript errors found. Check output above."
    exit 1
fi

# Step 5: Build
echo "🏗️  Building project..."
if npm run build; then
    echo "✅ Build successful!"
else
    echo "❌ Build failed. Check output above."
    exit 1
fi

echo "🎉 Migration completed successfully!"
echo ""
echo "Next steps:"
echo "1. npm run dev"
echo "2. Test all features"
echo "3. If everything works, delete backup: rm -rf $BACKUP_DIR"
```

Save as `migrate.sh` and run:
```bash
chmod +x migrate.sh
./migrate.sh
```

---

## 🧪 Post-Migration Testing

### Manual Testing Checklist
- [ ] App loads without console errors
- [ ] Can create new conversation
- [ ] Can send message (Standard mode)
- [ ] Can send message (RAG mode)
- [ ] Can send message (Similarity mode)
- [ ] Can switch between chat modes
- [ ] Can open settings panel
- [ ] Can change model/temperature
- [ ] Can regenerate message
- [ ] Can add feedback (thumbs up/down)
- [ ] Can copy message
- [ ] Can delete conversation
- [ ] Can archive conversation
- [ ] Loading states appear correctly
- [ ] Error messages display properly
- [ ] Streaming works (if enabled)

### Automated Tests
```bash
# Type check
npx tsc --noEmit

# Lint
npm run lint

# Build
npm run build

# Run dev server
npm run dev
```

---

## 🔙 Rollback Plan

If something goes wrong:

```bash
# Restore from backup
BACKUP_DIR=".backup/YYYYMMDD_HHMMSS"  # Use your actual backup dir

cp "$BACKUP_DIR/chat-store.ts" lib/stores/
cp "$BACKUP_DIR/ChatInterface.tsx" components/chat/
cp "$BACKUP_DIR/Sidebar.tsx" components/chat/
cp "$BACKUP_DIR/Header.tsx" components/chat/
cp "$BACKUP_DIR/MessageList.tsx" components/chat/
cp "$BACKUP_DIR/InputBox.tsx" components/chat/
cp "$BACKUP_DIR/MessageBubble.tsx" components/chat/

# Rebuild
npm run build
```

---

## 📊 Expected Results

### Before Migration
```
TypeScript Errors: 43
Build: ❌ Fails
Functionality: ⚠️ Partially broken
```

### After Migration
```
TypeScript Errors: 0 ✅
Build: ✅ Success
Functionality: ✅ All features working
```

---

## ⚠️ Important Notes

1. **Do NOT manually edit files during migration**
   - Use the script or follow steps exactly
   - Mixed edits can cause conflicts

2. **Test thoroughly before deleting backups**
   - Keep backups for at least 1 week
   - Test all features multiple times

3. **If you encounter issues**
   - Check the backup directory
   - Rollback immediately
   - Review error messages carefully

4. **Header component**
   - Will be created after migration
   - Uses new conversation-based structure
   - Shows current conversation title

---

## 🎯 Success Criteria

Migration is successful when:
- [x] TypeScript shows 0 errors
- [x] Build completes without errors
- [x] App runs without console errors
- [x] All chat features work
- [x] All 3 modes work (Standard, RAG, Similarity)
- [x] Settings persist
- [x] Error handling works
- [x] Loading states appear

---

**Ready to migrate?** Run the script or follow the manual steps above.

**Questions?** Check [IMPLEMENTATION_ANALYSIS.md](./IMPLEMENTATION_ANALYSIS.md) for detailed documentation.
