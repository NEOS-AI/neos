# NEOS Chat - 디버깅 지침서

## 🔍 현재 상황

**증상**: API 응답은 정상적으로 오지만 화면에 메시지가 표시되지 않음
**원인 조사**: 상세 디버그 로그 추가 완료

---

## 🧪 테스트 단계별 가이드

### 1단계: 서버 실행

```bash
# Terminal 1: Backend
cd /Users/ywsung/Desktop/neos/neos
uvicorn neos.main:app --reload --port 8000

# Terminal 2: Frontend
cd /Users/ywsung/Desktop/neos/web
npm run dev
```

### 2단계: 브라우저 접속

1. http://localhost:3000 접속
2. 개발자 도구 열기 (F12 또는 Cmd+Option+I)
3. Console 탭 선택

### 3단계: 메시지 전송

입력창에 "test" 입력 후 Enter

---

## 📊 예상 로그 순서

### 정상적인 경우

```javascript
// 1. 대화 생성 (처음인 경우)
[Store] No conversation exists, creating one...
[Store] Setting current conversation: 848e79bb-12b7-4b46-89ab-417520f7de9d

// 2. 메시지 전송 시작
[Store] Sending message to conversation: 848e79bb-12b7-4b46-89ab-417520f7de9d
[Store] Sending standard message...

// 3. API 응답 수신
[Store] Got response: {
  userMessageId: "72ec24f0-9ff3-4cf2-86ca-34a60fc8841d",
  assistantMessageId: "fcc757ee-ae71-40ec-ad86-677fc4d72459"
}

// 4. Store 업데이트 전
[Store] Adding messages to store...
[Store] ===== BEFORE UPDATE =====
[Store] Target conversation exists: true
[Store] Current messages count: 0
[Store] All conversation IDs: ["848e79bb-12b7-4b46-89ab-417520f7de9d"]

// 5. Store 업데이트 후
[Store] ===== AFTER UPDATE =====
[Store] Updated target exists: true
[Store] New messages count: 2
[Store] Message IDs: ["72ec24f0", "fcc757ee"]
[Store] Full updated conversation: {
  conversation_id: "848e79bb-12b7-4b46-89ab-417520f7de9d",
  messages: [
    { message_id: "72ec24f0...", role: "user", content: "test", ... },
    { message_id: "fcc757ee...", role: "assistant", content: "Hello! I'm here...", ... }
  ],
  message_count: 2,
  ...
}

// 6. 완료
[Store] Message sent successfully

// 7. Getter 호출 (자동)
[Store] currentConversation getter: {
  currentConversationId: "848e79bb-12b7-4b46-89ab-417520f7de9d",
  totalConversations: 1,
  found: true,
  messagesCount: 2
}

[Store] Getting messages: {
  conversationId: "848e79bb-12b7-4b46-89ab-417520f7de9d",
  messageCount: 2
}

// 8. 컴포넌트 렌더링
[MessageList] Component rendered: {
  messagesCount: 2,
  conversationId: "848e79bb-12b7-4b46-89ab-417520f7de9d",
  hasConversation: true,
  isLoading: false,
  isStreaming: false
}

[MessageList] Messages array changed: {
  count: 2,
  messages: [
    { id: "72ec24f0", role: "user", content: "test" },
    { id: "fcc757ee", role: "assistant", content: "Hello! I'm here and ready to..." }
  ]
}
```

---

## 🚨 문제 진단

### 문제 1: messages count가 0인 경우

**로그**:
```
[Store] New messages count: 0
```

**가능한 원인**:
1. `conversationId`가 일치하지 않음
2. `messages` 배열이 업데이트되지 않음

**확인 방법**:
```javascript
// Console에서 실행
const state = useChatStore.getState()
console.log("Conversations:", state.conversations)
console.log("Current ID:", state.currentConversationId)
console.log("Match:", state.conversations.find(c => c.conversation_id === state.currentConversationId))
```

**해결 방법**:
```javascript
// localStorage 초기화
localStorage.clear()
// 페이지 새로고침 (F5)
```

---

### 문제 2: currentConversation getter에서 found: false

**로그**:
```
[Store] currentConversation getter: {
  currentConversationId: "...",
  totalConversations: 1,
  found: false,  ← 문제!
  messagesCount: 0
}
```

**원인**: `currentConversationId`와 실제 conversation ID가 불일치

**확인 방법**:
```javascript
const state = useChatStore.getState()
console.log("Looking for:", state.currentConversationId)
console.log("Available:", state.conversations.map(c => c.conversation_id))
```

**해결 방법**:
1. "New Chat" 버튼으로 새 대화 생성
2. 또는 수동으로 ID 매칭:
```javascript
const state = useChatStore.getState()
state.setCurrentConversation(state.conversations[0].conversation_id)
```

---

### 문제 3: MessageList가 렌더링되지 않음

**로그**:
```
// MessageList 로그가 없음
```

**원인**: 컴포넌트가 마운트되지 않았거나 리렌더링되지 않음

**확인 방법**:
```javascript
// React DevTools에서 확인
// Components 탭 → MessageList 찾기 → Props 확인
```

**해결 방법**:
1. 페이지 새로고침 (F5)
2. React Strict Mode 확인 (개발 모드에서는 2번 렌더링됨)

---

### 문제 4: messages 배열이 비어있음

**로그**:
```
[MessageList] Messages array changed: {
  count: 0,
  messages: []
}
```

**하지만 Store에는 메시지가 있음**:
```
[Store] New messages count: 2
```

**원인**: Getter가 제대로 작동하지 않음

**확인 방법**:
```javascript
const state = useChatStore.getState()

// 1. Store에 메시지가 있는지 확인
console.log("In store:", state.conversations[0]?.messages)

// 2. Getter가 반환하는지 확인
console.log("From getter:", state.messages)

// 3. currentConversation 확인
console.log("Current:", state.currentConversation)
```

**해결 방법**:
```javascript
// Store 강제 업데이트
useChatStore.setState({})

// 또는 대화 재선택
const state = useChatStore.getState()
state.setCurrentConversation(state.currentConversationId)
```

---

## 🔬 수동 디버깅 명령어

### Store 상태 확인
```javascript
// 전체 상태
const state = useChatStore.getState()
console.log("Full state:", state)

// 대화 목록
console.log("Conversations:", state.conversations.map(c => ({
  id: c.conversation_id.slice(0, 8),
  title: c.title,
  messages: c.messages?.length || 0
})))

// 현재 대화
console.log("Current conversation:", state.currentConversation)

// 메시지
console.log("Messages:", state.messages)
```

### Store 직접 조작
```javascript
// 메시지 수동 추가 (테스트용)
const state = useChatStore.getState()
const testMessage = {
  message_id: "test-" + Date.now(),
  conversation_id: state.currentConversationId,
  role: "user",
  content: "Test message",
  sequence_number: 999,
  status: "completed",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

state.conversations[0].messages.push(testMessage)
useChatStore.setState({ conversations: state.conversations })
```

### localStorage 확인
```javascript
// 저장된 데이터 확인
const stored = localStorage.getItem("neos-chat-storage")
console.log("Stored:", JSON.parse(stored))

// 초기화
localStorage.removeItem("neos-chat-storage")
```

---

## ✅ 성공 확인 체크리스트

메시지 전송 후 다음이 모두 확인되어야 함:

- [ ] `[Store] Message sent successfully` 로그
- [ ] `[Store] New messages count: 2` 로그
- [ ] `[Store] currentConversation getter: { found: true, messagesCount: 2 }` 로그
- [ ] `[Store] Getting messages: { messageCount: 2 }` 로그
- [ ] `[MessageList] Messages array changed: { count: 2 }` 로그
- [ ] **화면에 2개 메시지 표시** (사용자 + 봇)

---

## 🎯 예상 화면

메시지가 정상적으로 표시되면:

```
┌─────────────────────────────────────┐
│  NEOS                               │
├─────────────────────────────────────┤
│                                     │
│  👤 You                            │
│  test                              │
│                                     │
│  🤖 NEOS                           │
│  Hello! I'm here and ready to      │
│  help. How can I assist you        │
│  today?                            │
│                                     │
│  claude-sonnet  29 tokens  3.0s   │
│                                     │
│  ┌───────────────────────────┐    │
│  │ Message NEOS...      [⬆] │    │
│  └───────────────────────────┘    │
└─────────────────────────────────────┘
```

---

## 🆘 여전히 안 되면

1. **전체 로그 복사**
   - Console 전체 내용 복사
   - 특히 `[Store]`와 `[MessageList]` 로그

2. **Network 탭 확인**
   - F12 → Network 탭
   - `/api/v1/chat/` 요청 확인
   - Response 내용 확인

3. **백엔드 로그 확인**
   - 터미널에서 uvicorn 로그 확인
   - 에러 메시지 있는지 확인

4. **React DevTools 확인**
   - Components 탭
   - MessageList 컴포넌트 찾기
   - Props의 `messages` 확인

5. **마지막 수단: 완전 초기화**
   ```javascript
   // 1. localStorage 초기화
   localStorage.clear()

   // 2. 백엔드 재시작
   // Ctrl+C 후 다시 uvicorn 실행

   // 3. 프론트엔드 재시작
   // Ctrl+C 후 다시 npm run dev

   // 4. 브라우저 캐시 삭제
   // Cmd+Shift+Delete → 캐시 삭제

   // 5. 페이지 새로고침
   // F5 또는 Cmd+R
   ```

---

**작성일**: 2025-01-07
**버전**: 2.0.0-debug

**다음 테스트 후 결과를 공유해주세요!**
- 어떤 로그가 나타나는지
- 화면에 무엇이 보이는지
- 문제가 발생한 단계
