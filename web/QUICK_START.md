# NEOS Web - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### 1. Setup Environment

```bash
cd web
cp .env.local.example .env.local
```

Edit `.env.local`:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8518
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### 2. Start Backend

```bash
cd ../neos
uvicorn neos.main:app --reload --port 8518
```

### 3. Start Frontend

```bash
cd ../web
npm install
npm run dev
```

### 4. Open Browser

Visit: http://localhost:3000

## 🎯 Test the Features

### Standard Chat
1. Keep default "Standard" mode selected
2. Type a message: "Hello, what can you do?"
3. See the response

### RAG Chat
1. Click "RAG" mode button
2. Send multiple messages to build context
3. Ask: "What did we discuss earlier?"
4. Click "Show context details" to see retrieved messages

### Similarity Chat
1. Click "Similarity" mode button
2. Send messages on different topics
3. Ask about a previous topic
4. View similarity scores in context details

### Settings
1. Click Settings icon (⚙️)
2. Try changing:
   - Model (Claude variants)
   - Temperature slider
   - Enable streaming
   - RAG/Similarity options

### Streaming
1. Enable streaming in settings
2. Send a message
3. Watch the response appear word-by-word

## 📁 Project Structure

```
web/
├── lib/
│   ├── api/chat-api.ts           ← All API calls
│   ├── stores/chat-store-new.ts  ← State management
│   └── types.ts                   ← TypeScript types
│
└── components/chat/
    ├── ChatInterfaceNew.tsx       ← Main container
    ├── ChatModeSelector.tsx       ← Mode switcher
    ├── SettingsPanel.tsx          ← Settings UI
    ├── SidebarNew.tsx             ← Conversations list
    ├── MessageListNew.tsx         ← Messages display
    ├── MessageBubbleNew.tsx       ← Individual message
    └── InputBoxNew.tsx            ← Message input
```

## 💡 Common Tasks

### Send a Message Programmatically

```tsx
import { useChatStore } from "@/lib/stores/chat-store-new";

const { sendMessage } = useChatStore();
await sendMessage("Hello NEOS!");
```

### Change Chat Mode

```tsx
const { setChatMode } = useChatStore();
setChatMode("rag"); // or "standard" or "similarity"
```

### Update Settings

```tsx
const { updateSettings } = useChatStore();
updateSettings({
  temperature: 0.9,
  stream: true,
  rag_top_k: 5,
});
```

### Create New Conversation

```tsx
const { createConversation } = useChatStore();
await createConversation("My New Chat");
```

## 🔧 Troubleshooting

### "Failed to fetch"
- ✅ Check backend is running: `curl http://localhost:8518/api/v1/health`
- ✅ Check `.env.local` has correct `NEXT_PUBLIC_BACKEND_URL`
- ✅ Clear browser cache

### "No conversations"
- ✅ Backend database initialized?
- ✅ Check backend logs for errors
- ✅ Try manually creating: click "New Chat"

### Settings not saving
- ✅ Clear localStorage: `localStorage.clear()`
- ✅ Refresh page
- ✅ Check browser console for errors

## 📚 Learn More

- [Full Integration Guide](./CHAT_INTEGRATION.md) - Detailed documentation
- [Implementation Checklist](./INTEGRATION_CHECKLIST.md) - All features
- [Backend API Docs](http://localhost:8518/docs) - Swagger UI

## 🎉 You're Ready!

Try all three chat modes and explore the settings. The UI will guide you through the features.

**Need help?** Check [CHAT_INTEGRATION.md](./CHAT_INTEGRATION.md) for detailed guides.
