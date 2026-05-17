/**
 * 백엔드 SSE 스트림 이벤트 타입 정의
 *
 * This file provides both legacy event types and OpenResponses-compliant types.
 * Use OpenResponses types for new code; legacy types are for backward compatibility.
 *
 * @see https://www.openresponses.org/specification
 */

// Re-export OpenResponses types for unified access
export type {
  // Core types
  ItemStatus,
  ResponseStatus,
  // Output items
  OutputItem,
  MessageItem,
  FunctionCallItem,
  ReasoningItem,
  // Content parts
  OutputTextPart,
  InputTextPart,
  InputFilePart,
  InputPart,
  // Response object
  OpenResponsesResponse,
  ResponseUsage,
  ResponseError,
  // Streaming events
  OpenResponsesEvent,
  StandardStreamEvent,
  NeosExtensionEvent,
  ResponseInProgressEvent,
  ResponseCompletedEvent,
  ResponseFailedEvent,
  OutputItemAddedEvent,
  OutputItemDoneEvent,
  ContentPartAddedEvent,
  ContentPartDoneEvent,
  OutputTextDeltaEvent,
  OutputTextDoneEvent,
  FunctionCallArgumentsDeltaEvent,
  FunctionCallArgumentsDoneEvent,
  // Neos extensions
  NeosArtifactMetaEvent,
  NeosArtifactDeltaEvent,
  NeosArtifactFinishEvent,
  NeosWorkflowProgressEvent,
  NeosUIFrameEvent,
  UIFramePayload,
  UIFrameComponent,
  NeosInlineVizEvent,
  InlineVisualization,
  MermaidVizData,
  ChartVizData,
  // Error types
  OpenResponsesErrorType,
  OpenResponsesErrorResponse,
} from "./open-responses-types";

// Re-export OpenResponses type guards
export {
  isResponseInProgressEvent,
  isResponseCompletedEvent,
  isResponseFailedEvent,
  isOutputItemAddedEvent,
  isOutputItemDoneEvent,
  isOutputTextDeltaEvent,
  isOutputTextDoneEvent,
  isContentPartAddedEvent,
  isContentPartDoneEvent,
  isFunctionCallArgumentsDeltaEvent,
  isFunctionCallArgumentsDoneEvent,
  isNeosArtifactMetaEvent,
  isNeosArtifactDeltaEvent,
  isNeosArtifactFinishEvent,
  isNeosWorkflowProgressEvent,
  isNeosUIFrameEvent,
  isNeosInlineVizEvent,
  isNeosInlineVizErrorEvent,
  isMessageItem,
  isFunctionCallItem,
  isReasoningItem,
} from "./open-responses-types";

// ============================================================================
// Legacy Event Types (Deprecated - use OpenResponses types for new code)
// ============================================================================

/**
 * @deprecated Use OpenResponsesEvent instead
 * Legacy stream event union type
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
  | WorkflowProgressEvent
  | UIFrameEvent;

/**
 * @deprecated Use ResponseInProgressEvent instead
 * 스트리밍 시작 이벤트
 */
export interface StreamStartEvent {
  type: "start";
  message_id: string;
  conversation_id: string;
}

/**
 * @deprecated Use OutputTextDeltaEvent instead
 * 컨텐츠 델타 이벤트
 * content 필드에는 새로운 텍스트 청크만 포함 (누적 아님)
 */
export interface StreamContentEvent {
  type: "content";
  content: string;
  conversation_id: string;
}

/**
 * @deprecated Use ResponseCompletedEvent instead
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
 * @deprecated Use ResponseFailedEvent instead
 * 에러 이벤트
 */
export interface StreamErrorEvent {
  type: "error";
  error: string;
  conversation_id: string;
}

/**
 * @deprecated Use NeosArtifactMetaEvent instead
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
 * @deprecated Use NeosArtifactDeltaEvent instead
 * 아티팩트 콘텐츠 델타 이벤트
 */
export interface ArtifactDeltaEvent {
  type: "artifact_delta";
  content: string;
  conversation_id: string;
}

/**
 * @deprecated Use NeosArtifactFinishEvent instead
 * 아티팩트 완료 이벤트
 */
export interface ArtifactFinishEvent {
  type: "artifact_finish";
  artifact_id: string;
  conversation_id: string;
}

/**
 * @deprecated Use OutputItemAddedEvent with FunctionCallItem instead
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
 * @deprecated Use OutputItemDoneEvent with FunctionCallItem instead
 * 워크플로우 노드 완료 이벤트
 */
export interface WorkflowNodeCompleteEvent {
  type: "workflow_node_complete";
  node_name: string;
  agent_name: string;
  conversation_id: string;
}

/**
 * @deprecated Use NeosWorkflowProgressEvent instead
 * 워크플로우 진행 상황 이벤트
 */
export interface WorkflowProgressEvent {
  type: "workflow_progress";
  progress_percent: number;
  message?: string;
  conversation_id: string;
}

/**
 * @deprecated Use NeosUIFrameEvent instead
 * A2UI UI frame event.
 */
export interface UIFrameEvent {
  type: "ui_frame";
  ui_frame?: Record<string, unknown>;
  data?: {
    ui_frame?: Record<string, unknown>;
  };
  conversation_id?: string;
}

// ============================================================================
// Legacy Type Guards (Deprecated - use OpenResponses type guards for new code)
// ============================================================================

/**
 * @deprecated Use isResponseInProgressEvent instead
 * 타입 가드: 시작 이벤트 확인
 */
export function isStreamStartEvent(event: StreamEvent): event is StreamStartEvent {
  return event.type === "start";
}

/**
 * @deprecated Use isOutputTextDeltaEvent instead
 * 타입 가드: 컨텐츠 이벤트 확인
 */
export function isStreamContentEvent(event: StreamEvent): event is StreamContentEvent {
  return event.type === "content";
}

/**
 * @deprecated Use isResponseCompletedEvent instead
 * 타입 가드: 완료 이벤트 확인
 */
export function isStreamCompleteEvent(event: StreamEvent): event is StreamCompleteEvent {
  return event.type === "complete";
}

/**
 * @deprecated Use isResponseFailedEvent instead
 * 타입 가드: 에러 이벤트 확인
 */
export function isStreamErrorEvent(event: StreamEvent): event is StreamErrorEvent {
  return event.type === "error";
}

/**
 * @deprecated Use isNeosArtifactMetaEvent instead
 * 타입 가드: 아티팩트 메타 이벤트 확인
 */
export function isArtifactMetaEvent(event: StreamEvent): event is ArtifactMetaEvent {
  return event.type === "artifact_meta";
}

/**
 * @deprecated Use isNeosArtifactDeltaEvent instead
 * 타입 가드: 아티팩트 델타 이벤트 확인
 */
export function isArtifactDeltaEvent(event: StreamEvent): event is ArtifactDeltaEvent {
  return event.type === "artifact_delta";
}

/**
 * @deprecated Use isNeosArtifactFinishEvent instead
 * 타입 가드: 아티팩트 완료 이벤트 확인
 */
export function isArtifactFinishEvent(event: StreamEvent): event is ArtifactFinishEvent {
  return event.type === "artifact_finish";
}

/**
 * @deprecated Use isOutputItemAddedEvent with isFunctionCallItem instead
 * 타입 가드: 워크플로우 노드 시작 이벤트 확인
 */
export function isWorkflowNodeStartEvent(event: StreamEvent): event is WorkflowNodeStartEvent {
  return event.type === "workflow_node_start";
}

/**
 * @deprecated Use isOutputItemDoneEvent with isFunctionCallItem instead
 * 타입 가드: 워크플로우 노드 완료 이벤트 확인
 */
export function isWorkflowNodeCompleteEvent(event: StreamEvent): event is WorkflowNodeCompleteEvent {
  return event.type === "workflow_node_complete";
}

/**
 * @deprecated Use isNeosWorkflowProgressEvent instead
 * 타입 가드: 워크플로우 진행 상황 이벤트 확인
 */
export function isWorkflowProgressEvent(event: StreamEvent): event is WorkflowProgressEvent {
  return event.type === "workflow_progress";
}
