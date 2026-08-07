import type { InferUITool, UIMessage } from "ai";
import { z } from "zod";
import type { ArtifactKind } from "@/components/artifact";
import type { createDocument } from "./ai/tools/create-document";
import type { getWeather } from "./ai/tools/get-weather";
import type { requestSuggestions } from "./ai/tools/request-suggestions";
import type { updateDocument } from "./ai/tools/update-document";
import type { Suggestion } from "./db/schema";
import type {
  ApprovalRequest,
  ItemStatus,
  UIFramePayload,
  InlineVisualization,
} from "./open-responses-types";

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

export const harnessMetadataSchema = z.object({
  status: z.string(),
  mode: z.string().optional(),
  verdict: z.string().optional(),
  score: z.number().optional(),
  failed_checks: z.array(z.string()).optional(),
  checks: z
    .array(
      z.object({
        check: z.string(),
        status: z.string().optional(),
        passed: z.boolean().optional(),
        score: z.number().optional(),
        severity: z.string().optional(),
      })
    )
    .optional(),
  repair_attempts: z.number().optional(),
  repair_actions: z.array(z.record(z.unknown())).optional(),
});

export type HarnessMetadata = z.infer<typeof harnessMetadataSchema>;

/**
 * 비동기 deep_analysis job 핸들.
 *
 * 챗 턴은 `neos:deep_analysis_started`를 보내고 **즉시 끝난다**. 진행 상황은
 * 이 `run_id`로 여는 별도 스트림(`/api/deep-analysis/{run_id}/events`)에서 온다.
 * 메시지 메타데이터에 붙여 두는 이유는 새로고침 후에도 어떤 메시지가 어떤
 * run에 속하는지 복원하기 위해서다(감사 §6 차단요인 2).
 */
export const deepAnalysisDegradationSchema = z.object({
  kind: z.string(),
  count: z.number(),
});

export const deepAnalysisMetadataSchema = z.object({
  run_id: z.string(),
  events_url: z.string().optional(),
  status: z.enum(["pending", "running", "completed", "failed"]).optional(),
  /**
   * 리포트 품질을 깎은 사건들. 백엔드가 run 종료 시 원장에서 집계해 메시지
   * 메타데이터에 실은 값이며(`deep_analysis_job_task.py`), 새로고침 후에는
   * **이것이 유일한 출처**다 — 종결된 run 은 다시 구독하지 않으므로 라이브
   * 리듀서의 상태가 남지 않는다.
   */
  degradations: z.array(deepAnalysisDegradationSchema).optional(),
});

export type DeepAnalysisMetadata = z.infer<typeof deepAnalysisMetadataSchema>;

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
  // Execution approval requests emitted by checkpointer-backed workflows.
  approval_requests: z.custom<ApprovalRequest[]>().optional(),
  approval_session_id: z.string().optional(),
  // Runtime research harness validation and repair progress.
  harness: harnessMetadataSchema.optional(),
  // 비동기 deep_analysis job 핸들 (챗 턴은 제출만 하고 즉시 끝난다).
  deep_analysis: deepAnalysisMetadataSchema.optional(),
  // Phase 8 (A2UI): UIFrame payload for form rendering
  ui_frame: z.custom<UIFramePayload>().optional(),
  // Inline Visualization: renderDiagram / renderChart 결과 (복수 지원)
  inline_visualizations: z.array(
    z.discriminatedUnion("viz_type", [
      z.object({
        id: z.string(),
        viz_type: z.literal("mermaid"),
        data: z.object({
          title: z.string(),
          mermaidCode: z.string(),
          description: z.string().optional(),
        }),
      }),
      z.object({
        id: z.string(),
        viz_type: z.literal("chart"),
        data: z.object({
          title: z.string(),
          type: z.enum(["bar", "line", "pie"]),
          data: z.array(z.object({ label: z.string(), value: z.number() })),
        }),
      }),
    ])
  ).optional(),
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

export type AutonomyLevel = 0 | 1 | 2;

export type AutonomyIcon = "lock" | "sparkles" | "cpu";

export interface AutonomyConfig {
  level: AutonomyLevel;
  label: string;
  description: string;
  icon: AutonomyIcon;
}

export const AUTONOMY_CONFIGS: AutonomyConfig[] = [
  {
    level: 0,
    label: "Manual",
    description: "Ask before agent actions",
    icon: "lock",
  },
  {
    level: 1,
    label: "Assisted",
    description: "Ask for sensitive actions",
    icon: "sparkles",
  },
  {
    level: 2,
    label: "Autonomous",
    description: "Run agent actions without prompts",
    icon: "cpu",
  },
];
