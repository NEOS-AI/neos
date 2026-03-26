/**
 * Stream Adapter - Converts legacy Neos events to OpenResponses format
 *
 * This adapter layer enables gradual migration from custom SSE events
 * to the OpenResponses specification while maintaining backward compatibility.
 */

import type { StreamEvent } from "@/lib/stream-types";
import type {
  OpenResponsesEvent,
  OpenResponsesResponse,
  OutputItem,
  MessageItem,
  FunctionCallItem,
  ItemStatus,
} from "@/lib/open-responses-types";
import { generateUUID } from "@/lib/utils";

/**
 * Stream adapter state - tracks ongoing response state during conversion
 */
export interface StreamAdapterState {
  responseId: string;
  messageId: string;
  currentOutputIndex: number;
  outputItems: Map<string, OutputItem>;
  textContent: string;
  createdAt: number;
}

/**
 * Create initial adapter state
 */
export function createAdapterState(): StreamAdapterState {
  return {
    responseId: `resp_${generateUUID()}`,
    messageId: `msg_${generateUUID()}`,
    currentOutputIndex: 0,
    outputItems: new Map(),
    textContent: "",
    createdAt: Math.floor(Date.now() / 1000),
  };
}

/**
 * Build current response object from state
 */
function buildResponse(
  state: StreamAdapterState,
  status: ItemStatus
): OpenResponsesResponse {
  return {
    id: state.responseId,
    object: "response",
    created_at: state.createdAt,
    status,
    output: Array.from(state.outputItems.values()),
  };
}

/**
 * Build message item from state
 */
function buildMessageItem(state: StreamAdapterState, status: ItemStatus): MessageItem {
  return {
    type: "message",
    id: state.messageId,
    role: "assistant",
    status,
    content: [{ type: "output_text", text: state.textContent }],
  };
}

/**
 * Convert a legacy Neos event to OpenResponses event(s)
 *
 * @param event - Legacy stream event
 * @param state - Current adapter state (mutated)
 * @returns Array of OpenResponses events (may return multiple events for one input)
 */
export function adaptLegacyEvent(
  event: StreamEvent,
  state: StreamAdapterState
): OpenResponsesEvent[] {
  const events: OpenResponsesEvent[] = [];

  switch (event.type) {
    case "start": {
      // Update state with backend IDs
      state.messageId = event.message_id;

      // Create initial message item
      const messageItem = buildMessageItem(state, "in_progress");
      state.outputItems.set(state.messageId, messageItem);

      // Emit response.in_progress
      events.push({
        type: "response.in_progress",
        response: buildResponse(state, "in_progress"),
      });

      // Emit output_item.added for the message
      events.push({
        type: "response.output_item.added",
        output_index: 0,
        item: messageItem,
      });

      // Emit content_part.added
      events.push({
        type: "response.content_part.added",
        item_id: state.messageId,
        output_index: 0,
        content_index: 0,
        part: { type: "output_text", text: "" },
      });
      break;
    }

    case "content": {
      // Accumulate text content
      state.textContent += event.content;

      // Update message item in state
      const messageItem = state.outputItems.get(state.messageId) as MessageItem;
      if (messageItem && messageItem.type === "message") {
        messageItem.content[0].text = state.textContent;
      }

      // Emit text delta
      events.push({
        type: "response.output_text.delta",
        item_id: state.messageId,
        output_index: 0,
        content_index: 0,
        delta: event.content,
      });
      break;
    }

    case "complete": {
      // Finalize message ID
      state.messageId = event.message_id;

      // Update message item status
      const messageItem = state.outputItems.get(state.messageId) as MessageItem;
      if (messageItem) {
        messageItem.status = "completed";
        messageItem.id = event.message_id;
      }

      // Emit text done
      events.push({
        type: "response.output_text.done",
        item_id: state.messageId,
        output_index: 0,
        content_index: 0,
        text: state.textContent,
      });

      // Emit content_part.done
      events.push({
        type: "response.content_part.done",
        item_id: state.messageId,
        output_index: 0,
        content_index: 0,
        part: { type: "output_text", text: state.textContent },
      });

      // Emit output_item.done for message
      events.push({
        type: "response.output_item.done",
        output_index: 0,
        item: buildMessageItem(state, "completed"),
      });

      // Emit response.completed with usage
      const completedResponse = buildResponse(state, "completed");
      completedResponse.usage = {
        input_tokens: event.metadata.prompt_tokens || 0,
        output_tokens: event.metadata.completion_tokens || 0,
      };
      events.push({
        type: "response.completed",
        response: completedResponse,
      });
      break;
    }

    case "error": {
      // Emit response.failed
      const failedResponse = buildResponse(state, "failed");
      failedResponse.error = {
        message: event.error,
        type: "server_error",
        param: null,
        code: "stream_error",
      };
      events.push({
        type: "response.failed",
        response: failedResponse,
      });
      break;
    }

    case "workflow_node_start": {
      // Create function_call item
      const functionCallId = `fc_${event.node_name}`;
      const functionCallItem: FunctionCallItem = {
        type: "function_call",
        id: functionCallId,
        call_id: event.node_name,
        name: event.agent_name,
        arguments: JSON.stringify({
          progress_percent: event.progress_percent,
          workflow_step: event.workflow_step,
          total_steps: event.total_steps,
        }),
        status: "in_progress",
      };

      state.currentOutputIndex++;
      state.outputItems.set(functionCallId, functionCallItem);

      // Emit output_item.added
      events.push({
        type: "response.output_item.added",
        output_index: state.currentOutputIndex,
        item: functionCallItem,
      });
      break;
    }

    case "workflow_node_complete": {
      const functionCallId = `fc_${event.node_name}`;
      const functionCallItem = state.outputItems.get(functionCallId) as FunctionCallItem;

      if (functionCallItem) {
        functionCallItem.status = "completed";

        // Emit output_item.done
        events.push({
          type: "response.output_item.done",
          output_index: state.currentOutputIndex,
          item: functionCallItem,
        });
      }
      break;
    }

    case "workflow_progress": {
      // Convert to neos extension event
      events.push({
        type: "neos:workflow_progress",
        progress_percent: event.progress_percent,
        message: event.message,
        conversation_id: event.conversation_id,
      });
      break;
    }

    case "artifact_meta": {
      // Convert to neos extension event with provider prefix
      events.push({
        type: "neos:artifact_meta",
        artifact_id: event.artifact_id,
        artifact_title: event.artifact_title,
        artifact_kind: event.artifact_kind,
        conversation_id: event.conversation_id,
      });
      break;
    }

    case "artifact_delta": {
      // Convert to neos extension event
      events.push({
        type: "neos:artifact_delta",
        content: event.content,
        conversation_id: event.conversation_id,
      });
      break;
    }

    case "artifact_finish": {
      // Convert to neos extension event
      events.push({
        type: "neos:artifact_finish",
        artifact_id: event.artifact_id,
        conversation_id: event.conversation_id,
      });
      break;
    }

    case "ui_frame": {
      // Phase 8 (A2UI): Convert legacy ui_frame to neos:ui_frame
      events.push({
        type: "neos:ui_frame",
        ui_frame: (event as any).data?.ui_frame || (event as any).ui_frame || {},
      });
      break;
    }

    default:
      // Unknown event type - pass through as-is (for forward compatibility)
      console.warn("Unknown legacy event type:", (event as any).type);
      break;
  }

  return events;
}

/**
 * Create a stream processor that handles version-based event adaptation
 */
export function createStreamProcessor(version: "legacy" | "openresponses") {
  const state = createAdapterState();

  return {
    /**
     * Process an incoming event
     */
    process(event: StreamEvent | OpenResponsesEvent): OpenResponsesEvent[] {
      if (version === "legacy") {
        return adaptLegacyEvent(event as StreamEvent, state);
      }
      // OpenResponses version - pass through
      return [event as OpenResponsesEvent];
    },

    /**
     * Get current adapter state
     */
    getState(): StreamAdapterState {
      return state;
    },

    /**
     * Reset adapter state
     */
    reset(): void {
      Object.assign(state, createAdapterState());
    },
  };
}

/**
 * Detect event format from raw event data
 */
export function detectEventFormat(
  event: unknown
): "legacy" | "openresponses" | "unknown" {
  if (!event || typeof event !== "object") {
    return "unknown";
  }

  const eventType = (event as { type?: string }).type;
  if (!eventType) {
    return "unknown";
  }

  // OpenResponses events use dot notation (e.g., "response.output_text.delta")
  if (eventType.startsWith("response.") || eventType.includes(":")) {
    return "openresponses";
  }

  // Legacy events use simple names (e.g., "start", "content", "complete")
  const legacyTypes = [
    "start",
    "content",
    "complete",
    "error",
    "artifact_meta",
    "artifact_delta",
    "artifact_finish",
    "workflow_node_start",
    "workflow_node_complete",
    "workflow_progress",
    "ui_frame",  // Phase 8 (A2UI)
  ];

  if (legacyTypes.includes(eventType)) {
    return "legacy";
  }

  return "unknown";
}

/**
 * Format SSE line for OpenResponses specification
 * Includes both event: and data: lines as per spec
 */
export function formatSSELine(event: OpenResponsesEvent): string {
  const eventType = event.type;
  const data = JSON.stringify(event);
  return `event: ${eventType}\ndata: ${data}\n\n`;
}

/**
 * Format SSE done marker
 */
export function formatSSEDone(): string {
  return "data: [DONE]\n\n";
}
