/**
 * 메시지 구조 변환 유틸리티
 *
 * Vercel AI SDK의 parts 구조 ↔ 백엔드의 content 문자열 변환
 */

/**
 * Parts 배열을 백엔드 content 문자열로 변환
 *
 * @param parts - Vercel AI SDK parts 배열
 * @returns 백엔드 content 문자열
 */
export function convertPartsToContent(parts: any[]): string {
  if (!parts || parts.length === 0) {
    return "";
  }

  // parts 배열에서 text 타입만 추출하여 문자열로 변환
  const textParts = parts
    .filter((part) => part.type === "text")
    .map((part) => part.text);

  return textParts.join("\n");
}

/**
 * 백엔드 content 문자열을 Parts 배열로 변환
 *
 * @param content - 백엔드 content 문자열
 * @param attachments - 첨부파일 배열 (선택)
 * @returns Vercel AI SDK parts 배열
 */
export function convertContentToParts(
  content: string,
  attachments: any[] = []
): any[] {
  const parts: any[] = [];

  // 기본 텍스트 part
  if (content) {
    parts.push({
      type: "text",
      text: content,
    });
  }

  // 첨부파일이 있으면 추가
  if (attachments && attachments.length > 0) {
    for (const attachment of attachments) {
      if (attachment.type === "image") {
        parts.push({
          type: "image",
          image: attachment.url || attachment.data,
        });
      } else if (attachment.type === "file") {
        parts.push({
          type: "file",
          data: attachment.url || attachment.data,
          mimeType: attachment.mimeType || attachment.mime_type,
        });
      }
    }
  }

  return parts;
}

/**
 * 백엔드 메시지를 Vercel AI SDK 메시지 형식으로 변환
 *
 * @param backendMessage - 백엔드 메시지 객체
 * @returns Vercel AI SDK 메시지 객체
 */
export function convertBackendMessageToSDK(backendMessage: any): any {
  // 백엔드에 parts가 있으면 우선 사용, 없으면 content에서 변환
  const parts =
    backendMessage.parts ||
    convertContentToParts(
      backendMessage.content,
      backendMessage.attachments
    );

  return {
    id: backendMessage.message_id,
    role: backendMessage.role,
    parts,
    attachments: backendMessage.attachments || [],
    createdAt: backendMessage.created_at,
  };
}

/**
 * Vercel AI SDK 메시지를 백엔드 형식으로 변환
 *
 * @param sdkMessage - Vercel AI SDK 메시지 객체
 * @returns 백엔드 메시지 객체
 */
export function convertSDKMessageToBackend(sdkMessage: any): any {
  const content = convertPartsToContent(sdkMessage.parts);

  return {
    role: sdkMessage.role,
    content,
    parts: sdkMessage.parts, // parts도 함께 저장 (백엔드가 지원하는 경우)
    attachments: sdkMessage.attachments || [],
  };
}

/**
 * Tool calls를 parts로 변환
 *
 * @param toolCalls - 백엔드 tool_calls 배열
 * @returns parts 배열에 추가할 tool-call parts
 */
export function convertToolCallsToParts(toolCalls: any[]): any[] {
  if (!toolCalls || toolCalls.length === 0) {
    return [];
  }

  return toolCalls.map((toolCall) => ({
    type: "tool-call",
    toolCallId: toolCall.id || toolCall.tool_call_id,
    toolName: toolCall.name || toolCall.function?.name,
    args: toolCall.arguments || toolCall.function?.arguments,
  }));
}

/**
 * Tool results를 parts로 변환
 *
 * @param toolResults - 백엔드 tool_results 배열
 * @returns parts 배열에 추가할 tool-result parts
 */
export function convertToolResultsToParts(toolResults: any[]): any[] {
  if (!toolResults || toolResults.length === 0) {
    return [];
  }

  return toolResults.map((toolResult) => ({
    type: "tool-result",
    toolCallId: toolResult.tool_call_id,
    toolName: toolResult.tool_name || toolResult.name,
    result: toolResult.result || toolResult.output,
  }));
}

/**
 * 전체 메시지 배열 변환 (백엔드 → SDK)
 *
 * @param backendMessages - 백엔드 메시지 배열
 * @returns Vercel AI SDK 메시지 배열
 */
export function convertBackendMessagesToSDK(backendMessages: any[]): any[] {
  return backendMessages.map((msg) => {
    const parts = [];

    // content를 parts로 변환
    if (msg.content) {
      parts.push(...convertContentToParts(msg.content, msg.attachments));
    }

    // tool_calls를 parts에 추가
    if (msg.tool_calls) {
      parts.push(...convertToolCallsToParts(msg.tool_calls));
    }

    // tool_results를 parts에 추가
    if (msg.tool_results) {
      parts.push(...convertToolResultsToParts(msg.tool_results));
    }

    // 백엔드에 이미 parts가 있으면 우선 사용
    if (msg.parts) {
      return {
        id: msg.message_id,
        role: msg.role,
        parts: msg.parts,
        attachments: msg.attachments || [],
        createdAt: msg.created_at,
      };
    }

    return {
      id: msg.message_id,
      role: msg.role,
      parts,
      attachments: msg.attachments || [],
      createdAt: msg.created_at,
    };
  });
}
