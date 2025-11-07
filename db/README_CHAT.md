# Chat System Database Schema

Claude와 같은 AI 채팅 시스템을 위한 데이터베이스 스키마 및 API 구현

## 주요 테이블

### 1. conversations
- 사용자의 대화방 관리
- 대화 설정 (모델, temperature, system prompt)
- 통계 정보 (메시지 수, 토큰 사용량, 비용)

### 2. messages
- 대화 내 모든 메시지 저장
- 역할: user, assistant, system, function, tool
- 토큰 사용량 및 도구 호출 정보 추적

### 3. message_edits
- 메시지 편집 이력
- 버전 관리

### 4. conversation_participants
- 대화 참여자 관리
- 권한 설정 (읽기, 쓰기, 편집, 삭제, 공유)
- 읽지 않은 메시지 카운트

### 5. conversation_branches
- Alternative responses 지원
- 대화 분기 관리

### 6. chat_analytics
- 대화별 통계 및 분석
- 토큰 사용량, 비용, 품질 메트릭

### 7. conversation_templates
- 재사용 가능한 대화 템플릿
- 초기 메시지 및 설정 저장

## 자동화 기능

### 트리거
1. **auto_generate_conversation_title**: 첫 메시지 기반 자동 제목 생성
2. **set_message_sequence_number**: 메시지 순서 자동 할당
3. **update_conversation_on_message**: 대화 통계 자동 업데이트
4. **update_*_updated_at**: updated_at 자동 갱신

### 유틸리티 함수
- `create_conversation()`: 새 대화 생성
- `add_message()`: 메시지 추가
- `get_user_conversations()`: 사용자 대화 목록
- `get_conversation_messages()`: 대화 메시지 조회

## 인덱스 전략

- 대화 조회 최적화 (user_id, status, last_message_at)
- 메시지 조회 최적화 (conversation_id, sequence_number)
- 전문 검색 지원 (pg_trgm 인덱스)

## 주의사항

### JSONB 필드
다음 필드들은 JSONB 타입으로 저장됩니다:
- tags, metadata (conversations)
- tool_calls, tool_results, attachments, metadata (messages)
- default_settings, initial_messages, tags, metadata (templates)

API에서 이들을 전달할 때 JSON 문자열로 변환이 필요합니다.

### 외래 키 제약
- conversations.user_id → users.user_id (ON DELETE CASCADE)
- messages.conversation_id → conversations.conversation_id (ON DELETE CASCADE)

대화를 삭제하면 관련 메시지가 모두 삭제됩니다.

## 성능 고려사항

1. **메시지 페이지네이션**: sequence_number 기반 커서 페이지네이션 사용
2. **대화 목록 조회**: is_pinned, last_message_at 인덱스 활용
3. **분석 데이터**: chat_analytics 테이블 사전 집계 활용

## 확장 가능성

- 벡터 임베딩 추가 (메시지 유사도 검색)
- 실시간 협업 기능 (conversation_participants 활용)
- 메시지 반응/리액션 테이블 추가 가능
