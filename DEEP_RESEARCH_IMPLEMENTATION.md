# Deep Research Web Integration Implementation

## 개요

neos 워크플로우의 Deep Research 기능을 웹 인터페이스에서 사용할 수 있도록 전체 스택을 구현했습니다.

## 구현된 기능

### 1. 데이터베이스 스키마 개선 ✅

**파일:** `/db/migrations/001_add_conversation_to_deep_research.sql`

- `hyper_research_reports` 테이블에 `conversation_id`, `initial_message_id` 컬럼 추가
- 채팅 대화와 딥리서치 리포트를 연결하는 외래 키 관계 설정
- 대화별 딥리서치 조회를 위한 뷰 및 함수 추가:
  - `conversation_with_deep_research` 뷰
  - `get_conversation_deep_research_reports()` 함수
  - `create_hyper_research_report()` 함수 업데이트

**적용 방법:**
```bash
# PostgreSQL에 접속하여 마이그레이션 실행
psql -U your_user -d your_database -f db/migrations/001_add_conversation_to_deep_research.sql
```

### 2. 백엔드 API 구현 ✅

#### 2.1. Pydantic 모델
**파일:** `/neos/api/models/deep_research_models.py`

- 요청/응답 모델 정의
- SSE 이벤트 타입 및 데이터 모델
- 연구 상태, 단계, 섹션 타입 등 Enum 정의

#### 2.2. API 핸들러
**파일:** `/neos/api/handlers/deep_research_handlers.py`

**엔드포인트:**
- `POST /api/v1/deep-research/start` - 딥리서치 시작
- `GET /api/v1/deep-research/{report_id}/stream` - SSE 스트림으로 진행 상태 구독
- `GET /api/v1/deep-research/{report_id}` - 완료된 리포트 조회
- `GET /api/v1/conversations/{conversation_id}/deep-research` - 대화의 모든 딥리서치 조회

**SSE 이벤트 타입:**
- `started` - 리서치 시작
- `phase_started` - 단계 시작 (topic_confirmation, planning, data_collection, analysis, report_generation)
- `phase_completed` - 단계 완료
- `section_started` - 섹션 시작
- `section_completed` - 섹션 완료
- `section_content` - 섹션 콘텐츠 스트리밍
- `query_executed` - 검색 쿼리 실행
- `progress_update` - 진행률 업데이트
- `completed` - 리서치 완료
- `failed` - 리서치 실패

#### 2.3. 라우터 등록
**파일:** `/neos/main.py`

- Deep Research 라우터를 FastAPI 앱에 등록
- API 문서에 엔드포인트 정보 추가

### 3. 프론트엔드 구현 ✅

#### 3.1. 타입 정의
**파일:** `/web/lib/types.ts`

- `ChatMode`에 "deep_research" 추가
- `DeepResearchReport`, `DeepResearchEvent` 인터페이스 추가
- `ChatSettings`에 `deep_research_enabled` 추가

#### 3.2. API 클라이언트
**파일:** `/web/lib/api/chat-api.ts`

**메서드:**
- `startDeepResearch()` - 딥리서치 시작
- `getDeepResearchReport()` - 리포트 조회
- `listConversationDeepResearch()` - 대화의 딥리서치 목록
- `connectDeepResearchStream()` - SSE 스트림 연결

#### 3.3. UI 컴포넌트
**파일:** `/web/components/chat/ChatModeSelector.tsx`

- "Deep Research" 모드 옵션 추가
- SearchX 아이콘 사용
- "Comprehensive multi-phase research with 100+ sources" 설명

#### 3.4. 상태 관리
**파일:** `/web/lib/stores/chat-store.ts`

**기능:**
- `sendMessage()`에서 `deep_research` 모드 지원
- SSE EventSource를 통한 실시간 진행 상태 수신
- 메시지 콘텐츠 스트리밍 업데이트
- 리서치 진행률, 쿼리 실행, 섹션 생성 등 실시간 표시

## 사용 방법

### 1. 데이터베이스 마이그레이션 적용

```bash
psql -U your_user -d ai_system -f db/migrations/001_add_conversation_to_deep_research.sql
```

### 2. 백엔드 서버 실행

```bash
cd /home/user/neos
python -m neos.main
# 또는
uvicorn neos.main:app --host 0.0.0.0 --port 8518
```

### 3. 프론트엔드 실행

```bash
cd /home/user/neos/web
npm install  # 처음 한 번만
npm run dev
```

### 4. 웹에서 사용

1. 브라우저에서 `http://localhost:3000` 접속
2. 좌측 상단의 "Mode" 선택기에서 "Deep Research" 선택
3. 연구하고 싶은 주제를 입력 (예: "Quantum computing trends in 2025")
4. 실시간으로 진행 상태 확인:
   - 단계별 진행 (주제 확인 → 계획 → 데이터 수집 → 분석 → 보고서 생성)
   - 쿼리 실행 현황
   - 수집된 소스 개수
   - 진행률 퍼센티지
5. 최종 보고서가 스트리밍으로 표시됨

## 아키텍처

### 데이터 흐름

```
사용자 입력 (웹)
    ↓
ChatStore.sendMessage()
    ↓
chatAPI.startDeepResearch()
    ↓
POST /api/v1/deep-research/start
    ↓
deep_research_handlers.start_deep_research()
    ↓
Database: hyper_research_reports 생성
    ↓
SSE Stream 시작: GET /api/v1/deep-research/{report_id}/stream
    ↓
EventSource.onmessage() (웹)
    ↓
실시간 UI 업데이트
    ↓
완료 시 메시지 상태 "completed"로 변경
```

### SSE 이벤트 스트림 예시

```
data: {"event":"started","report_id":"hyper_report_xxx","data":{"message":"Deep research started"}}

data: {"event":"phase_started","report_id":"hyper_report_xxx","data":{"phase":"planning","message":"Creating research plan..."}}

data: {"event":"query_executed","report_id":"hyper_report_xxx","data":{"query":"quantum computing 2025","results_count":10}}

data: {"event":"progress_update","report_id":"hyper_report_xxx","data":{"progress_percentage":45.5,"sources_collected":50}}

data: {"event":"section_content","report_id":"hyper_report_xxx","data":{"content_chunk":"## Introduction\n\n"}}

data: {"event":"completed","report_id":"hyper_report_xxx","data":{"total_sections":5,"total_sources":150}}
```

## 기술 스택

### 백엔드
- **FastAPI** - REST API 프레임워크
- **Pydantic** - 데이터 검증 및 직렬화
- **PostgreSQL** - 관계형 데이터베이스
- **SSE (Server-Sent Events)** - 실시간 단방향 스트리밍
- **asyncpg** - 비동기 PostgreSQL 드라이버

### 프론트엔드
- **Next.js 13+** - React 프레임워크
- **TypeScript** - 타입 안전성
- **Zustand** - 상태 관리
- **EventSource API** - SSE 클라이언트
- **Tailwind CSS** - 스타일링

## 주요 특징

### 1. 실시간 진행 상태 표시
- SSE를 통한 서버→클라이언트 실시간 스트리밍
- 단계별 진행 상황 표시
- 진행률 퍼센티지 표시
- 수집된 소스 개수 실시간 업데이트

### 2. 다중 단계 리서치
- **Topic Confirmation:** 주제 분석 및 확인
- **Planning:** 리서치 계획 수립
- **Data Collection:** 100+ 소스에서 데이터 수집
- **Analysis:** 수집된 데이터 분석
- **Report Generation:** 최종 보고서 생성

### 3. 데이터베이스 통합
- 채팅 대화와 딥리서치 리포트 연결
- 사용자별, 대화별 리서치 이력 추적
- 리서치 상태, 품질 점수, 처리 시간 등 메트릭 저장

### 4. 채팅 모드 통합
- Standard, RAG, Similarity, Deep Research 4가지 모드
- 모드별 독립적인 설정 및 동작
- 단일 인터페이스에서 모드 전환 가능

## 향후 개선 사항

### 1. 실제 HyperDeepResearch 에이전트 연동
현재는 시뮬레이션된 데이터를 사용하고 있습니다. 실제 구현 시:
- `deep_research_handlers.py`의 `deep_research_stream_generator()` 함수 수정
- `HyperDeepResearch` 에이전트의 실제 메서드 호출
- 에이전트의 진행 상태를 SSE 이벤트로 변환

```python
# 예시
agent = HyperDeepResearch(user_id=user_id, session_id=session_id)

async for event in agent.run_research_stream(research_topic):
    yield f"data: {event.model_dump_json()}\n\n"
```

### 2. 리서치 취소 기능
- 진행 중인 리서치를 사용자가 중단할 수 있는 기능
- `DELETE /api/v1/deep-research/{report_id}` 엔드포인트 추가

### 3. 리서치 히스토리 UI
- 완료된 리서치 목록 표시
- 이전 리서치 결과 재조회 및 공유

### 4. 고급 설정 옵션
- 소스 개수 조정 (기본 100+)
- 품질 임계값 설정
- 특정 도메인 포함/제외

### 5. 진행 상황 시각화
- 프로그레스 바 컴포넌트
- 단계별 아이콘 및 애니메이션
- 소스 도메인 분포 차트

## 테스트

### 백엔드 API 테스트

```bash
# 딥리서치 시작
curl -X POST http://localhost:8518/api/v1/deep-research/start \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "conversation_id": "conv_123",
    "initial_message_id": "msg_456",
    "research_topic": "AI trends 2025",
    "session_id": "session_789"
  }'

# SSE 스트림 구독 (curl로는 실시간 확인)
curl -N http://localhost:8518/api/v1/deep-research/{report_id}/stream

# 리포트 조회
curl http://localhost:8518/api/v1/deep-research/{report_id}
```

### 프론트엔드 테스트

1. 웹 인터페이스에서 Deep Research 모드 선택
2. 개발자 도구 콘솔에서 로그 확인
3. 네트워크 탭에서 SSE 연결 확인
4. 실시간 메시지 업데이트 확인

## 문제 해결

### 1. CORS 오류
- `neos/main.py`에서 CORS 설정 확인
- 프론트엔드 URL이 허용 목록에 있는지 확인

### 2. SSE 연결 실패
- EventSource가 브라우저에서 지원되는지 확인
- 프록시/로드밸런서가 SSE를 차단하지 않는지 확인
- 네트워크 타임아웃 설정 확인

### 3. 데이터베이스 오류
- 마이그레이션이 올바르게 적용되었는지 확인
- 외래 키 제약 조건 확인
- 테이블 권한 확인

### 4. 실시간 업데이트 안 됨
- 브라우저 콘솔에서 EventSource 에러 확인
- 백엔드 로그에서 SSE 스트림 오류 확인
- Zustand store의 상태 업데이트 로직 확인

## 기여자

이 기능은 다음 파일들을 수정/추가했습니다:

### 데이터베이스
- `db/migrations/001_add_conversation_to_deep_research.sql` (새 파일)

### 백엔드
- `neos/api/models/deep_research_models.py` (새 파일)
- `neos/api/handlers/deep_research_handlers.py` (새 파일)
- `neos/api/deep_research_routes.py` (새 파일)
- `neos/main.py` (수정)

### 프론트엔드
- `web/lib/types.ts` (수정)
- `web/lib/api/chat-api.ts` (수정)
- `web/lib/stores/chat-store.ts` (수정)
- `web/components/chat/ChatModeSelector.tsx` (수정)

## 라이선스

이 프로젝트의 라이선스를 따릅니다.

## 참고 자료

- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [SSE (Server-Sent Events) MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [Zustand 공식 문서](https://zustand-demo.pmnd.rs/)
- [Next.js 공식 문서](https://nextjs.org/docs)
