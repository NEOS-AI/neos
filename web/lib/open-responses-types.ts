/**
 * OpenResponses Specification Type Definitions
 * @see https://www.openresponses.org/specification
 */

// ============================================================================
// Core Types
// ============================================================================

/**
 * Item status - all items have explicit status field
 */
export type ItemStatus = "in_progress" | "completed" | "incomplete" | "failed";

/**
 * Response status
 */
export type ResponseStatus = ItemStatus;

// ============================================================================
// Output Item Types
// ============================================================================

/**
 * Base output item interface
 */
export interface BaseOutputItem {
  type: string;
  id: string;
  status: ItemStatus;
}

/**
 * Message item - text content response
 */
export interface MessageItem extends BaseOutputItem {
  type: "message";
  role: "assistant";
  content: OutputTextPart[];
}

/**
 * Function call item - tool/function invocation
 */
export interface FunctionCallItem extends BaseOutputItem {
  type: "function_call";
  call_id: string;
  name: string;
  arguments: string; // JSON string
}

/**
 * Reasoning item - model's thought process
 */
export interface ReasoningItem extends BaseOutputItem {
  type: "reasoning";
  content?: string;
  encrypted_content?: string;
  summary?: string;
}

/**
 * Union of all standard output items
 */
export type OutputItem = MessageItem | FunctionCallItem | ReasoningItem;

// ============================================================================
// Content Part Types
// ============================================================================

/**
 * Output text content part
 */
export interface OutputTextPart {
  type: "output_text";
  text: string;
}

/**
 * Input text content part
 */
export interface InputTextPart {
  type: "input_text";
  text: string;
}

/**
 * Input file content part
 */
export interface InputFilePart {
  type: "input_file";
  file: {
    url: string;
    media_type: string;
    name: string;
  };
}

/**
 * Union of input content parts
 */
export type InputPart = InputTextPart | InputFilePart;

// ============================================================================
// Response Object
// ============================================================================

/**
 * Usage statistics
 */
export interface ResponseUsage {
  input_tokens: number;
  output_tokens: number;
}

/**
 * Error information
 */
export interface ResponseError {
  message: string;
  type: string;
  param?: string | null;
  code?: string;
}

/**
 * OpenResponses Response object
 */
export interface OpenResponsesResponse {
  id: string;
  object: "response";
  created_at: number;
  status: ResponseStatus;
  output: OutputItem[];
  usage?: ResponseUsage;
  error?: ResponseError;
}

// ============================================================================
// Streaming Event Types
// ============================================================================

/**
 * Response state events
 */
export interface ResponseInProgressEvent {
  type: "response.in_progress";
  response: OpenResponsesResponse;
}

export interface ResponseCompletedEvent {
  type: "response.completed";
  response: OpenResponsesResponse;
}

export interface ResponseFailedEvent {
  type: "response.failed";
  response: OpenResponsesResponse;
}

export interface ResponseIncompleteEvent {
  type: "response.incomplete";
  response: OpenResponsesResponse;
}

/**
 * Output item events
 */
export interface OutputItemAddedEvent {
  type: "response.output_item.added";
  output_index: number;
  item: OutputItem;
}

export interface OutputItemDoneEvent {
  type: "response.output_item.done";
  output_index: number;
  item: OutputItem;
}

/**
 * Content part events
 */
export interface ContentPartAddedEvent {
  type: "response.content_part.added";
  item_id: string;
  output_index: number;
  content_index: number;
  part: OutputTextPart;
}

export interface ContentPartDoneEvent {
  type: "response.content_part.done";
  item_id: string;
  output_index: number;
  content_index: number;
  part: OutputTextPart;
}

/**
 * Text streaming events
 */
export interface OutputTextDeltaEvent {
  type: "response.output_text.delta";
  item_id: string;
  output_index: number;
  content_index: number;
  delta: string;
}

export interface OutputTextDoneEvent {
  type: "response.output_text.done";
  item_id: string;
  output_index: number;
  content_index: number;
  text: string;
}

/**
 * Reasoning streaming events (thinking/chain-of-thought)
 */
export interface ReasoningContentDeltaEvent {
  type: "response.reasoning.delta";
  item_id: string;
  output_index: number;
  delta: string;
}

export interface ReasoningContentDoneEvent {
  type: "response.reasoning.done";
  item_id: string;
  output_index: number;
  text: string;
}

export interface ReasoningSummaryDeltaEvent {
  type: "response.reasoning_summary.delta";
  item_id: string;
  output_index: number;
  delta: string;
}

export interface ReasoningSummaryDoneEvent {
  type: "response.reasoning_summary.done";
  item_id: string;
  output_index: number;
  text: string;
}

/**
 * Function call events
 */
export interface FunctionCallArgumentsDeltaEvent {
  type: "response.function_call_arguments.delta";
  item_id: string;
  output_index: number;
  call_id: string;
  delta: string;
}

export interface FunctionCallArgumentsDoneEvent {
  type: "response.function_call_arguments.done";
  item_id: string;
  output_index: number;
  call_id: string;
  arguments: string;
}

// ============================================================================
// Neos Extension Types (provider prefix: neos:)
// ============================================================================

/**
 * Neos artifact metadata event
 */
export interface NeosArtifactMetaEvent {
  type: "neos:artifact_meta";
  artifact_id: string;
  artifact_title: string;
  artifact_kind: "text" | "code" | "sheet" | "image";
  conversation_id: string;
}

/**
 * Neos artifact content delta event
 */
export interface NeosArtifactDeltaEvent {
  type: "neos:artifact_delta";
  content: string;
  conversation_id: string;
}

/**
 * Neos artifact finish event
 */
export interface NeosArtifactFinishEvent {
  type: "neos:artifact_finish";
  artifact_id: string;
  conversation_id: string;
}

/**
 * Neos workflow progress event
 */
export interface NeosWorkflowProgressEvent {
  type: "neos:workflow_progress";
  progress_percent: number;
  message?: string;
  conversation_id: string;
}

// ============================================================================
// Neos A2UI (Phase 8) Types
// ============================================================================

/**
 * UIFrame component definition
 */
export interface UIFrameComponent {
  id: string;
  type:
    | "text_field"
    | "date_picker"
    | "time_picker"
    | "select"
    | "multi_select"
    | "slider"
    | "checkbox"
    | "file_upload"
    | "card"
    | "chart"
    | "table"
    | "progress"
    | "divider"
    | "button"
    | "form";
  label?: string;
  placeholder?: string;
  required?: boolean;
  options?: Array<{ label: string; value: string } | string>;
  min?: number;
  max?: number;
  step?: number;
  default_value?: unknown;
  metadata?: Record<string, unknown>;
}

/**
 * UIFrame payload from the backend
 */
export interface UIFramePayload {
  frame_id: string;
  intent: string;
  components: UIFrameComponent[];
  session_id?: string;
  conversation_id?: string;
  timeout_seconds?: number;
}

/**
 * Neos A2UI UIFrame event — Phase 8
 */
export interface NeosUIFrameEvent {
  type: "neos:ui_frame";
  ui_frame: UIFramePayload;
}

// ============================================================================
// Neos Inline Visualization Types (renderDiagram / renderChart)
// ============================================================================

export interface MermaidVizData {
  title: string;
  mermaidCode: string;
  description: string;
}

export interface ChartVizData {
  title: string;
  type: "bar" | "line" | "pie";
  data: Array<{ label: string; value: number }>;
}

export interface InlineVisualization {
  id: string;
  viz_type: "mermaid" | "chart";
  data: MermaidVizData | ChartVizData;
}

export interface NeosInlineVizEvent {
  type: "neos:inline_viz";
  viz_id: string;
  viz_type: "mermaid" | "chart";
  data: MermaidVizData | ChartVizData;
}

// ============================================================================
// Union of All Events
// ============================================================================

/**
 * Standard OpenResponses events
 */
export type StandardStreamEvent =
  | ResponseInProgressEvent
  | ResponseCompletedEvent
  | ResponseFailedEvent
  | ResponseIncompleteEvent
  | OutputItemAddedEvent
  | OutputItemDoneEvent
  | ContentPartAddedEvent
  | ContentPartDoneEvent
  | OutputTextDeltaEvent
  | OutputTextDoneEvent
  | ReasoningContentDeltaEvent
  | ReasoningContentDoneEvent
  | ReasoningSummaryDeltaEvent
  | ReasoningSummaryDoneEvent
  | FunctionCallArgumentsDeltaEvent
  | FunctionCallArgumentsDoneEvent;

/**
 * Neos extension events
 */
export type NeosExtensionEvent =
  | NeosArtifactMetaEvent
  | NeosArtifactDeltaEvent
  | NeosArtifactFinishEvent
  | NeosWorkflowProgressEvent
  | NeosUIFrameEvent
  | NeosInlineVizEvent;

/**
 * All OpenResponses events (standard + neos extensions)
 */
export type OpenResponsesEvent = StandardStreamEvent | NeosExtensionEvent;

// ============================================================================
// Type Guards
// ============================================================================

export function isResponseInProgressEvent(
  event: OpenResponsesEvent
): event is ResponseInProgressEvent {
  return event.type === "response.in_progress";
}

export function isResponseCompletedEvent(
  event: OpenResponsesEvent
): event is ResponseCompletedEvent {
  return event.type === "response.completed";
}

export function isResponseFailedEvent(
  event: OpenResponsesEvent
): event is ResponseFailedEvent {
  return event.type === "response.failed";
}

export function isOutputItemAddedEvent(
  event: OpenResponsesEvent
): event is OutputItemAddedEvent {
  return event.type === "response.output_item.added";
}

export function isOutputItemDoneEvent(
  event: OpenResponsesEvent
): event is OutputItemDoneEvent {
  return event.type === "response.output_item.done";
}

export function isOutputTextDeltaEvent(
  event: OpenResponsesEvent
): event is OutputTextDeltaEvent {
  return event.type === "response.output_text.delta";
}

export function isOutputTextDoneEvent(
  event: OpenResponsesEvent
): event is OutputTextDoneEvent {
  return event.type === "response.output_text.done";
}

export function isContentPartAddedEvent(
  event: OpenResponsesEvent
): event is ContentPartAddedEvent {
  return event.type === "response.content_part.added";
}

export function isContentPartDoneEvent(
  event: OpenResponsesEvent
): event is ContentPartDoneEvent {
  return event.type === "response.content_part.done";
}

export function isReasoningContentDeltaEvent(
  event: OpenResponsesEvent
): event is ReasoningContentDeltaEvent {
  return event.type === "response.reasoning.delta";
}

export function isReasoningContentDoneEvent(
  event: OpenResponsesEvent
): event is ReasoningContentDoneEvent {
  return event.type === "response.reasoning.done";
}

export function isReasoningSummaryDeltaEvent(
  event: OpenResponsesEvent
): event is ReasoningSummaryDeltaEvent {
  return event.type === "response.reasoning_summary.delta";
}

export function isReasoningSummaryDoneEvent(
  event: OpenResponsesEvent
): event is ReasoningSummaryDoneEvent {
  return event.type === "response.reasoning_summary.done";
}

export function isFunctionCallArgumentsDeltaEvent(
  event: OpenResponsesEvent
): event is FunctionCallArgumentsDeltaEvent {
  return event.type === "response.function_call_arguments.delta";
}

export function isFunctionCallArgumentsDoneEvent(
  event: OpenResponsesEvent
): event is FunctionCallArgumentsDoneEvent {
  return event.type === "response.function_call_arguments.done";
}

// Neos extension type guards
export function isNeosArtifactMetaEvent(
  event: OpenResponsesEvent
): event is NeosArtifactMetaEvent {
  return event.type === "neos:artifact_meta";
}

export function isNeosArtifactDeltaEvent(
  event: OpenResponsesEvent
): event is NeosArtifactDeltaEvent {
  return event.type === "neos:artifact_delta";
}

export function isNeosArtifactFinishEvent(
  event: OpenResponsesEvent
): event is NeosArtifactFinishEvent {
  return event.type === "neos:artifact_finish";
}

export function isNeosWorkflowProgressEvent(
  event: OpenResponsesEvent
): event is NeosWorkflowProgressEvent {
  return event.type === "neos:workflow_progress";
}

export function isNeosUIFrameEvent(
  event: OpenResponsesEvent
): event is NeosUIFrameEvent {
  return event.type === "neos:ui_frame";
}

export function isNeosInlineVizEvent(
  event: OpenResponsesEvent
): event is NeosInlineVizEvent {
  return event.type === "neos:inline_viz";
}

// Output item type guards
export function isMessageItem(item: OutputItem): item is MessageItem {
  return item.type === "message";
}

export function isFunctionCallItem(item: OutputItem): item is FunctionCallItem {
  return item.type === "function_call";
}

export function isReasoningItem(item: OutputItem): item is ReasoningItem {
  return item.type === "reasoning";
}

// ============================================================================
// Error Type Mapping
// ============================================================================

/**
 * OpenResponses error types
 */
export type OpenResponsesErrorType =
  | "invalid_request"
  | "not_found"
  | "server_error"
  | "model_error"
  | "too_many_requests";

/**
 * OpenResponses error response structure
 */
export interface OpenResponsesErrorResponse {
  error: {
    message: string;
    type: OpenResponsesErrorType;
    param: string | null;
    code: string;
  };
}

// ============================================================================
// Tool Definition Types
// ============================================================================

/**
 * JSON Schema property for tool parameters
 */
export interface JsonSchemaProperty {
  type: string;
  description?: string;
  enum?: string[];
  items?: JsonSchemaProperty;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  default?: unknown;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
}

/**
 * OpenResponses tool parameter schema (JSON Schema format)
 */
export interface OpenResponsesToolParameters {
  type: "object";
  properties: Record<string, JsonSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

/**
 * OpenResponses function tool definition
 * @see https://www.openresponses.org/specification#tools
 */
export interface OpenResponsesFunctionTool {
  type: "function";
  name: string;
  description: string;
  parameters: OpenResponsesToolParameters;
  strict?: boolean;
}

/**
 * OpenResponses tool definition (union type for future extensibility)
 */
export type OpenResponsesToolDefinition = OpenResponsesFunctionTool;

/**
 * OpenResponses tool collection
 */
export interface OpenResponsesToolCollection {
  tools: OpenResponsesToolDefinition[];
}

/**
 * Tool choice options for API requests
 */
export type OpenResponsesToolChoice =
  | "auto"
  | "none"
  | "required"
  | { type: "function"; name: string };
