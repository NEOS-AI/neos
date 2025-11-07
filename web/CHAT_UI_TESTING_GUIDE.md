# NEOS Chat UI - Testing Guide

## 🎯 문제 해결 완료

**이슈**: API 응답은 정상적으로 오지만 화면에 메시지가 표시되지 않음

**해결책**:
1. ✅ 디버그 로깅 추가
2. ✅ 메시지 상태 업데이트 개선
3. ✅ message_count 동기화

---

## 🧪 테스트 방법

### Step 1: 백엔드 실행
```bash
cd /Users/ywsung/Desktop/neos/neos
uvicorn neos.main:app --reload --port 8518
```

### Step 2: 프론트엔드 실행
```bash
cd /Users/ywsung/Desktop/neos/web
npm run dev
```

### Step 3: 브라우저 열기
```bash
open http://localhost:3000
```

### Step 4: 개발자 콘솔 열기
- Chrome/Edge: `F12` 또는 `Cmd+Option+I` (Mac)
- Firefox: `F12` 또는 `Cmd+Option+K` (Mac)

---

## 🔍 디버그 로그 확인

채팅 메시지를 보내면 다음과 같은 로그가 콘솔에 표시됩니다:

### 정상 흐름
```
[Store] No conversation exists, creating one...
[Store] Setting current conversation: ad98e0ce-3353-41f0-ac08-af168a3a130e
[Store] Sending message to conversation: ad98e0ce-3353-41f0-ac08-af168a3a130e
[Store] Sending standard message...
[Store] Got response: {
  userMessageId: "089d8cc3-908e-4ec1-a2a2-b1d64821d1ce",
  assistantMessageId: "60de7c2b-5437-4aa6-b879-2da92a3b922c"
}
[Store] Adding messages to store...
[Store] Updated conversations: {
  total: 1,
  current: { conversation_id: "...", messages: [...], message_count: 2 }
}
[Store] Message sent successfully
[MessageList] Messages changed: {
  count: 2,
  messages: [
    { id: "089d8cc3...", role: "user", content: "Tell me about yourself" },
    { id: "60de7c2b...", role: "assistant", content: "I'm Claude, an AI assistant..." }
  ]
}
```

### 에러 발생 시
```
[Store] Failed to send message: Error: ...
```

---

## 📋 체크리스트

### 1. 대화 생성 테스트
- [ ] "New Chat" 버튼 클릭
- [ ] 콘솔에 `[Store] Setting current conversation` 로그 확인
- [ ] 사이드바에 새 대화 표시 확인

### 2. 메시지 전송 테스트
- [ ] 입력창에 "Tell me about yourself" 입력
- [ ] Enter 키 또는 Send 버튼 클릭
- [ ] 로딩 인디케이터 표시 확인
- [ ] 콘솔에 전송 로그 확인:
  ```
  [Store] Sending message to conversation: ...
  [Store] Sending standard message...
  ```

### 3. 응답 표시 테스트
- [ ] API 응답 후 로그 확인:
  ```
  [Store] Got response: { userMessageId: "...", assistantMessageId: "..." }
  [Store] Adding messages to store...
  ```
- [ ] MessageList에서 메시지 변경 로그 확인:
  ```
  [MessageList] Messages changed: { count: 2, messages: [...] }
  ```
- [ ] **화면에 사용자 메시지와 봇 응답이 모두 표시되는지 확인**

### 4. UI 상태 테스트
- [ ] 사용자 메시지: 파란색 아바타, 오른쪽 정렬
- [ ] 봇 메시지: 주황색 "N" 아바타, 왼쪽 정렬
- [ ] 메시지에 메타데이터 표시 (토큰, 시간, 비용)
- [ ] 스크롤이 자동으로 최하단으로 이동

### 5. 채팅 모드 테스트
- [ ] Standard 모드로 메시지 전송
- [ ] RAG 모드로 전환 후 메시지 전송
- [ ] Similarity 모드로 전환 후 메시지 전송
- [ ] 각 모드별 로그 확인:
  ```
  [Store] Sending standard message...
  [Store] Sending RAG message...
  [Store] Sending similarity message...
  ```

---

## 🐛 문제 해결

### 문제 1: 메시지가 화면에 표시되지 않음

**확인 사항**:
1. 콘솔 로그 확인:
   ```javascript
   [Store] Updated conversations: { ... }
   [MessageList] Messages changed: { count: X, messages: [...] }
   ```

2. Store 상태 확인 (콘솔에서):
   ```javascript
   useChatStore.getState().conversations
   useChatStore.getState().currentConversation
   useChatStore.getState().messages
   ```

3. messages 배열이 비어있는지 확인:
   ```javascript
   console.log(useChatStore.getState().messages.length)
   ```

**해결 방법**:
- localStorage 초기화:
  ```javascript
  localStorage.clear()
  // 페이지 새로고침
  ```

- 대화 재생성:
  ```javascript
  // "New Chat" 버튼 클릭
  // 메시지 다시 전송
  ```

---

### 문제 2: API 에러

**확인 사항**:
```javascript
// 콘솔에서
[Store] Failed to send message: Error: ...
```

**가능한 원인**:
1. 백엔드가 실행되지 않음
   ```bash
   curl http://localhost:8518/api/v1/health
   ```

2. CORS 에러
   - 백엔드 CORS 설정 확인
   - `.env.local`에서 `NEXT_PUBLIC_BACKEND_URL` 확인

3. 네트워크 에러
   - Network 탭에서 요청 확인
   - 요청 URL이 정확한지 확인

---

### 문제 3: 대화가 생성되지 않음

**확인 사항**:
```javascript
[Store] Failed to create conversation
```

**해결 방법**:
1. 백엔드 로그 확인
2. 데이터베이스 연결 확인
3. user_id가 올바른지 확인

---

## 🎨 예상 동작

### 정상적인 채팅 플로우

1. **초기 화면**
   - Welcome 메시지 표시
   - "New Chat" 버튼 보임
   - 예제 프롬프트 4개 표시

2. **메시지 입력**
   - 입력창에 텍스트 입력
   - Send 버튼 활성화 (파란색)
   - Enter 키로 전송 가능

3. **메시지 전송**
   - 로딩 인디케이터 표시 (점 3개)
   - Send 버튼이 Stop 버튼으로 변경
   - 입력창 비활성화

4. **응답 수신**
   - 사용자 메시지 표시
   - 봇 응답 표시 (마크다운 렌더링)
   - 메타데이터 표시 (토큰, 시간)
   - 자동 스크롤

5. **대화 계속**
   - 입력창 다시 활성화
   - 다음 메시지 입력 가능
   - 대화 히스토리 유지

---

## 📊 네트워크 요청 확인

### 1. 대화 생성 요청
```
POST /api/v1/chat/conversations
Request:
{
  "user_id": "anonymous",
  "title": "New Chat",
  "model_name": "claude-3-5-sonnet-20241022",
  "temperature": 0.7
}

Response:
{
  "conversation_id": "ad98e0ce-3353-41f0-ac08-af168a3a130e",
  "user_id": "anonymous",
  "title": "New Chat",
  ...
}
```

### 2. 메시지 전송 요청
```
POST /api/v1/chat/conversations/{id}/messages
Request:
{
  "content": "Tell me about yourself",
  "role": "user"
}

Response:
{
  "success": true,
  "user_message": { ... },
  "assistant_message": { ... }
}
```

---

## 🔧 개발자 도구

### 콘솔에서 Store 직접 조작

```javascript
// Store 상태 확인
const state = useChatStore.getState()
console.log("Conversations:", state.conversations)
console.log("Current ID:", state.currentConversationId)
console.log("Messages:", state.messages)

// 수동으로 메시지 전송
await state.sendMessage("Hello!")

// 설정 변경
state.setChatMode("rag")
state.updateSettings({ stream: true })

// localStorage 확인
console.log(localStorage.getItem("neos-chat-storage"))

// localStorage 초기화
localStorage.removeItem("neos-chat-storage")
```

---

## ✅ 성공 확인

다음이 모두 작동하면 성공:

1. ✅ 메시지 입력 후 전송
2. ✅ 사용자 메시지가 즉시 화면에 표시
3. ✅ 로딩 인디케이터 표시
4. ✅ 봇 응답이 화면에 표시
5. ✅ 메타데이터 (토큰, 시간) 표시
6. ✅ 다음 메시지 입력 가능
7. ✅ 대화 히스토리 유지
8. ✅ 사이드바에 대화 목록 표시

---

## 📝 추가 테스트 시나리오

### 시나리오 1: 긴 대화
1. 10개 이상의 메시지 주고받기
2. 스크롤 동작 확인
3. 성능 확인 (느려지지 않는지)

### 시나리오 2: 여러 대화
1. "New Chat" 버튼으로 새 대화 생성
2. 각 대화에서 메시지 전송
3. 대화 전환 시 메시지 로드 확인

### 시나리오 3: 에러 처리
1. 백엔드 중지
2. 메시지 전송 시도
3. 에러 메시지 표시 확인

### 시나리오 4: 페이지 새로고침
1. 메시지 몇 개 전송
2. 페이지 새로고침 (F5)
3. 대화 목록 유지 확인
4. 메시지는 다시 로드됨 (localStorage에 저장 안 함)

---

## 🎉 완료!

모든 테스트가 통과하면 채팅 UI가 정상적으로 작동하는 것입니다!

**문제가 계속되면**:
1. 콘솔 로그 전체 복사
2. Network 탭 확인
3. 백엔드 로그 확인
4. 위 정보와 함께 문의

---

**마지막 업데이트**: 2025-01-07
**버전**: 2.0.0
