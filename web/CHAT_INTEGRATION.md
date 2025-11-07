# NEOS Web - Chat API Integration Guide

## Overview

This guide explains the new chat API integration that connects neos-web frontend with all three backend chat modes: **Standard**, **RAG**, and **Similarity**.

## What's New

### 🎯 Features

1. **Three Chat Modes**
   - **Standard**: Basic conversation mode
   - **RAG**: Retrieval-Augmented Generation with context
   - **Similarity**: Context-aware responses using similar messages

2. **Full Backend Integration**
   - Complete conversation management (create, list, update, delete, archive)
   - Message operations (send, regenerate, edit, feedback)
   - Real-time streaming support
   - RAG and Similarity context display

3. **Enhanced UI**
   - Chat mode selector
   - Comprehensive settings panel
   - Message actions (copy, regenerate, feedback)
   - RAG/Similarity context visualization
   - Improved metadata display

## Architecture

### File Structure

```
web/
├── lib/
│   ├── api/
│   │   └── chat-api.ts                 # Complete chat API client
│   ├── stores/
│   │   ├── chat-store.ts               # OLD - Legacy store
│   │   └── chat-store-new.ts           # NEW - Full backend integration
│   └── types.ts                        # Updated type definitions
│
├── components/chat/
│   ├── ChatInterface.tsx               # OLD
│   ├── ChatInterfaceNew.tsx            # NEW - Integrated interface
│   ├── Sidebar.tsx                     # OLD
│   ├── SidebarNew.tsx                  # NEW - Backend-connected
│   ├── MessageBubble.tsx               # OLD
│   ├── MessageBubbleNew.tsx            # NEW - Enhanced with actions
│   ├── InputBox.tsx                    # OLD
│   ├── InputBoxNew.tsx                 # NEW - Streaming support
│   ├── MessageList.tsx                 # OLD
│   ├── MessageListNew.tsx              # NEW - Better empty state
│   ├── ChatModeSelector.tsx            # NEW - Mode switching
│   └── SettingsPanel.tsx               # NEW - Configuration UI
│
└── app/
    └── api/chat/route.ts               # BFF layer (can be deprecated)
```

## Migration Guide

### Step 1: Update Environment Variables

Create or update `.env.local`:

```bash
cp .env.local.example .env.local
```

Edit `.env.local`:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8518
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### Step 2: Update Imports

Replace old imports with new ones:

**Before:**
```tsx
import { useChatStore } from "@/lib/stores/chat-store";
import ChatInterface from "@/components/chat/ChatInterface";
```

**After:**
```tsx
import { useChatStore } from "@/lib/stores/chat-store-new";
import ChatInterface from "@/components/chat/ChatInterfaceNew";
```

### Step 3: Update Main Page

Edit `app/page.tsx`:

```tsx
import ChatInterface from "@/components/chat/ChatInterfaceNew";

export default function Home() {
  return <ChatInterface />;
}
```

### Step 4: Start the Backend

Ensure your NEOS backend is running:

```bash
cd neos
uvicorn neos.main:app --reload --port 8000
```

### Step 5: Start the Frontend

```bash
cd web
npm run dev
```

Visit http://localhost:3000

## API Client Usage

### Creating Conversations

```tsx
import { chatAPI } from "@/lib/api/chat-api";

// Create a new conversation
const conversation = await chatAPI.createConversation({
  user_id: "user123",
  title: "My Chat",
  model_name: "claude-sonnet-4-5-20250929",
  temperature: 0.7,
});
```

### Sending Messages

```tsx
// Standard message
const response = await chatAPI.sendMessage(conversationId, {
  content: "Hello!",
});

// RAG message
const ragResponse = await chatAPI.sendRAGMessage(conversationId, {
  content: "What did we discuss about AI?",
  enable_rag: true,
  rag_top_k: 3,
  include_cross_conversation: false,
});

// Similarity message
const simResponse = await chatAPI.sendSimilarityMessage(conversationId, {
  content: "Tell me more about that topic",
  top_k: 3,
  similarity_threshold: 0.7,
  include_cross_conversation: false,
});
```

### Streaming Messages

```tsx
const stream = await chatAPI.sendMessageStream(conversationId, {
  content: "Explain quantum computing",
});

const reader = stream.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value);
  // Process SSE chunk
  console.log(chunk);
}
```

## Store Usage

### Basic Operations

```tsx
import { useChatStore } from "@/lib/stores/chat-store-new";

function MyComponent() {
  const {
    conversations,
    currentConversation,
    messages,
    isLoading,
    settings,

    // Actions
    createConversation,
    sendMessage,
    setChatMode,
    updateSettings,
  } = useChatStore();

  // Send a message
  const handleSend = async () => {
    await sendMessage("Hello NEOS!");
  };

  // Switch to RAG mode
  const enableRAG = () => {
    setChatMode("rag");
  };

  // Update settings
  const changeModel = () => {
    updateSettings({
      model_name: "claude-opus-4-1-20250805",
      temperature: 0.9,
    });
  };

  return (
    <div>
      <div>Current mode: {settings.mode}</div>
      <div>Messages: {messages.length}</div>
      <button onClick={handleSend}>Send</button>
    </div>
  );
}
```

### Chat Mode Configuration

```tsx
const { settings, updateSettings, setChatMode } = useChatStore();

// Standard mode
setChatMode("standard");

// RAG mode with custom settings
setChatMode("rag");
updateSettings({
  rag_enabled: true,
  rag_top_k: 5,
  rag_cross_conversation: true,
});

// Similarity mode with custom settings
setChatMode("similarity");
updateSettings({
  similarity_top_k: 3,
  similarity_threshold: 0.8,
  similarity_cross_conversation: false,
  enable_auto_embedding: true,
});
```

## Component Customization

### Customizing Chat Modes

Edit `components/chat/ChatModeSelector.tsx`:

```tsx
const chatModes = [
  {
    id: "standard",
    name: "Standard",
    description: "Basic conversation mode",
    icon: <Sparkles />,
  },
  // Add your custom modes here
];
```

### Customizing Settings Panel

Edit `components/chat/SettingsPanel.tsx` to add more configuration options.

### Customizing Message Display

Edit `components/chat/MessageBubbleNew.tsx` to change how messages are rendered.

## Features Comparison

| Feature | Old Implementation | New Implementation |
|---------|-------------------|-------------------|
| Backend | Single `/api/v1/query` endpoint | Full chat API integration |
| Chat Modes | None | Standard, RAG, Similarity |
| Streaming | Not supported | Full SSE streaming |
| Conversation Management | Local only | Backend-synced |
| Message Actions | None | Regenerate, Edit, Feedback |
| Context Display | None | RAG & Similarity visualization |
| Settings | None | Full configuration panel |
| Persistence | localStorage only | Backend + localStorage |

## Advanced Features

### WebSocket Support

```tsx
import { chatAPI } from "@/lib/api/chat-api";

const ws = chatAPI.connectWebSocket(conversationId);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Message:", data);
};

ws.send(JSON.stringify({
  content: "Hello via WebSocket!",
}));
```

### Message Feedback

```tsx
const { addFeedback } = useChatStore();

// Positive feedback
await addFeedback(messageId, "positive", "Great response!");

// Negative feedback
await addFeedback(messageId, "negative", "Not accurate");
```

### Message Regeneration

```tsx
const { regenerateMessage } = useChatStore();

await regenerateMessage(messageId);
```

## Backend Endpoints Used

### Conversation Endpoints
- `POST /api/v1/chat/conversations` - Create conversation
- `GET /api/v1/chat/conversations/{id}` - Get conversation
- `GET /api/v1/chat/users/{user_id}/conversations` - List conversations
- `PATCH /api/v1/chat/conversations/{id}` - Update conversation
- `DELETE /api/v1/chat/conversations/{id}` - Delete conversation
- `POST /api/v1/chat/conversations/{id}/archive` - Archive conversation

### Message Endpoints
- `POST /api/v1/chat/conversations/{id}/messages` - Send standard message
- `POST /api/v1/chat/conversations/{id}/messages/stream` - Stream standard message
- `POST /api/v1/chat/conversations/{id}/messages/rag` - Send RAG message
- `POST /api/v1/chat/conversations/{id}/messages/rag/stream` - Stream RAG message
- `POST /api/v1/chat/conversations/{id}/messages/similarity` - Send similarity message
- `POST /api/v1/chat/conversations/{id}/messages/similarity/stream` - Stream similarity message
- `GET /api/v1/chat/conversations/{id}/messages` - Get messages
- `POST /api/v1/chat/messages/{id}/regenerate` - Regenerate message
- `PATCH /api/v1/chat/messages/{id}` - Edit message
- `POST /api/v1/chat/messages/{id}/feedback` - Add feedback

### WebSocket
- `WS /api/v1/chat/ws/{conversation_id}` - Real-time chat

## Troubleshooting

### CORS Issues

If you encounter CORS errors, ensure your backend allows the frontend origin:

```python
# In neos/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Connection Refused

Make sure the backend is running on the correct port:
```bash
# Check if backend is running
curl http://localhost:8518/api/v1/health
```

### Store Not Updating

Clear localStorage cache:
```js
localStorage.removeItem("neos-chat-storage");
```

Then refresh the page.

## Performance Optimization

### Lazy Loading Messages

Messages are only loaded when you open a conversation:

```tsx
const { loadMessages } = useChatStore();

// Manually load messages
await loadMessages(conversationId);
```

### Pagination

Load more messages:

```tsx
const messages = await chatAPI.getMessages(conversationId, {
  limit: 50,
  before_sequence: 100,
});
```

## Testing

### Test Standard Chat

1. Select "Standard" mode
2. Send a message
3. Verify response appears

### Test RAG Chat

1. Select "RAG" mode
2. Enable RAG in settings
3. Send multiple messages
4. Send a query asking about previous messages
5. Verify context is retrieved and displayed

### Test Similarity Chat

1. Select "Similarity" mode
2. Send multiple messages on different topics
3. Ask about a previous topic
4. Click "Show context details" to see similar messages

### Test Streaming

1. Enable streaming in settings
2. Send a message
3. Verify content appears incrementally

## Next Steps

1. **Remove Old Files**: After verifying everything works, delete old files:
   ```bash
   rm web/lib/stores/chat-store.ts
   rm web/components/chat/ChatInterface.tsx
   rm web/components/chat/Sidebar.tsx
   rm web/components/chat/MessageBubble.tsx
   rm web/components/chat/InputBox.tsx
   rm web/components/chat/MessageList.tsx
   ```

2. **Rename New Files**: Remove the "New" suffix:
   ```bash
   mv web/lib/stores/chat-store-new.ts web/lib/stores/chat-store.ts
   mv web/components/chat/ChatInterfaceNew.tsx web/components/chat/ChatInterface.tsx
   # ... etc
   ```

3. **Update Imports**: Update all imports to use the renamed files.

## Support

For issues or questions:
- Check backend logs: `tail -f neos/logs/app.log`
- Check frontend console for errors
- Review backend API documentation: http://localhost:8518/docs

## Changelog

### v2.0.0 (Current)
- ✅ Full backend chat API integration
- ✅ Three chat modes (Standard, RAG, Similarity)
- ✅ Streaming support
- ✅ Conversation management
- ✅ Message actions (regenerate, edit, feedback)
- ✅ Settings panel
- ✅ Enhanced metadata display

### v1.0.0 (Old)
- Basic chat UI
- Single query endpoint
- Local storage only
- No streaming
- Limited features
