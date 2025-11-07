# NEOS Web - 완전한 사용 가이드

## 🚀 시작하기

### 1. 서버 실행

#### 백엔드 실행
```bash
cd /Users/ywsung/Desktop/neos/neos
uvicorn neos.main:app --reload --port 8518
```

백엔드가 정상 실행되면:
```
INFO:     Uvicorn running on http://127.0.0.1:8518
INFO:     Application startup complete.
```

#### 프론트엔드 실행 (새 터미널)
```bash
cd /Users/ywsung/Desktop/neos/web
npm run dev
```

프론트엔드가 정상 실행되면:
```
✓ Ready in 2.5s
○ Local:   http://localhost:3000
```

### 2. 브라우저 접속
```
http://localhost:3000
```

---

## 📱 사용자 인터페이스

### 화면 구성

```
┌─────────────────────────────────────────────────────┐
│  [☰] NEOS                          [Mode] [⚙️]      │ ← Header
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ [➕ New] │    Welcome to NEOS                       │
│          │    Your intelligent AI agent             │
│ 📝 Chat 1│                                          │
│ 📝 Chat 2│    [Example Prompts]                     │
│ 📝 Chat 3│                                          │
│          │                                          │
│ Sidebar  │         Main Chat Area                   │
│          │                                          │
│          │  User: Tell me about yourself            │
│          │  Bot:  I'm Claude, an AI assistant...    │
│          │                                          │
│          │  ┌────────────────────────────────┐     │
│          │  │ Message NEOS...           [⬆] │     │ ← Input
│          │  └────────────────────────────────┘     │
│          │  NEOS can make mistakes...               │
└──────────┴──────────────────────────────────────────┘
```

---

## 💬 채팅 사용법

### 1. 새 대화 시작

**방법 1: New Chat 버튼**
1. 사이드바 상단의 `➕ New Chat` 버튼 클릭
2. 새 대화가 생성되고 입력창 활성화

**방법 2: 예제 프롬프트**
1. Welcome 화면에서 예제 프롬프트 클릭
2. 자동으로 메시지 전송

**방법 3: 바로 입력**
1. 입력창에 메시지 입력
2. Enter 키 또는 Send 버튼 클릭
3. 자동으로 대화 생성

### 2. 메시지 전송

```
입력창에 메시지 입력
↓
Enter 키 또는 [⬆] 버튼 클릭
↓
로딩 표시 (점 3개)
↓
사용자 메시지 표시
↓
봇 응답 표시
```

**키보드 단축키**:
- `Enter`: 메시지 전송
- `Shift + Enter`: 줄바꿈

### 3. 대화 관리

**대화 전환**:
- 사이드바에서 다른 대화 클릭

**대화 삭제**:
1. 대화에 마우스 호버
2. 🗑️ 아이콘 클릭
3. 확인 대화상자에서 확인

**대화 아카이브**:
1. 대화에 마우스 호버
2. 📦 아이콘 클릭

---

## 🎯 3가지 채팅 모드

### Standard Mode (기본)
**사용 시기**: 일반적인 대화, 질문 답변

**특징**:
- 빠른 응답
- 컨텍스트 없음
- 간단한 질문에 최적

**사용 예시**:
```
"파이썬으로 hello world 출력하는 방법은?"
"오늘 날씨 어때?"
"이 코드 설명해줘"
```

---

### RAG Mode (검색 증강 생성)
**사용 시기**: 이전 대화 내용 참조 필요

**특징**:
- 이전 메시지 검색
- 관련 컨텍스트 자동 추가
- 일관성 있는 답변

**설정 방법**:
1. Mode 버튼에서 "RAG" 선택
2. ⚙️ 아이콘 클릭
3. RAG 설정 조정:
   - Retrieved Messages: 1-10 (검색할 메시지 수)
   - Cross-Conversation: On/Off

**사용 예시**:
```
Message 1: "파이썬 리스트 만드는 법 알려줘"
Message 2: "그럼 딕셔너리는?"
Message 3: "아까 리스트 예제 다시 보여줘"  ← RAG가 첫 메시지 참조
```

**RAG Context 확인**:
1. 봇 응답 하단의 "Show context details" 클릭
2. 검색된 메시지와 유사도 점수 확인

---

### Similarity Mode (유사도 기반)
**사용 시기**: 비슷한 주제의 이전 대화 찾기

**특징**:
- 임베딩 기반 검색
- 유사한 질문/답변 자동 검색
- 정확한 매칭 필요 없음

**설정 방법**:
1. Mode 버튼에서 "Similarity" 선택
2. ⚙️ 아이콘 클릭
3. Similarity 설정 조정:
   - Retrieved Messages: 1-10
   - Similarity Threshold: 0-1 (낮을수록 더 많이 검색)
   - Cross-Conversation: On/Off

**사용 예시**:
```
Day 1: "머신러닝 알고리즘 설명해줘"
Day 2: "딥러닝이랑 AI 차이는?"  ← Similarity가 Day 1 대화 참조
```

**Similarity Scores 확인**:
1. 봇 응답 하단의 "Show context details" 클릭
2. 유사한 메시지와 점수 확인

---

## ⚙️ 설정

### 모델 선택
```
Claude 4.5 Sonnet  ← 권장 (균형)
Claude 3 Opus      ← 최고 품질
Claude 3 Sonnet    ← 빠른 응답
Claude 3 Haiku     ← 가장 빠름
```

### Temperature (창의성 조절)
```
0.0 ──────────────────── 2.0
│                         │
정확하고 일관적        창의적이고 다양함
```

**권장 값**:
- 0.3: 코드 생성, 수학 문제
- 0.7: 일반 대화 (기본값)
- 1.2: 창의적 글쓰기, 브레인스토밍

### Streaming
```
Off: 전체 응답을 한 번에 표시
On:  단어별로 실시간 표시 (타이핑 효과)
```

---

## 🎨 메시지 기능

### 메시지 액션 (호버 시 표시)

**복사**:
- 📋 아이콘 클릭
- 메시지 내용이 클립보드에 복사

**재생성**:
- 🔄 아이콘 클릭
- 같은 질문에 새로운 답변 생성

**피드백**:
- 👍 좋아요
- 👎 싫어요

### 메시지 메타데이터

봇 응답 하단에 표시:
```
claude-sonnet  596 tokens  7.7s  ✓ 0.49¢
│              │            │     │
모델          토큰 사용량   시간  비용
```

---

## 🔍 고급 기능

### RAG Context 상세 보기

1. RAG 모드로 메시지 전송
2. 응답 하단의 "Show context details" 클릭
3. 확인 가능 정보:
   - 검색된 메시지 수
   - 평균 유사도
   - 각 메시지 내용 미리보기

예시:
```
RAG Context
─────────────────
Retrieved: 3 messages
Avg Similarity: 85%

1. [90%] "파이썬 리스트는 대괄호로..."
2. [85%] "append() 메서드로 추가..."
3. [80%] "인덱스는 0부터 시작..."
```

### Similarity Scores 상세 보기

1. Similarity 모드로 메시지 전송
2. 응답 하단의 "Show context details" 클릭
3. 확인 가능 정보:
   - 유사 메시지 수
   - 각 메시지 유사도 점수
   - 메시지 내용 미리보기

예시:
```
Similar Messages (3)
─────────────────
Score: 87%
"머신러닝은 데이터로부터 패턴을..."

Score: 82%
"지도학습과 비지도학습의 차이는..."

Score: 78%
"신경망은 인간의 뇌를 모방한..."
```

---

## 📊 사용 시나리오

### 시나리오 1: 코드 학습

```
Mode: Standard

You: 파이썬으로 리스트 만들기
Bot: [코드 예제 제공]

You: 이제 딕셔너리 만들기
Bot: [코드 예제 제공]

Mode: RAG로 전환

You: 아까 리스트 예제 다시 보여줘
Bot: [RAG Context 사용하여 첫 답변 참조]
```

### 시나리오 2: 연구 작업

```
Mode: Similarity

Day 1:
You: 양자 컴퓨팅 설명해줘
Bot: [상세 설명]

Day 2:
You: 큐비트가 뭐야?
Bot: [Similarity가 Day 1 대화 참조하여 일관된 설명]
```

### 시나리오 3: 창의적 작업

```
Settings:
- Model: Claude 3 Opus
- Temperature: 1.2
- Mode: Standard

You: 판타지 소설 아이디어 10개 brainstorm해줘
Bot: [창의적인 아이디어들]

You: 첫 번째 아이디어로 1장 써줘
Bot: [스토리 작성]
```

---

## 🐛 문제 해결

### 메시지가 표시되지 않음

1. **브라우저 콘솔 확인** (F12)
   ```
   [Store] Messages changed: { count: 0, messages: [] }
   ```
   → messages가 비어있으면 문제

2. **localStorage 초기화**
   ```javascript
   localStorage.clear()
   ```
   페이지 새로고침 (F5)

3. **새 대화 생성**
   - "New Chat" 버튼 클릭
   - 메시지 다시 전송

### 로딩이 계속됨

1. **백엔드 확인**
   ```bash
   curl http://localhost:8518/api/v1/health
   ```

2. **네트워크 탭 확인** (F12 → Network)
   - 요청이 실패했는지 확인
   - 에러 메시지 확인

3. **백엔드 재시작**
   ```bash
   # Ctrl+C로 중지
   uvicorn neos.main:app --reload --port 8518
   ```

### 응답이 느림

1. **모델 변경**
   - Settings → Model → Claude 3 Haiku

2. **Temperature 낮추기**
   - Settings → Temperature → 0.5

3. **Streaming 활성화**
   - Settings → Streaming → On

---

## 💡 팁과 트릭

### 1. 효율적인 질문
```
❌ "이거 어떻게 해?"
✅ "파이썬에서 CSV 파일을 pandas로 읽는 방법을 코드 예제와 함께 설명해줘"
```

### 2. RAG 활용
```
대화 초반에 컨텍스트 제공:
"나는 React로 웹 개발 중이야"

이후 질문:
"상태 관리 어떻게 해?" ← RAG가 React 컨텍스트 유지
```

### 3. 여러 대화 활용
```
대화 1: "파이썬 학습"
대화 2: "자바스크립트 학습"
대화 3: "프로젝트 기획"

→ 주제별로 대화 분리하면 관리 쉬움
```

### 4. 설정 프리셋
```
코드 작성: Haiku, Temp 0.3, Standard
창의적 글쓰기: Opus, Temp 1.2, Standard
연구/분석: Sonnet, Temp 0.7, RAG
```

---

## 🎯 다음 단계

1. **첫 메시지 보내기**
   ```
   "Tell me about yourself"
   ```

2. **3가지 모드 체험**
   - Standard로 질문
   - RAG로 전환 후 이전 질문 참조
   - Similarity로 관련 주제 검색

3. **설정 실험**
   - Temperature 변경해보기
   - 다양한 모델 테스트

4. **고급 기능 사용**
   - Context details 확인
   - Similarity scores 분석

---

## 📚 추가 자료

- [API 통합 가이드](./CHAT_INTEGRATION.md)
- [테스팅 가이드](./CHAT_UI_TESTING_GUIDE.md)
- [구현 분석](./IMPLEMENTATION_ANALYSIS.md)
- [빠른 시작](./QUICK_START.md)

---

**즐거운 NEOS 사용 되세요!** 🎉

**문제가 있으면**: [CHAT_UI_TESTING_GUIDE.md](./CHAT_UI_TESTING_GUIDE.md) 참조
