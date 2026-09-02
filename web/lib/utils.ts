import type {
  CoreAssistantMessage,
  CoreToolMessage,
  UIMessage,
  UIMessagePart,
} from 'ai';
import { type ClassValue, clsx } from 'clsx';
import { formatISO } from 'date-fns';
import { twMerge } from 'tailwind-merge';
import type { DBMessage, Document } from '@/lib/db/schema';
import { deepAnalysisFromMessageMetadata } from './deep-analysis/metadata';
import { applyHarnessMetadata } from './harness/metadata';
import { ChatSDKError, type ErrorCode } from './errors';
import type { ChatMessage, ChatTools, CustomUIDataTypes } from './types';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fetcher = async (url: string) => {
  const response = await fetch(url);

  if (!response.ok) {
    const { code, cause } = await response.json();
    throw new ChatSDKError(code as ErrorCode, cause);
  }

  return response.json();
};

export async function fetchWithErrorHandlers(
  input: RequestInfo | URL,
  init?: RequestInit,
) {
  try {
    const response = await fetch(input, init);

    if (!response.ok) {
      const { code, cause } = await response.json();
      throw new ChatSDKError(code as ErrorCode, cause);
    }

    return response;
  } catch (error: unknown) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      throw new ChatSDKError('offline:chat');
    }

    throw error;
  }
}

export function getLocalStorage(key: string) {
  if (typeof window !== 'undefined') {
    return JSON.parse(localStorage.getItem(key) || '[]');
  }
  return [];
}

export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

type ResponseMessageWithoutId = CoreToolMessage | CoreAssistantMessage;
type ResponseMessage = ResponseMessageWithoutId & { id: string };

export function getMostRecentUserMessage(messages: UIMessage[]) {
  const userMessages = messages.filter((message) => message.role === 'user');
  return userMessages.at(-1);
}

export function getDocumentTimestampByIndex(
  documents: Document[],
  index: number,
) {
  if (!documents) { return new Date(); }
  if (index > documents.length) { return new Date(); }

  return documents[index].createdAt;
}

export function getTrailingMessageId({
  messages,
}: {
  messages: ResponseMessage[];
}): string | null {
  const trailingMessage = messages.at(-1);

  if (!trailingMessage) { return null; }

  return trailingMessage.id;
}

export function sanitizeText(text: string) {
  return text.replace('<has_function_call>', '');
}

export function convertToUIMessages(messages: DBMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role as 'user' | 'assistant' | 'system',
    parts: message.parts as UIMessagePart<CustomUIDataTypes, ChatTools>[],
    metadata: {
      createdAt: formatISO(message.createdAt),
    },
  }));
}

export function convertBackendMessagesToUI(
  backendMessages: any[]
): ChatMessage[] {
  return backendMessages.map((msg) => {
    const metadata: any = {
      createdAt: msg.created_at,
      sequenceNumber: msg.sequence_number,
      modelName: msg.model_name,
      totalTokens: msg.total_tokens,
    };

    // 백엔드 metadata에서 artifact 정보 추출 및 변환
    if (msg.metadata && msg.metadata.artifact) {
      metadata.artifact = {
        id: msg.metadata.artifact.id,
        title: msg.metadata.artifact.title,
        kind: msg.metadata.artifact.kind,
      };
    }

    // 나머지 metadata 필드도 포함
    if (msg.metadata) {
      Object.keys(msg.metadata).forEach((key) => {
        if (key !== 'artifact' && !metadata[key]) {
          metadata[key] = msg.metadata[key];
        }
      });
    }

    // 백엔드 키(`deep_analysis_run_id`)를 프론트 모양(`deep_analysis`)으로 옮긴다.
    // 이 브리지가 없으면 새로고침 후 진행 카드가 통째로 사라진다 — 강등 경고만이
    // 아니라 카드 자체가. 자세한 근거는 `lib/deep-analysis/metadata.ts` 주석 참조.
    const deepAnalysis = deepAnalysisFromMessageMetadata(msg.metadata);
    if (deepAnalysis) {
      metadata.deep_analysis = deepAnalysis;
    }

    // `harness` 는 백엔드가 같은 이름으로 쓰므로 위 통과 경로가 이미 복사해
    // 뒀다 -- **검증하지 않은 채로.** 스키마에 맞으면 검증된 값으로 바꾸고,
    // 아니면 지운다. 지우지 않으면 통과 경로가 남긴 원본이 그대로 컴포넌트에
    // 도달하고, 잘못된 모양 다섯 중 하나는 렌더를 던져 그 메시지 전체가
    // 에러 카드로 대체된다(`lib/harness/metadata.ts` 주석).
    applyHarnessMetadata(metadata, msg.metadata);

    return {
      id: msg.message_id,
      role: msg.role as 'user' | 'assistant' | 'system',
      parts: [
        {
          type: 'text' as const,
          text: msg.content,
        },
      ] as UIMessagePart<CustomUIDataTypes, ChatTools>[],
      metadata,
    };
  });
}

export function getTextFromMessage(message: ChatMessage | UIMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => (part as { type: 'text'; text: string}).text)
    .join('');
}
