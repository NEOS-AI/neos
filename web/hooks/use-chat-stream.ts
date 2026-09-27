/**
 * SSE 기반 커스텀 채팅 스트리밍 훅
 * Vercel AI SDK의 useChat을 대체하여 백엔드 SSE를 직접 처리
 *
 * Supports both legacy Neos events and OpenResponses specification events.
 * @see https://www.openresponses.org/specification
 */

import type { ChatStatus } from "ai";
import { useCallback, useEffect, useRef, useState } from "react";
import type { VisibilityType } from "@/components/visibility-selector";
import {
  createStreamProcessor,
  detectEventFormat,
} from "@/lib/adapters/stream-adapter";
import type { ChatModel } from "@/lib/ai/models";
import {
  type ActiveDeepAnalysisRun,
  readActiveRun,
  rememberActiveRun,
} from "@/lib/deep-analysis/active-run-store";
import { parseDeepAnalysisStarted } from "@/lib/deep-analysis/events";
import {
  applyReasoningDelta,
  applyReasoningDone,
  textPartOf,
} from "@/lib/reasoning-parts";
import { isAbortError } from "@/lib/stream-errors";
import type { MessageItem, OpenResponsesEvent } from "@/lib/stream-types";
import {
  // OpenResponses type guards
  isFunctionCallItem,
  isNeosApprovalRequestEvent,
  isNeosArtifactDeltaEvent,
  isNeosArtifactFinishEvent,
  isNeosArtifactMetaEvent,
  isNeosDeepAnalysisStartedEvent,
  isNeosGraphSubagentEvent,
  isNeosHarnessEvent,
  isNeosInlineVizErrorEvent,
  isNeosInlineVizEvent,
  isNeosUIFrameEvent,
  isNeosWorkflowProgressEvent,
  isOutputItemAddedEvent,
  isOutputItemDoneEvent,
  isOutputTextDeltaEvent,
  isReasoningContentDeltaEvent,
  isReasoningContentDoneEvent,
  isResponseCompletedEvent,
  isResponseFailedEvent,
  isResponseInProgressEvent,
} from "@/lib/stream-types";
import type { AutonomyLevel, ChatMessage, HarnessMetadata } from "@/lib/types";
import { messageMetadataSchema } from "@/lib/types";
import { generateUUID } from "@/lib/utils";
import { applyGraphSubagentEvent } from "@/lib/workflow-agents";

// messageMetadataSchema에서 개별 inline_viz 항목 스키마 추출 (SSE 검증 재사용)
const inlineVizEntrySchema = messageMetadataSchema.shape.inline_visualizations.unwrap().element;

const asString = (value: unknown) =>
  typeof value === "string" ? value : undefined;

const asNumber = (value: unknown) =>
  typeof value === "number" ? value : undefined;

const asStringArray = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;

const terminalHarnessStatus = (verdict: string | undefined) => {
  if (verdict === "pass" || verdict === "advisory_pass") {
    return "passed";
  }
  return "failed";
};

const applyHarnessEvent = (
  current: HarnessMetadata | undefined,
  eventName: string,
  data: Record<string, unknown>
): HarnessMetadata => {
  const harness: HarnessMetadata = {
    status: current?.status ?? "validating",
    failed_checks: current?.failed_checks ?? [],
    checks: current?.checks ?? [],
    repair_attempts: current?.repair_attempts ?? 0,
    repair_actions: current?.repair_actions ?? [],
    ...current,
  };

  if (eventName === "harness_started") {
    return {
      ...harness,
      status: "validating",
      mode: asString(data.mode) ?? harness.mode,
    };
  }

  if (eventName === "harness_check_started") {
    const check = asString(data.check);
    if (!check) {
      return harness;
    }
    return {
      ...harness,
      checks: [
        ...(harness.checks ?? []).filter((item) => item.check !== check),
        { check, status: "running" },
      ],
    };
  }

  if (eventName === "harness_check_completed") {
    const check = asString(data.check);
    if (!check) {
      return harness;
    }
    return {
      ...harness,
      checks: [
        ...(harness.checks ?? []).filter((item) => item.check !== check),
        {
          check,
          status: "completed",
          passed: typeof data.passed === "boolean" ? data.passed : undefined,
          score: asNumber(data.score),
          severity: asString(data.severity),
        },
      ],
    };
  }

  if (eventName === "harness_repair_started") {
    return {
      ...harness,
      status: "repairing",
      repair_attempts:
        asNumber(data.attempt) ?? (harness.repair_attempts ?? 0) + 1,
    };
  }

  if (eventName === "harness_repair_completed") {
    const actions = [
      ...((data.executed_actions as Record<string, unknown>[] | undefined) ?? []),
      ...((data.skipped_actions as Record<string, unknown>[] | undefined) ?? []),
    ];
    return {
      ...harness,
      status: "validating",
      repair_actions: [...(harness.repair_actions ?? []), ...actions],
    };
  }

  if (eventName === "harness_completed" || eventName === "harness_failed") {
    const verdict = asString(data.verdict) ?? harness.verdict;
    return {
      ...harness,
      status:
        eventName === "harness_failed" ? "failed" : terminalHarnessStatus(verdict),
      mode: asString(data.mode) ?? harness.mode,
      verdict,
      score: asNumber(data.score) ?? harness.score,
      failed_checks: asStringArray(data.failed_checks) ?? harness.failed_checks,
      repair_attempts: asNumber(data.repair_attempts) ?? harness.repair_attempts,
    };
  }

  return harness;
};

export interface ChatRequestOptions {
  // Vercel AI SDK와 호환되는 옵션
  [key: string]: any;
}

export interface UseChatStreamOptions {
  id: string;
  initialMessages: ChatMessage[];
  selectedChatModel: ChatModel["id"];
  selectedVisibilityType: VisibilityType;
  autonomyLevel?: AutonomyLevel;
  onFinish?: () => void;
  onError?: (error: Error) => void;
  onData?: (data: any) => void;
}

export interface UseChatStreamReturn {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  sendMessage: (message?: any, options?: ChatRequestOptions) => Promise<void>;
  status: ChatStatus;
  stop: () => Promise<void>;
  regenerate: (options?: { messageId?: string } & ChatRequestOptions) => Promise<void>;
  resumeStream: (options?: ChatRequestOptions) => Promise<void>;
}

export function useChatStream({
  id,
  initialMessages,
  selectedChatModel,
  selectedVisibilityType,
  autonomyLevel,
  onFinish,
  onError,
  onData,
}: UseChatStreamOptions): UseChatStreamReturn {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [status, setStatus] = useState<ChatStatus>("ready");
  const abortControllerRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const currentAssistantMessageRef = useRef<ChatMessage | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Cancel reader if exists
      if (readerRef.current) {
        readerRef.current.cancel().catch(() => {});
        readerRef.current = null;
      }
      // Abort controller if exists
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  /**
   * 새로고침 후 진행 중인 deep_analysis run에 **다시 붙는다**.
   *
   * 감사 §4.2의 사고 재발 방지가 이 효과의 설계 제약이다: 여기서 하는 일은
   * 메시지에 run_id 메타데이터를 되붙이는 것뿐이고, 실제 재접속은
   * `DeepAnalysisStatus`가 커서를 든 **GET 재구독**으로 수행한다.
   * `sendMessage`도 `POST /api/chat`도 호출하지 않는다 — 재실행은 없다.
   *
   * 이미 어떤 메시지가 같은 run을 물고 있으면(백엔드가 메타데이터를
   * 영속화한 경우) 아무것도 하지 않는다.
   */
  useEffect(() => {
    const active: ActiveDeepAnalysisRun | null = readActiveRun(id);
    if (!active) {
      return;
    }

    setMessages((prev) => {
      const alreadyAttached = prev.some(
        (message) => message.metadata?.deep_analysis?.run_id === active.runId
      );
      if (alreadyAttached) {
        return prev;
      }

      const target = [...prev]
        .reverse()
        .find(
          (message) =>
            message.role === "assistant" && !message.metadata?.deep_analysis
        );

      const deepAnalysis = {
        run_id: active.runId,
        status: "running" as const,
      };

      if (target) {
        return prev.map((message) =>
          message.id === target.id
            ? {
                ...message,
                metadata: {
                  createdAt:
                    message.metadata?.createdAt ?? new Date().toISOString(),
                  ...message.metadata,
                  deep_analysis: deepAnalysis,
                },
              }
            : message
        );
      }

      // 어시스턴트 메시지가 아직 저장되지 않은 채 새로고침된 경우:
      // 진행 표시를 걸 자리를 하나 만든다.
      return [
        ...prev,
        {
          id: active.assistantMessageId ?? generateUUID(),
          role: "assistant",
          parts: [{ type: "text", text: "" }],
          metadata: {
            createdAt: new Date().toISOString(),
            responseStatus: "in_progress" as const,
            deep_analysis: deepAnalysis,
          },
        } satisfies ChatMessage,
      ];
    });
  }, [id]);

  /**
   * SSE 스트림 처리 (OpenResponses 스펙 준수)
   * Supports both legacy events and OpenResponses events via adapter
   */
  const processStream = useCallback(
    async (response: Response) => {
      if (!response.body) {
        throw new Error("No response body");
      }

      const reader = response.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      // 현재 아티팩트 kind 추적
      let currentArtifactKind: "text" | "code" | "sheet" | "image" | null = null;

      // Stream processor for event format detection and adaptation
      const streamProcessor = createStreamProcessor("legacy");

      // 어시스턴트 메시지 초기화
      const assistantMessage: ChatMessage = {
        id: generateUUID(),
        role: "assistant",
        parts: [{ type: "text", text: "" }],
        metadata: {
          createdAt: new Date().toISOString(),
          responseStatus: "in_progress" as const,
        },
      };

      currentAssistantMessageRef.current = assistantMessage;
      setMessages((prev) => [...prev, assistantMessage]);

      // Helper to update message state
      const updateMessage = () => {
        setMessages((prev) => {
          const newMessages = [...prev];
          newMessages[newMessages.length - 1] = { ...assistantMessage };
          return newMessages;
        });
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            // Handle [DONE] token (OpenResponses spec)
            if (line === "data: [DONE]") {
              setStatus("ready");
              if (onFinish) onFinish();
              continue;
            }

            // Skip event: lines (OpenResponses spec - type is in data payload)
            if (line.startsWith("event: ")) {
              continue;
            }

            // Skip empty lines or non-data lines
            if (!line.trim() || !line.startsWith("data: ")) continue;

            try {
              const rawEvent = JSON.parse(line.substring(6));

              // Detect event format and process accordingly
              const format = detectEventFormat(rawEvent);

              // Convert legacy events to OpenResponses format
              const events: OpenResponsesEvent[] =
                format === "legacy"
                  ? streamProcessor.process(rawEvent)
                  : [rawEvent as OpenResponsesEvent];

              // Process each OpenResponses event
              for (const eventData of events) {
                // response.in_progress - 응답 시작
                if (isResponseInProgressEvent(eventData)) {
                  assistantMessage.id = eventData.response.output[0]?.id || assistantMessage.id;
                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    responseStatus: "in_progress",
                    responseId: eventData.response.id,
                  };
                  updateMessage();
                  if (onData) {
                    onData({ type: "message_start", data: { id: assistantMessage.id } });
                  }
                }

                // response.output_text.delta - 텍스트 증분
                else if (isOutputTextDeltaEvent(eventData)) {
                  // 사고 과정 파트가 앞에 끼일 수 있어 `parts[0]` 이 텍스트라고
                  // 가정하지 않는다(`lib/reasoning-parts.ts`).
                  const textPart = textPartOf(assistantMessage.parts);
                  if (textPart) {
                    textPart.text += eventData.delta;
                  }
                  updateMessage();
                  if (onData) {
                    onData({ type: "text_delta", delta: eventData.delta });
                  }
                }

                // response.reasoning.delta / .done - 모델 사고 과정.
                // 백엔드는 줄곧 보냈고 `message.tsx` 도 그릴 줄 알았는데 이 훅이
                // 받지 않아 버려지고 있었다(chat_stream_event_types.json).
                else if (isReasoningContentDeltaEvent(eventData)) {
                  applyReasoningDelta(assistantMessage.parts, eventData.delta);
                  updateMessage();
                } else if (isReasoningContentDoneEvent(eventData)) {
                  applyReasoningDone(assistantMessage.parts, eventData.text);
                  updateMessage();
                }

                // response.output_item.added - 새 아이템 추가
                else if (isOutputItemAddedEvent(eventData)) {
                  const item = eventData.item;

                  // function_call 아이템인 경우 워크플로우 UI 업데이트
                  if (isFunctionCallItem(item)) {
                    if (!assistantMessage.metadata) {
                      assistantMessage.metadata = { createdAt: new Date().toISOString() };
                    }
                    if (!assistantMessage.metadata.function_calls) {
                      assistantMessage.metadata.function_calls = [];
                    }

                    assistantMessage.metadata.function_calls.push({
                      id: item.id,
                      call_id: item.call_id,
                      name: item.name,
                      arguments: item.arguments,
                      status: item.status,
                    });

                    // Legacy compatibility: also update workflow_agents
                    if (!assistantMessage.metadata.workflow_agents) {
                      assistantMessage.metadata.workflow_agents = [];
                    }
                    assistantMessage.metadata.workflow_agents.push({
                      agent_name: item.name,
                      node_name: item.call_id,
                      status: item.status === "in_progress" ? "input-available" : "output-available",
                    });

                    updateMessage();

                    if (onData) {
                      onData({
                        type: "tool-start",
                        data: {
                          tool_name: item.name,
                          call_id: item.call_id,
                          status: item.status,
                        },
                      });
                    }
                  }
                }

                // response.output_item.done - 아이템 완료
                else if (isOutputItemDoneEvent(eventData)) {
                  const item = eventData.item;

                  if (isFunctionCallItem(item)) {
                    // Update function_call status
                    const fc = assistantMessage.metadata?.function_calls?.find(
                      (f: any) => f.id === item.id
                    );
                    if (fc) fc.status = "completed";

                    // Update legacy workflow_agents
                    const agent = assistantMessage.metadata?.workflow_agents?.find(
                      (a: any) => a.node_name === item.call_id
                    );
                    if (agent) agent.status = "output-available";

                    updateMessage();

                    if (onData) {
                      onData({
                        type: "tool-complete",
                        data: {
                          tool_name: item.name,
                          call_id: item.call_id,
                          status: "completed",
                        },
                      });
                    }
                  }
                }

                // response.completed - 전체 완료
                else if (isResponseCompletedEvent(eventData)) {
                  const messageItem = eventData.response.output.find(
                    (item): item is MessageItem => item.type === "message"
                  );
                  if (messageItem) {
                    assistantMessage.id = messageItem.id;
                  }

                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    responseStatus: "completed",
                  };

                  updateMessage();

                  if (onData) {
                    onData({
                      type: "finish",
                      finishReason: "stop",
                      usage: {
                        promptTokens: eventData.response.usage?.input_tokens || 0,
                        completionTokens: eventData.response.usage?.output_tokens || 0,
                        totalTokens:
                          (eventData.response.usage?.input_tokens || 0) +
                          (eventData.response.usage?.output_tokens || 0),
                      },
                    });
                  }

                  setStatus("ready");
                  if (onFinish) onFinish();
                }

                // response.failed - 에러
                else if (isResponseFailedEvent(eventData)) {
                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    responseStatus: "failed",
                  };
                  updateMessage();

                  setStatus("error");
                  if (onError) {
                    onError(new Error(eventData.response.error?.message || "Response failed"));
                  }
                }

                // neos:artifact_meta - 아티팩트 메타데이터
                else if (isNeosArtifactMetaEvent(eventData)) {
                  currentArtifactKind = eventData.artifact_kind;

                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    artifact: {
                      id: eventData.artifact_id,
                      title: eventData.artifact_title,
                      kind: eventData.artifact_kind,
                    },
                  };
                  updateMessage();

                  if (onData) {
                    onData({ type: "data-id", data: eventData.artifact_id });
                    onData({ type: "data-title", data: eventData.artifact_title });
                    onData({ type: "data-kind", data: eventData.artifact_kind });
                  }
                }

                // neos:artifact_delta - 아티팩트 콘텐츠 델타
                else if (isNeosArtifactDeltaEvent(eventData)) {
                  if (onData && currentArtifactKind) {
                    const deltaType = `data-${currentArtifactKind}Delta` as const;
                    onData({ type: deltaType, data: eventData.content });
                  }
                }

                // neos:artifact_finish - 아티팩트 완료
                else if (isNeosArtifactFinishEvent(eventData)) {
                  if (onData) {
                    onData({ type: "data-finish", data: null });
                  }
                }

                // neos:workflow_progress - 워크플로우 진행 상황
                else if (isNeosWorkflowProgressEvent(eventData)) {
                  if (onData) {
                    onData({
                      type: "workflow-progress",
                      data: {
                        progress: eventData.progress_percent,
                        message: eventData.message,
                      },
                    });
                  }
                }

                // neos:harness - research harness validation and repair progress
                else if (isNeosHarnessEvent(eventData)) {
                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    harness: applyHarnessEvent(
                      assistantMessage.metadata?.harness,
                      eventData.event,
                      eventData.data
                    ),
                  };
                  updateMessage();
                  if (onData) {
                    onData({
                      type: "harness-progress",
                      data: assistantMessage.metadata.harness,
                    });
                  }
                }

                // neos:deep_analysis_started — 비동기 job 제출됨.
                //
                // 이 이벤트 뒤 챗 턴은 정상 종료한다(블로킹 없음). run_id를
                // 이 메시지에 붙여 두면 `components/deep-analysis-status.tsx`가
                // 별도 이벤트 스트림을 구독해 진행 상황을 인라인 렌더링한다.
                // 하네스 이벤트와 같은 자리·같은 방식이며, 새 메커니즘이 아니다.
                else if (isNeosDeepAnalysisStartedEvent(eventData)) {
                  // 감사 §4.5: 백엔드 응답을 그대로 믿지 않는다.
                  const started = parseDeepAnalysisStarted(eventData);
                  if (started) {
                    assistantMessage.metadata = {
                      createdAt:
                        assistantMessage.metadata?.createdAt ??
                        new Date().toISOString(),
                      ...assistantMessage.metadata,
                      deep_analysis: {
                        run_id: started.runId,
                        events_url: started.eventsUrl,
                        status: "running",
                      },
                    };
                    // 새로고침 후 진행 중 run에 다시 붙기 위한 포인터.
                    // ⚠️ 재구독 전용이다 — 이 값으로 job을 재제출하지 않는다.
                    rememberActiveRun(id, {
                      runId: started.runId,
                      assistantMessageId:
                        started.assistantMessageId ?? assistantMessage.id,
                    });
                    updateMessage();
                    if (onData) {
                      onData({
                        type: "deep-analysis-started",
                        data: { runId: started.runId },
                      });
                    }
                  } else {
                    console.error(
                      "[DeepAnalysis] deep_analysis_started 페이로드 검증 실패",
                      eventData
                    );
                  }
                }

                // neos:approval_request - workflow paused for user approval
                else if (isNeosApprovalRequestEvent(eventData)) {
                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    responseStatus: "incomplete",
                    approval_requests: eventData.pending_approvals,
                    approval_session_id: eventData.session_id,
                  };
                  updateMessage();
                  if (onData) {
                    onData({
                      type: "approval-request",
                      data: {
                        sessionId: eventData.session_id,
                        pendingApprovals: eventData.pending_approvals,
                      },
                    });
                  }
                }

                // neos:ui_frame - Phase 8 (A2UI) UIFrame 렌더링
                else if (isNeosUIFrameEvent(eventData)) {
                  assistantMessage.metadata = {
                    createdAt: assistantMessage.metadata?.createdAt || new Date().toISOString(),
                    ...assistantMessage.metadata,
                    ui_frame: eventData.ui_frame,
                  };
                  updateMessage();
                  if (onData) {
                    onData({ type: "ui-frame", data: eventData.ui_frame });
                  }
                }

                // neos:inline_viz — renderDiagram / renderChart 인라인 시각화
                else if (isNeosInlineVizEvent(eventData)) {
                  const rawEntry = {
                    id: eventData.viz_id,
                    viz_type: eventData.viz_type,
                    data: eventData.data,
                  };
                  const parseResult = inlineVizEntrySchema.safeParse(rawEntry);
                  if (!parseResult.success) {
                    console.error(
                      "[InlineViz] SSE 이벤트 데이터 검증 실패:",
                      parseResult.error.flatten()
                    );
                  } else {
                    assistantMessage.metadata = {
                      ...assistantMessage.metadata,
                      createdAt: assistantMessage.metadata?.createdAt ?? new Date().toISOString(),
                      inline_visualizations: [
                        ...(assistantMessage.metadata?.inline_visualizations ?? []),
                        parseResult.data,
                      ],
                    };
                    updateMessage();
                  }
                }

                // neos:inline_viz_error — 시각화 도구 에러 (non-fatal)
                else if (isNeosInlineVizErrorEvent(eventData)) {
                  console.warn(
                    `[InlineViz] ${eventData.tool_name} 렌더링 실패: ${eventData.error}`
                  );
                }

                // neos:graph_subagent - 설계 그래프 서브에이전트 노드의 걸음·폴드.
                // 노드별 한 줄로 쌓고, 카드(`message.tsx`)가 같은 노드의 워크플로우
                // 항목 안에 그린다.
                else if (isNeosGraphSubagentEvent(eventData)) {
                  if (!assistantMessage.metadata) {
                    assistantMessage.metadata = { createdAt: new Date().toISOString() };
                  }
                  assistantMessage.metadata.graph_subagents = applyGraphSubagentEvent(
                    assistantMessage.metadata.graph_subagents,
                    eventData
                  );
                  updateMessage();
                }
              }
            } catch (parseError) {
              console.error("Failed to parse SSE event:", line, parseError);
            }
          }
        }
      } catch (error) {
        // 정지(Stop)로 인한 abort는 에러가 아니다 — 토스트를 띄우면 안 된다.
        // 바깥 catch(sendMessage)가 abort를 정상 처리하도록 그대로 다시 던진다.
        // (예전에는 여기서 삼켜져서 바깥의 AbortError 분기가 도달 불가였다)
        if (isAbortError(error)) {
          throw error;
        }
        console.error("Stream processing error:", error);
        setStatus("error");
        if (onError && error instanceof Error) {
          onError(error);
        }
      } finally {
        if (readerRef.current) {
          try {
            await readerRef.current.cancel();
          } catch {
            // Ignore cancel errors
          }
          readerRef.current = null;
        }
        currentAssistantMessageRef.current = null;
      }
    },
    [id, onData, onFinish, onError]
  );

  /**
   * 메시지 전송
   */
  const sendMessage = useCallback(
    async (message?: any, _options?: ChatRequestOptions) => {
      // message가 없으면 무시
      if (!message) return;

      setStatus("streaming");

      // 메시지에 id가 없으면 생성
      const chatMessage: ChatMessage = {
        id: message.id || generateUUID(),
        role: message.role || "user",
        parts: message.parts || [{ type: "text", text: message.text || "" }],
        metadata: {
          createdAt: new Date().toISOString(),
          ...(message.metadata || {}),
        },
        ...message,
      };

      // 사용자 메시지 추가
      setMessages((prev) => [...prev, chatMessage]);

      // AbortController 생성
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            id,
            message: chatMessage,
            selectedChatModel,
            selectedVisibilityType,
            autonomy_level: autonomyLevel,
          }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.message || "Failed to send message");
        }

        // SSE 스트림 처리
        await processStream(response);
      } catch (error) {
        // AbortError는 DOMException이라 `instanceof Error`가 아닐 수 있는 런타임이 있다.
        // 이름 기반 판별(isAbortError)을 써야 정지가 에러로 새지 않는다.
        if (isAbortError(error)) {
          console.log("Stream aborted");
          setStatus("ready");
        } else {
          console.error("Send message error:", error);
          setStatus("error");
          if (onError && error instanceof Error) {
            onError(error);
          }
        }
      } finally {
        abortControllerRef.current = null;
      }
    },
    [id, selectedChatModel, selectedVisibilityType, autonomyLevel, processStream, onError]
  );

  /**
   * 스트리밍 중지
   */
  const stop = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStatus("ready");
  }, []);

  /**
   * 메시지 재생성
   */
  const regenerate = useCallback(
    async (options?: { messageId?: string } & ChatRequestOptions) => {
      const messageId = options?.messageId;

      if (messageId) {
        // messageId가 있으면 해당 메시지와 이후 메시지 제거
        const messageIndex = messages.findIndex((m) => m.id === messageId);
        if (messageIndex === -1) return;

        const messagesToKeep = messages.slice(0, messageIndex);
        setMessages(messagesToKeep);

        // 이전 사용자 메시지 찾기
        const lastUserMessage = [...messagesToKeep]
          .reverse()
          .find((m) => m.role === "user");

        if (lastUserMessage) {
          await sendMessage(lastUserMessage);
        }
      } else {
        // messageId가 없으면 마지막 사용자 메시지 재생성
        const lastUserMessage = [...messages]
          .reverse()
          .find((m) => m.role === "user");

        if (lastUserMessage) {
          await sendMessage(lastUserMessage);
        }
      }
    },
    [messages, sendMessage]
  );

  /**
   * 스트림 재개 — **현재는 의도적으로 no-op이다.**
   *
   * 예전 구현은 마지막 user 메시지로 `sendMessage`를 다시 호출했다. 그것은 "재개"가
   * 아니라 **재실행**이다: `POST /api/chat`이 멀티에이전트 워크플로우를 처음부터
   * 새로 돌려서 사용자 의도 없이 **다시 과금**되고 메시지가 중복 생성됐다.
   * (중단된 대화를 새로고침하기만 해도 발생 — `use-auto-resume.ts`가 호출한다)
   *
   * 진짜 재개는 백엔드의 이벤트 로그 재생(run_id + `GET /{run_id}/events`)이 있어야
   * 가능하며, 이는 Phase 3 범위다. 그 전까지는 재실행을 하지 않는 쪽이 옳다 —
   * 재개 실패는 사용자가 다시 물어보면 되지만, 무단 재과금은 되돌릴 수 없다.
   *
   * 시그니처는 `UseChatHelpers`와의 호환을 위해 유지한다.
   */
  const resumeStream = useCallback(async (_options?: ChatRequestOptions) => {
    // 의도적 no-op: 재실행으로 인한 재과금 방지. Phase 3에서 이벤트 재생으로 대체 예정.
    return;
  }, []);

  return {
    messages,
    setMessages,
    sendMessage,
    status,
    stop,
    regenerate,
    resumeStream,
  };
}
