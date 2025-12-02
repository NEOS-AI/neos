# NEOS 프론트엔드 구현 문서 (NEOS Frontend Implementation)

## 목차 (Table of Contents)

1. [기술 스택](#기술-스택-technology-stack)
2. [프로젝트 구조](#프로젝트-구조-project-structure)
3. [상태 관리](#상태-관리-state-management)
4. [라우팅 및 페이지](#라우팅-및-페이지-routing-and-pages)
5. [컴포넌트 아키텍처](#컴포넌트-아키텍처-component-architecture)
6. [API 통합](#api-통합-api-integration)
7. [채팅 모드](#채팅-모드-chat-modes)
8. [실시간 통신](#실시간-통신-real-time-communication)
9. [스타일링 및 테마](#스타일링-및-테마-styling-and-theming)
10. [성능 최적화](#성능-최적화-performance-optimization)

---

## 기술 스택 (Technology Stack)

### 핵심 프레임워크

```json
{
  "version": "0.5.0",
  "framework": "Next.js 14.2.33",
  "runtime": "React 18.3.1",
  "language": "TypeScript 5.9.3",
  "styling": "Tailwind CSS 3.4.17",
  "stateManagement": "Zustand 4.5.7",
  "icons": "Lucide React 0.454.0",
  "routing": "Next.js App Router",
  "markdown": "react-markdown 9.1.0 + remark-gfm 4.0.1",
  "virtualization": "@tanstack/react-virtual 3.10.8"
}
```

### 주요 라이브러리

```json
{
  "dependencies": {
    "next": "^14.2.33",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.7",
    "react-markdown": "^9.1.0",
    "remark-gfm": "^4.0.1",
    "lucide-react": "^0.454.0",
    "axios": "^1.13.1",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.6.0",
    "nanoid": "^5.1.6",
    "@tanstack/react-virtual": "^3.10.8",
    "ioredis": "^5.4.2",
    "iron-session": "^8.0.3"
  },
  "devDependencies": {
    "@types/react": "^18",
    "@types/node": "^20",
    "typescript": "^5",
    "eslint": "^8",
    "tailwindcss": "^3.4.1",
    "postcss": "^8",
    "@testing-library/react": "^14.0.0",
    "@testing-library/jest-dom": "^6.1.4",
    "jest": "^29.7.0"
  }
}
```

### 개발 도구

- **TypeScript**: 정적 타입 체크
- **ESLint**: 코드 린팅
- **Prettier**: 코드 포맷팅
- **Turbopack**: Next.js 14 기본 번들러

---

## 프로젝트 구조 (Project Structure)

```
web/
├── app/                           # Next.js App Router
│   ├── layout.tsx                 # 루트 레이아웃
│   ├── page.tsx                   # 홈페이지 (/)
│   │
│   ├── chat/                      # 채팅 페이지
│   │   └── [id]/
│   │       └── page.tsx           # /chat/:id
│   │
│   ├── login/                     # 로그인 페이지
│   │   └── page.tsx               # /login
│   │
│   ├── register/                  # 회원가입 페이지
│   │   └── page.tsx               # /register
│   │
│   ├── api/                       # API 라우트
│   │   └── [...routes]/
│   │       └── route.ts
│   │
│   └── globals.css                # 글로벌 스타일
│
├── components/                    # React 컴포넌트
│   ├── chat/                      # 채팅 관련 컴포넌트
│   │   ├── ChatInterface.tsx      # 메인 채팅 인터페이스
│   │   ├── MessageList.tsx        # 메시지 목록
│   │   ├── MessageBubble.tsx      # 개별 메시지
│   │   ├── InputBox.tsx           # 입력창
│   │   ├── SettingsPanel.tsx      # 설정 패널
│   │   ├── Sidebar.tsx            # 사이드바
│   │   ├── ModeSelector.tsx       # 모드 선택기
│   │   ├── StreamingIndicator.tsx # 스트리밍 표시기
│   │   ├── SourceCard.tsx         # 소스 카드
│   │   └── ResearchProgress.tsx   # 연구 진행 상황
│   │
│   ├── home/                      # 홈페이지 컴포넌트 (6개)
│   │   ├── Sidebar.tsx            # 홈 사이드바 (~350 LOC)
│   │   ├── TopBar.tsx             # 상단 네비게이션 (~100 LOC)
│   │   ├── ChatComposer.tsx       # 대형 메시지 입력 (~150 LOC)
│   │   ├── ModeSelector.tsx       # 모드 선택 드롭다운 (~100 LOC)
│   │   ├── GreetingHero.tsx       # Claude 스타일 환영 메시지 (~50 LOC)
│   │   └── QuickActions.tsx       # 빠른 작업 버튼 (~100 LOC)
│   │
│   ├── auth/                      # 인증 컴포넌트
│   │   ├── LoginForm.tsx          # 로그인 폼
│   │   ├── RegisterForm.tsx       # 회원가입 폼
│   │   └── AuthGuard.tsx          # 인증 가드
│   │
│   ├── common/                    # 공통 컴포넌트
│   │   ├── ErrorBoundary.tsx      # React 에러 처리
│   │   ├── PerformanceMonitor.tsx # 런타임 성능 추적
│   │   ├── LoadingSpinner.tsx     # 로딩 스피너
│   │   ├── Button.tsx             # 버튼
│   │   ├── Input.tsx              # 입력
│   │   ├── Modal.tsx              # 모달
│   │   └── Toast.tsx              # 토스트 알림
│   │
│   └── providers/                 # Context Providers
│       ├── ThemeProvider.tsx      # 테마 프로바이더
│       └── AuthProvider.tsx       # 인증 프로바이더
│
├── lib/                           # 라이브러리 & 유틸리티
│   ├── api/                       # API 클라이언트
│   │   └── chat-api.ts            # 통합 Chat API (100+ methods, Strategy/Factory patterns)
│   │
│   ├── stores/                    # Zustand 스토어
│   │   └── chat-store.ts          # 통합 Chat Store (2,449 LOC, 40+ actions)
│   │
│   ├── contexts/                  # React Contexts
│   │   └── auth-context.tsx       # 글로벌 Auth 컨텍스트
│   │
│   ├── hooks/                     # Custom Hooks
│   │   ├── useAuthSync.ts         # Auth 상태 동기화
│   │   └── use-*.ts               # 기타 커스텀 훅
│   │
│   ├── __tests__/                 # 단위 테스트
│   │   ├── ChatInterface.test.tsx
│   │   ├── InputBox.test.tsx
│   │   └── MessageBubble.test.tsx
│   │
│   ├── types/                     # TypeScript 타입 정의
│   │   ├── chat.ts                # 채팅 타입
│   │   ├── message.ts             # 메시지 타입
│   │   ├── user.ts                # 사용자 타입
│   │   └── api.ts                 # API 타입
│   │
│   ├── auth.ts                    # JWT + Refresh 토큰 시스템
│   ├── fetchWithCsrf.ts           # CSRF 토큰 자동 관리
│   ├── errorLogger.ts             # 구조화된 에러 로깅
│   ├── inputValidation.ts         # 입력 검증 (1-32,000자)
│   ├── sessionValidation.ts       # 서버 사이드 인증 검증
│   ├── rateLimit.ts               # Sliding window rate limiter
│   └── utils.ts                   # 유틸리티 함수
│
├── middleware.ts                  # Next.js 미들웨어 (보안 헤더, Auth 체크)
├── public/                        # 정적 자산
│   ├── images/
│   ├── icons/
│   └── fonts/
│
├── .env.local.template            # 환경 변수 템플릿
├── next.config.js                 # Next.js 설정 (standalone build)
├── tailwind.config.ts             # Tailwind 설정
├── tsconfig.json                  # TypeScript 설정
├── jest.config.js                 # Jest 테스트 설정
└── package.json                   # 프로젝트 메타데이터 (v0.5.0)
```

---

## 상태 관리 (State Management)

NEOS는 **Zustand**를 사용하여 전역 상태를 관리합니다. Redux보다 간단하면서도 TypeScript 지원이 우수합니다.

### Chat Store (chat-store.ts)

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// 타입 정의
interface Message {
  message_id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tokens_used?: number;
  cost?: number;
  quality_score?: number;
  created_at: string;
}

interface Conversation {
  conversation_id: string;
  user_id: string;
  session_id: string;
  title: string;
  mode: 'standard' | 'rag' | 'similarity' | 'deep_research';
  status: string;
  created_at: string;
  updated_at: string;
}

interface ChatSettings {
  model: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
}

interface ChatState {
  // 현재 대화
  currentConversationId: string | null;
  currentMessages: Message[];

  // 대화 목록
  conversations: Conversation[];

  // 설정
  settings: ChatSettings;

  // UI 상태
  isLoading: boolean;
  isSidebarOpen: boolean;
  isSettingsPanelOpen: boolean;

  // 채팅 모드
  selectedMode: 'standard' | 'rag' | 'similarity' | 'deep_research';

  // WebSocket 연결 상태
  wsConnected: boolean;

  // Actions
  setCurrentConversation: (conversationId: string) => void;
  addMessage: (message: Message) => void;
  updateMessage: (messageId: string, updates: Partial<Message>) => void;
  setConversations: (conversations: Conversation[]) => void;
  updateSettings: (settings: Partial<ChatSettings>) => void;
  toggleSidebar: () => void;
  toggleSettingsPanel: () => void;
  setSelectedMode: (mode: string) => void;
  setWsConnected: (connected: boolean) => void;
  clearCurrentConversation: () => void;
}

// Zustand 스토어 생성
export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      // 초기 상태
      currentConversationId: null,
      currentMessages: [],
      conversations: [],
      settings: {
        model: 'gpt-4-turbo-preview',
        temperature: 0.7,
        max_tokens: 2000,
        top_p: 0.9,
      },
      isLoading: false,
      isSidebarOpen: true,
      isSettingsPanelOpen: false,
      selectedMode: 'standard',
      wsConnected: false,

      // Actions
      setCurrentConversation: (conversationId) => {
        set({ currentConversationId: conversationId, currentMessages: [] });
      },

      addMessage: (message) => {
        set((state) => ({
          currentMessages: [...state.currentMessages, message],
        }));
      },

      updateMessage: (messageId, updates) => {
        set((state) => ({
          currentMessages: state.currentMessages.map((msg) =>
            msg.message_id === messageId ? { ...msg, ...updates } : msg
          ),
        }));
      },

      setConversations: (conversations) => {
        set({ conversations });
      },

      updateSettings: (newSettings) => {
        set((state) => ({
          settings: { ...state.settings, ...newSettings },
        }));
      },

      toggleSidebar: () => {
        set((state) => ({ isSidebarOpen: !state.isSidebarOpen }));
      },

      toggleSettingsPanel: () => {
        set((state) => ({ isSettingsPanelOpen: !state.isSettingsPanelOpen }));
      },

      setSelectedMode: (mode) => {
        set({ selectedMode: mode as any });
      },

      setWsConnected: (connected) => {
        set({ wsConnected: connected });
      },

      clearCurrentConversation: () => {
        set({ currentConversationId: null, currentMessages: [] });
      },
    }),
    {
      name: 'neos-chat-storage', // localStorage 키
      partialize: (state) => ({
        // 로컬스토리지에 저장할 상태만 선택
        settings: state.settings,
        selectedMode: state.selectedMode,
        isSidebarOpen: state.isSidebarOpen,
      }),
    }
  )
);
```

### Auth Store (auth-store.ts)

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  user_id: string;
  email: string;
  username?: string;
  role: string;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;

  // Actions
  login: (user: User, accessToken: string, refreshToken: string) => void;
  logout: () => void;
  updateUser: (user: Partial<User>) => void;
  setAccessToken: (token: string) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,

      login: (user, accessToken, refreshToken) => {
        set({
          user,
          accessToken,
          refreshToken,
          isAuthenticated: true,
        });
      },

      logout: () => {
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
        });
      },

      updateUser: (updates) => {
        set((state) => ({
          user: state.user ? { ...state.user, ...updates } : null,
        }));
      },

      setAccessToken: (token) => {
        set({ accessToken: token });
      },
    }),
    {
      name: 'neos-auth-storage',
    }
  )
);
```

### UI Store (ui-store.ts)

```typescript
import { create } from 'zustand';

interface UIState {
  theme: 'light' | 'dark';
  isModalOpen: boolean;
  modalContent: React.ReactNode | null;
  toasts: Array<{
    id: string;
    type: 'success' | 'error' | 'info' | 'warning';
    message: string;
  }>;

  // Actions
  setTheme: (theme: 'light' | 'dark') => void;
  openModal: (content: React.ReactNode) => void;
  closeModal: () => void;
  addToast: (type: string, message: string) => void;
  removeToast: (id: string) => void;
}

export const useUIStore = create<UIState>((set) => ({
  theme: 'dark',
  isModalOpen: false,
  modalContent: null,
  toasts: [],

  setTheme: (theme) => set({ theme }),

  openModal: (content) => set({ isModalOpen: true, modalContent: content }),

  closeModal: () => set({ isModalOpen: false, modalContent: null }),

  addToast: (type, message) => {
    const id = Math.random().toString(36).substring(7);
    set((state) => ({
      toasts: [...state.toasts, { id, type: type as any, message }],
    }));
    // 3초 후 자동 제거
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((toast) => toast.id !== id),
      }));
    }, 3000);
  },

  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    }));
  },
}));
```

---

## 라우팅 및 페이지 (Routing and Pages)

### App Router 구조

Next.js 14의 App Router를 사용하여 파일 기반 라우팅을 구현합니다.

```
app/
├── layout.tsx              # 루트 레이아웃
├── page.tsx                # / (홈페이지)
├── chat/
│   └── [id]/
│       └── page.tsx        # /chat/:id (채팅 페이지)
├── login/
│   └── page.tsx            # /login (로그인)
├── register/
│   └── page.tsx            # /register (회원가입)
└── api/
    └── [...routes]/
        └── route.ts        # API 라우트
```

### 1. 홈페이지 (app/page.tsx)

```tsx
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useChatStore } from '@/lib/stores/chat-store';
import ChatComposer from '@/components/home/ChatComposer';
import ModeSelector from '@/components/home/ModeSelector';
import QuickActions from '@/components/home/QuickActions';
import GreetingHero from '@/components/home/GreetingHero';
import Sidebar from '@/components/home/Sidebar';

export default function HomePage() {
  const router = useRouter();
  const { selectedMode, setSelectedMode } = useChatStore();
  const [query, setQuery] = useState('');

  const handleSubmit = async (query: string) => {
    // 1. 새 대화 생성
    const response = await fetch('/api/v1/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: 'current-user-id',
        mode: selectedMode,
      }),
    });

    const { conversation_id } = await response.json();

    // 2. 채팅 페이지로 이동
    router.push(`/chat/${conversation_id}?initialQuery=${encodeURIComponent(query)}`);
  };

  return (
    <div className="flex h-screen bg-[#050d4d]">
      {/* 사이드바 */}
      <Sidebar />

      {/* 메인 콘텐츠 */}
      <main className="flex-1 flex flex-col items-center justify-center p-8">
        {/* 환영 메시지 */}
        <GreetingHero />

        {/* 모드 선택 */}
        <ModeSelector
          selectedMode={selectedMode}
          onModeChange={setSelectedMode}
        />

        {/* 채팅 작성기 */}
        <ChatComposer
          value={query}
          onChange={setQuery}
          onSubmit={handleSubmit}
          placeholder="Ask me anything..."
        />

        {/* 빠른 작업 */}
        <QuickActions onActionClick={handleSubmit} />
      </main>
    </div>
  );
}
```

### 2. 채팅 페이지 (app/chat/[id]/page.tsx)

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { useChatStore } from '@/lib/stores/chat-store';
import ChatInterface from '@/components/chat/ChatInterface';
import MessageList from '@/components/chat/MessageList';
import InputBox from '@/components/chat/InputBox';
import Sidebar from '@/components/chat/Sidebar';
import SettingsPanel from '@/components/chat/SettingsPanel';
import ResearchProgress from '@/components/chat/ResearchProgress';
import { useWebSocket } from '@/lib/hooks/useWebSocket';
import { useSSE } from '@/lib/hooks/useSSE';

export default function ChatPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const conversationId = params.id as string;
  const initialQuery = searchParams.get('initialQuery');

  const {
    currentMessages,
    setCurrentConversation,
    addMessage,
    selectedMode,
    settings,
  } = useChatStore();

  // WebSocket 연결 (실시간 업데이트용)
  const { sendMessage: sendWsMessage, lastMessage } = useWebSocket(conversationId);

  // SSE 연결 (Deep Research 진행 상황용)
  const { events: sseEvents, isConnected: sseConnected } = useSSE(
    selectedMode === 'deep_research' ? `/api/v1/deep-research/${conversationId}/stream` : null
  );

  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    setCurrentConversation(conversationId);

    // 초기 쿼리가 있으면 자동으로 전송
    if (initialQuery) {
      handleSendMessage(initialQuery);
    }
  }, [conversationId, initialQuery]);

  // WebSocket 메시지 수신 처리
  useEffect(() => {
    if (lastMessage) {
      const data = JSON.parse(lastMessage.data);

      if (data.type === 'agent_started') {
        // 에이전트 시작 알림
      } else if (data.type === 'result_ready') {
        // 결과 수신
        addMessage(data.message);
        setIsLoading(false);
      }
    }
  }, [lastMessage]);

  const handleSendMessage = async (content: string) => {
    setIsLoading(true);

    // 사용자 메시지 추가
    const userMessage = {
      message_id: `temp-${Date.now()}`,
      conversation_id: conversationId,
      role: 'user' as const,
      content,
      created_at: new Date().toISOString(),
    };
    addMessage(userMessage);

    try {
      // 메시지 전송 (스트리밍 모드)
      const response = await fetch(`/api/v1/conversations/${conversationId}/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'user', content }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';

      while (true) {
        const { done, value } = await reader!.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.substring(6));

            if (data.type === 'token') {
              assistantMessage += data.content;
              // 실시간으로 메시지 업데이트
              addMessage({
                message_id: `assistant-${Date.now()}`,
                conversation_id: conversationId,
                role: 'assistant',
                content: assistantMessage,
                created_at: new Date().toISOString(),
              });
            } else if (data.type === 'done') {
              setIsLoading(false);
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#050d4d]">
      {/* 사이드바 */}
      <Sidebar />

      {/* 메인 채팅 영역 */}
      <main className="flex-1 flex flex-col">
        {/* 메시지 목록 */}
        <MessageList messages={currentMessages} />

        {/* Deep Research 진행 상황 */}
        {selectedMode === 'deep_research' && sseConnected && (
          <ResearchProgress events={sseEvents} />
        )}

        {/* 입력창 */}
        <InputBox
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          disabled={isLoading}
        />
      </main>

      {/* 설정 패널 */}
      <SettingsPanel />
    </div>
  );
}
```

### 3. 로그인 페이지 (app/login/page.tsx)

```tsx
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/stores/auth-store';
import LoginForm from '@/components/auth/LoginForm';

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuthStore();
  const [error, setError] = useState('');

  const handleLogin = async (email: string, password: string) => {
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        throw new Error('Login failed');
      }

      const data = await response.json();
      login(data.user, data.access_token, data.refresh_token);
      router.push('/');
    } catch (err) {
      setError('Invalid email or password');
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-[#050d4d]">
      <div className="w-full max-w-md">
        <h1 className="text-3xl font-bold text-white mb-8 text-center">
          Login to NEOS
        </h1>
        <LoginForm onSubmit={handleLogin} error={error} />
      </div>
    </div>
  );
}
```

---

## 컴포넌트 아키텍처 (Component Architecture)

### 1. ChatInterface 컴포넌트

```tsx
// components/chat/ChatInterface.tsx
'use client';

import { useState, useRef, useEffect } from 'react';
import MessageList from './MessageList';
import InputBox from './InputBox';
import StreamingIndicator from './StreamingIndicator';

interface ChatInterfaceProps {
  conversationId: string;
  onSendMessage: (content: string) => Promise<void>;
}

export default function ChatInterface({ conversationId, onSendMessage }: ChatInterfaceProps) {
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 자동 스크롤
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, []);

  const handleSend = async (content: string) => {
    setIsStreaming(true);
    await onSendMessage(content);
    setIsStreaming(false);
    scrollToBottom();
  };

  return (
    <div className="flex flex-col h-full">
      <MessageList conversationId={conversationId} />
      {isStreaming && <StreamingIndicator />}
      <div ref={messagesEndRef} />
      <InputBox onSendMessage={handleSend} disabled={isStreaming} />
    </div>
  );
}
```

### 2. MessageBubble 컴포넌트

```tsx
// components/chat/MessageBubble.tsx
'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check, ThumbsUp, ThumbsDown } from 'lucide-react';
import SourceCard from './SourceCard';

interface MessageBubbleProps {
  message: {
    message_id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    created_at: string;
    sources?: Array<{ url: string; title: string }>;
  };
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-3xl px-6 py-4 rounded-lg ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-gray-800 text-gray-100 border border-gray-700'
        }`}
      >
        {/* 메시지 내용 (Markdown 렌더링) */}
        <div className="prose prose-invert max-w-none">
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>

        {/* 소스 카드 (assistant 메시지만) */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-sm text-gray-400">Sources:</p>
            {message.sources.map((source, idx) => (
              <SourceCard key={idx} source={source} />
            ))}
          </div>
        )}

        {/* 액션 버튼 (assistant 메시지만) */}
        {!isUser && (
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-700">
            <button
              onClick={handleCopy}
              className="p-1 hover:bg-gray-700 rounded transition-colors"
              title="Copy"
            >
              {copied ? (
                <Check className="w-4 h-4 text-green-500" />
              ) : (
                <Copy className="w-4 h-4 text-gray-400" />
              )}
            </button>
            <button
              className="p-1 hover:bg-gray-700 rounded transition-colors"
              title="Good response"
            >
              <ThumbsUp className="w-4 h-4 text-gray-400 hover:text-green-500" />
            </button>
            <button
              className="p-1 hover:bg-gray-700 rounded transition-colors"
              title="Bad response"
            >
              <ThumbsDown className="w-4 h-4 text-gray-400 hover:text-red-500" />
            </button>
          </div>
        )}

        {/* 타임스탬프 */}
        <p className="text-xs text-gray-500 mt-2">
          {new Date(message.created_at).toLocaleTimeString()}
        </p>
      </div>
    </div>
  );
}
```

### 3. ModeSelector 컴포넌트

```tsx
// components/home/ModeSelector.tsx
'use client';

import { Search, Database, BarChart, Microscope } from 'lucide-react';

interface ModeSelectorProps {
  selectedMode: 'standard' | 'rag' | 'similarity' | 'deep_research';
  onModeChange: (mode: string) => void;
}

const modes = [
  {
    id: 'standard',
    name: 'Standard',
    description: 'General conversation',
    icon: Search,
  },
  {
    id: 'rag',
    name: 'RAG',
    description: 'Knowledge base search',
    icon: Database,
  },
  {
    id: 'similarity',
    name: 'Similarity',
    description: 'Find similar messages',
    icon: BarChart,
  },
  {
    id: 'deep_research',
    name: 'Deep Research',
    description: 'Comprehensive research (15-30 min)',
    icon: Microscope,
  },
];

export default function ModeSelector({ selectedMode, onModeChange }: ModeSelectorProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      {modes.map((mode) => {
        const Icon = mode.icon;
        const isSelected = selectedMode === mode.id;

        return (
          <button
            key={mode.id}
            onClick={() => onModeChange(mode.id)}
            className={`p-4 rounded-lg border-2 transition-all ${
              isSelected
                ? 'border-blue-500 bg-blue-500/10'
                : 'border-gray-700 bg-gray-800 hover:border-gray-600'
            }`}
          >
            <Icon className={`w-8 h-8 mb-2 ${isSelected ? 'text-blue-500' : 'text-gray-400'}`} />
            <h3 className="font-semibold text-white mb-1">{mode.name}</h3>
            <p className="text-sm text-gray-400">{mode.description}</p>
          </button>
        );
      })}
    </div>
  );
}
```

### 4. ResearchProgress 컴포넌트

```tsx
// components/chat/ResearchProgress.tsx
'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

interface ResearchEvent {
  phase: string;
  progress: number;
  message: string;
  sources_found?: number;
  insights?: string[];
}

interface ResearchProgressProps {
  events: ResearchEvent[];
}

export default function ResearchProgress({ events }: ResearchProgressProps) {
  const latestEvent = events[events.length - 1];

  if (!latestEvent) return null;

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 mb-4">
      <div className="flex items-center gap-3">
        <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
        <div className="flex-1">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold text-white">
              {latestEvent.phase.charAt(0).toUpperCase() + latestEvent.phase.slice(1)}
            </span>
            <span className="text-sm text-gray-400">{latestEvent.progress}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${latestEvent.progress}%` }}
            />
          </div>
          <p className="text-sm text-gray-400 mt-2">{latestEvent.message}</p>
          {latestEvent.sources_found && (
            <p className="text-xs text-gray-500 mt-1">
              {latestEvent.sources_found} sources found
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
```

---

## API 통합 (API Integration)

### HTTP Client (chat-api.ts)

```typescript
// lib/api/chat-api.ts
import axios, { AxiosInstance } from 'axios';
import { useAuthStore } from '@/lib/stores/auth-store';

class ChatAPI {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // 요청 인터셉터 (JWT 토큰 추가)
    this.client.interceptors.request.use(
      (config) => {
        const { accessToken } = useAuthStore.getState();
        if (accessToken) {
          config.headers.Authorization = `Bearer ${accessToken}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // 응답 인터셉터 (에러 처리)
    this.client.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config;

        // 401 에러 시 토큰 갱신
        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true;

          try {
            const { refreshToken } = useAuthStore.getState();
            const response = await axios.post('/api/v1/auth/refresh', {
              refresh_token: refreshToken,
            });

            const { access_token } = response.data;
            useAuthStore.getState().setAccessToken(access_token);

            originalRequest.headers.Authorization = `Bearer ${access_token}`;
            return this.client(originalRequest);
          } catch (refreshError) {
            useAuthStore.getState().logout();
            window.location.href = '/login';
            return Promise.reject(refreshError);
          }
        }

        return Promise.reject(error);
      }
    );
  }

  // 대화 생성
  async createConversation(userId: string, mode: string, title?: string) {
    const response = await this.client.post('/api/v1/conversations', {
      user_id: userId,
      mode,
      title,
    });
    return response.data;
  }

  // 메시지 전송
  async sendMessage(conversationId: string, content: string) {
    const response = await this.client.post(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        role: 'user',
        content,
      }
    );
    return response.data;
  }

  // 메시지 스트리밍
  async* streamMessage(conversationId: string, content: string) {
    const response = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/conversations/${conversationId}/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        },
        body: JSON.stringify({ role: 'user', content }),
      }
    );

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          yield JSON.parse(line.substring(6));
        }
      }
    }
  }

  // 대화 조회
  async getConversation(conversationId: string) {
    const response = await this.client.get(`/api/v1/conversations/${conversationId}`);
    return response.data;
  }

  // 대화 목록
  async listConversations(userId: string, limit = 20, offset = 0) {
    const response = await this.client.get('/api/v1/conversations', {
      params: { user_id: userId, limit, offset },
    });
    return response.data;
  }

  // 메시지 재생성
  async regenerateMessage(messageId: string) {
    const response = await this.client.post(`/api/v1/messages/${messageId}/regenerate`);
    return response.data;
  }
}

export const chatAPI = new ChatAPI();
```

### WebSocket Hook (useWebSocket.ts)

```typescript
// lib/hooks/useWebSocket.ts
import { useEffect, useState, useRef, useCallback } from 'react';
import { useChatStore } from '@/lib/stores/chat-store';

interface WebSocketMessage {
  type: string;
  data: any;
}

export function useWebSocket(sessionId: string) {
  const [lastMessage, setLastMessage] = useState<MessageEvent | null>(null);
  const { setWsConnected } = useChatStore();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/api/v1/ws/${sessionId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setWsConnected(true);
    };

    ws.onmessage = (event) => {
      setLastMessage(event);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setWsConnected(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [sessionId]);

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { sendMessage, lastMessage };
}
```

### SSE Hook (useSSE.ts)

```typescript
// lib/hooks/useSSE.ts
import { useEffect, useState } from 'react';
import { useAuthStore } from '@/lib/stores/auth-store';

interface SSEEvent {
  [key: string]: any;
}

export function useSSE(url: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const { accessToken } = useAuthStore();

  useEffect(() => {
    if (!url) return;

    const fullUrl = `${process.env.NEXT_PUBLIC_API_URL}${url}`;
    const eventSource = new EventSource(fullUrl, {
      withCredentials: true,
    });

    eventSource.onopen = () => {
      console.log('SSE connected');
      setIsConnected(true);
    };

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setEvents((prev) => [...prev, data]);
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      setIsConnected(false);
      eventSource.close();
    };

    return () => {
      eventSource.close();
      setIsConnected(false);
    };
  }, [url]);

  return { events, isConnected };
}
```

---

## 채팅 모드 (Chat Modes)

NEOS는 4가지 채팅 모드를 지원합니다:

### 1. Standard Mode
- **용도**: 일반 대화
- **특징**: 빠른 응답, 범용 지식
- **UI**: 기본 채팅 인터페이스

### 2. RAG Mode
- **용도**: 지식 베이스 검색
- **특징**: 업로드된 문서 기반 답변
- **UI**: 소스 문서 표시

### 3. Similarity Mode
- **용도**: 유사 메시지 검색
- **특징**: 과거 대화 기록 기반
- **UI**: 유사도 점수 표시

### 4. Deep Research Mode
- **용도**: 심층 연구
- **특징**: 30-50+ 소스, 15-30분 소요
- **UI**: 실시간 진행 상황 표시 (SSE)

---

## 실시간 통신 (Real-time Communication)

### WebSocket (Query Processing)

```typescript
// 실시간 쿼리 처리 업데이트
const ws = new WebSocket(`ws://localhost:8000/api/v1/ws/${sessionId}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case 'query_started':
      // 쿼리 시작
      break;
    case 'agent_started':
      // 에이전트 실행 시작
      console.log(`Agent ${data.agent_name} started`);
      break;
    case 'agent_completed':
      // 에이전트 완료
      console.log(`Agent ${data.agent_name} completed`);
      break;
    case 'result_ready':
      // 최종 결과
      displayResult(data.result);
      break;
    case 'error':
      // 에러
      showError(data.message);
      break;
  }
};
```

### Server-Sent Events (Deep Research)

```typescript
// 심층 연구 진행 상황 스트리밍
const eventSource = new EventSource(`/api/v1/deep-research/${reportId}/stream`);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // 진행 상황 업데이트
  updateProgress({
    phase: data.phase,
    progress: data.progress,
    message: data.message,
    sourcesFound: data.sources_found,
  });

  if (data.phase === 'completed') {
    eventSource.close();
    displayFinalReport(data.report_url);
  }
};

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
  // 재연결 로직
  setTimeout(() => {
    eventSource.close();
    // 새 EventSource 생성
  }, 2000);
};
```

---

## 스타일링 및 테마 (Styling and Theming)

### Tailwind 설정 (tailwind.config.ts)

```typescript
import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // NEOS 다크 블루 테마
        primary: '#050d4d',
        secondary: '#0a1a7a',
        accent: '#3b82f6',
        background: {
          DEFAULT: '#050d4d',
          lighter: '#0a1a7a',
        },
        text: {
          primary: '#ffffff',
          secondary: '#9ca3af',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['Fira Code', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
  darkMode: 'class',
};

export default config;
```

### 글로벌 스타일 (app/globals.css)

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --primary: #050d4d;
  --secondary: #0a1a7a;
  --accent: #3b82f6;
}

body {
  @apply bg-primary text-white font-sans antialiased;
}

/* 스크롤바 스타일 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  @apply bg-gray-800;
}

::-webkit-scrollbar-thumb {
  @apply bg-gray-600 rounded-full;
}

::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500;
}

/* 마크다운 스타일 */
.prose {
  @apply max-w-none text-gray-100;
}

.prose code {
  @apply bg-gray-800 px-1 py-0.5 rounded text-sm;
}

.prose pre {
  @apply bg-gray-900 p-4 rounded-lg overflow-x-auto;
}

.prose pre code {
  @apply bg-transparent p-0;
}
```

---

## 성능 최적화 (Performance Optimization)

### 1. 코드 스플리팅

```typescript
// 동적 임포트로 코드 스플리팅
import dynamic from 'next/dynamic';

const SettingsPanel = dynamic(() => import('@/components/chat/SettingsPanel'), {
  loading: () => <LoadingSpinner />,
  ssr: false, // 클라이언트 사이드만 렌더링
});

const HeavyComponent = dynamic(() => import('@/components/HeavyComponent'), {
  loading: () => <p>Loading...</p>,
});
```

### 2. 메모이제이션

```typescript
import { memo, useMemo, useCallback } from 'react';

// 컴포넌트 메모이제이션
export default memo(function MessageBubble({ message }) {
  // ...
}, (prevProps, nextProps) => {
  // 커스텀 비교 함수
  return prevProps.message.message_id === nextProps.message.message_id;
});

// 값 메모이제이션
const sortedMessages = useMemo(() => {
  return messages.sort((a, b) =>
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
}, [messages]);

// 함수 메모이제이션
const handleSend = useCallback((content: string) => {
  // ...
}, [dependency]);
```

### 3. 가상화 (Virtualization)

```typescript
// 긴 메시지 목록에 대한 가상화
import { FixedSizeList } from 'react-window';

function MessageList({ messages }) {
  return (
    <FixedSizeList
      height={600}
      itemCount={messages.length}
      itemSize={80}
      width="100%"
    >
      {({ index, style }) => (
        <div style={style}>
          <MessageBubble message={messages[index]} />
        </div>
      )}
    </FixedSizeList>
  );
}
```

### 4. 이미지 최적화

```typescript
import Image from 'next/image';

// Next.js Image 컴포넌트 사용
<Image
  src="/images/logo.png"
  alt="NEOS Logo"
  width={200}
  height={50}
  priority // LCP 개선
  placeholder="blur" // 블러 플레이스홀더
/>
```

### 5. 로컬 스토리지 캐싱

```typescript
// 대화 목록 캐싱
const cachedConversations = localStorage.getItem('conversations');
if (cachedConversations) {
  setConversations(JSON.parse(cachedConversations));
} else {
  const conversations = await chatAPI.listConversations(userId);
  localStorage.setItem('conversations', JSON.stringify(conversations));
  setConversations(conversations);
}
```

---

## 환경 변수 (.env.local)

```env
# API 엔드포인트
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# 앱 설정
NEXT_PUBLIC_APP_NAME=NEOS
NEXT_PUBLIC_APP_VERSION=0.11.0

# 기능 플래그
NEXT_PUBLIC_ENABLE_DEEP_RESEARCH=true
NEXT_PUBLIC_ENABLE_RAG=true
NEXT_PUBLIC_ENABLE_SIMILARITY=true

# 분석
NEXT_PUBLIC_GA_ID=G-XXXXXXXXXX
```

---

## 빌드 및 배포

### 개발 서버 실행

```bash
cd web
npm install
npm run dev
# http://localhost:3000
```

### 프로덕션 빌드

```bash
npm run build
npm run start
```

### 최적화 옵션 (next.config.js)

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // 프로덕션 최적화
  reactStrictMode: true,
  swcMinify: true,

  // 이미지 최적화
  images: {
    domains: ['localhost', 'api.neos.ai'],
    formats: ['image/avif', 'image/webp'],
  },

  // 환경 변수
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
};

module.exports = nextConfig;
```

---

**문서 버전**: 1.1
**최종 업데이트**: 2025-12-02
**프론트엔드 버전**: 0.5.0
**Framework**: Next.js 14.2.33 + React 18.3.1
**주요 개선**: Connection Resilience (5가지), Deep Research 재연결, 다중 탭 동기화
**다음 업데이트 예정**: 2026-02-02
