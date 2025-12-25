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
  | StreamErrorEvent
  | ArtifactMetaEvent
  | ArtifactDeltaEvent
  | ArtifactFinishEvent
  | WorkflowNodeStartEvent
  | WorkflowNodeCompleteEvent
  | WorkflowProgressEvent;

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
 * 아티팩트 메타데이터 이벤트
 */
export interface ArtifactMetaEvent {
  type: "artifact_meta";
  artifact_id: string;
  artifact_title: string;
  artifact_kind: "text" | "code" | "sheet" | "image";
  conversation_id: string;
}

/**
 * 아티팩트 콘텐츠 델타 이벤트
 */
export interface ArtifactDeltaEvent {
  type: "artifact_delta";
  content: string;
  conversation_id: string;
}

/**
 * 아티팩트 완료 이벤트
 */
export interface ArtifactFinishEvent {
  type: "artifact_finish";
  artifact_id: string;
  conversation_id: string;
}

/**
 * 워크플로우 노드 시작 이벤트
 */
export interface WorkflowNodeStartEvent {
  type: "workflow_node_start";
  node_name: string;
  agent_name: string;
  progress_percent?: number;
  workflow_step?: number;
  total_steps?: number;
  conversation_id: string;
}

/**
 * 워크플로우 노드 완료 이벤트
 */
export interface WorkflowNodeCompleteEvent {
  type: "workflow_node_complete";
  node_name: string;
  agent_name: string;
  conversation_id: string;
}

/**
 * 워크플로우 진행 상황 이벤트
 */
export interface WorkflowProgressEvent {
  type: "workflow_progress";
  progress_percent: number;
  message?: string;
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

/**
 * 타입 가드: 아티팩트 메타 이벤트 확인
 */
export function isArtifactMetaEvent(event: StreamEvent): event is ArtifactMetaEvent {
  return event.type === "artifact_meta";
}

/**
 * 타입 가드: 아티팩트 델타 이벤트 확인
 */
export function isArtifactDeltaEvent(event: StreamEvent): event is ArtifactDeltaEvent {
  return event.type === "artifact_delta";
}

/**
 * 타입 가드: 아티팩트 완료 이벤트 확인
 */
export function isArtifactFinishEvent(event: StreamEvent): event is ArtifactFinishEvent {
  return event.type === "artifact_finish";
}

/**
 * 타입 가드: 워크플로우 노드 시작 이벤트 확인
 */
export function isWorkflowNodeStartEvent(event: StreamEvent): event is WorkflowNodeStartEvent {
  return event.type === "workflow_node_start";
}

/**
 * 타입 가드: 워크플로우 노드 완료 이벤트 확인
 */
export function isWorkflowNodeCompleteEvent(event: StreamEvent): event is WorkflowNodeCompleteEvent {
  return event.type === "workflow_node_complete";
}

/**
 * 타입 가드: 워크플로우 진행 상황 이벤트 확인
 */
export function isWorkflowProgressEvent(event: StreamEvent): event is WorkflowProgressEvent {
  return event.type === "workflow_progress";
}
