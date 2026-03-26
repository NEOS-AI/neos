/**
 * SSE 기반 커스텀 채팅 스트리밍 훅
 * Vercel AI SDK의 useChat을 대체하여 백엔드 SSE를 직접 처리
 *
 * Supports both legacy Neos events and OpenResponses specification events.
 * @see https://www.openresponses.org/specification
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";
import type { OpenResponsesEvent, MessageItem } from "@/lib/stream-types";
import {
  // OpenResponses type guards
  isResponseInProgressEvent,
  isResponseCompletedEvent,
  isResponseFailedEvent,
  isOutputItemAddedEvent,
  isOutputItemDoneEvent,
  isOutputTextDeltaEvent,
  isNeosArtifactMetaEvent,
  isNeosArtifactDeltaEvent,
  isNeosArtifactFinishEvent,
  isNeosWorkflowProgressEvent,
  isNeosUIFrameEvent,
  isFunctionCallItem,
} from "@/lib/stream-types";
import {
  createStreamProcessor,
  detectEventFormat,
} from "@/lib/adapters/stream-adapter";
import { generateUUID } from "@/lib/utils";
import type { VisibilityType } from "@/components/visibility-selector";
import type { ChatModel } from "@/lib/ai/models";
import type { ChatStatus } from "ai";

export interface ChatRequestOptions {
  // Vercel AI SDK와 호환되는 옵션
  [key: string]: any;
}

export interface UseChatStreamOptions {
  id: string;
  initialMessages: ChatMessage[];
  selectedChatModel: ChatModel["id"];
  selectedVisibilityType: VisibilityType;
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
                  const textPart = assistantMessage.parts[0];
                  if (textPart.type === "text") {
                    textPart.text += eventData.delta;
                  }
                  updateMessage();
                  if (onData) {
                    onData({ type: "text_delta", delta: eventData.delta });
                  }
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
              }
            } catch (parseError) {
              console.error("Failed to parse SSE event:", line, parseError);
            }
          }
        }
      } catch (error) {
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
    [onData, onFinish, onError]
  );

  /**
   * 메시지 전송
   */
  const sendMessage = useCallback(
    async (message?: any, options?: ChatRequestOptions) => {
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
        if (error instanceof Error && error.name === "AbortError") {
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
    [id, selectedChatModel, selectedVisibilityType, processStream, onError]
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
   * 스트림 재개 (자동 재개용)
   */
  const resumeStream = useCallback(
    async (options?: ChatRequestOptions) => {
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "user") {
        await sendMessage(lastMessage);
      }
    },
    [messages, sendMessage]
  );

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
