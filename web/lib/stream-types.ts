/**
 * 백엔드 SSE 스트림 이벤트 타입 정의
 */

/**
 * 스트림 이벤트 기본 타입
 */
export type StreamEvent =
  | StreamStartEvent
  | StreamContentEvent
  | StreamCompleteEvent
  | StreamErrorEvent;

/**
 * 스트리밍 시작 이벤트
 */
export interface StreamStartEvent {
  type: "start";
  message_id: string;
  conversation_id: string;
}

/**
 * 컨텐츠 델타 이벤트
 * content 필드에는 새로운 텍스트 청크만 포함 (누적 아님)
 */
export interface StreamContentEvent {
  type: "content";
  content: string;
  conversation_id: string;
}

/**
 * 스트리밍 완료 이벤트
 */
export interface StreamCompleteEvent {
  type: "complete";
  message_id: string;
  conversation_id: string;
  metadata: {
    total_tokens: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    cost_usd: number;
  };
}

/**
 * 에러 이벤트
 */
export interface StreamErrorEvent {
  type: "error";
  error: string;
  conversation_id: string;
}

/**
 * 타입 가드: 시작 이벤트 확인
 */
export function isStreamStartEvent(event: StreamEvent): event is StreamStartEvent {
  return event.type === "start";
}

/**
 * 타입 가드: 컨텐츠 이벤트 확인
 */
export function isStreamContentEvent(event: StreamEvent): event is StreamContentEvent {
  return event.type === "content";
}

/**
 * 타입 가드: 완료 이벤트 확인
 */
export function isStreamCompleteEvent(event: StreamEvent): event is StreamCompleteEvent {
  return event.type === "complete";
}

/**
 * 타입 가드: 에러 이벤트 확인
 */
export function isStreamErrorEvent(event: StreamEvent): event is StreamErrorEvent {
  return event.type === "error";
}
