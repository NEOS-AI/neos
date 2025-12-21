/**
 * SSE 기반 커스텀 채팅 스트리밍 훅
 * Vercel AI SDK의 useChat을 대체하여 백엔드 SSE를 직접 처리
 */

import { useCallback, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";
import type { StreamEvent } from "@/lib/stream-types";
import {
  isStreamContentEvent,
  isStreamCompleteEvent,
  isStreamErrorEvent,
  isStreamStartEvent,
  isArtifactMetaEvent,
  isArtifactDeltaEvent,
  isArtifactFinishEvent,
} from "@/lib/stream-types";
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
  const currentAssistantMessageRef = useRef<ChatMessage | null>(null);

  /**
   * SSE 스트림 처리
   */
  const processStream = useCallback(
    async (response: Response) => {
      if (!response.body) {
        throw new Error("No response body");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // 현재 아티팩트 kind 추적 (artifact_meta에서 설정됨)
      let currentArtifactKind: "text" | "code" | "sheet" | "image" | null = null;

      // 어시스턴트 메시지 초기화
      const assistantMessage: ChatMessage = {
        id: generateUUID(),
        role: "assistant",
        parts: [{ type: "text", text: "" }],
        metadata: {
          createdAt: new Date().toISOString(),
        },
      };

      currentAssistantMessageRef.current = assistantMessage;

      // 메시지 목록에 추가 (빈 메시지로 시작)
      setMessages((prev) => [...prev, assistantMessage]);

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.trim() || !line.startsWith("data: ")) continue;

            try {
              const eventData: StreamEvent = JSON.parse(line.substring(6));

              // 시작 이벤트
              if (isStreamStartEvent(eventData)) {
                // 메시지 ID 업데이트
                assistantMessage.id = eventData.message_id;
                if (onData) {
                  onData({ type: "message_start", data: { id: eventData.message_id } });
                }
              }
              // 컨텐츠 델타 이벤트
              else if (isStreamContentEvent(eventData)) {
                // 델타만 추가 (누적 아님!)
                const textPart = assistantMessage.parts[0];
                if (textPart.type === "text") {
                  textPart.text += eventData.content;
                }

                // 메시지 업데이트
                setMessages((prev) => {
                  const newMessages = [...prev];
                  newMessages[newMessages.length - 1] = { ...assistantMessage };
                  return newMessages;
                });

                if (onData) {
                  onData({ type: "text_delta", delta: eventData.content });
                }
              }
              // 완료 이벤트
              else if (isStreamCompleteEvent(eventData)) {
                // 메시지 ID 최종 확인
                assistantMessage.id = eventData.message_id;

                // 최종 메시지 업데이트
                setMessages((prev) => {
                  const newMessages = [...prev];
                  newMessages[newMessages.length - 1] = { ...assistantMessage };
                  return newMessages;
                });

                if (onData) {
                  onData({
                    type: "finish",
                    finishReason: "stop",
                    usage: {
                      promptTokens: eventData.metadata.prompt_tokens || 0,
                      completionTokens: eventData.metadata.completion_tokens || 0,
                      totalTokens: eventData.metadata.total_tokens || 0,
                    },
                  });
                }

                setStatus("ready");
                if (onFinish) {
                  onFinish();
                }
              }
              // 에러 이벤트
              else if (isStreamErrorEvent(eventData)) {
                const error = new Error(eventData.error);
                setStatus("error");
                if (onError) {
                  onError(error);
                }
              }
              // 아티팩트 메타데이터 이벤트
              else if (isArtifactMetaEvent(eventData)) {
                // 현재 아티팩트 kind 저장
                currentArtifactKind = eventData.artifact_kind;

                // 어시스턴트 메시지의 metadata에 아티팩트 정보 저장
                assistantMessage.metadata = {
                  createdAt:
                    assistantMessage.metadata?.createdAt ||
                    new Date().toISOString(),
                  artifact: {
                    id: eventData.artifact_id,
                    title: eventData.artifact_title,
                    kind: eventData.artifact_kind,
                  },
                };

                // 메시지 업데이트
                setMessages((prev) => {
                  const newMessages = [...prev];
                  newMessages[newMessages.length - 1] = { ...assistantMessage };
                  return newMessages;
                });

                if (onData) {
                  // artifact_id를 data-id로 변환
                  onData({ type: "data-id", data: eventData.artifact_id });
                  // artifact_title을 data-title로 변환
                  onData({ type: "data-title", data: eventData.artifact_title });
                  // artifact_kind를 data-kind로 변환
                  onData({ type: "data-kind", data: eventData.artifact_kind });
                }
              }
              // 아티팩트 델타 이벤트
              else if (isArtifactDeltaEvent(eventData)) {
                if (onData && currentArtifactKind) {
                  // 현재 아티팩트 kind에 따라 적절한 delta 타입으로 변환
                  const deltaType = `data-${currentArtifactKind}Delta` as const;
                  onData({ type: deltaType, data: eventData.content });
                }
              }
              // 아티팩트 완료 이벤트
              else if (isArtifactFinishEvent(eventData)) {
                if (onData) {
                  onData({ type: "data-finish", data: null });
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
