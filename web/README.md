# NEOS Web UI

Claude-inspired web interface for NEOS (Intelligent Search and Analysis Agent Workflow) built with Next.js, TypeScript, and Tailwind CSS.

## Features

- **Claude-like UI**: Clean, modern interface inspired by Claude's design
- **Real-time Chat**: Interactive chat interface with the NEOS backend
- **Session Management**: Multiple chat sessions with history
- **BFF Architecture**: Backend-for-Frontend pattern for optimized API communication
- **Responsive Design**: Mobile-friendly responsive layout
- **Markdown Support**: Rich markdown rendering for AI responses
- **Metadata Display**: Shows execution time, quality scores, and agent information

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State Management**: Zustand with persistence
- **Markdown**: react-markdown with remark-gfm
- **Icons**: lucide-react

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn/pnpm
- NEOS backend running on http://localhost:8518 (see main README)

### Installation

1. Install dependencies:

```bash
npm install
# or
yarn install
# or
pnpm install
```

2. Copy environment variables:

```bash
cp .env.local.template .env.local
```

3. Update `.env.local` if your backend is running on a different URL:

```env
BACKEND_URL=http://localhost:8518
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### Development

Run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Production Build

Build for production:

```bash
npm run build
npm start
```

Or use standalone output for Docker:

```bash
docker build -t neos-web .
docker run -p 3000:3000 -e BACKEND_URL=http://backend:8518 neos-web
```

## Project Structure

```
web/
├── app/                      # Next.js App Router
│   ├── api/                 # API routes (BFF layer)
│   │   └── chat/           # Chat API endpoint
│   ├── layout.tsx          # Root layout
│   ├── page.tsx            # Home page
│   └── globals.css         # Global styles
├── components/              # React components
│   └── chat/               # Chat-related components
│       ├── ChatInterface.tsx    # Main chat container
│       ├── Header.tsx          # Header with title
│       ├── Sidebar.tsx         # Session list sidebar
│       ├── MessageList.tsx     # Message display
│       ├── MessageBubble.tsx   # Individual message
│       └── InputBox.tsx        # Message input
├── lib/                     # Utilities and stores
│   ├── stores/             # Zustand stores
│   │   └── chat-store.ts  # Chat state management
│   ├── types.ts           # TypeScript type definitions
│   └── utils.ts           # Utility functions
├── public/                  # Static assets
├── .env.local              # Environment variables
├── next.config.js          # Next.js configuration
├── tailwind.config.ts      # Tailwind CSS configuration
├── tsconfig.json           # TypeScript configuration
└── package.json            # Dependencies

```

## API Routes (BFF Layer)

### POST /api/chat

Proxies requests to the NEOS backend with additional processing.

**Request:**
```json
{
  "query": "What is the weather like?",
  "user_id": "user123",
  "session_id": "session_abc",
  "preferences": {
    "max_iterations": 10,
    "agent_timeout": 300,
    "response_format": "text"
  }
}
```

**Response:**
```json
{
  "success": true,
  "response": "The current weather is...",
  "metadata": {
    "execution_time": 1234,
    "quality_score": 0.95,
    "agent_used": "RealtimeDataSearchAgent",
    "session_id": "session_abc"
  },
  "timestamp": "2025-11-04T12:00:00Z"
}
```

## State Management

The app uses Zustand for state management with local storage persistence:

- **Sessions**: Multiple chat conversations
- **Messages**: Chat message history
- **Loading States**: UI loading indicators
- **Error Handling**: Error state management

## Customization

### Theme

Edit `tailwind.config.ts` to customize colors:

```typescript
colors: {
  primary: {
    DEFAULT: "#CC785C",
    hover: "#B86A4E",
  },
  claude: {
    dark: "#1F1F1F",
    darker: "#171717",
    // ...
  },
}
```

### Backend URL

Update `BACKEND_URL` in `.env.local` or use environment variables:

```bash
BACKEND_URL=https://your-backend.com npm run dev
```

## Troubleshooting

### Backend Connection Issues

1. Ensure the NEOS backend is running:
```bash
cd ..
python -m neos.main
```

2. Check CORS settings in backend (should allow localhost:3000)

3. Verify `BACKEND_URL` in `.env.local`

### Build Errors

1. Clear Next.js cache:
```bash
rm -rf .next
npm run build
```

2. Check TypeScript errors:
```bash
npm run type-check
```

## Contributing

Follow the main NEOS contribution guidelines. For UI-specific changes:

1. Follow the existing component structure
2. Use Tailwind CSS for styling
3. Maintain TypeScript type safety
4. Test on mobile devices

## License

Same as main NEOS project.
