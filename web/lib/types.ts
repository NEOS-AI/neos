import type { InferUITool, UIMessage } from "ai";
import { z } from "zod";
import type { ArtifactKind } from "@/components/artifact";
import type { createDocument } from "./ai/tools/create-document";
import type { getWeather } from "./ai/tools/get-weather";
import type { requestSuggestions } from "./ai/tools/request-suggestions";
import type { updateDocument } from "./ai/tools/update-document";
import type { Suggestion } from "./db/schema";
import type { ItemStatus, UIFramePayload } from "./open-responses-types";

export type DataPart = { type: "append-message"; message: string };

/**
 * OpenResponses-compliant function call status
 */
export const functionCallStatusSchema = z.enum([
  "in_progress",
  "completed",
  "incomplete",
  "failed",
]);

/**
 * Function call item schema (OpenResponses spec)
 */
export const functionCallItemSchema = z.object({
  id: z.string(),
  call_id: z.string(),
  name: z.string(),
  arguments: z.string().optional(),
  status: functionCallStatusSchema,
});

export type FunctionCallItemData = z.infer<typeof functionCallItemSchema>;

/**
 * Message metadata schema with OpenResponses fields
 */
export const messageMetadataSchema = z.object({
  createdAt: z.string(),
  // OpenResponses: response-level status
  responseStatus: z
    .enum(["in_progress", "completed", "incomplete", "failed"])
    .optional(),
  // OpenResponses: response ID
  responseId: z.string().optional(),
  // Artifact information
  artifact: z
    .object({
      id: z.string(),
      title: z.string(),
      kind: z.custom<ArtifactKind>(),
      status: z.enum(["in_progress", "completed"]).optional(),
    })
    .optional(),
  // OpenResponses: function_call items
  function_calls: z.array(functionCallItemSchema).optional(),
  // Legacy: workflow_agents (deprecated, use function_calls)
  workflow_agents: z
    .array(
      z.object({
        agent_name: z.string(),
        node_name: z.string(),
        status: z.string(),
      })
    )
    .optional(),
  // Phase 8 (A2UI): UIFrame payload for form rendering
  ui_frame: z.custom<UIFramePayload>().optional(),
});

export type MessageMetadata = z.infer<typeof messageMetadataSchema>;

type weatherTool = InferUITool<typeof getWeather>;
type createDocumentTool = InferUITool<ReturnType<typeof createDocument>>;
type updateDocumentTool = InferUITool<ReturnType<typeof updateDocument>>;
type requestSuggestionsTool = InferUITool<
  ReturnType<typeof requestSuggestions>
>;

export type ChatTools = {
  getWeather: weatherTool;
  createDocument: createDocumentTool;
  updateDocument: updateDocumentTool;
  requestSuggestions: requestSuggestionsTool;
};

export type CustomUIDataTypes = {
  textDelta: string;
  imageDelta: string;
  sheetDelta: string;
  codeDelta: string;
  suggestion: Suggestion;
  appendMessage: string;
  id: string;
  title: string;
  kind: ArtifactKind;
  clear: null;
  finish: null;
  "chat-title": string;
};

export type ChatMessage = UIMessage<
  MessageMetadata,
  CustomUIDataTypes,
  ChatTools
>;

export type Attachment = {
  name: string;
  url: string;
  contentType: string;
};
